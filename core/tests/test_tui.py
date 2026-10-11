"""Terminal UI: slash-command parser, branding, and a headless chat run."""

import asyncio
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from neovarch.tui import brand
from neovarch.tui import commands as cmds

CORE = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ parser -----

@pytest.mark.parametrize("line,name,args", [
    ("/baru", "baru", []),
    ("/new", "baru", []),
    ("  /model gpt-4o-mini --global", "model", ["gpt-4o-mini", "--global"]),
    ("/reasoning Tinggi", "reasoning", ["Tinggi"]),
    ("/skill ppt-master buatkan slide", "skill", ["ppt-master", "buatkan", "slide"]),
    ("/stop", "stop", []),
    ("/STATUS", "status", []),
    ("/bantuan", "bantuan", []),
    ("/help", "bantuan", []),
    ("/keluar", "keluar", []),
    ("/exit", "keluar", []),
    ("/quit", "keluar", []),
    ("/bukti 2", "bukti", ["2"]),
    ('/model "nama dengan spasi"', "model", ["nama dengan spasi"]),
])
def test_parse_known_commands(line, name, args):
    c = cmds.parse(line)
    assert c is not None and c.known
    assert c.name == name
    assert c.args == args


@pytest.mark.parametrize("line", ["halo", "", "/", "/ spasi", "/etc/hosts isinya apa?", "a /baru",
                                  "C:\\Users\\x", "~/notes.md"])
def test_messages_are_not_commands(line):
    assert cmds.parse(line) is None


def test_unknown_command_and_suggestion():
    c = cmds.parse("/mdoel x")
    assert c is not None and not c.known and c.raw == "mdoel"
    assert cmds.suggest("mdoel") == "model"
    assert cmds.suggest("zzzzzz") is None


def test_rest_keeps_message_verbatim():
    c = cmds.parse("/skill ppt-master  buat 'judul' \"x\"")
    assert c.rest == "ppt-master  buat 'judul' \"x\""


def test_unbalanced_quotes_do_not_crash():
    c = cmds.parse('/model "tanpa tutup')
    assert c.name == "model" and c.args


@pytest.mark.parametrize("word,level", [("rendah", "low"), ("Sedang", "medium"), ("TINGGI", "high"),
                                        ("ultra", "ultra"), ("mati", "none"), ("high", "high"), ("x", None)])
def test_reasoning_words(word, level):
    assert cmds.reasoning_level(word) == level


def test_level_labels_round_trip():
    for word in cmds.REASONING_CHOICES:
        assert cmds.level_label(cmds.reasoning_level(word)).lower() == word
    assert cmds.level_label("") == "Bawaan"


def test_every_command_has_a_handler():
    from neovarch.tui.app import ChatApp
    for name in cmds.COMMANDS:
        assert callable(getattr(ChatApp, f"cmd_{name}", None)), name
    assert set(cmds.ALIASES.values()) <= set(cmds.COMMANDS)


# ------------------------------------------------------------ branding ----

def test_logo_asset_is_static_text():
    rows, mask = brand.logo_lines()
    assert len(rows) >= 10 and len(rows) == len(mask)
    assert all(ch == " " or 0x2800 <= ord(ch) <= 0x28FF for row in rows for ch in row)
    assert brand.logo_width() <= 60


def test_splash_full_colour_wide():
    s = brand.splash_text(width=100, color=True, version="9.9.9")
    assert "\x1b[" in s and "⣿" in s and "███╗" in s and "v9.9.9" in s


def test_splash_monochrome_without_colour_or_narrow():
    mono = brand.splash_text(width=100, color=False)
    assert "\x1b[" not in mono and "███╗" in mono and "⣿" not in mono
    narrow = brand.splash_text(width=60, color=True)
    assert "\x1b[" not in narrow and "N E O V A R C H" in narrow


def test_no_color_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert brand.color_enabled() is False


def test_no_third_party_branding_in_tui_sources():
    banned = "her" + "mes"
    for p in (CORE / "neovarch" / "tui").rglob("*"):
        if p.is_file():
            assert banned not in p.read_text(encoding="utf-8", errors="ignore").lower(), p


def test_find_paths(tmp_path):
    from neovarch.tui.app import find_paths
    f = tmp_path / "laporan.docx"
    f.write_text("x")
    text = f"Selesai! Berkas ada di {f}. Juga `{f}` dan /tidak/ada.txt"
    assert find_paths(text) == [str(f)]


# ------------------------------------------------------------ headless ----

class FakeClient:
    """Speaks the gateway's JSON-RPC session API with scripted events."""
    kind = "fake"

    def __init__(self, approval: bool = False):
        self.events: asyncio.Queue = asyncio.Queue()
        self.connected = False
        self.label = "lokal"
        self.calls: list[tuple[str, dict]] = []
        self.approval = approval
        self.answered = asyncio.Event()
        self.info = {"model": "mimo-2.6", "provider": "9router", "reasoning_effort": "medium", "cwd": "/tmp"}

    async def start(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "session.create":
            return {"session_id": "s1", "info": dict(self.info), "messages": []}
        if method == "setup.status":
            return {"provider_configured": True, "inference_provider": "9router"}
        if method == "session.status":
            return dict(self.info)
        if method == "router.status":
            return {"state": "running"}
        if method == "config.set":
            if params["key"] == "reasoning":
                self.info["reasoning_effort"] = params["value"]
                return {"ok": True, "value": params["value"]}
            model = params["value"].split()[0]
            self.info["model"] = model
            return {"ok": True, "model": model, "provider": "9router", "scope": "session"}
        if method == "commands.catalog":
            return {"skills": [{"name": "ppt-master", "description": "Buat PowerPoint"}]}
        if method == "approval.respond":
            self.answered.set()
            return {"ok": True}
        if method == "prompt.submit":
            asyncio.get_running_loop().create_task(self._script(params["text"]))
            return {"ok": True, "status": "running"}
        if method == "session.interrupt":
            return {"ok": True}
        return {}

    async def _script(self, text):
        put = lambda k, p: self.events.put_nowait((k, "s1", p))  # noqa: E731
        put("message.start", {})
        put("session.title", {"title": text[:20]})
        put("tool.start", {"tool_id": "t1", "name": "terminal", "preview": "ls -la"})
        if self.approval:
            put("approval.request", {"request_id": "apr-1", "command": "rm -rf build", "description": "Hapus folder",
                                     "tool_name": "terminal"})
            await asyncio.wait_for(self.answered.wait(), 10)
        put("tool.complete", {"tool_id": "t1", "name": "terminal", "summary": "total 3",
                              "result": "total 3\nREADME.md\n/etc/hostname", "duration_s": 0.2})
        for chunk in ("# Halo\n\n", "Ini **jawaban** ", "dari agen.\n\n```python\nprint('x')\n```\n"):
            put("message.delta", {"text": chunk})
        put("message.complete", {"text": "", "usage": {"avg_tps": 42.0}})


def _run_app(client, keys: str):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from rich.console import Console

    from neovarch.tui.app import ChatApp

    buf = io.StringIO()
    console = Console(file=buf, width=100, force_terminal=False, color_system=None)

    async def go():
        with create_pipe_input() as inp:
            inp.send_text(keys)
            app = ChatApp(client, console, prompt_input=inp, prompt_output=DummyOutput(), color=False)
            rc = await asyncio.wait_for(app.run(), 30)
            return rc, app
    rc, app = asyncio.run(go())
    return rc, buf.getvalue(), app


def test_headless_chat_session():
    client = FakeClient()
    rc, out, app = _run_app(client, "/reasoning tinggi\r/model gpt-x\rhalo agen\r/bukti\r/status\r/bantuan\r"
                                    "/mdoel\r/keluar\r")
    assert rc == 0
    methods = [m for m, _ in client.calls]
    assert methods[0] == "session.create"
    assert ("config.set", {"session_id": "s1", "key": "reasoning", "value": "high"}) in client.calls
    assert any(m == "config.set" and p["value"] == "gpt-x --session" for m, p in client.calls)
    assert ("prompt.submit", {"session_id": "s1", "text": "halo agen"}) in client.calls
    assert "NEOVARCH" in out and "███╗" in out                   # splash (monochrome)
    assert "penalaran" in out and "terhubung" in out              # header
    assert "Penalaran: Tinggi" in out
    assert "jawaban" in out and "print('x')" in out               # streamed markdown
    assert "terminal" in out and "ls -la" in out                  # tool chip
    assert "Bukti" in out and "README.md" in out                  # evidence opened
    assert "/etc/hostname" in out and "/buka" in out              # attachment path listed
    assert "Status" in out and "gpt-x" in out
    assert "Bantuan" in out and "/reasoning" in out
    assert "maksudnya /model" in out
    assert app.title == "halo agen"


def test_headless_approval_is_confirmed():
    client = FakeClient(approval=True)
    rc, out, _ = _run_app(client, "hapus build\rl\r/keluar\r")
    assert rc == 0
    assert ("approval.respond", {"session_id": "s1", "request_id": "apr-1", "choice": "session"}) in client.calls
    assert "Perlu persetujuan" in out and "rm -rf build" in out


def test_headless_embedded_gateway(tmp_path, monkeypatch):
    """The real gateway in-process: create a session and read its status."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NEOVARCH_HOME", str(tmp_path / ".neovarch"))
    from neovarch.paths import ensure_home
    from neovarch.tui.client import EmbeddedClient
    ensure_home()

    async def go():
        c = EmbeddedClient()
        await c.start()
        res = await c.call("session.create", {"source": "cli", "cwd": str(tmp_path)})
        st = await c.call("session.status", {"session_id": res["session_id"]})
        lv = await c.call("config.set", {"session_id": res["session_id"], "key": "reasoning", "value": "ultra"})
        await c.close()
        return res, st, lv
    res, st, lv = asyncio.run(go())
    assert res["session_id"] and "model" in st
    assert lv["value"] == "ultra"


# ------------------------------------------------------------ CLI ---------

def _env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEOVARCH_")}
    env.update(HOME=str(tmp_path), NEOVARCH_HOME=str(tmp_path / ".neovarch"), PYTHONPATH=str(CORE), **extra)
    return env


def test_help_is_branded_and_plain_when_piped(tmp_path):
    r = subprocess.run([sys.executable, "-m", "neovarch", "--help"], env=_env(tmp_path), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "███╗" in r.stdout and "\x1b[" not in r.stdout
    assert "/reasoning" in r.stdout and "--plain" in r.stdout


def test_pipe_uses_plain_mode(tmp_path):
    """stdin/stdout not a TTY: no TUI, no splash, prompt markers stay out of stdout."""
    r = subprocess.run([sys.executable, "-m", "neovarch"], input="/keluar\n", env=_env(tmp_path),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "███" not in r.stdout and "\x1b[" not in r.stdout
    assert "›" not in r.stdout
