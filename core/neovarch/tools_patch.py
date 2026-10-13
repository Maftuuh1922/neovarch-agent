"""``apply_patch``: Codex-style (V4A) multi-file patches.

GPT/Codex-trained models write edits in this envelope on their own; accepting it saves a
failed call and a retry, and lets any model add, change, move and delete several files
in one step::

    *** Begin Patch
    *** Add File: src/new.py
    +print("hi")
    *** Update File: src/app.py
    *** Move to: src/main.py          (optional rename)
    @@ def handler():                 (optional anchor line)
     context line
    -old line
    +new line
    *** Delete File: old.txt
    *** End Patch

Everything is computed in memory first and written only when every hunk of every file
applies (all or nothing). Hunks are located after the previous hunk / anchor: exact lines
first, then ignoring trailing whitespace, then ignoring indentation. Plain unified diffs
(``--- a/x`` / ``+++ b/x``) are accepted too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

BEGIN, END = "*** Begin Patch", "*** End Patch"
HEREDOC = re.compile(r"^\s*(?:apply_patch|applypatch)\s*<<-?\s*['\"]?(\w+)['\"]?\s*\n(.*)\n\s*\1\s*$", re.S)


class PatchError(ValueError):
    pass


@dataclass
class Hunk:
    anchors: list[str] = field(default_factory=list)
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    eof: bool = False


@dataclass
class FileOp:
    kind: str  # add | update | delete
    path: str
    move_to: str = ""
    content: str = ""
    hunks: list[Hunk] = field(default_factory=list)


def from_shell(command: str) -> str | None:
    """``apply_patch <<'EOF' ... EOF`` typed into the shell -> the patch text."""
    m = HEREDOC.match(command or "")
    return m.group(2) if m else None


def _strip_fences(text: str) -> str:
    t = text.strip("\n")
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t


def _from_unified(lines: list[str]) -> list[str]:
    """``--- a/x`` / ``+++ b/x`` diffs -> V4A lines."""
    out, i = [BEGIN], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old = ln[4:].split("\t")[0].strip()
            new = lines[i + 1][4:].split("\t")[0].strip()
            old = old[2:] if old.startswith(("a/", "b/")) else old
            new = new[2:] if new.startswith(("a/", "b/")) else new
            if old == "/dev/null":
                out.append(f"*** Add File: {new}")
            elif new == "/dev/null":
                out.append(f"*** Delete File: {old}")
            else:
                out.append(f"*** Update File: {old}")
                if new != old:
                    out.append(f"*** Move to: {new}")
            i += 2
            continue
        if ln.startswith("@@"):
            out.append("@@")
        elif ln.startswith(("diff --git", "index ", "new file mode", "deleted file mode", "similarity", "rename ")):
            pass
        elif ln.startswith("\\ No newline"):
            pass
        else:
            out.append(ln)
        i += 1
    out.append(END)
    return out


def parse(text: str) -> list[FileOp]:
    text = _strip_fences(str(text or "")).replace("\r\n", "\n")
    lines = text.split("\n")
    if not any(ln.strip() == BEGIN for ln in lines):
        if any(ln.startswith("+++ ") for ln in lines):
            lines = _from_unified(lines)
        elif any(ln.startswith(("*** Add File:", "*** Update File:", "*** Delete File:")) for ln in lines):
            lines = [BEGIN] + lines + [END]
        else:
            raise PatchError("patch must start with '*** Begin Patch' (or be a unified diff)")
    start = next(i for i, ln in enumerate(lines) if ln.strip() == BEGIN)
    ops: list[FileOp] = []
    cur: FileOp | None = None
    hunk: Hunk | None = None
    for raw in lines[start + 1:]:
        ln = raw
        s = ln.strip()
        if s == END:
            break
        header = re.match(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$", ln)
        if header:
            cur = FileOp(header.group(1).lower(), header.group(2))
            ops.append(cur)
            hunk = None
            continue
        if cur is None:
            if s:
                raise PatchError(f"line outside a file section: {ln[:80]!r}")
            continue
        m = re.match(r"^\*\*\* Move to:\s*(.+?)\s*$", ln)
        if m:
            cur.move_to = m.group(1)
            continue
        if s == "*** End of File":
            if hunk is not None:
                hunk.eof = True
            continue
        if cur.kind == "add":
            if ln.startswith("+"):
                cur.content += ln[1:] + "\n"
            elif s:
                raise PatchError(f"Add File {cur.path}: every line must start with '+'")
            continue
        if cur.kind == "delete":
            continue
        if ln.startswith("@@"):
            anchor = ln[2:].strip().strip("@").strip()
            if hunk is None or hunk.old or hunk.new:
                hunk = Hunk()
                cur.hunks.append(hunk)
            if anchor:
                hunk.anchors.append(anchor)
            continue
        if hunk is None:
            hunk = Hunk()
            cur.hunks.append(hunk)
        if ln.startswith("-"):
            hunk.old.append(ln[1:])
        elif ln.startswith("+"):
            hunk.new.append(ln[1:])
        else:  # context (a leading space, or a bare empty line)
            body = ln[1:] if ln.startswith(" ") else ln
            hunk.old.append(body)
            hunk.new.append(body)
    if not ops:
        raise PatchError("patch has no '*** Add/Update/Delete File:' section")
    for op in ops:
        if op.kind == "update" and not op.hunks and not op.move_to:
            raise PatchError(f"Update File {op.path}: no changes")
    return ops


_NORMS: list[tuple[Callable[[str], str], str]] = [
    (lambda s: s, ""),
    (lambda s: s.rstrip(), "ignoring trailing whitespace"),
    (lambda s: " ".join(s.split()), "ignoring indentation"),
]


def _find(lines: list[str], target: list[str], start: int, eof: bool) -> tuple[int, str]:
    if not target:
        return (len(lines) if eof else start), ""
    for norm, how in _NORMS:
        want = [norm(t) for t in target]
        rng = range(len(lines) - len(target), start - 1, -1) if eof else range(start, len(lines) - len(target) + 1)
        for i in rng:
            if [norm(x) for x in lines[i:i + len(target)]] == want:
                return i, how
    # search from the top as a last resort (hunks given out of order)
    for norm, how in _NORMS:
        want = [norm(t) for t in target]
        for i in range(0, min(start, len(lines) - len(target) + 1)):
            if [norm(x) for x in lines[i:i + len(target)]] == want:
                return i, how or "out of order"
    return -1, ""


def _closest(lines: list[str], target: list[str]) -> str:
    import difflib
    probe = next((t for t in target if t.strip()), "")
    if not probe:
        return ""
    best = difflib.get_close_matches(probe.strip(), [ln.strip() for ln in lines], n=1, cutoff=0.6)
    if not best:
        return ""
    idx = [ln.strip() for ln in lines].index(best[0])
    lo, hi = max(idx - 2, 0), min(idx + 3, len(lines))
    return "\nClosest region:\n" + "\n".join(f"{i + 1:>6}\t{lines[i][:200]}" for i in range(lo, hi))


def apply_hunks(text: str, hunks: list[Hunk], path: str = "") -> tuple[str, list[str]]:
    crlf = "\r\n" in text
    trailing_nl = text.endswith("\n") or not text
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "" and trailing_nl:
        lines.pop()
    notes: list[str] = []
    cursor = 0
    for n, h in enumerate(hunks, 1):
        for anchor in h.anchors:
            hit = next((i for i in range(cursor, len(lines)) if lines[i].strip() == anchor.strip()), -1)
            if hit < 0:
                hit = next((i for i in range(cursor, len(lines)) if anchor.strip() in lines[i]), -1)
            if hit < 0:
                hit = next((i for i in range(0, len(lines)) if anchor.strip() in lines[i]), -1)
            if hit < 0:
                raise PatchError(f"{path} hunk {n}: anchor '@@ {anchor}' not found")
            cursor = hit  # the hunk is searched from the anchor line on (it may be the first context line)
        old = h.old
        if not old:  # pure insertion: after the anchor line, else at the end of the file
            pos = cursor + 1 if h.anchors and not h.eof else len(lines)
            lines[pos:pos] = list(h.new)
            cursor = pos + len(h.new)
            continue
        pos, how = _find(lines, old, cursor, h.eof)
        if pos < 0 and old and not old[-1].strip():  # tolerate a stray blank context line at the end
            pos, how = _find(lines, old[:-1], cursor, h.eof)
            if pos >= 0:
                old, h = old[:-1], Hunk(h.anchors, old[:-1], h.new[:-1] if h.new and not h.new[-1].strip() else h.new,
                                        h.eof)
        if pos < 0:
            raise PatchError(f"{path} hunk {n}: context/removed lines not found" + _closest(lines, old))
        new = list(h.new)
        if how == "ignoring indentation" and old and new:
            # re-indent the replacement by the difference between file and patch indentation
            file_ind = re.match(r"\s*", lines[pos]).group(0)
            patch_ind = re.match(r"\s*", old[0]).group(0)
            if file_ind != patch_ind:
                new = [(file_ind + x[len(patch_ind):]) if x.startswith(patch_ind) and x.strip() else x for x in new]
        if how:
            notes.append(f"hunk {n} matched {how}")
        lines[pos:pos + len(old)] = new
        cursor = pos + len(new)
    out = "\n".join(lines)
    if trailing_nl and lines:
        out += "\n"
    if crlf:
        out = out.replace("\n", "\r\n")
    return out, notes


def plan(patch: str, resolve: Callable[[str], Path]) -> tuple[list[tuple[Path, str | None]], list[str]]:
    """Compute the result without writing: [(path, new_content or None to delete)], summary lines."""
    ops = parse(patch)
    writes: dict[Path, str | None] = {}
    summary: list[str] = []
    for op in ops:
        p = resolve(op.path)
        if op.kind == "add":
            if p in writes and writes[p] is not None or (p not in writes and p.exists()):
                raise PatchError(f"Add File {op.path}: file already exists (use Update File)")
            writes[p] = op.content
            summary.append(f"A {op.path} (+{op.content.count(chr(10))})")
            continue
        current = writes[p] if p in writes else (p.read_bytes().decode("utf-8", errors="replace") if p.is_file() else None)
        if current is None:
            raise PatchError(f"{op.kind.title()} File {op.path}: file not found")
        if op.kind == "delete":
            writes[p] = None
            summary.append(f"D {op.path}")
            continue
        new_text, notes = apply_hunks(current, op.hunks, op.path)
        added = sum(len(h.new) for h in op.hunks) - sum(len(h.old) for h in op.hunks)
        if op.move_to:
            dest = resolve(op.move_to)
            if dest != p and (dest.exists() and dest not in writes):
                raise PatchError(f"Move to {op.move_to}: destination exists")
            writes[p] = None
            writes[dest] = new_text
            summary.append(f"R {op.path} -> {op.move_to}" + (f" ({added:+d} lines)" if op.hunks else ""))
        else:
            writes[p] = new_text
            summary.append(f"M {op.path} ({added:+d} lines)" + (f"; {', '.join(notes)}" if notes else ""))
    return list(writes.items()), summary


def write(changes: list[tuple[Path, str | None]]) -> None:
    for p, content in changes:
        if content is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="")


SCHEMA = {
    "description": ("Apply a multi-file patch (Codex V4A): '*** Begin Patch', then per file '*** Add File: p' (+lines) | "
                    "'*** Update File: p' (optional '*** Move to: q', '@@ anchor', ' ' context, '-' old, '+' new) | "
                    "'*** Delete File: p', then '*** End Patch'. All or nothing; unified diffs also accepted."),
    "parameters": {"type": "object", "properties": {"patch": {"type": "string"}}, "required": ["patch"]},
}
