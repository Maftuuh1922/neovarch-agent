"""Local, free speech-to-text for ``/api/audio/transcribe`` (desktop mic + phone fallback).

Engines (both optional; nothing is downloaded or installed unless the user does it):

* ``faster-whisper`` — ``pip install faster-whisper`` (or ``pip install "neovarch[stt]"``).
  Decodes webm/ogg/m4a/wav itself (PyAV); the model is fetched once from Hugging Face
  on first use and cached.
* ``whisper.cpp`` — a ``whisper-cli`` (or ``whisper-cpp``) binary plus a ggml model file
  (``stt.whisper_cpp_model``); audio is converted to 16 kHz wav with ``ffmpeg``.

Config (``config.yaml``, every key optional; env vars win)::

    stt:
      engine: auto          # auto | faster-whisper | whisper.cpp | off   (NEOVARCH_STT_ENGINE)
      model: small          # tiny | base | small | medium | large-v3 … (NEOVARCH_STT_MODEL)
      language: auto        # auto, or "id", "en" …                       (NEOVARCH_STT_LANGUAGE)
      device: cpu           # cpu | cuda | auto                           (NEOVARCH_STT_DEVICE)
      compute_type: int8    # faster-whisper compute type
      whisper_cpp_bin: ""   # path to whisper-cli; default: looked up on PATH
      whisper_cpp_model: "" # path to ggml-*.bin                          (NEOVARCH_WHISPER_CPP_MODEL)

No engine → a clear, typed ``stt_unavailable`` answer with the install hint; never a crash.
"""

from __future__ import annotations

import base64
import binascii
import importlib.util
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

MAX_AUDIO_BYTES = 25 * 1024 * 1024
ENGINES = ("faster-whisper", "whisper.cpp")
INSTALL_HINT = 'pip install faster-whisper  (atau: pip install "neovarch[stt]")'

STT_UNAVAILABLE = ("Dikte suara di PC belum aktif: belum ada mesin STT lokal. Pasang yang gratis dengan "
                   f"`{INSTALL_HINT}`, lalu jalankan ulang Neovarch. Model default: small (diunduh sekali). "
                   "/ Voice typing on the PC is not available yet: no local speech-to-text engine. "
                   "Install the free one with `pip install faster-whisper`, then restart Neovarch.")
STT_OFF = ("Dikte suara di PC dimatikan (stt.engine: off di config.yaml). "
           "/ Voice typing on the PC is turned off (stt.engine: off).")

_EXT = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a",
        "audio/aac": ".aac", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
        "audio/3gpp": ".3gp", "audio/amr": ".amr", "audio/flac": ".flac"}


class SttError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def settings(cfg: dict | None = None) -> dict[str, str]:
    if cfg is None:
        try:
            from neovarch.config import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 - a broken config must not break dictation
            cfg = {}
    s = cfg.get("stt") if isinstance(cfg.get("stt"), dict) else {}

    def pick(key: str, env: str, default: str) -> str:
        v = os.environ.get(env, "").strip() if env else ""
        return v or str(s.get(key) or default).strip()

    return {
        "engine": pick("engine", "NEOVARCH_STT_ENGINE", "auto").lower(),
        "model": pick("model", "NEOVARCH_STT_MODEL", "small"),
        "language": pick("language", "NEOVARCH_STT_LANGUAGE", "auto").lower(),
        "device": pick("device", "NEOVARCH_STT_DEVICE", "cpu").lower(),
        "compute_type": pick("compute_type", "NEOVARCH_STT_COMPUTE_TYPE", "int8"),
        "whisper_cpp_bin": pick("whisper_cpp_bin", "NEOVARCH_WHISPER_CPP_BIN", ""),
        "whisper_cpp_model": pick("whisper_cpp_model", "NEOVARCH_WHISPER_CPP_MODEL", ""),
    }


def _has_faster_whisper() -> bool:
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def _whisper_cpp_bin(s: dict) -> str | None:
    if s["whisper_cpp_bin"]:
        p = Path(s["whisper_cpp_bin"]).expanduser()
        return str(p) if p.exists() else None
    for name in ("whisper-cli", "whisper-cpp", "whisper.cpp"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _whisper_cpp_ready(s: dict) -> bool:
    model = s["whisper_cpp_model"]
    return bool(_whisper_cpp_bin(s) and model and Path(model).expanduser().is_file() and shutil.which("ffmpeg"))


def pick_engine(s: dict) -> str | None:
    want = s["engine"]
    if want == "off":
        return None
    if want in ("faster-whisper", "faster_whisper"):
        return "faster-whisper" if _has_faster_whisper() else None
    if want in ("whisper.cpp", "whisper-cpp", "whispercpp"):
        return "whisper.cpp" if _whisper_cpp_ready(s) else None
    if _has_faster_whisper():
        return "faster-whisper"
    if _whisper_cpp_ready(s):
        return "whisper.cpp"
    return None


def status(cfg: dict | None = None) -> dict[str, Any]:
    s = settings(cfg)
    eng = pick_engine(s)
    out: dict[str, Any] = {"ok": True, "available": eng is not None, "engine": eng, "model": s["model"],
                           "language": s["language"], "configured_engine": s["engine"]}
    if eng is None:
        out["reason"] = STT_OFF if s["engine"] == "off" else STT_UNAVAILABLE
        out["install_hint"] = INSTALL_HINT
    if eng == "whisper.cpp":
        out["model"] = Path(s["whisper_cpp_model"]).name
    return out


def decode_audio(body: dict) -> tuple[bytes, str]:
    """``{data_url}`` or ``{audio_base64, mime_type}`` → (bytes, mime)."""
    mime = str(body.get("mime_type") or "").split(";")[0].strip().lower()
    raw = body.get("data_url") or body.get("audio_base64") or body.get("audio") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise SttError("bad_audio", "Tidak ada audio di permintaan. / No audio in the request.")
    if raw.startswith("data:"):
        head, _, raw = raw.partition(",")
        if not mime:
            mime = head[5:].split(";")[0].strip().lower()
    try:
        data = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        raise SttError("bad_audio", "Audio tidak bisa dibaca (base64 rusak). / Audio is not valid base64.") from None
    if len(data) < 64:
        raise SttError("bad_audio", "Rekaman terlalu pendek. / The recording is too short.")
    if len(data) > MAX_AUDIO_BYTES:
        raise SttError("too_large", "Rekaman terlalu panjang (maks 25 MB). / Recording too large (max 25 MB).")
    return data, mime or "audio/webm"


_models: dict[tuple, Any] = {}
_lock = threading.Lock()


def _faster_whisper(path: str, s: dict) -> tuple[str, str | None]:
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    key = (s["model"], s["device"], s["compute_type"])
    with _lock:
        model = _models.get(key)
        if model is None:
            model = WhisperModel(s["model"], device=s["device"], compute_type=s["compute_type"])
            _models.clear()
            _models[key] = model
        lang = None if s["language"] in ("", "auto") else s["language"]
        segments, info = model.transcribe(path, language=lang, beam_size=1, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, getattr(info, "language", None)


def _whisper_cpp(path: str, s: dict) -> tuple[str, str | None]:
    binary = _whisper_cpp_bin(s)
    with tempfile.TemporaryDirectory(prefix="nv-stt-") as d:
        wav = os.path.join(d, "in.wav")
        conv = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path, "-ar", "16000", "-ac", "1", wav],
                              capture_output=True, text=True, timeout=120)
        if conv.returncode != 0:
            raise SttError("stt_failed", f"ffmpeg gagal mengubah audio: {conv.stderr.strip()[:300]}")
        lang = "auto" if s["language"] in ("", "auto") else s["language"]
        run = subprocess.run([binary, "-m", str(Path(s["whisper_cpp_model"]).expanduser()), "-f", wav, "-l", lang, "-nt", "-np"],
                             capture_output=True, text=True, timeout=300)
        if run.returncode != 0:
            raise SttError("stt_failed", f"whisper.cpp gagal: {run.stderr.strip()[:300]}")
        return " ".join(run.stdout.split()).strip(), None if lang == "auto" else lang


def transcribe_bytes(data: bytes, mime: str, cfg: dict | None = None) -> dict[str, Any]:
    """Blocking; call it from a worker thread. Raises SttError with a typed code."""
    s = settings(cfg)
    eng = pick_engine(s)
    if eng is None:
        raise SttError("stt_unavailable", STT_OFF if s["engine"] == "off" else STT_UNAVAILABLE)
    with tempfile.NamedTemporaryFile(suffix=_EXT.get(mime, ".webm"), delete=False) as f:
        f.write(data)
        path = f.name
    try:
        try:
            text, lang = (_faster_whisper if eng == "faster-whisper" else _whisper_cpp)(path, s)
        except SttError:
            raise
        except Exception as e:  # noqa: BLE001 - surface any engine failure as a readable answer
            raise SttError("stt_failed", f"Transkripsi gagal ({eng}): {e}".strip()[:500]) from e
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return {"ok": True, "available": True, "transcript": text, "engine": eng,
            "model": s["model"] if eng == "faster-whisper" else Path(s["whisper_cpp_model"]).name, "language": lang}
