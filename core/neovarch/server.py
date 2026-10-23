"""`neovarch serve`: the HTTP + WebSocket gateway for the desktop and phone apps.

Wire compatibility
------------------
The Neovarch desktop and the phone remote speak one wire format (see NOTICE
for its origin); this gateway implements it from scratch:

* readiness line on stdout: ``HERMES_BACKEND_READY port=<n>`` (the desktop
  waits for exactly this sentinel);
* ``/api/ws``: JSON-RPC 2.0, one object per frame; server events are
  ``{"method":"event","params":{"type","session_id","payload"}}``; approvals are
  server→client requests ``{"id":"srq-…","method":"approval",…}``;
* REST under ``/api/*``; credentials are ``Authorization: Bearer <token>``,
  ``X-Hermes-Session-Token`` or ``?token=``.

Only the routes and methods the Neovarch desktop/phone actually call are
implemented; see ``UNIMPLEMENTED`` and docs in core/README.md. Unknown calls are
answered (404 / JSON-RPC -32601) and logged to ``logs/unhandled.log``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from neovarch import PRODUCT, __version__
from neovarch import config as cfgmod
from neovarch import session_settings
from neovarch.agent import Agent, default_cwd
from neovarch.paths import neovarch_home
from neovarch.store import Kanban, SessionStore, summarize
from neovarch.office import Office
from neovarch.company import CompanyError
from neovarch.company_runtime import CompanyRuntime
from neovarch.crew import CREW_HTTP, CREW_RPC_CODES, CrewError, CrewRuntime
from neovarch import uploads as upmod
from neovarch import msg_queue
from neovarch import cron as cronmod
from neovarch import netinfo
from neovarch.realtime import EventBus
from neovarch import models as modelsmod
from neovarch import router9
from neovarch.tools import ToolContext, list_skills, tool_schemas

APPROVAL_TIMEOUT_S = 300
# Slash commands the agent turn answers (see Agent._command); the desktop sends them as messages.
CORE_CHAT_COMMANDS = ("desain", "perbaiki", "fix")
from neovarch.stt import STT_UNAVAILABLE  # noqa: E402  (re-exported for callers/tests)
COMPANY_RPC_CODES = {"invalid": -32602, "not_found": -32004, "conflict": -32009}
COMPANY_HTTP = {"invalid": 400, "not_found": 404, "conflict": 409}


def _log_unhandled(kind: str, what: str) -> None:
    from neovarch.logs import log
    log.info("unhandled %s %s", kind, what)
    try:
        with (neovarch_home() / "logs" / "unhandled.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {what}\n")
    except OSError:
        pass


# ------------------------------------------------------------------- auth -----

DESKTOP_CONTRACT = 8
DEVICE_TOKEN_PREFIX = "nvd_"  # remote_link.store.SESSION_TOKEN_PREFIX
SESSION_EXPIRED = "Sesi kedaluwarsa, pasangkan ulang"
PAIR_ONLY_ROUTES = {("POST", "/api/remote/devices")}


class Auth:
    """Local mode: the desktop passes a session token. Remote mode (--isolated
    with a basic-auth secret): the phone presents an HMAC-signed access token."""

    def __init__(self, isolated: bool):
        self.session_token = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN") or os.environ.get("NEOVARCH_SESSION_TOKEN") or ""
        secret = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_SECRET") or os.environ.get("NEOVARCH_REMOTE_SECRET") or ""
        self.secret = base64.b64decode(secret) if secret else b""
        self.isolated = isolated
        # Loopback-only credential for this process's own encrypted-link bridge
        # (relay / Bluetooth). Random per start, never written anywhere.
        self.internal_token = secrets.token_urlsafe(32)
        # () -> remote_link LinkStore | None; set by Gateway (per-device tokens, pair tokens).
        self.link_store = None
        if not self.session_token and not self.secret:
            # Never run an open gateway: mint one and print it for CLI users.
            self.session_token = secrets.token_urlsafe(24)
            print(f"session token: {self.session_token}", flush=True)

    def _signed_payload(self, token: str) -> dict | None:
        if not self.secret:
            return None
        try:
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        except (ValueError, TypeError):
            return None
        if len(blob) <= 32:
            return None
        raw, sig = blob[:-32], blob[-32:]
        if not hmac.compare_digest(sig, hmac.new(self.secret, raw, hashlib.sha256).digest()):
            return None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            if float(payload.get("exp", 0)) <= time.time():
                return None
        except (TypeError, ValueError):
            return None
        return payload

    def verify_signed(self, token: str) -> bool:
        p = self._signed_payload(token)
        return bool(p) and p.get("kind") == "access"

    def verify_pair(self, token: str) -> bool:
        """A QR pair token (kind "pair", ~10 min): good once, only for POST /api/remote/devices.

        One-time: every successful pairing moves the link store's ``pair_epoch`` past
        the token's ``iat``."""
        p = self._signed_payload(token)
        if not p or p.get("kind") != "pair":
            return False
        try:
            iat = float(p.get("iat"))
        except (TypeError, ValueError):
            return False
        if iat > time.time() + 300:
            return False
        store = self.link_store() if self.link_store else None
        return bool(store) and store.pair_token_fresh(iat)

    def check(self, request: web.Request) -> str | None:
        """``ok``, ``pair`` (QR pair token), ``expired`` (idle-expired device token) or None.

        Also records ``nv_device`` (a paired phone's id, from its session token or,
        for this process's own relay/Bluetooth bridge, the link-device header)."""
        candidates = [request.query.get("token", "")]
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            candidates.append(auth[7:].strip())
        candidates.append(request.headers.get("X-Hermes-Session-Token", ""))
        candidates.append(request.headers.get("X-Neovarch-Session-Token", ""))
        verdict = None
        for c in filter(None, candidates):
            if hmac.compare_digest(c, self.internal_token) and (request.remote or "") in ("127.0.0.1", "::1"):
                dev = request.headers.get("X-Neovarch-Link-Device", "")
                if dev:
                    request["nv_device"] = dev
                return "ok"
            if self.session_token and hmac.compare_digest(c, self.session_token):
                return "ok"
            if c.startswith(DEVICE_TOKEN_PREFIX):
                store = self.link_store() if self.link_store else None
                if store is not None:
                    state, dev = store.check_session_token(c)
                    if state == "ok":
                        request["nv_device"] = dev["id"]
                        return "ok"
                    if state == "expired":
                        verdict = "expired"
                continue
            if self.verify_signed(c):
                return "ok"
            if self.verify_pair(c):
                verdict = verdict or "pair"
        return verdict

    def ok(self, request: web.Request) -> bool:
        return self.check(request) == "ok"


PUBLIC = {"/api/health", "/api/status", "/api/health/idle"}


# --------------------------------------------------------------- runtime -----

class Conn:
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.server_requests = False
        self.attached: set[str] = set()
        self.pending: dict[str, asyncio.Future] = {}
        self.lock = asyncio.Lock()

    async def send(self, obj: dict) -> None:
        if self.ws.closed:
            return
        async with self.lock:
            try:
                await self.ws.send_str(json.dumps(obj, ensure_ascii=False, default=str))
            except (ConnectionResetError, RuntimeError):
                pass


class LiveSession:
    """A conversation opened in this gateway (runtime id == stored id)."""

    def __init__(self, gw: "Gateway", rec: dict):
        self.gw = gw
        self.rec = rec
        self.id = rec["id"]
        self.task: asyncio.Task | None = None
        self.status = "idle"
        self.approvals: dict[str, dict] = {}
        company = getattr(gw, "company", None)
        self.ctx = ToolContext(cwd=Path(rec.get("cwd") or default_cwd()), approve=self.approve,
                               office=getattr(gw, "office_status", None),
                               kantor=getattr(company, "main_tool", None),
                               session_id=self.id, uploads=getattr(gw, "uploads", None),
                               gateway=gw, set_plan=self.set_plan)
        self.agent = Agent(rec, gw.store, self.ctx, self.emit)
        self.last_text = ""
        # Desktop composers stage images with image.attach* before prompt.submit;
        # the next submit consumes them as attachments of that user turn.
        self.pending_attachments: list[dict] = []

    def emit(self, kind: str, payload: dict) -> None:
        if kind == "message.complete":
            self.last_text = payload.get("text", "")
            if payload.get("error"):
                self._turn_error = True
        elif kind == "error":
            self._turn_error = True
        self.gw.broadcast_event(kind, self.id, payload)

    # ---- message queue (v1.4.7): messages sent while a turn runs ----
    def queue_payload(self) -> dict:
        return msg_queue.payload(self.rec, upmod.public)

    def queue_changed(self) -> None:
        self.gw.store.save(self.rec)
        self.gw.broadcast_event("queue.update", self.id, self.queue_payload())

    def enqueue(self, text: str, attachments: list[dict] | None = None) -> dict:
        it = msg_queue.push(self.rec, text, attachments)
        self.queue_changed()
        return it

    def stop(self, *, keep_queue_running: bool = False) -> None:
        """Interrupt the running turn. A stop by the person pauses the queue."""
        if keep_queue_running:
            self._drain_after_stop = True
        else:
            self._user_stopped = True
        self.agent.interrupt()
        for a in list(self.approvals.values()):
            if not a["future"].done():
                a["future"].set_result("deny")

    def _after_turn(self) -> None:
        """Turn ended: send the next queued message, or pause the queue after a stop/error."""
        drain = getattr(self, "_drain_after_stop", False)
        errored = getattr(self, "_turn_error", False)
        user_stopped = getattr(self, "_user_stopped", False)
        stopped = user_stopped or errored
        self._drain_after_stop = self._user_stopped = self._turn_error = False
        if not msg_queue.items(self.rec):
            if self.rec.pop("queue_paused", None) is not None:
                self.queue_changed()
            return
        if stopped and not drain:
            msg_queue.set_paused(self.rec, True, "stopped" if user_stopped else "error")
            self.queue_changed()
            return
        if msg_queue.paused(self.rec) and not drain:
            return
        msg_queue.set_paused(self.rec, False)
        nxt = msg_queue.pop_next(self.rec)
        self.queue_changed()
        if nxt:
            self.gw.broadcast_event("queue.sent", self.id, {"id": nxt["id"], "text": nxt.get("text") or ""})
            self.submit(nxt.get("text") or "", nxt.get("attachments") or None)

    def set_plan(self, steps: list[dict]) -> None:
        """plan_update → the chat shows the checklist (desktop paints status.update; phone reads plan.update)."""
        self.rec["plan"] = steps
        self.gw.store.save(self.rec)
        self.gw.broadcast_event("plan.update", self.id, {"steps": steps})
        mark = {"todo": "\u2610", "doing": "\u25d1", "done": "\u2611", "blocked": "\u26a0"}
        self.gw.broadcast_event("status.update", self.id, {
            "kind": "plan", "text": "Rencana: " + " · ".join(f"{mark.get(s['status'], '')} {s['title']}" for s in steps)})

    async def approve(self, command: str, description: str, tool: str) -> str:
        rid = "apr-" + secrets.token_hex(4)
        req = {"session_id": self.id, "request_id": rid, "command": command, "description": description,
               "choices": ["once", "session", "deny"], "tool_name": tool}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.approvals[rid] = {"params": req, "future": fut}
        self.gw.broadcast_event("approval.request", self.id, req)
        for conn in self.gw.conns_for(self.id):
            if conn.server_requests:
                asyncio.create_task(self.gw.server_request(conn, "approval", req, fut))
        try:
            choice = await asyncio.wait_for(asyncio.shield(fut), APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            choice = "deny"
        finally:
            self.approvals.pop(rid, None)
            self.gw.broadcast_event("approval.cancelled", self.id, {"request_ids": [rid]})
        self.gw.office.observe("approval.responded", self.id, {"choice": str(choice or "deny"), "request_id": rid})
        return str(choice or "deny")

    def answer(self, rid: str | None, choice: str) -> bool:
        items = [self.approvals[rid]] if rid and rid in self.approvals else list(self.approvals.values())[:1]
        for item in items:
            if not item["future"].done():
                item["future"].set_result(choice)
                return True
        return False

    def submit(self, text: str, attachments: list[dict] | None = None) -> None:
        self._turn_error = False
        self.status = "running"  # claimed now: a second submit in the same tick is queued, not raced

        async def run():
            self.status = "running"
            self.gw.broadcast_event("session.status", self.id, {"status": "running"})
            from neovarch.logs import log
            log.info("turn start session=%s model=%s", self.id, self.info().get("model"))
            from neovarch import sync as syncmod
            syncmod.mark_turn(self.id, title=str(self.rec.get("title") or ""), model=str(self.rec.get("model") or ""),
                              preview=str(text or ""))
            try:
                await self.gw.ensure_router(self.id)
                await self.agent.run_turn(text, attachments or None)
                log.info("turn done session=%s", self.id)
            except Exception as exc:  # report, keep the gateway alive
                log.exception("turn failed session=%s", self.id)
                traceback.print_exc()
                self.emit("error", {"message": f"{type(exc).__name__}: {exc}"})
                self.emit("message.complete", {"text": "", "error": str(exc)})
            finally:
                self.status = "idle"
                syncmod.clear_turn(self.id)
                self.gw.broadcast_event("session.status", self.id, {"status": "idle"})
                self.gw.broadcast_event("sessions.changed", None, {})
                watch = getattr(self.gw, "session_watch", None)
                if watch is not None:
                    watch.note_own_write()
                try:
                    self._after_turn()
                except Exception:  # the queue must never take the gateway down
                    traceback.print_exc()
        self.task = asyncio.create_task(run())

    def info(self) -> dict:
        cfg = cfgmod.load_config()
        ep = session_settings.effective_endpoint(cfg, self.rec)
        return {"title": self.rec.get("title") or "", "running": self.status == "running",
                # The model this session's next turn uses (its own pick, else the
                # Kantor per-agent model, else the default) — never a stale name.
                **({"model": ep["model"], "provider": ep["provider"]}
                   if (self.rec.get("model_override") or {}).get("model") or (self.rec.get("model_override") or {}).get("provider")
                   else {k: v for k, v in modelsmod.agent_model(cfg, "session:" + self.id).items()
                         if k in ("model", "provider")}),
                "reasoning_effort": session_settings.effective_effort(cfg, self.rec),
                # What the provider request really carries ('' = omitted).
                "reasoning_effort_wire": session_settings.wire_effort(
                    session_settings.effective_effort(cfg, self.rec)) or "",
                "cwd": str(self.ctx.cwd), "status": self.status,
                # Version of the desktop session protocol this core speaks; the
                # desktop warns "backend out of date" below its required level.
                "desktop_contract": DESKTOP_CONTRACT}


def to_ui_messages(rec: dict) -> list[dict]:
    out = []
    for i, m in enumerate(rec.get("messages", [])):
        role = m.get("role")
        if role not in ("user", "assistant", "tool") or m.get("hidden"):
            continue  # hidden = the agent's own self-check notes, never shown as user turns
        # row_id: the message's durable 1-based position in the stored
        # transcript (messages are append-only), used by the timeline and
        # the around-window history reads.
        item: dict[str, Any] = {"id": f"{rec['id']}:{i}", "row_id": i + 1, "role": role,
                                "content": m.get("content") or "", "text": m.get("content") or "",
                                "timestamp": m.get("ts")}
        if m.get("tool_calls"):
            item["tool_calls"] = m["tool_calls"]
        if role == "tool":
            item["tool_call_id"] = m.get("tool_call_id")
            item["name"] = m.get("name")
        if m.get("reasoning"):
            item["reasoning"] = m["reasoning"]
        if m.get("evidence"):
            item["evidence"] = m["evidence"]
        if m.get("files_changed"):
            item["files_changed"] = m["files_changed"]
        # Same schema both ways: files the person sent (user) and files the agent
        # sent with send_file (assistant); the bytes come from GET /api/uploads/<id>.
        if role in ("user", "assistant") and m.get("attachments"):
            item["attachments"] = [upmod.public(a) for a in m["attachments"] if isinstance(a, dict) and a.get("id")]
        out.append(item)
    return out


class Gateway:
    def _link_store(self):
        """The paired-device store (creates the LinkService on first use); None without `cryptography`."""
        if self.link is None:
            try:
                from neovarch.remote_link.service import LinkService
            except ImportError:
                return None
            self.link = LinkService(self)
        return self.link.store

    def __init__(self, isolated: bool):
        self.store = SessionStore()
        self.uploads = upmod.UploadStore()
        self.kanban = Kanban()
        self.auth = Auth(isolated)
        self.link = None  # remote_link.LinkService (relay / Bluetooth), created on demand
        self.auth.link_store = self._link_store
        self.background = None  # background.BackgroundService ("Jalankan di latar belakang"), created on demand
        self.conns: set[Conn] = set()
        self.live: dict[str, LiveSession] = {}
        self.started = time.time()
        self.port = 0
        self.bus = EventBus()
        self.kanban.on_event = lambda ev: self.broadcast_event("kanban.changed", None, ev)
        self.office = Office(self)
        self.uploads = upmod.UploadStore()
        from neovarch.social import Social
        self.social = Social(self)
        self.catalog = modelsmod.ModelCatalog()
        self.router = router9.Router9(on_status=lambda st: self.broadcast_event("router.status", None, st),
                                      on_models=lambda _ids: self._models_stale())
        self.company = CompanyRuntime(self)
        self.crew = CrewRuntime(self)
        from neovarch import sync as syncmod
        # The phone's LAN core and this one share ~/.neovarch/sessions: announce the other's writes too.
        self.session_watch = syncmod.SessionWatcher(
            self.store.root, lambda: self.broadcast_event("sessions.changed", None, {"external": True}),
            interval=float(os.environ.get("NEOVARCH_SESSION_WATCH_S") or 2))
        self.cron = cronmod.CronStore()
        self.scheduler = cronmod.Scheduler(
            self.cron, self._cron_run, lambda: self.broadcast_event("cron.changed", None, {}),
            tick=float(os.environ.get("NEOVARCH_CRON_TICK") or 5))

    async def _cron_run(self, job: dict) -> tuple[str, str | None]:
        """Run one scheduled job: a fresh session (source "cron") with the job's prompt."""
        rec = self.store.create(source="cron", title=f"Jadwal: {job.get('name') or job['id']}",
                                model=str(job.get("model") or ""))
        live = self.open(rec)
        errors: list[str] = []
        emit = live.emit

        def capture(kind: str, payload: dict) -> None:
            if kind == "error" and payload.get("message"):
                errors.append(str(payload["message"]))
            emit(kind, payload)
        live.emit = capture  # type: ignore[method-assign]
        live.agent.emit = capture
        self.broadcast_event("sessions.changed", None, {})
        live.submit(str(job.get("prompt") or ""))
        if live.task:
            await live.task
        live.emit = emit  # type: ignore[method-assign]
        live.agent.emit = emit
        return rec["id"], (errors[-1] if errors else None)

    def set_session_effort(self, sid: str, value: Any) -> dict:
        """One chat's reasoning level ('default'/'' = follow the PC default). Shared by the
        desktop composer (config.set), the phone (PATCH /api/sessions/{id}, prompt.submit)."""
        word = str(value or "").strip().lower()
        rec = self.live[sid].rec if sid in self.live else self.store.find(sid)
        if not rec:
            raise ValueError(f"session not found: {sid}")
        if word in ("", "default", "bawaan", "null"):
            rec.pop("reasoning_effort", None)
        else:
            level = session_settings.normalize_effort(word)
            if level is None:
                raise ValueError(f"unknown reasoning level: {value}")
            rec["reasoning_effort"] = level
        self.store.save(rec)
        if rec["id"] in self.live:
            self.broadcast_event("session.info", rec["id"], self.live[rec["id"]].info())
        return rec

    def composer_catalog(self, sid: str = "") -> dict:
        """``GET /api/composer/catalog`` for the phone composer: commands, skills, models, reasoning."""
        from neovarch import providers
        cfg = cfgmod.load_config()
        rec = (self.live[sid].rec if sid in self.live else self.store.find(sid)) if sid else None
        ep = session_settings.effective_endpoint(cfg, rec)
        try:
            opts = providers.model_options(cfg, False, ep if (rec or {}).get("model_override") else None)
            provs = [{"slug": p["slug"], "name": p.get("name") or p["slug"], "models": p.get("models") or [],
                      "is_current": bool(p.get("is_current"))} for p in opts.get("providers", [])]
        except Exception:  # an unreachable endpoint must not hide the composer
            provs = []
        caps = session_settings.reasoning_caps(ep.get("model") or "")
        return {"version": 1,
                "skills": [{"name": s["name"], "description": s["description"]} for s in list_skills()],
                "commands": [{"name": "new", "description": "Mulai percakapan baru"},
                             {"name": "perbaiki", "description": "Diagnosis & perbaikan diri"},
                             {"name": "desain", "description": "Mode Desain: brief → design system → pratinjau → kode"},
                             {"name": "undo", "description": "Pulihkan versi sebelumnya"}],
                "snippets": [], "mentions": [],
                "models": {"model": ep.get("model") or "", "provider": ep.get("provider") or "", "providers": provs},
                "reasoning": {"supported": caps["supported"], "levels": caps["levels"],
                              "labels": session_settings.REASONING_LABELS, "default": "default",
                              "current": session_settings.effective_effort(cfg, rec) if rec else "",
                              "pc_default": session_settings.normalize_effort(
                                  cfgmod.get_path(cfg, "agent.reasoning_effort")) or ""},
                "features": {"prompt_fields": ["reasoning_effort"]}}

    # ---- self-repair restart -------------------------------------------------
    def request_restart(self, session_id: str = "") -> None:
        """Restart this core process once every running turn has finished.

        Chats are already on disk; the new process reports back into ``session_id``."""
        from neovarch import selfedit
        notice = {"session_id": session_id, "requested_at": time.time(), "version": __version__}
        (selfedit.self_dir() / "restart.json").write_text(json.dumps(notice), encoding="utf-8")
        if getattr(self, "_restart_task", None) is None:
            self._restart_task = asyncio.get_running_loop().create_task(self._restart_when_idle())

    async def _restart_when_idle(self) -> None:
        from neovarch.logs import log
        deadline = time.monotonic() + 600
        await asyncio.sleep(0.5)
        while time.monotonic() < deadline and any(l.status == "running" for l in self.live.values()):
            await asyncio.sleep(0.5)
        for live in list(self.live.values()):
            self.store.save(live.rec)
        self.broadcast_event("core.restarting", None, {"port": self.port})
        await asyncio.sleep(0.3)  # let the event reach the clients
        log.info("self-repair restart: re-executing the core on port %s", self.port)
        argv = ([sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "neovarch", *sys.argv[1:]])
        os.environ["NEOVARCH_RESTART_PORT"] = str(self.port)
        os.execv(argv[0], argv)

    # ---- optional extras --------------------------------------------------------
    extras_job: dict | None = None

    def start_extras_job(self, name: str, reason: str = "manual") -> None:
        """Install one extra in a worker thread; progress goes out as `extras.progress` events."""
        from neovarch import extras
        loop = asyncio.get_running_loop()
        job = {"name": name, "state": "running", "phase": "start", "percent": None, "reason": reason,
               "started_at": time.time()}
        self.extras_job = job

        def progress(ev: dict) -> None:
            job.update({k: v for k, v in ev.items() if k in ("phase", "percent", "done", "total", "version")})
            loop.call_soon_threadsafe(self.broadcast_event, "extras.progress", None, dict(job))

        def work() -> None:
            try:
                res = extras.install(name, progress=progress, force=True)
                job.update(state="done", result=res, status=res.get("status"))
            except Exception as exc:  # noqa: BLE001
                job.update(state="failed", detail=str(exc)[:300])
            loop.call_soon_threadsafe(self.broadcast_event, "extras.progress", None, dict(job))

        loop.run_in_executor(None, work)

    def ensure_extras_after_install_or_update(self) -> None:
        """First gateway start of a new Neovarch version (fresh install or update): install the
        missing optional extras in the background. Skips when already checked for this version."""
        from neovarch import extras
        st = extras.state()
        if st.get("_checked_version") == __version__:
            return
        reason = "update" if st.get("_checked_version") else "install"
        loop = asyncio.get_running_loop()

        def work() -> None:
            res = extras.ensure_all(reason=reason)
            data = extras.state()
            data["_checked_version"] = __version__
            try:
                extras._save_state(data)
            except OSError:
                pass
            loop.call_soon_threadsafe(self.broadcast_event, "extras.progress", None,
                                      {"state": "ensured", "reason": reason, "results": res})

        if os.environ.get("NEOVARCH_EXTRAS_AUTO", "").strip().lower() in ("0", "false", "no", "off"):
            return
        loop.run_in_executor(None, work)

    # ---- `neovarch update` / desktop "Perbarui" (git pull or latest release) ------
    pull_job: dict | None = None

    def start_pull_update(self, *, restart: bool = False, check_only: bool = False) -> dict:
        """Run :func:`neovarch.pull_update.run` in a worker thread. The job dict (steps, log lines,
        result or error code) is what ``GET /api/update/pull`` returns and what `update.progress`
        events carry. ``restart`` restarts this core when idle; the desktop instead relaunches
        the whole app (which restarts the core with it) and passes ``restart=False``."""
        from neovarch import pull_update
        loop = asyncio.get_running_loop()
        job: dict = {"state": "running", "steps": {}, "lines": [], "started_at": time.time(),
                     "check_only": check_only, "result": None, "error": None, "code": None}
        self.pull_job = job

        def progress(ev: dict) -> None:
            if ev.get("kind") == "step":
                job["steps"][ev["step"]] = {"status": ev["status"], "detail": ev.get("detail", "")}
                job["step"] = ev["step"]
            elif ev.get("kind") == "line":
                job["lines"] = (job["lines"] + [ev["text"]])[-400:]
            loop.call_soon_threadsafe(self.broadcast_event, "update.progress", None,
                                      {"state": job["state"], "step": job.get("step"), "event": ev})

        def work() -> None:
            ctx = pull_update.Ctx(progress=progress, restart=lambda: {"requested": False, "detail": "desktop"})
            try:
                res = pull_update.run(ctx, check_only=check_only, restart=False)
                job.update(state="done", result=res)
            except pull_update.UpdateError as exc:
                job.update(state="failed", error=exc.message, code=exc.code, rolled_back=exc.rolled_back)
            except Exception as exc:  # noqa: BLE001
                job.update(state="failed", error=f"{type(exc).__name__}: {exc}"[:400], code="internal")
            job["finished_at"] = time.time()
            loop.call_soon_threadsafe(self.broadcast_event, "update.progress", None,
                                      {"state": job["state"], "code": job.get("code")})
            if restart and job["state"] == "done" and (job.get("result") or {}).get("updated"):
                loop.call_soon_threadsafe(self.request_restart, "")

        loop.run_in_executor(None, work)
        return job

    async def watch_update_restart(self, interval: float = 2.0) -> None:
        """`neovarch update` in a terminal writes <home>/update/restart-request.json; restart when idle."""
        from neovarch import pull_update
        started = time.time()
        path = pull_update.restart_request_path()
        while True:
            await asyncio.sleep(interval)
            try:
                ts = float(json.loads(path.read_text(encoding="utf-8")).get("ts") or 0)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
            if ts > started:
                try:
                    path.unlink()
                except OSError:
                    pass
                self.request_restart("")
                return

    def consume_restart_notice(self) -> None:
        """First boot after a restart: tell the chat that asked for it how it went."""
        from neovarch import selfedit
        path = selfedit.self_dir() / "restart.json"
        try:
            notice = json.loads(path.read_text(encoding="utf-8"))
            path.unlink()
        except (OSError, ValueError):
            return
        sid = str(notice.get("session_id") or "")
        rec = self.store.find(sid) if sid else None
        if not rec:
            return
        took = time.time() - float(notice.get("requested_at") or time.time())
        rec.setdefault("messages", []).append({
            "role": "assistant", "ts": time.time(), "command": "restart",
            "content": (f"\u2705 Core Neovarch sudah dimulai ulang ({took:.0f} dtk, versi {__version__}). "
                        "Perubahan sudah aktif; obrolan ini tetap tersimpan. Kalau ada yang aneh, ketik /undo "
                        "untuk memulihkan perubahan terakhir atau /perbaiki untuk diagnosis.")})
        self.store.save(rec)

    # ---- plumbing --------------------------------------------------------
    def conns_for(self, sid: str | None) -> list[Conn]:
        return [c for c in self.conns if sid is None or sid in c.attached or not c.attached]

    def broadcast_event(self, kind: str, sid: str | None, payload: dict) -> None:
        if kind != "office.update":
            self.office.observe(kind, sid, payload)
            try:
                self.company.observe(kind, sid, payload)
            except Exception:  # cost capture must never break event delivery
                traceback.print_exc()
            crew = self.__dict__.get("crew")
            if crew is not None and kind != "crew.update":
                try:
                    crew.observe(kind, sid, payload)
                except Exception:
                    traceback.print_exc()
        social = self.__dict__.get("social")
        if social is not None:
            social.observe(kind, sid, payload)
        if (kind == "tool.complete" and isinstance(payload, dict)
                and str(payload.get("name") or "").startswith("obsidian_write")):
            self.broadcast_event("vault.changed", None, {"tool": payload.get("name")})
        ev = self.bus.publish(kind, sid, payload)
        frame = {"jsonrpc": "2.0", "method": "event",
                 "params": {"type": kind, "session_id": sid, "payload": payload, "seq": ev["seq"]}}
        for conn in list(self.conns):
            if sid is None or sid in conn.attached:
                try:
                    asyncio.get_running_loop().create_task(conn.send(frame))
                except RuntimeError:  # no loop (sync caller outside the gateway)
                    pass

    async def server_request(self, conn: Conn, method: str, params: dict, answer: asyncio.Future) -> None:
        rid = "srq-" + secrets.token_hex(6)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[rid] = fut
        await conn.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            result = await asyncio.wait_for(fut, APPROVAL_TIMEOUT_S)
            if not answer.done() and isinstance(result, dict) and result.get("choice"):
                answer.set_result(result["choice"])
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            conn.pending.pop(rid, None)
            if answer.done():
                await conn.send({"jsonrpc": "2.0", "method": "request.cancel", "params": {"id": rid}})

    def open(self, rec: dict) -> LiveSession:
        live = self.live.get(rec["id"])
        if not live:
            live = LiveSession(self, rec)
            self.live[rec["id"]] = live
            self.company.bind_session(live)
        return live

    def active_sessions(self) -> list[dict]:
        """Chats with a running turn, in this core and in the other core on this PC (phone LAN core)."""
        from neovarch import sync as syncmod
        out = [{**summarize(l.rec), **l.info(), "id": l.id} for l in self.live.values() if l.status == "running"]
        seen = {row["id"] for row in out}
        for t in syncmod.foreign_turns():
            sid = str(t.get("session_id") or "")
            if not sid or sid in seen:
                continue
            rec = self.store.load(sid)
            row = summarize(rec) if rec else {"id": sid, "title": t.get("title") or None, "preview": t.get("preview") or ""}
            out.append({**row, "id": sid, "status": "running", "model": t.get("model") or row.get("model") or "",
                        "elsewhere": True})
            seen.add(sid)
        return out

    def office_status(self) -> dict:
        """Kantor snapshot plus the active model (the agent's office_status tool)."""
        try:
            company = self.company.summary()
        except Exception:
            company = None
        return {**self.office.snapshot(), "model": self.model_info(), "company": company}

    def model_info(self) -> dict:
        cfg = cfgmod.load_config()
        ep = cfgmod.resolve_endpoint(cfg)
        return {"model": ep["model"], "provider": ep["provider"], "base_url": ep["base_url"],
                "context_length": cfgmod.get_path(cfg, "model.context_length", 128000),
                "configured": bool(ep["base_url"])}

    # ---- 9Router + model routing -------------------------------------------
    def _models_stale(self) -> None:
        self.catalog.fetched_at = 0.0
        self.broadcast_event("models.changed", None, {"count": len(self.catalog.rows), "fetched_at": time.time()})

    async def ensure_router(self, sid: str) -> None:
        """Before a turn on 9Router: make sure we know it is up and hold its API key."""
        try:
            ep = modelsmod.endpoint_for(cfgmod.load_config(), "session:" + sid)
            if ep["provider"] == router9.PROVIDER and (not ep["api_key"] or not self.router.running):
                await router9.ensure_ready(self.router)
        except Exception:  # noqa: BLE001 - the turn reports the real error
            pass

    async def router_config(self, body: dict) -> dict:
        """Change the 9Router URL, autostart, or paste its API key ("" clears it)."""
        cfg = cfgmod.load_config()
        r9 = cfg.setdefault("router9", {})
        if "base_url" in body:
            url = str(body.get("base_url") or "").strip()
            if url:
                from neovarch import providers
                try:
                    url = providers.normalize_base_url(url)
                except providers.EndpointError as exc:
                    raise ValueError(str(exc)) from None
            r9["base_url"] = url
            self.catalog.fetched_at = 0.0
        if "autostart" in body:
            r9["autostart"] = bool(body["autostart"])
        cfgmod.save_config(cfg)
        if "api_key" in body:
            cfgmod.write_env_value(router9.KEY_ENV, str(body.get("api_key") or "").strip())
            self.catalog.fetched_at = 0.0
        await self.router.refresh()
        self.router._last_sig = None
        return self.router._publish()

    async def router_status(self, refresh: bool = True) -> dict:
        if refresh:
            return await self.router.refresh()
        return self.router.status()

    async def models_payload(self, refresh: bool = False) -> dict:
        cfg = cfgmod.load_config()
        st = await self.router.refresh(cfg)
        changed = await self.catalog.fetch(cfg, force=refresh)
        if changed:
            self.broadcast_event("models.changed", None, {"count": len(self.catalog.rows),
                                                          "fetched_at": self.catalog.fetched_at})
        cfg = cfgmod.load_config()  # provisioning may have written the key / config
        ref = modelsmod.default_ref(cfg)
        listing = self.catalog.listing(cfg, st["running"])
        return {"models": listing,
                # OpenAI-style mirror, kept for older callers of /api/models
                "data": [{"id": m["id"], "object": "model", "owned_by": m["provider"]} for m in listing],
                "default": {"model": ref["model"], "provider": ref["provider"]},
                "router": self.router.status(cfg), "fetched_at": self.catalog.fetched_at,
                "error": self.catalog.error if not st["running"] or self.catalog.error else None}

    def _default_changed(self, res: dict) -> None:
        ref = {"model": res.get("model"), "provider": res.get("provider")}
        self.broadcast_event("model.default.changed", None, ref)
        self.broadcast_event("model.changed", None, ref)
        self.office.schedule()
        for live in list(self.live.values()):   # sessions following the default see the new one
            self.broadcast_event("session.info", live.id, live.info())

    def set_default_model(self, model: str, provider: str | None) -> dict:
        cfg = cfgmod.load_config()
        res = modelsmod.set_default(cfg, model, provider, self.catalog.ids())
        cfgmod.save_config(cfg)
        self._default_changed(res)
        return {**res, "ok": True}

    def set_agent_model(self, agent_id: str, model: str | None, provider: str | None, *, quiet: bool = False) -> dict:
        cfg = cfgmod.load_config()
        res = modelsmod.set_agent_model(cfg, agent_id, model, provider, self.catalog.ids())
        cfgmod.save_config(cfg)
        self.broadcast_event("agent.model.changed", None, res)
        sid = res["agent_id"].split(":", 1)[1] if res["agent_id"].startswith("session:") else ""
        if not quiet and sid in self.live:
            self.broadcast_event("session.info", sid, self.live[sid].info())
        self.office.schedule()
        return {**res, "ok": True}

    def switch_model_command(self, value: str, session_id: str) -> dict:
        """The composer's `config.set model "<model> --provider <p> [--session|--global]"`.

        With a session it sets THAT agent's model (per-agent override); ``--global``
        (or no session) changes the global default instead."""
        import shlex
        try:
            parts = shlex.split(value)
        except ValueError:
            parts = value.split()
        model, provider, scope = "", None, ""
        i = 0
        while i < len(parts):
            tok = parts[i]
            if tok == "--provider" and i + 1 < len(parts):
                provider = parts[i + 1]
                i += 2
                continue
            if tok in ("--session", "--global"):
                scope = tok
            elif not tok.startswith("--") and not model:
                model = tok
            i += 1
        if not model:
            raise RpcError(-32602, "model wajib diisi")
        try:
            if session_id and scope != "--global":
                res = self.set_agent_model(session_id, model, provider)
                return {"ok": True, "value": model, "model": res["model"], "provider": res["provider"],
                        "scope": "session", "deferred": False}
            res = self.set_default_model(model, provider)
            return {"ok": True, "value": model, "model": res["model"], "provider": res["provider"], "scope": "global"}
        except modelsmod.ModelError as exc:
            raise RpcError(-32602, str(exc)) from None

    async def model_options(self, p: dict) -> dict:
        """Picker catalog (``model.options``): 9Router's live list first.
        ``session_id`` makes the current row that session's own pick (else its
        Kantor per-agent model); ``refresh`` re-probes 9Router and custom
        endpoints and prunes dead ids."""
        from neovarch import providers
        cfg = cfgmod.load_config()
        refresh = p.get("refresh") in (True, "1", "true")
        try:
            await router9.ensure_ready(self.router, cfg) if refresh else None
            if await self.catalog.fetch(cfg, force=refresh):
                self.broadcast_event("models.changed", None, {"count": len(self.catalog.rows),
                                                              "fetched_at": self.catalog.fetched_at})
        except Exception:  # noqa: BLE001 - an offline router still lists the default
            pass
        cfg = cfgmod.load_config()
        if refresh:
            try:
                pruned = await providers.refresh_models(cfg)
            except Exception:  # an unreachable endpoint must not break the picker
                pruned = {}
            if pruned:
                cfgmod.save_config(cfg)
        sid = str(p.get("session_id") or "")
        rec = self.live[sid].rec if sid in self.live else (self.store.find(sid) if sid else None)
        override = (rec or {}).get("model_override") or {}
        ep = session_settings.effective_endpoint(cfg, rec) if rec and (override.get("model") or override.get("provider")) else None
        res = providers.model_options(cfg, bool(p.get("include_unconfigured")), ep)
        if sid and ep is None:
            am = modelsmod.agent_model(cfg, sid)
            if am.get("source") == "agent":
                res["scope"] = "session"
                res["model"], res["provider"] = am["model"], am["provider"]
                for prov in res["providers"]:
                    prov["is_current"] = prov["slug"] == am["provider"]
                    if prov["is_current"] and am["model"] not in prov["models"]:
                        prov["models"] = [am["model"], *prov["models"]]
                        prov["total_models"] = len(prov["models"])
        if rec is not None:
            res["reasoning_effort"] = session_settings.effective_effort(cfg, rec)
            res.setdefault("scope", "session" if rec.get("model_override") else "default")
            if rec.get("model_override"):
                res["scope"] = "session"
        r9 = next((pv for pv in res["providers"] if pv["slug"] == router9.PROVIDER), None)
        if r9 is not None:
            r9["free_models"] = [m for m in r9["models"] if m.split("/", 1)[0] in router9.FREE_ALIASES]
            r9["status"] = self.router.status(cfg)
        return res

    # ---- JSON-RPC ----------------------------------------------------------
    async def rpc(self, conn: Conn, method: str, p: dict) -> Any:
        if method == "ping":
            return {"pong": True, "seq": self.bus.seq, "boot_id": self.bus.boot_id, "ts": time.time()}
        if method == "events.replay":
            sids = p.get("session_ids")
            if isinstance(sids, list):
                conn.attached.update(str(x) for x in sids)
            try:
                since = int(p.get("since") or 0)
            except (TypeError, ValueError):
                since = 0
            return self.bus.replay(since, p.get("boot_id") or None,
                                   [str(x) for x in sids] if isinstance(sids, list) else sorted(conn.attached))
        if method == "network.addresses":
            return netinfo.addresses(self.port)
        if method == "client.capabilities":
            conn.server_requests = bool(p.get("server_requests"))
            return {"ok": True, "server_requests": conn.server_requests}
        if method == "session.list":
            return {"sessions": self.store.list(limit=int(p.get("limit") or 50), offset=int(p.get("offset") or 0))}
        if method == "session.active_list":
            return {"sessions": self.active_sessions()}
        if method == "session.create":
            cwd = p.get("cwd") or str(default_cwd())
            rec = self.store.create(source=str(p.get("source") or "desktop"), cwd=cwd,
                                    model=self.model_info()["model"])
            # The composer's pick for a new chat rides on session.create.
            if p.get("model") or p.get("provider"):
                rec["model_override"] = {"model": str(p.get("model") or ""), "provider": str(p.get("provider") or "")}
            if session_settings.normalize_effort(p.get("reasoning_effort")):
                rec["reasoning_effort"] = session_settings.normalize_effort(p.get("reasoning_effort"))
            if rec.get("model_override") or rec.get("reasoning_effort"):
                rec["model"] = session_settings.effective_endpoint(cfgmod.load_config(), rec)["model"]
                self.store.save(rec)
            live = self.open(rec)
            conn.attached.add(live.id)
            self.broadcast_event("sessions.changed", None, {})
            return {"session_id": live.id, "stored_session_id": live.id, "messages": [], "info": live.info()}
        if method in ("session.resume", "session.activate"):
            key = str(p.get("session_id") or p.get("stored_session_id") or "")
            rec = self.live[key].rec if key in self.live else self.store.find(key)
            if not rec:
                raise RpcError(-32004, f"session not found: {key}")
            live = self.open(rec)
            conn.attached.add(live.id)
            open_requests = [{"id": rid, "method": "approval", "params": a["params"]} for rid, a in live.approvals.items()]
            return {"session_id": live.id, "stored_session_id": live.id, "messages": to_ui_messages(rec),
                    "info": live.info(), "open_requests": open_requests, "queue": live.queue_payload(),
                    "pending_approval": open_requests[0]["params"] if open_requests else None}
        if method == "session.status":
            live = self._live(p)
            return live.info()
        if method == "session.title":
            live = self._live(p)
            if p.get("title"):
                live.rec["title"] = str(p["title"])
                self.store.save(live.rec)
                self.broadcast_event("session.title", live.id, {"title": live.rec["title"]})
            return {"title": live.rec.get("title") or ""}
        if method == "session.save":
            live = self._live(p)
            self.store.save(live.rec)
            return {"ok": True, "session_id": live.id}
        if method == "session.interrupt":
            live = self._live(p)
            live.stop()
            return {"ok": True}
        if method.startswith("queue."):
            return self._queue_rpc(method, p)
        if method == "prompt.submit":
            live = self._live(p)
            text = str(p.get("text") or "")
            atts = self._resolve_attachments(p.get("attachments"))
            atts = live.pending_attachments + [a for a in atts if a["id"] not in {x["id"] for x in live.pending_attachments}]
            if not text.strip() and not atts:
                raise RpcError(-32602, "text is required")
            if len(atts) > upmod.MAX_PER_MESSAGE:
                raise RpcError(-32602, upmod.TOO_MANY)
            conn.attached.add(live.id)
            if live.status == "running":
                # v1.4.7: never refuse — the message waits in the session's queue and is
                # sent when the turn ends (phone and desktop see the same queue).
                live.pending_attachments = []
                try:
                    it = live.enqueue(text, atts)
                except msg_queue.QueueError as exc:
                    raise RpcError(-32602, str(exc)) from None
                q = live.queue_payload()
                return {"ok": True, "session_id": live.id, "status": "queued", "queued": True,
                        "queue_id": it["id"], "position": q["count"], "queue": q}
            if p.get("reasoning_effort"):  # the phone's pick rides on the prompt; it sticks to the chat
                try:
                    self.set_session_effort(live.id, p.get("reasoning_effort"))
                except ValueError as exc:
                    raise RpcError(-32602, str(exc)) from None
            live.pending_attachments = []
            live.submit(text, atts)
            res: dict[str, Any] = {"ok": True, "session_id": live.id, "status": "running"}
            if atts:
                res["attachments"] = [upmod.public(a) for a in atts]
                cfg = cfgmod.load_config()
                ep = session_settings.effective_endpoint(cfg, live.rec)
                if any(a["kind"] == "image" for a in atts) and not upmod.supports_vision(cfg, ep):
                    from neovarch import vision as visionmod
                    res["notice"] = visionmod.submit_notice(cfg)
            return res
        if method in ("image.attach", "image.attach_bytes", "file.attach", "image.detach",
                      "attachment.list", "attachment.upload", "attachment.upload_chunk"):
            return self._attach_rpc(method, p)
        if method.startswith("social."):
            return await self.social.rpc(method, p)
        if method == "approval.pending":
            live = self._live(p)
            return {"pending": [a["params"] for a in live.approvals.values()]}
        if method == "approval.respond":
            live = self._live(p)
            return {"ok": live.answer(p.get("request_id"), str(p.get("choice") or "deny"))}
        if method == "config.get":
            cfg = cfgmod.load_config()
            key = p.get("key")
            return {"value": cfgmod.get_path(cfg, key) if key else cfg, "config": cfg}
        if method == "config.set":
            return self._config_set(p)
        if method == "office.snapshot":
            return self.office.snapshot()
        if method == "router.status":
            return await self.router_status()
        if method == "router.start":
            return await self.router.start()
        if method == "router.stop":
            if not self.router.status()["managed"]:
                raise RpcError(-32010, "9Router ini tidak dijalankan oleh Neovarch, jadi tidak dihentikan.")
            return await self.router.stop()
        if method == "router.provision":
            await self.router.provision()
            self.router._last_sig = None
            return await self.router_status()
        if method == "router.config":
            try:
                return await self.router_config(p)
            except ValueError as exc:
                raise RpcError(-32602, str(exc)) from None
        if method == "models.list":
            return await self.models_payload(bool(p.get("refresh")))
        if method == "models.default.get":
            return modelsmod.default_ref(cfgmod.load_config())
        if method in ("models.default.set", "agent.model.set", "agent.model.get"):
            try:
                if method == "models.default.set":
                    return self.set_default_model(str(p.get("model") or ""), p.get("provider"))
                if method == "agent.model.get":
                    return modelsmod.agent_model(cfgmod.load_config(), str(p.get("agent_id") or ""))
                return self.set_agent_model(str(p.get("agent_id") or ""), p.get("model"), p.get("provider"))
            except modelsmod.ModelError as exc:
                raise RpcError(-32602, str(exc)) from None
        if method.startswith("crew."):
            try:
                return await self.crew.call(method, p)
            except CrewError as exc:
                raise RpcError(CREW_RPC_CODES.get(exc.code, -32602), str(exc)) from None
        if method.startswith("company."):
            try:
                return await self.company.call(method, p)
            except CompanyError as exc:
                raise RpcError(COMPANY_RPC_CODES.get(exc.code, -32602), str(exc)) from None
        if method == "commands.catalog":
            return {"commands": [{"name": "new", "description": "Start a new chat"},
                                 {"name": "model", "description": "Show the configured model"},
                                 {"name": "perbaiki", "description": "Diagnosis & perbaikan diri / self-diagnose and fix"},
                                 {"name": "fix", "description": "Self-diagnose and fix (sama dengan /perbaiki)"},
                                 {"name": "desain", "description": "Mode Desain: brief → design system → pratinjau → "
                                                                   "kode / design mode"},
                                 {"name": "rencana", "description": "Mode rencana: teliti & susun rencana dulu, "
                                                                     "belum mengubah file / plan mode (read-only)"},
                                 {"name": "undo", "description": "Pulihkan versi sebelumnya / undo the agent's last change"}],
                    "skills": list_skills()}
        if method == "self.changes":
            from neovarch import selfedit
            return {"changes": selfedit.entries(int(p.get("limit") or 50))}
        if method == "self.undo":
            from neovarch import selfedit
            return selfedit.undo(p.get("change_id") or None, session_id=str(p.get("session_id") or ""))
        if method == "self.diagnose":
            from neovarch import diagnose
            res = diagnose.run(self.store, str(p.get("session_id") or ""), apply=bool(p.get("apply", True)))
            return {"report": res["report"], "findings": res["findings"], "applied": res["applied"]}
        if method == "profiles.list":
            return {"profiles": [{"name": "default", "active": True, "path": str(neovarch_home())}], "active": "default"}
        if method == "process.list":
            return {"processes": []}
        if method == "shared_metrics.status":
            return {"enabled": False, "send": False, "decided": True}
        if method.startswith("shared_metrics."):
            return {"ok": True, "enabled": False}
        if method == "complete.path":
            return {"items": self._complete_path(str(p.get("prefix") or p.get("text") or ""))}
        if method == "complete.slash":
            return {"items": []}
        if method in ("slash.exec", "command.dispatch"):
            # Core chat commands (/desain, /perbaiki, /fix) are answered by the agent turn itself:
            # tell the desktop to send the typed line as a normal message to this session.
            name = str(p.get("name") or "").strip().lower()
            arg = str(p.get("arg") or "").strip()
            if not name:
                name, _, arg = str(p.get("command") or "").lstrip("/").partition(" ")
                name, arg = name.strip().lower(), arg.strip()
            if name in CORE_CHAT_COMMANDS:
                line = f"/{name}" + (f" {arg}" if arg else "")
                return {"type": "send", "message": line, "display": line}
            raise RpcError(-32601, f"not a quick/plugin/skill command: /{name}")
        if method == "reload.mcp":
            return {"ok": True, "servers": []}
        # ---- boot / readiness: the renderer asks these before it shows the composer
        if method == "setup.status":
            info = self.model_info()
            return {"provider_configured": info["configured"], "ready": info["configured"], "ok": True,
                    "other_providers": info["configured"], "free_tier_account": False, "free_tier_route": False,
                    "inference_provider": info["provider"] or None, "profile": "default"}
        if method == "setup.runtime_check":
            info = self.model_info()
            return {"ok": info["configured"], "provider": info["provider"] or None, "model": info["model"] or None,
                    "source": "config", "free_tier_route": False, "profile": "default",
                    "error": None if info["configured"] else "No model provider configured. Run `neovarch setup`."}
        if method == "model.options":
            return await self.model_options(p)
        if method in ("model.set", "model.switch"):
            from neovarch import providers
            cfg = cfgmod.load_config()
            res = providers.set_model(cfg, {"scope": "main", **p})
            cfgmod.save_config(cfg)
            self._default_changed(res)
            return res
        # ---- features the Neovarch core does not have (yet): answer "off", never an error
        if method == "pet.info":
            return {"enabled": False}
        if method == "free_tier.status":
            return {"has_guest": False, "enabled": False, "available": False, "notice_pending": False,
                    "model": "", "label": ""}
        if method == "wake.status":
            return {"listening": False, "owned_by_caller": False, "phrase": "", "provider": "",
                    "configured_surface": "", "input_device": {}, "available": False,
                    "hint": "Not available in the Neovarch core.", "enabled": False, "audio_silent": False,
                    "capture": "", "local_input_available": False, "sample_rate": 0, "frame_length": 0}
        if method == "projects.tree":
            return {"projects": [], "active_id": None, "scoped_session_ids": []}
        if method == "bot_relay.roster.sync":
            return {"count": 0}
        if method == "subagent.list":
            return {"subagents": [], "delegations": []}
        if method in ("subscription.state", "billing.state"):
            return {"ok": True, "logged_in": False}
        if method == "plugins.manage":
            return {"plugins": [], "user_count": 0, "bundled_count": 0, "ok": True}
        from neovarch import rpc_extra
        res = await rpc_extra.handle(self, method, p)
        if res is not rpc_extra.NOT_HANDLED:
            return res
        _log_unhandled("rpc", method + " " + json.dumps(p)[:300])
        raise RpcError(-32601, f"method not implemented in the Neovarch core: {method}")

    def _config_set(self, p: dict) -> dict:
        """``config.set``: composer model/reasoning picks plus plain dotted keys."""
        key = str(p.get("key") or "")
        value = p.get("value")
        sid = str(p.get("session_id") or "")
        live = self.live.get(sid) if sid else None
        if live is None and sid:
            rec = self.store.find(sid)
            live = self.open(rec) if rec else None
        if key == "model":
            from neovarch import providers
            model, provider, session_only = session_settings.parse_model_value(value)
            if not model and not provider:
                raise RpcError(-32602, "model is required")
            cfg = cfgmod.load_config()
            explicit_global = any(str(x).strip() in ("--global", "-g") for x in str(value or "").split())
            if live is not None and not session_only and not explicit_global:
                # The composer's pick for an open chat belongs to that chat (the
                # desktop's documented contract); Settings → Model is the door
                # for the default. Persist only when asked to or when there is
                # no working default yet (the first-ever pick).
                persist = bool(cfgmod.get_path(cfg, "model.persist_switch_by_default", False))
                session_only = not persist and bool(cfgmod.resolve_endpoint(cfg)["base_url"])
            if not provider and live is not None:
                provider = session_settings.effective_endpoint(cfg, live.rec)["provider"]
            if session_only and live is not None:
                live.rec["model_override"] = {"model": model, "provider": provider}
                ep = session_settings.effective_endpoint(cfg, live.rec)
            else:
                try:
                    res = providers.set_model(cfg, {"model": model, "provider": provider})
                except providers.EndpointError as exc:
                    raise RpcError(-32602, str(exc))
                cfgmod.save_config(cfg)
                if live is not None:
                    live.rec.pop("model_override", None)
                ep = cfgmod.resolve_endpoint(cfg)
                provider = res.get("provider") or provider
            if live is not None:
                live.rec["model"] = ep["model"]
                self.store.save(live.rec)
                self.broadcast_event("session.info", live.id, live.info())
            if not (session_only and live is not None):  # the default moved
                self.broadcast_event("model.changed", None, {"provider": ep["provider"], "model": ep["model"]})
            return {"ok": True, "value": ep["model"], "model": ep["model"], "provider": ep["provider"],
                    "deferred": False, "scope": "session" if session_only and live is not None else "global"}
        if key == "reasoning":
            word = str(value or "").strip().lower()
            cfg = cfgmod.load_config()
            if word in session_settings.DISPLAY_WORDS:
                cfgmod.set_path(cfg, "display.show_reasoning", session_settings.DISPLAY_WORDS[word])
                cfgmod.save_config(cfg)
                return {"ok": True, "value": word}
            if live is not None and str(p.get("scope") or "") != "global":
                try:
                    level = self.set_session_effort(live.id, word).get("reasoning_effort") or "default"
                except ValueError:
                    raise RpcError(-32602, f"unknown reasoning level: {value}") from None
                return {"ok": True, "value": level}
            level = session_settings.normalize_effort(word)
            if level is None:
                raise RpcError(-32602, f"unknown reasoning level: {value}")
            else:
                cfgmod.set_path(cfg, "agent.reasoning_effort", level)
                cfgmod.save_config(cfg)
            return {"ok": True, "value": level}
        if not key:
            raise RpcError(-32602, "key is required")
        cfg = cfgmod.load_config()
        cfgmod.set_path(cfg, key, value)
        session_settings.repair_config(cfg)
        cfgmod.save_config(cfg)
        self._config_changed(key)
        return {"ok": True, "value": value}

    def _config_changed(self, key: str = "") -> None:
        if not key or key.startswith("memory"):
            self.office.invalidate_vault()
            self.office.schedule()
        if not key or key.startswith("appearance"):
            self.broadcast_event("appearance.changed", None, appearance_of(cfgmod.load_config()))

    def _resolve_attachments(self, raw: Any) -> list[dict]:
        """``prompt.submit {attachments: [id | {id}]}`` -> stored upload metadata."""
        out: list[dict] = []
        for item in raw if isinstance(raw, list) else []:
            uid = item.get("id") if isinstance(item, dict) else item
            meta = self.uploads.get(str(uid or ""))
            if not meta:
                raise RpcError(-32602, f"lampiran tidak ditemukan: {uid}")
            if meta["id"] not in {m["id"] for m in out}:
                out.append(meta)
        return out

    def _attach_rpc(self, method: str, p: dict) -> dict:
        """Desktop composer staging (image.attach*, file.attach, image.detach) and the
        chunked upload for clients without multipart (attachment.upload_chunk)."""
        sid = str(p.get("session_id") or "")
        try:
            if method == "attachment.list":
                return {"attachments": [upmod.public(m) for m in self.uploads.list(sid)]}
            if method == "attachment.upload_chunk":
                return self._upload_chunk(sid, p)
            if method == "attachment.upload":
                raw = base64.b64decode(str(p.get("content_base64") or ""), validate=False)
                meta = self.uploads.save_bytes(sid, str(p.get("filename") or p.get("name") or "file"), raw,
                                               p.get("mime"))
                return {"ok": True, **upmod.public(meta)}
            live = self._live(p) if sid else None
            if method == "image.detach":
                if not live:
                    return {"detached": False, "count": 0}
                target = str(p.get("path") or p.get("id") or "")
                before = len(live.pending_attachments)
                live.pending_attachments = [a for a in live.pending_attachments
                                            if target not in (a["path"], a["id"]) and target]
                if not target:
                    live.pending_attachments = []
                return {"detached": len(live.pending_attachments) < before, "count": len(live.pending_attachments)}
            if method == "image.attach_bytes":
                raw = base64.b64decode(str(p.get("content_base64") or ""), validate=False)
                meta = self.uploads.save_bytes(sid, str(p.get("filename") or "image.png"), raw)
            elif method == "image.attach":
                meta = self.uploads.import_path(sid, Path(os.path.expanduser(str(p.get("path") or ""))))
            else:  # file.attach
                name = str(p.get("name") or Path(str(p.get("path") or "file")).name)
                data_url = str(p.get("data_url") or "")
                if data_url:
                    head, _, b64 = data_url.partition(",")
                    mime = head[5:].split(";")[0] if head.startswith("data:") else None
                    meta = self.uploads.save_bytes(sid, name, base64.b64decode(b64, validate=False), mime)
                else:
                    src = Path(os.path.expanduser(str(p.get("path") or "")))
                    if not src.is_file():
                        return {"attached": False, "message": f"File tidak ditemukan: {src}"}
                    return {"attached": True, "path": str(src), "ref_path": str(src), "name": name,
                            "ref_text": f"@file:{_ref(str(src))}", "uploaded": False}
                return {"attached": True, "path": meta["path"], "ref_path": meta["path"], "name": meta["name"],
                        "ref_text": f"@file:{_ref(meta['path'])}", "uploaded": True, "id": meta["id"]}
        except upmod.UploadError as exc:
            return {"attached": False, "ok": False, "message": str(exc)}
        except (ValueError, TypeError) as exc:
            return {"attached": False, "ok": False, "message": f"lampiran tidak valid: {exc}"}
        if meta["kind"] != "image":
            self.uploads.delete(meta["id"])
            return {"attached": False, "message": f"{meta['name']} bukan gambar."}
        if live:
            if len(live.pending_attachments) >= upmod.MAX_PER_MESSAGE:
                self.uploads.delete(meta["id"])
                return {"attached": False, "ok": False, "message": upmod.TOO_MANY,
                        "count": len(live.pending_attachments)}
            live.pending_attachments.append(meta)
        return {"attached": True, "path": meta["path"], "name": meta["name"], "bytes": meta["size"],
                "count": len(live.pending_attachments) if live else 1, "id": meta["id"],
                "text": f"[gambar: {meta['name']}]"}

    def _upload_chunk(self, sid: str, p: dict) -> dict:
        """{upload_id?, filename, mime, index, data(base64), final} -> {upload_id, received} / upload."""
        uid = str(p.get("upload_id") or "")
        chunks = self.__dict__.setdefault("_chunked", {})
        if not uid:
            uid = secrets.token_hex(8)
            chunks[uid] = self.uploads.writer(sid, str(p.get("filename") or "file"), p.get("mime"))
        w = chunks.get(uid)
        if w is None:
            raise RpcError(-32602, "upload_id tidak dikenal")
        try:
            data = base64.b64decode(str(p.get("data") or ""), validate=False)
            if not getattr(w, "head", None):
                w.head = data[:16]
            w.write(data)
        except upmod.UploadError:
            chunks.pop(uid, None)
            raise
        if p.get("final"):
            chunks.pop(uid, None)
            meta = w.finish(head=getattr(w, "head", b""))
            return {"ok": True, "upload_id": uid, "done": True, **upmod.public(meta)}
        return {"ok": True, "upload_id": uid, "received": w.size, "done": False}

    def _queue_rpc(self, method: str, p: dict) -> dict:
        """queue.list / queue.edit / queue.remove / queue.send_now / queue.clear / queue.resume."""
        live = self._live(p)
        qid = str(p.get("id") or p.get("queue_id") or "")
        try:
            if method == "queue.list":
                return live.queue_payload()
            if method == "queue.edit":
                msg_queue.edit(live.rec, qid, str(p.get("text") or ""))
            elif method == "queue.remove":
                msg_queue.remove(live.rec, qid)
                if not msg_queue.items(live.rec):
                    live.rec.pop("queue_paused", None)
            elif method == "queue.clear":
                msg_queue.clear(live.rec)
            elif method in ("queue.send_now", "queue.resume"):
                if method == "queue.send_now":
                    msg_queue.to_front(live.rec, qid)
                msg_queue.set_paused(live.rec, False)
                if live.status == "running":
                    if method == "queue.send_now":
                        live.stop(keep_queue_running=True)  # interrupt; the front item goes next
                    live.queue_changed()
                    return {**live.queue_payload(), "ok": True, "status": "interrupting"}
                nxt = msg_queue.pop_next(live.rec)
                live.queue_changed()
                if nxt:
                    self.broadcast_event("queue.sent", live.id, {"id": nxt["id"], "text": nxt.get("text") or ""})
                    live.submit(nxt.get("text") or "", nxt.get("attachments") or None)
                return {**live.queue_payload(), "ok": True, "status": "running" if nxt else "idle"}
            else:
                raise RpcError(-32601, f"unknown method: {method}")
        except msg_queue.QueueError as exc:
            raise RpcError(-32602, str(exc)) from None
        live.queue_changed()
        return {**live.queue_payload(), "ok": True}

    def _live(self, p: dict) -> LiveSession:
        sid = str(p.get("session_id") or "")
        if sid in self.live:
            return self.live[sid]
        rec = self.store.find(sid)
        if not rec:
            raise RpcError(-32004, f"session not found: {sid}")
        return self.open(rec)

    def _complete_path(self, prefix: str) -> list[dict]:
        base = Path(os.path.expanduser(prefix or "."))
        folder = base if prefix.endswith(("/", os.sep)) or base.is_dir() and not prefix else base.parent
        try:
            names = sorted(folder.iterdir())[:200]
        except OSError:
            return []
        stem = "" if folder == base else base.name
        return [{"path": str(n), "name": n.name, "is_dir": n.is_dir()} for n in names if n.name.startswith(stem)][:50]


def _ref(path: str) -> str:
    return f'"{path}"' if any(c.isspace() for c in path) else path


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ HTTP -----

def build_app(gw: Gateway) -> web.Application:
    @web.middleware
    async def auth_mw(request: web.Request, handler):
        path = request.path
        if request.method == "OPTIONS":
            return web.Response(status=204, headers=_cors(request))
        verdict = gw.auth.check(request) if path.startswith("/api/") and path not in PUBLIC else "ok"
        if verdict == "pair" and (request.method, path) not in PAIR_ONLY_ROUTES:
            verdict = None
        if verdict == "expired":
            return web.json_response({"detail": SESSION_EXPIRED, "code": "session_expired"}, status=401,
                                     headers=_cors(request))
        request["nv_auth"] = verdict
        if verdict is None:
            access = os.environ.get("NEOVARCH_ACCESS_LOG")
            if access:
                with open(access, "a", encoding="utf-8") as fh:
                    fh.write(f"401 {request.method} {request.path}\n")
            return web.json_response({"detail": "Unauthorized"}, status=401, headers=_cors(request))
        try:
            resp = await handler(request)
        except web.HTTPNotFound:
            _log_unhandled("http", f"{request.method} {path}")
            resp = web.json_response({"detail": f"Not implemented in the Neovarch core: {path}"}, status=404)
        except web.HTTPException as exc:
            resp = exc
        resp.headers.update(_cors(request))
        access = os.environ.get("NEOVARCH_ACCESS_LOG")
        if access and path.startswith("/api/"):
            try:
                with open(access, "a", encoding="utf-8") as fh:
                    fh.write(f"{resp.status} {request.method} {request.path_qs}\n")
            except OSError:
                pass
        return resp

    app = web.Application(middlewares=[auth_mw], client_max_size=64 * 1024 * 1024)
    r = app.router

    async def _start_cron(_app):
        gw.scheduler.start()
        gw.social.start()
        gw.company.start()
        gw.session_watch.start()
        if os.environ.get("NEOVARCH_9ROUTER_SUPERVISE", "1") not in ("0", "false", "off"):
            gw.router.start_supervisor()

    async def _stop_cron(_app):
        await gw.scheduler.stop()
        await gw.company.stop()
        await gw.crew.stop()
        await gw.session_watch.stop()
        await gw.social.stop()
        await gw.router.close()
    app.on_startup.append(_start_cron)
    app.on_cleanup.append(_stop_cron)

    # ---- scheduled jobs (cron) ---------------------------------------------
    def _job(jid: str):
        job = gw.cron.get(jid)
        if not job:
            raise web.HTTPNotFound()
        return job

    def _job_404(jid: str):
        return web.json_response({"detail": f"Jadwal {jid} tidak ditemukan."}, status=404)

    async def cron_list(_):
        return web.json_response([gw.cron.public(j) for j in gw.cron.list()])

    async def cron_create(request):
        try:
            job = gw.cron.create(await _json(request))
        except cronmod.ScheduleError as exc:
            return web.json_response({"detail": str(exc)}, status=422)
        gw.broadcast_event("cron.changed", None, {})
        return web.json_response(gw.cron.public(job))

    async def cron_get(request):
        job = gw.cron.get(request.match_info["jid"])
        return web.json_response(gw.cron.public(job)) if job else _job_404(request.match_info["jid"])

    async def cron_update(request):
        body = await _json(request)
        updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
        safe = {k: v for k, v in updates.items() if not str(k).startswith("_")}
        try:
            job = gw.cron.update(request.match_info["jid"], safe)
        except cronmod.ScheduleError as exc:
            return web.json_response({"detail": str(exc)}, status=422)
        if not job:
            return _job_404(request.match_info["jid"])
        gw.broadcast_event("cron.changed", None, {})
        return web.json_response(gw.cron.public(job))

    async def cron_delete(request):
        ok = gw.cron.delete(request.match_info["jid"])
        if not ok:
            return _job_404(request.match_info["jid"])
        gw.broadcast_event("cron.changed", None, {})
        return web.json_response({"ok": True})

    def _toggle(enabled: bool):
        async def h(request):
            job = gw.cron.update(request.match_info["jid"], {"enabled": enabled})
            if not job:
                return _job_404(request.match_info["jid"])
            gw.broadcast_event("cron.changed", None, {})
            return web.json_response(gw.cron.public(job))
        return h

    async def cron_trigger(request):
        jid = request.match_info["jid"]
        if not gw.cron.get(jid):
            return _job_404(jid)
        task = gw.scheduler.run_now(jid)
        if task and request.query.get("wait", "1") != "0":
            await asyncio.shield(task)
        return web.json_response(gw.cron.public(gw.cron.get(jid) or {"id": jid}))

    async def cron_runs(request):
        jid = request.match_info["jid"]
        if not gw.cron.get(jid):
            return _job_404(jid)
        try:
            limit = max(1, min(int(request.query.get("limit") or 20), 50))
        except ValueError:
            limit = 20
        rows = []
        for sid in gw.cron.runs(jid)[:limit]:
            rec = gw.store.load(sid)
            if rec:
                rows.append(summarize(rec))
        return web.json_response({"runs": rows})

    async def cron_targets(_):
        return web.json_response({"targets": [{"id": "local", "name": "Lokal (sesi di PC ini)",
                                                "home_env_var": None, "home_target_set": True}]})

    async def update_check(request):
        from neovarch import updates
        return web.json_response(await updates.check(force=request.query.get("force") in ("1", "true"),
                                                     platform=str(request.query.get("platform") or "")))

    r.add_get("/api/update", update_check)

    async def pull_update_get(_):
        from neovarch import pull_update
        install = await asyncio.to_thread(pull_update.detect)
        return web.json_response({"install": install, "job": gw.pull_job,
                                  "last": await asyncio.to_thread(pull_update.read_state)})

    async def pull_update_post(request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        job = gw.pull_job
        if job and job.get("state") == "running":
            return web.json_response({"detail": "Pembaruan sedang berjalan", "code": "busy", "job": job}, status=409)
        job = gw.start_pull_update(restart=bool((body or {}).get("restart")),
                                   check_only=bool((body or {}).get("check_only")))
        return web.json_response({"job": job}, status=202)

    r.add_get("/api/update/pull", pull_update_get)
    r.add_post("/api/update/pull", pull_update_post)
    r.add_get("/api/cron/jobs", cron_list)
    r.add_post("/api/cron/jobs", cron_create)
    r.add_get("/api/cron/jobs/{jid}", cron_get)
    r.add_put("/api/cron/jobs/{jid}", cron_update)
    r.add_patch("/api/cron/jobs/{jid}", cron_update)
    r.add_delete("/api/cron/jobs/{jid}", cron_delete)
    r.add_post("/api/cron/jobs/{jid}/pause", _toggle(False))
    r.add_post("/api/cron/jobs/{jid}/resume", _toggle(True))
    r.add_post("/api/cron/jobs/{jid}/trigger", cron_trigger)
    r.add_get("/api/cron/jobs/{jid}/runs", cron_runs)
    r.add_get("/api/cron/delivery-targets", cron_targets)

    async def health(_):
        return web.json_response({"ok": True, "status": "ok", "product": "neovarch", "version": __version__})

    async def status(_):
        info = gw.model_info()
        return web.json_response({
            "ok": True, "product": PRODUCT, "name": "neovarch", "version": __version__,
            "release_date": "", "hermes_home": str(neovarch_home()), "home": str(neovarch_home()),
            "config_path": str(cfgmod.config_path()), "env_path": str(cfgmod.env_path()),
            "gateway_running": True, "gateway_state": "running", "active_sessions": len(gw.active_sessions()),
            "hostname": socket.gethostname(), "platform": platform.system().lower(),
            "uptime_s": round(time.time() - gw.started), "model": info["model"], "provider": info["provider"],
            "configured": info["configured"], "auth_mode": "token", "port": gw.port,
        })

    async def ws_handler(request: web.Request):
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024 * 1024)
        await ws.prepare(request)
        conn = Conn(ws)
        gw.conns.add(conn)
        await conn.send({"jsonrpc": "2.0", "method": "event", "params": {
            "type": "gateway.ready", "session_id": None,
            "payload": {"product": "neovarch", "version": __version__, "skin": None,
                        "boot_id": gw.bus.boot_id, "seq": gw.bus.seq,
                        # The desktop refreshes its chat list on sessions.changed only when this
                        # is set; without it chats made on the phone never appeared (1.4.5).
                        "change_events": True}}})
        # ?since=<seq>&boot_id=<id>: replay global events missed while offline
        # (session events come back through events.replay / session.resume).
        if "since" in request.query:
            try:
                since = int(request.query.get("since") or 0)
            except ValueError:
                since = 0
            rep = gw.bus.replay(since, request.query.get("boot_id") or None, [])
            if rep["resync"]:
                await conn.send({"jsonrpc": "2.0", "method": "event", "params": {
                    "type": "resync.required", "session_id": None,
                    "payload": {"reason": rep.get("reason"), "boot_id": rep["boot_id"], "seq": rep["seq"]}}})
            else:
                for ev in rep["events"]:
                    await conn.send({"jsonrpc": "2.0", "method": "event", "params": {
                        "type": ev["type"], "session_id": None, "payload": ev["payload"],
                        "seq": ev["seq"], "replayed": True}})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    frame = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if "method" not in frame and frame.get("id") in conn.pending:
                    fut = conn.pending.get(frame["id"])
                    if fut and not fut.done():
                        fut.set_result(frame.get("result") if "result" in frame else {"choice": "deny"})
                    continue
                asyncio.create_task(_dispatch(gw, conn, frame))
        finally:
            gw.conns.discard(conn)
        return ws

    async def sessions_list(request):
        limit = int(request.query.get("limit", 50))
        offset = int(request.query.get("offset", 0))
        items = gw.store.list(limit=limit, offset=offset)
        return web.json_response({"sessions": items, "total": len(gw.store.list(limit=100000)), "limit": limit, "offset": offset})

    async def session_get(request):
        rec = gw.store.find(request.match_info["sid"])
        if not rec:
            return web.json_response({"detail": "not found"}, status=404)
        return web.json_response({**summarize(rec), "messages": to_ui_messages(rec)})

    async def session_messages(request):
        rec = gw.store.find(request.match_info["sid"])
        if not rec:
            return web.json_response({"detail": "not found"}, status=404)
        return web.json_response({"session_id": rec["id"], "messages": to_ui_messages(rec)})

    def _int(q, key: str, default: int, lo: int = 0, hi: int = 10**9) -> int:
        try:
            return max(lo, min(int(q.get(key) or default), hi))
        except (TypeError, ValueError):
            return default

    async def session_timeline(request):
        """User prompts of a stored chat (the thread's jump marks), paged by row id."""
        rec = gw.store.find(request.match_info["sid"])
        if not rec:
            return web.json_response({"detail": "not found"}, status=404)
        after = _int(request.query, "after_row_id", 0)
        limit = _int(request.query, "limit", 500, 1, 2000)
        marks = [{"row_id": m["row_id"], "preview": " ".join(str(m["content"]).split())[:160],
                  "timestamp": m.get("timestamp")}
                 for m in to_ui_messages(rec) if m["role"] == "user" and m["row_id"] > after]
        page, more = marks[:limit], len(marks) > limit
        return web.json_response({"session_id": rec["id"], "entries": page,
                                  "pagination": {"next_cursor": page[-1]["row_id"] if page else None,
                                                 "has_more": more}})

    async def session_messages_around(request):
        """A bounded page of a stored chat centred on ``row_id``."""
        rec = gw.store.find(request.match_info["sid"])
        if not rec:
            return web.json_response({"detail": "not found"}, status=404)
        rows = to_ui_messages(rec)
        limit = _int(request.query, "limit", 120, 1, 500)
        row_id = _int(request.query, "row_id", 0)
        idx = next((i for i, m in enumerate(rows) if m["row_id"] >= row_id), max(len(rows) - 1, 0))
        start = max(0, min(idx - limit // 2, len(rows) - limit))
        page = rows[start:start + limit]
        return web.json_response({"session_id": rec["id"], "messages": page,
                                  "pagination": {"limit": limit, "offset": start, "returned": len(page),
                                                 "order": "oldest", "has_older": start > 0,
                                                 "has_newer": start + len(page) < len(rows)}})

    async def session_delete(request):
        ok = gw.store.delete(request.match_info["sid"])
        gw.live.pop(request.match_info["sid"], None)
        gw.broadcast_event("sessions.changed", None, {})
        return web.json_response({"ok": ok})

    async def session_patch(request):
        rec = gw.store.find(request.match_info["sid"])
        if not rec:
            return web.json_response({"detail": "not found"}, status=404)
        body = await _json(request)
        if "title" in body:
            rec["title"] = str(body["title"] or "")
            gw.store.save(rec)
        if "reasoning_effort" in body:  # the phone's "Penalaran" for this chat
            try:
                rec = gw.set_session_effort(rec["id"], body.get("reasoning_effort"))
            except ValueError as exc:
                return web.json_response({"detail": str(exc)}, status=422)
        return web.json_response({"ok": True, **summarize(rec),
                                  "reasoning_effort": session_settings.effective_effort(cfgmod.load_config(), rec)})

    async def config_get(_):
        return web.json_response(cfgmod.load_config())

    async def config_put(request):
        body = await _json(request)
        cfg = cfgmod.load_config()
        data = body.get("config", body)
        if isinstance(data, dict):
            cfg = cfgmod._merge(cfg, data)
            cfgmod.save_config(cfg)
            gw._config_changed()
        return web.json_response({"ok": True})

    async def config_defaults(_):
        return web.json_response(cfgmod.DEFAULTS)

    async def model_info(_):
        return web.json_response(gw.model_info())

    async def model_options(request):
        q = request.query
        return web.json_response(await gw.model_options({
            "include_unconfigured": q.get("include_unconfigured") in ("1", "true"),
            "refresh": q.get("refresh") in ("1", "true"), "session_id": q.get("session_id") or ""}))

    async def model_set(request):
        from neovarch import providers
        body = await _json(request)
        cfg = cfgmod.load_config()
        try:
            res = providers.set_model(cfg, body)
        except providers.EndpointError as exc:
            return web.json_response({"ok": False, "detail": str(exc), "message": str(exc)}, status=422)
        cfgmod.save_config(cfg)
        gw._default_changed(res)
        return web.json_response(res)

    async def model_recommended(request):
        from neovarch import providers
        prov = request.query.get("provider") or ""
        cfg = cfgmod.load_config()
        model = ""
        if prov in cfgmod.PRESETS:
            model = cfgmod.PRESETS[prov]["model"]
        elif prov.startswith("custom:"):
            spec = providers.find_endpoint(cfg, prov.split(":", 1)[1]) or {}
            model = str(spec.get("model") or (spec.get("models") or [""])[0])
        return web.json_response({"provider": prov, "model": model, "free_tier": None})

    async def model_auxiliary(_):
        info = gw.model_info()
        return web.json_response({"main": {"model": info["model"], "provider": info["provider"]}, "tasks": []})

    # ---- providers / custom endpoints --------------------------------------
    async def custom_endpoints_get(_):
        from neovarch import providers
        return web.json_response(providers.endpoints_response(cfgmod.load_config()))

    async def custom_endpoints_save(request):
        from neovarch import providers
        body = await _json(request)
        cfg = cfgmod.load_config()
        try:
            eid = providers.save_endpoint(cfg, body)
        except providers.EndpointError as exc:
            return web.json_response({"ok": False, "detail": str(exc), "message": str(exc)}, status=422)
        cfgmod.save_config(cfg)
        gw.broadcast_event("model.changed", None, {})
        return web.json_response(providers.endpoints_response(cfg, eid))

    async def custom_endpoints_validate(request):
        from neovarch import providers
        body = await _json(request)
        cfg = cfgmod.load_config()
        key = str(body.get("api_key") or "")
        headers_raw = body.get("headers")
        insecure = bool(body.get("allow_insecure_tls"))
        existing = providers.find_endpoint(cfg, providers.slugify(body.get("id") or body.get("name") or ""))
        if existing is not None:
            key = key or cfgmod.secret(str(existing.get("key_env") or ""))
            if headers_raw is None:
                headers_raw = cfgmod.endpoint_headers(existing)
        try:
            headers = providers.parse_headers(headers_raw)
        except providers.EndpointError as exc:
            return web.json_response({"ok": False, "reachable": False, "message": str(exc), "models": []})
        res = await providers.probe(str(body.get("base_url") or ""), key, headers, insecure)
        if existing is not None and res.get("ok") and res.get("models") and existing.get("discover_models", True):
            # A successful probe of a saved endpoint prunes ids it no longer serves.
            res["pruned"] = providers.apply_discovered(existing, res["models"])
            cfgmod.save_config(cfg)
        return web.json_response(res)

    async def custom_endpoint_delete(request):
        from neovarch import providers
        cfg = cfgmod.load_config()
        providers.delete_endpoint(cfg, request.match_info["eid"])
        cfgmod.save_config(cfg)
        return web.json_response(providers.endpoints_response(cfg))

    async def custom_endpoint_activate(request):
        from neovarch import providers
        cfg = cfgmod.load_config()
        spec = providers.find_endpoint(cfg, request.match_info["eid"])
        if spec is None:
            return web.json_response({"ok": False, "detail": "endpoint tidak ditemukan"}, status=404)
        providers.activate(cfg, f"custom:{request.match_info['eid']}", str(spec.get("model") or ""))
        cfgmod.save_config(cfg)
        gw.broadcast_event("model.changed", None, {})
        return web.json_response({"ok": True, "provider": f"custom:{request.match_info['eid']}",
                                  "model": str(spec.get("model") or "")})

    async def providers_validate(request):
        from neovarch import providers
        body = await _json(request)
        key, value = str(body.get("key") or ""), str(body.get("value") or "")
        slug = providers.preset_for_env(key)
        if not slug:
            return web.json_response({"ok": True, "reachable": False, "message": "Disimpan tanpa uji koneksi."})
        if not value:
            return web.json_response({"ok": False, "reachable": False, "message": "API key kosong."})
        return web.json_response(await providers.probe(cfgmod.PRESETS[slug]["base_url"], value))

    async def env_get(_):
        from neovarch import providers
        return web.json_response(providers.env_vars())

    async def env_put(request):
        body = await _json(request)
        key = str(body.get("key") or "")
        if not key or not key.replace("_", "").isalnum():
            return web.json_response({"ok": False, "detail": "nama variabel tidak valid"}, status=422)
        cfgmod.write_env_value(key, str(body.get("value") or ""))
        gw.broadcast_event("model.changed", None, {})
        return web.json_response({"ok": True})

    async def env_delete(request):
        body = await _json(request)
        key = str(body.get("key") or request.query.get("key") or "")
        if key:
            cfgmod.write_env_value(key, "")
        return web.json_response({"ok": True})

    async def env_reveal(request):
        body = await _json(request)
        key = str(body.get("key") or "")
        return web.json_response({"key": key, "value": cfgmod.read_env_file().get(key, "")})

    async def config_schema(_):
        return web.json_response(config_schema_payload())

    async def skills(_):
        # The renderer expects SkillInfo[]
        return web.json_response([{"name": s["name"], "description": s["description"], "category": "neovarch",
                                   "enabled": s["enabled"], "provenance": "agent", "path": s["path"]}
                                  for s in list_skills(include_disabled=True)])

    async def skill_content(request):
        name = request.query.get("name") or ""
        for s in list_skills():
            if s["name"] == name:
                return web.json_response({"name": name, "path": s["path"],
                                          "content": Path(s["path"]).read_text(encoding="utf-8", errors="replace")})
        return web.json_response({"name": name, "path": "", "content": ""})

    async def tools(_):
        # The renderer expects ToolsetInfo[]
        return web.json_response([{"name": "core", "label": "Neovarch core", "description": "Shell, file, web, memori, skill",
                                   "enabled": True, "configured": True,
                                   "tools": [t["function"]["name"] for t in tool_schemas()]}])

    async def profiles(_):
        info = gw.model_info()
        return web.json_response({"profiles": [{"name": "default", "display_name": "Neovarch", "active": True,
                                                "is_default": True, "has_env": cfgmod.env_path().exists(),
                                                "model": info["model"] or None, "provider": info["provider"] or None,
                                                "skill_count": len(list_skills()), "path": str(neovarch_home())}],
                                  "active": "default"})

    async def sessions_search(request):
        q = (request.query.get("q") or "").strip().lower()
        results = []
        if q:
            for summary in gw.store.list(limit=500):
                rec = gw.store.load(summary["id"]) or {}
                for m in rec.get("messages", []):
                    text = m.get("content") if isinstance(m.get("content"), str) else ""
                    if text and q in text.lower():
                        i = text.lower().index(q)
                        results.append({**summary, "session_id": summary["id"], "snippet": text[max(0, i - 60):i + 100],
                                        "role": m.get("role")})
                        break
                if len(results) >= 50:
                    break
        return web.json_response({"results": results})

    async def sessions_sidebar(request):
        try:
            limit = int(request.query.get("recents_limit") or request.query.get("recentsLimit") or 50)
        except ValueError:
            limit = 50
        empty = {"sessions": []}
        return web.json_response({"recents": {"sessions": gw.store.list(limit=limit)}, "cron": empty, "messaging": empty})

    async def empty_list(request):
        key = request.path.rstrip("/").rsplit("/", 1)[-1]
        return web.json_response({key: [], "items": []})

    async def kanban_board(_):
        return web.json_response(gw.kanban.board())

    async def kanban_boards(_):
        total = len(gw.kanban.board()["tasks"])
        return web.json_response({"current": "default", "boards": [{"slug": "default", "name": "Tugas", "is_current": True,
                                                                   "total": total, "description": None}]})

    async def kanban_task_get(request):
        d = gw.kanban.detail(request.match_info["tid"])
        return web.json_response(d) if d else web.json_response({"detail": "tugas tidak ditemukan"}, status=404)

    async def kanban_task_delete(request):
        return web.json_response({"ok": gw.kanban.delete(request.match_info["tid"])})

    async def kanban_task_log(_):
        return web.json_response({"exists": False, "size_bytes": 0, "content": "", "truncated": False})

    async def kanban_bulk(request):
        b = await _json(request)
        results = []
        for tid in b.get("ids") or []:
            ok = bool(gw.kanban.update(str(tid), {k: v for k, v in b.items() if k in ("status", "assignee", "priority")}))
            results.append({"id": tid, "ok": ok})
        return web.json_response({"results": results})

    async def kanban_profiles(_):
        return web.json_response({"profiles": [{"name": "default", "is_default": True, "description": "Agen Neovarch",
                                                "description_auto": False}]})

    async def kanban_projects(_):
        return web.json_response({"projects": []})

    async def kanban_orchestration(_):
        return web.json_response({"orchestrator_profile": "", "default_assignee": "", "auto_decompose": False,
                                  "resolved_orchestrator_profile": "default", "resolved_default_assignee": "default"})

    async def kanban_events(request):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(request)
        try:
            since = int(request.query.get("since") or 0)
        except ValueError:
            since = 0
        try:
            first = True
            while not ws.closed:
                evs, cursor = gw.kanban.events_since(since)
                if evs or first:
                    await ws.send_json({"cursor": cursor, "events": evs})
                    since, first = max(since, cursor), False
                await asyncio.sleep(0.5)
        except (ConnectionResetError, RuntimeError, asyncio.CancelledError):
            pass
        return ws

    async def kanban_create(request):
        b = await _json(request)
        if not b.get("title"):
            return web.json_response({"detail": "title required"}, status=422)
        task = gw.kanban.create(str(b["title"]), str(b.get("body") or ""), b.get("assignee"), b.get("priority"))
        gw.office.observe("task.created", None, task)
        return web.json_response({**task, "task": task})

    async def kanban_patch(request):
        tid = request.match_info["tid"]
        before = next((t for t in gw.kanban.board()["tasks"] if t["id"] == tid), None)
        t = gw.kanban.update(tid, await _json(request))
        if t:
            if before and before.get("status") != t.get("status"):
                gw.office.observe("task.moved", None, {**t, "from": before.get("status"), "to": t.get("status")})
            else:
                gw.office.observe("task.updated", None, t)
        return web.json_response(t) if t else web.json_response({"detail": "not found"}, status=404)

    async def kanban_comment(request):
        b = await _json(request)
        c = gw.kanban.comment(request.match_info["tid"], str(b.get("body") or ""))
        return web.json_response(c) if c else web.json_response({"detail": "not found"}, status=404)

    async def fs_list(request):
        p = Path(os.path.expanduser(request.query.get("path") or str(default_cwd())))
        try:
            entries = [{"name": e.name, "path": str(e), "is_dir": e.is_dir(), "type": "dir" if e.is_dir() else "file"}
                       for e in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:2000]]
        except OSError as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        return web.json_response({"path": str(p), "entries": entries})

    async def fs_read(request):
        p = Path(os.path.expanduser(request.query.get("path") or ""))
        try:
            return web.json_response({"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")[:2_000_000]})
        except OSError as exc:
            return web.json_response({"detail": str(exc)}, status=400)

    async def fs_default(_):
        return web.json_response({"path": str(default_cwd())})

    async def office_get(_):
        return web.json_response(gw.office.snapshot())

    async def office_events(request):
        """Server-Sent Events: one `office.update` per change (plus the current snapshot first)."""
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no", **_cors(request)})
        await resp.prepare(request)
        q = gw.office.subscribe()
        try:
            snap = gw.office.snapshot()
            while True:
                data = json.dumps(snap, ensure_ascii=False, default=str)
                await resp.write(f"event: office.update\ndata: {data}\n\n".encode())
                while True:
                    try:
                        snap = await asyncio.wait_for(q.get(), 25)
                        break
                    except asyncio.TimeoutError:
                        await resp.write(b": keep-alive\n\n")
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            gw.office.unsubscribe(q)
        return resp

    async def events_sse(request):
        """Server-Sent Events: every gateway event with `id: <seq>`; resumes from
        Last-Event-ID / ?since=; `event: resync` when the gap cannot be replayed."""
        types = {t for t in (request.query.get("types") or "").split(",") if t}
        sessions = {t for t in (request.query.get("session") or "").split(",") if t}

        def wanted(ev: dict) -> bool:
            if types and not any(ev["type"] == t or ev["type"].startswith(t.rstrip("*")) for t in types):
                return False
            return not sessions or ev["session_id"] is None or ev["session_id"] in sessions

        def frame(ev: dict) -> bytes:
            body = json.dumps({"type": ev["type"], "session_id": ev["session_id"], "payload": ev["payload"],
                               "seq": ev["seq"]}, ensure_ascii=False, default=str)
            return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {body}\n\n".encode()

        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no", **_cors(request)})
        await resp.prepare(request)
        q = gw.bus.subscribe()
        try:
            hello = {"boot_id": gw.bus.boot_id, "seq": gw.bus.seq, "version": __version__}
            await resp.write(f"retry: 1000\nevent: hello\ndata: {json.dumps(hello)}\n\n".encode())
            last = request.headers.get("Last-Event-ID") or request.query.get("since")
            if last not in (None, ""):
                try:
                    since = int(str(last))
                except ValueError:
                    since = -1
                rep = gw.bus.replay(since, request.query.get("boot_id") or None) if since >= 0 else {"resync": True}
                if rep["resync"]:
                    await resp.write(f"event: resync\ndata: {json.dumps({'reason': rep.get('reason', 'bad-cursor'), 'seq': gw.bus.seq, 'boot_id': gw.bus.boot_id})}\n\n".encode())
                else:
                    for ev in rep["events"]:
                        if wanted(ev):
                            await resp.write(frame(ev))
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    await resp.write(b": keep-alive\n\n")
                    continue
                if ev.get("type") == "resync" and "seq" not in ev:
                    await resp.write(f"event: resync\ndata: {json.dumps({'reason': ev.get('reason'), 'seq': gw.bus.seq, 'boot_id': gw.bus.boot_id})}\n\n".encode())
                elif wanted(ev):
                    await resp.write(frame(ev))
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        finally:
            gw.bus.unsubscribe(q)
        return resp

    async def events_replay(request):
        try:
            since = int(request.query.get("since") or 0)
        except ValueError:
            since = 0
        sessions = [t for t in (request.query.get("session") or "").split(",") if t] or None
        return web.json_response(gw.bus.replay(since, request.query.get("boot_id") or None, sessions), dumps=lambda o: json.dumps(o, default=str))

    async def network_addresses(_):
        return web.json_response(await asyncio.to_thread(netinfo.addresses, gw.port))

    async def obsidian_status(_):
        from neovarch import obsidian
        return web.json_response(obsidian.status())

    async def obsidian_configure(request):
        from neovarch import obsidian
        body = await _json(request)
        try:
            res = obsidian.configure(str(body.get("path") or ""), body.get("enabled", True) is not False)
        except obsidian.VaultError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **res})

    async def appearance_get(_):
        return web.json_response(appearance_of(cfgmod.load_config()))

    async def appearance_put(request):
        body = await _json(request)
        cfg = cfgmod.load_config()
        try:
            new = normalize_appearance({**appearance_of(cfg), **{k: v for k, v in body.items() if k in ("accent", "base")}})
        except ValueError as exc:
            return web.json_response({"detail": str(exc)}, status=422)
        cfgmod.set_path(cfg, "appearance", {"accent": new["accent"], "base": new["base"]})
        cfgmod.save_config(cfg)
        gw._config_changed("appearance")
        return web.json_response(new)

    # ---- chat attachments + binary downloads ---------------------------------
    async def upload_post(request):
        """multipart/form-data: field `file` (+ optional `session_id`); or a raw body with
        ?filename=&session_id= and Content-Type. Max 25 MB. Returns the stored upload."""
        sid = request.query.get("session_id") or ""
        try:
            if request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                meta = None
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "session_id" and not part.filename:
                        sid = (await part.text()).strip()
                        continue
                    if part.filename is None:
                        await part.release()
                        continue
                    w = gw.uploads.writer(sid, part.filename, part.headers.get("Content-Type"))
                    head = b""
                    while True:
                        chunk = await part.read_chunk(256 * 1024)
                        if not chunk:
                            break
                        head = head or chunk[:16]
                        w.write(chunk)
                    meta = w.finish(head=head)
                    break
                if meta is None:
                    return web.json_response({"detail": "field `file` wajib ada"}, status=400)
            else:
                if request.content_length and request.content_length > upmod.MAX_BYTES:
                    return web.json_response({"detail": "File terlalu besar (maks 25 MB)."}, status=413)
                w = gw.uploads.writer(sid, request.query.get("filename") or "file", request.content_type)
                head = b""
                async for chunk in request.content.iter_chunked(256 * 1024):
                    head = head or chunk[:16]
                    w.write(chunk)
                meta = w.finish(head=head)
        except upmod.UploadError as exc:
            return web.json_response({"detail": str(exc)}, status=exc.status)
        gw.broadcast_event("attachment.uploaded", sid or None, upmod.public(meta))
        return web.json_response(upmod.public(meta))

    def _file_response(path: Path, name: str, mime: str | None, download: bool) -> web.StreamResponse:
        disp = "attachment" if download else "inline"
        quoted = name.replace('"', "")
        return web.FileResponse(path, headers={
            "Content-Type": mime or "application/octet-stream",
            "Content-Disposition": f'{disp}; filename="{quoted}"',
            "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    async def upload_get(request):
        meta = gw.uploads.get(request.match_info["uid"])
        if not meta:
            return web.json_response({"detail": "lampiran tidak ditemukan"}, status=404)
        return _file_response(Path(meta["path"]), meta["name"], meta["mime"], request.query.get("download") in ("1", "true"))

    async def upload_meta(request):
        meta = gw.uploads.get(request.match_info["uid"])
        return web.json_response(upmod.public(meta)) if meta else web.json_response({"detail": "lampiran tidak ditemukan"}, status=404)

    async def upload_delete(request):
        return web.json_response({"ok": gw.uploads.delete(request.match_info["uid"])})

    async def uploads_list(request):
        return web.json_response({"attachments": [upmod.public(m) for m in gw.uploads.list(request.query.get("session_id") or "")]})

    async def fs_download(request):
        """Binary download of any readable file (reports, artifacts, attachments)."""
        p = Path(os.path.expanduser(request.query.get("path") or ""))
        if not p.is_file():
            return web.json_response({"detail": f"file tidak ditemukan: {p}"}, status=404)
        import mimetypes
        return _file_response(p, p.name, mimetypes.guess_type(p.name)[0], request.query.get("inline") not in ("1", "true"))

    r.add_post("/api/uploads", upload_post)
    r.add_get("/api/uploads", uploads_list)
    r.add_get("/api/uploads/{uid}", upload_get)
    r.add_get("/api/uploads/{uid}/meta", upload_meta)
    r.add_delete("/api/uploads/{uid}", upload_delete)
    r.add_get("/api/fs/download", fs_download)
    gw.social.install_routes(r)

    # ---- 9Router + models (contract: docs/9router.md) ------------------------
    def _bad(exc: Exception, code: int = 400):
        return web.json_response({"ok": False, "error": str(exc), "detail": str(exc)}, status=code)

    async def router_status_h(_):
        return web.json_response(await gw.router_status())

    async def router_start_h(_):
        st = await gw.router.start()
        if st["state"] == "not_installed":
            return web.json_response({**st, "ok": False, "error": st["setup"]["message"]}, status=409)
        return web.json_response(st)

    async def router_stop_h(_):
        if not gw.router.status()["managed"]:
            st = gw.router.status()
            return web.json_response({**st, "ok": False,
                                      "error": "9Router ini tidak dijalankan oleh Neovarch, jadi tidak dihentikan."},
                                     status=409)
        return web.json_response(await gw.router.stop())

    async def router_config_h(request):
        try:
            return web.json_response(await gw.router_config(await _json(request)))
        except ValueError as exc:
            return _bad(exc)

    async def router_provision_h(_):
        await gw.router.provision()
        gw.router._last_sig = None
        return web.json_response(await gw.router_status())

    async def models_list_h(request):
        return web.json_response(await gw.models_payload(request.query.get("refresh") in ("1", "true")))

    async def models_default_get_h(_):
        return web.json_response(modelsmod.default_ref(cfgmod.load_config()))

    async def models_default_put_h(request):
        body = await _json(request)
        try:
            return web.json_response(gw.set_default_model(str(body.get("model") or ""), body.get("provider")))
        except (modelsmod.ModelError, ValueError) as exc:
            return _bad(exc)

    async def agents_models_h(_):
        cfg = cfgmod.load_config()
        ref = modelsmod.default_ref(cfg)
        return web.json_response({"default": {"model": ref["model"], "provider": ref["provider"]},
                                  "agents": {aid: modelsmod.agent_model(cfg, aid) for aid in modelsmod.overrides(cfg)}})

    async def agent_model_get_h(request):
        try:
            return web.json_response(modelsmod.agent_model(cfgmod.load_config(), request.match_info["aid"]))
        except modelsmod.ModelError as exc:
            return _bad(exc)

    async def agent_model_put_h(request):
        aid = request.match_info["aid"]
        if aid.startswith("company:") or aid == "pc":
            # A Perusahaan desk (that agent's own model) / the PC desk (the default model).
            return await agent_model_put(request)
        body = await _json(request)
        if "model" not in body:
            return _bad(ValueError("model wajib ada (null untuk kembali ke model global)"))
        if isinstance(body.get("model"), str) and not body["model"].strip():
            return web.json_response({"ok": False, "detail": "model wajib diisi (null untuk kembali ke model global)"},
                                     status=422)
        sid = aid.split(":", 1)[1] if aid.startswith("session:") else ""
        if sid and not (sid in gw.live or gw.store.find(sid)):
            return web.json_response({"ok": False, "detail": f"agen tidak ditemukan: {aid}"}, status=404)
        try:
            res = gw.set_agent_model(aid, body.get("model"), body.get("provider"))
        except modelsmod.ModelError as exc:
            return _bad(exc)
        # A chat desk's pick is that agent's only (never the PC default).
        return web.json_response({**res, "scope": "session" if res.get("source") == "agent" else "default"})

    async def agent_model_delete_h(request):
        try:
            return web.json_response(gw.set_agent_model(request.match_info["aid"], None, None))
        except modelsmod.ModelError as exc:
            return _bad(exc)

    r.add_get("/api/router/status", router_status_h)
    r.add_post("/api/router/start", router_start_h)
    r.add_post("/api/router/stop", router_stop_h)
    r.add_put("/api/router/config", router_config_h)
    r.add_post("/api/router/config", router_config_h)
    r.add_post("/api/router/provision", router_provision_h)
    r.add_get("/api/models", models_list_h)
    r.add_get("/api/models/default", models_default_get_h)
    r.add_put("/api/models/default", models_default_put_h)
    r.add_get("/api/agents/models", agents_models_h)
    r.add_get("/api/agents/{aid}/model", agent_model_get_h)
    r.add_put("/api/agents/{aid}/model", agent_model_put_h)
    r.add_delete("/api/agents/{aid}/model", agent_model_delete_h)

    r.add_get("/api/office", office_get)

    async def company_get(_):
        return web.json_response(await gw.company.call("company.snapshot", {}))

    async def company_post(request):
        try:
            body = await request.json() if request.can_read_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            return web.json_response(await gw.company.call("company." + request.match_info["method"],
                                                           body if isinstance(body, dict) else {}))
        except CompanyError as exc:
            return web.json_response({"error": str(exc), "code": exc.code, **exc.data},
                                     status=COMPANY_HTTP.get(exc.code, 400))

    async def crew_get(_):
        return web.json_response({**(await gw.crew.call("crew.list", {})),
                                  **(await gw.crew.call("crew.templates", {}))})

    async def crew_post(request):
        try:
            body = await request.json() if request.can_read_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            return web.json_response(await gw.crew.call("crew." + request.match_info["method"],
                                                        body if isinstance(body, dict) else {}))
        except CrewError as exc:
            return web.json_response({"error": str(exc), "code": exc.code}, status=CREW_HTTP.get(exc.code, 400))

    r.add_get("/api/crew", crew_get)
    r.add_post("/api/crew/{method:[a-z_.]+}", crew_post)
    r.add_get("/api/company", company_get)
    r.add_post("/api/company/{method:[a-z_.]+}", company_post)
    r.add_get("/api/office/events", office_events)
    r.add_get("/api/events", events_sse)
    r.add_get("/api/events/replay", events_replay)
    r.add_get("/api/network/addresses", network_addresses)

    async def usage_get(request):
        from neovarch import usage_stats
        sid = request.query.get("session") or ""
        rec = None
        if sid:
            try:
                rec = gw.store.load(sid)
            except Exception:
                rec = None
        return web.json_response(await asyncio.to_thread(usage_stats.summary, session=rec))

    r.add_get("/api/usage", usage_get)

    async def pamerkan_get(request):
        # Pamerkan card radar/bar/donut/trend: local sessions + usage.json only (pamerkan.py).
        from neovarch import pamerkan
        try:
            days = int(request.query.get("days") or pamerkan.DEFAULT_DAYS)
        except ValueError:
            days = pamerkan.DEFAULT_DAYS
        return web.json_response(await asyncio.to_thread(pamerkan.cached, days))

    r.add_get("/api/pamerkan", pamerkan_get)
    _add_remote_link_routes(app, gw)
    from neovarch.background import add_routes as _add_background_routes
    _add_background_routes(app, gw)
    r.add_get("/api/memory/obsidian", obsidian_status)
    r.add_post("/api/memory/obsidian", obsidian_configure)
    r.add_put("/api/memory/obsidian", obsidian_configure)

    # ---- Obsidian vault viewer (desktop page, phone read-only) ---------------
    def _vault_or_error():
        from neovarch import obsidian
        try:
            return obsidian.require_vault(), None
        except obsidian.VaultError as exc:
            return None, str(exc)

    async def vault_tree(_):
        from neovarch import obsidian
        vault, err = _vault_or_error()
        if err:
            return web.json_response({"configured": False, "tree": None, "detail": err})
        from neovarch import vault_sync
        return web.json_response({"configured": True, "vault": vault.name, "path": str(vault), "tree": obsidian.tree(vault),
                                  "open_uri": vault_sync.vault_uri(vault)})

    async def vault_note(request):
        from neovarch import obsidian
        vault, err = _vault_or_error()
        if err:
            return web.json_response({"detail": err}, status=409)
        rel = request.query.get("path") or ""
        try:
            note = obsidian.read_note(vault, rel)
            lk = obsidian.links(vault, note["path"])
        except obsidian.VaultError as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        except FileNotFoundError:
            return web.json_response({"detail": f"Catatan {rel} tidak ditemukan."}, status=404)
        # outgoing links resolved to note paths so the viewer can make them clickable
        g = {n["title"].lower(): n["id"] for n in obsidian.graph(vault)["nodes"] if n["exists"]}
        out = [{"target": t, "path": g.get(t.rsplit("/", 1)[-1].lower())} for t in lk["outgoing"]]
        return web.json_response({**note, "backlinks": lk["backlinks"], "outgoing": out,
                                  "open_uri": obsidian.open_uri(vault, note["path"])})

    async def vault_graph(_):
        from neovarch import obsidian
        vault, err = _vault_or_error()
        if err:
            return web.json_response({"configured": False, "nodes": [], "edges": []})
        return web.json_response({"configured": True, **obsidian.graph(vault)})

    async def vault_search(request):
        from neovarch import obsidian
        vault, err = _vault_or_error()
        if err:
            return web.json_response({"results": []})
        q = request.query.get("q") or ""
        return web.json_response({"results": obsidian.search(vault, q, 30) if q.strip() else []})

    async def vault_init(request):
        """Settings ▸ Vault Obsidian ▸ Siapkan vault: create/link the vault, zip backup, .obsidian,
        agent memory + past chats as notes. Non-destructive (only adds files)."""
        from neovarch import obsidian, vault_sync
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            res = await asyncio.to_thread(vault_sync.init, str((body or {}).get("path") or "") or None)
        except (obsidian.VaultError, OSError) as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        gw.broadcast_event("vault.changed", None, {"init": True})
        return web.json_response(res)

    async def vault_sync_now(_):
        from neovarch import obsidian, vault_sync
        vault, err = _vault_or_error()
        if err:
            return web.json_response({"detail": err}, status=409)
        try:
            res = await asyncio.to_thread(vault_sync.migrate, vault)
        except (obsidian.VaultError, OSError) as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        gw.broadcast_event("vault.changed", None, {"sync": True})
        return web.json_response(res)

    # ---- optional extras (Obsidian): status, install with progress ------------
    async def extras_status(_):
        from neovarch import extras
        st = await asyncio.to_thread(extras.status_all)
        return web.json_response({"extras": st, "job": gw.extras_job})

    async def extras_install(request):
        from neovarch import extras
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = str((body or {}).get("name") or "obsidian")
        if name not in extras.REGISTRY:
            return web.json_response({"detail": f"unknown extra {name}"}, status=400)
        job = gw.extras_job
        if job and job.get("state") == "running":
            return web.json_response({"job": job}, status=202)
        gw.start_extras_job(name)
        return web.json_response({"job": gw.extras_job}, status=202)

    async def extras_open(request):
        """Open an obsidian:// link on this PC (the desktop's "Buka di Obsidian")."""
        from neovarch import extras
        try:
            body = await request.json()
        except Exception:
            body = {}
        uri = str((body or {}).get("uri") or "")
        if not uri.startswith("obsidian://"):
            return web.json_response({"detail": "only obsidian:// links"}, status=400)
        found = await asyncio.to_thread(extras.detect, "obsidian")
        if not found["installed"]:
            return web.json_response({"opened": False, "installed": False, "extra": found}, status=409)
        return web.json_response({"opened": await asyncio.to_thread(extras.open_uri, uri), "installed": True})

    r.add_get("/api/extras", extras_status)
    r.add_post("/api/extras/install", extras_install)
    r.add_post("/api/extras/open", extras_open)
    r.add_post("/api/obsidian/init", vault_init)
    r.add_post("/api/obsidian/sync", vault_sync_now)
    r.add_get("/api/obsidian/tree", vault_tree)
    r.add_get("/api/obsidian/note", vault_note)
    r.add_get("/api/obsidian/graph", vault_graph)
    r.add_get("/api/obsidian/search", vault_search)
    async def account_get(_):
        from neovarch import account
        return web.json_response(await account.status())

    async def account_connect(request):
        from neovarch import account
        res = await account.connect(str((await _json(request)).get("token") or ""))
        return web.json_response(res)

    async def account_disconnect(_):
        from neovarch import account
        return web.json_response(account.disconnect())

    async def logs_get(request):
        from neovarch import logs as logmod
        return web.json_response(logmod.read(request.query))

    from neovarch import skills_admin

    async def skills_toggle(request):
        body = await _json(request)
        return web.json_response(skills_admin.set_enabled(str(body.get("name") or ""), bool(body.get("enabled"))))

    async def learning_node_get(request):
        return web.json_response(skills_admin.node(request.query.get("id") or ""))

    async def learning_node_put(request):
        body = await _json(request)
        return web.json_response(skills_admin.edit(str(body.get("id") or ""), str(body.get("content") or "")))

    async def learning_node_delete(request):
        return web.json_response(skills_admin.archive(str((await _json(request)).get("id") or "")))

    async def memory_get(_):
        return web.json_response(skills_admin.memory_status())

    async def memory_reset(request):
        return web.json_response(skills_admin.memory_reset(str((await _json(request)).get("target") or "all")))

    async def agent_model_put(request):
        """Kantor popover: switch one desk's model. A chat desk
        (``session:<id>``) gets a chat-only pick; any other desk (the PC
        itself) changes the default model."""
        body = await _json(request)
        model, provider = str(body.get("model") or "").strip(), str(body.get("provider") or "").strip()
        if not model:
            return web.json_response({"ok": False, "detail": "model wajib diisi"}, status=422)
        aid = request.match_info["aid"]
        if aid.startswith("company:"):
            # A Perusahaan desk: the pick belongs to that agent (never the PC default).
            try:
                a = await gw.company.call("company.agent.save", {"id": int(aid.split(":", 1)[1] or 0),
                                                                 "model": model, "provider": provider})
            except (CompanyError, ValueError) as exc:
                code = getattr(exc, "code", "invalid")
                return web.json_response({"ok": False, "detail": str(exc)}, status=404 if code == "not_found" else 422)
            gw.office.schedule()
            return web.json_response({"ok": True, "model": a["model"], "provider": a.get("provider") or "",
                                      "scope": "agent", "agent_id": aid})
        sid = aid.split(":", 1)[1] if aid.startswith("session:") else ""
        if sid and not (sid in gw.live or gw.store.find(sid)):
            return web.json_response({"ok": False, "detail": f"agen tidak ditemukan: {aid}"}, status=404)
        value = model + (f" --provider {provider}" if provider else "") + (" --session" if sid else " --global")
        try:
            res = gw._config_set({"session_id": sid, "key": "model", "value": value})
        except RpcError as exc:
            return web.json_response({"ok": False, "detail": exc.message}, status=422)
        gw.office.schedule()
        return web.json_response({**res, "agent_id": aid})

    r.add_put("/api/skills/toggle", skills_toggle)
    r.add_get("/api/learning/node", learning_node_get)
    r.add_put("/api/learning/node", learning_node_put)
    r.add_delete("/api/learning/node", learning_node_delete)
    r.add_get("/api/memory", memory_get)
    r.add_post("/api/memory/reset", memory_reset)
    r.add_get("/api/logs", logs_get)

    # ---- self-repair: change log, undo, diagnosis (docs/self-repair.md) --------
    async def self_changes(request):
        from neovarch import selfedit
        return web.json_response({"changes": selfedit.entries(int(request.query.get("limit") or 50))})

    async def self_undo(request):
        from neovarch import selfedit
        body = await _json(request)
        return web.json_response(selfedit.undo(body.get("change_id") or None, session_id=str(body.get("session_id") or "")))

    async def self_diagnose(request):
        from neovarch import diagnose
        body = await _json(request) if request.method == "POST" else {}
        res = await asyncio.to_thread(diagnose.run, gw.store, str(body.get("session_id") or ""),
                                      request.method == "POST" and body.get("apply", True) is not False)
        return web.json_response({"report": res["report"], "findings": res["findings"], "applied": res["applied"]})

    async def composer_catalog(request):
        return web.json_response(gw.composer_catalog(request.query.get("session_id") or ""))

    r.add_get("/api/composer/catalog", composer_catalog)
    r.add_get("/api/self/changes", self_changes)
    r.add_post("/api/self/undo", self_undo)
    r.add_get("/api/self/diagnose", self_diagnose)
    r.add_post("/api/self/diagnose", self_diagnose)
    r.add_get("/api/account/github", account_get)
    r.add_post("/api/account/github", account_connect)
    r.add_delete("/api/account/github", account_disconnect)
    r.add_get("/api/appearance", appearance_get)
    r.add_put("/api/appearance", appearance_put)
    r.add_post("/api/appearance", appearance_put)
    r.add_get("/api/health", health)
    r.add_get("/api/health/idle", health)
    r.add_get("/api/status", status)
    r.add_get("/api/ws", ws_handler)
    r.add_get("/api/sessions", sessions_list)
    r.add_get("/api/profiles/sessions", sessions_list)
    r.add_get("/api/sessions/{sid}", session_get)
    r.add_get("/api/sessions/{sid}/messages", session_messages)
    r.add_get("/api/sessions/{sid}/messages/around", session_messages_around)
    r.add_get("/api/sessions/{sid}/timeline", session_timeline)
    r.add_delete("/api/sessions/{sid}", session_delete)
    r.add_patch("/api/sessions/{sid}", session_patch)
    r.add_get("/api/config", config_get)
    r.add_put("/api/config", config_put)
    r.add_post("/api/config", config_put)
    r.add_get("/api/config/defaults", config_defaults)
    r.add_get("/api/model/info", model_info)
    r.add_get("/api/model/options", model_options)
    r.add_post("/api/model/set", model_set)
    r.add_get("/api/model/recommended-default", model_recommended)
    r.add_get("/api/model/auxiliary", model_auxiliary)
    r.add_get("/api/config/schema", config_schema)
    r.add_get("/api/providers/custom-endpoints", custom_endpoints_get)
    r.add_post("/api/providers/custom-endpoints", custom_endpoints_save)
    r.add_post("/api/providers/custom-endpoints/validate", custom_endpoints_validate)
    r.add_post("/api/providers/custom-endpoints/{eid}/activate", custom_endpoint_activate)
    r.add_delete("/api/providers/custom-endpoints/{eid}", custom_endpoint_delete)
    r.add_post("/api/providers/validate", providers_validate)
    r.add_get("/api/env", env_get)
    r.add_put("/api/env", env_put)
    r.add_post("/api/env", env_put)
    r.add_delete("/api/env", env_delete)
    r.add_post("/api/env/reveal", env_reveal)
    r.add_get("/api/skills", skills)
    r.add_get("/api/skills/content", skill_content)
    r.add_get("/api/sessions/search", sessions_search)
    r.add_get("/api/profiles/sessions/sidebar", sessions_sidebar)
    r.add_get("/api/tools/toolsets", tools)
    r.add_get("/api/profiles", profiles)
    async def cron_jobs(_):
        return web.json_response([])

    r.add_get("/api/cron/jobs", cron_jobs)
    r.add_get("/api/plugins/kanban/board", kanban_board)
    r.add_get("/api/plugins/kanban/boards", kanban_boards)
    r.add_get("/api/plugins/kanban/profiles", kanban_profiles)
    r.add_get("/api/plugins/kanban/projects", kanban_projects)
    r.add_get("/api/plugins/kanban/orchestration", kanban_orchestration)
    r.add_put("/api/plugins/kanban/orchestration", kanban_orchestration)
    r.add_get("/api/plugins/kanban/events", kanban_events)
    r.add_post("/api/plugins/kanban/tasks/bulk", kanban_bulk)
    r.add_get("/api/plugins/kanban/tasks/{tid}", kanban_task_get)
    r.add_delete("/api/plugins/kanban/tasks/{tid}", kanban_task_delete)
    r.add_get("/api/plugins/kanban/tasks/{tid}/log", kanban_task_log)
    r.add_post("/api/plugins/kanban/tasks", kanban_create)
    r.add_patch("/api/plugins/kanban/tasks/{tid}", kanban_patch)
    r.add_post("/api/plugins/kanban/tasks/{tid}/comments", kanban_comment)
    # Boot-time REST reads for features the core does not have: valid "off" answers.
    async def profiles_active(_):
        return web.json_response({"active": "default", "current": "default"})

    async def local_models_status(_):
        return web.json_response({"enabled": False, "tag": "", "configured_tag": "", "update_available": False,
                                  "runtime_installed": False, "runtime_backend": None, "server_running": False,
                                  "server_base_url": None, "active_model_id": None, "loaded_models": {},
                                  "models": [], "models_dir": ""})

    async def local_models_jobs(_):
        return web.json_response({"jobs": []})

    async def voice_live_status(_):
        return web.json_response({"ok": False, "available": False, "reason": "Not available in the Neovarch core."})

    async def audio_stt_status(_):
        from neovarch import stt
        return web.json_response(await asyncio.to_thread(stt.status))

    async def audio_transcribe(request):
        # Local, free STT (faster-whisper / whisper.cpp, both optional). Every
        # failure is a typed answer with `transcript: ""` (the desktop crashed on
        # a missing transcript in 1.4.5): `stt_unavailable` (no engine, with the
        # install hint), `bad_audio`, `too_large`, `stt_failed`.
        from neovarch import stt
        body = await _json(request)
        try:
            body = body if isinstance(body, dict) else {}
            data, mime = stt.decode_audio(body)
            lang = body.get("language") if isinstance(body.get("language"), str) else None
            return web.json_response(await asyncio.to_thread(stt.transcribe_bytes, data, mime, None, lang))
        except stt.SttError as e:
            out = {"ok": False, "available": e.code not in ("stt_unavailable",), "transcript": "",
                   "code": e.code, "error": str(e)}
            if e.code == "stt_unavailable":
                out["install_hint"] = stt.INSTALL_HINT
            return web.json_response(out)

    async def audio_stt_lease(request):
        from neovarch import stt
        body = await _json(request)
        avail = (await asyncio.to_thread(stt.status))["available"]
        return web.json_response({"ok": True, "active": bool(body.get("active")), "available": avail})

    async def terminal_backends(_):
        return web.json_response({"active": "local", "backends": [{
            "name": "local", "label": "Local", "description": "Commands run on this computer.",
            "active": True, "status": "ready", "detail": ""}]})

    async def owner_backfill(request):
        body = await _json(request)
        return web.json_response({"ok": True, "profile": body.get("profile") or "default", "stamped": 0})

    r.add_get("/api/profiles/active", profiles_active)
    r.add_get("/api/local-models/status", local_models_status)
    r.add_get("/api/local-models/jobs", local_models_jobs)
    r.add_get("/api/audio/voice-live/status", voice_live_status)
    r.add_post("/api/audio/transcribe", audio_transcribe)
    r.add_get("/api/audio/stt/status", audio_stt_status)
    r.add_post("/api/audio/stt-lease", audio_stt_lease)
    r.add_get("/api/tools/terminal/backends", terminal_backends)
    r.add_post("/api/sessions/owner-backfill", owner_backfill)
    r.add_get("/api/fs/list", fs_list)
    r.add_get("/api/fs/read", fs_read)
    r.add_get("/api/fs/default", fs_default)
    r.add_get("/api/fs/default-cwd", fs_default)
    # Last: quiet answers for every other route the desktop calls (never 404/500).
    # Chat attachments (/api/uploads) are registered above, before this fallback.
    from neovarch import compat
    compat.install(r, _log_unhandled)
    return app


def normalize_appearance(a: dict) -> dict:
    accent = str(a.get("accent") or "#EE1C1C").strip()
    if not accent.startswith("#"):
        accent = "#" + accent
    if len(accent) == 4:
        accent = "#" + "".join(c * 2 for c in accent[1:])
    try:
        int(accent[1:], 16)
    except ValueError:
        raise ValueError("accent must be a hex colour like #EE1C1C") from None
    if len(accent) != 7:
        raise ValueError("accent must be a hex colour like #EE1C1C")
    base = str(a.get("base") or "dark").lower()
    if base not in ("dark", "light"):
        raise ValueError("base must be dark or light")
    accent = accent.upper()
    r, g, b = (int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    # white text while it keeps >= 4:1 contrast (the brand red stays white-on-red),
    # otherwise whichever of white/black has the higher WCAG contrast
    white, black = 1.05 / (lum + 0.05), (lum + 0.05) / 0.05
    on = "#FFFFFF" if white >= 4.0 or white >= black else "#000000"
    return {"accent": accent, "base": base, "on_accent": on}


def appearance_of(cfg: dict) -> dict:
    try:
        return normalize_appearance(cfgmod.get_path(cfg, "appearance", {}) or {})
    except ValueError:
        return normalize_appearance({})


def config_schema_payload() -> dict:
    """The config fields the Neovarch core actually reads (Settings renders these)."""
    from neovarch import providers
    prov_opts = [""] + list(cfgmod.PRESETS) + ["custom"]
    try:
        prov_opts += [f"custom:{e['id']}" for e in providers.endpoints_response(cfgmod.load_config())["endpoints"]]
    except Exception:
        pass
    return {"category_order": ["model", "chat", "agent", "workspace", "safety", "advanced"], "fields": {
        "agent.harness_mode": {"category": "agent", "type": "select", "options": ["tempest", "legacy"],
                               "default": "tempest", "label": "Otak agen",
                               "description": "tempest = Neovarch Tempest, otak baru (bawaan): prompt hemat, cek "
                                              "lint/tes sebelum selesai, checkpoint yang bisa dipulihkan. legacy = "
                                              "loop lama, untuk kembali bila perlu."},
        "agent.escalate_on_stuck": {"category": "agent", "type": "boolean", "label": "Naik ke model lebih kuat saat buntu",
                                    "description": "Kalau agen gagal 2 kali berturut-turut di satu langkah, langkah itu "
                                                   "saja memakai model kuat di bawah, lalu kembali ke model bawaan."},
        "agent.escalation_model": {"category": "agent", "type": "string", "clearable": True,
                                   "label": "Model kuat untuk saat buntu",
                                   "description": "ID model yang lebih kuat (mis. dari 9Router atau endpoint kustom)."},
        "agent.escalation_provider": {"category": "agent", "type": "select", "options": prov_opts,
                                      "label": "Penyedia model kuat",
                                      "description": "Penyedia untuk model kuat (kosong = penyedia bawaan)."},
        "model.default": {"category": "model", "type": "string", "description": "ID model yang dipakai obrolan baru."},
        "model.provider": {"category": "model", "type": "select", "options": prov_opts,
                           "description": "Penyedia model (preset, custom, atau custom:<endpoint>)."},
        "model.base_url": {"category": "model", "type": "string", "clearable": True,
                           "description": "URL OpenAI-compatible untuk provider custom."},
        "model.context_length": {"category": "model", "type": "number", "description": "Panjang konteks model (token)."},
        "model_context_length": {"category": "model", "type": "number", "description": "Panjang konteks model (token)."},
        "approvals.mode": {"category": "safety", "type": "select", "options": ["ask", "off"],
                           "description": "ask = tanya sebelum perintah berbahaya; off = jalankan tanpa bertanya."},
        "agent.max_turns": {"category": "advanced", "type": "number", "description": "Titik periksa langkah: giliran yang masih ada kemajuan lanjut otomatis."},
        "agent.max_turn_steps": {"category": "advanced", "type": "number", "description": "Batas langkah maksimum per giliran."},
        "agent.max_turn_minutes": {"category": "advanced", "type": "number", "description": "Batas waktu per giliran (menit)."},
        "agent.max_turn_tokens": {"category": "advanced", "type": "number", "description": "Batas token per giliran."},
        "agent.system_prompt": {"category": "chat", "type": "text", "description": "Instruksi tambahan setelah SOUL.md."},
        # Settings › Obrolan › Perilaku
        "timezone": {"category": "chat", "type": "string", "clearable": True,
                     "description": "Zona waktu agen (mis. Asia/Jakarta). Kosong = jam PC."},
        "display.show_reasoning": {"category": "chat", "type": "boolean",
                                   "description": "Tampilkan proses berpikir model di obrolan."},
        # Settings › Ruang kerja › Proyek / Shell / File
        "terminal.cwd": {"category": "workspace", "type": "string", "clearable": True,
                         "description": "Folder kerja obrolan baru. Kosong = folder home."},
        "terminal.timeout": {"category": "workspace", "type": "number",
                             "description": "Batas waktu bawaan perintah shell (detik, maks 600)."},
        "file_read_max_chars": {"category": "workspace", "type": "number",
                                "description": "Batas karakter saat agen membaca satu file."},
    }}


def _cors(request: web.Request) -> dict:
    origin = request.headers.get("Origin")
    if not origin:
        return {}
    return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Hermes-Session-Token, X-Neovarch-Session-Token",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS"}


async def _json(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


async def _dispatch(gw: Gateway, conn: Conn, frame: dict) -> None:
    fid = frame.get("id")
    method = str(frame.get("method") or "")
    params = frame.get("params") or {}
    try:
        result = await gw.rpc(conn, method, params if isinstance(params, dict) else {})
        if fid is not None:
            await conn.send({"jsonrpc": "2.0", "id": fid, "result": result})
    except RpcError as exc:
        if fid is not None:
            await conn.send({"jsonrpc": "2.0", "id": fid, "error": {"code": exc.code, "message": exc.message}})
    except Exception as exc:
        traceback.print_exc()
        if fid is not None:
            await conn.send({"jsonrpc": "2.0", "id": fid, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}})


def _add_remote_link_routes(app: web.Application, gw: "Gateway") -> None:
    try:
        from neovarch.remote_link.service import add_routes
    except ImportError as exc:  # `cryptography` missing: LAN keeps working, relay/Bluetooth off
        reason = f"Remote dari mana saja tidak tersedia: {exc}"

        async def unavailable(_request):
            return web.json_response({"detail": reason}, status=503)
        for path in ("/api/remote/link", "/api/remote/link/config", "/api/remote/devices", "/api/remote/devices/{device_id}"):
            app.router.add_route("*", path, unavailable)
        return
    add_routes(app, gw)


async def _start_remote_link(gw: "Gateway") -> None:
    """The remote gateway (``--isolated``) also listens on the relay / Bluetooth."""
    if os.environ.get("NEOVARCH_LINK", "1" if gw.auth.isolated else "0").lower() in ("0", "false", "off"):
        return
    try:
        from neovarch.remote_link.service import LinkService
    except ImportError as exc:
        print(f"neovarch serve: remote link disabled ({exc})", file=sys.stderr, flush=True)
        return
    if gw.link is None:
        gw.link = LinkService(gw)
    await gw.link.start()


def serve(host: str, port: int, *, isolated: bool = False) -> int:
    # After a self-repair restart the new process takes the same port, so the
    # desktop and phone reconnect to the address they already know.
    restart_port = os.environ.pop("NEOVARCH_RESTART_PORT", "")
    if restart_port.isdigit() and not port:
        port = int(restart_port)

    async def main() -> None:
        gw = Gateway(isolated)
        runner = web.AppRunner(build_app(gw), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host, port, reuse_address=True)
        try:
            await site.start()
        except OSError as exc:
            print(f"neovarch serve: cannot listen on {host}:{port}: {exc}", file=sys.stderr, flush=True)
            raise SystemExit(98)
        sockets = getattr(site._server, "sockets", None) or []
        gw.port = sockets[0].getsockname()[1] if sockets else port
        from neovarch import logs as logmod
        logmod.setup().info("gateway listening on %s:%s (version %s)", host, gw.port, __version__)
        gw.consume_restart_notice()
        try:  # optional extras (Obsidian) after a fresh install or an update; never blocks startup
            gw.ensure_extras_after_install_or_update()
        except Exception:  # noqa: BLE001
            pass
        if os.environ.get("NEOVARCH_UPDATE_WATCH", "1").lower() not in ("0", "false", "off"):
            gw._update_watch = asyncio.get_running_loop().create_task(gw.watch_update_restart())
        # The desktop waits for this exact sentinel (legacy wire name, kept for compatibility).
        print(f"HERMES_BACKEND_READY port={gw.port}", flush=True)
        print(f"Neovarch gateway listening on {host}:{gw.port} (home {neovarch_home()})", flush=True)
        await _start_remote_link(gw)
        await asyncio.Event().wait()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    return 0
