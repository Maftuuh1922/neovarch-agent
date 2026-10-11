"""The Office: the agents this core runs, shown as "pegawai" at their desks.

Nothing here is simulated. Every pegawai is derived from something real:

* an employee the user hired through the main agent (``company.py``);
* an assignee of an open Kanban task.

Normal chats are answered by the main Neovarch Agent and are not desks.

The status of a pegawai is ``working`` while its turn runs, ``waiting-approval``
while a command waits for the user, otherwise ``idle``. An activity feed records
tool calls, messages, approvals and Kanban task moves. ``GET /api/office``
returns :meth:`Office.snapshot`; every change is pushed as the WebSocket event
``office.update`` (session_id null, so every client gets it) and on the SSE
stream ``GET /api/office/events``.
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from neovarch import __version__

if TYPE_CHECKING:  # pragma: no cover
    from neovarch.server import Gateway

NAMES = ["Ayu", "Bima", "Citra", "Dimas", "Eka", "Fajar", "Gita", "Hana", "Indra", "Joko",
         "Kirana", "Laras", "Made", "Nadia", "Oka", "Putri", "Raka", "Sari", "Tegar", "Wulan"]
ROLES = {"desktop": "Agen utama · desktop", "cli": "Agen terminal", "tui": "Agen terminal",
         "phone": "Agen remote · HP", "remote": "Agen remote · HP", "mobile": "Agen remote · HP"}
RECENT_S = 24 * 3600
MAX_DESKS = 100  # company employees are unlimited; the room shows the first 100
FEED_MAX = 200
SIGNIFICANT = {"tool.start", "tool.complete", "message.complete", "approval.request", "approval.cancelled",
               "approval.responded", "session.status", "session.title", "sessions.changed",
               "task.created", "task.moved", "task.updated", "error"}


def staff_name(key: str) -> str:
    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    return NAMES[h % len(NAMES)]


class Office:
    def __init__(self, gw: "Gateway"):
        self.gw = gw
        self.feed: deque[dict[str, Any]] = deque(maxlen=FEED_MAX)
        self.state: dict[str, dict[str, Any]] = {}   # session id -> {task, tool, last}
        self.seq = 0
        self._pending: asyncio.TimerHandle | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._vault_cache: tuple[float, dict] | None = None

    # ------------------------------------------------------------ events ---
    def _add(self, kind: str, sid: str | None, text: str, **extra) -> None:
        self.seq += 1
        item = {"id": self.seq, "ts": time.time(), "kind": kind, "session_id": sid,
                "agent": staff_name(sid) if sid else extra.pop("agent", None) or "Kanban", "text": text[:240]}
        item.update(extra)
        self.feed.append(item)

    def observe(self, kind: str, sid: str | None, payload: dict | None) -> None:
        if kind not in SIGNIFICANT:
            return
        p = payload or {}
        st = self.state.setdefault(sid, {}) if sid else {}
        now = time.time()
        if sid:
            st["last"] = now
        if kind == "tool.start":
            st["tool"] = f"{p.get('name')}: {p.get('preview') or ''}".strip(": ")
            self._add("tool", sid, f"menjalankan {p.get('name')}: {p.get('preview') or ''}".strip(), tool=p.get("name"))
        elif kind == "tool.complete":
            st.pop("tool", None)
            self._add("tool.done", sid, f"{p.get('name')} selesai ({p.get('duration_s', 0)} dtk): "
                                        f"{p.get('summary') or ''}".strip(), tool=p.get("name"))
        elif kind == "message.complete":
            st.pop("tool", None)
            if p.get("error") and p.get("status") != "interrupted":
                self._add("error", sid, f"gagal: {p.get('error')}")
            elif p.get("text"):
                self._add("message", sid, f"membalas: {p['text']}")
        elif kind == "approval.request":
            self._add("approval", sid, f"menunggu persetujuan: {p.get('command') or ''}")
        elif kind == "approval.responded":
            self._add("approval.done", sid, f"persetujuan dijawab: {p.get('choice')}")
        elif kind == "session.status" and p.get("status") == "running":
            live = self.gw.live.get(sid or "")
            msgs = live.rec.get("messages", []) if live else []
            last_user = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
            st["task"] = (last_user or "").strip().splitlines()[0][:160] if last_user else st.get("task", "")
            self._add("message.user", sid, f"mendapat tugas: {st['task']}" if st.get("task") else "mulai bekerja")
        elif kind in ("task.created", "task.moved", "task.updated"):
            who = p.get("assignee") or None
            if kind == "task.created":
                text = f"tugas baru di Kanban: {p.get('title')}"
            elif kind == "task.moved":
                text = f"memindahkan \u201c{p.get('title')}\u201d: {p.get('from')} \u2192 {p.get('to')}"
            else:
                text = f"memperbarui tugas \u201c{p.get('title')}\u201d"
            self._add("task", None, text, agent=staff_name("kanban:" + who) if who else "Kanban", task_id=p.get("id"))
        elif kind == "error":
            self._add("error", sid, str(p.get("message") or "error"))
        self.schedule()

    def schedule(self, delay: float = 0.25) -> None:
        """Coalesce bursts of events into one office.update."""
        if self._pending is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._pending = loop.call_later(delay, self._flush)

    def _flush(self) -> None:
        self._pending = None
        snap = self.snapshot()
        self.gw.broadcast_event("office.update", None, snap)
        for q in list(self._subscribers):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # ---------------------------------------------------------- snapshot ---
    def _vault(self) -> dict:
        from neovarch import obsidian
        now = time.monotonic()
        if self._vault_cache and now - self._vault_cache[0] < 20:
            return self._vault_cache[1]
        try:
            st = obsidian.status()
        except Exception as exc:  # never break the snapshot
            st = {"configured": True, "connected": False, "path": "", "note_count": 0, "error": str(exc)}
        self._vault_cache = (now, st)
        return st

    def invalidate_vault(self) -> None:
        self._vault_cache = None

    def _desk_for_session(self, rec: dict, live, cfg: dict | None = None) -> dict:
        sid = rec["id"]
        st = self.state.get(sid, {})
        msgs = rec.get("messages", [])
        status = "idle"
        if live is not None and live.approvals:
            status = "waiting-approval"
        elif live is not None and (live.status == "running" or
                                   (getattr(live, "task", None) is not None and not live.task.done())):
            status = "working"
        pending = None
        if live is not None and live.approvals:
            first = next(iter(live.approvals.values()))["params"]
            pending = {"request_id": first.get("request_id"), "command": first.get("command"),
                       "description": first.get("description")}
        last_user = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"
                          and isinstance(m.get("content"), str)), "")
        task = st.get("task") or ((last_user or "").strip().splitlines()[0][:160] if (last_user or "").strip() else "")
        last_ts = max(float(st.get("last") or 0), float(rec.get("updated_at") or rec.get("created_at") or 0))
        last_feed = next((f for f in reversed(self.feed) if f.get("session_id") == sid), None)
        source = str(rec.get("source") or "cli")
        model, provider = rec.get("model") or "", ""
        session_pick = False
        if cfg is not None:
            try:  # the model/provider this chat's next turn really uses
                from neovarch import session_settings
                if (rec.get("model_override") or {}).get("model"):
                    ep = session_settings.effective_endpoint(cfg, rec)
                    model, provider = ep.get("model") or model, ep.get("provider") or ""
                    session_pick = True
            except Exception:
                pass
        return {
            "id": f"session:{sid}", "kind": "session", "session_id": sid,
            "name": staff_name(sid), "role": ROLES.get(source, "Agen"), "source": source,
            "status": status, "current_task": task or None, "current_tool": st.get("tool") if status != "idle" else None,
            "title": rec.get("title") or None, "model": model, "model_provider": provider,
            **({"session_pick": True} if session_pick else {}),
            "last_activity": last_ts, "last_activity_text": last_feed["text"] if last_feed else None,
            "message_count": sum(1 for m in msgs if m.get("role") in ("user", "assistant")),
            "pending_approval": pending,
        }

    def _desks_for_kanban(self, tasks: list[dict]) -> list[dict]:
        by: dict[str, list[dict]] = {}
        for t in tasks:
            if t.get("assignee") and t.get("status") != "done":
                by.setdefault(str(t["assignee"]), []).append(t)
        out = []
        for who, items in by.items():
            running = [t for t in items if t.get("status") == "running"]
            cur = (running or sorted(items, key=lambda t: -float(t.get("updated_at") or 0)))[0]
            out.append({
                "id": f"kanban:{who}", "kind": "kanban", "session_id": None,
                "name": who, "role": "Pelaksana tugas Kanban", "source": "kanban",
                "status": "working" if running else "idle",
                "current_task": cur.get("title"), "current_tool": None, "title": None, "model": "",
                "last_activity": max(float(t.get("updated_at") or 0) for t in items),
                "last_activity_text": f"{cur.get('title')} ({cur.get('status')})",
                "message_count": 0, "pending_approval": None,
                "tasks": [{"id": t["id"], "title": t.get("title"), "status": t.get("status")} for t in items],
            })
        return out

    @staticmethod
    def _with_model(desk: dict, cfg: dict) -> dict:
        from neovarch import models as modelsmod
        if desk.get("kind") == "company" or desk.get("session_pick"):
            return desk  # a Perusahaan agent / a chat's own composer pick already names its model
        try:
            am = modelsmod.agent_model(cfg, desk["id"])
        except Exception:  # noqa: BLE001 - never break the snapshot
            return desk
        desk["model"] = am["model"]
        desk["model_provider"] = am["provider"]
        desk["model_override"] = am["override"]
        desk["model_source"] = am["source"]
        return desk

    def snapshot(self) -> dict[str, Any]:
        from neovarch import config as cfgmod
        from neovarch import models as modelsmod
        gw = self.gw
        now = time.time()
        desks: list[dict] = []
        # Chats are not employees: the Kantor starts empty and only lists the people
        # the user hired (company agents) plus Kanban assignees. `_desk_for_session`
        # stays for callers that describe one chat.
        try:
            tasks = gw.kanban.board().get("tasks", [])
        except Exception:
            tasks = []
        desks += self._desks_for_kanban(tasks)
        company = getattr(gw, "company", None)
        if company is not None:
            try:
                desks = company.merge_office(desks)
            except Exception:  # the Kantor must render even if the company data is broken
                pass
        order = {"working": 0, "waiting-approval": 1, "idle": 2}
        desks.sort(key=lambda d: (d.get("kind") != "company", order.get(d["status"], 3), -float(d["last_activity"] or 0)))
        desks = desks[:MAX_DESKS]
        cfg = cfgmod.load_config()
        desks = [self._with_model(d, cfg) for d in desks]
        dref = modelsmod.default_ref(cfg)
        counts = {"total": len(desks), "working": 0, "waiting-approval": 0, "idle": 0}
        for d in desks:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        model = None
        if hasattr(gw, "model_info"):
            try:
                model = gw.model_info()
            except Exception:
                model = None
        kanban = {s: sum(1 for t in tasks if t.get("status") == s) for s in ("todo", "ready", "running", "blocked", "done")}
        return {
            "version": 1, "product": "neovarch", "core_version": __version__,
            "generated_at": now, "host": socket.gethostname(), "seq": self.seq,
            "agents": desks, "counts": counts, "kanban": kanban,
            "feed": list(reversed(list(self.feed)[-60:])),
            "vault": self._vault(),
            "default_model": {"model": dref["model"], "provider": dref["provider"]},
            **({"model": model} if model else {}),
        }
