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
READ_LINE_CHARS = 2000
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
    # The chat this context serves, and the files send_file staged during the current
    # turn (upload metadata, origin "agent"); the agent stores them on its reply.
    session_id: str = ""
    uploads: Any = None
    outbox: list = field(default_factory=list)
    # The gateway this context serves (orchestrator tools); None in the terminal CLI.
    gateway: Any = None
    # Receives the plan_update checklist (the gateway publishes it to the chat).
    set_plan: Callable[[list[dict]], None] | None = None
    # One model call for read-only sub-agents (``task``): async (messages, tools) -> Completion.
    # Set by the agent for the duration of a turn; None elsewhere (CLI tools, employees).
    llm: Callable[[list[dict], list[dict]], Any] | None = None


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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


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
    from neovarch import tools_patch
    heredoc = tools_patch.from_shell(command)
    if heredoc is not None:  # Codex-trained models type `apply_patch <<'EOF' ... EOF` into the shell
        return await tool_apply_patch({"patch": heredoc}, ctx)
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
    if not _inside(workdir, ctx.cwd) and ("@outside:" + str(workdir)) not in ctx.session_allow:
        # Commands outside the chat's workspace always ask, even with approvals off.
        choice = await ctx.approve(command, f"Perintah ini berjalan di luar folder kerja ({workdir}).", "shell")
        if choice in ("deny", "", None):
            return "denied: the user did not approve running outside the workspace."
        if choice in ("session", "always"):
            ctx.session_allow.add("@outside:" + str(workdir))
    started = time.monotonic()
    env = {**os.environ, **_account_env(), "NEOVARCH_CORE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if args.get("background"):
        from neovarch import tools_code
        return await tools_code.start_job(command, workdir, env)
    spawn = asyncio.ensure_future(asyncio.create_subprocess_shell(
        command, cwd=str(workdir), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL, env=env, start_new_session=os.name != "nt",
    ))
    try:
        proc = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        # Stop landed while the command was still being started: the process already runs (and
        # may have started children), so finish getting its handle and kill the whole group.
        # Without this, asyncio only SIGKILLs the shell and a `sleep 120 &` child lives on.
        try:
            proc = await asyncio.wait_for(asyncio.shield(spawn), 5)
        except BaseException:
            proc = None
        if proc is not None:
            await asyncio.shield(kill_process_tree(proc))
        raise
    from neovarch.tools_code import OutputBuffer
    buf = OutputBuffer()

    async def collect() -> None:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buf.add(chunk)
        await proc.wait()
    try:
        await asyncio.wait_for(collect(), timeout=timeout)
    except asyncio.TimeoutError:
        await kill_process_tree(proc)
        partial = decode_output(buf.bytes())
        return _clip(f"error: timed out after {timeout:.0f}s; the command was stopped. For servers, watchers or long "
                     f"builds/tests use background=true and check them with shell_job.\n"
                     + (f"Output before the timeout:\n{partial}" if partial.strip() else "(no output before the timeout)"))
    except asyncio.CancelledError:
        # Stop: the command and everything it started go away now, not when it finishes.
        await asyncio.shield(kill_process_tree(proc))
        raise
    text = decode_output(buf.bytes())
    return _clip(f"exit code {proc.returncode} ({time.monotonic() - started:.1f}s)\n{text}")


async def kill_process_tree(proc) -> None:
    """Kill a command started with start_new_session=True together with every process
    it spawned (its process group); on Windows, taskkill /T kills the tree."""
    if os.name != "nt" and proc.returncode is not None:
        # The shell itself is already gone (asyncio's transport can SIGKILL just the leader when
        # the cancelled communicate() is torn down first), but a background child it started
        # (``sleep 120 &``) still sits in its process group: kill the group anyway. The pgid
        # cannot be reused while any member is alive, so this never hits a stranger.
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if proc.returncode is None:
        try:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/F", "/T", "/PID", str(proc.pid),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(killer.wait(), 5)
            else:
                os.killpg(proc.pid, 9)  # the whole command (start_new_session), not only the shell
        except (ProcessLookupError, PermissionError, AttributeError, OSError, asyncio.TimeoutError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except (asyncio.TimeoutError, Exception):
        pass


def decode_output(raw: bytes) -> str:
    """Command output as text: UTF-8 first; on Windows cmd.exe tools often print in
    the console/ANSI code page (cp437/cp850/cp1252), so fall back to that instead of
    turning every accented letter into U+FFFD."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if os.name == "nt":
        import locale
        for enc in ("oem", locale.getpreferredencoding(False)):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return raw.decode("utf-8", "replace")


async def tool_read_file(args: dict, ctx: ToolContext) -> str:
    p = _resolve(ctx, str(args.get("path") or ""))
    if p.is_dir():
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return _clip("\n".join(entries) or "(empty directory)")
    raw = p.read_bytes()
    if b"\0" in raw[:8192]:
        return f"{p}: binary file ({len(raw)} bytes); not shown as text"
    text = decode_output(raw)
    lines = text.splitlines()
    start = max(int(args.get("offset") or 1), 1)
    limit = int(args.get("limit") or 2000)
    chunk = lines[start - 1:start - 1 + limit]
    if start > 1 and not chunk:
        return f"(offset {start} is past the end: {p} has {len(lines)} lines)"

    def cut(line: str) -> str:  # minified / generated lines would eat the whole budget
        return line if len(line) <= READ_LINE_CHARS else line[:READ_LINE_CHARS] + f" … [+{len(line) - READ_LINE_CHARS} chars]"
    numbered = "\n".join(f"{i:>6}\t{cut(line)}" for i, line in enumerate(chunk, start))
    more = f"\n… {len(lines) - (start - 1 + len(chunk))} more lines" if start - 1 + len(chunk) < len(lines) else ""
    return _clip(numbered + more, int(_setting("file_read_max_chars", MAX_OUTPUT, 1000, 1_000_000)))


async def tool_write_file(args: dict, ctx: ToolContext) -> str:
    p = _resolve(ctx, str(args.get("path") or ""))
    content = str(args.get("content") or "")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {p}"


async def tool_edit_file(args: dict, ctx: ToolContext) -> str:
    """Exact replacement first, then a unique whitespace/indent-tolerant match; ``edits`` applies
    several replacements to one file at once (all or nothing). See neovarch.tools_code."""
    from neovarch import tools_code
    p = _resolve(ctx, str(args.get("path") or ""))
    edits = args.get("edits")
    if isinstance(edits, dict):
        edits = [edits]
    if not isinstance(edits, list) or not edits:
        edits = [{"old_text": args.get("old_text") if args.get("old_text") is not None else args.get("old_string"),
                  "new_text": args.get("new_text") if args.get("new_text") is not None else args.get("new_string"),
                  "replace_all": args.get("replace_all")}]
    if not p.exists():
        return f"error: not found: {p} (create it with write_file)"
    try:
        text = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return f"error: {p} is not UTF-8 text; edit it with shell or rewrite it with write_file"
    try:
        new_text, count, notes, (pos, new_len) = tools_code.edit_text(text, edits)
    except tools_code.EditError as exc:
        return f"error: {exc}"
    p.write_bytes(new_text.encode("utf-8"))
    how = ("; " + "; ".join(notes)) if notes else ""
    view = tools_code.snippet(new_text, pos, new_len)
    return f"edited {p} ({count} replacement(s){how})" + (f"\n{view}" if view else "")


async def tool_grep(args: dict, ctx: ToolContext) -> str:
    from neovarch import tools_code
    return _clip(await tools_code.grep(args, ctx.cwd, lambda raw: _resolve(ctx, raw)))


async def tool_glob(args: dict, ctx: ToolContext) -> str:
    from neovarch import tools_code
    return _clip(await tools_code.glob_files(args, ctx.cwd, lambda raw: _resolve(ctx, raw)))


async def tool_shell_job(args: dict, ctx: ToolContext) -> str:
    from neovarch import tools_code
    return _clip(await tools_code.job_tool(args))


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def _cfg_get():
    """A ``(dotted key, default) -> value`` reader over config.yaml (empty dict when it can't load)."""
    try:
        from neovarch import config as cfgmod
        cfg = cfgmod.load_config()
        return lambda k, d=None: cfgmod.get_path(cfg, k, d)
    except Exception:
        return lambda k, d=None: d


# Tools that only read (files, web, notes): Tempest runs several of them from one model message at
# the same time and never moves their output to a file (they clip themselves in context).
READ_ONLY_TOOLS = frozenset({"read_file", "grep", "glob", "web_fetch", "web_search", "session_search", "obsidian_search",
                             "obsidian_read", "obsidian_links", "report_search", "office_status", "repo_map",
                             "task"})


async def tool_web_fetch(args: dict, ctx: ToolContext) -> str:
    from neovarch import web
    url = str(args.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return "error: url must start with http:// or https://"
    render = str(args.get("render") or "auto").lower()
    if render not in ("auto", "always", "never"):
        render = "auto"
    page = await web.fetch(url, session=getattr(ctx, "session_id", "") or "", render=render, cfg_get=_cfg_get())
    if page.get("error") and not page.get("text"):
        return f"error: {page['error']} ({url})"
    return web.format_page(page, str(args.get("query") or ""), web.FETCH_CHARS)


async def tool_web_search(args: dict, ctx: ToolContext) -> str:
    """Search the web and (by default) read the top results in the same call."""
    from neovarch import web
    query = str(args.get("query") or "").strip()
    if not query:
        return "error: query is required"
    try:
        n = max(1, min(int(args.get("n") or 6), 10))
    except (TypeError, ValueError):
        n = 6
    try:
        n_fetch = max(0, min(int(args.get("fetch") if args.get("fetch") is not None else 2), 4))
    except (TypeError, ValueError):
        n_fetch = 2
    get = _cfg_get()
    session = getattr(ctx, "session_id", "") or ""
    results, backend = await web.search(query, get, session=session, n=n)
    if not results:
        return (f"tidak ditemukan: pencarian '{query}' tidak memberi hasil ({backend}). Coba kata kunci lain, "
                "atau web_fetch URL yang kamu tahu. Jangan menebak jawabannya.")
    lines = [f"Hasil pencarian '{query}' (sumber: {backend}):"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}" + (f"\n   {r['snippet'][:300]}" if r.get("snippet") else ""))
    if n_fetch:
        pages = await asyncio.gather(*(web.fetch(r["url"], session=session, cfg_get=get) for r in results[:n_fetch]),
                                     return_exceptions=True)
        for r, page in zip(results[:n_fetch], pages):
            if isinstance(page, BaseException) or (page.get("error") and not page.get("text")):
                continue
            lines.append("\n--- Isi halaman (dipotong di bagian yang cocok dengan kueri) ---\n"
                         + web.format_page(page, query, web.SEARCH_PAGE_CHARS))
    lines.append("\nJawab fakta hanya dari teks di atas dan sebut URL-nya; kalau tidak ada, bilang tidak ditemukan.")
    return "\n".join(lines)


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
    if action in ("append", "write"):  # versioned, so /undo can restore the previous note
        from neovarch import selfedit
        selfedit.memory_update(action, target.name, content=str(args.get("content") or ""),
                               session_id=getattr(ctx, "session_id", "") or "")
        return f"{'appended to' if action == 'append' else 'wrote'} memory/{target.name}"
    return "error: action must be list, read, append or write"


async def tool_skill(args: dict, ctx: ToolContext) -> str:
    """List or read skills (folders with SKILL.md in ~/.neovarch/skills)."""
    root = neovarch_home() / "skills"
    root.mkdir(parents=True, exist_ok=True)
    ensure_builtin_skills(root)
    name = str(args.get("name") or "")
    if not name:
        return "\n".join(f"{s['name']}: {s['description']}" for s in list_skills()) or "(no skills installed)"
    path = root / re.sub(r"[^a-zA-Z0-9_.-]+", "-", name) / "SKILL.md"
    if not path.exists():
        return f"(no skill named {name})"
    # Skills such as ppt-master need the host to tell them their absolute folder.
    return f"SKILL_DIR: {path.parent}\n\n" + path.read_text(encoding="utf-8")


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


MERMAID_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body{{margin:0;padding:16px;font-family:system-ui,sans-serif;background:#fff;color:#111}}
pre.mermaid{{white-space:pre}} .src{{margin-top:24px;color:#666;font-size:12px}}</style></head>
<body><pre class="mermaid">{code}</pre>
<details class="src"><summary>Sumber Mermaid</summary><pre>{code}</pre></details>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({{startOnLoad: true, securityLevel: "strict"}});
</script></body></html>
"""

SVG_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>body{{margin:0;padding:12px;background:#fff}} svg{{max-width:100%;height:auto}}</style>
</head><body>{svg}</body></html>
"""


def diagrams_dir() -> Path:
    d = neovarch_home() / "diagrams"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_diagram(name: str, fmt: str, content: str) -> list[Path]:
    """Write a diagram as files any browser opens (desktop and the phone's download).

    svg -> .svg + an .html wrapper; html -> .html; mermaid -> .mmd source + an .html
    page that renders it. The first path is the one to open."""
    fmt = (fmt or "").lower().strip()
    if fmt not in ("svg", "html", "mermaid"):
        raise ValueError("format must be svg, html or mermaid")
    content = str(content or "")
    if not content.strip():
        raise ValueError("content is empty")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name or "diagram")).strip("-")[:60] or "diagram"
    base = diagrams_dir() / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    title = html.escape(str(name or slug))
    if fmt == "html":
        out = [base.with_suffix(".html")]
        out[0].write_text(content, encoding="utf-8")
    elif fmt == "svg":
        if "<svg" not in content:
            raise ValueError("svg content must contain an <svg> element")
        page, svg = base.with_suffix(".html"), base.with_suffix(".svg")
        svg.write_text(content, encoding="utf-8")
        page.write_text(SVG_HTML.format(title=title, svg=content), encoding="utf-8")
        out = [page, svg]
    else:
        page, src = base.with_suffix(".html"), base.with_suffix(".mmd")
        src.write_text(content, encoding="utf-8")
        page.write_text(MERMAID_HTML.format(title=title, code=html.escape(content)), encoding="utf-8")
        out = [page, src]
    return out


def _open_on_desktop(path: Path) -> bool:
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


async def tool_visual_check(args: dict, ctx: ToolContext) -> str:
    from neovarch.visuals import check_visual, format_report
    return format_report(check_visual(str(args.get("code") or "")))


async def tool_diagram_save(args: dict, ctx: ToolContext) -> str:
    paths = save_diagram(str(args.get("name") or "diagram"), str(args.get("format") or ""),
                         str(args.get("content") or ""))
    opened = _open_on_desktop(paths[0]) if args.get("open") else False
    lines = [f"saved: {p}" for p in paths]
    lines.append(("Dibuka di PC. " if opened else "")
                 + f"Akhiri jawaban dengan jalur ini supaya desktop bisa membukanya dan HP bisa mengunduhnya: {paths[0]}")
    return "\n".join(lines)


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


PPT_SKILL_NAME = "ppt"
PPT_SKILL_VERSION = "1"
PPT_SKILL = f"""---
name: {PPT_SKILL_NAME}
description: Buat presentasi PowerPoint (.pptx) yang bisa diedit dengan PPT Master / Make editable PowerPoint (.pptx) decks with PPT Master.
builtin: true
version: {PPT_SKILL_VERSION}
---
# PPT / PowerPoint

Pakai saat pengguna minta PPT, slide, presentasi, atau deck (misalnya "buatin PPT dari ...").
Use when the user asks for a PPT, slides, a presentation or a deck. Permintaan dari HP juga dijalankan di PC ini.

1. Panggil `ppt_setup` (sekali; aman diulang). Hasilnya memberi `SKILL_DIR`, `PYTHON` dan folder kerja.
   Jika Python 3.10+ tidak ada, sampaikan pesan errornya apa adanya ke pengguna dan berhenti.
   Sumber PDF butuh `ppt_setup` dengan `pdf: true` (PyMuPDF, lisensi AGPL-3.0); tanyakan dulu ke pengguna.
2. Baca skill `ppt-master` (`skill` dengan name `ppt-master`) lalu ikuti alurnya. Ganti setiap `python3` di
   perintahnya dengan `PYTHON` dari langkah 1, dan `${{SKILL_DIR}}` dengan jalur absolutnya.
   Buat proyek dengan `--dir` ke folder kerja dari langkah 1. Untuk permintaan biasa dari obrolan/HP pakai
   alur Quick (`project_manager.py init <nama> --quick-generate --dir <folder kerja>`), kecuali pengguna minta
   alur lengkap.
3. Ekspor dengan `ppt_export` (`project_path`, `quick`), bukan dengan menebak perintah.
4. Akhiri dengan jalur absolut file .pptx supaya desktop bisa membukanya dan HP bisa mengunduhnya.

PPT Master: https://github.com/hugohe3/ppt-master (MIT, Copyright (c) 2025-2026 Hugo He).
"""

SELF_SKILL_NAME = "neovarch-diri"
SELF_SKILL_VERSION = "1"
SELF_SKILL = f"""---
name: {SELF_SKILL_NAME}
description: Cara agen utama memperbaiki dan meningkatkan dirinya sendiri (skill, memori, pengaturan, /perbaiki, /undo) dan mengatur seluruh aplikasi / How the main agent improves and repairs itself and runs the install.
builtin: true
version: {SELF_SKILL_VERSION}
---
# Memperbaiki & meningkatkan diri

Pakai saat pengguna minta "perbaiki dirimu", "ingat cara ini", "ubah pengaturanmu", "kenapa kamu error",
atau saat kamu menemukan cara kerja yang layak disimpan. Permintaan dari HP sama saja: semuanya jalan di PC ini.

## Simpan pelajaran di tempat yang benar
- **Skill** (`skill_manage`): prosedur, perintah yang terbukti jalan, jebakan, preferensi pengguna untuk jenis tugas
  tertentu. Satu skill per jenis pekerjaan; perbarui skill lama daripada membuat duplikat.
  Format SKILL.md: frontmatter `name`, `description` (satu kalimat: kapan dipakai), lalu langkah bernomor,
  bagian "Jebakan" dan "Verifikasi".
- **Memori** (`memory_update`): hanya fakta yang berlaku di setiap sesi (siapa pengguna, lingkungan PC, konvensi
  tetap). Tulis sebagai fakta, bukan perintah. Ganti/rangkum catatan basi, jangan menumpuk.
- Jangan simpan rahasia, token, atau hal yang basi dalam seminggu.

## Kapan menyimpan
- Setelah tugas sulit atau berulang (banyak langkah, banyak percobaan): tawarkan menyimpannya sebagai skill.
- Skill yang kamu pakai ternyata salah/kurang langkah: perbaiki dengan `skill_manage` action=patch sebelum selesai.
- Pengguna mengoreksimu: catat koreksinya di skill terkait (atau memori kalau berlaku umum).

## Mengubah pengaturanmu
- `settings_update` (model bawaan, instruksi tambahan, persona, alat yang dimatikan, tingkat penalaran, naik ke model
  lebih kuat saat buntu). Setiap perubahan tercatat; sebutkan nilai lama → baru ke pengguna.
- Setelah berubah, `core_reload` action=soft supaya langsung berlaku tanpa memutus obrolan.

## Memperbaiki diri (/perbaiki)
1. `self_diagnose` action=diagnose — baca laporan (log core & desktop, alat yang gagal, pengaturan; rahasia disamarkan).
2. Perbaikan pengaturan/skill diterapkan otomatis dan bisa dibatalkan dengan /undo.
3. Masalah di kode aplikasi: hanya kalau instalasi dari git checkout. Buat diff sekecil mungkin →
   `self_diagnose` action=prepare_patch (branch lokal baru + tes) → tunjukkan ringkasan & hasil tes →
   action=apply_patch (pengguna menekan Setujui) → `core_reload` action=restart.
4. Laporkan dengan Temuan → Bukti → Batasan → Langkah berikutnya.

## Mengatur aplikasi (`manage`)
Kantor (rekrut/beri tugas/jeda/lanjutkan), pengaturan, model, skill, memori, jadwal, perangkat, perbaikan diri.
Pekerjaan panjang untuk pegawai: tulis keputusan dan batasan di deskripsi tugas, karena pegawai tidak melihat obrolan.

## Pulihkan
- "/undo" atau "Pulihkan versi sebelumnya" membatalkan perubahan terakhir (skill, memori, pengaturan, persona, patch).
- `self_undo` action=log menampilkan riwayat perubahan.
"""

BUILTINS = [
    (BUILTIN_SKILL_NAME, BUILTIN_SKILL_VERSION, BUILTIN_SKILL),
    (PPT_SKILL_NAME, PPT_SKILL_VERSION, PPT_SKILL),
    (SELF_SKILL_NAME, SELF_SKILL_VERSION, SELF_SKILL),
]


def ensure_builtin_skills(root: Path | None = None) -> None:
    """Install (or refresh) the built-in skills; a copy the user edited is kept."""
    root = root or (neovarch_home() / "skills")
    for name, version, body in BUILTINS:
        target = root / name / "SKILL.md"
        try:
            from neovarch import skills_admin
            if not target.exists() and skills_admin.archived(name):
                continue  # the user archived it
            if target.exists():
                text = target.read_text(encoding="utf-8", errors="replace")
                if "builtin: true" not in text or f"version: {version}" in text:
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        except OSError:
            pass
    _install_pack(root)


_PACK_DONE: set[str] = set()


def _install_pack(root: Path) -> None:
    """The default skill pack (neovarch/skillpack), once per process per skills folder."""
    key = str(root)
    if key in _PACK_DONE:
        return
    _PACK_DONE.add(key)
    try:
        from neovarch import skillpack
        skillpack.install(root)
    except Exception:  # a broken pack must never break the agent
        pass


def list_skills(include_disabled: bool = False) -> list[dict[str, Any]]:
    """Installed skills; disabled ones (Skills tab toggle) only when asked."""
    root = neovarch_home() / "skills"
    ensure_builtin_skills(root)
    from neovarch import skills_admin
    off = skills_admin.disabled()
    from neovarch import skillpack
    pack = skillpack.by_id()
    out = []
    if not root.exists():
        return out
    for skill_md in sorted(root.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        desc = ""
        m = re.search(r"(?m)^description:\s*(.+)$", text)
        if m:
            desc = m.group(1).strip()
            if desc in (">", "|", ">-", "|-"):  # folded YAML block (e.g. ppt-master)
                fold = re.search(r"(?m)^description:\s*[>|]-?\s*\n((?:[ \t]+.*\n?)+)", text)
                desc = " ".join(ln.strip() for ln in fold.group(1).splitlines())[:300] if fold else ""
        else:
            body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith(("---", "#", "name:"))]
            desc = body[0][:160] if body else ""
        enabled = skill_md.parent.name not in off
        item = {"name": skill_md.parent.name, "description": desc, "path": str(skill_md), "enabled": enabled}
        meta = pack.get(skill_md.parent.name)
        if meta and (skill_md.parent / skillpack.MARKER).is_file():
            # Pack skills: a short ID/EN summary keeps the prompt index small for every model.
            item.update(description=meta["summary"], label=meta["label"], category=meta["category"],
                        source=meta["source"], license=meta["license"], builtin=True)
        if enabled or include_disabled:
            out.append(item)
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


async def tool_ppt_setup(args: dict, ctx: ToolContext) -> str:
    import asyncio
    from neovarch import pptmaster as ppt
    try:
        res = await asyncio.to_thread(ppt.setup, pdf=bool(args.get("pdf")), force=bool(args.get("force")))
    except ppt.PptError as exc:
        return f"error: {exc}"
    return (f"PPT Master {res['version']} siap / ready.\n"
            f"SKILL_DIR={res['skill_dir']}\n"
            f"PYTHON={res['python']}   (pakai ini sebagai pengganti python3 / use instead of python3)\n"
            f"WORK_DIR={res['presentations_dir']}   (project_manager.py init <nama> --quick-generate --dir WORK_DIR)\n"
            f"PDF input: {'aktif / on (PyMuPDF, AGPL-3.0)' if res['pdf_input'] else 'mati / off (ppt_setup pdf=true untuk sumber PDF)'}\n"
            "Next: read the skill `ppt-master` and follow it; export with ppt_export.")


async def tool_ppt_export(args: dict, ctx: ToolContext) -> str:
    import asyncio
    from neovarch import pptmaster as ppt
    try:
        res = await asyncio.to_thread(ppt.export, str(args.get("project_path") or ""),
                                      quick=args.get("quick", True) is not False,
                                      notes=args.get("notes", True) is not False,
                                      output=args.get("output") or None)
    except ppt.PptError as exc:
        return f"error: {exc}"
    return "exported\n" + "\n".join(f"pptx: {f}" for f in res["files"])


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
                     f"heartbeat {'aktif' if company.get('autorun') else 'dijeda'}; "
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

async def tool_send_file(args: dict, ctx: ToolContext) -> str:
    """Attach PC files to the agent's reply so they appear in the chat (phone + desktop)."""
    from neovarch import outbox
    from neovarch import uploads as upmod
    raw = args.get("paths")
    if isinstance(raw, str):
        raw = [raw]
    paths = [str(p) for p in (raw or []) if str(p or "").strip()]
    if args.get("path"):
        paths.insert(0, str(args["path"]))
    if not paths:
        return "error: berikan `paths` (daftar path berkas di PC ini)"
    store = ctx.uploads or upmod.UploadStore()
    lines = []
    for raw_path in paths:
        if len(ctx.outbox) >= outbox.MAX_FILES_PER_TURN:
            lines.append(f"skipped {raw_path}: maks {outbox.MAX_FILES_PER_TURN} berkas per balasan")
            continue
        src = str(outbox.resolve(raw_path, ctx.cwd)) if raw_path else raw_path
        if any(m.get("source_path") == src for m in ctx.outbox):
            lines.append(f"already sent: {src}")
            continue
        try:
            meta = outbox.stage(store, ctx.session_id, raw_path, ctx.cwd)
        except (outbox.SendError, OSError) as exc:
            lines.append(f"error {raw_path}: {exc}")
            continue
        ctx.outbox.append(meta)
        lines.append(f"sent {meta['kind']}: {meta['name']} ({meta['size']} B, id {meta['id']})")
    ok = any(line.startswith("sent") for line in lines)
    tail = ("\nThe file(s) now show in the user's chat (inline image / download card on phone and desktop); "
            "do not repeat the PC path as the way to get them.") if ok else ""
    return "\n".join(lines) + tail


TOOLS: dict[str, tuple[Callable[[dict, ToolContext], Awaitable[str]], dict]] = {
    "send_file": (tool_send_file, {
        "description": "Send files from this PC into the chat so the user gets them where they are chatting "
                       "(phone remote or desktop): images/screenshots show inline, other files (pdf, docx, pptx, "
                       "zip, …) as download cards. Use it whenever the user asks to send/kirim/share/kasih a file, "
                       "screenshot, image, report or deck 'here' / 'ke sini' / 'ke HP', and after you create a file "
                       "the user asked for. Replying with only a PC path does NOT deliver the file. Max 25 MB per "
                       "file, 10 per reply; folders must be zipped first; keys/credentials are refused.",
        "parameters": {"type": "object", "properties": {
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "absolute paths (or relative to the working directory) of files to send"},
            "path": {"type": "string", "description": "a single file to send (same as paths=[path])"}}}}),
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
        "description": "Run a shell command and return its output. Dangerous commands ask the user first. "
                       "background=true for servers/long jobs (then shell_job).",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "workdir": {"type": "string"},
            "timeout": {"type": "number", "description": "seconds, default 60"},
            "background": {"type": "boolean"}}, "required": ["command"]}}),
    "grep": (tool_grep, {
        "description": "Regex search in files (ripgrep, .gitignore respected), capped. Use instead of shell grep.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"},
            "output": {"type": "string", "enum": ["content", "files", "count"]},
            "ignore_case": {"type": "boolean"}, "context": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": ["pattern"]}}),
    "glob": (tool_glob, {
        "description": "Find files by name pattern (e.g. **/*.py), newest first.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}),
    "shell_job": (tool_shell_job, {
        "description": "Background jobs from shell(background=true). action: list | output (new output) | "
                       "wait (until done or timeout s) | kill.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "output", "wait", "kill"]}, "id": {"type": "string"},
            "timeout": {"type": "number"}}, "required": ["action"]}}),
    "read_file": (tool_read_file, {
        "description": "Read a text file (with line numbers) or list a directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}),
    "write_file": (tool_write_file, {
        "description": "Create or overwrite a text file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}),
    "edit_file": (tool_edit_file, {
        "description": "Replace text in a file; old_text must match one place (whitespace/indent tolerated) unless "
                       "replace_all. Many changes: edits=[{old_text,new_text}] (all or nothing).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"}, "edits": {"type": "array", "items": {"type": "object"}}},
            "required": ["path"]}}),
    "web_search": (tool_web_search, {
        "description": "Search the web (no key) and read the top `fetch` pages (default 2, clipped to the query). "
                       "Use it for facts you do not know.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "fetch": {"type": "integer"}},
                       "required": ["query"]}}),
    "web_fetch": (tool_web_fetch, {
        "description": "Fetch a URL as readable text (JS pages rendered); `query` keeps the matching parts of long pages.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "query": {"type": "string"}},
                       "required": ["url"]}}),
    "memory": (tool_memory, {
        "description": "Long-term memory notes. action: list | read | append | write; name: note name.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "read", "append", "write"]},
            "name": {"type": "string"}, "content": {"type": "string"}}, "required": ["action"]}}),
    "skill": (tool_skill, {
        "description": "List installed skills (no name) or read one skill's instructions (name). Read the matching "
                       "skill BEFORE starting a task it covers (design, security, diagrams, academic writing, "
                       "debugging, ...), then follow it.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}),
    "diagram_save": (tool_diagram_save, {
        "description": "Save a diagram so it opens on this PC and downloads on the phone. format: svg (inline SVG), "
                       "html (self-contained page) or mermaid (Mermaid source; wrapped in an HTML page that renders "
                       "it). Writes to ~/.neovarch/diagrams and returns the absolute path; end your answer with it. "
                       "open=true also opens it in the PC's browser.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "format": {"type": "string", "enum": ["svg", "html", "mermaid"]},
            "content": {"type": "string"}, "open": {"type": "boolean"}}, "required": ["format", "content"]}}),
    "visual_check": (tool_visual_check, {
        "description": "Check an inline ```visual block (declarative graph/flow/bar/timeline/compare JSON spec, raw SVG "
                       "or HTML+CSS) before sending it in the answer: reports errors the chat renderer would hit "
                       "(unknown type, edges to missing nodes, missing viewBox, scripts/external urls) and layout "
                       "advice. code = the block content (with or without the ```visual fence). See skill visual-inline.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}),
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
    "ppt_setup": (tool_ppt_setup, {
        "description": "Prepare PowerPoint (.pptx) generation with PPT Master (MIT, github.com/hugohe3/ppt-master): checks "
                       "Python 3.10+ on this PC, downloads the official skill once into ~/.neovarch/skills/ppt-master and "
                       "installs its packages in a private venv. Returns SKILL_DIR, PYTHON and WORK_DIR. pdf=true also "
                       "installs PyMuPDF (AGPL-3.0) for PDF sources; ask the user first.",
        "parameters": {"type": "object", "properties": {
            "pdf": {"type": "boolean", "description": "also install PDF input support (PyMuPDF, AGPL-3.0)"},
            "force": {"type": "boolean", "description": "re-download the skill"}}}}),
    "ppt_export": (tool_ppt_export, {
        "description": "Export a PPT Master project (its svg_output/ pages, after the final quality check) to a native, "
                       "editable .pptx with the skill's own exporter. Returns the .pptx path(s).",
        "parameters": {"type": "object", "properties": {
            "project_path": {"type": "string", "description": "PPT Master project folder"},
            "quick": {"type": "boolean", "description": "Quick workflow project (default true); false for the full workflow"},
            "notes": {"type": "boolean", "description": "include speaker notes (default true)"},
            "output": {"type": "string", "description": "optional explicit output .pptx path"}},
            "required": ["project_path"]}}),
    "obsidian_links": (tool_obsidian_links, {
        "description": "List the backlinks (notes that [[link]] to this one) and outgoing links of a vault note.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}),
}


from neovarch import orchestrator as _orch  # noqa: E402  (registers the main agent's self/orchestrator tools)

TOOLS.update(_orch.TOOLS)


def _disabled_tools() -> set[str]:
    try:
        from neovarch import config as cfgmod
        from neovarch.selfedit import PROTECTED_TOOLS
        raw = cfgmod.get_path(cfgmod.load_config(), "tools.disabled", []) or []
        return {str(x) for x in raw} - PROTECTED_TOOLS if isinstance(raw, list) else set()
    except Exception:  # a broken config must never hide every tool
        return set()


def _allowed_builtin(ctx: "ToolContext | None") -> set[str]:
    names = set(TOOLS) - _disabled_tools()
    company = getattr(ctx, "company", None) if ctx is not None else None
    if company is None:
        if ctx is None or getattr(ctx, "kantor", None) is None:
            names.discard("kantor")
        return names
    names.discard("kantor")  # employees never run the Kantor; the main agent does
    names -= set(_orch.TOOLS) - _orch.EMPLOYEE_ALLOWED  # nor change the install
    allowed = company.allowed_tools() if hasattr(company, "allowed_tools") else None
    if allowed:
        allowed = set(allowed) | ({"web_search"} if "web_fetch" in allowed else set()) \
            | ({"grep", "glob", "repo_map"} if "read_file" in allowed else set()) \
            | ({"shell_job"} if "shell" in allowed else set()) | ({"apply_patch"} if "edit_file" in allowed else set())
        names &= allowed | {"office_status", "send_file"}
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
    from neovarch import hooks
    if hooks.load():
        blocked = await hooks.pre_tool(name, args, ctx.cwd)
        if blocked:
            return blocked
    try:
        result = await entry[0](args, ctx)
        if hooks.load():
            result = str(result) + await hooks.post_tool(name, args, str(result), ctx.cwd)
        return result
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


def _register_vision_tools() -> None:
    """image_ask lives in neovarch.vision (the vision fallback); registered here with the rest."""
    from neovarch import vision
    TOOLS.setdefault("image_ask", (vision.tool_image_ask, vision.IMAGE_ASK_SCHEMA))


_register_vision_tools()


def _register_design_tools() -> None:
    """`design` (Mode Desain) lives in neovarch.design; registered here with the rest."""
    from neovarch import design
    TOOLS.setdefault("design", (design.tool_design, design.SCHEMA))


_register_design_tools()


async def tool_apply_patch(args: dict, ctx: ToolContext) -> str:
    """Codex V4A multi-file patch; all or nothing (see neovarch.tools_patch)."""
    from neovarch import tools_patch
    patch = args.get("patch") or args.get("input") or args.get("diff") or ""
    try:
        changes, summary = tools_patch.plan(str(patch), lambda raw: _resolve(ctx, raw))
    except tools_patch.PatchError as exc:
        return f"error: patch not applied (nothing written): {exc}"
    tools_patch.write(changes)
    return f"patched {len(summary)} file(s):\n" + "\n".join(summary)


async def tool_repo_map(args: dict, ctx: ToolContext) -> str:
    from neovarch import repomap
    root = _resolve(ctx, str(args.get("path") or ".")) if args.get("path") else Path(ctx.cwd)
    budget = max(200, min(int(args.get("budget") or 1500), 8000))
    return await asyncio.to_thread(repomap.build, root, str(args.get("focus") or ""), budget)


def _register_agent_upgrade_tools() -> None:
    """apply_patch (Codex V4A), repo_map (symbol map), task (parallel read-only sub-agents)."""
    from neovarch import repomap, subagent, tools_patch
    TOOLS.setdefault("apply_patch", (tool_apply_patch, tools_patch.SCHEMA))
    TOOLS.setdefault("repo_map", (tool_repo_map, repomap.SCHEMA))
    TOOLS.setdefault("task", (subagent.tool_task, subagent.SCHEMA))


_register_agent_upgrade_tools()
