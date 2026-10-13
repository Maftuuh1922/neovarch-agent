"""Token usage on this PC: per day, per session, lifetime and per model.

One source for the phone's Pamerkan card tiles ("token hari ini", "total
token"), the phone's Profil › Pemakaian token panel, the live chat header and
the token monitor on desktop.

Stored in ``<home>/usage.json`` (written atomically: temp file + rename)::

    {"version": 2,
     "since": "2026-10-12",                 # first day this PC counted anything
     "lifetime": {"input": n, "output": n, "cached": n, "cache_write": n, "calls": n},
     "days": {"2026-10-12": {…, "models": {"mimo-2.6": {…}}}},
     "sessions": {"<session id>": {…, "last": "2026-10-12"}},
     "models": {"mimo-2.6": {…, "provider": "9router"}}}

Every bucket uses ONE meaning, whatever shape the provider answered in:

* ``input``  = every prompt token the model read: uncached + cache read + cache write
* ``cached`` = the cache-read part of ``input`` (a subset, never added on top)
* ``cache_write`` = the cache-write part of ``input`` (a subset too)
* ``output`` = completion tokens (reasoning included)
* ``total``  = ``input + output``

Days use the PC's local date. Only the last ``KEEP_DAYS`` days and the last
``KEEP_SESSIONS`` sessions are kept (lifetime and per-model keep everything).
Counts only: no prompts, no text, nothing private.

REST: ``GET /api/usage[?session=<id>]`` → :func:`summary` (``trend`` = the last 30
kept days, each ``{date, total, input, output, cached, cache_write, calls}``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

KEEP_DAYS = 120
KEEP_SESSIONS = 300
VERSION = 2
_lock = threading.Lock()
_FIELDS = ("input", "output", "cached", "cache_write", "calls")


def _path() -> Path:
    from neovarch import config as cfgmod
    return cfgmod.neovarch_home() / "usage.json"


def _zero() -> dict:
    return dict.fromkeys(_FIELDS, 0)


def _empty() -> dict:
    return {"version": VERSION, "since": "", "lifetime": _zero(), "days": {}, "sessions": {}, "models": {}}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            data.setdefault("lifetime", _zero())
            data.setdefault("models", {})
            if not isinstance(data.get("sessions"), dict):
                data["sessions"] = {}
            if not data.get("since"):
                # v1 files (core 1.4.7) had no "since": the oldest day kept is the best answer.
                data["since"] = min(data["days"]) if data["days"] else ""
            return data
    except (OSError, ValueError):
        pass
    return _empty()


def _save(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, separators=(",", ":")))
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except OSError:
        pass


def _int(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _sub(d: Any, key: str) -> int:
    return _int(d.get(key)) if isinstance(d, dict) else 0


def normalize(usage: dict | None) -> dict | None:
    """One provider ``usage`` object → ``{input, output, cached, cache_write}`` (see module doc).

    Shapes understood:

    * OpenAI chat: ``prompt_tokens`` (cache INCLUDED), ``completion_tokens``,
      ``prompt_tokens_details.cached_tokens`` / ``.cache_creation_tokens`` (9router),
      DeepSeek's ``prompt_cache_hit_tokens``.
    * OpenAI Responses: ``input_tokens`` (cache included), ``output_tokens``,
      ``input_tokens_details.cached_tokens``.
    * Anthropic: ``input_tokens`` (cache EXCLUDED), ``cache_read_input_tokens``,
      ``cache_creation_input_tokens``, ``output_tokens``.
    * Gemini: ``promptTokenCount`` (cache included), ``candidatesTokenCount``,
      ``thoughtsTokenCount``, ``cachedContentTokenCount``.

    Returns None when the provider sent no usable counts.
    """
    if not isinstance(usage, dict) or not usage:
        return None
    u = usage
    if "promptTokenCount" in u or "candidatesTokenCount" in u:  # Gemini usageMetadata
        inp = _int(u.get("promptTokenCount"))
        out = _int(u.get("candidatesTokenCount")) + _int(u.get("thoughtsTokenCount"))
        cached, write = _int(u.get("cachedContentTokenCount")), 0
    elif "prompt_tokens" in u or "completion_tokens" in u:  # OpenAI chat completions
        det = u.get("prompt_tokens_details")
        inp = _int(u.get("prompt_tokens"))
        out = _int(u.get("completion_tokens"))
        cached = (_sub(det, "cached_tokens") or _int(u.get("prompt_cache_hit_tokens"))
                  or _int(u.get("cache_read_input_tokens")) or _int(u.get("cached_tokens")))
        write = _sub(det, "cache_creation_tokens") or _int(u.get("cache_creation_input_tokens"))
        if cached + write > inp:
            # A proxy that copied Anthropic's cache-exclusive prompt into prompt_tokens.
            inp += cached + write
    elif "input_tokens" in u or "output_tokens" in u:
        out = _int(u.get("output_tokens"))
        if isinstance(u.get("input_tokens_details"), dict):  # OpenAI Responses: cache included
            inp = _int(u.get("input_tokens"))
            cached, write = _sub(u["input_tokens_details"], "cached_tokens"), 0
            if cached > inp:
                inp += cached
        else:  # Anthropic: input_tokens is only the UNcached part
            cached = _int(u.get("cache_read_input_tokens")) or _int(u.get("cached_tokens"))
            write = _int(u.get("cache_creation_input_tokens"))
            inp = _int(u.get("input_tokens")) + cached + write
    else:
        return None
    if inp <= 0 and out <= 0:
        return None
    return {"input": inp, "output": out, "cached": min(cached, inp), "cache_write": min(write, inp)}


def cached_tokens(usage: dict | None) -> int:
    """Cache-read tokens in a provider ``usage`` (any shape :func:`normalize` knows)."""
    n = normalize(usage)
    return n["cached"] if n else 0


def merge_stream_usage(prev: dict | None, new: dict | None) -> dict | None:
    """Fold one streamed chunk's ``usage`` into what earlier chunks sent.

    Providers differ: most send one final usage chunk, some repeat a cumulative
    usage on every chunk, and some split it (prompt counts in the first chunk,
    completion in the last — Anthropic-style ``message_start``/``message_delta``
    behind OpenAI-compatible proxies). Keeping the largest value seen per field
    is right for all three; replacing (last chunk wins) loses the prompt of a
    split stream."""
    if not isinstance(new, dict) or not new:
        return prev
    if not isinstance(prev, dict) or not prev:
        return json.loads(json.dumps(new))
    out = dict(prev)
    for k, v in new.items():
        old = out.get(k)
        if isinstance(v, dict):
            out[k] = merge_stream_usage(old if isinstance(old, dict) else None, v)
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            if v is not None:
                out[k] = v
        elif isinstance(old, (int, float)) and not isinstance(old, bool):
            out[k] = max(old, v)
        else:
            out[k] = v
    return out


def _add(bucket: dict, c: dict) -> None:
    for k in ("input", "output", "cached", "cache_write"):
        bucket[k] = _int(bucket.get(k)) + _int(c.get(k))
    bucket["calls"] = _int(bucket.get("calls")) + 1


def today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now if now is not None else time.time()))


def record(model: str, usage: dict | None, *, provider: str = "", session: str = "",
           now: float | None = None, path: Path | None = None) -> dict | None:
    """Add one model call. Returns the normalized per-call counts, or None when the provider sent no usage."""
    counts = normalize(usage)
    if counts is None:
        return None
    model = (model or "?").strip()[:120] or "?"
    p = path or _path()
    day = today(now)
    with _lock:
        data = _load(p)
        data["version"] = VERSION
        if not data.get("since"):
            data["since"] = day
        _add(data["lifetime"], counts)
        d = data["days"].setdefault(day, {**_zero(), "models": {}})
        _add(d, counts)
        _add(d.setdefault("models", {}).setdefault(model, _zero()), counts)
        m = data["models"].setdefault(model, _zero())
        _add(m, counts)
        if provider:
            m["provider"] = provider[:60]
        sid = (session or "").strip()[:80]
        if sid:
            s = data["sessions"].pop(sid, None) or _zero()  # re-insert: most recent last
            _add(s, counts)
            s["last"] = day
            data["sessions"][sid] = s
            for old in list(data["sessions"])[:-KEEP_SESSIONS]:
                data["sessions"].pop(old, None)
        for old in sorted(data["days"])[:-KEEP_DAYS]:
            data["days"].pop(old, None)
        _save(p, data)
    return counts


def _total(b: dict | None) -> dict:
    b = b or {}
    out = {k: _int(b.get(k)) for k in _FIELDS}
    out["total"] = out["input"] + out["output"]
    return out


def summary(*, session: dict | None = None, session_id: str = "", now: float | None = None,
            path: Path | None = None, days: int = 30) -> dict[str, Any]:
    """Today / lifetime (+ ``since``) / per model / trend, and the session when one is named.

    The session comes from the on-disk counter (survives restarts); a session
    record's own ``usage_total`` is the fallback for sessions counted before v2."""
    data = _load(path or _path())
    day = today(now)
    t = data["days"].get(day) or {}
    models = sorted(({"model": k, **_total(v), **({"provider": v["provider"]} if v.get("provider") else {})}
                     for k, v in data["models"].items()), key=lambda m: -m["total"])
    today_models = sorted(({"model": k, **_total(v)} for k, v in (t.get("models") or {}).items()),
                          key=lambda m: -m["total"])
    # Each day carries its masuk/keluar/cache split (v1.4.8 phone chart); "date" and
    # "total" stay first so older readers (desktop token monitor, phone ≤ 1.4.7) keep working.
    trend = [{"date": k, **_total(v)} for k, v in sorted(data["days"].items())[-days:]]
    out: dict[str, Any] = {"date": day, "since": data.get("since") or "", "today": _total(t),
                           "lifetime": _total(data["lifetime"]), "models": models,
                           "today_models": today_models, "trend": trend}
    sid = session_id or (str(session.get("id") or "") if isinstance(session, dict) else "")
    disk = data["sessions"].get(sid) if sid else None
    if disk:
        out["session"] = _total(disk)
    elif session is not None:
        out["session"] = _total(session.get("usage_total") or {})
    return out


def add_session(rec: dict, counts: dict | None) -> dict:
    """Running per-session totals kept on the session record (live events, desktop statusbar)."""
    tot = rec.setdefault("usage_total", _zero())
    if counts:
        _add(tot, counts)
    return _total(tot)


def session_total(rec: dict) -> dict:
    """This session's totals ({input, output, cached, cache_write, calls, total}); zeros when nothing was counted."""
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
