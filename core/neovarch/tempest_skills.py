"""Tempest skills from experience: turn a verified multi-step task into a reusable skill, and
repair a skill that led to a failure.

Deterministic and zero extra LLM calls; every write goes through ``selfedit.skill_manage`` so
it is versioned and undoable with /undo.

* A turn that (a) changed files or ran commands, (b) used at least ``skill_min_steps`` tool
  calls and (c) passed the verify gate (or had no test command and finished without a gate
  failure) becomes a *candidate*: the request, the commands that worked, the files touched and
  the verify command.
* ``skill_learn: offer`` (default) - on the next user message the model gets one short note
  offering to save the candidate as a skill (it decides, or asks the user).
* ``skill_learn: auto`` - the harness writes a draft skill itself (``origin: tempest``), unless a
  skill for the same kind of task already exists.
* ``skill_learn: off`` - nothing.

Usage counters per skill (uses / passes / fails, ACE-style helpful vs harmful signal) live in
``skills/.tempest_stats.json``. A skill that was read in a turn whose verify gate gave up gets a
fail count, a repair hint for the model and, in ``auto`` mode, a dated line under
"## Catatan kegagalan (Tempest)" in its SKILL.md.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

OFFER_MARK = "# Tawaran skill (otomatis)"
REPAIR_MARK = "# Perbaiki skill (otomatis)"
FAIL_SECTION = "## Catatan kegagalan (Tempest)"
STOP = {"yang", "dan", "di", "ke", "dari", "untuk", "dengan", "ini", "itu", "tolong", "buat", "buatkan", "bikin",
        "the", "a", "an", "to", "of", "in", "and", "please", "for", "on", "with", "file", "kode", "code", "saya",
        "aku", "kamu", "agar", "supaya", "lalu", "terus", "juga", "ya", "dong", "nya"}


# ------------------------------------------------------------------ stats --

def _stats_path(skills_root: Path) -> Path:
    return Path(skills_root) / ".tempest_stats.json"


def load_stats(skills_root: Path) -> dict:
    p = _stats_path(skills_root)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def bump(skills_root: Path, names: list[str], outcome: str) -> None:
    """outcome: use | pass | fail."""
    if not names:
        return
    data = load_stats(skills_root)
    for n in names:
        s = data.setdefault(n, {"uses": 0, "passes": 0, "fails": 0})
        key = {"use": "uses", "pass": "passes", "fail": "fails"}[outcome]
        s[key] = int(s.get(key) or 0) + 1
        s["last"] = time.time()
    p = _stats_path(skills_root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def skills_read(tools: list[dict]) -> list[str]:
    """Skill names the model read in this turn (``skill`` name=…, ``skill_manage`` view)."""
    out = []
    for t in tools:
        a = t.get("args") or {}
        name = ""
        if t.get("name") == "skill" and a.get("name"):
            name = str(a["name"])
        elif t.get("name") == "skill_manage" and str(a.get("action")) == "view" and a.get("name"):
            name = str(a["name"])
        name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-")
        if name and name not in out:
            out.append(name)
    return out


# ------------------------------------------------------------- candidates --

def _keywords(text: str, n: int = 5) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text or "")]
    seen: list[str] = []
    for w in words:
        if w not in STOP and w not in seen:
            seen.append(w)
    return seen[:n]


def slug_for(request: str) -> str:
    kws = _keywords(request, 4) or ["tugas"]
    return ("alur-" + "-".join(kws))[:48].strip("-")


def candidate(request: str, tools: list[dict], verify_cmd: list[str] | None, min_steps: int) -> dict | None:
    """A skill candidate from one finished turn's tool ledger, or None when it is not worth it."""
    ok_tools = [t for t in tools if t.get("ok")]
    if len(tools) < max(1, min_steps) or not ok_tools:
        return None
    if not any(t.get("name") in ("write_file", "edit_file", "shell") for t in ok_tools):
        return None  # pure reading/chat: nothing procedural to keep
    commands, files = [], []
    for t in ok_tools:
        a = t.get("args") or {}
        if t["name"] == "shell" and a.get("command"):
            c = str(a["command"]).strip()
            if c and c not in commands:
                commands.append(c[:200])
        elif t["name"] in ("write_file", "edit_file") and a.get("path"):
            p = str(a["path"])
            if p not in files:
                files.append(p)
    return {"request": (request or "").strip()[:400], "commands": commands[:12], "files": files[:12],
            "verify": " ".join(verify_cmd) if verify_cmd else "", "steps": len(tools),
            "skills_used": skills_read(tools), "ts": time.time(), "name": slug_for(request)}


def draft(cand: dict) -> tuple[str, str]:
    """(description, SKILL.md body) for a candidate. Plain, factual, editable."""
    req = cand["request"].splitlines()[0][:160] if cand["request"] else "tugas serupa"
    desc = f"Langkah yang terbukti berhasil untuk tugas seperti: {req}"
    lines = [f"# {cand['name']}", "", f"Dibuat otomatis oleh Tempest dari tugas yang lolos verifikasi "
             f"({cand['steps']} langkah, {time.strftime('%Y-%m-%d', time.localtime(cand['ts']))}). "
             "Periksa dan rapikan sebelum diandalkan.", "", "## Kapan dipakai", f"- {req}", "", "## Langkah"]
    i = 1
    if cand["files"]:
        lines.append(f"{i}. Baca dulu file yang relevan: " + ", ".join(f"`{f}`" for f in cand["files"][:6]))
        i += 1
    for c in cand["commands"]:
        lines.append(f"{i}. Jalankan `{c}`")
        i += 1
    lines.append(f"{i}. Ubah kode seperlunya, lalu verifikasi.")
    lines += ["", "## Verifikasi", f"- `{cand['verify']}` harus lulus." if cand["verify"]
              else "- Jalankan perintah yang membuktikan hasilnya (tes/skrip) dan tunjukkan output-nya.",
              "", "## Jebakan", "- (tambahkan di sini saat menemukan kegagalan)"]
    return desc, "\n".join(lines)


def similar_skill(cand: dict, skills: list[dict]) -> str | None:
    """Name of an installed skill that already covers this kind of task (name or description overlap)."""
    kws = set(_keywords(cand["request"], 6))
    if cand["name"] in {s.get("name") for s in skills}:
        return cand["name"]
    best, best_score = None, 0.0
    for s in skills:
        words = set(_keywords((s.get("name") or "").replace("-", " ") + " " + (s.get("description") or ""), 30))
        if not kws or not words:
            continue
        score = len(kws & words) / len(kws)
        if score > best_score:
            best, best_score = s.get("name"), score
    return best if best_score >= 0.6 else None


def offer_text(cand: dict, existing: str | None) -> str:
    head = OFFER_MARK + f"\nTugas sebelumnya di obrolan ini selesai dan lolos verifikasi ({cand['steps']} langkah"
    head += f", `{cand['verify']}`)." if cand["verify"] else ")."
    if existing:
        return (head + f" Skill `{existing}` sudah mencakup jenis tugas ini: bila ada langkah atau jebakan baru dari "
                "tugas itu, perbarui skill tersebut dengan `skill_manage` action=patch. Kalau tidak ada, abaikan "
                "catatan ini tanpa menyebutnya.")
    steps = "; ".join(cand["commands"][:4]) or ", ".join(cand["files"][:4])
    return (head + " Bila jenis tugas ini kemungkinan berulang, simpan sebagai skill dengan `skill_manage` "
            f"action=create (nama usulan `{cand['name']}`; isi: kapan dipakai, langkah bernomor, Jebakan, Verifikasi). "
            f"Langkah yang berhasil: {steps}. Kalau ragu, tawarkan ke pengguna dalam satu kalimat; kalau tidak "
            "berguna, abaikan tanpa menyebutnya.")


def repair_text(names: list[str], summary: str) -> str:
    return (REPAIR_MARK + "\nSkill " + ", ".join(f"`{n}`" for n in names) + " dipakai di tugas yang gagal verifikasi"
            + (f" ({summary.splitlines()[0][:160]})" if summary else "") + ". Bila langkah di skill itu keliru atau "
            "kurang, perbaiki dengan `skill_manage` action=patch (tambahkan di bagian Jebakan) sebelum melanjutkan.")


def auto_save(cand: dict, session_id: str = "") -> str:
    """auto mode: write the draft skill (undoable). Returns a status line."""
    from neovarch import selfedit
    from neovarch.tools import list_skills
    existing = similar_skill(cand, list_skills(include_disabled=True))
    if existing:
        return f"skill `{existing}` sudah ada untuk jenis tugas ini; tidak dibuat duplikat"
    desc, body = draft(cand)
    content = f"---\nname: {cand['name']}\ndescription: {desc}\nauthor: agent\norigin: tempest\n---\n{body}\n"
    try:
        res = selfedit.skill_manage("create", cand["name"], content=content, session_id=session_id)
    except Exception as exc:  # never break a turn over a skill draft
        return f"skill tidak dibuat: {exc}"
    return res.get("message") or f"skill {cand['name']} dibuat"


def auto_repair(skills_root: Path, names: list[str], summary: str, verify: str, session_id: str = "") -> list[str]:
    """auto mode: append a dated failure line to each used skill. Returns the names patched."""
    from neovarch import selfedit
    done = []
    line = f"- {time.strftime('%Y-%m-%d')}: gagal verifikasi `{verify or '?'}`: {(summary or '').splitlines()[0][:200] if summary else 'tanpa ringkasan'}"
    for n in names:
        doc = Path(skills_root) / n / "SKILL.md"
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        if "builtin: true" in text:
            continue  # built-in skills are refreshed by the app; only user/agent skills get notes
        try:
            if FAIL_SECTION in text:
                tail = text.split(FAIL_SECTION, 1)[1]
                old = FAIL_SECTION + tail
                new_text = old.rstrip("\n") + "\n" + line + "\n"
                selfedit.skill_manage("patch", n, old_text=old, new_text=new_text, session_id=session_id)
            else:
                body = text.rstrip("\n")
                selfedit.skill_manage("edit", n, content=body + "\n\n" + FAIL_SECTION + "\n" + line + "\n",
                                      session_id=session_id)
            done.append(n)
        except Exception:
            continue
    return done


# ------------------------------------------------------------- session state --

def state(rec: dict) -> dict:
    return rec.setdefault("tempest_skill", {})


def pending_note(rec: dict) -> str:
    """The offer/repair note for the next user message (consumed once)."""
    s = state(rec)
    note = s.pop("pending", "")
    return note
