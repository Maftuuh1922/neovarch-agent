"""Perusahaan through the gateway: RPC/REST, heartbeats with the mock model, tools, persona, Kantor desks."""

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from neovarch.server import Gateway, build_app
from neovarch.tools import office_summary, tool_schemas

import mock_llm
from test_server import WS


async def _gw(monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setenv("NEOVARCH_COMPANY_TICK", "0.05")
    gw = Gateway(isolated=False)
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    return gw, client


H = {"Authorization": "Bearer tok"}


async def post(c, method, body=None, status=200):
    r = await c.post(f"/api/company/{method}", json=body or {}, headers=H)
    data = await r.json()
    assert r.status == status, data
    return data


async def test_rest_requires_auth_and_reports_no_company(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        assert (await c.get("/api/company")).status == 401
        r = await c.get("/api/company", headers=H)
        assert (await r.json()) == {"exists": False}
        err = await post(c, "ticket.save", {"title": "x"}, status=400)
        assert err["code"] == "invalid"
        assert (await post(c, "nope", status=404))["code"] == "not_found"
    finally:
        await c.close()


async def test_seed_demo_and_rpc_errors(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        snap = await post(c, "seed_demo", {"autorun": False})
        names = {a["name"]: a for a in snap["agents"]}
        assert set(names) == {"Dimas", "Hana", "Raka", "Sari"}
        assert names["Raka"]["reports_to_name"] == "Hana"
        assert snap["company"]["autorun"] is False          # paused explicitly by this test
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        res = await ws.call("company.ticket.get", {"id": 999})
        assert res["error"]["code"] == -32004
        t = (await ws.call("company.ticket.list", {}))["result"]["tickets"][0]
        res = await ws.call("company.ticket.move", {"id": t["id"], "status": "done"})
        assert res["error"]["code"] == -32009
        await ws.ws.close()
    finally:
        await c.close()


async def test_manual_wake_runs_heartbeat_and_records_cost(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        await post(c, "update", {"price_in_per_mtok": 100, "price_out_per_mtok": 100})
        dimas = next(a for a in (await post(c, "snapshot"))["agents"] if a["name"] == "Raka")
        await post(c, "ticket.save", {"title": "Perbaiki build", "assignee_id": dimas["id"]})
        await post(c, "agent.wake", {"id": dimas["id"]})
        err = await post(c, "agent.wake", {"id": dimas["id"]}, status=409)   # one run per agent
        assert "sedang bekerja" in err["error"]
        await asyncio.wait_for(gw.company.active[dimas["id"]], 20)
        runs = (await post(c, "agent.runs", {"id": dimas["id"]}))["runs"]
        assert runs[0]["status"] == "succeeded" and runs[0]["ticket_key"] == "NV-2"
        assert runs[0]["prompt_tokens"] + runs[0]["completion_tokens"] > 0
        t = await post(c, "ticket.get", {"id": "NV-2"})
        assert t["status"] == "in_progress" and t["locked"] is False      # lock released after the run
        assert t["comments"] and t["comments"][-1]["author_name"] == "Raka"
        assert "neovarch-tool-ok" in t["comments"][-1]["body"]    # the mock ran a real tool, then answered
        costs = await post(c, "costs")
        row = next(r for r in costs["by_agent"] if r["name"] == "Raka")
        assert row["tokens"] > 0 and row["cents"] > 0
        a = next(a for a in (await post(c, "snapshot"))["agents"] if a["name"] == "Raka")
        assert a["status"] == "idle" and a["session_id"]
        rec = gw.store.find(a["session_id"])
        assert rec["source"] == "company" and rec["company_agent_id"] == dimas["id"]
        acts = [x["action"] for x in (await post(c, "activity"))["items"]]
        assert "run.started" in acts and "run.succeeded" in acts and "agent.woken" in acts
    finally:
        await c.close()


async def test_autorun_scheduler_assignment_and_parallel_limit(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        agents = {a["name"]: a for a in (await post(c, "snapshot"))["agents"]}
        await post(c, "ticket.save", {"title": "Tulis catatan rilis", "assignee_id": agents["Sari"]["id"]})
        await asyncio.sleep(0.3)
        assert not gw.company.active                       # autorun off: nothing ran
        await post(c, "update", {"autorun": True, "max_parallel": 1})
        gw.company.start()
        seen_parallel = 0
        for _ in range(400):
            seen_parallel = max(seen_parallel, len(gw.company.active))
            d1, d2 = await post(c, "ticket.get", {"id": "NV-1"}), await post(c, "ticket.get", {"id": "NV-2"})
            if d1["comments"] and d2["comments"] and not gw.company.active:
                break
            await asyncio.sleep(0.05)
        assert seen_parallel <= 1
        tickets = {t["key"]: t for t in (await post(c, "ticket.list"))["tickets"]}
        assert tickets["NV-1"]["status"] == "review" and tickets["NV-2"]["status"] == "in_progress"
        await gw.company.stop()
    finally:
        await c.close()


async def test_paused_and_over_budget_agents_do_not_run(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        dimas = next(a for a in (await post(c, "snapshot"))["agents"] if a["name"] == "Dimas")
        await post(c, "agent.pause", {"id": dimas["id"]})
        assert "dijeda" in (await post(c, "agent.wake", {"id": dimas["id"]}, status=409))["error"]
        await post(c, "agent.resume", {"id": dimas["id"]})
        await post(c, "agent.save", {"id": dimas["id"], "budget_monthly_tokens": 1})
        gw.company.store.record_cost(agent_id=dimas["id"], prompt_tokens=5, completion_tokens=0)
        res = await gw.company.run_heartbeat(dimas["id"], "manual")
        assert res == {"status": "skipped", "reason": "paused"}
        err = await post(c, "agent.resume", {"id": dimas["id"]}, status=409)
        assert "Anggaran" in err["error"]
    finally:
        await c.close()


async def test_agent_tools_delegate_review_escalate(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        ag = {a["name"]: a for a in s.agents_public()}
        dimas_live = gw.company.agent_session(s.agent(ag["Dimas"]["id"]))
        b = gw.company.bindings[dimas_live.id]
        names = {t["function"]["name"] for t in tool_schemas(dimas_live.ctx)}
        assert {"company_delegate", "company_ticket_update", "office_status"} <= names
        assert "company_delegate" not in {t["function"]["name"] for t in tool_schemas()}
        b.ticket_id = s.ticket("NV-1")["id"]
        s.checkout(b.ticket_id, ag["Dimas"]["id"], None)
        out = await b.run_tool("company_delegate", {"title": "Perbaiki crash", "assignee": "Raka"})
        assert out.startswith("NV-2 dibuat untuk Raka")      # Raka reports to Hana who reports to Dimas
        assert (await b.run_tool("company_delegate", {"title": "x", "assignee": "Dimas"})).startswith("error:")
        child = s.ticket("NV-2")
        assert child["parent_id"] == b.ticket_id and child["assignee_id"] == ag["Raka"]["id"]
        assert s.q1("SELECT * FROM wakeups WHERE agent_id=?", (ag["Raka"]["id"],))["reason"] == "assignment"

        raka_live = gw.company.agent_session(s.agent(ag["Raka"]["id"]))
        rb = gw.company.bindings[raka_live.id]
        rb.ticket_id = child["id"]
        s.checkout(child["id"], ag["Raka"]["id"], None)
        assert "bukan tiketmu" in await rb.run_tool("company_comment", {"ticket": "NV-1", "body": "hai"})
        out = await rb.run_tool("company_ticket_update", {"status": "done", "comment": "Sudah diperbaiki"})
        assert "ditinjau" in out and s.ticket("NV-2")["status"] == "review"
        [ap] = [a for a in s.list_approvals() if a["kind"] == "review"]
        ap = await post(c, "approval.decide", {"id": ap["id"], "decision": "approve"})
        assert ap["status"] == "approved" and s.ticket("NV-2")["status"] == "done"

        s.save_agent({"name": "Budi", "title": "QA", "reports_to": ag["Hana"]["id"], "skip_approval": True})
        t3 = s.create_ticket({"title": "Uji", "assignee_id": ag["Raka"]["id"]})
        rb.ticket_id = t3["id"]
        s.checkout(t3["id"], ag["Raka"]["id"], None)
        out = await rb.run_tool("company_escalate", {"reason": "butuh akses server"})
        assert "atasanmu" in out and s.ticket(t3["id"])["status"] == "blocked"
        assert s.q1("SELECT * FROM wakeups WHERE agent_id=? AND reason='escalation'", (ag["Hana"]["id"],))
        res = await gw.company.run_heartbeat(ag["Hana"]["id"], "escalation", t3["id"])
        assert res["status"] == "succeeded" and res["ticket"] == t3["key"]
        assert s.ticket(t3["id"])["assignee_id"] == ag["Raka"]["id"]     # supervising does not steal the ticket
    finally:
        await c.close()


async def test_persona_and_office_desks(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        hana = next(a for a in s.agents_public() if a["name"] == "Hana")
        t = s.create_ticket({"title": "Rancang arsitektur sinkronisasi", "assignee_id": hana["id"]})
        s.checkout(t["id"], hana["id"], None)
        chat = await post(c, "agent.chat", {"id": hana["id"]})
        live = gw.live[chat["session_id"]]
        persona = live.ctx.persona()
        assert "Kamu adalah Hana, CTO" in persona and "Atasan: Dimas (CEO)" in persona
        assert "Raka (Software Engineer)" in persona and t["key"] in persona
        assert "Misi perusahaan" in persona and "lagi apa" in persona
        live.submit("lagi apa kamu?")
        await live.task
        sent = mock_provider.app[mock_llm.REQUESTS][-1]["messages"][0]["content"]
        assert "Kamu adalah Hana" in sent and t["key"] in sent

        snap = gw.office.snapshot()
        desks = {d["id"]: d for d in snap["agents"]}
        d = desks[f"company:{hana['id']}"]
        assert d["kind"] == "company" and d["role"] == "CTO" and d["company"]["ticket_key"] == t["key"]
        assert d["company"]["ticket_status"] == "in_progress"
        assert not any(x.get("kind") == "session" and x.get("session_id") == chat["session_id"] for x in snap["agents"])
        summary = office_summary(gw.office_status())
        assert "Perusahaan: Neovarch Studio" in summary and "Hana (CTO)" in summary
        # usage from the chat turn is booked on Hana
        assert s.spend(agent_id=hana["id"])["tokens"] > 0
    finally:
        await c.close()


async def test_restart_recovers_stuck_runs(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        dimas = s.agents_public()[0]
        run = s.start_run(dimas["id"], "manual", 1)
        s.checkout(1, dimas["id"], run)
        s.set_agent_status(dimas["id"], "running", log=False)
    finally:
        await c.close()
    gw2, c2 = await _gw(monkeypatch)
    try:
        s2 = gw2.company.store
        assert s2.ticket(1)["checkout_run_id"] is None and s2.ticket(1)["status"] == "in_progress"
        assert s2.agent(dimas["id"])["status"] == "idle"
        assert s2.q1("SELECT status, error FROM runs WHERE id=?", (run,))["status"] == "failed"
    finally:
        await c2.close()


async def test_routine_trigger_and_comment_wakes(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        sari = next(a for a in s.agents_public() if a["name"] == "Sari")
        r = await post(c, "routine.save", {"name": "Ringkasan mingguan", "schedule": "every 7d", "agent_id": sari["id"]})
        t = await post(c, "routine.trigger", {"id": r["id"]})
        assert t["assignee_id"] == sari["id"]
        s.x("DELETE FROM wakeups")
        await post(c, "ticket.comment", {"id": t["id"], "body": "Tolong pakai nada santai"})
        assert s.q1("SELECT reason FROM wakeups WHERE agent_id=?", (sari["id"],))["reason"] == "comment"
    finally:
        await c.close()


async def test_agent_model_pick_follows_session_and_desk_put(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        hana = next(a for a in s.agents_public() if a["name"] == "Hana")
        chat = await post(c, "agent.chat", {"id": hana["id"]})
        sid = chat["session_id"]
        assert not gw.live[sid].rec.get("model_override")
        await post(c, "agent.save", {"id": hana["id"], "model": "mock-model-2", "provider": "custom"})
        assert gw.live[sid].rec["model_override"] == {"model": "mock-model-2", "provider": "custom"}
        await post(c, "agent.save", {"id": hana["id"], "model": "", "provider": ""})
        assert not gw.live[sid].rec.get("model_override")
        default_before = gw.model_info()["model"]
        # Kantor desk popover on a company desk changes that agent only, never the PC default
        r = await c.put(f"/api/agents/company:{hana['id']}/model", json={"model": "mock-model-3"}, headers=H)
        body = await r.json()
        assert r.status == 200 and body["scope"] == "agent", body
        assert s.agent(hana["id"])["model"] == "mock-model-3"
        assert gw.model_info()["model"] == default_before
        r = await c.put("/api/agents/company:9999/model", json={"model": "x"}, headers=H)
        assert r.status == 404
    finally:
        await c.close()


async def test_ceo_strategy_flow_creates_and_assigns_tickets(mock_provider, monkeypatch):
    """Paperclip flow: goal → CEO strategy heartbeat → board approval → tickets for the team, assignees woken."""
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        snap = await post(c, "snapshot")
        ag = {a["name"]: a for a in snap["agents"]}
        dimas = ag["Dimas"]
        nv1 = await post(c, "ticket.get", {"id": "NV-1"})
        assert nv1["kind"] == "strategy" and nv1["assignee_id"] == dimas["id"]
        await post(c, "agent.wake", {"id": dimas["id"]})
        await asyncio.wait_for(gw.company.active[dimas["id"]], 20)
        nv1 = await post(c, "ticket.get", {"id": "NV-1"})
        assert nv1["status"] == "review"
        aps = (await post(c, "approval.list"))["approvals"]
        st = next(a for a in aps if a["kind"] == "strategy")
        assert [t["assignee"] for t in st["payload"]["tickets"]] == ["Hana", "Raka", "Sari"]
        assert any(x["type"] == "comment" and "Strategi" in x["body"] for x in nv1["timeline"])
        await post(c, "approval.decide", {"id": st["id"], "decision": "approve", "note": "gas"})
        tickets = {t["title"]: t for t in (await post(c, "ticket.list"))["tickets"]}
        assert tickets["Tulis catatan rilis"]["assignee_id"] == ag["Sari"]["id"]
        assert tickets["Rancang arsitektur rilis"]["parent_id"] == nv1["id"]
        assert (await post(c, "ticket.get", {"id": "NV-1"}))["status"] == "done"
        woken = {w["agent_id"] for w in gw.company.store.q("SELECT agent_id FROM wakeups")}
        assert {ag["Hana"]["id"], ag["Raka"]["id"], ag["Sari"]["id"]} <= woken
        tl = (await post(c, "ticket.get", {"id": "NV-1"}))["timeline"]
        kinds = {x["type"] for x in tl}
        assert {"comment", "event", "run"} <= kinds            # one thread: comments + audit + heartbeat runs
    finally:
        await c.close()


async def test_strategy_revision_and_reject(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        dimas = s.ceo()
        ap = s.create_approval("strategy", ticket_id=1, agent_id=dimas["id"], requested_by="agent", actor_id=dimas["id"],
                               title="Strategi CEO: x", payload={"plan": "p", "tickets": [{"title": "a"}]})
        s.move_ticket(1, "review", actor="agent", actor_id=dimas["id"], force=True)
        r = await post(c, "approval.decide", {"id": ap["id"], "decision": "revise", "note": "tambah QA"})
        assert r["status"] == "revision_requested"
        assert s.ticket(1)["status"] == "todo"
        assert s.q1("SELECT * FROM wakeups WHERE agent_id=? AND reason='approval'", (dimas["id"],))
        ap2 = s.create_approval("strategy", ticket_id=1, agent_id=dimas["id"], requested_by="agent",
                                actor_id=dimas["id"], title="Strategi CEO: y", payload={"tickets": []})
        await post(c, "approval.decide", {"id": ap2["id"], "decision": "reject"})
        assert s.ticket(1)["status"] == "backlog"          # rejected: the CEO does not retry on its own
        err = await post(c, "approval.decide", {"id": s.create_approval("review", ticket_id=1)["id"],
                                                "decision": "revise"}, status=400)
        assert "revisi" in err["error"]
    finally:
        await c.close()


async def test_heartbeat_default_on_and_pause_switch(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        snap = await post(c, "seed_demo")
        assert snap["company"]["autorun"] is True           # heartbeat on once a company exists
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        r = await ws.call("company.heartbeat", {"on": False})
        assert r["result"]["autorun"] is False
        await ws.ws.close()
        acts = [x["action"] for x in (await post(c, "activity", {"limit": 20}))["items"]]
        assert "company.heartbeat_off" in acts
        await post(c, "heartbeat", {"on": True})
        assert (await post(c, "snapshot"))["company"]["autorun"] is True
    finally:
        await c.close()


async def test_live_activity_event_and_incremental_feed(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    seen = []
    orig = gw.broadcast_event
    gw.broadcast_event = lambda kind, sid, payload: (seen.append((kind, payload)), orig(kind, sid, payload))[1]
    try:
        await post(c, "seed_demo", {"autorun": False})
        last = (await post(c, "activity", {"limit": 1}))["items"][0]["id"]
        sari = next(a for a in (await post(c, "snapshot"))["agents"] if a["name"] == "Sari")
        await post(c, "ticket.save", {"title": "Poster rilis", "assignee_id": sari["id"]})
        live = [p for k, p in seen if k == "company.activity"]
        assert live and live[-1]["action"] == "ticket.created" and live[-1]["id"] > last
        newer = (await post(c, "activity", {"after": last}))["items"]
        assert [x["action"] for x in newer] == ["ticket.created"]
        mine = (await post(c, "activity", {"agent_id": sari["id"]}))["items"]
        assert mine and all(x["entity"] == "agent" or x["actor_id"] == sari["id"] for x in mine)
    finally:
        await c.close()


async def test_live_budget_stop_interrupts_and_asks_board(mock_provider, monkeypatch):
    """Per-call usage is recorded live; crossing the agent's token budget pauses it, halts the run and
    files a budget approval; approving raises the budget and resumes."""
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        raka = next(a for a in s.q("SELECT * FROM agents WHERE name='Raka'"))
        await post(c, "agent.save", {"id": raka["id"], "budget_monthly_tokens": 100})
        live = gw.company.agent_session(s.agent(raka["id"]))
        b = gw.company.bindings[live.id]
        halted = []
        gw.company.active[raka["id"]] = asyncio.get_running_loop().create_future()
        gw.company.halt_run = lambda aid, why: halted.append((aid, why))
        gw.company.observe("usage.update", live.id, {"prompt_tokens": 60, "completion_tokens": 10, "model": "free-x"})
        assert s.agent(raka["id"])["status"] == "idle" and not halted
        gw.company.observe("usage.update", live.id, {"prompt_tokens": 40, "completion_tokens": 0, "model": "free-x"})
        assert s.agent(raka["id"])["status"] == "paused" and s.agent(raka["id"])["pause_reason"] == "budget"
        assert halted == [(raka["id"], "anggaran habis")]
        # the turn's own total must not be counted a second time
        gw.company.observe("message.complete", live.id, {"usage": {"prompt_tokens": 100, "completion_tokens": 10}})
        assert s.spend(agent_id=raka["id"])["tokens"] == 110
        assert b.usage_seen is False
        ap = next(a for a in s.list_approvals() if a["kind"] == "budget")
        assert ap["payload"]["extra_tokens"] == 100
        gw.company.active.pop(raka["id"]).cancel()
        await post(c, "approval.decide", {"id": ap["id"], "decision": "approve"})
        a = s.agent(raka["id"])
        assert a["budget_monthly_tokens"] == 200 and a["status"] == "idle"
    finally:
        await c.close()


async def test_agent_hire_request_always_needs_board(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        await post(c, "seed_demo", {"autorun": False})
        s = gw.company.store
        s.update_company({"require_hire_approval": False})
        hana = s.q1("SELECT * FROM agents WHERE name='Hana'")
        raka = s.q1("SELECT * FROM agents WHERE name='Raka'")
        from neovarch.company_runtime import CompanyBinding
        out = await CompanyBinding(gw.company, hana["id"]).run_tool("company_hire", {"name": "Budi", "title": "QA"})
        assert "dewan" in out
        budi = s.q1("SELECT * FROM agents WHERE name='Budi'")
        assert budi["status"] == "pending_approval" and budi["reports_to"] == hana["id"]
        assert any(a["kind"] == "hire" and a["agent_id"] == budi["id"] for a in s.list_approvals())
        out = await CompanyBinding(gw.company, raka["id"]).run_tool("company_hire", {"name": "Cici", "title": "x"})
        assert out.startswith("error:")                      # no team, not CEO
        out = await CompanyBinding(gw.company, hana["id"]).run_tool(
            "company_propose_strategy", {"plan": "p", "tickets": [{"title": "a"}]})
        assert out.startswith("error:") and "CEO" in out
    finally:
        await c.close()
