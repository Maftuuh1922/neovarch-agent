"""Mode 1: offline fallback — agen tetap menjawab saat internet/kuota mati.

Ketika model utama (mis. 9Router / provider gratis) gagal total — koneksi mati,
kuota habis, semua kandidat fallback dipakai — agent mencoba **server model
lokal** (Ollama di ``127.0.0.1:11434`` atau server OpenAI-compatible lain yang
diatur di ``config.yaml``). Semua di PC pengguna, tanpa API berbayar, tanpa
internet. Kalau tidak ada yang jalan, jawaban seperti sebelumnya (error biasa).

Konfigurasi ``config.yaml``::

    offline:
      enabled: true            # bawaan: true (tanpa biaya, hanya dipakai saat gagal)
      base_url: ""             # kosong = autodetect Ollama; contoh: http://127.0.0.1:1234/v1
      model: ""                # kosong = model pertama yang terdaftar di server

Env menang: ``NEOVARCH_OFFLINE_BASE_URL``, ``NEOVARCH_OFFLINE_MODEL``,
``NEOVARCH_OFFLINE_ENABLED`` (0/1).

Perilaku yang dijamin:
- Hanya dicoba setelah fallback bawaan (model gratis lain) habis, jadi nominal
  tidak mengubah urutan model yang dipakai orang.
- Satu percobaan per giliran; hasilnya diumumkan ke obrolan sebagai peristiwa
  ``offline.fallback`` supaya HP/desktop bisa menampilkan lencana "mode luring".
- Tidak pernah mengubah model bawaan yang tersimpan (sama seperti router9).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import aiohttp

from neovarch import config as cfgmod

OLLAMA_URL = "http://127.0.0.1:11434"
PROBE_TIMEOUT_S = 2.0
ASK_TIMEOUT_S = 300.0
COOLDOWN_S = 60.0  # setelah gagal, jangan ganggu server lokal lagi selama semenit

_state: dict[str, Any] = {"failed_at": 0.0, "last_base": None}


def settings(cfg: dict | None = None) -> dict[str, Any]:
    cfg = _cfg(cfg)
    return {
        "enabled": _enabled(cfg),
        "base_url": _env("NEOVARCH_OFFLINE_BASE_URL") or str(cfgmod.get_path(cfg, "offline.base_url", "") or ""),
        "model": _env("NEOVARCH_OFFLINE_MODEL") or str(cfgmod.get_path(cfg, "offline.model", "") or ""),
    }


def _cfg(cfg: dict | None) -> dict:
    try:
        return cfg if cfg is not None else cfgmod.load_config()
    except Exception:
        return {}


def _env(key: str) -> str:
    return str(os.environ.get(key) or "").strip()


def _enabled(cfg: dict) -> bool:
    env = _env("NEOVARCH_OFFLINE_ENABLED")
    if env:
        return env not in ("0", "false", "off")
    return bool(cfgmod.get_path(cfg, "offline.enabled", True))


def cooling_down() -> bool:
    return time.time() - float(_state["failed_at"]) < COOLDOWN_S


def note_failure() -> None:
    _state["failed_at"] = time.time()


def reset() -> None:
    _state["failed_at"] = 0.0


async def probe(base_url: str) -> dict | None:
    """Endpoint siap pakai di ``base_url`` (Ollama autodetect bila kosong), None bila tidak ada."""
    candidates = [base_url] if base_url else [OLLAMA_URL]
    for base in candidates:
        base = base.rstrip("/")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_S)) as s:
                async with s.get(base + "/models") as r:
                    if r.status != 200:
                        continue
                    data = await r.json()
            ids = [str(m.get("id")) for m in (data.get("data") or []) if m.get("id")]
            if ids:
                return {"base_url": base, "models": ids}
        except Exception:
            continue
    return None


async def endpoint(cfg: dict | None = None, prefer_model: str = "") -> dict[str, Any] | None:
    """Endpoint lokal yang bisa dipakai sekarang, atau None. Tidak pernah melempar."""
    s = settings(_cfg(cfg))
    if not s["enabled"] or cooling_down():
        return None
    found = await probe(s["base_url"])
    if not found:
        note_failure()
        return None
    model = prefer_model or s["model"]
    if model and model in found["models"]:
        chosen = model
    else:
        chosen = found["models"][0]
    return {"base_url": found["base_url"], "api_key": "", "model": chosen,
            "provider": "offline", "headers": {}}


async def status(cfg: dict | None = None) -> dict:
    """Untuk ``GET /api/offline/status``: apa yang akan dipakai saat offline."""
    s = settings(_cfg(cfg))
    found = await probe(s["base_url"]) if s["enabled"] else None
    return {
        "enabled": s["enabled"],
        "configured_base_url": s["base_url"] or OLLAMA_URL,
        "available": found is not None,
        "base_url": found["base_url"] if found else None,
        "models": found["models"] if found else [],
        "model": s["model"] or (found["models"][0] if found else None),
        "cooling_down": cooling_down(),
    }


async def answer(base_url: str, model: str, prompt: str) -> str:
    """Panggilan chat satu putaran (tanpa alat) — dipakai brief pagi mode luring."""
    timeout = aiohttp.ClientTimeout(total=ASK_TIMEOUT_S)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(base_url.rstrip("/") + "/chat/completions", json=body,
                          headers={"Content-Type": "application/json"}) as r:
            text = await r.text()
            if r.status != 200:
                raise RuntimeError(f"offline model HTTP {r.status}: {text[:200]}")
            data = json.loads(text)
            return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
