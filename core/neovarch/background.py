"""Jalankan di latar belakang: the PC's gateway (and its relay client) keeps
running after the desktop window is closed.

The desktop owns the process side (tray icon, a detached gateway whose stdio is
not tied to Electron, autostart at login). This module is the shared state the
desktop *and* the phone read and change, so the phone can turn the option on or
off, see whether the background service is up, and stop or restart the agent
or the gateway.

State lives in ``<NEOVARCH_HOME>/remote/background.json``::

    {"run_in_background": bool, "start_at_login": bool, "updated_at": float}

REST (gateway token required, like every /api/ route)::

    GET  /api/remote/background                  status + settings
    POST /api/remote/background                  {run_in_background?, start_at_login?, desktop_pid?}
    POST /api/remote/background/{action}         stop-agent | restart-agent | restart-gateway | stop-gateway
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from neovarch.paths import neovarch_home

log = logging.getLogger("neovarch.background")

ACTIONS = ("stop-agent", "restart-agent", "restart-gateway", "stop-gateway")
# Exit code that asks the desktop to start the gateway again (Windows has no exec()).
RESTART_EXIT_CODE = 75


def default_path() -> Path:
    return neovarch_home() / "remote" / "background.json"


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes  # noqa: PLC0415

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class BackgroundState:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else default_path()
        self.clock = clock
        self.run_in_background = False
        self.start_at_login = False
        self.updated_at = 0.0
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.run_in_background = data.get("run_in_background") is True
            self.start_at_login = data.get("start_at_login") is True
            try:
                self.updated_at = float(data.get("updated_at") or 0)
            except (TypeError, ValueError):
                self.updated_at = 0.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings(), indent=2), "utf-8")
        os.replace(tmp, self.path)

    def settings(self) -> dict:
        return {"run_in_background": self.run_in_background, "start_at_login": self.start_at_login,
                "updated_at": self.updated_at}

    def update(self, *, run_in_background: bool | None = None, start_at_login: bool | None = None) -> bool:
        changed = False
        if run_in_background is not None and run_in_background != self.run_in_background:
            self.run_in_background = run_in_background
            changed = True
        if start_at_login is not None and start_at_login != self.start_at_login:
            self.start_at_login = start_at_login
            changed = True
        if changed:
            self.updated_at = self.clock()
            self.save()
        return changed


class BackgroundService:
    """Status and controls for the background gateway, bound to one Gateway."""

    def __init__(self, gw: Any, state: BackgroundState | None = None, *,
                 exit_process: Callable[[int], None] | None = None,
                 exec_self: Callable[[], None] | None = None):
        self.gw = gw
        self.state = state or BackgroundState()
        env_pid = os.environ.get("NEOVARCH_DESKTOP_PID") or ""
        self.desktop_pid: int | None = int(env_pid) if env_pid.isdigit() else None
        self._exit = exit_process or (lambda code: os._exit(code))
        self._exec = exec_self or _exec_self
        self.pending: str | None = None  # gateway action scheduled after the reply

    # ------------------------------------------------------------------ status --
    def desktop_attached(self) -> bool:
        return pid_alive(self.desktop_pid)

    def status(self) -> dict:
        gw = self.gw
        live = list(getattr(gw, "live", {}).values())
        running = sum(1 for s in live if getattr(s, "status", "") == "running")
        relay: dict = {"enabled": False, "state": "off", "phones": 0, "error": None}
        link = getattr(gw, "link", None)
        client = getattr(link, "relay", None) if link is not None else None
        if link is not None:
            relay["enabled"] = bool(getattr(link, "relay_enabled", False))
        if client is not None:
            relay["state"] = getattr(client, "state", "off")
            relay["error"] = getattr(client, "error", None)
            phones = getattr(client, "phones", None)
            try:
                relay["phones"] = int(phones() if callable(phones) else phones or 0)
            except Exception:
                relay["phones"] = 0
        started = float(getattr(gw, "started", time.time()))
        attached = self.desktop_attached()
        return {
            **self.state.settings(),
            "service": {
                "state": "stopping" if self.pending in ("stop-gateway",) else
                         "restarting" if self.pending == "restart-gateway" else "running",
                # The gateway outlives the window only when this is on; without a
                # desktop process it is running purely in the background.
                "mode": "background" if not attached else "app",
                "desktop_attached": attached,
                "pid": os.getpid(),
                "port": getattr(gw, "port", 0),
                "started_at": started,
                "uptime_s": max(0, int(time.time() - started)),
                "platform": sys.platform,
            },
            "agent": {"sessions": len(live), "running": running},
            "relay": relay,
        }

    # ---------------------------------------------------------------- settings --
    def update(self, body: dict) -> dict:
        rib = body.get("run_in_background")
        sal = body.get("start_at_login")
        pid = body.get("desktop_pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            self.desktop_pid = pid
        self.state.update(run_in_background=rib if isinstance(rib, bool) else None,
                          start_at_login=sal if isinstance(sal, bool) else None)
        out = self.status()
        # Turned off while no desktop holds this gateway: nothing would ever stop
        # it, so it stops itself (the reply goes out first).
        if rib is False and not self.desktop_attached():
            self.pending = "stop-gateway"
            out = self.status()
            out["will_stop"] = True
        return out

    # ----------------------------------------------------------------- actions --
    def interrupt_agents(self) -> int:
        n = 0
        for live in list(getattr(self.gw, "live", {}).values()):
            if getattr(live, "status", "") != "running" and not getattr(live, "approvals", None):
                continue
            try:
                live.agent.interrupt()
            except Exception:  # pragma: no cover - defensive
                log.exception("interrupt failed")
            for a in list(getattr(live, "approvals", {}).values()):
                fut = a.get("future")
                if fut is not None and not fut.done():
                    fut.set_result("deny")
            n += 1
        return n

    def restart_agents(self) -> int:
        n = self.interrupt_agents()
        live = getattr(self.gw, "live", None)
        if isinstance(live, dict):
            for s in list(live.values()):
                task = getattr(s, "task", None)
                if task is not None and not task.done():
                    task.cancel()
            live.clear()  # next prompt opens a fresh agent from the stored session
        return n

    def action(self, name: str) -> dict:
        if name == "stop-agent":
            n = self.interrupt_agents()
            return {"ok": True, "action": name, "message": f"{n} agen dihentikan." if n else "Tidak ada agen yang berjalan."}
        if name == "restart-agent":
            n = self.restart_agents()
            return {"ok": True, "action": name, "message": "Agen dimulai ulang. Sesi tetap tersimpan."}
        if name in ("restart-gateway", "stop-gateway"):
            self.pending = name
            msg = "Gateway dimulai ulang; HP tersambung lagi sebentar lagi." if name == "restart-gateway" else \
                "Gateway dihentikan. Untuk menyalakannya lagi, buka aplikasi Neovarch di PC."
            return {"ok": True, "action": name, "message": msg}
        raise ValueError(name)

    def run_pending(self) -> None:
        """Carry out a scheduled gateway action (called after the reply is sent)."""
        name, self.pending = self.pending, None
        if name == "stop-gateway":
            log.info("background: stopping gateway on request")
            self._exit(0)
        elif name == "restart-gateway":
            log.info("background: restarting gateway on request")
            if sys.platform == "win32":
                self._exit(RESTART_EXIT_CODE)
            else:
                self._exec()


def _exec_self() -> None:
    # Same PID on POSIX, so the desktop (or the PID file) keeps tracking it.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os.execv(sys.executable, [sys.executable, *sys.argv])


def add_routes(app: web.Application, gw: Any, *, delay: float = 0.5) -> None:
    r = app.router

    def svc() -> BackgroundService:
        s = getattr(gw, "background", None)
        if s is None:
            s = gw.background = BackgroundService(gw)
        return s

    def schedule(s: BackgroundService) -> None:
        if s.pending:
            asyncio.get_running_loop().call_later(delay, s.run_pending)

    async def get(_request):
        return web.json_response(svc().status())

    async def post(request):
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"detail": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"detail": "invalid JSON"}, status=400)
        s = svc()
        out = s.update(body)
        schedule(s)
        return web.json_response(out)

    async def act(request):
        name = request.match_info["action"]
        if name not in ACTIONS:
            return web.json_response({"detail": f"aksi tidak dikenal: {name}"}, status=404)
        s = svc()
        out = s.action(name)
        schedule(s)
        return web.json_response(out)

    r.add_get("/api/remote/background", get)
    r.add_post("/api/remote/background", post)
    r.add_post("/api/remote/background/{action}", act)
