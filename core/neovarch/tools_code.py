"""Coding tools: a forgiving ``edit_file`` engine, ``grep``/``glob`` and background shell jobs.

Written for cheap models, which are the ones Neovarch usually runs on:

* **edit engine** - exact match first; when that fails, a unique match that ignores
  trailing whitespace / line endings / smart quotes, then one that also ignores indentation
  (``new_text`` is re-indented to the file). Several edits of one file go in one call
  (``edits``), all-or-nothing. A miss names the closest region (with line numbers) and a
  non-unique match names every line it occurs on, so the next try lands instead of a
  ``read_file`` round trip. The reply carries a few numbered lines around the change.
* **grep / glob** - ripgrep when it is installed (respects .gitignore), a pure-Python walk
  otherwise (Windows without rg); results are capped and relative to the working folder.
  Both are read-only, so Tempest runs them in parallel with other reads.
* **background jobs** - ``shell(background=true)`` starts a command whose output goes to a
  log file and returns at once; ``shell_job`` lists, reads (new output only), waits for or
  kills it. Foreground ``shell`` keeps the output it got when it times out.
"""

from __future__ import annotations

import asyncio
import atexit
import difflib
import os
import re
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ------------------------------------------------------------ edit engine -----

_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\t": "    "})


class EditError(ValueError):
    pass


def _norm_soft(line: str) -> str:
    """Trailing whitespace, CR, smart quotes and tabs-vs-spaces do not count."""
    return line.rstrip().translate(_QUOTES)


def _norm_loose(line: str) -> str:
    """Also ignore indentation."""
    return _norm_soft(line).strip()


def _line_spans(text: str) -> list[tuple[int, int]]:
    """(start, end-without-newline) of every line."""
    spans, pos = [], 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        spans.append((pos, pos + len(body)))
        pos += len(line)
    return spans


def _indent(s: str) -> str:
    return s[:len(s) - len(s.lstrip(" \t"))]


def _fuzzy(text: str, old: str, norm) -> list[tuple[int, int, str]]:
    """Line-window matches of ``old`` in ``text`` under ``norm``: (start, end, file_first_line)."""
    old_lines = old.strip("\r\n").splitlines()
    while old_lines and not old_lines[0].strip():
        old_lines.pop(0)
    while old_lines and not old_lines[-1].strip():
        old_lines.pop()
    if not old_lines:
        return []
    want = [norm(x) for x in old_lines]
    spans = _line_spans(text)
    lines = [text[a:b] for a, b in spans]
    got = [norm(x) for x in lines]
    n, out = len(want), []
    for i in range(len(lines) - n + 1):
        if got[i:i + n] == want:
            out.append((spans[i][0], spans[i + n - 1][1], lines[i]))
    return out


def _reindent(new: str, old: str, file_first: str) -> str:
    """Shift ``new`` by the indentation difference between ``old`` and the file."""
    first_old = next((x for x in old.splitlines() if x.strip()), "")
    first_new = next((x for x in new.splitlines() if x.strip()), "")
    have, want = _indent(first_old), _indent(file_first)
    if have == want or _indent(first_new) != have:
        return new  # same indent, or new_text already carries its own (e.g. only old_text was dedented)
    out = []
    for line in new.splitlines(keepends=True):
        if not line.strip():
            out.append(line)
        elif line.startswith(have):
            out.append(want + line[len(have):])
        else:
            out.append(want + line.lstrip(" \t") if not have else line)
    return "".join(out)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _closest(text: str, old: str) -> str:
    """'closest match' hint: the window of the file most similar to ``old``."""
    old_lines = [x for x in old.strip("\r\n").splitlines()]
    lines = text.splitlines()
    if not old_lines or not lines:
        return ""
    n = len(old_lines)
    target = "\n".join(_norm_loose(x) for x in old_lines)
    first = _norm_loose(next((x for x in old_lines if x.strip()), ""))
    best, best_i = 0.0, -1
    limit = min(len(lines), 6000)
    for i in range(0, max(limit - n + 1, 1)):
        # Cheap pre-filter: the window has to share something with the first non-blank line.
        if first and difflib.SequenceMatcher(None, first, _norm_loose(lines[i]), autojunk=False).quick_ratio() < 0.5:
            if n == 1 or difflib.SequenceMatcher(None, first, _norm_loose(lines[min(i + 1, len(lines) - 1)]),
                                                 autojunk=False).quick_ratio() < 0.5:
                continue
        window = "\n".join(_norm_loose(x) for x in lines[i:i + n])
        r = difflib.SequenceMatcher(None, target, window, autojunk=False).ratio()
        if r > best:
            best, best_i = r, i
    if best_i < 0 or best < 0.5:
        return ""
    end = min(best_i + max(n, 1), len(lines))
    shown = lines[best_i:min(end, best_i + 12)]
    body = "\n".join(f"{j:>6}\t{x[:300]}" for j, x in enumerate(shown, best_i + 1))
    return f"\nClosest match (lines {best_i + 1}-{end}, {best:.0%} similar) - copy old_text from here:\n{body}"


def apply_edit(text: str, old: str, new: str, replace_all: bool = False) -> tuple[str, int, str, int]:
    """Apply one edit. Returns (new_text, replacements, how, first_changed_offset).

    ``how`` is "" for an exact match, otherwise which tolerance matched."""
    crlf = "\r\n" in text
    if crlf and "\r\n" not in new:
        new = new.replace("\n", "\r\n")
    candidates = [old]
    if crlf and "\r\n" not in old and "\n" in old:
        candidates.append(old.replace("\n", "\r\n"))
    for cand in candidates:
        count = text.count(cand)
        if count == 1 or (count > 1 and replace_all):
            pos = text.find(cand)
            return (text.replace(cand, new) if replace_all else text.replace(cand, new, 1)), \
                (count if replace_all else 1), "", pos
        if count > 1:
            where = []
            i = text.find(cand)
            while i >= 0 and len(where) < 12:
                where.append(str(_line_of(text, i)))
                i = text.find(cand, i + 1)
            raise EditError(f"old_text occurs {count} times (lines {', '.join(where)}); include more surrounding "
                            "lines so it is unique, or set replace_all=true")
    for norm, how in ((_norm_soft, "ignoring trailing whitespace/quotes"), (_norm_loose, "ignoring indentation")):
        hits = _fuzzy(text, old, norm)
        if not hits:
            continue
        if len(hits) > 1 and not replace_all:
            where = ", ".join(str(_line_of(text, a)) for a, _, _ in hits[:12])
            raise EditError(f"old_text matches {len(hits)} places when {how} (lines {where}); include more "
                            "surrounding lines so it is unique, or set replace_all=true")
        body = new.strip("\r\n") if new.strip("\r\n") else ""
        out, last = [], 0
        for a, b, first_line in hits:
            rep = _reindent(body, old, first_line) if norm is _norm_loose else body
            out.append(text[last:a])
            if rep:
                out.append(rep)
                last = b
            else:  # deleting whole lines: take the newline with them
                last = b + (2 if text.startswith("\r\n", b) else 1 if text.startswith("\n", b) else 0)
        out.append(text[last:])
        return "".join(out), len(hits), how, hits[0][0]
    raise EditError("old_text was not found in the file" + _closest(text, old))


def snippet(text: str, pos: int, new_len: int, around: int = 2, cap: int = 14) -> str:
    """Numbered lines around a change (what the file looks like now)."""
    lines = text.splitlines()
    if not lines:
        return ""
    first = _line_of(text, pos)
    last = _line_of(text, pos + max(new_len, 0))
    lo, hi = max(first - around, 1), min(last + around, len(lines))
    if hi - lo + 1 > cap:
        hi = lo + cap - 1
    return "\n".join(f"{i:>6}\t{lines[i - 1][:240]}" for i in range(lo, hi + 1))


def edit_text(text: str, edits: list[dict]) -> tuple[str, int, list[str], tuple[int, int]]:
    """All edits in order on an in-memory text; any failure raises (nothing is written)."""
    total, notes, focus = 0, [], (0, 0)
    for i, e in enumerate(edits, 1):
        if not isinstance(e, dict):
            raise EditError(f"edit {i}: expected an object with old_text/new_text")
        old = str(e.get("old_text") if e.get("old_text") is not None else e.get("old_string") or "")
        new = str(e.get("new_text") if e.get("new_text") is not None else e.get("new_string") or "")
        if not old:
            raise EditError(f"edit {i}: old_text is required (to create a file use write_file)")
        if old == new:
            raise EditError(f"edit {i}: old_text and new_text are identical")
        try:
            text, n, how, pos = apply_edit(text, old, new, bool(e.get("replace_all")))
        except EditError as exc:
            pre = f"edit {i} of {len(edits)}: " if len(edits) > 1 else ""
            raise EditError(pre + str(exc)) from None
        total += n
        if how:
            notes.append(f"edit {i} matched {how}" if len(edits) > 1 else f"matched {how}")
        if i == 1:
            focus = (pos, len(new))
    return text, total, notes, focus


# --------------------------------------------------------------- grep/glob -----

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", ".tox", "dist", "build", ".next", "target", ".gradle", ".dart_tool", ".idea"}
MAX_FILE_BYTES = 2_000_000
LINE_CHARS = 300


def glob_regex(pattern: str) -> re.Pattern:
    """gitignore-style glob -> regex over a relative posix path. A pattern without '/' matches the
    file name at any depth (what ripgrep's -g does)."""
    pat = pattern.strip().lstrip("./") if pattern.strip().startswith("./") else pattern.strip()
    if "/" not in pat:
        pat = "**/" + pat
    out, i = "", 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pat.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "{":
            j = pat.find("}", i)
            if j > i:
                out += "(?:" + "|".join(re.escape(x) for x in pat[i + 1:j].split(",")) + ")"
                i = j + 1
                continue
            out += re.escape(c)
        elif c == "[":
            j = pat.find("]", i)
            if j > i:
                out += pat[i:j + 1]
                i = j + 1
                continue
            out += re.escape(c)
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


def walk_files(root: Path, pattern: str | None = None):
    """Files under root (skipping VCS/dependency/build dirs), optionally filtered by a glob."""
    rx = glob_regex(pattern) if pattern else None
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d in (".github",))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if rx is not None and not rx.match(p.relative_to(root).as_posix()):
                continue
            yield p


def _rel(p: Path | str, cwd: Path) -> str:
    try:
        return Path(p).resolve().relative_to(cwd.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def _is_binary(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return b"\0" in f.read(4096)
    except OSError:
        return True


def rg_excludes(root: Path) -> list[str]:
    """Same skip list as the Python walk (rg alone only honours .gitignore inside a git repo)."""
    if any(part in SKIP_DIRS for part in root.parts):
        return ["--no-require-git"]
    return ["--no-require-git"] + [x for d in sorted(SKIP_DIRS) for x in ("-g", f"!{d}/")]


def rg_path() -> str | None:
    if os.environ.get("NEOVARCH_NO_RG"):
        return None
    return shutil.which("rg")


async def _run(argv: list[str], cwd: Path, timeout: float = 20) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, (out or b"").decode("utf-8", "replace") + (err or b"").decode("utf-8", "replace")


def _py_grep(rx: re.Pattern, root: Path, glob: str | None, mode: str, context: int, cap: int,
             show) -> tuple[list[str], int]:
    out, total = [], 0
    for p in walk_files(root, glob):
        try:
            if p.stat().st_size > MAX_FILE_BYTES or _is_binary(p):
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        hits = [i for i, line in enumerate(lines) if rx.search(line)]
        if not hits:
            continue
        rel = show(p)
        if mode == "files":
            total += 1
            if len(out) < cap:
                out.append(rel)
            continue
        if mode == "count":
            total += 1
            if len(out) < cap:
                out.append(f"{rel}:{len(hits)}")
            continue
        shown: set[int] = set()
        for i in hits:
            total += 1
            for j in range(max(i - context, 0), min(i + context + 1, len(lines))):
                if j in shown or len(out) >= cap:
                    continue
                shown.add(j)
                sep = ":" if j == i or j in hits else "-"
                out.append(f"{rel}{sep}{j + 1}{sep}{lines[j][:LINE_CHARS]}")
    return out, total


async def grep(args: dict, cwd: Path, resolve) -> str:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        return "error: pattern is required"
    root = resolve(str(args.get("path") or ".")) if args.get("path") else cwd
    if not root.exists():
        return f"error: not found: {root}"
    mode = str(args.get("output") or args.get("output_mode") or "content").lower()
    mode = {"files_with_matches": "files", "files": "files", "count": "count"}.get(mode, "content")
    glob = str(args.get("glob") or "") or None
    icase = bool(args.get("ignore_case") or args.get("-i"))
    fixed = bool(args.get("literal"))
    try:
        context = max(0, min(int(args.get("context") or 0), 5))
    except (TypeError, ValueError):
        context = 0
    try:
        cap = max(1, min(int(args.get("limit") or 100), 500))
    except (TypeError, ValueError):
        cap = 100
    rg = rg_path()
    lines: list[str]
    total = 0
    if rg:
        argv = [rg, "--no-heading", "--color", "never", "--max-columns", str(LINE_CHARS), "--max-columns-preview",
                "--max-filesize", "2M"]
        argv += ["-l"] if mode == "files" else ["-c"] if mode == "count" else ["-n"]
        if context and mode == "content":
            argv += ["-C", str(context)]
        if icase:
            argv.append("-i")
        if fixed:
            argv.append("-F")
        if glob:
            argv += ["-g", glob]
        argv += rg_excludes(root)  # after the filter: later rg globs win
        argv += ["-e", pattern, "--", "." if root == cwd else _rel(root, cwd)]
        try:
            code, text = await _run(argv, cwd)
        except asyncio.TimeoutError:
            return "error: grep timed out after 20s; narrow it with path or glob"
        if code == 2 and "regex" in text.lower():
            return "error: invalid regex: " + text.strip().splitlines()[-1][:300]
        raw = [x[2:] if x.startswith("./") else x for x in text.splitlines() if x and x != "--"]
        total = len([x for x in raw if not re.match(r"^.+?-\d+-", x)]) if mode == "content" else len(raw)
        lines = raw[:cap]
    else:
        try:
            rx = re.compile(re.escape(pattern) if fixed else pattern, re.IGNORECASE if icase else 0)
        except re.error as exc:
            return f"error: invalid regex: {exc}"
        lines, total = await asyncio.to_thread(_py_grep, rx, root, glob, mode, context, cap, lambda p: _rel(p, cwd))
    if not lines:
        return f"no matches for {pattern!r}" + (f" in {glob}" if glob else "")
    more = f"\n… {total - len(lines)} more; narrow with path/glob or raise limit" if total > len(lines) else ""
    return "\n".join(lines) + more


async def glob_files(args: dict, cwd: Path, resolve) -> str:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return "error: pattern is required"
    root = resolve(str(args.get("path") or ".")) if args.get("path") else cwd
    if not root.is_dir():
        return f"error: not a directory: {root}"
    try:
        cap = max(1, min(int(args.get("limit") or 200), 1000))
    except (TypeError, ValueError):
        cap = 200
    rg = rg_path()
    files: list[Path] = []
    if rg:
        try:
            code, text = await _run([rg, "--files", "--color", "never", "-g", pattern, *rg_excludes(root)], root)
        except asyncio.TimeoutError:
            return "error: glob timed out after 20s"
        files = [root / x for x in text.splitlines() if x and not x.startswith("rg:")]
    else:
        files = await asyncio.to_thread(lambda: list(walk_files(root, pattern)))

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    files.sort(key=lambda p: (-mtime(p), str(p)))  # most recently changed first
    if not files:
        return f"no files match {pattern!r}"
    shown = [_rel(p, cwd) for p in files[:cap]]
    more = f"\n… {len(files) - cap} more; narrow the pattern or raise limit" if len(files) > cap else ""
    return "\n".join(shown) + more


# ------------------------------------------------------- background jobs -----

MAX_JOBS = 8
JOB_READ_CHARS = 8000


@dataclass
class Job:
    id: str
    command: str
    cwd: str
    log: Path
    proc: Any
    started: float = field(default_factory=time.time)
    read_pos: int = 0
    ended: float | None = None


JOBS: dict[str, Job] = {}


def jobs_dir() -> Path:
    from neovarch.paths import neovarch_home
    d = neovarch_home() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status(job: Job) -> str:
    rc = job.proc.returncode
    if rc is None:
        return f"running {time.time() - job.started:.0f}s"
    if job.ended is None:
        job.ended = time.time()
    return f"exited {rc} after {job.ended - job.started:.0f}s"


async def start_job(command: str, cwd: Path, env: dict) -> str:
    running = [j for j in JOBS.values() if j.proc.returncode is None]
    if len(running) >= MAX_JOBS:
        return f"error: {len(running)} background jobs already running; kill one with shell_job first"
    jid = f"j{int(time.time() * 1000) % 10**8:x}"
    log = jobs_dir() / f"{jid}.log"
    fh = open(log, "wb")
    try:
        proc = await asyncio.create_subprocess_shell(command, cwd=str(cwd), stdout=fh, stderr=asyncio.subprocess.STDOUT,
                                                     stdin=asyncio.subprocess.DEVNULL, env=env,
                                                     start_new_session=os.name != "nt")
    finally:
        fh.close()
    JOBS[jid] = Job(jid, command, str(cwd), log, proc)
    await asyncio.sleep(0.3)  # catch commands that fail immediately
    head = _read_new(JOBS[jid])
    return (f"started background job {jid} (pid {proc.pid}, {_status(JOBS[jid])}); output -> {log}\n"
            f"Check it with shell_job (action=output id={jid}), wait with action=wait, stop with action=kill."
            + (f"\n{head}" if head.strip() else ""))


def _read_new(job: Job) -> str:
    try:
        with open(job.log, "rb") as f:
            f.seek(job.read_pos)
            data = f.read()
    except OSError:
        return ""
    job.read_pos += len(data)
    from neovarch.tools import decode_output
    text = decode_output(data)
    if len(text) > JOB_READ_CHARS:
        text = f"… [{len(text) - JOB_READ_CHARS} earlier characters omitted] …\n" + text[-JOB_READ_CHARS:]
    return text


async def job_tool(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    if action == "list" or not args.get("id"):
        if not JOBS:
            return "(no background jobs)"
        return "\n".join(f"{j.id}: {_status(j)} - {j.command[:120]}" for j in JOBS.values())
    job = JOBS.get(str(args.get("id")))
    if job is None:
        return f"error: no background job {args.get('id')} (list shows the jobs)"
    if action == "kill":
        if job.proc.returncode is None:
            from neovarch.tools import kill_process_tree
            await kill_process_tree(job.proc)
        return f"{job.id}: {_status(job)}\n{_read_new(job)}".rstrip()
    if action == "wait":
        try:
            timeout = max(1.0, min(float(args.get("timeout") or 60), 300))
        except (TypeError, ValueError):
            timeout = 60.0
        try:
            await asyncio.wait_for(asyncio.shield(job.proc.wait()), timeout)
        except asyncio.TimeoutError:
            pass
    out = _read_new(job)
    return f"{job.id}: {_status(job)}\n" + (out if out.strip() else "(no new output)")


@atexit.register
def _kill_jobs_at_exit() -> None:  # pragma: no cover - process teardown
    for job in JOBS.values():
        if job.proc.returncode is None:
            try:
                if os.name != "nt":
                    os.killpg(job.proc.pid, 9)
                else:
                    job.proc.kill()
            except Exception:
                pass


class OutputBuffer:
    """Keeps the head and the tail of a long stream (bounded memory), for timed-out commands."""

    def __init__(self, head: int = 1_000_000, tail: int = 1_000_000):
        self.head, self.tail_cap = bytearray(), tail
        self.head_cap = head
        self.tail: deque[bytes] = deque()
        self.tail_len = 0
        self.dropped = 0

    def add(self, b: bytes) -> None:
        room = self.head_cap - len(self.head)
        if room > 0:
            self.head += b[:room]
            b = b[room:]
        if not b:
            return
        self.tail.append(b)
        self.tail_len += len(b)
        while self.tail_len > self.tail_cap and len(self.tail) > 1:
            gone = self.tail.popleft()
            self.tail_len -= len(gone)
            self.dropped += len(gone)

    def bytes(self) -> bytes:
        mid = f"\n… [{self.dropped} bytes omitted] …\n".encode() if self.dropped else b""
        return bytes(self.head) + mid + b"".join(self.tail)
