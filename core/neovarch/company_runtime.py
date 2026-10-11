"""Perusahaan runtime: API dispatch, heartbeat scheduler, agent tools and persona.

The store (``company.py``) owns data and invariants; this module wires it into the
gateway: JSON-RPC/REST methods, the asyncio heartbeat loop that wakes agents for
their tickets, the ``company_*`` tools an agent gets while it works, the persona
block for chats with an office agent, cost capture from ``message.complete``, and
the Kantor desks.
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from neovarch.company import STATUS_LABEL, CompanyError, CompanyStore

if TYPE_CHECKING:  # pragma: no cover
    from neovarch.server import Gateway, LiveSession

REASON_LABEL = {"assignment": "penugasan", "comment": "komentar baru", "schedule": "jadwal", "manual": "dibangunkan",
                "routine": "rutinitas", "approval": "keputusan persetujuan", "escalation": "eskalasi bawahan"}


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "", False) else None
    except (TypeError, ValueError):
        return None


@dataclass
class CompanyBinding:
    """Attached to a LiveSession's ToolContext when the session belongs to an office agent."""
    runtime: "CompanyRuntime"
    agent_id: int
    run_id: int | None = None
    ticket_id: int | None = None
    commented: bool = False
    touched: set[int] = field(default_factory=set)

    def tool_schemas(self) -> list[dict]:
        return [{"type": "function", "function": {"name": n, **spec}} for n, spec in AGENT_TOOLS.items()]

    def tool_names(self) -> set[str]:
        return set(AGENT_TOOLS)

    async def run_tool(self, name: str, args: dict) -> str:
        try:
            return self.runtime.agent_tool(self, name, args or {})
        except CompanyError as exc:
            return f"error: {exc}"

    def persona(self) -> str:
        return self.runtime.persona(self.agent_id, self.ticket_id)

    def allowed_tools(self) -> set[str] | None:
        """The built-in tools this employee may use; None = all of them."""
        a = self.runtime.store.agent(self.agent_id)
        names = self.runtime.store.parse_names((a or {}).get("tools"))
        return set(names) if names else None


AGENT_TOOLS: dict[str, dict] = {
    "company_my_work": {
        "description": "Kantor: list your tickets (with status) and the details of your current ticket, its goal "
                       "ancestry, comments, blockers and sub-tickets.",
        "parameters": {"type": "object", "properties": {}}},
    "company_ticket_update": {
        "description": "Kantor: report progress on a ticket you own (default: your current ticket). status: "
                       "in_progress | review (finished, ask for review) | done | blocked | todo (give it back). "
                       "Always include a short Indonesian comment explaining what you did or what blocks you.",
        "parameters": {"type": "object", "properties": {
            "ticket": {"type": "string", "description": "ticket key like NV-3 (optional)"},
            "status": {"type": "string", "enum": ["in_progress", "review", "done", "blocked", "todo"]},
            "comment": {"type": "string"}}, "required": ["comment"]}},
    "company_comment": {
        "description": "Kantor: add a comment to a ticket you own or one owned by someone in your team.",
        "parameters": {"type": "object", "properties": {
            "ticket": {"type": "string"}, "body": {"type": "string"}}, "required": ["body"]}},
    "company_delegate": {
        "description": "Kantor (managers): split work — create a sub-ticket of your current ticket and assign it to "
                       "someone who reports to you (directly or indirectly). They are woken to work on it.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "description": {"type": "string"},
            "assignee": {"type": "string", "description": "name of a report, e.g. Hana"},
            "priority": {"type": "integer", "description": "0 low … 3 urgent (default 1)"}},
            "required": ["title", "assignee"]}},
    "company_assign": {
        "description": "Kantor (managers): reassign a ticket of your team to another member of your team.",
        "parameters": {"type": "object", "properties": {
            "ticket": {"type": "string"}, "assignee": {"type": "string"}}, "required": ["ticket", "assignee"]}},
    "company_escalate": {
        "description": "Kantor: you are stuck — mark your current ticket blocked with the reason and wake your manager.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    "company_request_approval": {
        "description": "Kantor: ask the human board to approve a plan before you continue (e.g. spending, risky "
                       "change). You are woken again when they decide.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "plan": {"type": "string"}}, "required": ["title", "plan"]}},
    "company_work_product": {
        "description": "Kantor: attach a work product to your current ticket (a file path, a link, or a text result).",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "ref": {"type": "string", "description": "path, URL or text"},
            "kind": {"type": "string", "enum": ["file", "link", "text"]}}, "required": ["title", "ref"]}},
}


class CompanyRuntime:
    def __init__(self, gw: "Gateway", store: CompanyStore | None = None):
        self.gw = gw
        self.store = store or CompanyStore()
        self.store.on_change = self._on_change
        self.bindings: dict[str, CompanyBinding] = {}      # session id -> binding
        self.active: dict[int, asyncio.Task] = {}           # agent id -> running heartbeat
        self.active_runs: dict[int, int] = {}               # agent id -> run id
        self.last_error: dict[str, str] = {}
        self.tick_s = float(os.environ.get("NEOVARCH_COMPANY_TICK") or 10)
        self._loop_task: asyncio.Task | None = None
        self._pending: asyncio.TimerHandle | None = None
        self._recover()

    # ------------------------------------------------------------ lifecycle --
    def _recover(self) -> None:
        """A restart kills every in-flight run: fail them and free their locks."""
        s = self.store
        stale = s.q("SELECT * FROM runs WHERE status='running'")
        for r in stale:
            s.finish_run(r["id"], "failed", "core dimulai ulang saat pekerjaan berjalan")
        s.x("UPDATE tickets SET checkout_agent_id=NULL, checkout_run_id=NULL, checkout_at=NULL WHERE checkout_run_id IS NOT NULL")
        s.x("UPDATE agents SET status='idle' WHERE status='running'")

    def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
            self._loop_task = None
        for t in list(self.active.values()):
            t.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(self.tick_s)

    # --------------------------------------------------------------- events --
    def _on_change(self, entity: str, eid: int | None, action: str) -> None:
        self._last_change = {"entity": entity, "id": eid, "action": action}
        if self._pending is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._pending = loop.call_later(0.2, self._flush)

    def _flush(self) -> None:
        self._pending = None
        payload = dict(getattr(self, "_last_change", {}) or {})
        self.gw.broadcast_event("company.changed", None, payload)
        try:
            self.gw.office.schedule()
        except Exception:
            pass

    def observe(self, kind: str, sid: str | None, payload: dict | None) -> None:
        """Called for every gateway event: capture usage of office-agent sessions as cost events."""
        if not sid or kind != "message.complete":
            return
        b = self.bindings.get(sid)
        if b is None:
            return
        p = payload or {}
        if p.get("error") and p.get("status") != "interrupted":
            self.last_error[sid] = str(p["error"])
        usage = p.get("usage") or {}
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        if pt or ct:
            live = self.gw.live.get(sid)
            model = str(live.rec.get("model") or "") if live else ""
            self.store.record_cost(agent_id=b.agent_id, prompt_tokens=pt, completion_tokens=ct, model=model,
                                   ticket_id=b.ticket_id, run_id=b.run_id)
            self.store.check_budgets(b.agent_id)

    # ------------------------------------------------------------- sessions --
    def bind_session(self, live: "LiveSession") -> None:
        aid = _int(live.rec.get("company_agent_id"))
        if not aid:
            return
        a = self.store.agent(aid)
        if not a:
            return
        b = self.bindings.get(live.id) or CompanyBinding(self, aid)
        self.bindings[live.id] = b
        live.ctx.company = b  # type: ignore[attr-defined]
        live.ctx.persona = b.persona  # type: ignore[attr-defined]

    @staticmethod
    def _apply_model(rec: dict, a: dict) -> None:
        """The agent's own model pick (empty = the PC's default) rides on its session."""
        if a.get("model") or a.get("provider"):
            rec["model_override"] = {"model": a.get("model") or "", "provider": a.get("provider") or ""}
        else:
            rec.pop("model_override", None)

    def sync_session_model(self, a: dict) -> None:
        """After agent.save: an open persona session follows a new model pick at once."""
        sid = a.get("session_id")
        gw = self.gw
        if not sid:
            return
        rec = gw.live[sid].rec if sid in gw.live else gw.store.find(sid)
        if not rec:
            return
        before = rec.get("model_override")
        self._apply_model(rec, a)
        if rec.get("model_override") == before:
            return
        try:
            from neovarch import config as cfgmod, session_settings
            rec["model"] = session_settings.effective_endpoint(cfgmod.load_config(), rec)["model"]
        except Exception:  # noqa: BLE001 - a bad pick falls back to the default at turn time
            pass
        gw.store.save(rec)
        if sid in gw.live:
            gw.broadcast_event("session.info", sid, gw.live[sid].info())

    def agent_session(self, a: dict) -> "LiveSession":
        gw = self.gw
        rec = None
        if a.get("session_id"):
            rec = gw.live[a["session_id"]].rec if a["session_id"] in gw.live else gw.store.find(a["session_id"])
        if not rec:
            rec = gw.store.create(source="company", title=f"Kantor · {a['name']}", model=gw.model_info()["model"])
            self.store.x("UPDATE agents SET session_id=? WHERE id=?", (rec["id"], a["id"]))
        rec["company_agent_id"] = a["id"]
        self._apply_model(rec, a)
        gw.store.save(rec)
        live = gw.open(rec)
        self.bind_session(live)
        return live

    # -------------------------------------------------------------- persona --
    def persona(self, aid: int, ticket_id: int | None = None) -> str:
        s = self.store
        a = s.agent(aid)
        c = s.company()
        if not a or not c:
            return ""
        mgr = s.agent(a["reports_to"])
        reports = s.reports(a["id"])
        cur = s.ticket(ticket_id) if ticket_id else None
        if not cur:
            cur = s.q1("SELECT * FROM tickets WHERE assignee_id=? AND status IN ('in_progress','review') "
                       "ORDER BY updated_at DESC LIMIT 1", (aid,))
        queue = s.q("SELECT key, title, status FROM tickets WHERE assignee_id=? AND status IN "
                    "('todo','in_progress','review','blocked') ORDER BY priority DESC, id LIMIT 6", (aid,))
        acts = s.q("SELECT summary, ts FROM activity WHERE actor_type='agent' AND actor_id=? ORDER BY id DESC LIMIT 5", (aid,))
        running = aid in self.active
        if a["status"] == "paused":
            state = "sedang dijeda" + (" karena anggaran habis" if a["pause_reason"] == "budget" else " oleh pengguna")
        elif running and cur:
            state = f"sedang mengerjakan {cur['key']}"
        elif a["status"] == "pending_approval":
            state = "menunggu persetujuan rekrutmen"
        else:
            state = "sedang tidak menjalankan tiket"
        lines = [f"# Kamu adalah {a['name']}, {a['title'] or a['role']} di {c['name']}",
                 f"Misi perusahaan: {c['mission'] or '-'}",
                 f"Atasan: {mgr['name'] + ' (' + (mgr['title'] or mgr['role']) + ')' if mgr else 'langsung ke pengguna (dewan)'}",
                 f"Bawahan: {', '.join(r['name'] + ' (' + (r['title'] or r['role']) + ')' for r in reports) or '-'}",
                 f"Deskripsi kerja: {a['job_description'] or '-'}",
                 f"Status kamu sekarang: {state}."]
        if cur:
            chain = " → ".join(x["title"] if x["type"] != "ticket" else f"{x['key']} {x['title']}"
                               for x in s.ancestry(cur["id"]))
            lines.append(f"Tiket saat ini: {cur['key']} “{cur['title']}” ({STATUS_LABEL[cur['status']]}). "
                         f"{(cur['description'] or '')[:400]}")
            if chain:
                lines.append(f"Kenapa ini penting (dari tiket ke misi): {chain}")
        if queue:
            lines.append("Antrian tiketmu: " + "; ".join(f"{q['key']} {q['title']} ({STATUS_LABEL[q['status']]})"
                                                          for q in queue))
        if acts:
            lines.append("Aktivitas terakhirmu: " + "; ".join(x["summary"] for x in acts))
        unit = s.unit(a.get("unit_id"))
        if unit:
            path = []
            u = unit
            while u is not None and len(path) < 20:
                path.append(u["name"])
                u = s.unit(u["parent_id"])
            lines.append("Unit: " + " → ".join(reversed(path)))
        skills = s.parse_names(a.get("skills"))
        if skills:
            lines.append("Skill yang kamu kuasai (baca dengan alat `skill` bila perlu): " + ", ".join(skills))
        if (a.get("persona") or "").strip():
            lines.append("Persona / gaya kerjamu:\n" + a["persona"].strip()[:2000])
        lines.append(f"Aturan: jawab sebagai {a['name']} dalam bahasa Indonesia yang santai dan sopan. Kalau ditanya "
                     "“lagi apa”, jawab dari data di atas apa adanya; jangan mengarang pekerjaan yang tidak tercatat. "
                     "Gunakan alat company_* untuk melaporkan kemajuan tiket.")
        return "\n".join(lines)

    def heartbeat_prompt(self, a: dict, t: dict, reason: str) -> str:
        s = self.store
        d = s.ticket_detail(t["id"])
        chain = " → ".join(x["title"] if x["type"] != "ticket" else f"{x['key']} {x['title']}" for x in d["ancestry"])
        parts = [f"[Heartbeat Kantor · alasan: {REASON_LABEL.get(reason, reason)}]",
                 f"Tiket {t['key']}: “{t['title']}” (status {STATUS_LABEL[d['status']]}, prioritas {t['priority']}).",
                 f"Deskripsi: {t['description'] or '-'}"]
        if chain:
            parts.append(f"Kenapa ini penting: {chain}")
        if d["comments"]:
            parts.append("Komentar terbaru:\n" + "\n".join(
                f"- {c['author_name'] or ('Pengguna' if c['author_type'] == 'user' else 'Sistem')}: {c['body'][:500]}"
                for c in d["comments"][-6:]))
        if d["children"]:
            parts.append("Subtiket: " + "; ".join(f"{x['key']} {x['title']} ({STATUS_LABEL[x['status']]})"
                                                   for x in d["children"]))
        if d["work_products"]:
            parts.append("Hasil kerja sejauh ini: " + "; ".join(w["title"] for w in d["work_products"]))
        if t["assignee_id"] != a["id"]:
            owner = s.agent(t["assignee_id"])
            parts.append(f"Ini tiket bawahanmu {owner['name'] if owner else '-'} yang terhambat. Beri arahan dengan "
                         "company_comment, alihkan dengan company_assign, atau eskalasi dengan company_escalate.")
        else:
            parts.append("Kerjakan sekarang dengan alat yang tersedia. Bila selesai panggil company_ticket_update "
                         "status=review dengan ringkasan hasil; bila terhambat status=blocked dengan alasannya; bila "
                         "pekerjaannya perlu dibagi, gunakan company_delegate ke bawahanmu.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------ heartbeat --
    def can_run(self, a: dict) -> str | None:
        if a["status"] in ("paused", "terminated", "pending_approval"):
            return {"paused": "dijeda", "terminated": "diberhentikan", "pending_approval": "belum disetujui"}[a["status"]]
        if a["id"] in self.active:
            return "sedang bekerja"
        return None

    async def tick(self) -> None:
        s = self.store
        c = s.company()
        if not c or not c["autorun"]:
            return
        for r in s.due_routines():
            try:
                t = s.fire_routine(r["id"])
                if t["assignee_id"]:
                    s.wake(t["assignee_id"], "routine", t["id"])
            except CompanyError:
                pass
        wakes = s.take_wakeups()
        now = s.clock()
        for a in s.q("SELECT * FROM agents WHERE status='idle' AND heartbeat_s>0"):
            if now - float(a["last_heartbeat_at"] or 0) >= a["heartbeat_s"] and a["id"] not in wakes:
                wakes[a["id"]] = [{"reason": "schedule", "ticket_id": None}]
        # agents with assigned todo work but no queued wake (e.g. autorun just turned on)
        for r in s.q("SELECT DISTINCT assignee_id FROM tickets WHERE status='todo' AND assignee_id IS NOT NULL"):
            wakes.setdefault(r["assignee_id"], [{"reason": "assignment", "ticket_id": None}])
        for aid, items in wakes.items():
            a = s.agent(aid)
            if not a:
                continue
            first = items[0]
            if self.can_run(a):
                if a["status"] not in ("terminated",) and a["id"] in self.active:
                    for it in items:   # retry after the current run
                        s.wake(aid, it["reason"], it.get("ticket_id"))
                continue
            if len(self.active) >= int(c["max_parallel"] or 1):
                for it in items:
                    s.wake(aid, it["reason"], it.get("ticket_id"))
                continue
            self.launch(a, first["reason"], first.get("ticket_id"))

    def launch(self, a: dict, reason: str, ticket_id: int | None = None) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(self.run_heartbeat(a["id"], reason, ticket_id))
        self.active[a["id"]] = task
        task.add_done_callback(lambda _t, aid=a["id"]: self.active.pop(aid, None))
        return task

    def wake_now(self, aid: int) -> dict:
        a = self.store.require_agent(aid)
        why = self.can_run(a)
        if why:
            raise CompanyError("conflict", f"{a['name']} {why}")
        c = self.store.require_company()
        if len(self.active) >= int(c["max_parallel"] or 1):
            raise CompanyError("conflict", "Semua slot kerja sedang terpakai; coba lagi nanti")
        self.launch(a, "manual")
        self.store.log("agent.woken", "agent", a["id"], f"membangunkan {a['name']}")
        return {"ok": True, "agent_id": a["id"]}

    async def run_heartbeat(self, aid: int, reason: str, ticket_hint: int | None = None) -> dict:
        s = self.store
        a = s.agent(aid)
        if not a:
            return {"status": "skipped"}
        s.check_budgets(aid)
        a = s.agent(aid)
        if a["status"] in ("paused", "terminated", "pending_approval"):
            return {"status": "skipped", "reason": a["status"]}
        ticket = None
        supervising = False
        if ticket_hint:
            h = s.ticket(ticket_hint)
            if h and h["status"] not in ("done", "cancelled"):
                if h["assignee_id"] == aid:
                    ticket = h
                elif h["assignee_id"] in s.subtree(aid) and reason == "escalation":
                    ticket, supervising = h, True
        ticket = ticket or s.next_ticket_for(aid)
        if not ticket:
            s.x("UPDATE agents SET last_heartbeat_at=? WHERE id=?", (s.clock(), aid))
            return {"status": "idle", "reason": "tidak ada tiket"}
        run_id = s.start_run(aid, reason, ticket["id"])
        if not supervising:
            try:
                ticket = s.checkout(ticket["id"], aid, run_id)
            except CompanyError as exc:
                s.finish_run(run_id, "cancelled", str(exc))
                return {"status": "conflict", "error": str(exc)}
        self.active_runs[aid] = run_id
        s.set_agent_status(aid, "running", log=False)
        s.log("run.started", "agent", aid, f"mulai bekerja di {ticket['key']} ({REASON_LABEL.get(reason, reason)})",
              actor="agent", actor_id=aid)
        status, error, sid = "succeeded", None, None
        try:
            live = self.agent_session(a)
            sid = live.id
            if live.status == "running":
                raise CompanyError("conflict", "sesi agen sedang dipakai untuk obrolan")
            b = self.bindings[live.id]
            b.run_id, b.ticket_id, b.commented = run_id, ticket["id"], False
            self.last_error.pop(live.id, None)
            live.submit(self.heartbeat_prompt(s.agent(aid), ticket, reason))
            if live.task:
                await live.task
            err = self.last_error.pop(live.id, None)
            if err:
                status, error = "failed", err
            final = (live.last_text or "").strip()
            if final and not b.commented and not supervising:
                s.comment(ticket["id"], final[:4000], actor="agent", actor_id=aid)
            b.run_id = None
        except CompanyError as exc:
            status, error = "cancelled", str(exc)
            s.wake(aid, reason, ticket["id"])
        except asyncio.CancelledError:
            status, error = "cancelled", "dihentikan"
        except Exception as exc:  # report, keep the scheduler alive
            traceback.print_exc()
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            self.active_runs.pop(aid, None)
            t = s.ticket(ticket["id"])
            if t and t["checkout_run_id"] == run_id:
                s.release(t["id"], aid, actor="agent")
            s.finish_run(run_id, status, error, sid)
            cur = s.agent(aid)
            if cur and cur["status"] == "running":
                s.set_agent_status(aid, "error" if status == "failed" else "idle", log=False)
            s.x("UPDATE agents SET last_heartbeat_at=? WHERE id=?", (s.clock(), aid))
            s.log(f"run.{status}", "agent", aid, f"selesai bekerja di {ticket['key']}" if status == "succeeded"
                  else f"berhenti di {ticket['key']}: {error}", actor="agent", actor_id=aid)
            s.check_budgets(aid)
            s.changed("run", run_id, status)
        return {"status": status, "error": error, "run_id": run_id, "ticket": ticket["key"]}

    def stop_agent(self, aid: int) -> dict:
        a = self.store.require_agent(aid)
        if a["session_id"] and a["session_id"] in self.gw.live:
            self.gw.live[a["session_id"]].agent.interrupt()
        task = self.active.get(a["id"])
        if task and not task.done():
            # the agent loop checks `interrupted` between model/tool calls; cancel as a backstop
            asyncio.get_running_loop().call_later(5, lambda: task.done() or task.cancel())
        self.store.set_agent_status(a["id"], "paused", reason="dihentikan")
        return self.store.require_agent(a["id"])

    # ---------------------------------------------------------- agent tools --
    def _find_agent(self, name: str) -> dict:
        r = self.store.q1("SELECT * FROM agents WHERE lower(name)=lower(?) AND status!='terminated'", ((name or "").strip(),))
        if not r:
            raise CompanyError("not_found", f"tidak ada pegawai bernama {name}")
        return r

    def _own_ticket(self, b: CompanyBinding, key: str | None, *, team: bool = False) -> dict:
        s = self.store
        t = s.require_ticket(key) if key else (s.ticket(b.ticket_id) if b.ticket_id else None)
        if not t:
            t = s.next_ticket_for(b.agent_id)
        if not t:
            raise CompanyError("not_found", "kamu tidak sedang memegang tiket")
        allowed = {b.agent_id} | (s.subtree(b.agent_id) if team else set())
        if t["assignee_id"] not in allowed:
            raise CompanyError("conflict", f"{t['key']} bukan tiketmu")
        return t

    def agent_tool(self, b: CompanyBinding, name: str, args: dict) -> str:
        s = self.store
        aid = b.agent_id
        me = s.require_agent(aid)
        if name == "company_my_work":
            mine = s.list_tickets(assignee_id=aid, limit=20)
            lines = [f"{t['key']} [{t['status']}] {t['title']}" for t in mine if t["status"] not in ("done", "cancelled")]
            out = "Tiketmu:\n" + ("\n".join(lines) or "(kosong)")
            cur = s.ticket(b.ticket_id) if b.ticket_id else None
            if cur:
                d = s.ticket_detail(cur["id"])
                out += (f"\n\nTiket saat ini {cur['key']}: {cur['title']}\n{cur['description']}\n"
                        "Asal-usul: " + " → ".join(x.get("key", "") + " " + x["title"] for x in d["ancestry"]))
                if d["comments"]:
                    out += "\nKomentar:\n" + "\n".join(f"- {c['author_name'] or c['author_type']}: {c['body'][:300]}"
                                                       for c in d["comments"][-5:])
            team = s.reports(aid)
            if team:
                out += "\n\nTimmu: " + ", ".join(f"{r['name']} ({r['title'] or r['role']})" for r in team)
            return out
        if name == "company_ticket_update":
            t = self._own_ticket(b, args.get("ticket"))
            comment = str(args.get("comment") or "").strip()
            if comment:
                s.comment(t["id"], comment, actor="agent", actor_id=aid)
                b.commented = True
            to = args.get("status")
            if not to or to == t["status"]:
                return f"{t['key']}: komentar dicatat"
            c = s.require_company()
            if to in ("done", "review"):
                if c["require_review"] or to == "review":
                    if t["status"] != "review":
                        s.move_ticket(t["id"], "review", actor="agent", actor_id=aid,
                                      force=t["status"] not in ("in_progress",))
                    s.create_approval("review", ticket_id=t["id"], agent_id=aid,
                                      title=f"Tinjau hasil {t['key']}: {t['title']}", requested_by="agent", actor_id=aid,
                                      payload={"summary": comment[:1000]})
                    return f"{t['key']} dikirim untuk ditinjau pengguna"
                s.move_ticket(t["id"], "done", actor="agent", actor_id=aid, force=t["status"] == "blocked")
                return f"{t['key']} selesai"
            if to == "todo":
                s.release(t["id"], aid, actor="agent")
                s.move_ticket(t["id"], "todo", actor="agent", actor_id=aid, force=True)
                return f"{t['key']} dikembalikan ke antrian"
            if to == "in_progress":
                s.checkout(t["id"], aid, b.run_id)
                return f"{t['key']} dikerjakan"
            s.move_ticket(t["id"], to, actor="agent", actor_id=aid, force=True)
            return f"{t['key']} → {STATUS_LABEL[to]}"
        if name == "company_comment":
            t = self._own_ticket(b, args.get("ticket"), team=True)
            s.comment(t["id"], str(args.get("body") or ""), actor="agent", actor_id=aid)
            if t["id"] == b.ticket_id:
                b.commented = True
            elif t["assignee_id"] and t["assignee_id"] != aid:
                s.wake(t["assignee_id"], "comment", t["id"])
            return "komentar dicatat"
        if name == "company_delegate":
            target = self._find_agent(str(args.get("assignee") or ""))
            if target["id"] not in s.subtree(aid):
                raise CompanyError("conflict", f"{target['name']} bukan bawahanmu; delegasi hanya ke timmu sendiri")
            parent = s.ticket(b.ticket_id) if b.ticket_id else None
            t = s.create_ticket({"title": args.get("title"), "description": args.get("description") or "",
                                 "assignee_id": target["id"], "parent_id": parent["id"] if parent else None,
                                 "priority": args.get("priority") if args.get("priority") is not None else 1,
                                 "status": "todo"}, actor="agent", actor_id=aid)
            s.wake(target["id"], "assignment", t["id"])
            s.log("ticket.delegated", "ticket", t["id"], f"mendelegasikan {t['key']} ke {target['name']}",
                  actor="agent", actor_id=aid)
            return f"{t['key']} dibuat untuk {target['name']}"
        if name == "company_assign":
            t = self._own_ticket(b, args.get("ticket"), team=True)
            target = self._find_agent(str(args.get("assignee") or ""))
            if target["id"] not in s.subtree(aid) | {aid}:
                raise CompanyError("conflict", f"{target['name']} bukan anggota timmu")
            s.assign_ticket(t["id"], target["id"], actor="agent", actor_id=aid)
            if t["status"] == "blocked":
                s.move_ticket(t["id"], "todo", actor="agent", actor_id=aid)
            s.wake(target["id"], "assignment", t["id"])
            return f"{t['key']} dialihkan ke {target['name']}"
        if name == "company_escalate":
            t = self._own_ticket(b, None)
            reason = str(args.get("reason") or "").strip() or "butuh bantuan"
            s.comment(t["id"], f"Eskalasi: {reason}", actor="agent", actor_id=aid)
            b.commented = True
            if t["status"] != "blocked":
                s.move_ticket(t["id"], "blocked", actor="agent", actor_id=aid, force=True)
            if me["reports_to"]:
                s.wake(me["reports_to"], "escalation", t["id"])
                return f"{t['key']} ditandai terhambat; atasanmu dibangunkan"
            s.create_approval("plan", ticket_id=t["id"], agent_id=aid, title=f"{me['name']} butuh bantuan di {t['key']}",
                              requested_by="agent", actor_id=aid, payload={"plan": reason})
            return f"{t['key']} ditandai terhambat; pengguna diminta memutuskan"
        if name == "company_request_approval":
            t = s.ticket(b.ticket_id) if b.ticket_id else None
            ap = s.create_approval("plan", ticket_id=t["id"] if t else None, agent_id=aid,
                                   title=str(args.get("title") or "Rencana"), requested_by="agent", actor_id=aid,
                                   payload={"plan": str(args.get("plan") or "")[:4000]})
            return f"permintaan persetujuan #{ap['id']} dikirim; tunggu keputusan pengguna (kamu akan dibangunkan)"
        if name == "company_work_product":
            t = self._own_ticket(b, None)
            w = s.add_work_product(t["id"], str(args.get("title") or ""), str(args.get("ref") or ""),
                                   str(args.get("kind") or "text"), actor="agent", actor_id=aid)
            return f"hasil kerja #{w['id']} dilampirkan ke {t['key']}"
        return f"error: unknown tool {name}"

    # ------------------------------------------------- main agent (kantor) --
    def _unit_ref(self, ref) -> dict | None:
        if ref in (None, ""):
            return None
        s = self.store
        u = s.unit(ref) if str(ref).isdigit() else None
        u = u or s.unit_by_name(str(ref))
        if not u:
            raise CompanyError("not_found", f"tidak ada organisasi/agency bernama {ref}")
        return u

    def _agent_ref(self, ref) -> dict:
        s = self.store
        if str(ref or "").isdigit():
            a = s.agent(int(ref))
            if a and a["status"] != "terminated":
                return a
        return self._find_agent(str(ref or ""))

    def org_text(self) -> str:
        s = self.store
        if not s.company():
            return "Kantor masih kosong: belum ada organisasi, agency, atau pegawai."
        units = s.units()
        agents = s.agents_public()
        by_unit: dict[int | None, list[dict]] = {}
        for a in agents:
            by_unit.setdefault(a.get("unit_id"), []).append(a)
        lines = [f"Kantor: {s.company()['name']}"]

        def person(a: dict, depth: int) -> str:
            cur = (a.get("current_ticket") or {}).get("key")
            extra = []
            if a.get("model"):
                extra.append(f"model {a['model']}")
            if a.get("skills"):
                extra.append("skill " + ", ".join(a["skills"]))
            if a.get("tools"):
                extra.append("alat " + ", ".join(a["tools"]))
            return ("  " * depth + f"- {a['name']} ({a['title'] or a['role']}) · {a['status']}"
                    + (f" · tiket {cur}" if cur else "") + (f" · {'; '.join(extra)}" if extra else ""))

        def walk(parent: int | None, depth: int) -> None:
            for u in [u for u in units if u["parent_id"] == parent]:
                lines.append("  " * depth + f"[{u['kind']}] {u['name']} (id {u['id']})")
                for a in by_unit.get(u["id"], []):
                    lines.append(person(a, depth + 1))
                walk(u["id"], depth + 1)

        walk(None, 0)
        loose = by_unit.get(None, [])
        if loose:
            lines.append("Tanpa unit:")
            lines += [person(a, 1) for a in loose]
        if not units and not agents:
            lines.append("(belum ada organisasi, agency, atau pegawai)")
        open_t = s.q("SELECT t.key, t.title, t.status, a.name AS who FROM tickets t LEFT JOIN agents a ON a.id=t.assignee_id "
                     "WHERE t.status NOT IN ('done','cancelled') ORDER BY t.id DESC LIMIT 10")
        if open_t:
            lines.append("Tugas terbuka: " + "; ".join(f"{t['key']} {t['title']} ({t['status']}, {t['who'] or 'belum ada'})"
                                                      for t in open_t))
        return "\n".join(lines)

    def main_tool(self, args: dict) -> str:
        """The main Neovarch Agent runs the Kantor on the user's command (tool `kantor`)."""
        s = self.store
        action = str(args.get("action") or "overview").strip().lower()
        try:
            if action in ("overview", "lihat", "status"):
                return self.org_text()
            if action in ("create_org", "create_agency", "create_unit"):
                s.ensure_company()
                kind = {"create_org": "organisasi", "create_agency": "agency"}.get(action) or args.get("kind")
                parent = self._unit_ref(args.get("parent") or args.get("unit"))
                u = s.save_unit({"name": args.get("name"), "kind": kind, "parent_id": parent["id"] if parent else None,
                                 "description": args.get("description") or ""}, actor="system")
                return f"{u['kind']} “{u['name']}” dibuat (id {u['id']})" + (f" di bawah {parent['name']}" if parent else "")
            if action == "rename_unit":
                u = self._unit_ref(args.get("unit") or args.get("name"))
                u = s.save_unit({"id": u["id"], "name": args.get("new_name") or args.get("title")}, actor="system")
                return f"unit diganti nama menjadi {u['name']}"
            if action == "delete_unit":
                u = self._unit_ref(args.get("unit") or args.get("name"))
                s.delete_unit(u["id"], actor="system")
                return f"{u['kind']} {u['name']} dihapus; isinya pindah ke unit di atasnya"
            if action == "hire":
                s.ensure_company()
                unit = self._unit_ref(args.get("unit"))
                mgr = self._agent_ref(args["manager"]) if args.get("manager") else None
                body = {"name": args.get("name"), "title": args.get("title") or "", "role": args.get("role") or "pegawai",
                        "job_description": args.get("job_description") or args.get("description") or "",
                        "unit_id": unit["id"] if unit else None, "reports_to": mgr["id"] if mgr else None,
                        "persona": args.get("persona") or "", "skills": args.get("skills") or [],
                        "tools": args.get("tools") or [], "skip_approval": True}
                if args.get("model"):
                    body["model"] = args["model"]
                    body["provider"] = args.get("provider") or ""
                a = s.save_agent(body, actor="system")
                return (f"{a['name']} direkrut sebagai {a['title'] or a['role']}" + (f" di {unit['name']}" if unit else "")
                        + f" (model {a['model'] or 'bawaan PC'})")
            if action in ("fire", "delete_employee", "delete"):
                a = self._agent_ref(args.get("name") or args.get("employee"))
                if a["id"] in self.active:
                    self.stop_agent(a["id"])
                s.delete_agent(a["id"], actor="system")
                return f"{a['name']} diberhentikan dan dihapus dari Kantor; tiketnya kini tanpa penanggung jawab"
            if action == "move":
                a = self._agent_ref(args.get("name") or args.get("employee"))
                body = {"id": a["id"]}
                if "unit" in args:
                    unit = self._unit_ref(args.get("unit"))
                    body["unit_id"] = unit["id"] if unit else None
                if "manager" in args:
                    mgr = self._agent_ref(args["manager"]) if args.get("manager") else None
                    body["reports_to"] = mgr["id"] if mgr else None
                a = s.save_agent(body, actor="system")
                u = s.unit(a.get("unit_id"))
                return f"{a['name']} dipindah ke {u['name'] if u else 'tanpa unit'}"
            if action in ("set_employee", "update_employee"):
                a = self._agent_ref(args.get("name") or args.get("employee"))
                body = {"id": a["id"]}
                for k in ("title", "role", "job_description", "persona", "model", "provider", "skills", "tools"):
                    if k in args:
                        body[k] = args[k]
                if "new_name" in args:
                    body["name"] = args["new_name"]
                a = s.save_agent(body, actor="system")
                if "model" in body or "provider" in body:
                    self.sync_session_model(a)
                return f"profil {a['name']} diperbarui"
            if action in ("assign_task", "task"):
                s.ensure_company()
                a = self._agent_ref(args.get("employee") or args.get("name"))
                t = s.create_ticket({"title": args.get("title") or args.get("task"),
                                     "description": args.get("description") or "", "assignee_id": a["id"],
                                     "priority": args.get("priority") if args.get("priority") is not None else 1,
                                     "status": "todo"}, actor="system")
                if args.get("start_now"):
                    try:
                        self.wake_now(a["id"])
                    except (CompanyError, RuntimeError):
                        s.wake(a["id"], "assignment", t["id"])
                elif s.company()["autorun"]:
                    s.wake(a["id"], "assignment", t["id"])
                return f"tugas {t['key']} “{t['title']}” diberikan ke {a['name']}" + (
                    "" if s.company()["autorun"] or args.get("start_now")
                    else " (mulai saat “Jalan otomatis” aktif atau pegawai dibangunkan)")
            return f"error: aksi tidak dikenal: {action}"
        except CompanyError as exc:
            return f"error: {exc}"
        except KeyError as exc:
            return f"error: argumen {exc} wajib diisi"

    # --------------------------------------------------------------- office --
    def merge_office(self, desks: list[dict]) -> list[dict]:
        """Company agents become desks; their own chat sessions are not listed twice."""
        s = self.store
        if not s.company():
            return desks
        out_ids = set()
        company_desks = []
        for a in s.agents_public():
            live = self.gw.live.get(a["session_id"] or "")
            if live is not None and live.approvals:
                status = "waiting-approval"
            elif a["id"] in self.active or (live is not None and live.status == "running"):
                status = "working"
            elif a["pending_approvals"] or (a["current_ticket"] or {}).get("status") == "review":
                status = "waiting-approval"
            else:
                status = "idle"
            cur = a["current_ticket"]
            if a["session_id"]:
                out_ids.add(a["session_id"])
            last = s.q1("SELECT summary, ts FROM activity WHERE actor_type='agent' AND actor_id=? ORDER BY id DESC LIMIT 1",
                        (a["id"],))
            company_desks.append({
                "id": f"company:{a['id']}", "kind": "company", "session_id": a["session_id"],
                "name": a["name"], "role": a["title"] or a["role"], "source": "company", "status": status,
                "current_task": f"{cur['key']} · {cur['title']}" if cur else None, "current_tool": None,
                "title": None, "model": a["model"] or "",
                "last_activity": float(last["ts"]) if last else float(a["updated_at"] or 0),
                "last_activity_text": last["summary"] if last else None, "message_count": 0,
                "pending_approval": None,
                "company": {"agent_id": a["id"], "title": a["title"], "agent_status": a["status"],
                            "paused": a["status"] == "paused", "pause_reason": a["pause_reason"],
                            "reports_to": a["reports_to"], "ticket_key": cur["key"] if cur else None,
                            "ticket_title": cur["title"] if cur else None, "ticket_status": cur["status"] if cur else None,
                            "budget_pct": a["budget"]["pct"]},
            })
        rest = [d for d in desks if d.get("session_id") not in out_ids]
        return company_desks + rest

    def summary(self) -> dict | None:
        snap = self.store.snapshot()
        if not snap.get("exists"):
            return None
        return {"name": snap["company"]["name"], "mission": snap["company"]["mission"],
                "autorun": snap["company"]["autorun"], "ticket_counts": snap["ticket_counts"],
                "pending_approvals": snap["pending_approvals"], "budget": snap["budget"],
                "agents": [{"name": a["name"], "title": a["title"], "status": a["status"],
                            "ticket": (a["current_ticket"] or {}).get("key")} for a in snap["agents"]]}

    # ------------------------------------------------------------------ API --
    async def call(self, method: str, p: dict) -> Any:
        s = self.store
        m = method[len("company."):] if method.startswith("company.") else method
        p = p or {}

        def wake_assignee(t: dict, reason: str = "assignment") -> None:
            if t.get("assignee_id") and t["status"] in ("todo", "in_progress"):
                s.wake(t["assignee_id"], reason, t["id"])

        if m == "snapshot":
            snap = s.snapshot()
            if snap.get("exists"):
                snap["active_agents"] = sorted(self.active)
            return snap
        if m == "setup":
            return s.setup(str(p.get("name") or ""), str(p.get("mission") or ""),
                           **{k: v for k, v in p.items() if k not in ("name", "mission")})
        if m == "update":
            return s.update_company(p)
        if m == "seed_demo":
            return self.seed_demo(p)
        if m == "goal.save":
            return s.save_goal(p)
        if m == "goal.delete":
            s.delete_goal(int(p.get("id") or 0))
            return {"ok": True}
        if m == "project.save":
            return s.save_project(p)
        if m == "project.delete":
            s.delete_project(int(p.get("id") or 0))
            return {"ok": True}
        if m == "unit.list":
            return {"units": s.units()}
        if m == "unit.save":
            s.ensure_company()
            return s.save_unit(p)
        if m == "unit.delete":
            s.delete_unit(p.get("id"))
            return {"ok": True}
        if m == "agent.move":
            a = s.require_agent(p.get("id"))
            body: dict = {"id": a["id"]}
            if "unit_id" in p:
                body["unit_id"] = p.get("unit_id")
            if "reports_to" in p:
                body["reports_to"] = p.get("reports_to")
            return s.save_agent(body)
        if m == "agent.delete":
            a = s.require_agent(p.get("id"))
            if a["id"] in self.active:
                self.stop_agent(a["id"])
            return {"ok": True, "deleted": s.delete_agent(a["id"])["id"]}
        if m == "agent.save":
            if not p.get("id"):
                s.ensure_company()
            a = s.save_agent(p)
            if p.get("id") and ("model" in p or "provider" in p):
                self.sync_session_model(a)
            return a
        if m == "agent.pause":
            return s.set_agent_status(p.get("id"), "paused", reason=str(p.get("reason") or "dijeda pengguna"))
        if m == "agent.resume":
            a = s.require_agent(p.get("id"))
            if a["status"] != "paused" and a["status"] != "error":
                raise CompanyError("conflict", f"{a['name']} tidak sedang dijeda")
            if a["pause_reason"] == "budget" and s.budget_state(agent=a)["level"] == "exceeded" and not p.get("force"):
                raise CompanyError("conflict", f"Anggaran {a['name']} masih habis; naikkan anggaran dulu")
            return s.set_agent_status(a["id"], "idle")
        if m == "agent.stop":
            return self.stop_agent(int(p.get("id") or 0))
        if m == "agent.terminate":
            a = s.require_agent(p.get("id"))
            if a["id"] in self.active:
                self.stop_agent(a["id"])
            for t in s.q("SELECT id FROM tickets WHERE assignee_id=? AND status NOT IN ('done','cancelled')", (a["id"],)):
                s.release(t["id"], actor="system")
                s.assign_ticket(t["id"], None, actor="system")
            s.x("UPDATE agents SET reports_to=? WHERE reports_to=?", (a["reports_to"], a["id"]))
            return s.set_agent_status(a["id"], "terminated")
        if m == "agent.wake":
            return self.wake_now(int(p.get("id") or 0))
        if m == "agent.runs":
            return {"runs": s.q("SELECT r.*, t.key AS ticket_key FROM runs r LEFT JOIN tickets t ON t.id=r.ticket_id "
                                "WHERE r.agent_id=? ORDER BY r.id DESC LIMIT ?",
                                (int(p.get("id") or 0), int(p.get("limit") or 20)))}
        if m == "agent.chat":
            a = s.require_agent(p.get("id"))
            live = self.agent_session(a)
            return {"session_id": live.id}
        if m == "ticket.list":
            return {"tickets": s.list_tickets(status=p.get("status"), assignee_id=p.get("assignee_id"),
                                              project_id=p.get("project_id"), limit=int(p.get("limit") or 500))}
        if m == "ticket.get":
            return s.ticket_detail(p.get("id") or p.get("key"))
        if m == "ticket.save":
            if p.get("id"):
                t = s.update_ticket(p["id"], p)
                if "assignee_id" in p and p["assignee_id"] != t["assignee_id"]:
                    t = s.assign_ticket(t["id"], p["assignee_id"])
                    wake_assignee(t)
                return t
            t = s.create_ticket(p)
            wake_assignee(t)
            return t
        if m == "ticket.move":
            t = s.require_ticket(p.get("id"))
            to = str(p.get("status") or "")
            if to == "in_progress" and t["status"] != "in_progress":
                if not t["assignee_id"]:
                    raise CompanyError("conflict", f"{t['key']} belum punya penanggung jawab")
                t = s.checkout(t["id"], t["assignee_id"], None)
                return s.release(t["id"], actor="system")
            t = s.move_ticket(t["id"], to, actor="user")
            wake_assignee(t)
            return t
        if m == "ticket.assign":
            t = s.assign_ticket(p.get("id"), p.get("agent_id"))
            wake_assignee(t)
            return t
        if m == "ticket.checkout":
            return s.checkout(p.get("id"), int(p.get("agent_id") or 0), _int(p.get("run_id")))
        if m == "ticket.release":
            return s.release(p.get("id"))
        if m == "ticket.comment":
            c = s.comment(p.get("id"), str(p.get("body") or ""))
            t = s.require_ticket(c["ticket_id"])
            if t["assignee_id"] and t["status"] not in ("done", "cancelled", "backlog"):
                s.wake(t["assignee_id"], "comment", t["id"])
            return c
        if m == "ticket.block":
            return s.add_blocker(p.get("id"), p.get("blocker_id"))
        if m == "ticket.unblock":
            return s.remove_blocker(p.get("id"), p.get("blocker_id"))
        if m == "ticket.work_product":
            return s.add_work_product(p.get("id"), str(p.get("title") or ""), str(p.get("ref") or ""),
                                      str(p.get("kind") or "text"))
        if m == "approval.list":
            return {"approvals": s.list_approvals(p.get("status", "pending") or None)}
        if m == "approval.decide":
            decision = str(p.get("decision") or "")
            decision = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}.get(decision, decision)
            ap = s.decide(p.get("id"), decision, str(p.get("note") or ""))
            if ap["agent_id"] and ap["kind"] in ("plan", "review") and not (ap["kind"] == "review" and decision == "approved"):
                s.wake(ap["agent_id"], "approval", ap["ticket_id"])
                if ap["ticket_id"] and ap["kind"] == "plan":
                    s.comment(ap["ticket_id"], f"Rencana “{ap['title']}” {'disetujui' if decision == 'approved' else 'ditolak'}"
                              + (f": {ap['note']}" if ap["note"] else "."), actor="user")
            return ap
        if m == "costs":
            return s.costs(p.get("month"))
        if m == "activity":
            return {"items": s.activity(int(p.get("limit") or 100), _int(p.get("before")), p.get("entity"),
                                        _int(p.get("entity_id")))}
        if m == "routine.save":
            return s.save_routine(p)
        if m == "routine.delete":
            s.delete_routine(p.get("id"))
            return {"ok": True}
        if m == "routine.trigger":
            t = s.fire_routine(p.get("id"), actor="user")
            wake_assignee(t, "routine")
            return t
        raise CompanyError("not_found", f"metode tidak dikenal: {method}")

    def seed_demo(self, p: dict) -> dict:
        """A small sample company so the user sees the flow before building their own."""
        s = self.store
        if not s.company():
            s.setup(str(p.get("name") or "Neovarch Studio"),
                    str(p.get("mission") or "Membangun aplikasi yang membantu orang bekerja lebih ringan"))
        if s.q1("SELECT id FROM agents LIMIT 1"):
            raise CompanyError("conflict", "Perusahaan sudah punya pegawai")
        g = s.save_goal({"title": "Rilis versi berikutnya dengan stabil"})
        pr = s.save_project({"name": "Aplikasi desktop", "goal_id": g["id"]})
        dimas = s.save_agent({"name": "Dimas", "title": "CEO", "role": "ceo", "skip_approval": True,
                              "job_description": "Memecah tujuan perusahaan menjadi pekerjaan dan membaginya ke tim."})
        hana = s.save_agent({"name": "Hana", "title": "CTO", "role": "cto", "reports_to": dimas["id"], "skip_approval": True,
                             "job_description": "Memimpin teknik: merancang, meninjau, dan membagi tugas kode."})
        s.save_agent({"name": "Raka", "title": "Software Engineer", "role": "engineer", "reports_to": hana["id"],
                      "skip_approval": True, "job_description": "Menulis dan memperbaiki kode sesuai tiket."})
        s.save_agent({"name": "Sari", "title": "Marketing", "role": "marketing", "reports_to": dimas["id"],
                      "skip_approval": True, "job_description": "Menulis catatan rilis dan materi promosi."})
        s.create_ticket({"title": "Susun rencana rilis", "assignee_id": dimas["id"], "project_id": pr["id"],
                         "description": "Pecah rilis jadi tugas teknik dan pemasaran, lalu delegasikan."})
        return s.snapshot()
