"""End-to-end encryption between the phone and this PC (link protocol v1).

Used by every non-LAN transport (relay, Bluetooth). The relay only ever sees
ciphertext. Primitives: X25519, HKDF-SHA256, ChaCha20-Poly1305 (IETF).

Handshake (two plaintext frames, then everything is encrypted)::

    phone → PC   {"t":"hello","v":1,"dev":<pk_dev>,"eph":<e_phone>}
    PC → phone   {"t":"welcome","v":1,"pc":<pk_pc>,"eph":<e_pc>}

    th   = SHA256("neovarch-link/1" | pk_dev | pk_pc | e_phone | e_pc)
    ikm  = X25519(dev, pc) | X25519(e_phone, e_pc)      # static-static + ephemeral-ephemeral
    keys = HKDF-SHA256(ikm, salt=th, info="neovarch-link/1 keys", 64)
    k_up = keys[:32]   (phone → PC)     k_down = keys[32:]   (PC → phone)

The static-static term authenticates both ends (the phone pinned ``pk_pc`` from
the QR, the PC knows the device keys it enrolled); the ephemeral term gives each
connection fresh keys (forward secrecy). Data frames are ``{"t":"d","c":<b64>}``;
the nonce is a per-direction counter (4 zero bytes + 8-byte big-endian) that is
never sent: the transports are ordered, so a replayed, dropped or reordered
frame fails authentication and the session is closed. AAD = ``th``.

Plaintext = 1 flag byte (0 = last part, 1 = more parts follow) + a UTF-8 JSON
chunk; messages larger than :data:`CHUNK` are split.

All binary values are base64url without padding.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

PROTOCOL = 1
LABEL = b"neovarch-link/1"
INFO = b"neovarch-link/1 keys"
CHUNK = 48 * 1024
MAX_MESSAGE = 24 * 1024 * 1024  # reassembled plaintext cap


class LinkError(Exception):
    """Bad frame, failed authentication or a protocol violation: close the link."""


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64d(s: str) -> bytes:
    if not isinstance(s, str):
        raise LinkError("expected base64 text")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (ValueError, TypeError) as exc:
        raise LinkError("bad base64") from exc


@dataclass
class KeyPair:
    private: bytes
    public: bytes

    @classmethod
    def generate(cls) -> "KeyPair":
        return cls.from_private(X25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))

    @classmethod
    def from_private(cls, raw: bytes) -> "KeyPair":
        sk = X25519PrivateKey.from_private_bytes(raw)
        return cls(raw, sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))

    def dh(self, peer_public: bytes) -> bytes:
        if len(peer_public) != 32:
            raise LinkError("bad public key")
        shared = X25519PrivateKey.from_private_bytes(self.private).exchange(X25519PublicKey.from_public_bytes(peer_public))
        if shared == b"\x00" * 32:
            raise LinkError("low-order public key")
        return shared


def device_id(pk_dev: bytes) -> str:
    """Stable short id of a device key (shown in Settings → Remote)."""
    return b64e(hashlib.sha256(pk_dev).digest())[:16]


def transcript(pk_dev: bytes, pk_pc: bytes, e_phone: bytes, e_pc: bytes) -> bytes:
    return hashlib.sha256(LABEL + pk_dev + pk_pc + e_phone + e_pc).digest()


def derive(ikm: bytes, th: bytes) -> tuple[bytes, bytes]:
    okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=th, info=INFO).derive(ikm)
    return okm[:32], okm[32:]


def _nonce(counter: int) -> bytes:
    return b"\x00\x00\x00\x00" + counter.to_bytes(8, "big")


@dataclass
class Session:
    """One encrypted direction pair. ``role`` is "pc" or "phone"."""

    role: str
    k_send: bytes
    k_recv: bytes
    th: bytes
    peer: bytes  # the other side's static public key
    send_ctr: int = 0
    recv_ctr: int = 0
    _parts: list[bytes] = field(default_factory=list)
    _size: int = 0

    @classmethod
    def for_pc(cls, k_up: bytes, k_down: bytes, th: bytes, peer: bytes) -> "Session":
        return cls("pc", k_down, k_up, th, peer)

    @classmethod
    def for_phone(cls, k_up: bytes, k_down: bytes, th: bytes, peer: bytes) -> "Session":
        return cls("phone", k_up, k_down, th, peer)

    def _seal(self, plaintext: bytes) -> str:
        if self.send_ctr >= 2**64 - 1:
            raise LinkError("counter exhausted")
        ct = ChaCha20Poly1305(self.k_send).encrypt(_nonce(self.send_ctr), plaintext, self.th)
        self.send_ctr += 1
        return json.dumps({"t": "d", "c": b64e(ct)}, separators=(",", ":"))

    def encrypt(self, message: dict | str) -> list[str]:
        """Wire frames (one or more) for one inner message."""
        text = message if isinstance(message, str) else json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        data = text.encode("utf-8")
        if len(data) > MAX_MESSAGE:
            raise LinkError("message too large")
        chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
        return [self._seal((b"\x01" if i < len(chunks) - 1 else b"\x00") + c) for i, c in enumerate(chunks)]

    def decrypt(self, frame: str | dict) -> dict | None:
        """Feed one wire frame; returns the inner message once complete, else None."""
        f = frame if isinstance(frame, dict) else _loads(frame)
        if f.get("t") != "d":
            raise LinkError("expected a data frame")
        try:
            pt = ChaCha20Poly1305(self.k_recv).decrypt(_nonce(self.recv_ctr), b64d(f.get("c", "")), self.th)
        except LinkError:
            raise
        except Exception as exc:  # InvalidTag: tampered, replayed or reordered
            raise LinkError("authentication failed") from exc
        self.recv_ctr += 1
        if not pt:
            raise LinkError("empty frame")
        self._parts.append(pt[1:])
        self._size += len(pt) - 1
        if self._size > MAX_MESSAGE:
            raise LinkError("message too large")
        if pt[0] == 1:
            return None
        if pt[0] != 0:
            raise LinkError("bad flag")
        data = b"".join(self._parts)
        self._parts, self._size = [], 0
        msg = _loads(data.decode("utf-8", errors="strict"))
        return msg


def _loads(text: str) -> dict:
    try:
        v = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise LinkError("bad json") from exc
    if not isinstance(v, dict):
        raise LinkError("expected an object")
    return v


# ---------------------------------------------------------------- handshake --

def hello(dev: KeyPair, eph: KeyPair) -> dict:
    return {"t": "hello", "v": PROTOCOL, "dev": b64e(dev.public), "eph": b64e(eph.public)}


def pc_accept(pc: KeyPair, hello_frame: dict, eph: KeyPair | None = None) -> tuple[dict, Session]:
    """PC side: answer a hello. Returns (welcome frame, session). Raises LinkError."""
    if hello_frame.get("t") != "hello" or hello_frame.get("v") != PROTOCOL:
        raise LinkError("unsupported hello")
    pk_dev, e_phone = b64d(hello_frame.get("dev", "")), b64d(hello_frame.get("eph", ""))
    if len(pk_dev) != 32 or len(e_phone) != 32:
        raise LinkError("bad key length")
    eph = eph or KeyPair.generate()
    th = transcript(pk_dev, pc.public, e_phone, eph.public)
    k_up, k_down = derive(pc.dh(pk_dev) + eph.dh(e_phone), th)
    welcome = {"t": "welcome", "v": PROTOCOL, "pc": b64e(pc.public), "eph": b64e(eph.public)}
    return welcome, Session.for_pc(k_up, k_down, th, pk_dev)


def phone_finish(dev: KeyPair, eph: KeyPair, pinned_pc: bytes, welcome: dict) -> Session:
    """Phone side (used by tests and tooling; the app does this in Dart)."""
    if welcome.get("t") != "welcome" or welcome.get("v") != PROTOCOL:
        raise LinkError("unsupported welcome")
    pk_pc, e_pc = b64d(welcome.get("pc", "")), b64d(welcome.get("eph", ""))
    if pk_pc != pinned_pc:
        raise LinkError("PC key does not match the pairing")
    th = transcript(dev.public, pk_pc, eph.public, e_pc)
    k_up, k_down = derive(dev.dh(pk_pc) + eph.dh(e_pc), th)
    return Session.for_phone(k_up, k_down, th, pk_pc)


def random_token(n: int = 32) -> str:
    return b64e(os.urandom(n))


def pc_id_for_room_key(room_key: str) -> str:
    """Relay room id: base64url(sha256(room_key))[:22] (the relay checks the same)."""
    return b64e(hashlib.sha256(room_key.encode("utf-8")).digest())[:22]
