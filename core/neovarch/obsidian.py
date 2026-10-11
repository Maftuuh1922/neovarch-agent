"""Obsidian vault as long-term memory.

The vault is a plain folder of markdown notes (``memory.obsidian_vault`` in
config.yaml). The agent can search, read, write and follow links in it. Every
path is resolved and must stay inside the vault: ``..``, absolute paths and
symlinks that point outside are refused, and so is any foreign path (see
``paths.is_foreign_path``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from neovarch import config as cfgmod
from neovarch.paths import check_path, is_foreign_path

SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules"}
MAX_NOTE_BYTES = 2_000_000
_WIKILINK = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
_TAG = re.compile(r"(?:(?<=\s)|^)#([A-Za-z0-9_/\-]*[A-Za-z_/\-][A-Za-z0-9_/\-]*)")
_STOP = {
    "yang", "dan", "atau", "untuk", "dengan", "dari", "pada", "ini", "itu", "akan", "bisa", "saya", "kamu",
    "tolong", "buat", "buatkan", "apa", "the", "and", "for", "with", "that", "this", "what", "from", "have",
    "your", "about", "please", "into", "make", "show", "tell", "dalam", "juga", "sudah", "belum", "ada",
}


class VaultError(ValueError):
    pass


def configured_path(cfg: dict | None = None) -> Path | None:
    """The saved vault folder, whether or not the vault is switched on."""
    cfg = cfg if cfg is not None else cfgmod.load_config()
    raw = str(cfgmod.get_path(cfg, "memory.obsidian_vault", "") or "").strip()
    if not raw:
        return None
    return Path(os.path.expanduser(raw)).resolve()


def is_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else cfgmod.load_config()
    val = cfgmod.get_path(cfg, "memory.obsidian_enabled", True)
    if isinstance(val, str):
        return val.strip().lower() not in ("0", "false", "no", "off")
    return val is not False


def vault_path(cfg: dict | None = None) -> Path | None:
    """The vault the agent and the viewer use: None when unset or switched off."""
    cfg = cfg if cfg is not None else cfgmod.load_config()
    if not is_enabled(cfg):
        return None
    return configured_path(cfg)


def configure(path: str, enabled: bool = True) -> dict[str, Any]:
    """Save ``memory.obsidian_vault`` / ``memory.obsidian_enabled`` (Settings ▸ Vault Obsidian).

    An enabled vault must be an existing folder outside any Hermes install;
    an empty path clears it. Returns the new :func:`status`.
    """
    raw = str(path or "").strip()
    if raw:
        target = Path(os.path.expanduser(raw)).resolve()
        if is_foreign_path(target):
            raise VaultError("the folder is inside a Hermes Agent install; Neovarch does not touch it")
        if enabled and not target.is_dir():
            raise VaultError(f"the folder does not exist: {target}")
        raw = str(target)
    cfg = cfgmod.load_config()
    cfgmod.set_path(cfg, "memory.obsidian_vault", raw)
    cfgmod.set_path(cfg, "memory.obsidian_enabled", bool(enabled))
    cfgmod.save_config(cfg)
    return status(cfg)


def require_vault(cfg: dict | None = None) -> Path:
    vault = vault_path(cfg)
    if vault is None:
        raise VaultError("no Obsidian vault is configured (set memory.obsidian_vault)")
    if is_foreign_path(vault):
        raise VaultError("the configured vault is inside a Hermes Agent install; Neovarch does not touch it")
    if not vault.is_dir():
        raise VaultError(f"the Obsidian vault folder does not exist: {vault}")
    return vault


def safe_path(vault: Path, rel: str, *, note: bool = True) -> Path:
    """Resolve ``rel`` inside ``vault``; refuse anything that escapes it."""
    rel = str(rel or "").strip().replace("\\", "/")
    if not rel:
        raise VaultError("path is required")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or rel.startswith("~"):
        raise VaultError("use a path relative to the vault")
    if note and not rel.lower().endswith(".md"):
        rel += ".md"
    root = vault.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise VaultError(f"{rel} is outside the Obsidian vault")
    if any(part in SKIP_DIRS for part in target.relative_to(root).parts[:-1]):
        raise VaultError(f"{rel} is inside a hidden vault folder")
    check_path(target)
    return target


def iter_notes(vault: Path):
    root = vault.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.lower().endswith(".md"):
                p = Path(dirpath) / name
                try:
                    real = p.resolve()
                except OSError:
                    continue
                if real == root or root in real.parents:
                    yield p


def rel_of(vault: Path, p: Path) -> str:
    return p.relative_to(vault.resolve()).as_posix()


def note_count(vault: Path | None) -> int:
    if vault is None or not vault.is_dir():
        return 0
    return sum(1 for _ in iter_notes(vault))


def split_frontmatter(text: str) -> tuple[dict, str, str]:
    """(frontmatter dict, raw frontmatter block incl. fences, body)."""
    if text.startswith("---"):
        m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
        if m:
            try:
                data = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                data = {}
            return (data if isinstance(data, dict) else {}), m.group(0), text[m.end():]
    return {}, "", text


def note_tags(text: str) -> list[str]:
    fm, _, body = split_frontmatter(text)
    tags: list[str] = []
    raw = fm.get("tags") or fm.get("tag") or []
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw) if t]
    if isinstance(raw, list):
        tags += [str(t).lstrip("#") for t in raw if t]
    body_no_code = re.sub(r"```.*?```", " ", body, flags=re.S)
    tags += _TAG.findall(body_no_code)
    seen: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.append(t)
    return seen


def _read(p: Path) -> str:
    if p.stat().st_size > MAX_NOTE_BYTES:
        return p.read_bytes()[:MAX_NOTE_BYTES].decode("utf-8", "replace")
    return p.read_text(encoding="utf-8", errors="replace")


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if pos < 0:
        _, _, body = split_frontmatter(text)
        return re.sub(r"\s+", " ", body).strip()[:width]
    start = max(pos - width // 3, 0)
    return ("…" if start else "") + re.sub(r"\s+", " ", text[start:start + width]).strip()


def search(vault: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    tag_terms = [t[1:] for t in q.split() if t.startswith("#") and len(t) > 1]
    terms = [t.lstrip("#") for t in re.findall(r"#?[\w/\-]+", q) if len(t.lstrip("#")) >= 2]
    results = []
    for p in iter_notes(vault):
        try:
            text = _read(p)
        except OSError:
            continue
        low = text.lower()
        name = p.stem.lower()
        tags = [t.lower() for t in note_tags(text)]
        score = 0.0
        if q in name:
            score += 10
        for t in terms:
            if t in name:
                score += 5
            if any(tag == t or tag.startswith(t + "/") for tag in tags):
                score += 6
            score += min(low.count(t), 10)
        for t in tag_terms:
            if not any(tag == t or tag.startswith(t + "/") for tag in tags):
                score = 0
                break
        if q in low:
            score += 3
        if score > 0:
            results.append({"path": rel_of(vault, p), "title": p.stem, "tags": note_tags(text),
                            "score": round(score, 1), "snippet": _snippet(text, terms or [q])})
    results.sort(key=lambda r: (-r["score"], r["path"]))
    return results[:max(1, min(int(limit or 10), 50))]


def read_note(vault: Path, rel: str) -> dict[str, Any]:
    p = safe_path(vault, rel)
    if not p.exists():
        found = find_by_name(vault, Path(rel).stem)
        if not found:
            raise FileNotFoundError(rel)
        p = found
    text = _read(p)
    fm, _, body = split_frontmatter(text)
    return {"path": rel_of(vault, p), "title": p.stem, "frontmatter": fm, "tags": note_tags(text),
            "links": sorted(set(l.strip() for l in _WIKILINK.findall(text))), "content": text}


def find_by_name(vault: Path, stem: str) -> Path | None:
    stem = stem.strip().lower()
    for p in iter_notes(vault):
        if p.stem.lower() == stem:
            return p
    return None


def write_note(vault: Path, rel: str, content: str, mode: str = "create",
               frontmatter: dict | None = None) -> dict[str, Any]:
    """mode: create (fails if it exists) | append | overwrite (keeps the old frontmatter
    when the new content has none). Content is written verbatim, so [[wikilinks]] stay."""
    mode = (mode or "create").lower()
    if mode not in ("create", "append", "overwrite"):
        raise VaultError("mode must be create, append or overwrite")
    p = safe_path(vault, rel)
    content = str(content or "")
    exists = p.exists()
    if mode == "create" and exists:
        raise VaultError(f"{rel_of(vault, p)} already exists; use mode=append or overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    # re-check after mkdir: a symlinked parent could point outside
    safe_path(vault, rel_of(vault, p))
    if mode == "append" and exists:
        old = _read(p)
        fm, block, body = split_frontmatter(old)
        if frontmatter:
            fm = {**fm, **frontmatter}
            block = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n"
        sep = "" if not body or body.endswith("\n") else "\n"
        new = block + body + sep + content.rstrip("\n") + "\n"
    else:
        new_fm, new_block, new_body = split_frontmatter(content)
        if mode == "overwrite" and exists and not new_block:
            _, old_block, _ = split_frontmatter(_read(p))
            new_block = old_block
        if frontmatter:
            merged = {**new_fm, **frontmatter} if new_block else dict(frontmatter)
            if mode == "overwrite" and exists and not new_fm:
                merged = {**split_frontmatter(_read(p))[0], **frontmatter}
            new_block = "---\n" + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True) + "---\n"
        new = new_block + new_body.rstrip("\n") + "\n"
    tmp = p.with_name(f".{p.name}.nvtmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, p)
    return {"path": rel_of(vault, p), "mode": mode if exists or mode != "append" else "create",
            "bytes": len(new.encode("utf-8"))}


def links(vault: Path, rel: str) -> dict[str, Any]:
    p = safe_path(vault, rel)
    if not p.exists():
        found = find_by_name(vault, Path(rel).stem)
        if found:
            p = found
    stem = p.stem.lower()
    relpath_noext = rel_of(vault, p)[:-3].lower() if p.exists() else ""
    backlinks = []
    for other in iter_notes(vault):
        if other.resolve() == p.resolve():
            continue
        try:
            text = _read(other)
        except OSError:
            continue
        targets = [t.strip().lower() for t in _WIKILINK.findall(text)]
        if any(t == stem or t == relpath_noext or t.endswith("/" + stem) for t in targets):
            backlinks.append({"path": rel_of(vault, other), "title": other.stem,
                              "snippet": _snippet(text, ["[[" + p.stem.lower()])})
    outgoing = []
    if p.exists():
        outgoing = sorted(set(l.strip() for l in _WIKILINK.findall(_read(p))))
    return {"path": rel_of(vault, p) if p.exists() else rel, "backlinks": backlinks, "outgoing": outgoing}


def keywords(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[\w\-]{4,}", (text or "").lower())
    out: list[str] = []
    for w in words:
        if w not in _STOP and not w.isdigit() and w not in out:
            out.append(w)
    return out[:limit]


def relevant_notes(vault: Path, text: str, limit: int = 3, max_chars: int = 1500) -> list[dict[str, str]]:
    """Simple keyword retrieval for prompt injection."""
    kws = keywords(text)
    if not kws:
        return []
    scored: dict[str, float] = {}
    for kw in kws:
        for r in search(vault, kw, limit=20):
            scored[r["path"]] = scored.get(r["path"], 0) + r["score"]
    out = []
    for path, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        try:
            text_ = _read(safe_path(vault, path))
        except (OSError, VaultError):
            continue
        out.append({"path": path, "content": text_[:max_chars]})
    return out


def status(cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else cfgmod.load_config()
    enabled = is_enabled(cfg)
    saved = configured_path(cfg)
    vault = saved if enabled else None
    if vault is None:
        return {"configured": False, "connected": False, "enabled": enabled,
                "path": str(saved) if saved else "", "note_count": 0}
    ok = vault.is_dir() and not is_foreign_path(vault)
    return {"configured": True, "connected": ok, "enabled": enabled, "path": str(vault),
            "note_count": note_count(vault) if ok else 0,
            **({} if ok else {"error": "folder not found" if not vault.is_dir() else "refused"})}


# ---- viewer helpers (desktop page + phone, read-only) ----------------------
def open_uri(vault: Path, rel: str) -> str:
    """``obsidian://open?vault=<name>&file=<path>`` — opens the note in the Obsidian app."""
    from urllib.parse import quote
    rel = rel[:-3] if rel.lower().endswith(".md") else rel
    return f"obsidian://open?vault={quote(vault.resolve().name)}&file={quote(rel)}"


def tree(vault: Path) -> dict[str, Any]:
    """Folders and notes as a nested tree (folders first, both sorted)."""
    root: dict[str, Any] = {"name": vault.resolve().name, "path": "", "type": "folder", "children": []}
    index: dict[str, dict] = {"": root}
    for p in iter_notes(vault):
        rel = rel_of(vault, p)
        parts = rel.split("/")
        parent = root
        for i in range(len(parts) - 1):
            key = "/".join(parts[: i + 1])
            if key not in index:
                node = {"name": parts[i], "path": key, "type": "folder", "children": []}
                parent["children"].append(node)
                index[key] = node
            parent = index[key]
        parent["children"].append({"name": p.stem, "path": rel, "type": "note"})

    def order(n: dict) -> None:
        n["children"].sort(key=lambda c: (c["type"] != "folder", c["name"].lower()))
        for c in n["children"]:
            if c["type"] == "folder":
                order(c)
    order(root)
    return root


def _resolve_target(target: str, by_stem: dict[str, str], by_path: dict[str, str]) -> str | None:
    t = target.split("#", 1)[0].strip().lower()
    if not t:
        return None
    if t.endswith(".md"):
        t = t[:-3]
    return by_path.get(t) or by_stem.get(t.rsplit("/", 1)[-1])


def graph(vault: Path, limit: int = 2000) -> dict[str, Any]:
    """Nodes = notes (+ unresolved link targets), edges = wikilinks. Degree included."""
    notes = list(iter_notes(vault))[:limit]
    by_stem: dict[str, str] = {}
    by_path: dict[str, str] = {}
    for p in notes:
        rel = rel_of(vault, p)
        by_stem.setdefault(p.stem.lower(), rel)
        by_path[rel[:-3].lower()] = rel
    nodes: dict[str, dict] = {rel_of(vault, p): {"id": rel_of(vault, p), "title": p.stem, "exists": True, "degree": 0}
                              for p in notes}
    edges: set[tuple[str, str]] = set()
    for p in notes:
        src = rel_of(vault, p)
        try:
            text = _read(p)
        except OSError:
            continue
        for raw in _WIKILINK.findall(text):
            dst = _resolve_target(raw, by_stem, by_path)
            if dst is None:
                name = raw.split("#", 1)[0].strip()
                if not name:
                    continue
                dst = f"?{name}"
                nodes.setdefault(dst, {"id": dst, "title": name, "exists": False, "degree": 0})
            if dst != src and (src, dst) not in edges:
                edges.add((src, dst))
    for s, d in edges:
        nodes[s]["degree"] += 1
        nodes[d]["degree"] += 1
    return {"nodes": list(nodes.values()), "edges": [{"source": s, "target": d} for s, d in sorted(edges)]}
