"""Tempest grounding check for web answers (v2, zero extra LLM calls).

When a turn used ``web_search`` / ``web_fetch``, every number in the final answer that looks like a fact
(3+ digits, money, a percentage, a decimal) must appear in the text those tools returned (or in the user's
own message). A number that does not is most likely invented; the model gets one hidden correction
("quote it from the source or say tidak ditemukan"), sharing the verify retry budget. If it still has an
unsupported number, the answer goes out with a short "angka berikut tidak ditemukan di sumber" note.
"""

from __future__ import annotations

import re

WEB_TOOLS = ("web_search", "web_fetch")
GROUND_MARK = "[cek sumber"

GROUNDING_RULE = ("- Fakta dari web: jawab hanya dari teks yang benar-benar kamu ambil (web_search/web_fetch), sebut "
                  "URL sumbernya, jangan menambah angka/tanggal dari ingatan. Tidak ada di sumber: bilang \"tidak "
                  "ditemukan\" dan sebut apa yang sudah dicari.")

# 1.234.567 / 1,234,567 / 5.27 / 3,5 / 2026 / 45% / Rp 5.270.000 -- one token per number.
_NUM = re.compile(r"(?<![\w.,])(?:rp\.?\s*)?\d[\d.,]*\d(?:\s*%)?|(?<![\w.,])\d(?:\s*%)", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")


def _digits(tok: str) -> str:
    return re.sub(r"\D", "", tok)


def _variants(tok: str) -> set[str]:
    """Digit strings a number may appear as in a source: 5.270.000 == 5270000; 5,27 == 5.27."""
    t = tok.strip().lower().replace("rp", "").replace("%", "").strip(" .")
    d = _digits(t)
    out = {d}
    if re.fullmatch(r"\d+[.,]0+", t):  # 12.0 / 12,00 -> 12
        out.add(re.split(r"[.,]", t)[0])
    return {x for x in out if x}


def numbers(text: str) -> list[str]:
    """Fact-like numbers in ``text`` (URLs and markdown link targets ignored)."""
    text = _URL.sub(" ", text or "")
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0)
        d = _digits(tok)
        if not d:
            continue
        factlike = len(d) >= 3 or "%" in tok or tok.lower().startswith("rp") or bool(re.search(r"\d[.,]\d", tok))
        if factlike:
            out.append(tok.strip())
    return out


def corpus_digits(texts: list[str]) -> str:
    """All number tokens of the sources as one searchable string of ``|digits|`` cells."""
    cells = set()
    for t in texts:
        for m in re.finditer(r"\d[\d.,]*\d|\d", t or ""):
            piece = m.group(0).strip(".,")
            d = _digits(piece)
            if d:
                cells.add(d)
                if re.fullmatch(r"\d+[.,]0+", piece):
                    cells.add(re.split(r"[.,]", piece)[0])
    return "|" + "|".join(sorted(cells)) + "|"


def unsupported(answer: str, sources: list[str], user_text: str = "") -> list[str]:
    """Numbers in ``answer`` that appear in neither the web sources nor the user's message."""
    if not sources:
        return []
    hay = corpus_digits(list(sources) + [user_text])
    missing = []
    for tok in numbers(answer):
        if not any(f"|{v}|" in hay for v in _variants(tok)):
            if tok not in missing:
                missing.append(tok)
    return missing


def used_web(tools: list[dict]) -> bool:
    return any(t.get("name") in WEB_TOOLS and t.get("ok") for t in tools or [])


def prompt(missing: list[str]) -> str:
    shown = ", ".join(missing[:8])
    return (f"{GROUND_MARK}] Angka berikut di jawabanmu tidak ada di teks web yang kamu ambil: {shown}. "
            "Perbaiki jawabanmu: kutip angka persis dari sumber (sebut URL-nya), ambil halaman yang memuatnya, atau "
            "tulis bahwa angka itu tidak ditemukan. Jangan menambah angka dari ingatan.")


def note(missing: list[str]) -> str:
    return ("\n\n_Catatan: angka berikut tidak ditemukan di sumber yang dibuka, mohon cek ulang: "
            + ", ".join(missing[:8]) + "._")
