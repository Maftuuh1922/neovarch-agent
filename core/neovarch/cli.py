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


async def _ensure_9router() -> None:
    """The terminal chat has no gateway: start/provision the local 9Router itself."""
    from neovarch import router9
    cfg = cfgmod.load_config()
    if cfgmod.resolve_endpoint(cfg)["provider"] != router9.PROVIDER:
        return
    try:
        st = await router9.ensure_ready(router9.Router9(), cfg)
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
    await _ensure_9router()
    if prompt is not None:
        await agent.run_turn(prompt)
        return 0
    print(f"{version_line()}\nsession {rec['id']} — /exit to quit, /new for a new chat\n")
    while True:
        try:
            line = await asyncio.to_thread(input, "\x1b[31m›\x1b[0m ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line.strip():
            continue
        if line.strip() in ("/exit", "/quit"):
            return 0
        if line.strip() == "/new":
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
    print("A Hermes Agent install (~/.hermes, the `hermes` command) is never touched.")
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

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="neovarch", description=f"{PRODUCT} — AI agent on your computer")
    p.add_argument("-V", "--version", action="store_true", help="show version")
    p.add_argument("-q", "--query", help="run one prompt and exit")
    p.add_argument("--resume", help="continue a session (id or title)")
    p.add_argument("-p", "--profile", help="use a named profile (data under <home>/profiles/<name>)")
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("chat", help="interactive chat (default)")
    c.add_argument("-q", "--query", dest="chat_query")
    c.add_argument("--resume", dest="chat_resume")

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
    raise SystemExit(asyncio.run(_chat(query, resume)))
