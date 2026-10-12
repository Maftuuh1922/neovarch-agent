"""Tempest auto-memory: periodic reminders to persist durable facts, plus dedup on write.

Zero extra LLM calls and cache-safe: the reminder is a short note appended to the *next*
user message (its ``wire_tail``), never an edit of the system prompt or of older messages.

When a reminder is due:

* every ``memory_nudge_every`` user turns since the last memory write in this chat, or
* on the first user turn after a finished task (a turn that changed files and ended without a
  verify/lint failure), because that is when lessons are fresh.

Dedup: before a memory append/write runs, lines that are already in the note (or in any other
memory note), after normalising case, punctuation and whitespace, or that are near-identical
to an existing line, are dropped. If nothing new is left the write is skipped and the model is
told the fact is already stored.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

NUDGE_MARK = "# Pengingat memori (otomatis)"
NEAR_DUP = 0.9  # SequenceMatcher ratio at/above which two lines are the same fact
MEMORY_TOOLS = ("memory", "memory_update")


def _norm(line: str) -> str:
    s = re.sub(r"^[\s>*\-•\d.)]+", "", line or "").lower()
    s = re.sub(r"[^\w\s:/.@-]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip(" .:")


def existing_lines(mem_dir: Path) -> list[str]:
    out = []
    if mem_dir.exists():
        for p in sorted(mem_dir.glob("*.md")):
            try:
                for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    n = _norm(ln)
                    if len(n) >= 4:
                        out.append(n)
            except OSError:
                continue
    return out


def is_duplicate(line: str, known: list[str]) -> bool:
    n = _norm(line)
    if len(n) < 4:
        return False
    for k in known:
        if n == k or (len(n) > 24 and (n in k)):
            return True
        if abs(len(n) - len(k)) <= max(8, len(n) // 5) and SequenceMatcher(None, n, k).ratio() >= NEAR_DUP:
            return True
    return False


def dedup_content(content: str, mem_dir: Path) -> tuple[str, list[str]]:
    """(new content with duplicate fact lines removed, the dropped lines)."""
    known = existing_lines(mem_dir)
    kept, dropped = [], []
    for ln in str(content or "").splitlines():
        if ln.strip() and not ln.lstrip().startswith("#") and is_duplicate(ln, known):
            dropped.append(ln.strip())
            continue
        kept.append(ln)
        n = _norm(ln)
        if len(n) >= 4:
            known.append(n)  # also dedups repeats inside the same write
    return "\n".join(kept).strip("\n"), dropped


def guard_write(name: str, args: dict, mem_dir: Path) -> tuple[dict, str | None]:
    """Apply dedup to a memory tool call. Returns (args to run, or the reply when nothing is left)."""
    action = str(args.get("action") or "")
    if name not in MEMORY_TOOLS or action != "append":
        return args, None
    content = str(args.get("content") or "")
    new, dropped = dedup_content(content, mem_dir)
    if not dropped:
        return args, None
    if not new.strip():
        return args, ("sudah ada di memori, tidak ditambahkan lagi (duplikat): "
                      + "; ".join(d[:120] for d in dropped[:5]))
    return {**args, "content": new}, None


def state(rec: dict) -> dict:
    return rec.setdefault("tempest_memory", {"turns_since": 0, "task_done": False, "nudges": 0})


def note_turn_start(rec: dict, st: dict) -> str:
    """Called once per user turn. Returns the reminder text to append, or ''."""
    s = state(rec)
    s["turns_since"] = int(s.get("turns_since") or 0) + 1
    every = int(st.get("memory_nudge_every") or 0)
    due = bool(s.get("task_done")) or (every > 0 and s["turns_since"] > every)
    if not due:
        return ""
    s["turns_since"] = 0
    s["task_done"] = False
    s["nudges"] = int(s.get("nudges") or 0) + 1
    return nudge_text()


def nudge_text() -> str:
    return (NUDGE_MARK + "\nSebelum atau sesudah menjawab pesan ini: bila percakapan sejauh ini memunculkan fakta yang "
            "tetap berlaku di sesi lain (preferensi/koreksi pengguna, konvensi proyek, lingkungan PC, keputusan), "
            "simpan satu baris faktual dengan `memory_update` action=append. Jangan simpan hal sekali pakai, rahasia, "
            "atau yang sudah ada di memori. Kalau tidak ada yang layak, abaikan pengingat ini tanpa menyebutnya.")


def note_memory_write(rec: dict) -> None:
    state(rec)["turns_since"] = 0


def note_task_done(rec: dict) -> None:
    state(rec)["task_done"] = True
