"""Chat attachments: uploads staged per session, and how they reach the model.

Files land under ``~/.neovarch/uploads/<session>/<id>-<name>`` with a sidecar
``<id>.json`` (name, mime, size, kind). A chat message references them by id:

* images go to the model as OpenAI-compatible ``image_url`` content parts with a
  ``data:`` URL when the selected model can see images (``model.vision`` in
  config, ``vision: true`` on a custom endpoint, or a known vision model name);
  otherwise the agent gets a clear notice plus the file path;
* other files reach the agent as their path plus extracted text for
  text/markdown/code and PDF (via ``pdftotext`` when installed).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from neovarch.paths import neovarch_home

MAX_BYTES = 25 * 1024 * 1024
TEXT_LIMIT = 20_000          # characters of extracted text per file sent to the model
IMAGE_HISTORY = 3            # images are re-sent for at most the last N user turns that had them
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_ID = re.compile(r"^[a-f0-9]{12}$")

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".html", ".htm", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".rb",
    ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".dart", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".php", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".lua", ".r", ".m", ".scala", ".vue", ".svelte", ".tex",
    ".bib", ".log", ".env.example", ".gradle", ".proto", ".graphql",
}
IMAGE_MIME = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/heic", "image/heif"}

# Model ids that accept image input on OpenAI-compatible endpoints (substring match).
VISION_HINTS = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision", "gpt-5", "o1", "o3", "o4", "chatgpt-4o",
    "claude-3", "claude-sonnet-4", "claude-opus-4", "claude-haiku-4", "claude-4",
    "gemini", "gemma-3", "gemma3", "llava", "bakllava", "-vl", "vl-", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "qwen3-vl", "pixtral", "vision", "llama-3.2-11b", "llama-3.2-90b", "llama-4", "minicpm-v", "glm-4v",
    "glm-4.5v", "internvl", "moondream", "grok-2-vision", "grok-4", "mistral-medium-3", "mistral-small-3.1",
    "phi-3.5-vision", "phi-4-multimodal", "kimi-vl", "step-1v", "yi-vision",
    # Xiaomi MiMo v2.x reads images (mimo-v2.5, mimo-v2.6, flash / free / pro).
    "mimo-v2", "mimo-vl",
)

# The models Neovarch ships as defaults (9Router): always vision-capable, whatever
# the hint list or the provider's metadata says.
DEFAULT_VISION_MODELS = ("oc/mimo-v2.6-flash-free", "mimo/mimo-v2.6-pro")

# Vision flags read from a provider's ``GET /models`` (9Router passes through what
# its upstreams declare). Filled by models.ModelCatalog.fetch; id → True/False.
MODEL_VISION_META: dict[str, bool] = {}


def vision_from_meta(row: dict) -> bool | None:
    """What one ``/models`` row says about image input, or None when it says nothing."""
    if not isinstance(row, dict):
        return None
    for key in ("vision", "supports_vision", "supportsVision"):
        if isinstance(row.get(key), bool):
            return row[key]
    caps = row.get("capabilities")
    if isinstance(caps, dict):
        for key in ("vision", "image_input", "images"):
            if isinstance(caps.get(key), bool):
                return caps[key]
    if isinstance(caps, list) and caps:
        return any(str(c).lower() in ("vision", "image", "image_input") for c in caps)
    arch = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
    for mods in (row.get("input_modalities"), row.get("modalities"), arch.get("input_modalities")):
        if isinstance(mods, list) and mods:
            return any(str(m).lower() in ("image", "images", "vision") for m in mods)
        if isinstance(mods, dict) and isinstance(mods.get("input"), list):
            return any(str(m).lower() in ("image", "images") for m in mods["input"])
    modality = str(arch.get("modality") or row.get("modality") or "")
    if "->" in modality:
        return "image" in modality.split("->", 1)[0]
    return None


def remember_model_meta(rows: list[dict]) -> None:
    """Record the vision flags a ``/models`` listing declares (unknown rows are skipped)."""
    for row in rows or []:
        mid = str((row or {}).get("id") or "")
        flag = vision_from_meta(row)
        if mid and flag is not None:
            MODEL_VISION_META[mid] = flag


class UploadError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def root() -> Path:
    return neovarch_home() / "uploads"


def _session_dir(session_id: str) -> Path:
    sid = _SAFE.sub("_", session_id or "_unsorted").strip(". ") or "_unsorted"
    return root() / sid[:80]


def safe_name(name: str) -> str:
    from urllib.parse import unquote
    raw = str(name or "")
    if "%" in raw:
        raw = unquote(raw)
    base = Path(raw.replace("\\", "/")).name
    base = _SAFE.sub("_", base).strip(" .") or "file"
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:100] + dot + ext[:15]) if dot else base[:120]
    return base


def kind_of(name: str, mime: str) -> str:
    if (mime or "").lower() in IMAGE_MIME or Path(name).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic"):
        return "image"
    return "file"


def guess_mime(name: str, given: str | None = None, head: bytes = b"") -> str:
    sniffed = sniff_image(head)
    if sniffed:
        return sniffed
    if given and given != "application/octet-stream":
        return given.split(";")[0].strip().lower()
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def sniff_image(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def public(meta: dict) -> dict:
    """What clients see: never the bytes, always a download URL."""
    return {"id": meta["id"], "name": meta["name"], "mime": meta["mime"], "size": meta["size"],
            "kind": meta["kind"], "session_id": meta.get("session_id"), "path": meta["path"],
            "created_at": meta.get("created_at"), "url": f"/api/uploads/{meta['id']}",
            # "user" = sent by the person (phone/desktop composer), "agent" = sent by the
            # agent with send_file. Same schema both ways, so any transport can carry it.
            "origin": meta.get("origin") or "user"}


class UploadStore:
    """Staged uploads on disk. Index lookups scan the per-session folders (small)."""

    def save_bytes(self, session_id: str, name: str, data: bytes, mime: str | None = None) -> dict:
        if len(data) > MAX_BYTES:
            raise UploadError(f"File terlalu besar (maks {MAX_BYTES // (1024 * 1024)} MB).", 413)
        if not data:
            raise UploadError("File kosong.")
        w = self.writer(session_id, name, mime)
        w.write(data)
        return w.finish(head=data[:16])

    def writer(self, session_id: str, name: str, mime: str | None = None) -> "_Writer":
        return _Writer(self, session_id, name, mime)

    def get(self, uid: str) -> dict | None:
        if not _ID.match(uid or ""):
            return None
        base = root()
        if not base.is_dir():
            return None
        for meta_path in base.glob(f"*/{uid}.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            p = Path(meta.get("path", ""))
            # Only bytes that live inside the uploads store are ever served; a sidecar
            # that points elsewhere (edited, or from an older layout) is ignored.
            try:
                inside = p.resolve().is_relative_to(base.resolve())
            except (OSError, ValueError):
                inside = False
            if inside and p.is_file():
                return meta
        return None

    def list(self, session_id: str) -> list[dict]:
        d = _session_dir(session_id)
        out = []
        for meta_path in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(out, key=lambda m: m.get("created_at") or 0)

    def delete(self, uid: str) -> bool:
        meta = self.get(uid)
        if not meta:
            return False
        for p in (Path(meta["path"]), Path(meta["path"]).parent / f"{uid}.json"):
            try:
                p.unlink()
            except OSError:
                pass
        return True

    def import_path(self, session_id: str, src: Path, extra: dict | None = None) -> dict:
        """Stage a copy of a host file (desktop drag-drop / paste of a saved file, or a
        file the agent sends to the chat with ``extra={"origin": "agent", ...}``)."""
        src = Path(src).expanduser()
        if not src.is_file():
            raise UploadError(f"File tidak ditemukan: {src}", 404)
        if src.stat().st_size > MAX_BYTES:
            raise UploadError(f"File terlalu besar (maks {MAX_BYTES // (1024 * 1024)} MB).", 413)
        with src.open("rb") as fh:
            head = fh.read(16)
        w = self.writer(session_id, src.name, mimetypes.guess_type(src.name)[0])
        with src.open("rb") as fh:
            shutil.copyfileobj(fh, w.fh)
        w.size = src.stat().st_size
        return w.finish(head=head, extra=extra)


class _Writer:
    """Streams one upload to disk, enforcing the size cap as bytes arrive."""

    def __init__(self, store: UploadStore, session_id: str, name: str, mime: str | None):
        self.store = store
        self.id = secrets.token_hex(6)
        self.session_id = session_id or ""
        self.name = safe_name(name)
        self.given_mime = mime
        self.dir = _session_dir(self.session_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{self.id}-{self.name}"
        self.fh = self.path.open("wb")
        self.size = 0

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > MAX_BYTES:
            self.abort()
            raise UploadError(f"File terlalu besar (maks {MAX_BYTES // (1024 * 1024)} MB).", 413)
        self.fh.write(chunk)

    def abort(self) -> None:
        try:
            self.fh.close()
            self.path.unlink()
        except OSError:
            pass

    def finish(self, head: bytes = b"", extra: dict | None = None) -> dict:
        self.fh.close()
        if self.size == 0:
            self.abort()
            raise UploadError("File kosong.")
        mime = guess_mime(self.name, self.given_mime, head)
        meta = {"id": self.id, "name": self.name, "mime": mime, "size": self.size,
                "kind": kind_of(self.name, mime), "session_id": self.session_id,
                "path": str(self.path), "created_at": time.time(), "origin": "user", **(extra or {})}
        (self.dir / f"{self.id}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta


# ------------------------------------------------------------- to the model ---

def supports_vision(cfg: dict, endpoint: dict) -> bool:
    from neovarch import config as cfgmod
    explicit = cfgmod.get_path(cfg, "model.vision", None)
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, str) and explicit.lower() in ("true", "false", "yes", "no", "1", "0"):
        return explicit.lower() in ("true", "yes", "1")
    prov = str(endpoint.get("provider") or "")
    if prov.startswith("custom:"):
        try:
            from neovarch import providers
            spec = providers.find_endpoint(cfg, prov.split(":", 1)[1]) or {}
            if isinstance(spec.get("vision"), bool):
                return spec["vision"]
        except Exception:
            pass
    raw = str(endpoint.get("model") or "")
    model = raw.lower()
    if raw in DEFAULT_VISION_MODELS or MODEL_VISION_META.get(raw) is True:
        return True
    if any(h in model for h in VISION_HINTS):
        return True
    # Only the provider's own metadata can still say yes for an unknown name.
    bare = raw.split("/", 1)[-1]
    return MODEL_VISION_META.get(bare) is True


def extract_text(path: Path, mime: str = "") -> str | None:
    """Readable text of a file for the agent, or None when it is not text-like."""
    suffix = path.suffix.lower()
    if suffix == ".pdf" or mime == "application/pdf":
        exe = shutil.which("pdftotext")
        if not exe:
            return None
        try:
            out = subprocess.run([exe, "-layout", "-q", str(path), "-"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = out.stdout.decode("utf-8", "replace").strip()
        return text or None
    if suffix in TEXT_EXT or mime.startswith("text/") or mime in ("application/json", "application/xml"):
        try:
            raw = path.read_bytes()[: TEXT_LIMIT * 4]
        except OSError:
            return None
        if b"\x00" in raw[:4096]:
            return None
        return raw.decode("utf-8", "replace")
    return None


def data_url(meta: dict) -> str | None:
    try:
        raw = Path(meta["path"]).read_bytes()
    except OSError:
        return None
    return f"data:{meta.get('mime') or 'image/png'};base64,{base64.b64encode(raw).decode('ascii')}"


def file_block(meta: dict) -> str:
    """The text a non-image (or vision-less image) attachment contributes."""
    p = Path(meta["path"])
    head = f"[Lampiran: {meta['name']} ({meta.get('mime') or 'file'}, {meta['size']} B) — path: {p}]"
    if meta.get("kind") == "image":
        return head
    text = extract_text(p, meta.get("mime") or "")
    if text is None:
        return head + "\n(Isi tidak bisa diekstrak sebagai teks; baca file dari path di atas bila perlu.)"
    cut = text[:TEXT_LIMIT]
    more = "\n…(dipotong, baca selengkapnya dari path di atas)" if len(text) > TEXT_LIMIT else ""
    return f"{head}\n```\n{cut}\n```{more}"


VISION_NOTICE = ("Model yang dipilih tidak mendukung input gambar, jadi gambar dikirim sebagai path file. "
                 "Pilih model vision (mis. gpt-4o, Gemini, Claude, Qwen-VL) atau set model.vision: true.")


def user_wire(m: dict, vision: bool, send_images: bool) -> dict:
    """Build the wire form of a stored user message that carries attachments."""
    atts: list[dict] = [a for a in (m.get("attachments") or []) if isinstance(a, dict)]
    text = str(m.get("content") or "")
    blocks: list[str] = []
    images: list[dict] = []
    for a in atts:
        if a.get("kind") == "image" and vision and send_images:
            url = data_url(a)
            if url:
                images.append({"type": "image_url", "image_url": {"url": url}})
                continue
        blocks.append(file_block(a))
        if a.get("kind") == "image" and not vision:
            blocks.append("(Catatan: " + VISION_NOTICE + ")")
    full = "\n\n".join([t for t in [text, *blocks] if t]) or ("Apa yang ada di gambar ini?" if images else "")
    if images:
        return {"role": "user", "content": [{"type": "text", "text": full}, *images]}
    return {"role": "user", "content": full}


_FILE_REF = re.compile(r"@file:(\"[^\"]+\"|'[^']+'|\S+)")


def expand_file_refs(text: str, cwd: Path) -> str:
    """Desktop composers put ``@file:<path>`` refs in the text; append the text of each
    referenced file once so the model can read it without a tool round-trip."""
    blocks = []
    seen: set[str] = set()
    for m in _FILE_REF.finditer(text or ""):
        ref = m.group(1).strip("\"'").rstrip(".,;)")
        if ref in seen:
            continue
        seen.add(ref)
        p = Path(ref).expanduser()
        if not p.is_absolute():
            p = cwd / p
        if not p.is_file() or p.stat().st_size > MAX_BYTES:
            continue
        mime = mimetypes.guess_type(p.name)[0] or ""
        body = extract_text(p, mime)
        if body is None:
            continue
        blocks.append(f"[Isi @file:{ref}]\n```\n{body[:TEXT_LIMIT]}\n```")
        if len(blocks) >= 8:
            break
    return text if not blocks else text + "\n\n" + "\n\n".join(blocks)
