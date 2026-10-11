"""Tempest: an opt-in, lightweight harness layer for the agent loop (Phase 1 prototype).

Off by default. ``agent.harness_mode: tempest`` in config.yaml turns it on; anything else
("legacy", empty) keeps the loop exactly as before. ``agent.tempest_profile`` picks:

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
   tail + the path (+ size) stays in context (``read_file`` is exempt: the model asked for it);
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
"""

from __future__ import annotations

import ast
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


def mode(cfg: dict) -> str:
    raw = str(_get(cfg, "agent.harness_mode", "") or "").strip().lower()
    # "tempa" is the deprecated pre-rename name of this harness; still accepted.
    return "tempest" if raw in ("tempest", "tempa") else "legacy"


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


# ------------------------------------------------------------ offload -----

def offload(result: str, name: str, call_id: str, obs_dir: Path, limit_tokens: int) -> str:
    if name == "read_file" or est_tokens(result) <= limit_tokens:
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


def run_verify(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "NEOVARCH_CORE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return True, f"(verifikasi dilewati: {exc})"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out


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
                  "skills": "Skill terpasang", "cwd": "Direktori kerja"}


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
