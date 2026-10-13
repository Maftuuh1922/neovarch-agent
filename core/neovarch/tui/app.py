"""Interactive terminal chat for Neovarch Agent (prompt_toolkit input + rich output).

The TUI is a client of the gateway's JSON-RPC session API (``session.create``,
``prompt.submit``, ``config.set model|reasoning``, ``approval.respond`` …), the
same calls the desktop and phone make; it holds no agent logic of its own.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from neovarch import PRODUCT, __version__
from neovarch.tui import brand
from neovarch.tui import commands as cmds
from neovarch.tui.client import BaseClient, ClientError

THEME = Theme({
    "accent": f"bold {brand.ACCENT}",
    "accent.soft": brand.ACCENT,
    "bone": brand.BONE,
    "muted": brand.MUTED,
    "chip": f"{brand.BONE} on #2A1212",
    "chip.done": f"{brand.MUTED} on #1A0B0B",
    "chip.fail": f"bold {brand.ACCENT_BRIGHT} on #2A1212",
    "ok": "bold #5BBF7A",
    "warn": "bold #E0A030",
    "markdown.code": f"{brand.BONE} on #1E0E0E",
    "markdown.h1": f"bold {brand.ACCENT_BRIGHT}",
    "markdown.h2": f"bold {brand.ACCENT}",
    "markdown.link": f"underline {brand.ACCENT_BRIGHT}",
})

KEY_HINTS = [("Enter", "kirim"), ("Alt+Enter", "baris baru"), ("↑↓", "riwayat"), ("Tab", "lengkapi"),
             ("Ctrl+O", "bukti"), ("Ctrl+C", "hentikan"), ("Ctrl+D", "keluar"), ("/bantuan", "")]

PATH_RE = re.compile(r"""(?:(?<=[\s`"'(\[<])|^)((?:~|/|[A-Za-z]:[\\/])[^\s`"'<>|*?\])]*[^\s`"'<>|*?\]).,:;])""",
                     re.MULTILINE)


def find_paths(text: str, limit: int = 12) -> list[str]:
    """Absolute paths of existing files mentioned in ``text`` (in order, unique)."""
    out: list[str] = []
    for m in PATH_RE.finditer(text or ""):
        raw = m.group(1)
        p = Path(os.path.expanduser(raw))
        try:
            if p.is_file() and str(p) not in out:
                out.append(str(p))
        except (OSError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def open_path(path: str) -> None:
    """Open a file with the desktop's default application (Linux, Windows, macOS)."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


# ---------------------------------------------------------------- turn state --

@dataclass
class ToolCall:
    id: str
    name: str
    preview: str = ""
    summary: str = ""
    result: str = ""
    duration: float | None = None
    done: bool = False

    @property
    def failed(self) -> bool:
        head = (self.summary or self.result or "")[:80].lower()
        return self.done and (head.startswith("error") or head.startswith("gagal") or "denied" in head)


@dataclass
class Turn:
    text: str = ""
    reasoning: str = ""
    tools: list[ToolCall] = field(default_factory=list)
    notices: list[tuple[str, str]] = field(default_factory=list)  # (style, text)
    error: str = ""
    done: bool = False
    stopping: bool = False
    started: float = field(default_factory=time.monotonic)
    usage: dict = field(default_factory=dict)
    # what an earlier live view already left on screen (approval prompts split the view)
    shown_tools: int = 0
    shown_notices: int = 0

    def tool(self, tid: str) -> ToolCall | None:
        return next((t for t in self.tools if t.id == tid), None)


def tool_chip(t: ToolCall) -> Text:
    if not t.done:
        icon, style = "⚙", "chip"
    elif t.failed:
        icon, style = "✗", "chip.fail"
    else:
        icon, style = "✓", "chip.done"
    label = f" {icon} {t.name} "
    line = Text("  ")
    line.append(label, style=style)
    if t.preview:
        line.append(" " + t.preview[:90], style="muted")
    if t.done and t.duration is not None:
        line.append(f"  {t.duration:.1f}s", style="muted")
    return line


def render_turn(turn: Turn, show_spinner: bool = True) -> RenderableType:
    parts: list[RenderableType] = []
    for style, text in turn.notices[turn.shown_notices:]:
        parts.append(Text("  " + text, style=style))
    for t in turn.tools[turn.shown_tools:]:
        parts.append(tool_chip(t))
    if turn.text:
        parts.append(Padding(Markdown(turn.text, code_theme="monokai", hyperlinks=True), (0, 0, 0, 2)))
    if turn.error:
        parts.append(Text(f"  ✗ {turn.error}", style="chip.fail"))
    if show_spinner and not turn.done:
        running = next((t for t in reversed(turn.tools) if not t.done), None)
        label = ("Menghentikan…" if turn.stopping else
                 f"Menjalankan {running.name}…" if running else
                 "Menulis…" if turn.text else "Berpikir…")
        secs = int(time.monotonic() - turn.started)
        parts.append(Spinner("dots", text=Text(f" {label} {secs}s", style="muted"), style="accent"))
    return Group(*parts) if parts else Text("")


# -------------------------------------------------------------------- app ----

AskFn = Callable[[str], Awaitable[str]]


class ChatApp:
    def __init__(self, client: BaseClient, console: Console | None = None, *,
                 prompt_input: Any = None, prompt_output: Any = None, history_path: Path | None = None,
                 cwd: str | None = None, color: bool | None = None, show_splash: bool = True):
        self.client = client
        self.color = brand.color_enabled() if color is None else color
        self.console = console or Console(theme=THEME, highlight=False, no_color=not self.color)
        if console is not None:
            self.console.push_theme(THEME)
        self.prompt_input = prompt_input
        self.prompt_output = prompt_output
        self.history_path = history_path
        self.cwd = cwd or os.getcwd()
        self.show_splash = show_splash
        self.session_id = ""
        self.title = ""
        self.info: dict = {}
        self.setup: dict = {}
        self.router_state = ""
        self.last_turn: Turn | None = None
        self.files: list[str] = []
        self.evidence_open = False
        self.running = False
        self._stop = asyncio.Event()
        self._session = None
        self._ctrl_c_at = 0.0

    # ---- prompt_toolkit --------------------------------------------------
    def _prompt_session(self):
        if self._session is not None:
            return self._session
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.output import ColorDepth
        from prompt_toolkit.styles import Style

        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            buf = event.current_buffer
            if buf.text.endswith("\\"):
                buf.delete_before_cursor(1)
                buf.insert_text("\n")
            else:
                buf.validate_and_handle()

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("c-o")
        def _(event):
            event.current_buffer.text = "/bukti"
            event.current_buffer.validate_and_handle()

        class SlashCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if not text.startswith("/") or " " in text:
                    return
                for name, (usage, desc) in cmds.COMMANDS.items():
                    word = "/" + name
                    if word.startswith(text.lower()):
                        yield Completion(word, start_position=-len(text), display=usage, display_meta=desc)

        history = InMemoryHistory()
        if self.history_path is not None:
            try:
                self.history_path.parent.mkdir(parents=True, exist_ok=True)
                history = FileHistory(str(self.history_path))
            except OSError:
                pass
        style = Style.from_dict({
            "bottom-toolbar": f"noreverse bg:#140808 {brand.MUTED}",
            "bottom-toolbar.key": f"bold {brand.BONE}",
            "bottom-toolbar.accent": f"bold {brand.ACCENT_BRIGHT}",
            "prompt": f"bold {brand.ACCENT_BRIGHT}",
            "continuation": brand.MUTED,
            "completion-menu.completion": f"bg:#1A0B0B {brand.BONE}",
            "completion-menu.completion.current": f"bg:{brand.ACCENT} #FFFFFF",
            "completion-menu.meta.completion": f"bg:#140808 {brand.MUTED}",
        })
        kwargs: dict[str, Any] = {}
        if self.prompt_input is not None:
            kwargs["input"] = self.prompt_input
        if self.prompt_output is not None:
            kwargs["output"] = self.prompt_output
        self._session = PromptSession(
            history=history, key_bindings=kb, multiline=True, completer=SlashCompleter(),
            complete_while_typing=True, bottom_toolbar=self._toolbar, style=style,
            prompt_continuation=lambda width, line_no, wrap: [("class:continuation", "·".rjust(width - 1) + " ")],
            color_depth=None if self.color else ColorDepth.MONOCHROME,
            **kwargs)
        return self._session

    def _toolbar(self):
        parts: list[tuple[str, str]] = [("class:bottom-toolbar.accent", " ✦ "),
                                        ("class:bottom-toolbar", self._status_short() + "   ")]
        for key, label in KEY_HINTS:
            parts.append(("class:bottom-toolbar.key", key))
            parts.append(("class:bottom-toolbar", (" " + label if label else "") + "  "))
        return parts

    async def ask(self, message: str) -> str:
        sess = self._prompt_session()
        try:
            return (await sess.prompt_async([("class:prompt", message)], multiline=False,
                                            complete_while_typing=False)).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ---- header / status -------------------------------------------------
    def model_label(self) -> str:
        model = self.info.get("model") or self.setup.get("model") or "—"
        prov = self.info.get("provider") or self.setup.get("inference_provider") or ""
        return f"{model}" + (f" ({prov})" if prov else "")

    def reasoning_label(self) -> str:
        return cmds.level_label(self.info.get("reasoning_effort") or "")

    def connection(self) -> tuple[str, str]:
        """(style, text) of the connection status."""
        if not self.client.connected:
            return "chip.fail", f"terputus · {self.client.label}"
        if self.setup and not self.setup.get("provider_configured", True):
            return "warn", "belum ada model · jalankan `neovarch setup`"
        if self.router_state and self.router_state not in ("running", "ready"):
            return "warn", f"9Router {self.router_state} · {self.client.label}"
        return "ok", f"terhubung · {self.client.label}"

    def _status_short(self) -> str:
        return f"{self.model_label()} · penalaran {self.reasoning_label()} · {self.connection()[1]}"

    def header(self) -> RenderableType:
        style, conn = self.connection()
        t = Text()
        t.append(f"{brand.MARK} NEOVARCH", style="accent")
        t.append("  │  ", style="muted")
        t.append("model ", style="muted")
        t.append(self.model_label(), style="bone")
        t.append("  │  ", style="muted")
        t.append("penalaran ", style="muted")
        t.append(self.reasoning_label(), style="bone")
        t.append("  │  ", style="muted")
        t.append("● ", style=style)
        t.append(conn, style=style)
        return Panel(t, border_style="accent.soft", padding=(0, 1),
                     subtitle=Text(self.title or f"sesi {self.session_id[:12]}" if self.session_id else "",
                                   style="muted"),
                     subtitle_align="right")

    def print_header(self) -> None:
        self.console.print(self.header())

    def print_splash(self) -> None:
        width = self.console.width
        text = brand.splash_text(width=width, color=self.color, version=__version__)
        self.console.print(Text.from_ansi(text) if self.color else Text(text), highlight=False)
        self.console.print()

    async def refresh_status(self) -> None:
        try:
            self.setup = await self.client.call("setup.status", {}) or {}
        except ClientError:
            self.setup = {}
        if self.session_id:
            try:
                self.info = await self.client.call("session.status", {"session_id": self.session_id}) or {}
            except ClientError:
                pass

    async def _check_router(self) -> None:
        """Background: 9Router readiness (can take seconds; never blocks the screen)."""
        if (self.info.get("provider") or self.setup.get("inference_provider")) != "9router":
            return
        try:
            st = await asyncio.wait_for(self.client.call("router.status", {}), 15)
            self.router_state = str((st or {}).get("state") or "")
        except (ClientError, asyncio.TimeoutError):
            self.router_state = "tidak terjangkau"
        except Exception:  # noqa: BLE001 - status only
            self.router_state = ""

    # ---- sessions --------------------------------------------------------
    async def new_session(self) -> None:
        res = await self.client.call("session.create", {"source": "cli", "cwd": self.cwd})
        self.session_id = res["session_id"]
        self.info = res.get("info") or {}
        self.title = ""
        self.last_turn = None
        self.files = []

    async def resume(self, key: str) -> bool:
        try:
            res = await self.client.call("session.resume", {"session_id": key})
        except ClientError as exc:
            self.console.print(Text(f"✗ {exc}", style="chip.fail"))
            return False
        self.session_id = res["session_id"]
        self.info = res.get("info") or {}
        self.title = self.info.get("title") or ""
        msgs = [m for m in res.get("messages") or [] if m.get("role") in ("user", "assistant") and m.get("content")]
        self.console.print(Text(f"Melanjutkan {self.title or self.session_id} · {len(msgs)} pesan", style="muted"))
        for m in msgs[-4:]:
            self._print_message(m["role"], str(m["content"]))
        return True

    def _print_message(self, role: str, content: str) -> None:
        if role == "user":
            self.console.print(Text("› ", style="accent") + Text(content, style="bone"))
        else:
            self.console.print(Padding(Markdown(content, code_theme="monokai"), (0, 0, 0, 2)))

    # ---- main loop -------------------------------------------------------
    async def run(self, *, resume: str | None = None, initial: str | None = None, once: bool = False) -> int:
        if self.show_splash and not once:
            self.print_splash()
        try:
            await self.client.start()
        except ClientError as exc:
            self.console.print(Text(f"✗ {exc}", style="chip.fail"))
            return 1
        try:
            if not (resume and await self.resume(resume)):
                if resume:
                    return 1
                await self.new_session()
            await self.refresh_status()
            router = asyncio.create_task(self._check_router())
            if not once:
                self.print_header()
                self.console.print(Text("  Ketik pesan, atau /bantuan untuk perintah.", style="muted"))
            if initial:
                await self.send(initial)
                if once:
                    return 1 if self.last_turn and self.last_turn.error else 0
            while True:
                try:
                    line = await self._prompt_session().prompt_async([("class:prompt", "› ")])
                except KeyboardInterrupt:
                    now = time.monotonic()
                    if now - self._ctrl_c_at < 2:
                        return 0
                    self._ctrl_c_at = now
                    self.console.print(Text("  (Ctrl+C lagi atau /keluar untuk keluar)", style="muted"))
                    continue
                except EOFError:
                    return 0
                if not line.strip():
                    continue
                if await self.handle(line) == "exit":
                    return 0
        finally:
            if "router" in locals() and not router.done():
                router.cancel()
            await self.client.close()

    async def handle(self, line: str) -> str | None:
        cmd = cmds.parse(line)
        if cmd is None:
            await self.send(line)
            return None
        if not cmd.known:
            hint = cmds.suggest(cmd.raw)
            self.console.print(Text(f"  Perintah tidak dikenal: /{cmd.raw}"
                                    + (f" — maksudnya /{hint}?" if hint else " — lihat /bantuan"), style="warn"))
            return None
        handler = getattr(self, f"cmd_{cmd.name}")
        try:
            return await handler(cmd)
        except ClientError as exc:
            self.console.print(Text(f"  ✗ {exc}", style="chip.fail"))
            return None

    # ---- commands --------------------------------------------------------
    async def cmd_keluar(self, _cmd) -> str:
        return "exit"

    async def cmd_bantuan(self, _cmd) -> None:
        tbl = Table(box=None, show_header=False, padding=(0, 2))
        tbl.add_column(style="accent.soft", no_wrap=True)
        tbl.add_column(style="bone")
        for usage, desc in cmds.COMMANDS.values():
            tbl.add_row(usage, desc)
        keys = Text("  ".join(f"{k} {v}".strip() for k, v in KEY_HINTS[:-1]), style="muted")
        self.console.print(Panel(Group(tbl, Text(""), keys), title=Text("Bantuan", style="accent"),
                                 border_style="accent.soft", title_align="left"))

    async def cmd_baru(self, _cmd) -> None:
        await self.new_session()
        self.console.print(Text("  Obrolan baru dimulai.", style="muted"))
        self.print_header()

    async def cmd_stop(self, _cmd) -> None:
        if self.session_id:
            await self.client.call("session.interrupt", {"session_id": self.session_id})
        self.console.print(Text("  Tidak ada giliran yang berjalan." if not self.running else "  Dihentikan.",
                                style="muted"))

    async def cmd_status(self, _cmd) -> None:
        await self.refresh_status()
        await self._check_router()
        style, conn = self.connection()
        tbl = Table(box=None, show_header=False, padding=(0, 2))
        tbl.add_column(style="muted", no_wrap=True)
        tbl.add_column(style="bone")
        tbl.add_row("Versi", f"{PRODUCT} v{__version__}")
        tbl.add_row("Koneksi", Text("● " + conn, style=style))
        tbl.add_row("Model", self.model_label())
        tbl.add_row("Penalaran", self.reasoning_label())
        tbl.add_row("Sesi", f"{self.session_id}" + (f" · {self.title}" if self.title else ""))
        tbl.add_row("Folder kerja", str(self.info.get("cwd") or self.cwd))
        if self.router_state:
            tbl.add_row("9Router", self.router_state)
        self.console.print(Panel(tbl, title=Text("Status", style="accent"), border_style="accent.soft",
                                 title_align="left"))

    async def cmd_model(self, cmd) -> None:
        args = list(cmd.args)
        scope = "--global" if "--global" in args else "--session"
        args = [a for a in args if a not in ("--global", "--session")]
        provider = ""
        if "--provider" in args:
            i = args.index("--provider")
            provider = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
        name = " ".join(args).strip()
        if not name:
            opts = await self.client.call("model.options", {"session_id": self.session_id})
            rows: list[tuple[str, str]] = []
            tbl = Table(box=None, show_header=False, padding=(0, 1))
            tbl.add_column(style="muted", justify="right")
            tbl.add_column(style="bone")
            tbl.add_column(style="muted")
            cur_m, cur_p = opts.get("model") or self.info.get("model"), opts.get("provider") or self.info.get("provider")
            for prov in opts.get("providers") or []:
                for m in (prov.get("models") or [])[:8]:
                    rows.append((m, prov.get("slug") or ""))
                    mark = " ●" if m == cur_m and prov.get("slug") == cur_p else ""
                    tbl.add_row(str(len(rows)), m + mark, prov.get("name") or prov.get("slug") or "")
            if not rows:
                self.console.print(Text(f"  Model sekarang: {self.model_label()} — tidak ada daftar model.",
                                        style="muted"))
                return
            self.console.print(Panel(tbl, title=Text(f"Model · sekarang {self.model_label()}", style="accent"),
                                     border_style="accent.soft", title_align="left"))
            pick = await self.ask("Nomor model (Enter batal): ")
            if not pick.isdigit() or not 1 <= int(pick) <= len(rows):
                self.console.print(Text("  Dibatalkan.", style="muted"))
                return
            name, provider = rows[int(pick) - 1]
        value = name + (f" --provider {provider}" if provider else "") + f" {scope}"
        res = await self.client.call("config.set", {"session_id": self.session_id, "key": "model", "value": value})
        self.info.update({"model": res.get("model") or name, "provider": res.get("provider") or provider})
        where = "default global" if res.get("scope") == "global" else "obrolan ini"
        self.console.print(Text(f"  Model {where}: {self.model_label()}", style="ok"))

    async def cmd_reasoning(self, cmd) -> None:
        word = cmd.args[0] if cmd.args else ""
        if not word:
            self.console.print(Text(f"  Penalaran sekarang: {self.reasoning_label()}  ·  pilihan: "
                                    + " / ".join(c.capitalize() for c in cmds.REASONING_CHOICES) + " / Mati",
                                    style="muted"))
            word = await self.ask("Tingkat penalaran (Enter batal): ")
            if not word:
                return
        level = cmds.reasoning_level(word)
        if level is None:
            self.console.print(Text(f"  Tingkat tidak dikenal: {word}. Pilih Rendah, Sedang, Tinggi, Ultra atau Mati.",
                                    style="warn"))
            return
        res = await self.client.call("config.set", {"session_id": self.session_id, "key": "reasoning",
                                                    "value": level})
        self.info["reasoning_effort"] = res.get("value") or level
        self.console.print(Text(f"  Penalaran: {self.reasoning_label()}", style="ok"))

    async def cmd_desain(self, cmd) -> None:
        # The core answers /desain inside the turn (status/cek directly, a brief starts the workflow).
        await self.send("/desain" + (f" {cmd.rest}" if cmd.rest else ""))

    async def cmd_skill(self, cmd) -> None:
        cat = await self.client.call("commands.catalog", {})
        skills = [s for s in (cat or {}).get("skills") or [] if isinstance(s, dict)]
        if not cmd.args:
            if not skills:
                self.console.print(Text("  Belum ada skill terpasang (~/.neovarch/skills).", style="muted"))
                return
            tbl = Table(box=None, show_header=False, padding=(0, 2))
            tbl.add_column(style="accent.soft", no_wrap=True)
            tbl.add_column(style="bone")
            for s in skills:
                tbl.add_row(str(s.get("name")), str(s.get("description") or "")[:100])
            self.console.print(Panel(tbl, title=Text("Skill · /skill <nama> <pesan>", style="accent"),
                                     border_style="accent.soft", title_align="left"))
            return
        name = cmd.args[0]
        names = {str(s.get("name")) for s in skills}
        if names and name not in names:
            import difflib
            hit = difflib.get_close_matches(name, sorted(names), n=1)
            self.console.print(Text(f"  Skill tidak ditemukan: {name}" + (f" — maksudnya {hit[0]}?" if hit else ""),
                                    style="warn"))
            return
        rest = cmd.rest[len(cmd.args[0]):].strip() if cmd.rest.startswith(cmd.args[0]) else " ".join(cmd.args[1:])
        msg = f"Gunakan skill `{name}` (baca dulu dengan alat `skill`)." + (f"\n\n{rest}" if rest else "")
        await self.send(msg, echo=f"/skill {name}" + (f" {rest}" if rest else ""))

    async def cmd_bukti(self, cmd) -> None:
        turn = self.last_turn
        if not turn or not turn.tools:
            self.console.print(Text("  Belum ada bukti (hasil alat) di giliran terakhir.", style="muted"))
            return
        if cmd.args and cmd.args[0].isdigit():
            i = int(cmd.args[0])
            if 1 <= i <= len(turn.tools):
                self.console.print(self.evidence([turn.tools[i - 1]], full=True, start=i))
            return
        self.evidence_open = not self.evidence_open
        if self.evidence_open:
            self.console.print(self.evidence(turn.tools))
        else:
            self.console.print(self.evidence_collapsed(turn))

    async def cmd_buka(self, cmd) -> None:
        if not self.files:
            self.console.print(Text("  Belum ada berkas di giliran terakhir.", style="muted"))
            return
        n = cmd.args[0] if cmd.args else ("1" if len(self.files) == 1 else "")
        if not n.isdigit() or not 1 <= int(n) <= len(self.files):
            self.console.print(Text(f"  Pakai /buka <1-{len(self.files)}>.", style="warn"))
            return
        path = self.files[int(n) - 1]
        try:
            open_path(path)
            self.console.print(Text(f"  Membuka {path}", style="muted"))
        except OSError as exc:
            self.console.print(Text(f"  ✗ Tidak bisa membuka {path}: {exc}", style="chip.fail"))

    # ---- evidence / files ------------------------------------------------
    def evidence_collapsed(self, turn: Turn) -> Text:
        ok = sum(1 for t in turn.tools if not t.failed)
        t = Text("  ▸ Bukti", style="accent.soft")
        t.append(f" · {len(turn.tools)} alat" + (f" · {len(turn.tools) - ok} gagal" if ok < len(turn.tools) else ""),
                 style="muted")
        t.append("  (/bukti atau Ctrl+O untuk membuka)", style="muted")
        return t

    def evidence(self, tools: list[ToolCall], full: bool = False, start: int = 1) -> RenderableType:
        items: list[RenderableType] = []
        limit = 20000 if full else 1200
        for i, t in enumerate(tools, start):
            head = Text(f"{i}. ", style="muted")
            head.append(t.name, style="accent.soft")
            if t.preview:
                head.append("  " + t.preview[:160], style="bone")
            if t.duration is not None:
                head.append(f"  {t.duration:.1f}s", style="muted")
            items.append(head)
            body = (t.result or t.summary or "").rstrip()
            if body:
                cut = body[:limit] + ("\n… (/bukti %d untuk selengkapnya)" % i if len(body) > limit and not full else "")
                items.append(Padding(Syntax(cut, "text", theme="monokai", word_wrap=True,
                                            background_color="#140808"), (0, 0, 1, 3)))
        return Panel(Group(*items), title=Text("▾ Bukti", style="accent"), border_style="accent.soft",
                     title_align="left")

    def files_block(self, files: list[str]) -> Text:
        t = Text("  Berkas", style="accent.soft")
        t.append("  (/buka <n> untuk membuka)\n", style="muted")
        for i, path in enumerate(files, 1):
            t.append(f"  [{i}] ", style="muted")
            try:
                uri = Path(path).resolve().as_uri()
            except ValueError:
                uri = ""
            t.append(path, style=f"underline {brand.BONE}" + (f" link {uri}" if uri else ""))
            if i < len(files):
                t.append("\n")
        return t

    # ---- a turn ----------------------------------------------------------
    async def send(self, text: str, echo: str | None = None) -> None:
        if echo and self.console.is_terminal is False:
            self.console.print(Text("› ", style="accent") + Text(echo, style="bone"))
        try:
            await self.client.call("prompt.submit", {"session_id": self.session_id, "text": text})
        except ClientError as exc:
            self.console.print(Text(f"  ✗ {exc}", style="chip.fail"))
            return
        turn = Turn()
        self.last_turn = turn
        self.evidence_open = False
        self.running = True
        self._stop.clear()
        old = self._install_sigint()
        try:
            await self._pump(turn)
        finally:
            self._restore_sigint(old)
            self.running = False
        if turn.tools:
            self.console.print(self.evidence_collapsed(turn))
        blob = turn.text + "\n" + "\n".join(t.result for t in turn.tools)
        self.files = find_paths(blob)
        if self.files:
            self.console.print(self.files_block(self.files))
        foot = Text("  ", style="muted")
        secs = time.monotonic() - turn.started
        foot.append(f"{secs:.1f}s", style="muted")
        tps = (turn.usage or {}).get("avg_tps")
        if tps:
            foot.append(f" · {tps} tok/s", style="muted")
        self.console.print(foot)

    def _install_sigint(self):
        loop = asyncio.get_running_loop()

        def handler(*_a):
            loop.call_soon_threadsafe(self._stop.set)
        try:
            return signal.signal(signal.SIGINT, handler)
        except (ValueError, OSError):  # not the main thread (tests)
            return None

    @staticmethod
    def _restore_sigint(old) -> None:
        if old is not None:
            try:
                signal.signal(signal.SIGINT, old)
            except (ValueError, OSError):
                pass

    async def _pump(self, turn: Turn) -> None:
        live = Live(console=self.console, get_renderable=lambda: render_turn(turn), refresh_per_second=10,
                    transient=False, vertical_overflow="visible", auto_refresh=self.console.is_terminal)
        live.start()
        deadline = None
        try:
            while not turn.done:
                if self._stop.is_set() and not turn.stopping:
                    turn.stopping = True
                    deadline = time.monotonic() + 15
                    try:
                        await self.client.call("session.interrupt", {"session_id": self.session_id})
                    except ClientError:
                        pass
                if deadline and time.monotonic() > deadline:
                    turn.error = turn.error or "dihentikan"
                    break
                try:
                    kind, sid, payload = await asyncio.wait_for(self.client.events.get(), 0.2)
                except asyncio.TimeoutError:
                    continue
                if kind == "connection.lost":
                    turn.error = "koneksi ke gateway terputus"
                    break
                if sid not in (None, self.session_id):
                    continue
                if kind == "approval.request":
                    live.stop()
                    turn.shown_tools = max(0, len(turn.tools) - 1) if turn.tools and not turn.tools[-1].done \
                        else len(turn.tools)
                    turn.shown_notices = len(turn.notices)
                    choice = await self.confirm(payload)
                    try:
                        await self.client.call("approval.respond", {"session_id": self.session_id,
                                                                    "request_id": payload.get("request_id"),
                                                                    "choice": choice})
                    except ClientError as exc:
                        turn.notices.append(("chip.fail", f"✗ {exc}"))
                    live = Live(console=self.console, get_renderable=lambda: render_turn(turn),
                                refresh_per_second=10, transient=False, vertical_overflow="visible",
                                auto_refresh=self.console.is_terminal)
                    live.start()
                    continue
                self.apply_event(turn, kind, payload)
                live.refresh()
        finally:
            turn.done = True
            live.refresh()
            live.stop()
            if not self.console.is_terminal:
                self.console.line()  # files/pipes: keep the next block on its own line

    def apply_event(self, turn: Turn, kind: str, p: dict) -> None:
        if kind == "message.delta":
            turn.text += str(p.get("text") or "")
        elif kind == "reasoning.delta":
            turn.reasoning += str(p.get("text") or "")
        elif kind == "tool.start":
            turn.tools.append(ToolCall(id=str(p.get("tool_id") or len(turn.tools)), name=str(p.get("name") or "alat"),
                                       preview=str(p.get("preview") or "")))
        elif kind == "tool.complete":
            t = turn.tool(str(p.get("tool_id") or "")) or next((x for x in reversed(turn.tools) if not x.done), None)
            if t is None:
                t = ToolCall(id=str(p.get("tool_id") or ""), name=str(p.get("name") or "alat"))
                turn.tools.append(t)
            t.done = True
            t.summary = str(p.get("summary") or "")
            t.result = str(p.get("result") or p.get("result_text") or "")
            t.duration = p.get("duration_s")
        elif kind in ("model.fallback",):
            turn.notices.append(("warn", "⚠ " + str(p.get("text") or "")))
        elif kind == "status" and p.get("text"):
            turn.notices.append(("muted", "ℹ " + str(p.get("text"))))
        elif kind == "attachment.notice" and p.get("message"):
            turn.notices.append(("warn", "⚠ " + str(p.get("message"))))
        elif kind == "error":
            turn.error = str(p.get("message") or "error")
        elif kind == "session.title":
            self.title = str(p.get("title") or "")
        elif kind == "session.info":
            self.info.update(p or {})
        elif kind == "message.complete":
            if p.get("text") and not turn.text:
                turn.text = str(p["text"])
            if p.get("error") and not turn.error and p.get("status") != "interrupted":
                turn.error = str(p["error"])
            if p.get("status") == "interrupted":
                turn.notices.append(("muted", "■ Dihentikan."))
            turn.usage = p.get("usage") or {}
            turn.done = True

    async def confirm(self, req: dict) -> str:
        """Risky action: show what will run and ask once / session / deny."""
        body = Group(Text(str(req.get("description") or "Agen ingin menjalankan perintah berisiko."), style="bone"),
                     Text(""),
                     Syntax(str(req.get("command") or ""), "bash", theme="monokai", word_wrap=True,
                            background_color="#140808"))
        self.console.print(Panel(body, title=Text("⚠ Perlu persetujuan", style="warn"), border_style="warn",
                                 subtitle=Text(str(req.get("tool_name") or ""), style="muted"),
                                 title_align="left"))
        ans = (await self.ask("Izinkan? [s]ekali · se[l]ama sesi · [T]olak: ")).lower()
        choice = {"s": "once", "sekali": "once", "y": "once", "ya": "once", "o": "once",
                  "l": "session", "sesi": "session", "selama": "session"}.get(ans, "deny")
        label = {"once": "Diizinkan sekali.", "session": "Diizinkan selama sesi ini.", "deny": "Ditolak."}[choice]
        self.console.print(Text("  " + label, style="ok" if choice != "deny" else "warn"))
        return choice


async def run_tui(*, resume: str | None = None, initial: str | None = None, once: bool = False,
                  connect: str | None = None, token: str | None = None) -> int:
    from neovarch.paths import neovarch_home
    from neovarch.tui.client import EmbeddedClient, RemoteClient
    client: BaseClient = RemoteClient(connect, token or "") if connect else EmbeddedClient()
    app = ChatApp(client, history_path=neovarch_home() / "cli_history")
    return await app.run(resume=resume, initial=initial, once=once)
