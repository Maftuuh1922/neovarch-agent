"""Tempest: an opt-in, lightweight harness layer for the agent loop (Phase 1 prototype).

Off by default. ``agent.harness_mode: tempest`` in config.yaml turns it on; anything else
("legacy", empty) keeps the loop exactly as before. ``agent.tempest_profile`` picks:

* ``ringan``   (default) - offload big tool output, mask old observations, 2 verify retries;
* ``tinggi``   - no masking, larger offload threshold, 4 verify retries;
* ``otomatis`` - ringan, but masking only starts once the wire is past
                 ``agent.tempest_auto_mask_tokens`` (default 12000).

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
    return out


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
