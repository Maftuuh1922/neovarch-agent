"""Pamerkan: radar + charts for the share card, computed ONLY from what this PC already records.

Sources (all local, nothing is sent anywhere, nothing is estimated or invented):

* ``sessions/<id>.json`` (:class:`neovarch.store.SessionStore`): every assistant ``tool_calls``
  entry with its message ``ts``, the session ``source`` (``cli`` / ``cron`` / ``company`` …) and
  user turns. A ``codemode`` call is not counted itself; the tools its program calls
  (``tools.read_file(…)``, ``tools.call("grep", …)``, ``tools.parallel([("web_search", {…}), …])``)
  are read from the program text and counted one by one (a call written inside a loop counts once).
* ``usage.json`` (:mod:`neovarch.usage_stats`): tokens per local day.

Axes (``AXES``) and how a tool call lands on one (:func:`category`):

* ``coding``  - file edits/reads, grep/glob/repo_map, patches, shell, diagrams
* ``riset``   - web_search, papers/reports, session/vault search, read-only sub-agents (``task``)
* ``ppt``     - ``ppt_*`` (PPT Master) and any tool with ppt/pptx/slide/deck in its name
* ``browser`` - ``web_fetch`` (opens a page, rendered by the headless browser when needed) and any
  MCP / extra tool with browser/playwright/puppeteer/navigate/click/screenshot in its name
* ``otomasi`` - Kantor / company, cron, background shell jobs, ``manage``/``skill_manage``/settings,
  plus every user turn of a session the scheduler or the company runtime started
  (``source`` ``cron`` / ``company`` / ``kanban``)
* ``token``   - input + output tokens of the window (``usage.json``)
* anything else (``memory``, ``skill``, unknown MCP tools …) is ``lainnya``: it shows in the
  donut and the top-tools bar, never on the radar

Score (0-100) per axis is a log scale against a fixed reference (``REFERENCE``)::

    score = round(100 * min(1, log10(1 + value) / log10(1 + reference)))

so 1 call already shows a little, the reference amount fills the axis, and nothing is ever
normalised against the other axes (a quiet month really looks quiet). ``empty`` is true when
every axis is 0 - the UI then shows its empty state instead of a flat polygon.

REST: ``GET /api/pamerkan[?days=30]`` → :func:`compute`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

AXES = ("coding", "riset", "ppt", "browser", "otomasi", "token")
ACTIVITY_AXES = AXES[:-1]

# The amount that fills an axis (100) for the default 30-day window; scaled by days/30.
REFERENCE: dict[str, float] = {
    "coding": 1500,
    "riset": 300,
    "ppt": 40,
    "browser": 200,
    "otomasi": 150,
    "token": 20_000_000,
}
DEFAULT_DAYS = 30
MAX_DAYS = 365
TREND_DAYS = 14
TREND_WEEKS = 8
TOP_TOOLS = 8

AUTOMATION_SOURCES = frozenset({"cron", "company", "kanban"})

_CODING = frozenset({
    "read_file", "write_file", "edit_file", "multi_edit", "str_replace", "apply_patch", "patch",
    "grep", "glob", "repo_map", "shell", "diagram_save", "self_diagnose", "self_undo", "core_reload",
})
_RISET = frozenset({
    "web_search", "report_search", "report_create", "report_export", "session_search",
    "obsidian_search", "obsidian_read", "obsidian_links", "obsidian_write", "task",
})
_BROWSER = frozenset({"web_fetch"})
_OTOMASI = frozenset({
    "kantor", "office_status", "shell_job", "manage", "skill_manage", "settings_update", "plan_update",
    "update_plan", "send_file",
})
_BROWSER_RE = re.compile(r"browser|playwright|puppeteer|navigate|click|screenshot|chrom", re.I)
_PPT_RE = re.compile(r"(^|_)ppt|pptx|slide|deck|presentation", re.I)
_AUTO_RE = re.compile(r"cron|schedule|jadwal|kanban|company|kantor|workflow|automat|heartbeat", re.I)
_CODE_RE = re.compile(r"edit|write|patch|lint|test|git|code|compile|build", re.I)
_SEARCH_RE = re.compile(r"search|research|paper|scholar|wiki|fetch_doc|docs", re.I)

# codemode program text → the tools it calls
_CM_ATTR = re.compile(r"\btools\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CM_CALL = re.compile(r"\btools\.call\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
_CM_PAR = re.compile(r"\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*,\s*\{")
_CM_HELPERS = frozenset({"call", "parallel", "list", "describe"})


def category(name: str) -> str | None:
    """Axis for one tool name, or None when it fits none (counted as ``lainnya``)."""
    n = (name or "").strip()
    if not n:
        return None
    base = n.split("__")[-1]  # mcp__server__tool → tool (the server name still decides browser below)
    if base in _CODING:
        return "coding"
    if base in _RISET:
        return "riset"
    if base in _BROWSER or _BROWSER_RE.search(n):
        return "browser"
    if _PPT_RE.search(base):
        return "ppt"
    if base in _OTOMASI or _AUTO_RE.search(n):
        return "otomasi"
    if _SEARCH_RE.search(base):
        return "riset"
    if _CODE_RE.search(base):
        return "coding"
    return None


def codemode_tools(code: str) -> list[str]:
    """Tool names a codemode program calls, in order of appearance (helpers excluded)."""
    if not isinstance(code, str) or not code:
        return []
    hits: list[tuple[int, str]] = []
    for m in _CM_ATTR.finditer(code):
        if m.group(1) not in _CM_HELPERS:
            hits.append((m.start(), m.group(1)))
    for m in _CM_CALL.finditer(code):
        hits.append((m.start(), m.group(1)))
    for start in (m.end() for m in re.finditer(r"\btools\.parallel\(", code)):
        depth, end = 1, start
        while end < len(code) and depth:
            depth += {"(": 1, ")": -1}.get(code[end], 0)
            end += 1
        for m in _CM_PAR.finditer(code, start, end):
            hits.append((m.start(), m.group(1)))
    return [name for _, name in sorted(hits) if name not in ("codemode", "extra_tool")]


def _call_names(call: dict) -> list[str]:
    fn = call.get("function") if isinstance(call, dict) else None
    if not isinstance(fn, dict):
        return []
    name = str(fn.get("name") or "")
    if name == "codemode":
        raw = fn.get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
        except (TypeError, ValueError):
            args = {}
        return codemode_tools(str((args or {}).get("code") or (args or {}).get("program") or ""))
    if name == "extra_tool":  # deferred tool: the real name is in the arguments
        raw = fn.get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
        except (TypeError, ValueError):
            args = {}
        inner = str((args or {}).get("name") or (args or {}).get("tool") or "")
        return [inner] if inner else []
    return [name] if name else []


def score(value: float, reference: float) -> int:
    if value <= 0 or reference <= 0:
        return 0
    return int(round(100 * min(1.0, math.log10(1 + value) / math.log10(1 + reference))))


def _local_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _iso_week(day: str) -> str:
    y, w, _ = dt.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def _iter_sessions(sessions_dir: Path) -> Iterable[dict]:
    if not sessions_dir.is_dir():
        return
    for p in sessions_dir.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            yield rec


def _usage_days(usage_path: Path) -> dict[str, int]:
    try:
        data = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    days = data.get("days") if isinstance(data, dict) else None
    out: dict[str, int] = {}
    if isinstance(days, dict):
        for day, b in days.items():
            if isinstance(b, dict):
                try:
                    out[str(day)] = max(0, int(b.get("input") or 0)) + max(0, int(b.get("output") or 0))
                except (TypeError, ValueError):
                    continue
    return out


def compute(*, home: Path | None = None, sessions_dir: Path | None = None, usage_path: Path | None = None,
            days: int = DEFAULT_DAYS, now: float | None = None) -> dict[str, Any]:
    """Radar axes, bar/donut/trend series and headline numbers for the last ``days`` local days."""
    if home is None:
        from neovarch.paths import neovarch_home
        home = neovarch_home()
    sessions_dir = sessions_dir or home / "sessions"
    usage_path = usage_path or home / "usage.json"
    days = max(1, min(MAX_DAYS, int(days or DEFAULT_DAYS)))
    now = time.time() if now is None else now
    today = dt.date.fromisoformat(_local_day(now))
    first = today - dt.timedelta(days=days - 1)
    span_first = min(first, today - dt.timedelta(days=max(TREND_DAYS, TREND_WEEKS * 7) - 1))
    window = {(first + dt.timedelta(days=i)).isoformat() for i in range(days)}

    raw: Counter = Counter()
    tools: Counter = Counter()
    other = 0
    calls_per_day: Counter = Counter()
    turns_per_day: Counter = Counter()
    sessions = 0
    by_source: Counter = Counter()
    span_lo = span_first.isoformat()

    for rec in _iter_sessions(sessions_dir):
        source = str(rec.get("source") or "cli")
        auto = source in AUTOMATION_SOURCES
        touched = False
        for m in rec.get("messages") or []:
            if not isinstance(m, dict):
                continue
            ts = m.get("ts")
            if not isinstance(ts, (int, float)) or isinstance(ts, bool):
                continue
            day = _local_day(ts)
            if day < span_lo or day > today.isoformat():
                continue
            in_window = day in window
            role = m.get("role")
            if role == "user" and not m.get("hidden") and not m.get("kind"):
                turns_per_day[day] += 1
                if in_window:
                    touched = True
                    if auto:
                        raw["otomasi"] += 1
            elif role == "assistant":
                for call in m.get("tool_calls") or []:
                    for name in _call_names(call):
                        calls_per_day[day] += 1
                        if not in_window:
                            continue
                        touched = True
                        tools[name] += 1
                        cat = category(name)
                        if cat:
                            raw[cat] += 1
                        else:
                            other += 1
        if touched:
            sessions += 1
            by_source[source] += 1

    tok_days = _usage_days(usage_path)
    raw["token"] = sum(v for d, v in tok_days.items() if d in window)

    scale = days / DEFAULT_DAYS
    axes = [{"id": a, "value": int(raw[a]), "reference": int(round(REFERENCE[a] * scale)),
             "score": score(raw[a], REFERENCE[a] * scale)} for a in AXES]

    tool_calls = int(sum(tools.values()))
    donut = [{"id": a, "value": int(raw[a])} for a in ACTIVITY_AXES if raw[a]]
    if other:
        donut.append({"id": "lainnya", "value": other})

    daily = []
    for i in range(TREND_DAYS - 1, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily.append({"date": d, "calls": int(calls_per_day[d]), "turns": int(turns_per_day[d]),
                      "tokens": int(tok_days.get(d, 0))})
    weekly: list[dict] = []
    for i in range(TREND_WEEKS - 1, -1, -1):
        start = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=i)
        ds = [(start + dt.timedelta(days=k)).isoformat() for k in range(7)]
        weekly.append({"week": _iso_week(ds[0]), "start": ds[0],
                       "calls": int(sum(calls_per_day[d] for d in ds)),
                       "turns": int(sum(turns_per_day[d] for d in ds)),
                       "tokens": int(sum(tok_days.get(d, 0) for d in ds))})

    active = sorted({d for d in window if calls_per_day[d] or turns_per_day[d] or tok_days.get(d)})
    streak = 0
    d = today
    while d.isoformat() in window and (calls_per_day[d.isoformat()] or turns_per_day[d.isoformat()]
                                         or tok_days.get(d.isoformat())):
        streak += 1
        d -= dt.timedelta(days=1)

    empty = all(a["value"] == 0 for a in axes)
    return {
        "version": 1,
        "days": days,
        "from": first.isoformat(),
        "to": today.isoformat(),
        "empty": empty,
        "axes": axes,
        "bars": [{"id": a, "value": int(raw[a])} for a in ACTIVITY_AXES],
        "donut": donut,
        "tools_top": [{"name": n, "value": int(c), "axis": category(n) or "lainnya"}
                      for n, c in tools.most_common(TOP_TOOLS)],
        "trend": {"daily": daily, "weekly": weekly},
        "totals": {"sessions": sessions, "tool_calls": tool_calls, "turns": int(sum(turns_per_day[d] for d in window)),
                   "tokens": int(raw["token"]), "active_days": len(active), "streak": streak,
                   "automated_sessions": int(sum(by_source[s] for s in AUTOMATION_SOURCES))},
    }


# A small cache: the desktop re-opens the dialog often; sessions only change between turns.
_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, dict]] = {}
CACHE_SECONDS = 20.0


def cached(days: int = DEFAULT_DAYS, *, home: Path | None = None) -> dict[str, Any]:
    if home is None:
        from neovarch.paths import neovarch_home
        home = neovarch_home()
    key = (str(home), int(days), _local_day(time.time()))
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    out = compute(home=home, days=days)
    with _cache_lock:
        _cache.clear()
        _cache[key] = (time.monotonic(), out)
    return out
