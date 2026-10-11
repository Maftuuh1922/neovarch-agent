"""Token usage on this PC: per day, lifetime and per model (v1.4.7).

One source for the phone's Pamerkan card tiles ("token hari ini", "total
token"), the live chat header and the token monitor on desktop/phone.

Stored in ``<home>/usage.json``::

    {"version": 1,
     "lifetime": {"input": n, "output": n, "cached": n, "calls": n},
     "days": {"2026-10-12": {"input": …, "output": …, "cached": …, "calls": …,
                             "models": {"mimo-2.6": {…}}}},
     "models": {"mimo-2.6": {"input": …, "output": …, "cached": …, "calls": …, "provider": "9router"}}}

Days use the PC's local date. Only the last ``KEEP_DAYS`` days are kept (the
lifetime and per-model totals keep everything). Counts only: no prompts, no
text, nothing private.

REST: ``GET /api/usage[?session=<id>]`` → :func:`summary`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

KEEP_DAYS = 120
_lock = threading.Lock()
_FIELDS = ("input", "output", "cached", "calls")


def _path() -> Path:
    from neovarch import config as cfgmod
    return cfgmod.neovarch_home() / "usage.json"


def _empty() -> dict:
    return {"version": 1, "lifetime": dict.fromkeys(_FIELDS, 0), "days": {}, "models": {}}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            data.setdefault("lifetime", dict.fromkeys(_FIELDS, 0))
            data.setdefault("models", {})
            return data
    except (OSError, ValueError):
        pass
    return _empty()


def cached_tokens(usage: dict | None) -> int:
    u = usage or {}
    details = u.get("prompt_tokens_details") or {}
    for v in (details.get("cached_tokens") if isinstance(details, dict) else None,
              u.get("cache_read_input_tokens"), u.get("cached_tokens")):
        try:
            if v:
                return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def _add(bucket: dict, inp: int, out: int, cached: int) -> None:
    bucket["input"] = int(bucket.get("input") or 0) + inp
    bucket["output"] = int(bucket.get("output") or 0) + out
    bucket["cached"] = int(bucket.get("cached") or 0) + cached
    bucket["calls"] = int(bucket.get("calls") or 0) + 1


def today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now if now is not None else time.time()))


def record(model: str, usage: dict | None, *, provider: str = "", now: float | None = None,
           path: Path | None = None) -> dict | None:
    """Add one model call. Returns the per-call counts, or None when the provider sent no usage."""
    u = usage or {}
    try:
        inp = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        out = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if inp <= 0 and out <= 0:
        return None
    cached = cached_tokens(u)
    model = (model or "?").strip()[:120] or "?"
    p = path or _path()
    day = today(now)
    with _lock:
        data = _load(p)
        _add(data["lifetime"], inp, out, cached)
        d = data["days"].setdefault(day, {**dict.fromkeys(_FIELDS, 0), "models": {}})
        _add(d, inp, out, cached)
        _add(d.setdefault("models", {}).setdefault(model, dict.fromkeys(_FIELDS, 0)), inp, out, cached)
        m = data["models"].setdefault(model, dict.fromkeys(_FIELDS, 0))
        _add(m, inp, out, cached)
        if provider:
            m["provider"] = provider[:60]
        for old in sorted(data["days"])[:-KEEP_DAYS]:
            data["days"].pop(old, None)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
    return {"input": inp, "output": out, "cached": cached}


def _total(b: dict) -> dict:
    out = {k: int(b.get(k) or 0) for k in _FIELDS}
    out["total"] = out["input"] + out["output"]
    return out


def summary(*, session: dict | None = None, now: float | None = None, path: Path | None = None,
            days: int = 30) -> dict[str, Any]:
    data = _load(path or _path())
    day = today(now)
    t = data["days"].get(day) or {}
    models = sorted(({"model": k, **_total(v), **({"provider": v["provider"]} if v.get("provider") else {})}
                     for k, v in data["models"].items()), key=lambda m: -m["total"])
    today_models = sorted(({"model": k, **_total(v)} for k, v in (t.get("models") or {}).items()),
                          key=lambda m: -m["total"])
    trend = [{"date": k, "total": _total(v)["total"]} for k, v in sorted(data["days"].items())[-days:]]
    out: dict[str, Any] = {"date": day, "today": _total(t), "lifetime": _total(data["lifetime"]),
                           "models": models, "today_models": today_models, "trend": trend}
    if session is not None:
        out["session"] = _total(session.get("usage_total") or {})
    return out


def add_session(rec: dict, counts: dict | None) -> dict:
    """Running per-session totals kept on the session record."""
    tot = rec.setdefault("usage_total", dict.fromkeys(_FIELDS, 0))
    if counts:
        _add(tot, int(counts["input"]), int(counts["output"]), int(counts["cached"]))
    return _total(tot)


def session_total(rec: dict) -> dict:
    """This session's totals ({input, output, cached, calls, total}); zeros when nothing was counted."""
    return _total(rec.get("usage_total") or {})


def desktop_usage(session_total: dict, context_tokens: int, context_window: int) -> dict:
    """Desktop statusbar ``UsageStats``: session input/output/total/calls + live context.

    ``context_used`` is the prompt of the latest model call (what the window holds now)."""
    out = {k: int(session_total.get(k) or 0) for k in ("input", "output", "total", "calls")}
    cached = int(session_total.get("cached") or 0)
    out["cached"] = cached
    if out["input"] and cached:
        out["cache_hit_pct"] = round(100 * cached / out["input"], 1)
    if context_window:
        used = max(0, int(context_tokens))
        out.update(context_used=used, context_max=int(context_window),
                   context_percent=round(min(100.0, 100 * used / context_window), 1))
    return out
