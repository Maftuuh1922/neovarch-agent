"""The agent changing itself: skills, memory notes, settings, persona — always undoable.

Every change goes through :func:`record`, which first copies what is about to
change into ``~/.neovarch/self/backups/<change-id>/`` and appends one line to
``~/.neovarch/self/journal.jsonl`` (the change log). :func:`undo` reverses the
newest change that is not undone yet: a backed-up file or folder is put back, a
newly created one is moved aside (never deleted), a setting gets its previous
value, and a code patch is reverted with ``git revert``. ``/undo`` and
"Pulihkan versi sebelumnya" in chat call it.

Nothing here prints or stores a secret: settings that hold keys are not
writable through these helpers, and values are passed through
:func:`neovarch.diagnose.redact` before they reach the log.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from neovarch import config as cfgmod
from neovarch.paths import neovarch_home

_LOCK = threading.RLock()
NAME_RX = re.compile(r"[^a-zA-Z0-9_.-]+")

# Settings the agent may change on its own (dotted config keys). Anything with a
# key, token or endpoint secret is deliberately absent.
SETTINGS: dict[str, dict[str, Any]] = {
    "model.default": {"type": "str", "label": "Model bawaan"},
    "model.provider": {"type": "str", "label": "Penyedia model bawaan"},
    "model.context_length": {"type": "int", "label": "Panjang konteks model"},
    "agent.system_prompt": {"type": "str", "label": "Instruksi tambahan agen"},
    "agent.max_turns": {"type": "int", "label": "Batas langkah per giliran", "min": 1, "max": 200},
    "agent.reasoning_effort": {"type": "str", "label": "Tingkat penalaran bawaan"},
    "agent.escalate_on_stuck": {"type": "bool", "label": "Naik ke model lebih kuat saat buntu"},
    "agent.escalation_model": {"type": "str", "label": "Model kuat untuk saat buntu"},
    "agent.escalation_provider": {"type": "str", "label": "Penyedia model kuat"},
    "tools.disabled": {"type": "list", "label": "Alat yang dimatikan"},
    "skills.disabled": {"type": "list", "label": "Skill yang dimatikan"},
    "memory.obsidian_enabled": {"type": "bool", "label": "Pakai vault Obsidian"},
    "approvals.mode": {"type": "str", "label": "Mode persetujuan", "choices": ["ask", "off"], "risky": "off"},
    "display.show_reasoning": {"type": "bool", "label": "Tampilkan penalaran"},
}
# Tools the agent needs to repair itself; they can never be switched off.
PROTECTED_TOOLS = {"self_diagnose", "self_undo", "settings_update", "core_reload", "manage"}


class SelfEditError(ValueError):
    pass


def self_dir() -> Path:
    d = neovarch_home() / "self"
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_path() -> Path:
    return self_dir() / "journal.jsonl"


def _safe(name: str) -> str:
    return NAME_RX.sub("-", str(name or "")).strip(".-")


def _redact(value: Any) -> Any:
    from neovarch.diagnose import redact
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


# ----------------------------------------------------------------- journal --

def entries(limit: int = 50, include_undone: bool = True) -> list[dict]:
    p = journal_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    undone = {e.get("undoes") for e in out if e.get("action") == "undo"}
    for e in out:
        e["undone"] = e.get("id") in undone
    if not include_undone:
        out = [e for e in out if not e["undone"] and e.get("action") != "undo"]
    return out[-limit:]


def _append(entry: dict) -> dict:
    with _LOCK:
        with journal_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    try:
        from neovarch.logs import log
        log.info("self-change %s %s %s: %s", entry.get("kind"), entry.get("action"), entry.get("target"),
                 entry.get("summary"))
    except Exception:
        pass
    return entry


def _backup_path(target: Path, change_id: str) -> Path | None:
    """Copy ``target`` (file or folder) into the change's backup slot; None when it did not exist."""
    if not target.exists():
        return None
    dest = self_dir() / "backups" / change_id / target.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest)
    else:
        shutil.copy2(target, dest)
    return dest


def record(kind: str, action: str, target: str, path: Path | None = None, *, summary: str = "",
           before: Any = None, after: Any = None, session_id: str = "", extra: dict | None = None) -> dict:
    """Back up ``path`` (if given) and write the change-log line. Call BEFORE changing ``path``."""
    cid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    backup = _backup_path(path, cid) if path is not None else None
    entry = {"id": cid, "ts": time.time(), "kind": kind, "action": action, "target": target,
             "path": str(path) if path is not None else None, "backup": str(backup) if backup else None,
             "existed": bool(path is not None and path.exists()), "summary": summary,
             "before": _redact(before), "after": _redact(after), "session_id": session_id, **(extra or {})}
    return _append(entry)


def undo(change_id: str | None = None, session_id: str = "") -> dict:
    """Reverse the newest (or the given) change that is not undone yet."""
    pending = entries(500, include_undone=False)
    if change_id:
        pending = [e for e in pending if e["id"] == change_id]
    if not pending:
        return {"ok": False, "message": "Tidak ada perubahan yang bisa dipulihkan."}
    e = pending[-1]
    kind = e.get("kind")
    try:
        if kind == "config":
            cfg = cfgmod.load_config()
            raw_before = e.get("raw_before", e.get("before"))
            if raw_before is None:
                _delete_path(cfg, e["target"])
            else:
                cfgmod.set_path(cfg, e["target"], raw_before)
            cfgmod.save_config(cfg)
        elif kind == "code":
            from neovarch import selfpatch
            selfpatch.revert(e)
        else:
            _restore_file(e)
    except Exception as exc:  # report, never half-crash the turn
        return {"ok": False, "message": f"Gagal memulihkan {e.get('target')}: {exc}"}
    _append({"id": time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3), "ts": time.time(), "kind": kind,
             "action": "undo", "undoes": e["id"], "target": e.get("target"), "session_id": session_id,
             "summary": f"dipulihkan: {e.get('summary') or e.get('target')}"})
    return {"ok": True, "undone": e["id"], "kind": kind, "target": e.get("target"),
            "message": f"Dipulihkan ke versi sebelumnya: {_label(e)}."}


def _label(e: dict) -> str:
    kinds = {"skill": "skill", "memory": "catatan memori", "config": "pengaturan", "persona": "persona",
             "code": "patch kode"}
    return f"{kinds.get(e.get('kind'), e.get('kind'))} {e.get('target')} ({e.get('action')})"


def _delete_path(cfg: dict, dotted: str) -> None:
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def _restore_file(e: dict) -> None:
    path = Path(e["path"])
    if path.exists():  # move the current version aside, never delete it
        aside = self_dir() / "backups" / (e["id"] + "-replaced") / path.name
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(aside))
    if e.get("backup"):
        src = Path(e["backup"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, path)
        else:
            shutil.copy2(src, path)


# ------------------------------------------------------------------ skills --

def skills_root() -> Path:
    return neovarch_home() / "skills"


def _skill_doc(name: str, description: str, body: str) -> str:
    body = str(body or "").strip()
    if body.startswith("---"):
        return body + "\n"
    desc = " ".join(str(description or "").split()) or name
    return f"---\nname: {name}\ndescription: {desc}\nauthor: agent\n---\n{body}\n"


def skill_manage(action: str, name: str, *, content: str = "", description: str = "", old_text: str = "",
                 new_text: str = "", session_id: str = "") -> dict:
    """create | edit (whole SKILL.md) | patch (replace text) | delete (archived, undoable) | view | list."""
    action = str(action or "list")
    if action == "list":
        from neovarch.tools import list_skills
        return {"ok": True, "skills": [{"name": s["name"], "description": s["description"], "enabled": s["enabled"]}
                                       for s in list_skills(include_disabled=True)]}
    safe = _safe(name)
    if not safe:
        raise SelfEditError("nama skill wajib diisi")
    folder = skills_root() / safe
    doc = folder / "SKILL.md"
    if action == "view":
        if not doc.exists():
            raise SelfEditError(f"skill '{safe}' tidak ditemukan")
        return {"ok": True, "name": safe, "content": doc.read_text(encoding="utf-8", errors="replace")}
    if action == "create":
        if doc.exists():
            raise SelfEditError(f"skill '{safe}' sudah ada; pakai action edit atau patch")
        if not str(content or "").strip():
            raise SelfEditError("content (isi SKILL.md) wajib diisi")
        e = record("skill", "create", safe, folder, summary=f"skill baru {safe}", session_id=session_id)
        folder.mkdir(parents=True, exist_ok=True)
        doc.write_text(_skill_doc(safe, description, content), encoding="utf-8")
        return {"ok": True, "change_id": e["id"], "path": str(doc), "message": f"Skill '{safe}' dibuat."}
    if not doc.exists():
        raise SelfEditError(f"skill '{safe}' tidak ditemukan")
    text = doc.read_text(encoding="utf-8", errors="replace")
    if action == "edit":
        if not str(content or "").strip():
            raise SelfEditError("content wajib diisi untuk edit")
        new = _skill_doc(safe, description or _desc_of(text), content)
    elif action == "patch":
        if not old_text:
            raise SelfEditError("old_text wajib diisi untuk patch")
        n = text.count(old_text)
        if n != 1:
            raise SelfEditError(f"old_text ditemukan {n} kali; harus tepat 1")
        new = text.replace(old_text, new_text, 1)
    elif action == "delete":
        e = record("skill", "delete", safe, folder, summary=f"hapus skill {safe}", session_id=session_id)
        aside = self_dir() / "backups" / (e["id"] + "-deleted") / safe
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(aside))
        return {"ok": True, "change_id": e["id"], "message": f"Skill '{safe}' dihapus (bisa dipulihkan dengan /undo)."}
    else:
        raise SelfEditError("action harus list, view, create, edit, patch atau delete")
    e = record("skill", action, safe, folder, summary=f"{action} skill {safe}", session_id=session_id)
    doc.write_text(new, encoding="utf-8")
    return {"ok": True, "change_id": e["id"], "path": str(doc), "message": f"Skill '{safe}' diperbarui ({action})."}


def _desc_of(text: str) -> str:
    m = re.search(r"(?m)^description:\s*(.+)$", text)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ memory --

def memory_dir() -> Path:
    d = neovarch_home() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_update(action: str, name: str = "notes", *, content: str = "", old_text: str = "", new_text: str = "",
                  session_id: str = "") -> dict:
    """list | read | write | append | replace (old_text → new_text) | delete. Every change is undoable."""
    action = str(action or "list")
    if action == "list":
        return {"ok": True, "notes": sorted(p.name for p in memory_dir().glob("*.md"))}
    safe = _safe(name) or "notes"
    target = memory_dir() / (safe if safe.endswith(".md") else safe + ".md")
    if action == "read":
        return {"ok": True, "name": target.name,
                "content": target.read_text(encoding="utf-8") if target.exists() else ""}
    if action in ("replace", "delete") and not target.exists():
        raise SelfEditError(f"catatan {target.name} tidak ditemukan")
    if action == "write":
        new = str(content or "")
    elif action == "append":
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        new = old + ("" if not old or old.endswith("\n") else "\n") + str(content or "").rstrip() + "\n"
    elif action == "replace":
        text = target.read_text(encoding="utf-8")
        if not old_text or text.count(old_text) != 1:
            raise SelfEditError("old_text harus muncul tepat 1 kali di catatan")
        new = text.replace(old_text, new_text, 1)
    elif action == "delete":
        e = record("memory", "delete", target.name, target, summary=f"hapus memori {target.name}",
                   session_id=session_id)
        target.unlink()
        return {"ok": True, "change_id": e["id"], "message": f"Catatan {target.name} dihapus (bisa /undo)."}
    else:
        raise SelfEditError("action harus list, read, write, append, replace atau delete")
    e = record("memory", action, target.name, target, summary=f"{action} memori {target.name}",
               session_id=session_id)
    target.write_text(new, encoding="utf-8")
    return {"ok": True, "change_id": e["id"], "message": f"Memori {target.name} disimpan ({action})."}


# ---------------------------------------------------------------- settings --

def _coerce(key: str, value: Any) -> Any:
    spec = SETTINGS[key]
    t = spec["type"]
    if t == "bool":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "ya", "yes", "on", "aktif")
        return bool(value)
    if t == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise SelfEditError(f"{key} harus angka") from None
        if "min" in spec and v < spec["min"] or "max" in spec and v > spec["max"]:
            raise SelfEditError(f"{key} harus di antara {spec.get('min')} dan {spec.get('max')}")
        return v
    if t == "list":
        if isinstance(value, str):
            value = [x.strip() for x in value.split(",") if x.strip()]
        return [str(x) for x in (value or [])]
    v = str(value if value is not None else "")
    if spec.get("choices") and v not in spec["choices"]:
        raise SelfEditError(f"{key} harus salah satu dari {', '.join(spec['choices'])}")
    if key == "agent.reasoning_effort" and v:
        from neovarch.session_settings import normalize_effort
        if normalize_effort(v) is None:
            raise SelfEditError(f"tingkat penalaran tidak dikenal: {v}")
    return v


def is_risky_setting(key: str, value: Any) -> bool:
    spec = SETTINGS.get(key) or {}
    return "risky" in spec and str(value) == str(spec["risky"])


def settings_view() -> dict:
    cfg = cfgmod.load_config()
    return {k: {"label": v["label"], "value": cfgmod.get_path(cfg, k)} for k, v in SETTINGS.items()}


def settings_update(key: str, value: Any, *, session_id: str = "", cfg: dict | None = None,
                    save: bool = True) -> dict:
    """Change one allowed setting; logs before/after and keeps the old value for /undo."""
    key = str(key or "")
    if key not in SETTINGS:
        raise SelfEditError(f"pengaturan '{key}' tidak boleh diubah agen. Yang boleh: {', '.join(SETTINGS)}")
    new = _coerce(key, value)
    if key == "tools.disabled":
        blocked = sorted(PROTECTED_TOOLS & set(new))
        if blocked:
            raise SelfEditError("alat ini dibutuhkan untuk memperbaiki diri dan tidak bisa dimatikan: " + ", ".join(blocked))
    cfg = cfg if cfg is not None else cfgmod.load_config()
    before = cfgmod.get_path(cfg, key)
    e = record("config", "set", key, None, summary=f"{SETTINGS[key]['label']}: {before!r} → {new!r}",
               before=before, after=new, session_id=session_id, extra={"raw_before": before})
    cfgmod.set_path(cfg, key, new)
    if save:
        cfgmod.save_config(cfg)
    return {"ok": True, "change_id": e["id"], "key": key, "before": _redact(before), "value": _redact(new),
            "message": f"{SETTINGS[key]['label']} diubah."}


def persona_update(content: str, *, session_id: str = "") -> dict:
    """Rewrite SOUL.md (the agent's persona); the old text is kept for /undo."""
    p = neovarch_home() / "SOUL.md"
    cfgmod.soul_text()  # make sure it exists so there is something to restore
    if not str(content or "").strip():
        raise SelfEditError("persona tidak boleh kosong")
    e = record("persona", "edit", "SOUL.md", p, summary="persona agen diubah", session_id=session_id)
    p.write_text(str(content).strip() + "\n", encoding="utf-8")
    return {"ok": True, "change_id": e["id"], "message": "Persona agen diperbarui (bisa /undo)."}


def change_log(limit: int = 20) -> str:
    rows = entries(limit)
    if not rows:
        return "(belum ada perubahan oleh agen)"
    out = []
    for e in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(e.get("ts") or 0)))
        flag = " [dipulihkan]" if e.get("undone") else ""
        out.append(f"- {when} {e.get('id')} {e.get('kind')}/{e.get('action')} {e.get('target')}: "
                   f"{e.get('summary') or ''}{flag}")
    return "\n".join(out)


UNDO_PHRASES = re.compile(r"^\s*(/undo|/pulihkan|pulihkan versi sebelumnya|kembalikan versi sebelumnya|undo)\s*[.!]?\s*$",
                          re.IGNORECASE)
FIX_COMMAND = re.compile(r"^\s*/(perbaiki|fix)\b\s*(.*)$", re.IGNORECASE | re.S)
