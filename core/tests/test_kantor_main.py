"""Kantor run by the main agent: empty start, Organisasi → Agency → Orang, hire/fire/move, tasks, tools."""

import json

from aiohttp.test_utils import TestClient, TestServer

from neovarch.company import CompanyStore
from neovarch.server import Gateway, build_app
from neovarch.tools import ToolContext, run_tool, tool_schemas

H = {"Authorization": "Bearer tok"}


async def _gw(monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setenv("NEOVARCH_COMPANY_TICK", "30")
    gw = Gateway(isolated=False)
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    return gw, client


async def post(c, method, body=None, status=200):
    r = await c.post(f"/api/company/{method}", json=body or {}, headers=H)
    data = await r.json()
    assert r.status == status, data
    return data


def test_units_nest_without_limit_and_delete_moves_people_up(home):
    s = CompanyStore()
    s.ensure_company()
    org = s.save_unit({"name": "Neovarch Labs"})
    assert org["kind"] == "organisasi"
    parent = org
    for i in range(6):  # unlimited depth
        parent = s.save_unit({"name": f"Agency {i}", "parent_id": parent["id"]})
        assert parent["kind"] == "agency"
    a = s.save_agent({"name": "Budi", "title": "Desainer", "unit_id": parent["id"], "skills": "figma, ui",
                      "tools": ["read_file"], "persona": "teliti"})
    assert a["status"] == "idle"  # hires through the main agent need no extra approval
    pub = next(x for x in s.agents_public() if x["id"] == a["id"])
    assert pub["skills"] == ["figma", "ui"] and pub["tools"] == ["read_file"] and pub["unit_name"] == "Agency 5"
    up = s.unit(parent["parent_id"])
    s.delete_unit(parent["id"])
    assert s.agent(a["id"])["unit_id"] == up["id"]
    try:
        s.save_unit({"id": org["id"], "parent_id": up["id"]})
        raise AssertionError("cycle accepted")
    except Exception as exc:
        assert "melingkar" in str(exc)
    assert len(s.snapshot()["units"]) == 6


def test_delete_agent_frees_tickets_and_reports(home):
    s = CompanyStore()
    s.ensure_company()
    boss = s.save_agent({"name": "Dewi"})
    w = s.save_agent({"name": "Eko", "reports_to": boss["id"]})
    t = s.create_ticket({"title": "Tulis", "assignee_id": boss["id"]})
    s.delete_agent(boss["id"])
    assert s.agent(boss["id"]) is None
    assert s.require_ticket(t["id"])["assignee_id"] is None
    assert s.agent(w["id"])["reports_to"] is None
    assert [a["name"] for a in s.agents_public()] == ["Eko"]


async def test_kantor_starts_empty_and_main_tool_runs_it(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        assert (await (await c.get("/api/company", headers=H)).json()) == {"exists": False}
        assert gw.office.snapshot()["agents"] == []
        t = gw.company.main_tool
        assert "kosong" in t({"action": "overview"})
        assert "dibuat" in t({"action": "create_org", "name": "Neovarch Labs"})
        assert "dibuat" in t({"action": "create_agency", "name": "Kreatif", "parent": "Neovarch Labs"})
        out = t({"action": "hire", "name": "Sinta", "title": "Copywriter", "unit": "Kreatif",
                 "skills": ["menulis"], "persona": "ceria"})
        assert "Sinta direkrut" in out and "Kreatif" in out
        assert "Sinta" in t({"action": "overview"}) and "[agency] Kreatif" in t({"action": "overview"})
        assert "diberikan ke Sinta" in t({"action": "assign_task", "employee": "Sinta", "title": "Caption IG"})
        assert "dipindah ke Neovarch Labs" in t({"action": "move", "name": "Sinta", "unit": "Neovarch Labs"})
        assert "diperbarui" in t({"action": "set_employee", "name": "Sinta", "model": "x/y", "provider": "custom",
                                  "tools": ["read_file", "web_fetch"]})
        snap = await post(c, "snapshot")
        sinta = next(a for a in snap["agents"] if a["name"] == "Sinta")
        assert sinta["model"] == "x/y" and sinta["tools"] == ["read_file", "web_fetch"]
        desks = gw.office.snapshot()["agents"]
        assert [d["name"] for d in desks] == ["Sinta"]
        assert t({"action": "hire", "name": "Sinta"}).startswith("error:")
        assert "diberhentikan" in t({"action": "fire", "name": "Sinta"})
        assert gw.office.snapshot()["agents"] == []
        assert t({"action": "fire", "name": "Sinta"}).startswith("error:")
        assert "dihapus" in t({"action": "delete_unit", "unit": "Kreatif"})
    finally:
        await c.close()


async def test_rest_unit_and_agent_delete(mock_provider, monkeypatch):
    gw, c = await _gw(monkeypatch)
    try:
        org = await post(c, "unit.save", {"name": "Org A"})  # creates the Kantor on demand
        ag = await post(c, "unit.save", {"name": "Agency B", "parent_id": org["id"]})
        a = await post(c, "agent.save", {"name": "Rudi", "unit_id": ag["id"]})
        moved = await post(c, "agent.move", {"id": a["id"], "unit_id": org["id"]})
        assert moved["unit_id"] == org["id"]
        assert (await post(c, "agent.delete", {"id": a["id"]}))["ok"] is True
        snap = await post(c, "snapshot")
        assert snap["agents"] == [] and [u["name"] for u in snap["units"]] == ["Org A", "Agency B"]
        await post(c, "unit.delete", {"id": org["id"]})
        assert [u["parent_id"] for u in (await post(c, "unit.list"))["units"]] == [None]
    finally:
        await c.close()


async def test_kantor_tool_only_for_the_main_agent(home):
    calls = []
    main = ToolContext(cwd=home, approve=None, kantor=lambda a: calls.append(a) or "ok")
    names = {t["function"]["name"] for t in tool_schemas(main)}
    assert "kantor" in names
    assert await run_tool("kantor", {"action": "overview"}, main) == "ok" and calls

    class Emp:
        def tool_schemas(self):
            return []

        def tool_names(self):
            return set()

        def allowed_tools(self):
            return {"read_file"}

    emp = ToolContext(cwd=home, approve=None, kantor=lambda a: "ok", company=Emp())
    names = {t["function"]["name"] for t in tool_schemas(emp)}
    # send_file: deliver files into the chat; grep/glob come with read_file (read-only search)
    assert names == {"read_file", "grep", "glob", "repo_map", "office_status", "send_file"}
    assert (await run_tool("shell", {"command": "true"}, emp)).startswith("refused")
    assert (await run_tool("kantor", {}, emp)).startswith("refused")
    plain = ToolContext(cwd=home, approve=None)
    assert "kantor" not in {t["function"]["name"] for t in tool_schemas(plain)}
    assert json.dumps(tool_schemas(main))  # schemas stay serialisable
