"""This PC's link identity and the phones allowed to use it.

``~/.neovarch/remote/link.json`` (mode 0600)::

    {"pc_key": <X25519 private, b64url>, "room_key": <relay room secret>,
     "devices": {<device_id>: {"pk", "name", "added", "last_seen", "via"}},
     "revoked": [<device_id>, …]}

Pairing codes live in memory only and expire (they are what the QR carries for
pairing over the relay or Bluetooth; LAN pairing uses the gateway token).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from neovarch.paths import neovarch_home

from .crypto import KeyPair, b64d, b64e, device_id, pc_id_for_room_key

PAIR_CODE_TTL = 30 * 60
PAIR_CODE_REFRESH = 10 * 60  # hand out a fresh code when the current one is older than this
MAX_DEVICES = 20


def default_path() -> Path:
    return neovarch_home() / "remote" / "link.json"


class LinkStore:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = Path(path) if path else default_path()
        self.clock = clock
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
    def devices(self) -> list[dict]:
        return sorted(({"id": k, **{x: v.get(x) for x in ("name", "added", "last_seen", "via")}}
                       for k, v in self._data["devices"].items()), key=lambda d: d.get("added") or 0)

    def device_for_key(self, pk: bytes) -> dict | None:
        did = device_id(pk)
        d = self._data["devices"].get(did)
        if d and hmac.compare_digest(b64d(d["pk"]), pk):
            return {"id": did, **d}
        return None

    def is_revoked(self, pk: bytes) -> bool:
        return device_id(pk) in self._data["revoked"]

    def enroll(self, pk: bytes, name: str, via: str) -> dict:
        """Allow a device key (idempotent). Un-revokes a key enrolled again on purpose."""
        if len(pk) != 32:
            raise ValueError("bad device key")
        did = device_id(pk)
        with self._lock:
            devs = self._data["devices"]
            if did not in devs and len(devs) >= MAX_DEVICES:
                oldest = min(devs, key=lambda k: devs[k].get("last_seen") or devs[k].get("added") or 0)
                devs.pop(oldest)
            now = int(self.clock())
            prev = devs.get(did, {})
            devs[did] = {"pk": b64e(pk), "name": (name or "HP").strip()[:64] or "HP",
                         "added": prev.get("added", now), "last_seen": now, "via": via}
            if did in self._data["revoked"]:
                self._data["revoked"].remove(did)
            self._save()
        return {"id": did, **devs[did]}

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
            self._save()
        return found

    # ------------------------------------------------------------ pair codes --
    def pair_code(self) -> tuple[str, float]:
        """Current pairing code for the QR (new one when the last is older than 10 min)."""
        now = self.clock()
        with self._lock:
            self._codes = {c: exp for c, exp in self._codes.items() if exp > now}
            for c, exp in sorted(self._codes.items(), key=lambda kv: -kv[1]):
                if exp - PAIR_CODE_TTL + PAIR_CODE_REFRESH > now:
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
