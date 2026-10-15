"""Neovarch's default skill pack: well-known, permissively licensed skills that
ship with the core and are enabled by default.

* ``pack.json`` lists every skill: id (folder), label, category, upstream source,
  license, a short ID/EN summary for the prompt index and the keywords the
  matcher uses. Each skill folder keeps its upstream LICENSE; ``THIRD_PARTY_SKILLS.md``
  is the attribution notice.
* ``install(root)`` copies the pack into ``~/.neovarch/skills`` (cheap when already
  current: one marker file per skill). A copy the user edited, or archived, is left alone.
* ``match(text, skills)`` scores the user's message against the keywords and the
  description of every enabled skill, so even models that ignore a long skill
  index get an explicit "use this skill" hint.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parent
MARKER = ".neovarch-pack.json"


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    return json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))


def pack_skills() -> list[dict[str, Any]]:
    return list(manifest()["skills"])


def by_id() -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in pack_skills()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def install(root: Path) -> list[str]:
    """Install or refresh the pack under ``root``; returns the ids written."""
    from neovarch import skills_admin
    version = str(manifest().get("version", "1"))
    written: list[str] = []
    for s in pack_skills():
        sid = s["id"]
        src, dst = PACK_DIR / sid, root / sid
        marker = dst / MARKER
        try:
            if not dst.exists():
                if skills_admin.archived(sid):
                    continue  # the user archived it
            else:
                if not marker.is_file():
                    continue  # a skill of the user's own with the same name
                meta = json.loads(marker.read_text(encoding="utf-8"))
                if meta.get("version") == version:
                    continue
                if meta.get("sha") != _sha(dst / "SKILL.md"):
                    continue  # the user edited it: keep their copy
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            marker.write_text(json.dumps({"version": version, "sha": _sha(dst / "SKILL.md"),
                                          "source": s["source"], "license": s["license"]}), encoding="utf-8")
            written.append(sid)
        except (OSError, ValueError):
            continue
    return written


# --------------------------------------------------------------- matcher ----

_STOP = set("""yang dan atau untuk dengan dari pada dalam ini itu saya aku kamu bisa tolong buat bikin buatkan
bikinin bantu dong ya gak tidak ada akan juga sudah lagi saja aja mau ingin the and for with from this that
use when user asks into your you are not any also make create help please about have has""".split())


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9/+#.]+", " ", str(text or "").lower()) + " "


def _words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) >= 4 and w not in _STOP}


def match(text: str, skills: list[dict[str, Any]] | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Skills relevant to ``text``, best first: [{name, label, score, reason}].

    A keyword phrase from pack.json found in the message scores 3 (multi-word 4);
    each meaningful word shared with a skill's description scores 1. Skills need
    a score of 3 to be suggested, so one stray shared word never triggers a hint."""
    msg = _norm(text)
    if not msg.strip():
        return []
    mwords = _words(text)
    pack = by_id()
    if skills is None:
        skills = [{"name": s["id"], "description": s["summary"]} for s in pack_skills()]
    scored = []
    for sk in skills:
        name = sk.get("name") or ""
        meta = pack.get(name, {})
        score, hits = 0, []
        for kw in meta.get("keywords", []):
            if _norm(kw) in msg:
                score += 4 if " " in kw.strip() else 3
                hits.append(kw)
        label_words = _words(name.replace("-", " ") + " " + meta.get("label", ""))
        shared = (mwords & _words(sk.get("description") or "")) | (mwords & label_words)
        score += len(shared)
        if score >= 3:
            scored.append({"name": name, "label": meta.get("label", name), "score": score,
                           "reason": ", ".join((hits or sorted(shared))[:4])})
    scored.sort(key=lambda r: (-r["score"], r["name"]))
    return scored[:limit]


def hint_block(text: str, skills: list[dict[str, Any]], lean: bool = False) -> str:
    """The prompt section that names the matching skills for this message.

    ``lean`` (Tempest lean turns): the skills are offered, not ordered. A keyword match ("tes", "bug")
    used to cost every small coding task one extra model call to read a long process skill."""
    hits = match(text, skills)
    if not hits:
        return ""
    lines = [f"- `{h['name']}` ({h['label']}) - cocok karena: {h['reason']}" for h in hits]
    if lean:
        return ("# Skill terkait (opsional) / Related skills (optional)\n"
                "Baca dengan alat `skill` hanya bila tugas ini butuh prosedur khusus yang belum jelas bagimu "
                "(mis. desain, dokumen, riset, rilis). Perbaikan kode, rename, menambah tes atau pertanyaan "
                "tentang kode: langsung kerjakan. / Read one only if the task needs a procedure you lack.\n"
                + "\n".join(lines))
    return ("# Skill yang cocok untuk pesan ini / Skills matching this message\n"
            "Sebelum mengerjakan, panggil alat `skill` dengan `name` skill yang paling cocok di bawah, baca isinya, "
            "lalu ikuti langkahnya. Jika ternyata tidak relevan, abaikan.\n"
            "Before you start, call the `skill` tool with the best matching name below and follow it.\n"
            + "\n".join(lines))
