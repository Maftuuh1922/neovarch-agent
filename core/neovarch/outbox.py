"""Files the agent sends back into the chat (PC -> phone / desktop).

Before this, the agent could only answer "screenshot saved at /home/.../shot.png":
assistant messages never carried attachments, so the phone had nothing to show.

Now the agent calls the ``send_file`` tool (and, as a safety net, fresh files it
names in its final answer are picked up too). Each file is COPIED into the
uploads store with ``origin: "agent"`` — the same schema phone->PC uploads use
(``id, name, mime, size, kind, url``) — and stored on the assistant message as
``attachments``. Clients fetch the bytes with ``GET /api/uploads/<id>``: a lookup
by a 12-hex id, never by path, so the download endpoint cannot be turned into an
arbitrary file read. Any transport that carries the REST API (LAN gateway, a
relay later) carries attachments without changes.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from neovarch import uploads as upmod
from neovarch.paths import check_path, neovarch_home

MAX_FILES_PER_TURN = 10
AUTO_MAX = 4  # files picked up from the final answer when send_file was not used

# Never sent, even when asked: keys and credentials.
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store"}
_SECRET_NAMES = {".env", ".netrc", ".pgpass", ".git-credentials", ".npmrc", ".pypirc", "credentials",
                 "credentials.json", "auth.json", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                 "known_hosts", "authorized_keys", "shadow", "passwd"}
_SECRET_SUFFIX = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".keystore", ".jks")

# What the final-answer safety net may attach: things a person wants on the phone.
AUTO_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".docx", ".doc", ".pptx",
            ".ppt", ".xlsx", ".xls", ".csv", ".zip", ".mp4", ".mp3", ".wav", ".odt", ".odp", ".html", ".txt", ".md"}

# Absolute paths in text: POSIX (/a/b.png, ~/a.png) and Windows (C:\a\b.png, C:/a/b.png).
_PATH_RE = re.compile(
    r"""(?:(?<=^)|(?<=[\s`'"(\[<:=]))"""
    r"""((?:~|[A-Za-z]:)?[\\/][^\s`'"<>|*?\]\)]*?\.[A-Za-z0-9]{1,5})"""
    r"""(?=$|[\s`'")\]<>,;!]|\.(?:\s|$))""",
    re.MULTILINE,
)


class SendError(ValueError):
    pass


def refuse_reason(p: Path) -> str | None:
    """Why a file must not leave the PC, or None when it may be sent."""
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        resolved = p
    parts = {s.lower() for s in resolved.parts}
    name = resolved.name.lower()
    if parts & _SECRET_DIRS or name in _SECRET_NAMES or name.startswith(".env") or name.endswith(_SECRET_SUFFIX):
        return "berkas kunci/kredensial tidak boleh dikirim ke obrolan"
    home = neovarch_home()
    try:
        home = home.resolve()
    except OSError:
        pass
    if resolved.parent == home:  # config.yaml, .env, tokens of the core itself
        return "berkas konfigurasi Neovarch tidak boleh dikirim ke obrolan"
    if _under(resolved, home) and resolved.relative_to(home).parts[:1] == ("sessions",):
        return "berkas sesi Neovarch tidak boleh dikirim ke obrolan"
    return None


def _under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def resolve(raw: str, cwd: Path) -> Path:
    raw = str(raw or "").strip().strip("`'\"")
    if not raw:
        raise SendError("path wajib diisi")
    if raw.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse
        raw = unquote(urlparse(raw).path)
        if sys.platform == "win32" and re.match(r"^/[A-Za-z]:", raw):
            raw = raw[1:]
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = Path(cwd) / p
    return p


def stage(store: upmod.UploadStore, session_id: str, raw: str, cwd: Path) -> dict:
    """Copy one host file into the chat's uploads as an agent attachment."""
    p = resolve(raw, cwd)
    check_path(p)
    if p.is_dir():
        raise SendError(f"{p} adalah folder; kirim berkasnya satu per satu atau zip dulu")
    if not p.is_file():
        raise SendError(f"berkas tidak ditemukan: {p}")
    why = refuse_reason(p)
    if why:
        raise SendError(why)
    try:
        return store.import_path(session_id, p, extra={"origin": "agent", "source_path": str(p)})
    except upmod.UploadError as exc:
        raise SendError(str(exc)) from exc


def paths_in_text(text: str, cwd: Path, since: float) -> list[Path]:
    """Fresh files (modified during this turn) that the final answer names by path."""
    out: list[Path] = []
    seen: set[str] = set()
    for m in _PATH_RE.finditer(text or ""):
        raw = m.group(1).rstrip(".,;:")
        if Path(raw).suffix.lower() not in AUTO_EXT:
            continue
        try:
            p = resolve(raw, cwd)
            key = os.path.normcase(str(p.resolve()))
            if key in seen or not p.is_file():
                continue
            st = p.stat()
        except (OSError, SendError, RuntimeError):
            continue
        seen.add(key)
        if st.st_mtime + 2 < since or st.st_size > upmod.MAX_BYTES or refuse_reason(p):
            continue
        out.append(p)
        if len(out) >= AUTO_MAX:
            break
    return out


def wants_file(user_text: str) -> bool:
    """The person asked for a file/screenshot to be sent here (Indonesian or English)."""
    t = (user_text or "").lower()
    return bool(re.search(r"\b(kirim\w*|kasih|send|share|bagikan|lampir\w*|attach\w*|upload)\b", t)) or \
        bool(re.search(r"\b(ke sini|kesini|ke hp|ke chat|di sini|disini|here)\b", t))


def now() -> float:
    return time.time()
