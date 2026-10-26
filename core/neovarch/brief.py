"""Mode 3 (proaktif mini): brief pagi di HP/PC.

Sekali sehari (bila ``brief.morning`` aktif, bawaan 08:00 waktu lokal) core
menyusun ringkasan keadaan tanpa bertanya lebih dulu:

* jadwal (cron) yang gagal atau tidak pernah jalan;
* sesi yang baru saja error (pesan error terakhirnya dikutip);
* server model lokal (mode luring) tersedia atau tidak;
* jadwal apa yang berikutnya akan jalan.

Brief dikirim sebagai **pesan asisten pada sesi cron ``Brief pagi``** — tiba di
HP lewat feed sesi yang sudah ada, tanpa saluran baru. Penyusunan brief tidak
memanggil model sama sekali (murni membaca store), jadi gratis dan tetap jalan
saat internet mati. Pengaturan ``config.yaml``::

    brief:
      morning: true        # bawaan: aktif
      hour: 8              # jam lokal 0-23
      minute: 0

Env: ``NEOVARCH_BRIEF_ENABLED`` (0/1), ``NEOVARCH_BRIEF_AT`` ("08:30").
"""

from __future__ import annotations

import os
import time
from typing import Any

from neovarch import config as cfgmod

SESSION_ID = "brief-morning"
ERROR_WINDOW_S = 24 * 3600  # sesi dengan error dalam 24 jam terakhir masuk brief
MAX_ERRORS = 3


def settings(cfg: dict | None = None) -> dict[str, Any]:
    cfg = _cfg(cfg)
    at = _env("NEOVARCH_BRIEF_AT") or str(cfgmod.get_path(cfg, "brief.at", "") or "")
    hour, minute = 8, 0
    if at and ":" in at:
        try:
            hour, minute = (int(p) for p in at.split(":", 1))
        except ValueError:
            hour, minute = 8, 0
    hour = min(max(int(cfgmod.get_path(cfg, "brief.hour", hour) or hour), 0), 23)
    minute = min(max(int(cfgmod.get_path(cfg, "brief.minute", minute) or minute), 0), 59)
    return {"enabled": _enabled(cfg), "hour": hour, "minute": minute}


def _cfg(cfg: dict | None) -> dict:
    try:
        return cfg if cfg is not None else cfgmod.load_config()
    except Exception:
        return {}


def _env(key: str) -> str:
    return str(os.environ.get(key) or "").strip()


def _enabled(cfg: dict) -> bool:
    env = _env("NEOVARCH_BRIEF_ENABLED")
    if env:
        return env not in ("0", "false", "off")
    return bool(cfgmod.get_path(cfg, "brief.morning", True))


def _local_now() -> tuple[int, int]:
    lt = time.localtime()
    return lt.tm_hour, lt.tm_min


def build(store: Any, cron_store: Any = None, offline_status: dict | None = None) -> dict:
    """Susun isi brief dari data lokal. Tidak ada panggilan model / jaringan di sini."""
    now = time.time()
    lines: list[str] = []
    alerts = 0

    failed_jobs = []
    upcoming = []
    for job in (cron_store.list() if cron_store else []):
        if job.get("last_error"):
            failed_jobs.append(job)
        elif job.get("enabled") and job.get("next_run"):
            upcoming.append(job)
    if failed_jobs:
        alerts += len(failed_jobs)
        for j in failed_jobs[:MAX_ERRORS]:
            name = j.get("name") or j["id"]
            err = str(j.get("last_error") or "")[:140]
            lines.append(f"- ⛔ Jadwal **{name}** gagal: {err}")
    if upcoming:
        nxt = min(upcoming, key=lambda j: float(j.get("next_run") or 0))
        import datetime
        when = datetime.datetime.fromtimestamp(float(nxt["next_run"])).strftime("%d %b %H:%M")
        lines.append(f"- ⏰ Jadwal berikutnya: **{nxt.get('name') or nxt['id']}** pukul {when}")

    errored = []
    for summary in store.list(limit=200):
        rec = store.load(summary["id"]) or {}
        msgs = rec.get("messages", [])
        last_err = next((str(m.get("content") or "") for m in reversed(msgs)
                         if m.get("role") == "assistant" and isinstance(m.get("meta"), dict)
                         and m["meta"].get("error")), "")
        if not last_err:
            last_err = str(rec.get("last_error") or "")
        if last_err and now - float(rec.get("updated_at") or 0) < ERROR_WINDOW_S:
            errored.append((rec, last_err))
    if errored:
        alerts += len(errored)
        for rec, err in errored[:MAX_ERRORS]:
            title = rec.get("title") or rec["id"]
            lines.append(f"- ⚠️ Sesi **{title[:60]}** berakhir error: {err[:140]}")

    if offline_status is not None:
        if offline_status.get("available"):
            lines.append(f"- 🟢 Mode luring siap: model lokal `{offline_status.get('model')}` tersedia")
        elif offline_status.get("enabled"):
            alerts += 1
            lines.append("- 🔴 Mode luring tidak siap (server model lokal tidak jalan)")

    if not lines:
        lines.append("- ✅ Semua aman: tidak ada jadwal gagal, sesi error, atau hal yang menunggu.")

    hour, minute = _local_now()
    head = f"Brief pagi ({hour:02d}.{minute:02d})"
    if alerts:
        head += f" — {alerts} hal perlu dilihat"
    body = "\n".join(lines)
    return {"title": head, "body": f"{head}\n\n{body}", "alerts": alerts}


def next_epoch(at_hour: int, at_minute: int, now: float | None = None) -> float:
    """Epoch detik untuk brief berikutnya (lokal). Lewat jam ini hari ini → besok."""
    import datetime
    now = now if now is not None else time.time()
    lt = datetime.datetime.fromtimestamp(now)
    target = lt.replace(hour=at_hour, minute=at_minute, second=0, microsecond=0)
    if target.timestamp() <= now:
        target += datetime.timedelta(days=1)
    return target.timestamp()
