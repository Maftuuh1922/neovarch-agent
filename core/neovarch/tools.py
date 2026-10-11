"""The agent's tools: shell, files, web fetch, memory notes and skills.

Each tool is an async function ``(args, ctx) -> str``. Dangerous shell commands
go through ``ctx.approve`` first (the CLI asks on the terminal, the gateway sends
an ``approval`` request to the desktop/phone).
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

from neovarch.paths import ForeignPathError, check_path, neovarch_home

MAX_OUTPUT = 20_000
SHELL_DEFAULT_TIMEOUT = 60
SHELL_MAX_TIMEOUT = 600

ApproveFn = Callable[[str, str, str], Awaitable[str]]


@dataclass
class ToolContext:
    cwd: Path
    approve: ApproveFn
    approvals_mode: str = "ask"            # ask | off
    session_allow: set[str] = field(default_factory=set)
    # Live Kantor snapshot (set by the gateway; the terminal CLI has none).
    office: Callable[[], dict] | None = None
    # Set when this session belongs to a Kantor company agent (neovarch.company_runtime.CompanyBinding).
    company: Any = None
    persona: Callable[[], str] | None = None
    # The main agent's Kantor control (CompanyRuntime.main_tool); None outside the gateway.
    kantor: Callable[[dict], str] | None = None


DANGEROUS = [
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+", "deletes files recursively/forcibly"),
    (r"\bsudo\b|\bdoas\b|\bsu\s+-", "runs as another user (root)"),
    (r"\bmkfs(\.\w+)?\b|\bfdisk\b|\bparted\b|\bwipefs\b", "formats or partitions a disk"),
    (r"\bdd\s+.*\bof=", "writes raw data with dd"),
    (r">\s*/dev/(sd|nvme|hd|disk)", "writes to a block device"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "shuts down or restarts the machine"),
    (r"\bchmod\s+(-R\s+)?[0-7]*7[0-7]*\s+/|\bchown\s+-R\b", "changes permissions/ownership broadly"),
    (r"\bgit\s+(push\s+.*(--force|-f)\b|reset\s+--hard|clean\s+-[a-z]*f)", "rewrites or discards git history/work"),
    (r"(curl|wget)[^|]*\|\s*(sh|bash|zsh|python)", "pipes a download into a shell"),
    (r"\bkill(all)?\s+-9\b|\bpkill\b", "force-kills processes"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\b(drop\s+table|drop\s+database|truncate\s+table)\b", "destroys database data"),
]


def danger_reason(command: str) -> str | None:
    if re.search(r"(^|[\s'\"=:])(~|\$HOME|\$\{HOME\}|/home/[^/\s]+|/root)?/\.hermes(/|\s|$|['\"])"
                 r"|(^|[;&|(]\s*|\bxargs\s+)hermes(-acp|-agent)?(\s|$)", command):
        return "touches a Hermes Agent install (Neovarch never does)"
    for pattern, reason in DANGEROUS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n… [{len(text) - limit} characters omitted] …\n" + text[-half:]


def _setting(key: str, default: float, lo: float, hi: float) -> float:
    """A number from Settings (config.yaml), clamped; the default when unset or invalid."""
    try:
        from neovarch import config as cfgmod
        val = float(cfgmod.get_path(cfgmod.load_config(), key, default) or default)
    except Exception:
        return default
    return min(max(val, lo), hi)


def _resolve(ctx: ToolContext, raw: str) -> Path:
    if not raw:
        raise ValueError("path is required")
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = ctx.cwd / p
    p = p.resolve()
    check_path(p)
    return p


# ------------------------------------------------------------------ tools -----

async def tool_shell(args: dict, ctx: ToolContext) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        return "error: command is required"
    default_timeout = _setting("terminal.timeout", SHELL_DEFAULT_TIMEOUT, 1, SHELL_MAX_TIMEOUT)
    timeout = min(float(args.get("timeout") or default_timeout), SHELL_MAX_TIMEOUT)
    reason = danger_reason(command)
    if reason and "hermes" in reason.lower():
        return f"refused: this command {reason}."
    if reason and ctx.approvals_mode != "off" and command not in ctx.session_allow:
        choice = await ctx.approve(command, f"This command {reason}.", "shell")
        if choice in ("deny", "", None):
            return "denied: the user did not approve this command."
        if choice in ("session", "always"):
            ctx.session_allow.add(command)
    workdir = _resolve(ctx, args["workdir"]) if args.get("workdir") else ctx.cwd
    started = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command, cwd=str(workdir), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **_account_env(), "NEOVARCH_CORE": "1"}, start_new_session=True,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, 9)  # the whole command (start_new_session), not only the shell
        except (ProcessLookupError, PermissionError, AttributeError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except (asyncio.TimeoutError, Exception):
            pass
        return f"error: timed out after {timeout:.0f}s"
    text = out.decode("utf-8", "replace")
    return _clip(f"exit code {proc.returncode} ({time.monotonic() - started:.1f}s)\n{text}")


async def tool_read_file(args: dict, ctx: ToolContext) -> str:
    p = _resolve(ctx, str(args.get("path") or ""))
    if p.is_dir():
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return _clip("\n".join(entries) or "(empty directory)")
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(int(args.get("offset") or 1), 1)
    limit = int(args.get("limit") or 2000)
    chunk = lines[start - 1:start - 1 + limit]
    numbered = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(chunk, start))
    more = f"\n… {len(lines) - (start - 1 + len(chunk))} more lines" if start - 1 + len(chunk) < len(lines) else ""
    return _clip(numbered + more, int(_setting("file_read_max_chars", MAX_OUTPUT, 1000, 1_000_000)))


async def tool_write_file(args: dict, ctx: ToolContext) -> str:
    p = _resolve(ctx, str(args.get("path") or ""))
    content = str(args.get("content") or "")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {p}"


async def tool_edit_file(args: dict, ctx: ToolContext) -> str:
    p = _resolve(ctx, str(args.get("path") or ""))
    old = str(args.get("old_text") or "")
    new = str(args.get("new_text") or "")
    if not old:
        return "error: old_text is required"
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return "error: old_text was not found in the file"
    if count > 1 and not args.get("replace_all"):
        return f"error: old_text occurs {count} times; add more context or set replace_all"
    p.write_text(text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1), encoding="utf-8")
    return f"edited {p} ({count if args.get('replace_all') else 1} replacement(s))"


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


async def tool_web_fetch(args: dict, ctx: ToolContext) -> str:
    url = str(args.get("url") or "")
    if not re.match(r"^https?://", url):
        return "error: url must start with http:// or https://"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as s:
        async with s.get(url, headers={"User-Agent": "NeovarchAgent/0.1 (+https://github.com/Maftuuh1922/neovrach_Agent)"}) as r:
            body = await r.text(errors="replace")
            ctype = r.headers.get("Content-Type", "")
            text = _html_to_text(body) if "html" in ctype else body
            return _clip(f"HTTP {r.status} {ctype}\n{text}")


async def tool_memory(args: dict, ctx: ToolContext) -> str:
    """Save or read long-term memory notes (markdown files in ~/.neovarch/memory)."""
    mem = neovarch_home() / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    action = str(args.get("action") or "list")
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(args.get("name") or "notes")).strip("-") or "notes"
    target = mem / (name if name.endswith(".md") else name + ".md")
    if action == "list":
        return "\n".join(sorted(p.name for p in mem.glob("*.md"))) or "(no memory notes yet)"
    if action == "read":
        return target.read_text(encoding="utf-8") if target.exists() else f"(no note named {target.name})"
    if action == "append":
        with target.open("a", encoding="utf-8") as fh:
            fh.write(str(args.get("content") or "").rstrip() + "\n")
        return f"appended to memory/{target.name}"
    if action == "write":
        target.write_text(str(args.get("content") or ""), encoding="utf-8")
        return f"wrote memory/{target.name}"
    return "error: action must be list, read, append or write"


async def tool_skill(args: dict, ctx: ToolContext) -> str:
    """List or read skills (folders with SKILL.md in ~/.neovarch/skills)."""
    root = neovarch_home() / "skills"
    root.mkdir(parents=True, exist_ok=True)
    name = str(args.get("name") or "")
    if not name:
        return "\n".join(f"{s['name']}: {s['description']}" for s in list_skills()) or "(no skills installed)"
    path = root / re.sub(r"[^a-zA-Z0-9_.-]+", "-", name) / "SKILL.md"
    return path.read_text(encoding="utf-8") if path.exists() else f"(no skill named {name})"


def _vault():
    from neovarch import obsidian
    return obsidian, obsidian.require_vault()


async def tool_obsidian_search(args: dict, ctx: ToolContext) -> str:
    obs, vault = _vault()
    hits = obs.search(vault, str(args.get("query") or ""), int(args.get("limit") or 10))
    if not hits:
        return "(no matching notes)"
    return _clip("\n".join(
        f"- {h['path']}" + (f"  tags: {', '.join('#' + t for t in h['tags'])}" if h["tags"] else "")
        + f"\n  {h['snippet']}" for h in hits))


async def tool_obsidian_read(args: dict, ctx: ToolContext) -> str:
    obs, vault = _vault()
    note = obs.read_note(vault, str(args.get("path") or ""))
    return _clip(f"# {note['path']}\n{note['content']}")


async def tool_obsidian_write(args: dict, ctx: ToolContext) -> str:
    obs, vault = _vault()
    fm = args.get("frontmatter") if isinstance(args.get("frontmatter"), dict) else None
    res = obs.write_note(vault, str(args.get("path") or ""), str(args.get("content") or ""),
                         str(args.get("mode") or "create"), fm)
    # The obsidian:// link lets the user open the note straight in the Obsidian app
    # (the chat renders it as a clickable "Buka di Obsidian" link).
    return (f"{res['mode']}: {res['path']} ({res['bytes']} bytes) in the Obsidian vault\n"
            f"Buka di Obsidian: {obs.open_uri(vault, res['path'])}")


async def tool_obsidian_links(args: dict, ctx: ToolContext) -> str:
    obs, vault = _vault()
    res = obs.links(vault, str(args.get("path") or ""))
    back = "\n".join(f"- {b['path']}" for b in res["backlinks"]) or "(none)"
    out = "\n".join(f"- [[{o}]]" for o in res["outgoing"]) or "(none)"
    return f"{res['path']}\nbacklinks:\n{back}\noutgoing links:\n{out}"


BUILTIN_SKILL_NAME = "neovarch-app"
BUILTIN_SKILL_VERSION = "1"
BUILTIN_SKILL = f"""---
name: {BUILTIN_SKILL_NAME}
description: Peta fitur aplikasi Neovarch (Kantor, Kanban, Obsidian, Skill, Jadwal, Pengaturan, remote HP) dan cara membacanya dengan tool.
builtin: true
version: {BUILTIN_SKILL_VERSION}
---
# Neovarch app

Gunakan skill ini saat pengguna bertanya tentang aplikasi Neovarch itu sendiri.

## Halaman
- **Obrolan / Sesi** - percakapan dengan agen; daftar sesi dengan cari, sematkan, pengelompokan.
- **Kantor** - kantor 3D: tiap sesi aktif/baru dan tiap tugas Kanban tampil sebagai pegawai di meja
  (bekerja / menunggu persetujuan / santai), tugas saat ini, model, umpan aktivitas, taman.
- **Kanban** - papan tugas (todo, ready, running, blocked, done), dipakai bersama Kantor.
- **Catatan / Obsidian** - vault Obsidian pengguna: pohon, catatan, backlink, graf; juga memori jangka panjang.
- **Skill** - folder berisi SKILL.md di ~/.neovarch/skills.
- **Jadwal** - cron job agen. **Pasangkan HP** - QR untuk aplikasi remote di HP.
- **Pengaturan** - model, penyedia, endpoint kustom OpenAI-compatible, tampilan, keamanan (persetujuan), memori.

## Cara membaca keadaan
- Kantor: panggil `office_status` (sekali sudah cukup).
- Obsidian: `obsidian_search`, `obsidian_read`, `obsidian_links`.
- Jangan grep app.asar, folder instalasi, atau site-packages untuk mencari tahu fitur aplikasi.
"""


def ensure_builtin_skills(root: Path | None = None) -> None:
    """Install (or refresh) the built-in skill; a copy the user edited is kept."""
    root = root or (neovarch_home() / "skills")
    target = root / BUILTIN_SKILL_NAME / "SKILL.md"
    try:
        from neovarch import skills_admin
        if not target.exists() and skills_admin.archived(BUILTIN_SKILL_NAME):
            return  # the user archived it
        if target.exists():
            text = target.read_text(encoding="utf-8", errors="replace")
            if "builtin: true" not in text or f"version: {BUILTIN_SKILL_VERSION}" in text:
                return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(BUILTIN_SKILL, encoding="utf-8")
    except OSError:
        pass


def list_skills(include_disabled: bool = False) -> list[dict[str, Any]]:
    """Installed skills; disabled ones (Skills tab toggle) only when asked."""
    root = neovarch_home() / "skills"
    ensure_builtin_skills(root)
    from neovarch import skills_admin
    off = skills_admin.disabled()
    out = []
    if not root.exists():
        return out
    for skill_md in sorted(root.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        desc = ""
        m = re.search(r"(?m)^description:\s*(.+)$", text)
        if m:
            desc = m.group(1).strip()
        else:
            body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith(("---", "#", "name:"))]
            desc = body[0][:160] if body else ""
        enabled = skill_md.parent.name not in off
        if enabled or include_disabled:
            out.append({"name": skill_md.parent.name, "description": desc, "path": str(skill_md), "enabled": enabled})
    return out


async def tool_report_search(args: dict, ctx: ToolContext) -> str:
    import asyncio
    from neovarch import report as rep
    res = await asyncio.to_thread(rep.search_references, str(args.get("query") or ""),
                                  int(args.get("limit") or 8), year_from=args.get("year_from"))
    refs = res["references"]
    rep.remember(refs)
    if not refs:
        return "no references found" + (f" (errors: {res['errors']})" if res["errors"] else "")
    lines = [f"{len(refs)} real references (cite them as [@key]; only these keys are accepted by report_create):"]
    for r in refs:
        authors = ", ".join(r["authors"][:3]) + (" et al." if len(r["authors"]) > 3 else "")
        lines.append(f"- @{r['key']}: {authors} ({r['year']}). {r['title']}. {r.get('venue') or ''}"
                     f"{' doi:' + r['doi'] if r.get('doi') else ''}"
                     + (f"\n  abstract: {r['abstract'][:300]}" if r.get("abstract") else ""))
    if res["errors"]:
        lines.append(f"(sources that failed: {', '.join(res['errors'])})")
    return "\n".join(lines)


async def tool_report_create(args: dict, ctx: ToolContext) -> str:
    from neovarch import report as rep
    body = str(args.get("body") or "")
    keys = [str(k).lstrip("@") for k in (args.get("references") or [])]
    keys = sorted(set(keys) | rep.cited_keys(body))
    refs, missing = rep.recall(keys)
    if missing:
        return ("error: these keys were never returned by report_search, so they are not real references: "
                + ", ".join(missing) + ". Search again and cite only returned keys.")
    try:
        res = rep.create_report(str(args.get("title") or ""), body, refs, author=str(args.get("author") or ""),
                                institution=str(args.get("institution") or ""), style=str(args.get("style") or "apa"))
    except rep.ReportError as exc:
        return f"error: {exc}"
    return (f"report written: {res['markdown']} with {res['references']} references ({res['bibtex']}). "
            f"Cited: {', '.join(res['cited']) or 'none'}. Next: report_export to make .docx/.pdf.")


async def tool_report_export(args: dict, ctx: ToolContext) -> str:
    import asyncio
    from neovarch import report as rep
    vault = None
    if args.get("save_to_vault"):
        try:
            from neovarch import obsidian
            vault = str(obsidian.require_vault())
        except Exception as exc:
            return f"error: {exc}"
    try:
        res = await asyncio.to_thread(rep.export_report, str(args.get("path") or ""),
                                      list(args.get("formats") or ["docx", "pdf"]),
                                      style=args.get("style"), vault=vault)
    except rep.ReportError as exc:
        return f"error: {exc}"
    lines = [f"{k}: {v}" for k, v in res["files"].items()]
    if res.get("obsidian_uri"):
        lines.append(f"Buka di Obsidian: {res['obsidian_uri']}")
    lines += [f"warning: {w}" for w in res["warnings"]]
    return "exported\n" + "\n".join(lines)


def office_summary(snap: dict) -> str:
    """Compact text view of a Kantor snapshot for the model."""
    lines = []
    counts = snap.get("counts") or {}
    lines.append(f"Kantor: {counts.get('total', 0)} agen — {counts.get('working', 0)} bekerja, "
                 f"{counts.get('waiting-approval', 0)} menunggu persetujuan, {counts.get('idle', 0)} santai.")
    model = snap.get("model") or {}
    if model.get("model"):
        lines.append(f"Model aktif: {model.get('model')} (penyedia {model.get('provider') or '-'})")
    for a in (snap.get("agents") or [])[:20]:
        if not isinstance(a, dict):
            continue
        task = a.get("current_task") or a.get("task") or a.get("title") or ""
        lines.append(f"- {a.get('name') or a.get('id')}: {a.get('status')}"
                     + (f" — {str(task)[:120]}" if task else "")
                     + (f" [{a.get('model')}]" if a.get("model") else ""))
    kanban = snap.get("kanban") or {}
    if kanban:
        lines.append("Kanban: " + ", ".join(f"{k} {v}" for k, v in kanban.items()))
    feed = snap.get("feed") or []
    if feed:
        lines.append("Aktivitas terakhir:")
        for item in feed[:8]:
            if isinstance(item, dict):
                lines.append(f"  · {item.get('text') or item.get('kind')}")
    company = snap.get("company")
    if isinstance(company, dict):
        tc = company.get("ticket_counts") or {}
        lines.append(f"Perusahaan: {company.get('name')} — misi: {company.get('mission') or '-'}; "
                     f"jalan otomatis {'aktif' if company.get('autorun') else 'mati'}; "
                     f"{company.get('pending_approvals', 0)} persetujuan menunggu.")
        lines.append("Tiket: " + ", ".join(f"{k} {v}" for k, v in tc.items() if v))
        for a in (company.get("agents") or [])[:20]:
            lines.append(f"  · {a.get('name')} ({a.get('title') or '-'}): {a.get('status')}"
                         + (f" — {a.get('ticket')}" if a.get("ticket") else ""))
    vault = snap.get("vault") or {}
    if isinstance(vault, dict) and vault.get("configured") is not None:
        lines.append(f"Vault Obsidian: {'terpasang' if vault.get('configured') else 'belum diatur'}")
    return "\n".join(lines)


async def tool_office_status(args: dict, ctx: ToolContext) -> str:
    if ctx.office is None:
        return "Kantor hanya tersedia saat core berjalan sebagai gateway desktop (neovarch serve)."
    return office_summary(ctx.office())


async def tool_kantor(args: dict, ctx: ToolContext) -> str:
    if getattr(ctx, "company", None) is not None:
        return "refused: hanya agen utama Neovarch yang mengatur Kantor"
    if ctx.kantor is None:
        return "Kantor hanya tersedia saat core berjalan sebagai gateway desktop (neovarch serve)."
    return ctx.kantor(args or {})


KANTOR_ACTIONS = ["overview", "create_org", "create_agency", "rename_unit", "delete_unit", "hire", "fire", "move",
                  "set_employee", "assign_task"]

TOOLS: dict[str, tuple[Callable[[dict, ToolContext], Awaitable[str]], dict]] = {
    "kantor": (tool_kantor, {
        "description": "Run the user's Kantor (office) ONLY when the user asks for it. Structure: Organisasi → Agency "
                       "→ Orang (pegawai), nested without limit. action: overview (show the org) | create_org "
                       "(name, parent?) | create_agency (name, parent = org/agency name) | rename_unit (unit, new_name) "
                       "| delete_unit (unit) | hire (name, title, unit?, manager?, job_description?, persona?, skills?, "
                       "tools?, model?, provider?) | fire (name: removes the employee) | move (name, unit?, manager?) | "
                       "set_employee (name, title?, persona?, skills?, tools?, model?, provider?, new_name?) | "
                       "assign_task (employee, title, description?, start_now?). Kantor starts empty; never invent "
                       "employees the user did not ask for. You stay the one answering the user.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": KANTOR_ACTIONS},
            "name": {"type": "string"}, "new_name": {"type": "string"}, "title": {"type": "string"},
            "unit": {"type": "string", "description": "organisasi/agency name or id"},
            "parent": {"type": "string", "description": "parent organisasi/agency name or id"},
            "manager": {"type": "string", "description": "employee this person reports to"},
            "employee": {"type": "string"}, "description": {"type": "string"},
            "job_description": {"type": "string"}, "persona": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "tools": {"type": "array", "items": {"type": "string"},
                      "description": "built-in tools this employee may use (empty = all)"},
            "model": {"type": "string"}, "provider": {"type": "string"},
            "start_now": {"type": "boolean"}}, "required": ["action"]}}),

    "office_status": (tool_office_status, {
        "description": "Read the live Neovarch Kantor (office) state: agents, their status and current task, "
                       "Kanban counts, recent activity and the active model. Read-only; use it to answer questions "
                       "about the Kantor instead of searching files.",
        "parameters": {"type": "object", "properties": {}}}),
    "shell": (tool_shell, {
        "description": "Run a shell command on the user's computer and return its output. Dangerous commands ask the user first.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "workdir": {"type": "string"},
            "timeout": {"type": "number", "description": "seconds, default 120"}}, "required": ["command"]}}),
    "read_file": (tool_read_file, {
        "description": "Read a text file (with line numbers) or list a directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}),
    "write_file": (tool_write_file, {
        "description": "Create or overwrite a text file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}),
    "edit_file": (tool_edit_file, {
        "description": "Replace exact text in a file (old_text must be unique unless replace_all).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"}}, "required": ["path", "old_text", "new_text"]}}),
    "web_fetch": (tool_web_fetch, {
        "description": "Fetch a web page or API URL and return its text.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}),
    "memory": (tool_memory, {
        "description": "Long-term memory notes. action: list | read | append | write; name: note name.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "read", "append", "write"]},
            "name": {"type": "string"}, "content": {"type": "string"}}, "required": ["action"]}}),
    "skill": (tool_skill, {
        "description": "List installed skills (no name) or read one skill's instructions (name).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}),
    "obsidian_search": (tool_obsidian_search, {
        "description": "Search the user's Obsidian vault (memory) by words in the text, note filename and tags "
                       "(#tag). Only works when an Obsidian vault is configured.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}),
    "obsidian_read": (tool_obsidian_read, {
        "description": "Read one note from the Obsidian vault (path relative to the vault, or a note name).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}),
    "obsidian_write": (tool_obsidian_write, {
        "description": "Create or append to a note in the Obsidian vault. mode: create | append | overwrite. "
                       "Write markdown with [[wikilinks]] and #tags; existing frontmatter is kept. "
                       "Paths are relative to the vault and can never leave it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
            "mode": {"type": "string", "enum": ["create", "append", "overwrite"]},
            "frontmatter": {"type": "object", "description": "optional YAML frontmatter keys to set"}},
            "required": ["path", "content"]}}),
    "report_search": (tool_report_search, {
        "description": "Search real scholarly references (OpenAlex, Crossref, Semantic Scholar) for a report or thesis. "
                       "Returns citation keys; cite them in markdown as [@key]. Never cite anything else.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "description": "per source, default 8"},
            "year_from": {"type": "integer"}}, "required": ["query"]}}),
    "report_create": (tool_report_create, {
        "description": "Write a report/thesis as Pandoc Markdown + references.bib under ~/.neovarch/reports/<slug>/. "
                       "body is markdown with chapters (# BAB I Pendahuluan ...) citing [@key] from report_search. "
                       "Unknown keys are rejected.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "body": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}, "description": "extra keys to list even if not cited"},
            "author": {"type": "string"}, "institution": {"type": "string"},
            "style": {"type": "string", "enum": ["apa", "ieee"]}}, "required": ["title", "body"]}}),
    "report_export": (tool_report_export, {
        "description": "Export a report.md to .docx (campus format: Times New Roman 12, 1.5 spacing, margins 4-3-3-3, "
                       "table of contents, numbered chapters) and .pdf with Pandoc + citeproc. Optionally save a copy in the Obsidian vault.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "path to report.md"},
            "formats": {"type": "array", "items": {"type": "string", "enum": ["docx", "pdf", "md"]}},
            "style": {"type": "string", "enum": ["apa", "ieee"]},
            "save_to_vault": {"type": "boolean"}}, "required": ["path"]}}),
    "obsidian_links": (tool_obsidian_links, {
        "description": "List the backlinks (notes that [[link]] to this one) and outgoing links of a vault note.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}),
}


def _allowed_builtin(ctx: "ToolContext | None") -> set[str]:
    names = set(TOOLS)
    company = getattr(ctx, "company", None) if ctx is not None else None
    if company is None:
        if ctx is None or getattr(ctx, "kantor", None) is None:
            names.discard("kantor")
        return names
    names.discard("kantor")  # employees never run the Kantor; the main agent does
    allowed = company.allowed_tools() if hasattr(company, "allowed_tools") else None
    if allowed:
        names &= set(allowed) | {"office_status"}
    return names


def tool_schemas(ctx: "ToolContext | None" = None) -> list[dict[str, Any]]:
    allowed = _allowed_builtin(ctx)
    out = [{"type": "function", "function": {"name": n, **spec}} for n, (_, spec) in TOOLS.items() if n in allowed]
    if ctx is not None and getattr(ctx, "company", None) is not None:
        out += ctx.company.tool_schemas()
    return out


def _vault_error():
    from neovarch.obsidian import VaultError
    return VaultError


async def run_tool(name: str, args: dict, ctx: ToolContext) -> str:
    entry = TOOLS.get(name)
    company = getattr(ctx, "company", None)
    if not entry and company is not None and name in company.tool_names():
        return await company.run_tool(name, args)
    if not entry:
        return f"error: unknown tool {name}"
    if name not in _allowed_builtin(ctx):
        return f"refused: alat {name} tidak diizinkan untuk agen ini"
    try:
        return await entry[0](args, ctx)
    except ForeignPathError as exc:
        return f"refused: {exc}"
    except _vault_error() as exc:
        return f"error: {exc}"
    except FileNotFoundError as exc:
        return f"error: not found: {exc.filename or exc}"
    except Exception as exc:  # tools report errors to the model instead of crashing the turn
        return f"error: {type(exc).__name__}: {exc}"


def _account_env() -> dict[str, str]:
    try:
        from neovarch import account
        return account.shell_env()
    except Exception:  # a broken .env must never stop a command
        return {}
