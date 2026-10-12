"""Tempest: the lightweight harness layer for the agent loop (Neovarch's default brain since 1.4.7).

On by default. ``agent.harness_mode: legacy`` (or ``off``/``false``) in config.yaml switches back to
the legacy loop, which is kept unchanged; an unset or empty value follows the default (Tempest).
``agent.tempest_profile`` picks:

* ``ringan``   (default) - offload big tool output, 2 verify retries;
* ``tinggi``   - larger offload threshold, 4 verify retries;
* ``otomatis`` - ringan with Phase-1 auto masking settings.

Since Fase 1 every profile compacts at the context boundary instead of masking per turn
(``agent.tempest_mask_mode: turn`` brings the Phase-1 per-turn masking back), and cache
layout v2, the delta static gate and shadow checkpoints are on; progress recitation is
opt-in. Each switch is ``agent.tempest_<name>`` (see :data:`FEATURE_DEFAULTS`).

What it does (all deterministic, zero extra LLM calls):

1. stable prompt prefix - date/time and the per-message vault notes leave the system prompt
   and ride as a tail on the user message they were computed for (stored, so the history
   is byte-identical across calls and turns -> provider prefix caches keep hitting);
2. offload - a tool result over ``offload_tokens`` is written to a file and only head +
   tail + the path (+ size) stays in context. Read-only tools (read_file, web_search, web_fetch, note
   search) are exempt since v2: they are clipped in context around the query instead, so the model never
   spends an extra read_file step on its own search result;
3. observation masking - tool results older than ``keep_turns`` assistant turns become a
   short placeholder on the wire; the boundary moves in blocks of ``mask_block`` turns so
   the prefix only changes once per block;
4. syntax check - write_file/edit_file on .py/.json/.js(.mjs/.cjs)/.ts is checked after
   writing; a broken file is restored and the error is returned;
5. verification gate - when the model wants to finish a turn that changed files, the
   detected test command runs; on failure the model is asked for a short reflection and
   a fix, at most ``verify_retries`` times, then the turn stops with an escalation note.

Fase 1 additions (each behind its own ``agent.tempest_*`` switch, see :data:`FEATURE_DEFAULTS`):

6. cache layout v2 (``tempest_cache_v2``) - the system prompt is frozen per session; later
   config changes (cwd, memory notes, skills, persona, extra prompt) ride as an appended
   "# Perubahan konfigurasi" note on the next user message instead of editing the prefix.
   Tool schemas are canonical (sorted by name, sorted JSON keys). For Anthropic-compatible
   endpoints, at most 4 ``cache_control`` breakpoints are placed (system static part, end of
   system, the previous call's last message, the last message). :func:`prefix_violation`
   is the lint that tests and the agent use to catch a prefix that changed between calls.
7. recoverable compaction (``tempest_compact``) - nothing is masked per turn; only when the
   wire crosses ``compact_at`` x the model window (default 50%) old tool outputs are swapped
   for a placeholder that keeps the path to the full text (offload file, or the file that was
   read), so the cache breaks once per compaction. Small error outputs stay ("keep the wrong
   stuff in"). Still over ``compact_target``: live file reads go too, then a deterministic
   structured summary (requests, notes, files touched/read, verify status, last errors,
   restorable paths) replaces the oldest turns. ``tempest_model_overrides`` turns it (or any
   knob) off per model glob, e.g. ``{"gemini-2.5-flash*": {"compact": false}}``.
8. delta static gate (``tempest_lint_gate``) - when the model wants to finish a turn that
   changed files, the available checkers (builtin, ruff, pyright, mypy, tsc) run on the
   changed files before and after; only NEW diagnostics block, at most ``lint_retries``
   times, out of the same retry budget as the verify gate (see tempest_lint.py).
9. shadow-git checkpoints (``tempest_checkpoints``) - a snapshot before the first modifying
   tool of a turn and at its end, tagged green/red/unknown by the verify gate, in a separate
   git dir (the user's git is untouched). When the verify gate gives up, the files go back
   to the last green checkpoint (the turn start, verified on demand); ``neovarch rewind``
   restores by hand (see tempest_ckpt.py).
10. progress + recitation (``tempest_progress``) - an ``update_plan`` tool keeps the plan per
   project (outside the repo); a new chat with an unfinished plan gets it recited on its first
   message, long sessions get it recited as a trailing note on every call, and the verify gate
   marks done items verified/unverified (see tempest_progress.py).

Fase 2 additions (the learning loop and the claim gate, all zero extra LLM calls):

11. session search (``tempest_session_search``) - a ``session_search`` tool over a local SQLite
   FTS5 index of every saved chat (tempest_search.py).
12. auto-memory (``tempest_memory_nudge``, ``tempest_memory_dedup``) - a reminder rides on the
   next user message every N turns / after a finished task; duplicate memory lines are dropped
   before they are written (tempest_memory.py).
13. skills from experience (``tempest_skill_learn``) - a verified multi-step task becomes a skill
   offer (or a draft skill in ``auto``); a skill read in a failed turn gets a fail count and a
   repair hint (tempest_skills.py).
14. claim gate (``tempest_claim_gate``) - "done/fixed/tests pass" without an execution after
   the last edit gets one correction, then an explicit "belum terverifikasi" note; every turn
   reports ``verification`` (verified/unverified/failed/none) in message.complete
   (tempest_claims.py). ``/rewind`` in a Tempest chat restores the last green checkpoint.

Prompt diet (``tempest_prompt_diet``):

15. lazy skill index + deferred tool schemas - the system prompt names the skills but leaves the
   descriptions to the per-message skill hint and the ``skill`` tool; only core tool schemas are sent
   and the rest sit behind one ``extra_tool`` (describe -> schema as a tool result, run -> unwrapped
   into the real tool). The tools array stays byte-stable per session (tempest_diet.py).
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "ringan": {"offload_tokens": 2000, "keep_turns": 6, "mask_block": 4, "verify_retries": 2,
               "mask": True, "auto_mask_tokens": 0},
    "tinggi": {"offload_tokens": 6000, "keep_turns": 10**6, "mask_block": 1, "verify_retries": 4,
               "mask": False, "auto_mask_tokens": 0},
    "otomatis": {"offload_tokens": 2000, "keep_turns": 6, "mask_block": 4, "verify_retries": 2,
                 "mask": True, "auto_mask_tokens": 12000},
}

# Fase 1 feature switches (``agent.tempest_<name>``). Defaults are only flipped on after the
# A/B replay bench shows no regression (see bench/tempest_ab.py and the Fase 1 report).
FEATURE_DEFAULTS: dict[str, Any] = {
    "cache_v2": True,              # bench: no pass change, 0 prefix breaks; Anthropic-style cost -74%
    "cache_breakpoints": "auto",   # auto | on | off  (auto = Anthropic-compatible endpoint)
    "cache_ttl": "",               # "" (5 minutes) | "1h"
    "compact": True,               # bench: +7.4 pt pass (no overflow), -28% cost vs per-turn masking
    "compact_at": 0.5,             # fraction of the model window that triggers a compaction
    "compact_target": 0.35,        # aim below this fraction after compacting
    "compact_keep_turns": 4,       # newest assistant turns whose tool outputs always stay
    "mask_mode": "",               # "" = derive (compact > turn masking > off) | turn | compact | off
    "lint_gate": True,             # delta static gate at the end of a turn (tempest_lint.py)
    "lint_retries": 1,             # how often new diagnostics block a finish (shares verify_retries)
    "lint_tools": "auto",          # auto | comma list of builtin,ruff,pyright,mypy,tsc
    "lint_timeout": 60,
    "checkpoints": True,           # shadow-git checkpoints + rollback to last green (tempest_ckpt.py)
    "checkpoint_max_files": 5000,
    "progress": False,             # opt-in: bench showed no pass gain and +3% cost (tempest_progress.py)
    "recite_after": 10,            # tool results in a session before the plan is recited every call
    # Fase 2 (learning loop + claim gate); see tempest_search / tempest_memory / tempest_skills / tempest_claims
    "session_search": True,        # session_search tool over an FTS5 index of every saved chat
    "memory_nudge": True,          # reminder (on the next user message) to persist durable facts
    "memory_nudge_every": 6,       # user turns without a memory write before a reminder
    "memory_dedup": True,          # drop memory lines that are already stored (exact / near-identical)
    "skill_learn": "offer",        # offer | auto | off: skill from a verified multi-step task
    "skill_min_steps": 5,          # tool calls a verified task needs before it is skill material
    "claim_gate": True,            # "done" claims need execution evidence after the last edit
    "claim_retries": 1,            # hidden corrections before the answer is marked unverified
    # Prompt diet: lazy skill index + deferred tool schemas behind extra_tool (tempest_diet.py)
    "prompt_diet": True,           # live bench: first prompt ~11.3K -> ~5.4K tokens, no pass loss
    # Tempest v2
    "adaptive_effort": True,       # high effort on the first step / after a failure, lighter on routine steps
    "parallel_tools": True,        # read-only tool calls of one model message run at the same time
    "ground_check": True,          # numbers in a web answer must appear in the fetched text (tempest_ground.py)
}

HEAD_LINES = 30
TAIL_LINES = 30
SYNTAX_EXTS = {".py", ".json", ".js", ".mjs", ".cjs", ".ts"}
MASK_TEXT = "[output alat lama disembunyikan untuk menghemat konteks{where}; jalankan lagi bila perlu]"


def _get(cfg: dict, dotted: str, default=None):
    """Dotted lookup; ``agent.tempest_*`` falls back to the deprecated ``agent.tempa_*`` key."""
    if dotted.startswith("agent.tempest_"):
        val = _lookup(cfg, dotted, None)
        if val is None:
            val = _lookup(cfg, "agent.tempa_" + dotted[len("agent.tempest_"):], None)
        return default if val is None else val
    return _lookup(cfg, dotted, default)


def _lookup(cfg: dict, dotted: str, default=None):
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# Values of ``agent.harness_mode`` that mean "the user turned Tempest off". Since 1.4.7 Tempest is
# the default harness, so only an explicit one of these keeps the legacy loop; an unset, empty or
# unknown value runs Tempest. YAML ``false`` / ``off`` / ``no`` arrive here as the bool False.
LEGACY_VALUES = {"legacy", "lama", "klasik", "classic", "off", "false", "0", "no", "tidak", "none", "disabled"}
DEFAULT_MODE = "tempest"


def mode(cfg: dict) -> str:
    val = _get(cfg, "agent.harness_mode", None)
    if val is False:
        return "legacy"
    raw = str(val if val is not None else "").strip().lower()
    if raw in LEGACY_VALUES:
        return "legacy"
    # "tempa" is the deprecated pre-rename name of this harness; still accepted. Empty/unset and any
    # value we do not know fall back to the default (Tempest), never silently to legacy.
    return "tempest"


def mode_is_explicit(cfg: dict) -> bool:
    """True when config.yaml names the harness itself (vs. following the shipped default)."""
    val = _get(cfg, "agent.harness_mode", None)
    return val is False or str(val if val is not None else "").strip() != ""


def settings(cfg: dict) -> dict[str, Any] | None:
    """The Tempest knobs for this config, or None in legacy mode."""
    if mode(cfg) != "tempest":
        return None
    name = str(_get(cfg, "agent.tempest_profile", "ringan") or "ringan").strip().lower()
    out = dict(PROFILES.get(name, PROFILES["ringan"]))
    out["profile"] = name if name in PROFILES else "ringan"
    for key in ("offload_tokens", "keep_turns", "mask_block", "verify_retries", "auto_mask_tokens"):
        val = _get(cfg, f"agent.tempest_{key}")
        if val not in (None, ""):
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                pass
    mask = _get(cfg, "agent.tempest_mask")
    if isinstance(mask, bool):
        out["mask"] = mask
    for key, default in FEATURE_DEFAULTS.items():
        _apply(out, key, _get(cfg, f"agent.tempest_{key}"), default)
    overrides = _get(cfg, "agent.tempest_model_overrides")
    out["model_overrides"] = overrides if isinstance(overrides, dict) else {}
    return _derive(out)


def _apply(out: dict, key: str, val: Any, default: Any) -> None:
    if isinstance(default, bool):
        out[key] = _as_bool(val, out.get(key, default))
    elif isinstance(default, float):
        try:
            out[key] = float(val) if val not in (None, "") else out.get(key, default)
        except (TypeError, ValueError):
            out[key] = out.get(key, default)
    elif isinstance(default, int):
        try:
            out[key] = int(val) if val not in (None, "") else out.get(key, default)
        except (TypeError, ValueError):
            out[key] = out.get(key, default)
    else:
        out[key] = str(val).strip().lower() if val not in (None, "") else out.get(key, default)


def _derive(out: dict) -> dict:
    """mask_mode decides between per-turn masking (Phase 1), boundary compaction and nothing."""
    mm = str(out.get("mask_mode") or "")
    if mm not in ("turn", "compact", "off"):
        mm = "compact" if out.get("compact") else ("turn" if out.get("mask") else "off")
    out["mask_mode"] = mm
    out["compact"] = mm == "compact"
    out["mask"] = mm == "turn"  # mask_wire() only masks per turn in "turn" mode
    return out


def for_model(st: dict | None, model: str) -> dict | None:
    """Apply ``agent.tempest_model_overrides`` (glob on the model id -> knob values)."""
    if not st or not st.get("model_overrides"):
        return st
    import fnmatch
    out = dict(st)
    for pat, knobs in st["model_overrides"].items():
        if isinstance(knobs, dict) and fnmatch.fnmatch(str(model or "").lower(), str(pat).lower()):
            for key, val in knobs.items():
                key = str(key).removeprefix("tempest_")
                if key in FEATURE_DEFAULTS:
                    _apply(out, key, val, FEATURE_DEFAULTS[key])
                elif key in ("mask",) and isinstance(val, bool):
                    out[key] = val
            if "compact" in knobs or "tempest_compact" in knobs:
                out["mask_mode"] = ""
    return _derive(out)


def _as_bool(val, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str) and val.strip().lower() in ("1", "true", "yes", "on", "ya"):
        return True
    if isinstance(val, str) and val.strip().lower() in ("0", "false", "no", "off", "tidak"):
        return False
    return default


def est_tokens(text: str) -> int:
    """Cheap token estimate (chars/4); good enough for thresholds."""
    return (len(text) + 3) // 4


# ------------------------------------------------------- adaptive effort -----

# The user's level -> the lighter effort used on routine steps (tool result in, next tool call out).
# The first step of a turn (planning) and any step after a failure keep the full level.
ROUTINE_EFFORT = {"ultra": "medium", "max": "medium", "xhigh": "medium", "high": "low"}
FAIL_KINDS = ("verify", "lint", "claim", "ground")
PLAN_ONCE = ("[Tempest] Penalaran tinggi: rencanakan sekali di langkah pertama (singkat, 2-6 butir), lalu eksekusi "
             "tanpa merencanakan ulang; pikirkan ulang hanya bila ada kegagalan atau temuan yang mengubah rencana.")


def step_effort(level: str, wire: str | None, messages: list[dict], last_failed: bool,
                first_step: bool) -> str | None:
    """The ``reasoning_effort`` for the next model call of a turn.

    ``level`` is the user's normalized choice (ultra/high/...), ``wire`` its full wire value. Only high
    levels adapt: lower ones are already cheap and the user picked them on purpose."""
    routine = ROUTINE_EFFORT.get(str(level or ""))
    if not wire or not routine or first_step:
        return wire
    last = messages[-1] if messages else {}
    if last.get("role") == "user":  # a gate asked for a fix, or a new message: think properly
        return wire
    if last_failed:
        return wire  # a tool of the last batch failed: this step needs real thought
    return routine


# ------------------------------------------------------------ offload -----

# Read-only tools (web, file reads, note search) are never moved to a file: the model would only have
# to spend a step reading the file back. They are clipped in context around what matches the query.
READ_ONLY_INLINE_TOKENS = 6000


def offload(result: str, name: str, call_id: str, obs_dir: Path, limit_tokens: int, query: str = "") -> str:
    from neovarch.tools import READ_ONLY_TOOLS
    if name in READ_ONLY_TOOLS:
        if name == "read_file":
            return result  # the model asked for exactly this range
        cap = max(int(limit_tokens) * 3, READ_ONLY_INLINE_TOKENS)
        if est_tokens(result) <= cap:
            return result
        from neovarch import web
        return web.smart_clip(result, query, cap * 4)
    if est_tokens(result) <= limit_tokens:
        return result
    obs_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{call_id}")[:80] or "obs"
    path = obs_dir / f"{safe}.txt"
    path.write_text(result, encoding="utf-8")
    lines = result.splitlines()
    if len(lines) > HEAD_LINES + TAIL_LINES:
        head = "\n".join(_cut(l) for l in lines[:HEAD_LINES])
        tail = "\n".join(_cut(l) for l in lines[-TAIL_LINES:])
        body = f"{head}\n… [{len(lines) - HEAD_LINES - TAIL_LINES} baris di tengah disimpan di file] …\n{tail}"
    else:  # few, very long lines
        body = result[:3000] + f"\n… [{len(result) - 6000} karakter disimpan di file] …\n" + result[-3000:]
    return (f"[output besar: {len(lines)} baris, {len(result)} karakter, ~{est_tokens(result)} token. "
            f"Lengkapnya di {path} — pakai read_file (offset/limit) atau shell grep pada file itu.]\n{body}")


def _cut(line: str, n: int = 300) -> str:
    return line if len(line) <= n else line[:n] + " …"


# ------------------------------------------------------------ masking -----

def mask_wire(wire: list[dict], st: dict[str, Any]) -> list[dict]:
    """Replace tool results older than keep_turns assistant turns with a placeholder.

    ``wire`` is the provider message list (system first). The boundary snaps to multiples
    of mask_block so the prefix stays identical for mask_block calls in a row."""
    if not st.get("mask"):
        return wire
    if st.get("auto_mask_tokens"):
        total = sum(est_tokens(str(m.get("content") or "")) for m in wire)
        if total < st["auto_mask_tokens"]:
            return wire
    asst = [i for i, m in enumerate(wire) if m.get("role") == "assistant"]
    keep, block = max(int(st["keep_turns"]), 0), max(int(st["mask_block"]), 1)
    n_old = len(asst) - keep
    if n_old <= 0:
        return wire
    n_old = (n_old // block) * block
    if n_old <= 0:
        return wire
    # tool results answering the n_old oldest assistant turns sit before the next assistant turn
    nxt = asst[n_old] if n_old < len(asst) else len(wire)
    live = _live_reads(wire)
    out = []
    for i, m in enumerate(wire):
        if m.get("role") == "tool" and i < nxt and m.get("tool_call_id") not in live:
            content = str(m.get("content") or "")
            if est_tokens(content) > 60:
                where = ""
                hit = re.search(r"Lengkapnya di (\S+)", content)
                if hit:
                    where = f"; lengkapnya di {hit.group(1)}"
                m = {**m, "content": MASK_TEXT.format(where=where)}
        out.append(m)
    return out


def _live_reads(wire: list[dict]) -> set[str]:
    """read_file results still current: the same path was not written, edited or re-read later.

    Masking those only makes the model read the file again before editing it."""
    calls: list[tuple[str, str, str]] = []  # (call_id, tool, path) in order
    for m in wire:
        for c in m.get("tool_calls") or []:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            path = str(args.get("path") or "") if isinstance(args, dict) else ""
            calls.append((str(c.get("id") or ""), str(fn.get("name") or ""), path))
    live = set()
    for idx, (cid, name, path) in enumerate(calls):
        if name != "read_file" or not path:
            continue
        if not any(p == path and n in ("read_file", "write_file", "edit_file") for _, n, p in calls[idx + 1:]):
            live.add(cid)
    return live


# ------------------------------------------------------- syntax check -----

def syntax_error(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext not in SYNTAX_EXTS or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if ext == ".py":
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            return f"{type(exc).__name__}: {exc.msg} (baris {exc.lineno}, kolom {exc.offset})"
        return None
    if ext == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return f"JSONDecodeError: {exc.msg} (baris {exc.lineno}, kolom {exc.colno})"
        return None
    node = shutil.which("node")
    if not node:
        return None  # no checker available: skip rather than block
    cmd = [node, "--check", str(path)]
    if ext == ".ts":
        cmd = [node, "--experimental-strip-types", "--check", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if proc.returncode == 0:
        return None
    err = (proc.stderr or proc.stdout).strip()
    if ext == ".ts" and ("bad option" in err or "unknown" in err.lower() and "option" in err.lower()):
        return None  # old node without type stripping
    lines = [l for l in err.splitlines() if l.strip()]
    return "\n".join(lines[:6])


# ----------------------------------------------------- verification gate -----

def _python() -> str:
    """The project's python (PATH), not the core's own interpreter (may be a frozen app)."""
    import sys
    return shutil.which("python3") or shutil.which("python") or sys.executable


_PYTEST_OK: dict[str, bool] = {}


def pytest_available(python: str) -> bool:
    """Can this interpreter run pytest? (cached; a PC without pytest gets no pytest verify gate)"""
    if python not in _PYTEST_OK:
        try:
            r = subprocess.run([python, "-c", "import pytest"], capture_output=True, timeout=30)
            _PYTEST_OK[python] = r.returncode == 0
        except Exception:
            _PYTEST_OK[python] = False
    return _PYTEST_OK[python]


def detect_verify(cwd: Path) -> list[str] | None:
    """A test command for the project at cwd, or None."""
    cwd = Path(cwd)
    if (cwd / "pytest.ini").exists() or (cwd / "tests").is_dir() or (cwd / "conftest.py").exists() \
            or any(cwd.glob("test_*.py")):
        return [_python(), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    pyproject = cwd / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8", errors="replace"):
        return [_python(), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    pkg = cwd / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
        except Exception:
            scripts = {}
        test = str(scripts.get("test") or "")
        if test and "no test specified" not in test:
            return ["npm", "test", "--silent"]
    return None


# Processes started by the gate running in this context (see :func:`killable`). asyncio.to_thread
# copies the caller's context into the worker thread, so run_proc() there registers into the
# list the awaiting coroutine owns, and a Stop (task cancel) can kill them.
_GATE_PROCS: contextvars.ContextVar[list | None] = contextvars.ContextVar("tempest_gate_procs", default=None)


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=5)
        else:
            os.killpg(proc.pid, 9)  # the whole test run (pytest workers, npm children), not only the parent
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_proc(cmd: list[str], *, cwd: Path | str | None = None, timeout: float, env: dict | None = None
             ) -> subprocess.CompletedProcess:
    """``subprocess.run(capture_output=True, text=True)`` that a Stop can kill, child processes included.

    Raises ``subprocess.TimeoutExpired`` like subprocess.run (after killing the process tree)."""
    kw: dict[str, Any] = {"cwd": str(cwd) if cwd is not None else None, "stdout": subprocess.PIPE,
                          "stderr": subprocess.PIPE, "text": True, "errors": "replace", "env": env}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    group = _GATE_PROCS.get()
    if group is not None:
        group.append(proc)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            raise
    finally:
        if group is not None and proc in group:
            group.remove(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


async def killable(fn, *args):
    """Run a blocking gate (verify / lint) in a worker thread. When the awaiting task is cancelled
    (Stop), every process the gate started is killed right away instead of running to its timeout."""
    group: list = []
    token = _GATE_PROCS.set(group)
    try:
        return await asyncio.to_thread(fn, *args)
    except asyncio.CancelledError:
        for proc in list(group):
            _kill_tree(proc)
        raise
    finally:
        _GATE_PROCS.reset(token)


def run_verify(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[bool | None, str]:
    """(True, out) passed, (False, out) failed, (None, why) could not run at all: no verdict.

    "Could not run" (runner missing, pytest not installed, no tests collected) must never count
    as a failure: before 1.4.7 a PC without pytest failed every gated turn and rolled it back."""
    is_pytest = len(cmd) >= 3 and cmd[1:3] == ["-m", "pytest"]
    if is_pytest and not pytest_available(cmd[0]):
        return None, f"(verifikasi dilewati: pytest tidak terpasang untuk {cmd[0]})"
    # A fresh, empty bytecode cache per run. Python (and pytest's assertion
    # rewriter) trust a __pycache__ entry whose recorded source mtime (whole
    # seconds) and size still match; an edit within the same second that keeps
    # the size ("return 2" -> "return 4") then ran the OLD code and the gate
    # passed a broken change. PYTHONDONTWRITEBYTECODE alone only stops writes,
    # stale entries left by an earlier shell `pytest` were still read.
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="nv-verify-pyc-") as pyc:
            proc = run_proc(cmd, cwd=cwd, timeout=timeout,
                            env={**os.environ, "NEOVARCH_CORE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                                 "PYTHONPYCACHEPREFIX": pyc})
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (FileNotFoundError, PermissionError) as exc:
        return None, f"(verifikasi dilewati: {exc})"
    out = (proc.stdout or "") + (proc.stderr or "")
    if is_pytest and proc.returncode == 5:  # pytest: no tests collected
        return None, "(verifikasi dilewati: tidak ada tes yang terkumpul)\n" + out[-500:]
    return proc.returncode == 0, out


_FAILED_ID = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def failing_ids(out: str) -> set[str]:
    """Test ids pytest reports as FAILED/ERROR (empty for other runners)."""
    return {m.group(1) for m in _FAILED_ID.finditer(out or "")}


def same_failure(now: set[str], before: set[str]) -> bool:
    """The failure now is (one of) the failures from before the turn. Without test ids (npm and
    other runners) a red start is taken as the same failure."""
    return not (now and before and not (now & before))


PRE_EXISTING_PROMPT = ("\n\nCatatan: tes ini sudah gagal SEBELUM perubahan di turn ini. Kalau memperbaikinya memang bagian "
                       "dari permintaan pengguna, perbaiki. Kalau tidak terkait, jangan diubah: jawab saja dan sebutkan "
                       "bahwa tes itu sudah gagal sebelumnya.")


def pre_existing_note(cmd: list[str], summary: str) -> str:
    return (f"\n\nℹ️ Tes proyek ({' '.join(cmd)}) sudah gagal sebelum perubahan di turn ini, dengan kegagalan "
            "yang sama, jadi tidak dianggap akibat perubahan ini (file tidak dikembalikan). "
            "Perubahan ini belum terverifikasi oleh tes.\n" + "\n".join(summary.splitlines()[-6:]))


def failure_summary(out: str, max_lines: int = 40) -> str:
    lines = out.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    half = max_lines // 2
    return "\n".join(lines[:half] + [f"… [{len(lines) - max_lines} baris] …"] + lines[-half:])


def verify_prompt(cmd: list[str], summary: str, attempt: int, retries: int) -> str:
    return (f"[verifikasi otomatis gagal — percobaan {attempt}/{retries}]\n"
            f"Perintah: {' '.join(cmd)}\n{summary}\n\n"
            "Sebelum menjawab selesai: tulis refleksi singkat (maks 5 baris: penyebab, apa yang dicoba beda), "
            "lalu perbaiki dan pastikan tesnya lulus.")


def escalation_note(cmd: list[str], summary: str, retries: int) -> str:
    return (f"\n\n⚠️ Verifikasi masih gagal setelah {retries} percobaan perbaikan ({' '.join(cmd)}). "
            "Berhenti di sini; perlu dicek manual atau dilanjutkan dengan model yang lebih kuat.\n"
            + "\n".join(summary.splitlines()[-8:]))


def save_reflection(notes_dir: Path, session_id: str, text: str) -> None:
    try:
        notes_dir.mkdir(parents=True, exist_ok=True)
        with (notes_dir / f"{session_id or 'session'}.md").open("a", encoding="utf-8") as fh:
            fh.write(text.strip() + "\n\n")
    except OSError:
        pass


# ------------------------------------------------------ cache layout v2 -----

def canonical(obj: Any) -> Any:
    """The same value with every dict's keys in sorted order (JSON bytes become stable)."""
    if isinstance(obj, dict):
        return {k: canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [canonical(v) for v in obj]
    return obj


def stable_tools(tools: list[dict]) -> list[dict]:
    """Tool schemas in a deterministic order (by name) with canonical key order."""
    def name(t: dict) -> str:
        return str(((t or {}).get("function") or {}).get("name") or "")
    return [canonical(t) for t in sorted(tools or [], key=name)]


SECTION_TITLES = {"soul": "Persona dasar (SOUL)", "app": "Tentang aplikasi", "persona": "Identitas",
                  "extra": "Instruksi tambahan", "memory": "Catatan memori", "vault": "Obsidian vault",
                  "skills": "Skill terpasang", "platform": "PC ini", "cwd": "Direktori kerja"}


def config_change_note(old: list, new: list) -> str:
    """What changed between two system-prompt section lists, as an append-only note.

    The model reads it as overriding the same section in the (frozen) system prompt."""
    o, n = dict((k, v) for k, v in old), dict((k, v) for k, v in new)
    parts = []
    for key, text in new:
        if o.get(key) != text:
            parts.append(f"## {SECTION_TITLES.get(key, key)} (baru)\n{text}")
    for key, _ in old:
        if key not in n:
            parts.append(f"## {SECTION_TITLES.get(key, key)}: dihapus")
    if not parts:
        return ""
    return ("# Perubahan konfigurasi (berlaku mulai pesan ini; menggantikan bagian yang sama di prompt sistem)\n"
            + "\n\n".join(parts))


def wants_breakpoints(st: dict | None, endpoint: dict) -> bool:
    """Explicit cache_control breakpoints: only for Anthropic-compatible endpoints (or forced)."""
    if not st or not st.get("cache_v2"):
        return False
    mode_ = str(st.get("cache_breakpoints") or "auto")
    if mode_ in ("off", "false", "0"):
        return False
    if mode_ in ("on", "true", "1"):
        return True
    model = str(endpoint.get("model") or "").lower()
    base = str(endpoint.get("base_url") or "").lower()
    prov = str(endpoint.get("provider") or "").lower()
    return "claude" in model or "anthropic" in model or "anthropic" in base or prov == "anthropic"


MAX_BREAKPOINTS = 4


def _parts(content: Any) -> list[dict] | None:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [dict(p) for p in content]
    return None


def place_breakpoints(wire: list[dict], system_split: int | None, prev_last: int | None,
                      ttl: str = "") -> list[dict]:
    """A copy of ``wire`` with at most 4 Anthropic ``cache_control`` breakpoints.

    Every text content becomes a list of parts (always, so the bytes do not depend on
    where a breakpoint sits). Breakpoints: (1) after the static part of the system prompt
    (``system_split`` chars), (2) end of the system prompt, (3) the message that was last
    in the previous call (its write is read back exactly), (4) the last message."""
    mark: dict[str, str] = {"type": "ephemeral"}
    if ttl == "1h":
        mark["ttl"] = "1h"
    out = []
    for m in wire:
        c = _parts(m.get("content"))
        out.append({**m, "content": c} if c is not None else dict(m))
    budget = MAX_BREAKPOINTS
    if out and out[0].get("role") == "system" and out[0]["content"]:
        text = "".join(p.get("text", "") for p in out[0]["content"])
        if system_split and 0 < system_split < len(text):
            out[0]["content"] = [{"type": "text", "text": text[:system_split], "cache_control": dict(mark)},
                                 {"type": "text", "text": text[system_split:], "cache_control": dict(mark)}]
            budget -= 2
        else:
            out[0]["content"] = [{"type": "text", "text": text, "cache_control": dict(mark)}]
            budget -= 1

    def markable(i: int) -> int | None:
        while i > 0:
            if out[i].get("content") and isinstance(out[i]["content"], list):
                return i
            i -= 1
        return None
    targets = []
    last = markable(len(out) - 1)
    if last is not None:
        targets.append(last)
    if prev_last is not None and prev_last < len(out):
        pl = markable(prev_last)
        if pl is not None and pl not in targets:
            targets.append(pl)
    for i in sorted(targets)[-budget:] if budget > 0 else []:
        parts = out[i]["content"]
        parts[-1] = {**parts[-1], "cache_control": dict(mark)}
    return out


def count_breakpoints(wire: list[dict]) -> int:
    n = 0
    for m in wire:
        if isinstance(m.get("content"), list):
            n += sum(1 for p in m["content"] if isinstance(p, dict) and p.get("cache_control"))
    return n


def _strip_marks(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        c = [{k: v for k, v in p.items() if k != "cache_control"} if isinstance(p, dict) else p for p in c]
    return json.dumps({**m, "content": c}, ensure_ascii=False, sort_keys=True)


def prefix_violation(prev: list[dict] | None, cur: list[dict]) -> int | None:
    """Prefix lint: index of the first message of the previous call (excluding its last
    message, which may carry an ephemeral tail) that is not byte-identical in this call.

    None when the previous wire is a clean prefix. cache_control markers are ignored
    (providers do not hash them)."""
    if not prev:
        return None
    for i, m in enumerate(prev[:-1]):
        if i >= len(cur) or _strip_marks(m) != _strip_marks(cur[i]):
            return i
    return None


def cached_tokens(usage: dict | None) -> int:
    """Cache-read tokens a provider reported (OpenAI-style or Anthropic-style usage)."""
    u = usage or {}
    det = u.get("prompt_tokens_details") or {}
    for v in (det.get("cached_tokens") if isinstance(det, dict) else None, u.get("cache_read_input_tokens"),
              u.get("cached_tokens")):
        try:
            if v is not None:
                return int(v)
        except (TypeError, ValueError):
            continue
    return 0


# ------------------------------------------------- recoverable compaction -----

COMPACT_PLACEHOLDER = "[output alat lama dipindah ke {path} (~{n} token{desc}); baca ulang dengan read_file bila perlu]"
SUMMARY_MARK = "[ringkasan terstruktur — konteks lama dipadatkan otomatis"


def wire_tokens(wire: list[dict], tools: list[dict] | None = None) -> int:
    """Cheap size of a request: chars/4 over message contents, tool calls and tool schemas."""
    n = est_tokens(json.dumps(tools, ensure_ascii=False)) if tools else 0
    for m in wire:
        c = m.get("content")
        if isinstance(c, list):
            n += sum(est_tokens(str(p.get("text") or "")) for p in c if isinstance(p, dict)) + 4
        else:
            n += est_tokens(str(c or "")) + 4
        for tc in m.get("tool_calls") or []:
            n += est_tokens(json.dumps(tc, ensure_ascii=False))
    return n


def apply_compaction(wire: list[dict], state: dict | None) -> list[dict]:
    """Rebuild the compacted wire from the stored compaction state (deterministic, so the
    prefix is identical on every call between two compactions).

    ``wire`` is [system] + one wire message per stored message, in order."""
    if not state:
        return wire
    masked = state.get("masked") or {}
    upto = int(state.get("summary_upto") or 0)
    out = [wire[0]]
    if upto and state.get("summary"):
        out.append({"role": "user", "content": state["summary"]})
    for i, m in enumerate(wire[1:]):
        if i < upto:
            continue
        if m.get("role") == "tool" and m.get("tool_call_id") in masked:
            m = {**m, "content": masked[m["tool_call_id"]]}
        out.append(m)
    return out


def _is_error_output(text: str) -> bool:
    head = text[:400]
    return (head.startswith(("error", "rejected", "refused", "Traceback")) or "Traceback (most recent call last)" in text
            or bool(re.search(r"\b\d+ failed\b|\bFAILED\b|Error:", text)))


def _call_index(messages: list[dict]) -> dict[str, tuple[str, dict]]:
    out = {}
    for m in messages:
        for c in m.get("tool_calls") or []:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            out[str(c.get("id") or "")] = (str(fn.get("name") or ""), args if isinstance(args, dict) else {})
    return out


def compact(messages: list[dict], state: dict | None, st: dict, window: int, obs_dir: Path,
            measure) -> tuple[dict, dict]:
    """One compaction pass. ``measure(state) -> tokens`` sizes the wire under a candidate state.

    Returns (new_state, report). Stages: 1) mask old tool outputs except live reads and small
    errors; 2) mask live reads, oldest first; 3) structured summary of the oldest turns."""
    state = {"masked": dict((state or {}).get("masked") or {}), "summary": (state or {}).get("summary") or "",
             "summary_upto": int((state or {}).get("summary_upto") or 0), "epoch": int((state or {}).get("epoch") or 0) + 1}
    target = int(window * float(st.get("compact_target") or 0.35))
    before = measure(state)
    calls = _call_index(messages)
    asst = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    keep = max(int(st.get("compact_keep_turns") or 4), 1)
    cut = asst[-keep] if len(asst) >= keep else 0  # tool outputs before this index may go
    wire_like = [{"role": "system", "content": ""}] + [dict(m) for m in messages]
    live = _live_reads(wire_like)
    stage = 0

    def mask_one(m: dict) -> None:
        cid = str(m.get("tool_call_id") or "")
        name, args = calls.get(cid, (str(m.get("name") or "tool"), {}))
        content = str(m.get("content") or "")
        n = est_tokens(content)
        hit = re.search(r"Lengkapnya di (\S+)", content)
        if name == "read_file" and args.get("path"):
            path, desc = str(args["path"]), "; isi file yang dibaca"
        elif hit:
            path, desc = hit.group(1), f"; {name}"
        else:
            obs_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{cid}")[:80] or "obs"
            dest = obs_dir / f"{safe}.txt"
            if not dest.exists():
                dest.write_text(content, encoding="utf-8")
            path, desc = str(dest), f"; {name}"
        preview = str(args.get("command") or args.get("path") or args.get("query") or "")[:80]
        if preview and name != "read_file":
            desc += f" `{preview}`"
        state["masked"][cid] = COMPACT_PLACEHOLDER.format(path=path, n=n, desc=desc)

    def candidates(include_live: bool) -> list[dict]:
        out = []
        for i, m in enumerate(messages[:cut]):
            if i < state["summary_upto"] or m.get("role") != "tool":
                continue
            cid = str(m.get("tool_call_id") or "")
            content = str(m.get("content") or "")
            if cid in state["masked"] or est_tokens(content) <= 60:
                continue
            if _is_error_output(content) and est_tokens(content) <= 400:
                continue  # keep the wrong stuff in: small failures stay visible
            if cid in live and not include_live:
                continue
            out.append(m)
        return out

    for m in candidates(False):
        mask_one(m)
        stage = 1
    if measure(state) > target:
        for m in candidates(True):
            mask_one(m)
            stage = 2
            if measure(state) <= target:
                break
    if measure(state) > target and cut > 0:
        state["summary"] = structured_summary(messages[:cut], state, calls)
        state["summary_upto"] = cut
        stage = 3
    return state, {"stage": stage, "before": before, "after": measure(state), "epoch": state["epoch"],
                   "masked": len(state["masked"])}


def structured_summary(old: list[dict], state: dict, calls: dict) -> str:
    """Deterministic (no LLM) anchor summary of the turns being collapsed."""
    users = [str(m.get("content") or "") for m in old if m.get("role") == "user" and m.get("kind") not in ("verify", "lint")]
    notes = [str(m.get("content") or "").strip() for m in old if m.get("role") == "assistant" and m.get("content")]
    touched, reads, errors, paths = [], [], [], []
    for m in old:
        for c in m.get("tool_calls") or []:
            name, args = calls.get(str(c.get("id") or ""), ("", {}))
            p = str(args.get("path") or "")
            if name in ("write_file", "edit_file") and p and p not in touched:
                touched.append(p)
            if name == "read_file" and p:
                if p in reads:
                    reads.remove(p)
                reads.append(p)
        if m.get("role") == "tool":
            text = str(state["masked"].get(m.get("tool_call_id")) or m.get("content") or "")
            hit = re.search(r"dipindah ke (\S+)", text) or re.search(r"Lengkapnya di (\S+)", text)
            if hit and hit.group(1) not in paths:
                paths.append(hit.group(1))
            raw = str(m.get("content") or "")
            if _is_error_output(raw):
                errors.append("\n".join(raw.strip().splitlines()[:3])[:300])
    verify = [str(m.get("content") or "").splitlines()[0] for m in old if m.get("kind") in ("verify", "lint")]
    lines = [SUMMARY_MARK + "; detail lengkap tetap bisa dibaca ulang dari path di bawah]"]
    if users:
        lines.append("## Permintaan pengguna")
        lines += [f"- {u[:500]}" for u in users[:-1][-5:]]
        lines.append(f"- (terbaru) {users[-1][:2000]}")
    if notes:
        lines.append("## Catatan & keputusan asisten")
        lines += [f"- {n[:300]}" for n in notes[-15:]]
    if touched:
        lines.append("## File yang diubah\n" + "\n".join(f"- {p}" for p in touched[-20:]))
    if reads:
        lines.append("## File terakhir dibaca\n" + "\n".join(f"- {p}" for p in reads[-8:]))
    lines.append("## Status verifikasi\n- " + (verify[-1] if verify else "belum ada umpan balik verifikasi"))
    if errors:
        lines.append("## Error terakhir\n" + "\n".join(f"- {e}" for e in errors[-3:]))
    if paths:
        lines.append("## Output yang dipindah (bisa dibaca ulang)\n" + "\n".join(f"- {p}" for p in paths[-20:]))
    return "\n".join(lines)
