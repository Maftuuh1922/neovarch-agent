"""`neovarch` — the Neovarch Agent command line."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from neovarch import PRODUCT, __version__
from neovarch import config as cfgmod
from neovarch.paths import ensure_home, install_guard, neovarch_home

INSTALLER = "https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install"


def version_line() -> str:
    return f"{PRODUCT} v{__version__} (Neovarch core)"


def _color() -> bool:
    from neovarch.tui import brand
    return brand.color_enabled()


def _splash(width: int | None = None) -> str:
    from neovarch.tui import brand
    return brand.splash_text(width=width, color=_color(), version=__version__)


def _use_tui(args) -> bool:
    """The interactive TUI only on a real terminal; --plain, pipes and TERM=dumb stay plain."""
    if getattr(args, "plain", False) or os.environ.get("NEOVARCH_PLAIN") not in (None, "", "0"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    from neovarch import tui
    if not tui.available():
        print("neovarch: tampilan interaktif butuh paket `rich` dan `prompt_toolkit`; "
              "jalankan ulang installer atau `pip install rich prompt_toolkit`. Memakai mode polos.",
              file=sys.stderr)
        return False
    return True


# ------------------------------------------------------------------ chat -----

def _print_event(kind: str, payload: dict) -> None:
    if kind == "message.delta":
        sys.stdout.write(payload.get("text", ""))
        sys.stdout.flush()
    elif kind == "tool.start":
        sys.stdout.write(f"\n\x1b[2m⚙ {payload.get('name')}: {payload.get('preview', '')}\x1b[0m\n")
    elif kind == "tool.complete":
        sys.stdout.write(f"\x1b[2m  ↳ {payload.get('summary', '')} ({payload.get('duration_s')}s)\x1b[0m\n")
    elif kind == "model.fallback":
        sys.stdout.write(f"\n\x1b[33m⚠ {payload.get('text', '')}\x1b[0m\n")
    elif kind == "error":
        sys.stdout.write(f"\n\x1b[31merror: {payload.get('message')}\x1b[0m\n")
    elif kind == "message.complete":
        sys.stdout.write("\n")


async def _terminal_approve(command: str, description: str, tool: str) -> str:
    print(f"\n\x1b[33m⚠ {description}\x1b[0m\n  {command}")
    if not sys.stdin.isatty():
        print("  (no terminal to ask; denied)")
        return "deny"
    answer = await asyncio.to_thread(input, "  Allow? [o]nce / [s]ession / [N]o: ")
    return {"o": "once", "once": "once", "s": "session", "session": "session", "y": "once"}.get(answer.strip().lower(), "deny")


async def _ensure_9router(timeout: float = 20.0) -> None:
    """The plain terminal chat has no gateway: start/provision the local 9Router itself.

    Bounded, so a slow or missing 9Router can never leave the terminal blank."""
    from neovarch import router9
    cfg = cfgmod.load_config()
    if cfgmod.resolve_endpoint(cfg)["provider"] != router9.PROVIDER:
        return
    try:
        st = await asyncio.wait_for(router9.ensure_ready(router9.Router9(), cfg), timeout)
    except Exception:  # noqa: BLE001 - the turn reports the real error
        return
    if not st["setup"]["ready"] and st["setup"]["message"]:
        print(f"\x1b[33m{st['setup']['message']}\x1b[0m", file=sys.stderr)


async def _chat(prompt: str | None, resume: str | None) -> int:
    from neovarch.agent import Agent, default_cwd
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    store = SessionStore()
    rec = store.find(resume) if resume else None
    if resume and not rec:
        print(f"no session {resume}", file=sys.stderr)
        return 1
    rec = rec or store.create(source="cli", cwd=str(default_cwd()))
    ctx = ToolContext(cwd=Path(rec.get("cwd") or default_cwd()), approve=_terminal_approve)
    agent = Agent(rec, store, ctx, _print_event)
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    if prompt is None:
        # Say something before any network wait: the old CLI printed nothing until
        # 9Router answered, which looked like a dead terminal.
        print(f"{version_line()}\nsesi {rec['id']} — /keluar untuk keluar, /baru untuk obrolan baru\n",
              file=sys.stdout if tty else sys.stderr, flush=True)
    await _ensure_9router()
    if prompt is not None:
        await agent.run_turn(prompt)
        return 0
    marker = "\x1b[31m›\x1b[0m " if tty and _color() else ("› " if tty else "")
    while True:
        try:
            line = await asyncio.to_thread(input, marker)
        except (EOFError, KeyboardInterrupt):
            if tty:
                print()
            return 0
        if not line.strip():
            continue
        if line.strip() in ("/exit", "/quit", "/keluar"):
            return 0
        if line.strip() in ("/new", "/baru"):
            rec = store.create(source="cli", cwd=str(default_cwd()))
            agent = Agent(rec, store, ctx, _print_event)
            print(f"new session {rec['id']}")
            continue
        try:
            await agent.run_turn(line)
        except KeyboardInterrupt:
            agent.interrupt()


# ----------------------------------------------------------------- setup -----

def cmd_router(args) -> int:
    """`neovarch router status|start|stop|setup` — the local 9Router (default provider)."""
    import json as _json

    from neovarch import router9

    async def run() -> dict:
        r = router9.Router9()
        cfg = cfgmod.load_config()
        if args.action == "start" or args.action == "setup":
            st = await r.start(cfg, wait=float(args.wait))
        elif args.action == "stop":
            st = await r.refresh(cfg)
            print("9Router dijalankan terpisah; hentikan dari ikon tray-nya atau Pengaturan \u25b8 Model.")
        else:
            st = await r.refresh(cfg)
        if args.action == "setup":
            cfg = cfgmod.load_config()
            if not cfgmod.get_path(cfg, "model.provider", "") and not cfgmod.get_path(cfg, "model.base_url", ""):
                model = router9.choose_default(r.free_models)
                cfg.setdefault("model", {})["provider"] = router9.PROVIDER
                cfg["model"]["default"] = model
                cfgmod.save_config(cfg)
            st = r.status()
        return st

    st = asyncio.run(run())
    if args.json:
        print(_json.dumps(st, ensure_ascii=False, indent=2))
    else:
        from neovarch import models as modelsmod
        ref = modelsmod.default_ref(cfgmod.load_config())
        print(f"9Router: {st['state']} ({st['base_url']})" + (f" v{st['version']}" if st.get("version") else ""))
        print(f"API key Neovarch: {'ada' if st['has_api_key'] else 'belum'}")
        print(f"Model default: {ref['model']} via {ref['provider']}")
        if st["setup"]["message"]:
            print(st["setup"]["message"])
        if st["setup"]["action_url"]:
            print(f"Dashboard: {st['setup']['action_url']}")
    return 0 if st["setup"]["ready"] or args.action in ("status", "stop") else 1


def cmd_setup(args) -> int:
    cfg = cfgmod.load_config()
    provider = args.provider
    if provider == "9router":
        from neovarch import router9
        cfg.setdefault("model", {}).update({"provider": "9router", "default": args.model or router9.DEFAULT_MODEL,
                                            "base_url": ""})
        if args.base_url:
            cfg.setdefault("router9", {})["base_url"] = args.base_url
        cfgmod.save_config(cfg)
        if args.api_key:
            cfgmod.write_env_value("NEOVARCH_9ROUTER_API_KEY", args.api_key)
        print(f"saved {cfgmod.config_path()} (provider 9router, model {cfg['model']['default']})")
        return 0
    if not provider:
        names = list(cfgmod.PRESETS) + ["custom"]
        print("Model provider (OpenAI-compatible):")
        for i, n in enumerate(names, 1):
            print(f"  {i}. {n}")
        choice = input("Choose [1]: ").strip() or "1"
        provider = names[int(choice) - 1] if choice.isdigit() else choice
    preset = cfgmod.PRESETS.get(provider, {})
    base_url = args.base_url or preset.get("base_url") or ""
    if not base_url and not args.non_interactive:
        base_url = input("Base URL (…/v1): ").strip()
    model = args.model or preset.get("model") or ""
    if not args.model and not args.non_interactive:
        model = input(f"Model [{model}]: ").strip() or model
    key_env = preset.get("key_env", "OPENAI_API_KEY") if provider != "custom" else "NEOVARCH_API_KEY"
    api_key = args.api_key
    if api_key is None and key_env and not args.non_interactive:
        api_key = getpass.getpass(f"API key ({key_env}, empty to keep): ").strip()
    name = provider if provider != "custom" else "custom"
    cfg.setdefault("providers", {})[name] = {"base_url": base_url, "key_env": key_env}
    cfg["model"] = {**cfg.get("model", {}), "provider": name, "default": model, "base_url": base_url}
    cfgmod.save_config(cfg)
    if api_key:
        cfgmod.write_env_value(key_env, api_key)
    print(f"saved {cfgmod.config_path()} (provider {name}, model {model or '-'})")
    return 0


def cmd_config(args) -> int:
    cfg = cfgmod.load_config()
    if args.action == "path":
        print(cfgmod.config_path())
    elif args.action == "get":
        value = cfgmod.get_path(cfg, args.key) if args.key else cfg
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif args.action == "set":
        try:
            value = json.loads(args.value)
        except (json.JSONDecodeError, TypeError):
            value = args.value
        if args.key == "memory.obsidian_vault" and isinstance(value, str) and value:
            value = str(Path(os.path.expanduser(value)).resolve())
        cfgmod.set_path(cfg, args.key, value)
        cfgmod.save_config(cfg)
        print(f"{args.key} = {json.dumps(value)}")
        if args.key == "memory.obsidian_vault":
            from neovarch import obsidian
            st = obsidian.status(cfg)
            if st["connected"]:
                print(f"Obsidian vault terhubung: {st['note_count']} catatan")
            elif st["configured"]:
                print(f"peringatan: folder vault tidak ditemukan: {value}")
    else:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
    return 0


def cmd_sessions(args) -> int:
    from neovarch.store import SessionStore

    store = SessionStore()
    if args.action == "show":
        rec = store.find(args.id)
        if not rec:
            return 1
        for m in rec["messages"]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                print(f"[{m['role']}] {m['content']}\n")
        return 0
    if args.action == "delete":
        return 0 if store.delete(args.id) else 1
    for s in store.list(limit=args.limit):
        print(f"{s['id']}  {s['message_count']:>3} msgs  {s['title'] or '(untitled)'}")
    return 0


def cmd_uninstall(args) -> int:
    home = neovarch_home()
    print(f"This removes Neovarch Agent and all of its data in {home}.")
    print("Only this folder is removed; nothing outside it is touched.")
    if not args.yes:
        if not sys.stdin.isatty() or input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("Cancelled (use --yes).")
            return 1
    shim = Path.home() / ".local" / "bin" / "neovarch"
    try:
        if shim.is_symlink() and str(Path(os.path.realpath(shim))).startswith(str(home)):
            shim.unlink()
            print(f"removed {shim}")
    except OSError:
        pass
    if home.name.lower().startswith(".hermes") or home == Path.home():
        print("refusing to remove", home)
        return 1
    shutil.rmtree(home, ignore_errors=True)
    print(f"removed {home}")
    return 0


def cmd_desktop(_args) -> int:
    import subprocess

    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    for exe in (data / "neovarch-agent" / "neovarch-agent", neovarch_home() / "app" / "neovarch-agent",
                local / "Programs" / "Neovarch Agent" / "Neovarch Agent.exe"):
        if exe.is_file():
            subprocess.Popen([str(exe)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Opening Neovarch Agent ({exe})")
            return 0
    print(f"The desktop app is not installed. Install it with:\n  curl -fsSL {INSTALLER}.sh | sh", file=sys.stderr)
    return 1


# ------------------------------------------------------------------ main -----

HELP_EPILOG = """\
Perintah di dalam obrolan:
  /baru                    obrolan baru
  /model [nama]            lihat atau ganti model
  /reasoning [tingkat]     Rendah, Sedang, Tinggi, Ultra (atau Mati)
  /skill [nama] [pesan]    daftar skill / pakai satu skill
  /stop                    hentikan giliran (atau Ctrl+C)
  /status                  model, penalaran, koneksi, sesi
  /bukti [n]               buka bagian Bukti (hasil alat)
  /bantuan  /keluar        bantuan, keluar

Contoh:
  neovarch                          buka obrolan interaktif
  neovarch -q "ringkas README.md"   satu pertanyaan lalu keluar
  echo "halo" | neovarch --plain    keluaran polos untuk skrip
  neovarch serve                    gateway untuk aplikasi desktop & HP (port 9319)
"""


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30, width=min(100, shutil.get_terminal_size((90, 24)).columns))


def build_parser() -> argparse.ArgumentParser:
    try:
        banner = _splash()
    except Exception:  # noqa: BLE001 - branding must never break --help
        banner = "NEOVARCH"
    p = argparse.ArgumentParser(prog="neovarch", formatter_class=_HelpFormatter,
                                description=f"{banner}\n\n{PRODUCT} — AI agent on your computer",
                                epilog=HELP_EPILOG)
    p.add_argument("-V", "--version", action="store_true", help="show version")
    p.add_argument("-q", "--query", help="run one prompt and exit")
    p.add_argument("--resume", help="continue a session (id or title)")
    p.add_argument("-p", "--profile", help="use a named profile (data under <home>/profiles/<name>)")
    p.add_argument("--plain", action="store_true", help="plain text output (no TUI, colours or splash)")
    p.add_argument("--connect", metavar="URL", help="chat through a running gateway, e.g. http://127.0.0.1:9319")
    p.add_argument("--token", help="session token for --connect (or NEOVARCH_SESSION_TOKEN)")
    sub = p.add_subparsers(dest="cmd", title="subcommands", metavar="<command>")

    c = sub.add_parser("chat", help="interactive chat (default)", formatter_class=_HelpFormatter)
    c.add_argument("-q", "--query", dest="chat_query")
    c.add_argument("--resume", dest="chat_resume")
    c.add_argument("--plain", dest="chat_plain", action="store_true", help="plain text output")

    s = sub.add_parser("serve", help="run the gateway for the desktop and phone apps")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=9319, help="0 = pick a free port (default 9319)")
    s.add_argument("--isolated", action="store_true", help="remote/phone mode: require the paired token")

    st = sub.add_parser("setup", help="choose a model provider and save its API key")
    st.add_argument("--provider")
    st.add_argument("--base-url")
    st.add_argument("--model")
    st.add_argument("--api-key")
    st.add_argument("--non-interactive", action="store_true")

    cf = sub.add_parser("config", help="show or change config.yaml")
    cf.add_argument("action", nargs="?", default="show", choices=["show", "get", "set", "path"])
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")

    se = sub.add_parser("sessions", help="list, show or delete saved chats")
    se.add_argument("action", nargs="?", default="list", choices=["list", "show", "delete"])
    se.add_argument("id", nargs="?")
    se.add_argument("--limit", type=int, default=30)

    ro = sub.add_parser("router", help="the local 9Router (default model provider)")
    ro.add_argument("action", nargs="?", default="status", choices=["status", "start", "stop", "setup"])
    ro.add_argument("--json", action="store_true")
    ro.add_argument("--wait", default="40", help="seconds to wait for 9Router to answer")

    sub.add_parser("version", help="show version")
    sub.add_parser("update", help="how to update Neovarch")
    u = sub.add_parser("uninstall", help="remove Neovarch (only ~/.neovarch)")
    u.add_argument("-y", "--yes", action="store_true")
    sub.add_parser("desktop", help="open the desktop app")
    return p


def main(argv: list[str] | None = None) -> None:
    install_guard()
    args = build_parser().parse_args(argv)
    profile = (args.profile or "").strip()
    if profile and profile != "default":
        if not profile.replace("-", "").replace("_", "").isalnum():
            print(f"invalid profile name: {profile}", file=sys.stderr)
            raise SystemExit(2)
        os.environ["NEOVARCH_HOME"] = str(neovarch_home() / "profiles" / profile)
    if args.version or args.cmd == "version":
        if not args.plain and sys.stdout.isatty():
            print(_splash() + "\n")
        print(version_line())
        print(f"Home: {neovarch_home()}")
        print(f"Install directory: {Path(__file__).resolve().parent.parent}")
        return
    ensure_home()
    if args.cmd == "serve":
        from neovarch.server import serve

        raise SystemExit(serve(args.host, args.port, isolated=args.isolated))
    if args.cmd == "setup":
        raise SystemExit(cmd_setup(args))
    if args.cmd == "router":
        raise SystemExit(cmd_router(args))
    if args.cmd == "config":
        raise SystemExit(cmd_config(args))
    if args.cmd == "sessions":
        raise SystemExit(cmd_sessions(args))
    if args.cmd == "uninstall":
        raise SystemExit(cmd_uninstall(args))
    if args.cmd == "desktop":
        raise SystemExit(cmd_desktop(args))
    if args.cmd == "update":
        print(f"Update Neovarch by re-running its installer:\n  curl -fsSL {INSTALLER}.sh | sh\n  irm {INSTALLER}.ps1 | iex")
        return
    query = getattr(args, "chat_query", None) or args.query
    resume = getattr(args, "chat_resume", None) or args.resume
    args.plain = bool(args.plain or getattr(args, "chat_plain", False))
    if _use_tui(args):
        from neovarch.tui.app import run_tui
        raise SystemExit(asyncio.run(run_tui(resume=resume, initial=query, once=query is not None,
                                             connect=args.connect,
                                             token=args.token or os.environ.get("NEOVARCH_SESSION_TOKEN"))))
    raise SystemExit(asyncio.run(_chat(query, resume)))
