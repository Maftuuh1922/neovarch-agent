"""Neovarch terminal branding: the star mark, the NEOVARCH wordmark, colours.

The star mark is a static braille text asset baked from the logo artwork by
``core/scripts/make_logo_ascii.py``; nothing here needs an image library.
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import TextIO

ASSETS = Path(__file__).resolve().parent / "assets"

# Dark red accent and bone white (the Neovarch palette).
ACCENT = "#C8101A"
ACCENT_BRIGHT = "#EE1C1C"
BONE = "#F2EDE4"
MUTED = "#8A7F78"
ANSI_ACCENT = "\x1b[38;2;200;16;26m"
ANSI_BONE = "\x1b[38;2;242;237;228m"
ANSI_DIM = "\x1b[2m"
ANSI_BOLD = "\x1b[1m"
ANSI_RESET = "\x1b[0m"

WORDMARK = (
    "███╗   ██╗███████╗ ██████╗ ██╗   ██╗ █████╗ ██████╗  ██████╗██╗  ██╗",
    "████╗  ██║██╔════╝██╔═══██╗██║   ██║██╔══██╗██╔══██╗██╔════╝██║  ██║",
    "██╔██╗ ██║█████╗  ██║   ██║██║   ██║███████║██████╔╝██║     ███████║",
    "██║╚██╗██║██╔══╝  ██║   ██║╚██╗ ██╔╝██╔══██║██╔══██╗██║     ██╔══██║",
    "██║ ╚████║███████╗╚██████╔╝ ╚████╔╝ ██║  ██║██║  ██║╚██████╗██║  ██║",
    "╚═╝  ╚═══╝╚══════╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝",
)
WORDMARK_WIDTH = max(len(x) for x in WORDMARK)
WORDMARK_SMALL = "N E O V A R C H"
MARK = "✦"
TAGLINE = "Agen AI di komputermu"


@lru_cache(maxsize=1)
def logo_lines() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(braille rows, mask rows); mask ``w`` = bright cell, ``r`` = accent cell."""
    try:
        text = (ASSETS / "logo.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
        mask = (ASSETS / "logo.mask").read_text(encoding="utf-8").rstrip("\n").split("\n")
    except OSError:
        return (), ()
    while text and not text[-1].strip():
        text.pop()
    mask = (mask + [""] * len(text))[: len(text)]
    return tuple(text), tuple(mask)


def logo_width() -> int:
    rows, _ = logo_lines()
    return max((len(r) for r in rows), default=0)


def color_enabled(stream: TextIO | None = None) -> bool:
    """Colour only on a real terminal, never with NO_COLOR or TERM=dumb."""
    if os.environ.get("NO_COLOR") not in (None, ""):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except (OSError, ValueError):
        return default


def _center(line: str, width: int, block: int) -> str:
    pad = max(0, (width - block) // 2)
    return " " * pad + line


def splash_text(width: int | None = None, color: bool | None = None, version: str = "") -> str:
    """The startup splash as text (ANSI colour when ``color``).

    Full splash (star mark + big wordmark) needs colour and >= 80 columns;
    otherwise only a monochrome wordmark is shown (big if it fits, else small).
    """
    width = width or term_width()
    color = color_enabled() if color is None else color
    tag = TAGLINE + (f" · v{version}" if version else "")
    out: list[str] = []
    if color and width >= 80:
        rows, mask = logo_lines()
        lw = logo_width()
        for row, m in zip(rows, mask):
            out.append(_center(_paint_logo_row(row, m), width, lw))
        out.append("")
        for line in WORDMARK:
            out.append(_center(f"{ANSI_ACCENT}{line}{ANSI_RESET}", width, WORDMARK_WIDTH))
        out.append(_center(f"{ANSI_DIM}{tag}{ANSI_RESET}", width, len(tag)))
        return "\n".join(out)
    if width >= WORDMARK_WIDTH + 2:
        out.extend(_center(line, width, WORDMARK_WIDTH) for line in WORDMARK)
        out.append(_center(tag, width, len(tag)))
    else:
        out.append(f"{MARK} {WORDMARK_SMALL}")
        out.append(tag)
    return "\n".join(out)


def _paint_logo_row(row: str, mask: str) -> str:
    parts: list[str] = []
    cur = None
    for i, ch in enumerate(row):
        kind = mask[i] if i < len(mask) else " "
        if ch == " ":
            kind = " "
        if kind != cur:
            parts.append(ANSI_RESET if kind == " " else (ANSI_BONE if kind == "w" else ANSI_ACCENT))
            cur = kind
        parts.append(ch)
    parts.append(ANSI_RESET)
    return "".join(parts)


def compact_mark(color: bool) -> str:
    return f"{ANSI_ACCENT}{ANSI_BOLD}{MARK} NEOVARCH{ANSI_RESET}" if color else f"{MARK} NEOVARCH"
