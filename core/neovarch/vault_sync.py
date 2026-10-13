"""The agent's projects and sessions as real Obsidian notes.

The vault (``memory.obsidian_vault``) stays a plain Obsidian vault: Markdown notes with
YAML frontmatter, ``[[wikilinks]]``, ``#tags`` and a ``.obsidian/`` config folder, so it opens
directly in the Obsidian app. On top of that the agent keeps one note per project (the folder a
chat works in), one per session, and one per file it changed, all linked to each other:

    Neovarch/Neovarch.md                         hub: every project
    Neovarch/Proyek/<project>.md                 project: its sessions, files, notes
    Neovarch/Proyek/<project>/Berkas/<rel>.md    a file the agent changed (relative to the project)
    Neovarch/Sesi/<date> <title> <id>.md         one chat: its project, files, notes written
    Neovarch/Memori/<name>.md                    the agent's own memory notes (copied, see migrate)

Only the block between ``AUTO_START`` and ``AUTO_END`` is rewritten; anything a person writes
outside it in Obsidian is kept. Nothing outside the vault is touched, and nothing the user wrote
is ever deleted or overwritten (migration only adds files, after a zip backup).
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from neovarch import config as cfgmod
from neovarch import obsidian

ROOT = "Neovarch"
AUTO_START = "<!-- neovarch:auto:start (diperbarui otomatis oleh Neovarch; tulis catatanmu di luar blok ini) -->"
AUTO_END = "<!-- neovarch:auto:end -->"
_AUTO_RE = re.compile(r"<!-- neovarch:auto:start[^>]*-->.*?<!-- neovarch:auto:end -->", re.S)
_BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+')
WRITE_TOOLS = {"write_file", "edit_file", "patch", "apply_patch", "multi_edit", "str_replace"}
MAX_LIST = 200
BACKUP_MAX_BYTES = 512 * 1024 * 1024

# Colour groups shared by the built-in graph and Obsidian's own graph (.obsidian/graph.json).
GROUPS = {
    "project": ("tag:#neovarch/proyek", 0xE5484D),
    "session": ("tag:#neovarch/sesi", 0x3E9BF7),
    "file": ("tag:#neovarch/berkas", 0x46A758),
    "memory": ("tag:#neovarch/memori", 0xF5A524),
}

OBSIDIAN_CONFIG: dict[str, Any] = {
    "app.json": {"alwaysUpdateLinks": True, "newLinkFormat": "shortest", "useMarkdownLinks": False,
                 "showFrontmatter": True, "promptDelete": True},
    "core-plugins.json": {name: True for name in (
        "file-explorer", "global-search", "switcher", "graph", "backlink", "outgoing-link", "tag-pane",
        "properties", "page-preview", "outline", "word-count", "file-recovery")},
    "graph.json": {
        "collapse-filter": False, "search": "", "showTags": False, "showAttachments": False,
        "hideUnresolved": False, "showOrphans": True, "collapse-color-groups": False,
        "colorGroups": [{"query": q, "color": {"a": 1, "rgb": rgb}} for q, rgb in GROUPS.values()],
        "collapse-display": False, "showArrow": False, "textFadeMultiplier": 0, "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1, "collapse-forces": True, "centerStrength": 0.5, "repelStrength": 10,
        "linkStrength": 1, "linkDistance": 250, "scale": 1, "close": False,
    },
}


# ---------------------------------------------------------------- settings --
def autonotes_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else cfgmod.load_config()
    val = cfgmod.get_path(cfg, "memory.vault_autonotes", True)
    if isinstance(val, str):
        return val.strip().lower() not in ("0", "false", "no", "off")
    return val is not False


def default_vault_dir() -> Path:
    explicit = os.environ.get("NEOVARCH_VAULT_DIR", "").strip()
    if explicit:
        return Path(os.path.expanduser(explicit)).resolve()
    return (Path.home() / "Neovarch Vault").resolve()


def _state_path() -> Path:
    return cfgmod.neovarch_home() / "vault_state.json"


def _state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ----------------------------------------------------------------- helpers --
def slug(text: str, limit: int = 80) -> str:
    """A filename Obsidian accepts and wikilinks can reach (no / \\ : * ? " < > | # ^ [ ])."""
    s = _BAD_CHARS.sub(" ", str(text or "")).strip().strip(".")
    s = re.sub(r"\s+", " ", s)[:limit].strip()
    return s or "Tanpa judul"


def vault_uri(vault: Path) -> str:
    """``obsidian://open?path=...`` opens (and registers) the whole vault folder in Obsidian."""
    return "obsidian://open?path=" + quote(str(vault.resolve()))


def link(rel: str, alias: str | None = None) -> str:
    target = rel[:-3] if rel.lower().endswith(".md") else rel
    return f"[[{target}|{alias}]]" if alias else f"[[{target}]]"


def _dump_fm(fm: dict) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000) + "---\n"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.nvtmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def upsert_note(vault: Path, rel: str, fm_updates: dict, auto_body: str, *, user_stub: str = "") -> Path:
    """Create or update a managed note: merge ``fm_updates`` into its frontmatter and replace only
    the auto block. Text a person wrote outside the block stays as it is."""
    p = obsidian.safe_path(vault, rel)
    old = _read(p) if p.exists() else ""
    fm, _, body = obsidian.split_frontmatter(old)
    fm = {**fm, **{k: v for k, v in fm_updates.items() if v is not None}}
    block = f"{AUTO_START}\n{auto_body.strip()}\n{AUTO_END}"
    if _AUTO_RE.search(body):
        body = _AUTO_RE.sub(lambda _: block, body, count=1)
    elif body.strip():
        body = block + "\n\n" + body.lstrip("\n")
    else:
        body = block + "\n" + (f"\n{user_stub.strip()}\n" if user_stub else "")
    new = _dump_fm(fm) + body.rstrip("\n") + "\n"
    if new != old:
        obsidian.safe_path(vault, rel)  # re-check right before writing (symlinked parents)
        _write(p, new)
    return p


def _push(lst: list | None, item: str, limit: int = MAX_LIST) -> list:
    out = [x for x in (lst or []) if x != item]
    out.insert(0, item)
    return out[:limit]


def _clip(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _quote_block(text: str, n: int) -> str:
    return "> " + _clip(text, n) if text else "> (kosong)"


# ---------------------------------------------------------------- projects --
def project_name(cwd: str | Path | None) -> str | None:
    """The project a chat works in = its folder; none for the home folder or the filesystem root."""
    if not cwd:
        return None
    try:
        p = Path(os.path.expanduser(str(cwd))).resolve()
    except OSError:
        return None
    if p == Path.home().resolve() or p.parent == p or not p.name:
        return None
    return p.name


def project_rel(vault: Path, cwd: str | Path) -> str | None:
    name = project_name(cwd)
    if not name:
        return None
    path = str(Path(os.path.expanduser(str(cwd))).resolve())
    base = f"{ROOT}/Proyek/{slug(name)}.md"
    existing = obsidian.safe_path(vault, base)
    if existing.exists():
        fm, _, _ = obsidian.split_frontmatter(_read(existing))
        if fm.get("path") and str(fm.get("path")) != path:  # same folder name, different project
            parent = slug(Path(path).parent.name or "root", 40)
            return f"{ROOT}/Proyek/{slug(name)} ({parent}).md"
    return base


def _file_rel(project_rel_: str, relpath: str) -> str:
    folder = project_rel_[:-3]
    parts = [slug(part, 120) for part in Path(relpath).parts if part not in ("", ".", "..")]
    return f"{folder}/Berkas/" + "/".join(parts) + ".md"


def _rel_inside(cwd: Path, path: str) -> str | None:
    raw = Path(os.path.expanduser(str(path)))
    p = raw if raw.is_absolute() else cwd / raw
    try:
        p = p.resolve()
        return p.relative_to(cwd).as_posix()
    except (OSError, ValueError):
        return None


def session_rel(rec: dict) -> str:
    if rec.get("vault_note"):
        return str(rec["vault_note"])
    created = float(rec.get("created_at") or time.time())
    day = time.strftime("%Y-%m-%d", time.localtime(created))
    title = slug(rec.get("title") or "Sesi", 60)
    sid = str(rec.get("id") or "")[-6:] or "baru"
    return f"{ROOT}/Sesi/{day} {title} {slug(sid, 10)}.md"


def _messages_info(rec: dict) -> dict[str, Any]:
    """First request, last answer, files changed and vault notes written/read in this chat."""
    msgs = rec.get("messages") or []
    first = next((m.get("content") for m in msgs if m.get("role") == "user" and not m.get("hidden")
                  and isinstance(m.get("content"), str) and m.get("content").strip()), "")
    last = next((m.get("content") for m in reversed(msgs) if m.get("role") == "assistant"
                 and isinstance(m.get("content"), str) and m.get("content").strip()), "")
    files: list[str] = []
    notes_written: list[str] = []
    notes_read: list[str] = []
    for m in msgs:
        for f in m.get("files_changed") or []:
            if f not in files:
                files.append(str(f))
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {}
            if not isinstance(args, dict):
                continue
            path = str(args.get("path") or args.get("file_path") or "")
            if name in WRITE_TOOLS and path and path not in files:
                files.append(path)
            elif name == "obsidian_write" and path and path not in notes_written:
                notes_written.append(path)
            elif name in ("obsidian_read", "obsidian_links") and path and path not in notes_read:
                notes_read.append(path)
    turns = sum(1 for m in msgs if m.get("role") == "user" and not m.get("hidden"))
    return {"first": first, "last": last, "files": files, "notes_written": notes_written,
            "notes_read": notes_read, "turns": turns}


def _note_rel(vault: Path, raw: str) -> str | None:
    """A path the agent passed to obsidian_* resolved to an existing note, else None."""
    try:
        p = obsidian.safe_path(vault, raw)
    except obsidian.VaultError:
        return None
    if p.exists():
        return obsidian.rel_of(vault, p)
    found = obsidian.find_by_name(vault, Path(raw).stem)
    return obsidian.rel_of(vault, found) if found else None


# -------------------------------------------------------------- recording --
def record_session(vault: Path, rec: dict, files_changed: list[str] | None = None,
                   cwd: str | Path | None = None) -> dict[str, Any]:
    """Write/refresh the notes for one chat (session + project + changed files + hub).
    Returns ``{"session": rel, "project": rel|None, "files": [rel...]}``."""
    vault = vault.resolve()
    cwd_s = str(cwd or rec.get("cwd") or "")
    info = _messages_info(rec)
    for f in files_changed or []:
        if f not in info["files"]:
            info["files"].append(str(f))
    s_rel = session_rel(rec)
    p_rel = project_rel(vault, cwd_s) if cwd_s else None
    pname = project_name(cwd_s) if cwd_s else None
    cwd_path = Path(os.path.expanduser(cwd_s)).resolve() if cwd_s else None

    file_links: list[tuple[str, str]] = []  # (note rel, relpath shown)
    if p_rel and cwd_path is not None:
        for f in info["files"][:MAX_LIST]:
            rel_in = _rel_inside(cwd_path, f)
            if not rel_in:
                continue
            f_rel = _file_rel(p_rel, rel_in)
            try:
                obsidian.safe_path(vault, f_rel)
            except obsidian.VaultError:
                continue
            file_links.append((f_rel, rel_in))

    notes = [r for r in (_note_rel(vault, n) for n in info["notes_written"]) if r]
    read = [r for r in (_note_rel(vault, n) for n in info["notes_read"]) if r and r not in notes]
    now = time.strftime("%Y-%m-%d %H:%M")
    created = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(rec.get("created_at") or time.time())))
    title = rec.get("title") or _clip(info["first"], 60) or "Sesi"

    # session note
    lines = [f"# {title}", ""]
    lines.append(f"- Proyek: {link(p_rel, pname)}" if p_rel else f"- Proyek: (tanpa folder proyek) · {link(f'{ROOT}/Neovarch', 'Neovarch')}")
    lines += [f"- Model: `{rec.get('model') or '-'}` · Sumber: {rec.get('source') or '-'} · Giliran: {info['turns']}",
              f"- Mulai: {created} · Diperbarui: {now}", "", "## Permintaan", _quote_block(info["first"], 500), "",
              "## Hasil terakhir", _quote_block(info["last"], 900), ""]
    if file_links:
        lines += ["## Berkas diubah", *[f"- {link(r, shown)}" for r, shown in file_links[:60]], ""]
    if notes:
        lines += ["## Catatan & keputusan yang ditulis", *[f"- {link(r)}" for r in notes], ""]
    if read:
        lines += ["## Catatan yang dibaca", *[f"- {link(r)}" for r in read[:30]], ""]
    upsert_note(vault, s_rel, {
        "neovarch": "session", "session_id": rec.get("id"), "title": title, "project": pname,
        "model": rec.get("model") or None, "source": rec.get("source") or None,
        "created": created, "updated": now, "tags": ["neovarch/sesi"],
    }, "\n".join(lines))

    # file notes
    for f_rel, shown in file_links:
        fp = obsidian.safe_path(vault, f_rel)
        fm, _, _ = obsidian.split_frontmatter(_read(fp)) if fp.exists() else ({}, "", "")
        sessions = _push(fm.get("neovarch_sessions"), s_rel)
        abs_path = (cwd_path / shown) if cwd_path is not None else Path(shown)
        body = [f"# {Path(shown).name}", "", f"- Proyek: {link(p_rel, pname)}",
                f"- Berkas: [{shown}]({abs_path.as_uri() if abs_path.is_absolute() else shown})", "",
                "## Diubah di sesi", *[f"- {link(s)}" for s in sessions[:50]]]
        upsert_note(vault, f_rel, {"neovarch": "file", "project": pname, "path": str(abs_path), "updated": now,
                                   "neovarch_sessions": sessions, "tags": ["neovarch/berkas"]}, "\n".join(body))

    # project note
    if p_rel:
        pp = obsidian.safe_path(vault, p_rel)
        fm, _, _ = obsidian.split_frontmatter(_read(pp)) if pp.exists() else ({}, "", "")
        sessions = _push(fm.get("neovarch_sessions"), s_rel)
        pfiles = list(fm.get("neovarch_files") or [])
        for f_rel, _shown in file_links:
            pfiles = _push(pfiles, f_rel, 400)
        pnotes = list(fm.get("neovarch_notes") or [])
        for n in notes:
            pnotes = _push(pnotes, n)
        body = [f"# {pname}", "", f"- Folder: `{cwd_path}`", f"- Hub: {link(f'{ROOT}/Neovarch', 'Neovarch')}",
                f"- Diperbarui: {now}", "", f"## Sesi ({len(sessions)})", *[f"- {link(s)}" for s in sessions[:60]]]
        if pfiles:
            body += ["", f"## Berkas ({len(pfiles)})",
                     *[f"- {link(f, f[len(p_rel[:-3]) + len('/Berkas/'):-3])}" for f in pfiles[:120]]]
        if pnotes:
            body += ["", "## Catatan & keputusan", *[f"- {link(n)}" for n in pnotes[:60]]]
        upsert_note(vault, p_rel, {"neovarch": "project", "path": str(cwd_path), "updated": now,
                                   "neovarch_sessions": sessions, "neovarch_files": pfiles,
                                   "neovarch_notes": pnotes, "tags": ["neovarch/proyek"]},
                    "\n".join(body), user_stub="## Catatan\n")
    write_hub(vault)
    return {"session": s_rel, "project": p_rel, "files": [r for r, _ in file_links]}


def write_hub(vault: Path) -> str:
    rel = f"{ROOT}/Neovarch.md"
    projects = []
    pdir = vault / ROOT / "Proyek"
    if pdir.is_dir():
        projects = sorted(p for p in pdir.glob("*.md"))
    mem = sorted((vault / ROOT / "Memori").glob("*.md")) if (vault / ROOT / "Memori").is_dir() else []
    body = ["# Neovarch", "", "Peta kerja agen Neovarch: setiap proyek, sesi, dan berkas yang diubah tertaut di sini.",
            "", f"## Proyek ({len(projects)})", *[f"- {link(obsidian.rel_of(vault, p), p.stem)}" for p in projects]]
    if mem:
        body += ["", "## Memori agen", *[f"- {link(obsidian.rel_of(vault, p), p.stem)}" for p in mem]]
    upsert_note(vault, rel, {"neovarch": "hub", "tags": ["neovarch"]}, "\n".join(body))
    return rel


def record_turn(cfg: dict, rec: dict, files_changed: list[str] | None = None,
                cwd: str | Path | None = None) -> str | None:
    """Called after every turn. Returns the session note path, or None when the vault or auto
    notes are off. Never raises into the turn (the caller wraps it, but be safe twice)."""
    if not autonotes_enabled(cfg):
        return None
    try:
        vault = obsidian.require_vault(cfg)
    except obsidian.VaultError:
        return None
    res = record_session(vault, rec, files_changed, cwd)
    return res["session"]


# ------------------------------------------------------------------ context --
def context_for(cfg: dict, cwd: str | Path | None, limit: int = 5) -> str:
    """Short prompt context: this project's note in the vault, its latest sessions and the notes
    that link to it (backlinks), so the agent can pick up where earlier chats left off."""
    if not autonotes_enabled(cfg):
        return ""
    vault = obsidian.vault_path(cfg)
    if vault is None or not vault.is_dir() or not cwd:
        return ""
    p_rel = project_rel(vault, cwd)
    if not p_rel:
        return ""
    p = obsidian.safe_path(vault, p_rel)
    if not p.exists():
        return ""
    fm, _, _ = obsidian.split_frontmatter(_read(p))
    sessions = [Path(s).stem for s in (fm.get("neovarch_sessions") or [])[:limit]]
    notes = [Path(n).stem for n in (fm.get("neovarch_notes") or [])[:limit]]
    back = [b["title"] for b in obsidian.links(vault, p_rel)["backlinks"]
            if not b["path"].startswith(f"{ROOT}/Sesi/") and not b["path"].startswith(p_rel[:-3] + "/")][:limit]
    out = [f"# Proyek ini di vault Obsidian\nCatatan proyek: {p_rel} (baca dengan obsidian_read; "
           "obsidian_links untuk backlink)."]
    if sessions:
        out.append("Sesi sebelumnya: " + "; ".join(sessions))
    if notes:
        out.append("Catatan & keputusan proyek: " + "; ".join(notes))
    if back:
        out.append("Catatan lain yang menautkan proyek ini: " + "; ".join(back))
    out.append(f"Simpan keputusan penting sebagai catatan dengan tautan [[{Path(p_rel).stem}]] dan tag #keputusan.")
    return "\n".join(out)


# ---------------------------------------------------------------- migration --
def ensure_obsidian_config(vault: Path) -> list[str]:
    """Create the .obsidian/ files Obsidian needs to open the folder as a vault. Existing
    files are never changed (the user's own Obsidian settings win)."""
    cfg_dir = vault / ".obsidian"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for name, data in OBSIDIAN_CONFIG.items():
        p = cfg_dir / name
        if not p.exists():
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            created.append(f".obsidian/{name}")
    return created


def backup_vault(vault: Path, dest_dir: Path | None = None) -> str | None:
    """Zip the vault (notes, attachments, .obsidian) before the first migration. Returns the zip
    path, or None when there is nothing to back up."""
    vault = vault.resolve()
    files = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(vault, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".trash")]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if total + size > BACKUP_MAX_BYTES:
                continue
            total += size
            files.append(p)
    if not files:
        return None
    dest_dir = dest_dir or (cfgmod.neovarch_home() / "backups")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"vault-{slug(vault.name, 40).replace(' ', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(vault).as_posix())
    return str(out)


def import_memory(vault: Path) -> list[str]:
    """Copy the agent's memory notes (~/.neovarch/memory/*.md) into Neovarch/Memori/. The originals
    stay where they are; a note already in the vault is left alone."""
    src = cfgmod.neovarch_home() / "memory"
    out = []
    if not src.is_dir():
        return out
    for p in sorted(src.glob("*.md")):
        rel = f"{ROOT}/Memori/{slug(p.stem)}.md"
        target = obsidian.safe_path(vault, rel)
        if target.exists():
            continue
        text = _read(p)
        fm, block, body = obsidian.split_frontmatter(text)
        fm = {**fm, "neovarch": "memory", "source": str(p), "tags": sorted(set(
            [*(fm.get("tags") or [] if isinstance(fm.get("tags"), list) else []), "neovarch/memori"]))}
        _write(target, _dump_fm(fm) + body.lstrip("\n").rstrip("\n") + f"\n\n{link(f'{ROOT}/Neovarch', 'Neovarch')}\n")
        out.append(rel)
    return out


def backfill(vault: Path, limit: int = 200) -> int:
    """Notes for chats that ran before the vault was linked (newest ``limit``)."""
    from neovarch.store import SessionStore
    store = SessionStore()
    n = 0
    for summary in store.list(limit=limit):
        rec = store.load(summary["id"])
        if not rec or not rec.get("messages"):
            continue
        try:
            res = record_session(vault, rec)
        except (OSError, obsidian.VaultError):
            continue
        if rec.get("vault_note") != res["session"]:
            # remember the note without touching updated_at (keeps the chat's "last active" order)
            from neovarch.store import _LOCK, _atomic_write
            rec["vault_note"] = res["session"]
            with _LOCK:
                _atomic_write(store.path(rec["id"]), rec)
        n += 1
    return n


def migrate(vault: Path, *, backup: bool = True, sessions: bool = True) -> dict[str, Any]:
    """Make ``vault`` a full Neovarch Obsidian vault without losing anything: zip backup first
    (once per vault), .obsidian config, agent memory copied in, past chats as notes, hub note."""
    vault = vault.resolve()
    if obsidian.is_foreign_path(vault):
        raise obsidian.VaultError("the folder is inside a foreign agent install; Neovarch does not touch it")
    vault.mkdir(parents=True, exist_ok=True)
    state = _state()
    key = str(vault)
    entry = dict(state.get(key) or {})
    backup_path = None
    if backup and not entry.get("backup"):
        backup_path = backup_vault(vault)
        if backup_path:
            entry["backup"] = backup_path
    created = ensure_obsidian_config(vault)
    memory = import_memory(vault)
    count = backfill(vault) if sessions else 0
    write_hub(vault)
    entry["migrated_at"] = time.time()
    state[key] = entry
    _save_state(state)
    return {"vault": key, "backup": entry.get("backup"), "new_backup": backup_path, "obsidian_config": created,
            "memory_imported": memory, "sessions": count, "open_uri": vault_uri(vault)}


def init(path: str | None = None) -> dict[str, Any]:
    """Settings ▸ Vault Obsidian ▸ "Siapkan vault": use ``path``, else the saved vault, else
    ~/Neovarch Vault; create it, link it in config, then :func:`migrate`."""
    cfg = cfgmod.load_config()
    raw = str(path or "").strip()
    target = Path(os.path.expanduser(raw)).resolve() if raw else (obsidian.configured_path(cfg) or default_vault_dir())
    if obsidian.is_foreign_path(target):
        raise obsidian.VaultError("the folder is inside a foreign agent install; Neovarch does not touch it")
    target.mkdir(parents=True, exist_ok=True)
    obsidian.configure(str(target), True)
    res = migrate(target)
    return {**res, "status": obsidian.status()}
