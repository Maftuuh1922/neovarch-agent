"""Vision fallback: let a text-only model "see" attached images.

When the chat's model cannot take image input, each attached image is sent to a
vision-capable model (found automatically on the local 9Router and the other
configured endpoints) with a compact prompt; its structured Indonesian
description (contents, verbatim text/OCR, numbers/tables, UI elements) is
injected into the user turn for the main model, labelled with the model that
read it. The ``image_ask`` tool lets a text-only model ask that vision model a
specific question about an image.

Config (``~/.neovarch/config.yaml``)::

    vision:
      fallback: auto          # auto (default) | off
      fallback_model: ""      # pin a model id, e.g. "gm/gemini-2.5-flash" (optional)
      fallback_provider: ""   # where that model lives: 9router | custom:<id> (optional)
      timeout_s: 60           # per image
      concurrency: 1          # images read at once (1-2)

Detection: a model counts as vision when its ``/models`` metadata says so
(``capabilities.vision``, or ``image`` in ``input_modalities`` /
``architecture.input_modalities`` / ``modalities``), else when its id matches
``uploads.VISION_HINTS``. Model lists are cached for an hour; descriptions are
cached on disk by image sha256 under ``~/.neovarch/vision-cache``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import aiohttp

from neovarch import config as cfgmod
from neovarch.logs import log as _log
from neovarch.paths import neovarch_home

CATALOG_TTL_S = 3600.0        # a good model list is reused for an hour
CATALOG_FAIL_TTL_S = 60.0     # an unreachable endpoint is retried after a minute
LIST_TIMEOUT_S = 6.0
DEFAULT_TIMEOUT_S = 60.0
MAX_CONCURRENCY = 2
MAX_DESCRIPTION = 6000        # characters of one description injected into the turn
PROMPT_VERSION = 1

DESCRIBE_PROMPT = (
    "Kamu membaca gambar untuk asisten lain yang tidak bisa melihat gambar. Jawab dalam Bahasa Indonesia, "
    "ringkas tapi lengkap, dengan format:\n"
    "Isi: <apa yang ada di gambar, 1-3 kalimat>\n"
    "Teks: <SEMUA teks yang terlihat, verbatim, baris demi baris; tulis '-' bila tidak ada>\n"
    "Angka/tabel: <angka penting, tabel sebagai baris 'kolom | kolom'; '-' bila tidak ada>\n"
    "UI: <elemen antarmuka (tombol, menu, kolom, pesan error) bila ini tangkapan layar; '-' bila bukan>\n"
    "Jangan menebak hal yang tidak terlihat."
)
ASK_PROMPT = ("Jawab pertanyaan tentang gambar ini dalam Bahasa Indonesia, singkat dan tepat. Kutip teks yang "
              "terlihat secara verbatim bila relevan. Jangan menebak hal yang tidak terlihat.\n\nPertanyaan: ")

# Cheap/fast model ids are preferred when no price is published.
_CHEAP = ("flash", "mini", "lite", "nano", "haiku", "small", "-vl", "vl-", "free", "fast", "turbo", "8b", "7b",
          "11b", "12b", "4b")
_PRICEY = ("opus", "-pro", "pro-", "ultra", "large", "max", "thinking", "reasoning")
_IMAGE_WORDS = ("image", "vision")


@dataclass
class VisionModel:
    model: str
    provider: str           # 9router | custom:<id> | the active provider
    base_url: str
    api_key: str = ""
    headers: dict | None = None
    verify_ssl: bool = True
    source: str = "hints"   # metadata | hints | config
    price: float | None = None

    def endpoint(self) -> dict[str, Any]:
        return {"model": self.model, "provider": self.provider, "base_url": self.base_url,
                "api_key": self.api_key, "headers": self.headers or {}, "verify_ssl": self.verify_ssl}


# ------------------------------------------------------------------ config ---

def settings(cfg: dict) -> dict[str, Any]:
    raw = cfgmod.get_path(cfg, "vision", {}) or {}
    return raw if isinstance(raw, dict) else {}


def enabled(cfg: dict) -> bool:
    mode = settings(cfg).get("fallback", "auto")
    if isinstance(mode, bool):
        return mode
    return str(mode or "auto").strip().lower() not in ("off", "false", "no", "0", "disabled", "none")


def _timeout(cfg: dict) -> float:
    try:
        return max(0.1, min(float(settings(cfg).get("timeout_s") or DEFAULT_TIMEOUT_S), 600.0))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


def _concurrency(cfg: dict) -> int:
    try:
        return max(1, min(int(settings(cfg).get("concurrency") or 1), MAX_CONCURRENCY))
    except (TypeError, ValueError):
        return 1


def submit_notice(cfg: dict) -> str:
    """What prompt.submit tells the client right away about an image the model cannot see."""
    from neovarch import uploads
    if not enabled(cfg):
        return uploads.VISION_NOTICE
    return ("Model aktif tidak mendukung input gambar; Neovarch mencoba membacanya dengan model vision "
            "cadangan (lihat pemberitahuan berikutnya).")


# --------------------------------------------------------------- detection ---

def _has_image(values: Any) -> bool | None:
    if isinstance(values, dict):
        values = values.get("input") or values.get("in")
    if isinstance(values, str):
        values = re.split(r"[\s,+>-]+", values.split("->")[0])
    if not isinstance(values, (list, tuple)):
        return None
    return any(str(v).lower() in _IMAGE_WORDS for v in values)


def vision_from_metadata(row: dict) -> bool | None:
    """True/False when the /models row says whether it takes images, None when it is silent."""
    caps = row.get("capabilities")
    if isinstance(caps, dict):
        for key in ("vision", "image_input", "imageInput", "supports_vision"):
            if isinstance(caps.get(key), bool):
                return caps[key]
        got = _has_image(caps.get("input_modalities") or caps.get("modalities"))
        if got is not None:
            return got
    elif isinstance(caps, list):
        if any(str(c).lower() in ("vision", "image", "image_input") for c in caps):
            return True
    arch = row.get("architecture")
    candidates = [row.get("input_modalities"), row.get("modalities"),
                  arch.get("input_modalities") if isinstance(arch, dict) else None,
                  arch.get("modality") if isinstance(arch, dict) else None]
    for c in candidates:
        got = _has_image(c)
        if got is not None:
            return got
    for key in ("vision", "supports_vision"):
        if isinstance(row.get(key), bool):
            return row[key]
    return None


def vision_from_hints(model_id: str) -> bool:
    from neovarch import uploads
    mid = str(model_id or "").lower()
    return any(h in mid for h in uploads.VISION_HINTS)


def classify(row: dict) -> tuple[bool, str]:
    """(is_vision, "metadata" | "hints") for one /models row."""
    meta = vision_from_metadata(row)
    if meta is not None:
        return meta, "metadata"
    return vision_from_hints(str(row.get("id") or "")), "hints"


def _price(row: dict) -> float | None:
    pricing = row.get("pricing")
    if not isinstance(pricing, dict):
        return None
    total = 0.0
    seen = False
    for key in ("prompt", "input", "image", "completion", "output"):
        try:
            total += float(pricing[key])
            seen = True
        except (KeyError, TypeError, ValueError):
            continue
    return total if seen else None


# ----------------------------------------------------------------- catalog ---

_CATALOG: dict[str, tuple[float, list[dict]]] = {}   # base_url -> (fetched_at, rows)


def reset() -> None:
    """Forget cached model lists (tests, or after the user changed endpoints)."""
    _CATALOG.clear()


async def _fetch_rows(base_url: str, api_key: str = "", headers: dict | None = None,
                      verify_ssl: bool = True) -> list[dict] | None:
    h = {"Accept": "application/json", **(headers or {})}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=LIST_TIMEOUT_S)) as s:
            async with s.get(base_url.rstrip("/") + "/models", headers=h, ssl=None if verify_ssl else False) as r:
                if r.status >= 400:
                    return None
                data = await r.json(content_type=None)
    except Exception:  # noqa: BLE001 - an unreachable endpoint just has no models
        return None
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(data, dict) and rows is None:
        rows = data.get("models")
    out = []
    for row in rows or []:
        if isinstance(row, str):
            row = {"id": row}
        if isinstance(row, dict) and (row.get("id") or row.get("name")):
            row = dict(row)
            row["id"] = str(row.get("id") or row.get("name"))
            out.append(row)
    return out


async def _rows(base_url: str, **kw: Any) -> list[dict]:
    now = time.time()
    hit = _CATALOG.get(base_url)
    if hit and now - hit[0] < (CATALOG_TTL_S if hit[1] else CATALOG_FAIL_TTL_S):
        return hit[1]
    rows = await _fetch_rows(base_url, **kw)
    _CATALOG[base_url] = (now, rows or [])
    return rows or []


def _sources(cfg: dict, active: dict | None) -> list[dict]:
    """Endpoints to look for vision models on: the local 9Router, every custom endpoint,
    and the chat's own endpoint (deduplicated by base URL)."""
    from neovarch import providers, router9
    out: list[dict] = []
    seen: set[str] = set()

    def add(src: dict) -> None:
        base = str(src.get("base_url") or "").rstrip("/")
        if base and base not in seen:
            seen.add(base)
            out.append({**src, "base_url": base})

    add({"provider": router9.PROVIDER, "base_url": router9.base_url(cfg), "api_key": router9.api_key(),
         "headers": {}, "verify_ssl": True, "spec": None})
    for spec in cfg.get("custom_providers") or []:
        if not isinstance(spec, dict) or not spec.get("base_url"):
            continue
        add({"provider": f"custom:{providers._eid(spec)}", "base_url": str(spec["base_url"]),
             "api_key": cfgmod.secret(str(spec.get("key_env") or "")), "headers": cfgmod.endpoint_headers(spec),
             "verify_ssl": not bool(spec.get("allow_insecure_tls")), "spec": spec})
    if active and active.get("base_url"):
        add({"provider": str(active.get("provider") or "custom"), "base_url": str(active["base_url"]),
             "api_key": str(active.get("api_key") or ""), "headers": active.get("headers") or {},
             "verify_ssl": active.get("verify_ssl", True), "spec": None})
    return out


async def vision_models(cfg: dict, active: dict | None = None) -> list[VisionModel]:
    """Every vision-capable model reachable right now, in discovery order."""
    found: list[VisionModel] = []
    for src in _sources(cfg, active):
        spec = src.get("spec") or {}
        rows = await _rows(src["base_url"], api_key=src["api_key"], headers=src["headers"],
                           verify_ssl=src["verify_ssl"])
        if not rows and spec:  # offline custom endpoint: fall back to its saved list
            rows = [{"id": m} for m in (spec.get("models") or []) if m]
            if spec.get("model") and spec["model"] not in [r["id"] for r in rows]:
                rows.insert(0, {"id": spec["model"]})
        flagged = {str(m) for m in (spec.get("vision_models") or [])} if spec else set()
        for row in rows:
            kind = str(row.get("kind") or row.get("type") or "").lower()
            if kind and kind not in ("llm", "chat", "imagetotext", "image-to-text", "model"):
                continue  # embeddings, TTS, image generation, web search combos
            mid = str(row["id"])
            if mid in flagged or (spec.get("vision") is True and mid == spec.get("model")):
                ok, how = True, "config"
            else:
                ok, how = classify(row)
            if ok:
                found.append(VisionModel(model=mid, provider=src["provider"], base_url=src["base_url"],
                                         api_key=src["api_key"], headers=src["headers"],
                                         verify_ssl=src["verify_ssl"], source=how, price=_price(row)))
    return found


def rank(models: list[VisionModel], active: dict | None = None) -> list[VisionModel]:
    """Cheapest/fastest first: published price when known, then models whose metadata
    confirms vision, then name hints (flash/mini/lite/vl/free...); 9Router models that
    are cooling down after a rate limit go last."""
    from neovarch import router9
    active_model = str((active or {}).get("model") or "")

    def score(i_m: tuple[int, VisionModel]) -> tuple:
        i, m = i_m
        mid = m.model.lower()
        cheap = sum(1 for w in _CHEAP if w in mid)
        pricey = sum(1 for w in _PRICEY if w in mid)
        cooling = m.provider == router9.PROVIDER and router9.cooldown_left(m.model) > 0
        # confirmed by metadata/config beats a name guess; then cheap/fast names
        return (cooling, m.price is None, m.price or 0.0, m.source == "hints", -(cheap - 2 * pricey), i)

    pool = [m for m in models if m.model != active_model] or list(models)
    return [m for _, m in sorted(enumerate(pool), key=score)]


async def pick_fallback(cfg: dict, active: dict | None = None) -> VisionModel | None:
    """The model that reads images for a text-only chat, or None (off / none available)."""
    if not enabled(cfg):
        return None
    s = settings(cfg)
    pinned = str(s.get("fallback_model") or "").strip()
    models = await vision_models(cfg, active)
    if pinned:
        want_prov = str(s.get("fallback_provider") or "").strip()
        for m in models:
            if m.model == pinned and (not want_prov or m.provider == want_prov):
                return VisionModel(**{**m.__dict__, "source": "config"})
        # Not listed (or listed without vision metadata): trust the user's pick.
        for src in _sources(cfg, active):
            if want_prov and src["provider"] != want_prov:
                continue
            rows = _CATALOG.get(src["base_url"], (0, []))[1]
            if want_prov or any(r.get("id") == pinned for r in rows):
                return VisionModel(model=pinned, provider=src["provider"], base_url=src["base_url"],
                                   api_key=src["api_key"], headers=src["headers"], verify_ssl=src["verify_ssl"],
                                   source="config")
        if active and active.get("base_url"):
            return VisionModel(model=pinned, provider=str(active.get("provider") or "custom"),
                               base_url=str(active["base_url"]), api_key=str(active.get("api_key") or ""),
                               headers=active.get("headers") or {}, verify_ssl=active.get("verify_ssl", True),
                               source="config")
        return None
    ranked = rank(models, active)
    return ranked[0] if ranked else None


# ------------------------------------------------------------------- cache ---

def cache_dir() -> Path:
    return neovarch_home() / "vision-cache"


def image_sha(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def cache_get(key: str) -> dict | None:
    try:
        data = json.loads(_cache_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != PROMPT_VERSION or not data.get("text"):
        return None
    return data


def cache_put(key: str, model: str, text: str) -> None:
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps({"v": PROMPT_VERSION, "model": model, "text": text,
                                                "created_at": time.time()}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# -------------------------------------------------------------- the queue ---

_SEMS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]]" = \
    weakref.WeakKeyDictionary()


def _queue(limit: int) -> asyncio.Semaphore:
    """One process-wide queue per event loop, so images from all chats are read a few at a time."""
    loop = asyncio.get_running_loop()
    cur = _SEMS.get(loop)
    if cur is None or cur[0] != limit:
        cur = (limit, asyncio.Semaphore(limit))
        _SEMS[loop] = cur
    return cur[1]


async def _ask_model(vm: VisionModel, meta: dict, prompt: str, timeout_s: float) -> str:
    from neovarch import uploads
    from neovarch.llm import LLMError, stream_chat
    url = uploads.data_url(meta)
    if not url:
        raise LLMError("gambar tidak bisa dibaca dari disk")
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                             {"type": "image_url", "image_url": {"url": url}}]}]
    comp = await asyncio.wait_for(
        stream_chat(base_url=vm.base_url, api_key=vm.api_key, model=vm.model, messages=messages,
                    extra_headers=vm.headers or None, verify_ssl=vm.verify_ssl, timeout_s=timeout_s),
        timeout=timeout_s)
    text = (comp.text or "").strip()
    if not text:
        raise LLMError("model vision membalas kosong")
    return text


def _local_ocr(path: Path) -> str | None:
    """Text from RapidOCR when it is installed (optional, offline)."""
    engine_cls = None
    try:
        from rapidocr_onnxruntime import RapidOCR as engine_cls  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from rapidocr import RapidOCR as engine_cls  # type: ignore
        except Exception:  # noqa: BLE001
            return None
    try:
        out = engine_cls()(str(path))
        result = out[0] if isinstance(out, tuple) else out
        if hasattr(result, "txts"):
            lines = [str(t) for t in (result.txts or [])]
        else:
            lines = [str(r[1]) for r in (result or []) if len(r) > 1]
    except Exception:  # noqa: BLE001 - OCR is best effort
        return None
    text = "\n".join(t for t in lines if t.strip())
    return text or None


async def describe(cfg: dict, vm: VisionModel | None, meta: dict) -> dict:
    """Describe one image: {"ok", "text", "model", "cached", "error"}. Never raises."""
    path = Path(str(meta.get("path") or ""))
    sha = image_sha(path)
    if sha is None:
        return {"ok": False, "error": "file gambar tidak ditemukan"}
    hit = cache_get(sha)
    if hit:
        return {"ok": True, "text": hit["text"], "model": hit.get("model") or "", "cached": True, "sha256": sha}
    if vm is None:
        text = await asyncio.to_thread(_local_ocr, path)
        if text:
            text = "Isi: (dibaca dengan OCR lokal; hanya teks)\nTeks:\n" + text[:MAX_DESCRIPTION]
            cache_put(sha, "OCR lokal (RapidOCR)", text)
            return {"ok": True, "text": text, "model": "OCR lokal (RapidOCR)", "cached": False, "sha256": sha}
        return {"ok": False, "error": "tidak ada model vision yang tersedia"}
    timeout_s = _timeout(cfg)
    async with _queue(_concurrency(cfg)):
        hit = cache_get(sha)  # an earlier queued job may have read the same image
        if hit:
            return {"ok": True, "text": hit["text"], "model": hit.get("model") or "", "cached": True, "sha256": sha}
        try:
            text = await _ask_model(vm, meta, DESCRIBE_PROMPT, timeout_s)
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"model vision {vm.model} tidak menjawab dalam {timeout_s:.0f} detik"}
        except Exception as exc:  # noqa: BLE001 - reported as a notice, the turn goes on
            return {"ok": False, "error": f"{vm.model}: {str(exc)[:200]}"}
    text = text[:MAX_DESCRIPTION]
    cache_put(sha, vm.model, text)
    return {"ok": True, "text": text, "model": vm.model, "cached": False, "sha256": sha}


async def describe_all(cfg: dict, vm: VisionModel | None, images: list[dict]) -> list[dict]:
    """Describe images in order through the shared queue (results keep the input order)."""
    return list(await asyncio.gather(*(describe(cfg, vm, a) for a in images)))


# ---------------------------------------------------------- agent hooks ---

def notice_text(model: str) -> str:
    return f"Gambar dibaca oleh {model} karena model aktif tidak mendukung vision."


async def prepare_attachments(cfg: dict, endpoint: dict, attachments: list[dict],
                              emit: Callable[[str, dict], Any]) -> bool:
    """Called by the agent for a text-only model before the turn. Stores each image's
    description on its attachment (``vision_text`` / ``vision_model``) and emits an
    ``attachment.notice``. Returns True when at least one image was described."""
    from neovarch import uploads
    images = [a for a in attachments if isinstance(a, dict) and a.get("kind") == "image"]
    if not images:
        return False
    if not enabled(cfg):
        emit("attachment.notice", {"level": "warning", "message": uploads.VISION_NOTICE})
        return False
    try:
        vm = await pick_fallback(cfg, endpoint)
    except Exception as exc:  # noqa: BLE001 - discovery must never break a turn
        _log.warning("vision fallback discovery failed: %s", exc)
        vm = None
    if vm is not None:
        emit("status.update", {"kind": "notice", "text": f"Membaca gambar dengan {vm.model}\u2026"})
    results = await describe_all(cfg, vm, images)
    used: list[str] = []
    errors: list[str] = []
    for a, res in zip(images, results):
        if res.get("ok"):
            a["vision_text"] = res["text"]
            a["vision_model"] = res["model"]
            if res["model"] not in used:
                used.append(res["model"])
        else:
            errors.append(res.get("error") or "gagal")
    if used:
        msg = notice_text(", ".join(used))
        if errors:
            msg += f" {len(errors)} gambar gagal dibaca ({errors[0]}); untuk itu dikirim path file."
        emit("attachment.notice", {"level": "info", "message": msg, "vision_model": used[0],
                                   "kind": "vision_fallback"})
        return True
    detail = f" (Pembaca vision otomatis gagal: {errors[0]}.)" if errors and vm is not None else ""
    emit("attachment.notice", {"level": "warning", "message": uploads.VISION_NOTICE + detail})
    return False


def description_block(meta: dict) -> str:
    return (f"[Deskripsi otomatis gambar {meta.get('name') or ''} oleh model {meta.get('vision_model')} "
            f"(model aktif tidak bisa melihat gambar; path: {meta.get('path')})]\n"
            f"{meta.get('vision_text')}\n[Akhir deskripsi. Untuk pertanyaan lain soal gambar ini pakai alat "
            f"`image_ask`.]")


def augment_wire(w: dict, m: dict, vision: bool) -> dict:
    """Add stored descriptions to the wire form of a user turn for a text-only model."""
    if vision:
        return w
    described = [a for a in (m.get("attachments") or [])
                 if isinstance(a, dict) and a.get("kind") == "image" and a.get("vision_text")]
    if not described or not isinstance(w.get("content"), str):
        return w
    from neovarch import uploads
    text = w["content"]
    note = "(Catatan: " + uploads.VISION_NOTICE + ")"
    if len(described) == sum(1 for a in m.get("attachments") or [] if isinstance(a, dict) and a.get("kind") == "image"):
        text = text.replace("\n\n" + note, "").replace(note, "")
    text = "\n\n".join(t for t in [text, *[description_block(a) for a in described]] if t)
    return {**w, "content": text}


# -------------------------------------------------------------- image_ask ---

IMAGE_ASK_SCHEMA = {
    "description": "Ask a vision model a question about an image file (use when you cannot see images yourself).",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "image path or attachment id"},
        "question": {"type": "string"}}, "required": ["path", "question"]}}


async def tool_image_ask(args: dict, ctx: Any) -> str:
    from neovarch import uploads
    raw = str(args.get("path") or "").strip()
    question = str(args.get("question") or "").strip() or "Jelaskan isi gambar ini."
    if not raw:
        return "error: berikan path gambar"
    meta = uploads.UploadStore().get(raw) if re.fullmatch(r"[a-f0-9]{12}", raw) else None
    if meta is None:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path(getattr(ctx, "cwd", ".")) / p
        if not p.is_file():
            return f"error: not found: {p}"
        with p.open("rb") as fh:
            mime = uploads.guess_mime(p.name, None, fh.read(16))
        if uploads.kind_of(p.name, mime) != "image":
            return f"error: bukan file gambar: {p}"
        meta = {"name": p.name, "path": str(p), "mime": mime}
    cfg = cfgmod.load_config()
    if not enabled(cfg):
        return "error: vision fallback dimatikan (vision.fallback: off)"
    vm = await pick_fallback(cfg, cfgmod.resolve_endpoint(cfg))
    if vm is None:
        return "error: tidak ada model vision yang tersedia di 9Router atau endpoint lain"
    sha = image_sha(Path(meta["path"]))
    key = hashlib.sha256(f"{sha}|{vm.model}|{question}".encode()).hexdigest()
    hit = cache_get("q-" + key)
    if hit:
        return f"[{hit['model']}] {hit['text']}"
    timeout_s = _timeout(cfg)
    async with _queue(_concurrency(cfg)):
        try:
            text = await _ask_model(vm, meta, ASK_PROMPT + question, timeout_s)
        except asyncio.TimeoutError:
            return f"error: model vision {vm.model} tidak menjawab dalam {timeout_s:.0f} detik"
    text = text[:MAX_DESCRIPTION]
    cache_put("q-" + key, vm.model, text)
    return f"[{vm.model}] {text}"
