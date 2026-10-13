"""Slash commands of the terminal chat: parsing, aliases and reasoning words."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

# name -> (usage, description); order is the /bantuan order.
COMMANDS: dict[str, tuple[str, str]] = {
    "baru": ("/baru", "Mulai obrolan baru"),
    "model": ("/model [nama] [--global]", "Lihat atau ganti model obrolan ini"),
    "reasoning": ("/reasoning [rendah|sedang|tinggi|ultra|mati]", "Atur tingkat penalaran"),
    "skill": ("/skill [nama] [pesan]", "Daftar skill, atau minta agen memakai satu skill"),
    "desain": ("/desain [brief|status|cek|katalog]", "Mode Desain: brief → design system → pratinjau → kode"),
    "rencana": ("/rencana <tugas>", "Mode rencana: teliti dan susun rencana dulu, belum mengubah file"),
    "stop": ("/stop", "Hentikan giliran yang sedang berjalan"),
    "status": ("/status", "Model, penalaran, koneksi dan sesi"),
    "bukti": ("/bukti [n]", "Buka/tutup bagian Bukti (hasil alat) giliran terakhir"),
    "buka": ("/buka <n>", "Buka berkas lampiran nomor n dengan aplikasi bawaan"),
    "bantuan": ("/bantuan", "Tampilkan bantuan ini"),
    "keluar": ("/keluar", "Keluar"),
}

ALIASES = {
    "new": "baru", "reset": "baru", "clear": "baru",
    "models": "model", "reason": "reasoning", "penalaran": "reasoning", "effort": "reasoning",
    "skills": "skill", "design": "desain", "plan": "rencana", "batal": "stop", "interrupt": "stop", "hentikan": "stop",
    "info": "status", "evidence": "bukti", "open": "buka",
    "help": "bantuan", "h": "bantuan", "?": "bantuan",
    "exit": "keluar", "quit": "keluar", "q": "keluar",
}

# Display word <-> core level (session_settings.REASONING_LEVELS)
REASONING_WORDS = {
    "mati": "none", "off": "none", "none": "none",
    "minimal": "minimal",
    "rendah": "low", "low": "low",
    "sedang": "medium", "medium": "medium", "med": "medium",
    "tinggi": "high", "high": "high",
    "ultra": "ultra", "max": "ultra", "xhigh": "ultra",
}
REASONING_CHOICES = ("rendah", "sedang", "tinggi", "ultra")
LEVEL_LABEL = {"": "Bawaan", "none": "Mati", "minimal": "Minimal", "low": "Rendah", "medium": "Sedang",
               "high": "Tinggi", "xhigh": "Ultra", "max": "Ultra", "ultra": "Ultra"}


@dataclass
class Command:
    name: str               # canonical name ("" when unknown)
    raw: str                # what the user typed after the slash, first word
    args: list[str] = field(default_factory=list)
    rest: str = ""          # everything after the command word, verbatim

    @property
    def known(self) -> bool:
        return bool(self.name)


def is_command(line: str) -> bool:
    s = line.lstrip()
    # "/" alone or a path like "/etc/hosts are..." is a message, not a command
    return s.startswith("/") and len(s) > 1 and not s[1:2].isspace() and "/" not in s.split()[0][1:]


def parse(line: str) -> Command | None:
    """``"/model gpt-4o --global"`` -> Command("model", ["gpt-4o", "--global"]). None for a message."""
    if not is_command(line):
        return None
    s = line.strip()[1:]
    word, _, rest = s.partition(" ")
    raw = word.strip()
    key = raw.lower()
    name = key if key in COMMANDS else ALIASES.get(key, "")
    rest = rest.strip()
    try:
        args = shlex.split(rest) if rest else []
    except ValueError:
        args = rest.split()
    return Command(name=name, raw=raw, args=args, rest=rest)


def reasoning_level(word: str) -> str | None:
    """User word (Indonesian or core level) -> core level, None when unknown."""
    return REASONING_WORDS.get(str(word or "").strip().lower())


def level_label(level: str | None) -> str:
    return LEVEL_LABEL.get(str(level or "").strip().lower(), str(level or "Bawaan").capitalize())


def suggest(raw: str) -> str | None:
    """Closest command for a typo (``/mdoel`` -> ``model``)."""
    import difflib
    names = list(COMMANDS) + list(ALIASES)
    hit = difflib.get_close_matches(raw.lower(), names, n=1, cutoff=0.6)
    if not hit:
        return None
    return hit[0] if hit[0] in COMMANDS else ALIASES[hit[0]]


def completions() -> list[str]:
    return ["/" + n for n in COMMANDS]
