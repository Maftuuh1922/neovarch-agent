"""This PC's link identity and the phones allowed to use it.

``~/.neovarch/remote/link.json`` (mode 0600)::

    {"pc_key": <X25519 private, b64url>, "room_key": <relay room secret>,
     "devices": {<device_id>: {"pk", "name", "added", "last_seen", "via", "token_hash"?}},
     "revoked": [<device_id>, …], "expired": [<device_id>, …], "pair_epoch": <unix>}

Pairing codes live in memory only, are short-lived (10 min) and one-time: a
successful pairing burns the code (they are what the QR carries for pairing
over the relay or Bluetooth). LAN pairing exchanges the QR's short-lived pair
token for a per-device session token (``nvd_…``, only its SHA-256 is stored);
pairing again rotates it. ``pair_epoch`` is bumped on every successful pairing
so any pair token minted before it stops working (one-time QR).

A paired device that has not been seen for ``remote.pairing_idle_days`` (default
30, 0 = never) is revoked automatically and told "sesi kedaluwarsa".
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from neovarch.paths import neovarch_home

from .crypto import KeyPair, b64d, b64e, device_id, pc_id_for_room_key

PAIR_CODE_TTL = 10 * 60
PAIR_CODE_MIN_LEFT = 2 * 60  # hand out a fresh code when the current one has less than this left
MAX_DEVICES = 20
DEFAULT_IDLE_DAYS = 30
SESSION_TOKEN_PREFIX = "nvd_"
EXPIRED_MESSAGE = "Sesi kedaluwarsa, pasangkan ulang"


_IDLE_CACHE: list = [0.0, float(DEFAULT_IDLE_DAYS)]  # [read at, value]


def configured_idle_days() -> float:
    """``remote.pairing_idle_days`` from config.yaml (default 30; 0 or less = never expire).

    Re-read at most every 30 s (it is consulted on every authenticated request)."""
    now = time.monotonic()
    if _IDLE_CACHE[0] and now - _IDLE_CACHE[0] < 30:
        return _IDLE_CACHE[1]
    try:
        from neovarch.config import load_config
        v = float((load_config().get("remote") or {}).get("pairing_idle_days", DEFAULT_IDLE_DAYS))
    except Exception:
        v = float(DEFAULT_IDLE_DAYS)
    _IDLE_CACHE[0], _IDLE_CACHE[1] = now, v
    return v


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_path() -> Path:
    return neovarch_home() / "remote" / "link.json"


class LinkStore:
    def __init__(self, path: Path | None = None, clock=time.time, idle_days=None):
        self.path = Path(path) if path else default_path()
        self.clock = clock
        # number, or a callable returning one (re-read so a config change applies live)
        self._idle_days = idle_days if idle_days is not None else configured_idle_days
        self._lock = threading.Lock()
        self._codes: dict[str, float] = {}  # code -> expiry
        self._data = self._load()

    # ------------------------------------------------------------ persistence --
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            data = {}
        changed = False
        try:
            KeyPair.from_private(b64d(data.get("pc_key", "")))
        except Exception:
            data["pc_key"] = b64e(KeyPair.generate().private)
            changed = True
        if not isinstance(data.get("room_key"), str) or len(data["room_key"]) < 32:
            data["room_key"] = b64e(os.urandom(32))
            changed = True
        if not isinstance(data.get("devices"), dict):
            data["devices"] = {}
            changed = True
        if not isinstance(data.get("revoked"), list):
            data["revoked"] = []
            changed = True
        if not isinstance(data.get("expired"), list):
            data["expired"] = []
            changed = True
        if not isinstance(data.get("expired_tokens"), dict):
            data["expired_tokens"] = {}  # device_id -> token hash, so an expired token gets a clear answer
            changed = True
        if not isinstance(data.get("pair_epoch"), (int, float)):
            data["pair_epoch"] = 0
            changed = True
        self._data = data
        if changed:
            self._save()
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def reload(self) -> None:
        with self._lock:
            self._data = self._load()

    # --------------------------------------------------------------- identity --
    @property
    def pc_keys(self) -> KeyPair:
        return KeyPair.from_private(b64d(self._data["pc_key"]))

    @property
    def pc_public(self) -> str:
        return b64e(self.pc_keys.public)

    @property
    def room_key(self) -> str:
        return self._data["room_key"]

    @property
    def pc_id(self) -> str:
        return pc_id_for_room_key(self.room_key)

    # ---------------------------------------------------------------- devices --
    @property
    def idle_days(self) -> float:
        v = self._idle_days() if callable(self._idle_days) else self._idle_days
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(DEFAULT_IDLE_DAYS)

    def _idle_seconds(self) -> float | None:
        d = self.idle_days
        return d * 86400 if d > 0 else None

    def _expires_at(self, d: dict) -> int | None:
        idle = self._idle_seconds()
        if idle is None:
            return None
        return int((d.get("last_seen") or d.get("added") or 0) + idle)

    def expire_idle(self) -> list[str]:
        """Revoke every device idle longer than ``idle_days``; returns their ids."""
        idle = self._idle_seconds()
        if idle is None:
            return []
        now = self.clock()
        with self._lock:
            devs = self._data["devices"]
            gone = [k for k, v in devs.items() if now - (v.get("last_seen") or v.get("added") or 0) > idle]
            if not gone:
                return []
            for k in gone:
                rec = devs.pop(k, None) or {}
                if rec.get("token_hash"):
                    self._data["expired_tokens"][k] = rec["token_hash"]
                if k not in self._data["expired"]:
                    self._data["expired"].append(k)
                if k in self._data["revoked"]:
                    self._data["revoked"].remove(k)
            self._data["expired"] = self._data["expired"][-200:]
            keep = set(self._data["expired"])
            self._data["expired_tokens"] = {k: v for k, v in self._data["expired_tokens"].items() if k in keep}
            self._save()
        return gone

    def devices(self) -> list[dict]:
        self.expire_idle()
        out = []
        for k, v in self._data["devices"].items():
            d = {"id": k, **{x: v.get(x) for x in ("name", "added", "last_seen", "via")}}
            d["created_at"] = v.get("added")
            d["expires_at"] = self._expires_at(v)
            out.append(d)
        return sorted(out, key=lambda d: d.get("added") or 0)

    def _public(self, did: str, d: dict) -> dict:
        return {"id": did, **{k: v for k, v in d.items() if k != "token_hash"},
                "created_at": d.get("added"), "expires_at": self._expires_at(d)}

    def device_for_key(self, pk: bytes) -> dict | None:
        self.expire_idle()
        did = device_id(pk)
        d = self._data["devices"].get(did)
        if d and hmac.compare_digest(b64d(d["pk"]), pk):
            return self._public(did, d)
        return None

    def is_revoked(self, pk: bytes) -> bool:
        return device_id(pk) in self._data["revoked"]

    def is_expired(self, pk: bytes) -> bool:
        return device_id(pk) in self._data["expired"]

    def denial_reason(self, pk: bytes) -> str:
        """Why an unknown key is refused: ``expired``, ``revoked`` or ``unknown_device``."""
        if self.is_expired(pk):
            return "expired"
        if self.is_revoked(pk):
            return "revoked"
        return "unknown_device"

    def enroll(self, pk: bytes, name: str, via: str, *, issue_token: bool = False) -> dict:
        """Allow a device key (idempotent). Un-revokes a key enrolled again on purpose.

        With ``issue_token`` (LAN pairing) a fresh per-device session token is minted
        and returned once as ``session_token``; any previous token of this device
        stops working (re-pairing rotates it).
        """
        if len(pk) != 32:
            raise ValueError("bad device key")
        did = device_id(pk)
        token = None
        with self._lock:
            devs = self._data["devices"]
            if did not in devs and len(devs) >= MAX_DEVICES:
                oldest = min(devs, key=lambda k: devs[k].get("last_seen") or devs[k].get("added") or 0)
                devs.pop(oldest)
            now = int(self.clock())
            prev = devs.get(did, {})
            rec = {"pk": b64e(pk), "name": (name or "HP").strip()[:64] or "HP",
                   "added": prev.get("added", now), "last_seen": now, "via": via}
            if issue_token:
                token = SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
                rec["token_hash"] = _hash_token(token)
            elif prev.get("token_hash"):
                rec["token_hash"] = prev["token_hash"]
            devs[did] = rec
            for lst in ("revoked", "expired"):
                if did in self._data[lst]:
                    self._data[lst].remove(did)
            self._data["expired_tokens"].pop(did, None)
            self._save()
        out = self._public(did, devs[did])
        if token:
            out["session_token"] = token
        return out

    def check_session_token(self, token: str) -> tuple[str, dict | None]:
        """``("ok", device)``, ``("expired", None)`` or ``("invalid", None)``.

        A valid token refreshes the device's ``last_seen`` (throttled)."""
        if not isinstance(token, str) or not token.startswith(SESSION_TOKEN_PREFIX):
            return "invalid", None
        h = _hash_token(token)
        self.expire_idle()
        for did, d in list(self._data["devices"].items()):
            th = d.get("token_hash")
            if th and hmac.compare_digest(th, h):
                self.touch(did, "lan")
                return "ok", self._public(did, d)
        for th in self._data["expired_tokens"].values():
            if isinstance(th, str) and hmac.compare_digest(th, h):
                return "expired", None
        return "invalid", None

    def touch(self, did: str, via: str) -> None:
        d = self._data["devices"].get(did)
        if not d:
            return
        now = int(self.clock())
        if now - int(d.get("last_seen") or 0) < 60 and d.get("via") == via:
            return
        with self._lock:
            d["last_seen"], d["via"] = now, via
            self._save()

    def revoke(self, did: str) -> bool:
        with self._lock:
            found = self._data["devices"].pop(did, None) is not None
            if did not in self._data["revoked"]:
                self._data["revoked"].append(did)
                self._data["revoked"] = self._data["revoked"][-200:]
            if did in self._data["expired"]:
                self._data["expired"].remove(did)
            self._data["expired_tokens"].pop(did, None)
            self._save()
        return found

    # ------------------------------------------------------------ pair codes --
    def pair_code(self) -> tuple[str, float]:
        """Current one-time pairing code for the QR (fresh when the last has < 2 min left or was used)."""
        now = self.clock()
        with self._lock:
            self._codes = {c: exp for c, exp in self._codes.items() if exp > now}
            for c, exp in sorted(self._codes.items(), key=lambda kv: -kv[1]):
                if exp - now >= PAIR_CODE_MIN_LEFT:
                    return c, exp
            code = secrets.token_urlsafe(12)
            self._codes[code] = now + PAIR_CODE_TTL
            return code, self._codes[code]

    def check_pair_code(self, code: str) -> bool:
        now = self.clock()
        for c, exp in list(self._codes.items()):
            if exp > now and isinstance(code, str) and hmac.compare_digest(c.encode(), code.encode()):
                return True
        return False

    def consume_pair_code(self, code: str) -> bool:
        """Check and burn a pairing code (one-time). Also ends every outstanding pair token."""
        now = self.clock()
        with self._lock:
            hit = None
            for c, exp in list(self._codes.items()):
                if exp > now and isinstance(code, str) and hmac.compare_digest(c.encode(), code.encode()):
                    hit = c
            if hit is None:
                return False
            self._codes.clear()
        self.mark_paired()
        return True

    # ------------------------------------------------------------ pair tokens --
    @property
    def pair_epoch(self) -> float:
        return float(self._data.get("pair_epoch") or 0)

    def mark_paired(self) -> None:
        """A pairing succeeded: QR pair tokens minted up to now and the shown code stop working."""
        with self._lock:
            self._codes.clear()
            self._data["pair_epoch"] = max(self.clock(), self.pair_epoch + 0.001)
            self._save()

    def pair_token_fresh(self, issued_at: float) -> bool:
        return float(issued_at) > self.pair_epoch
