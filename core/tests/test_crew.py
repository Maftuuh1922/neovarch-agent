"""Crew: the main agent designs a small team, the user approves, the engine runs it."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from neovarch import crew as crewmod
from neovarch.crew import CrewEngine, CrewError, CrewStore, normalize


@pytest.fixture
def store(tmp_path):
    return CrewStore(tmp_path / "crews.json")


def design_json(**over) -> str:
    d = {"title": "Riset harga laptop", "process": "sequential",
         "members": [{"id": "m1", "name": "Rani", "role": "Peneliti", "goal": "cari data", "tools": ["web"]},
                     {"id": "m2", "name": "Bayu", "role": "Analis", "goal": "ringkas", "tools": []}],
         "tasks": [{"id": "t1", "title": "Cari", "description": "cari harga", "member_id": "m1"},
                   {"id": "t2", "title": "Ringkas", "description": "ringkas temuan", "member_id": "m2"}]}
    d.update(over)
    return "Berikut rancangannya:\n```json\n" + json.dumps(d) + "\n```"


class Recorder:
    """A fake member turn: returns '<role> selesai' and records each prompt."""

    def __init__(self, gate: asyncio.Event | None = None):
        self.prompts: list[tuple[str, str]] = []
        self.gate = gate

    async def __call__(self, c, m, prompt):
        self.prompts.append((m["id"], prompt))
        if self.gate is not None:
            await self.gate.wait()
        return f"{m['role']} selesai #{len(self.prompts)}"


# ------------------------------------------------------------------ design --
def test_templates_are_valid_and_cover_the_four_kinds():
    assert set(crewmod.TEMPLATES) == {"riset", "konten", "coding", "riset_laporan"}
    for key in crewmod.TEMPLATES:
        d = crewmod.from_template(key, "tujuan X")
        assert d["members"] and d["tasks"]
        assert all(t["member_id"] in {m["id"] for m in d["members"]} for t in d["tasks"])
        assert "{goal}" not in json.dumps(d)
    assert crewmod.from_template("coding", "x")["process"] == "hierarchical"
    assert crewmod.from_template("coding", "x")["side_effects"] == ["shell", "write"]
    assert crewmod.from_template("riset", "x")["side_effects"] == []
    assert [t["id"] for t in crewmod.templates_payload()] == list(crewmod.TEMPLATES)


@pytest.mark.parametrize("goal,key", [
    ("Perbaiki bug login di repo saya", "coding"),
    ("Tulis artikel blog tentang kopi", "konten"),
    ("Buat laporan pasar EV Indonesia", "riset_laporan"),
    ("Bandingkan harga laptop gaming", "riset"),
    ("sesuatu yang lain", "riset"),
])
def test_pick_template(goal, key):
    assert crewmod.pick_template(goal) == key


def test_normalize_rejects_bad_designs(monkeypatch):
    base = json.loads(design_json().split("```json\n")[1].split("\n```")[0])
    with pytest.raises(CrewError, match="alat tidak dikenal"):
        normalize({**base, "members": [{"role": "x", "tools": ["root"]}]})
    with pytest.raises(CrewError, match="alur tidak dikenal"):
        normalize({**base, "process": "random"})
    with pytest.raises(CrewError, match="maksimal"):
        normalize({**base, "members": [{"role": f"r{i}"} for i in range(9)]})
    with pytest.raises(CrewError, match="peran"):
        normalize({**base, "members": [{"name": "tanpa peran"}]})
    with pytest.raises(CrewError) as e:
        normalize({**base, "members": [{"role": "x", "model": "openai/gpt-5"}]})
    assert e.value.code == "paid_model"
    ok = normalize({**base, "members": [{"role": "x", "model": "oc/mimo-v2.6-flash-free"}]})
    assert ok["members"][0]["model"] == "oc/mimo-v2.6-flash-free"
    with pytest.raises(CrewError, match="manajer"):
        normalize({**base, "process": "hierarchical", "manager": "nobody"})
    # unknown task assignee falls back to a worker; hierarchical keeps the manager out of plain work
    d = normalize({**base, "process": "hierarchical", "manager": "m1",
                   "tasks": [{"title": "a", "member_id": "ghost"}]})
    assert d["tasks"][0]["member_id"] == "m2"
    assert d["manager"] == "m1"


async def test_propose_uses_the_main_agent_design(store):
    asked = []

    async def ask(prompt):
        asked.append(prompt)
        return design_json()

    e = CrewEngine(store, ask=ask, run_member=Recorder())
    c = await e.propose("Riset harga laptop gaming 2026")
    assert c["status"] == "proposed" and c["designed_by"] == "agent"
    assert c["title"] == "Riset harga laptop"
    assert [m["role"] for m in c["members"]] == ["Peneliti", "Analis"]
    assert "Riset harga laptop gaming 2026" in asked[0]
    assert c["allow_side_effects"] is False


@pytest.mark.parametrize("answer", ["maaf saya tidak bisa", design_json(process="chaos"), RuntimeError("down")])
async def test_propose_falls_back_to_a_template(store, answer):
    async def ask(_):
        if isinstance(answer, Exception):
            raise answer
        return answer

    e = CrewEngine(store, ask=ask, run_member=Recorder())
    c = await e.propose("Tulis artikel tentang kopi Gayo")
    assert c["designed_by"] == "template" and c["template"] == "konten"
    assert c["note"]
    assert len(c["members"]) == 3


async def test_explicit_template_skips_the_designer(store):
    async def ask(_):
        raise AssertionError("designer must not be called")

    c = await CrewEngine(store, ask=ask, run_member=Recorder()).propose("apa saja", "riset_laporan")
    assert c["template"] == "riset_laporan" and c["designed_by"] == "template"
    with pytest.raises(CrewError):
        await CrewEngine(store).propose("x", "tidak-ada")
    with pytest.raises(CrewError, match="tujuan"):
        await CrewEngine(store).propose("   ")


# --------------------------------------------------------------- approval --
async def test_nothing_runs_before_approval_and_side_effects_need_consent(store):
    rec = Recorder()
    e = CrewEngine(store, run_member=rec)
    c = await e.propose("Perbaiki bug login", "coding")
    await asyncio.sleep(0.01)
    assert rec.prompts == [] and store.get(c["id"])["status"] == "proposed"
    with pytest.raises(CrewError) as err:
        e.approve(c["id"])
    assert err.value.code == "needs_consent"
    assert rec.prompts == []
    e.approve(c["id"], allow_side_effects=True)
    done = await e.wait(c["id"])
    assert done["status"] == "done" and done["allow_side_effects"] is True


async def test_sequential_passes_earlier_results_on(store):
    rec = Recorder()
    events = []
    e = CrewEngine(store, run_member=rec, on_change=events.append)
    c = await e.propose("Bandingkan harga laptop", "riset")
    e.approve(c["id"])
    done = await e.wait(c["id"])
    assert done["status"] == "done"
    assert [m for m, _ in rec.prompts] == ["m1", "m2"]
    assert "Peneliti selesai #1" in rec.prompts[1][1]           # task 2 sees task 1's result
    assert "Bandingkan harga laptop" in rec.prompts[0][1]
    assert done["final_output"] == "Analis selesai #2"
    assert all(t["status"] == "done" for t in done["tasks"])
    assert all(m["status"] == "done" for m in done["members"])
    statuses = [ev.get("status") for ev in events]
    assert "running" in statuses and statuses[-1] == "done"
    assert any(m["status"] == "working" for ev in events for m in ev.get("members", []))


async def test_hierarchical_manager_reviews_and_asks_one_revision(store):
    rec = Recorder()
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        if "Periksa hasil" in prompt:
            return "REVISI: tambahkan tes" if sum("Periksa hasil" in p for p in calls) == 1 else "OK"
        if "jawaban akhir" in prompt:
            return "Ringkasan akhir manajer"
        return design_json()

    e = CrewEngine(store, ask=ask, run_member=rec)
    c = await e.propose("x", "coding")
    e.approve(c["id"], allow_side_effects=True)
    done = await e.wait(c["id"])
    assert done["status"] == "done", done["error"]
    workers = [m for m, _ in rec.prompts]
    assert "m1" not in workers                                  # the manager delegates, it does not do the tasks
    assert workers == ["m2", "m2", "m3", "m4"]                  # first task redone once after REVISI
    assert "tambahkan tes" in rec.prompts[1][1]
    assert done["final_output"] == "Ringkasan akhir manajer"
    assert any("minta revisi" in row["text"] for row in done["log"])


async def test_cancel_stops_a_running_crew(store):
    gate = asyncio.Event()
    e = CrewEngine(store, run_member=Recorder(gate))
    c = await e.propose("x", "riset")
    e.approve(c["id"])
    await asyncio.sleep(0.02)
    with pytest.raises(CrewError):
        e.update(c["id"], {"process": "sequential"})            # no edits while it works
    with pytest.raises(CrewError):
        e.delete(c["id"])
    e.cancel(c["id"])
    done = await e.wait(c["id"])
    assert done["status"] == "cancelled"
    assert done["tasks"][0]["status"] == "cancelled" and done["tasks"][1]["status"] == "skipped"


async def test_failure_is_reported(store):
    async def boom(c, m, p):
        raise RuntimeError("model mati")

    e = CrewEngine(store, run_member=boom)
    c = await e.propose("x", "riset")
    e.approve(c["id"])
    done = await e.wait(c["id"])
    assert done["status"] == "failed" and "model mati" in done["error"]


# ---------------------------------------------------------------- Lanjutan --
async def test_lanjutan_edit_validates_and_resets_consent(store):
    e = CrewEngine(store, run_member=Recorder())
    c = await e.propose("x", "riset")
    members = c["members"] + [{"id": "m3", "name": "Oka", "role": "Programmer", "tools": ["shell"]}]
    tasks = c["tasks"] + [{"id": "t3", "title": "Skrip", "description": "jalankan", "member_id": "m3"}]
    c2 = e.update(c["id"], {"members": members, "tasks": tasks, "title": "Baru", "process": "hierarchical",
                            "manager": "m1"})
    assert c2["title"] == "Baru" and c2["process"] == "hierarchical" and c2["side_effects"] == ["shell"]
    with pytest.raises(CrewError) as err:
        e.update(c["id"], {"members": [{"role": "x", "model": "anthropic/claude"}]})
    assert err.value.code == "paid_model"
    with pytest.raises(CrewError):
        e.approve(c["id"])                                       # new shell tool -> consent needed again
    e.approve(c["id"], allow_side_effects=True)
    done = await e.wait(c["id"])
    # editing a finished crew makes it a proposal again
    again = e.update(c["id"], {"title": "Ulang"})
    assert done["status"] == "done" and again["status"] == "proposed" and again["final_output"] == ""


async def test_store_persists_and_marks_interrupted_runs(tmp_path):
    path = tmp_path / "crews.json"
    s1 = CrewStore(path)
    gate = asyncio.Event()
    e = CrewEngine(s1, run_member=Recorder(gate))
    c = await e.propose("x", "riset")
    e.approve(c["id"])
    await asyncio.sleep(0.02)
    s2 = CrewStore(path)                                         # the core restarted mid-run
    assert s2.get(c["id"])["status"] == "failed"
    assert "dimulai ulang" in s2.get(c["id"])["error"]
    e.cancel(c["id"])
    await e.wait(c["id"])
    assert [x["id"] for x in CrewEngine(CrewStore(path)).list()] == [c["id"]]


def test_member_model_is_always_free(home):
    from neovarch import config as cfgmod
    from neovarch import router9
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "gpt-paid", "base_url": "http://x/v1"}
    assert crewmod.member_model({}, cfg) == {"model": router9.DEFAULT_MODEL, "provider": router9.PROVIDER}
    free = "oc/mimo-v2.6-flash-free"
    assert crewmod.member_model({"model": free}, cfg) == {"model": free, "provider": router9.PROVIDER}
    assert crewmod.member_model({}, {}) is None                  # built-in default is already free


def test_binding_limits_tools_and_side_effects():
    m = {"name": "Fajar", "role": "Programmer", "tools": ["files", "write", "shell"]}
    assert crewmod.CrewBinding(m, False).allowed_tools() == {"read_file", "grep", "glob", "repo_map"}
    allowed = crewmod.CrewBinding(m, True).allowed_tools()
    assert {"shell", "write_file", "edit_file"} <= allowed
    assert crewmod.CrewBinding({"role": "x", "tools": []}, True).allowed_tools() == {"__crew_no_tools__"}


# ----------------------------------------------------------------- gateway --
H = {"Authorization": "Bearer tok"}


async def test_gateway_rest_rpc_and_a_real_member_turn(mock_provider, monkeypatch):
    from neovarch.server import Gateway, build_app
    from neovarch.tools import tool_schemas
    from test_server import WS
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setattr(crewmod, "is_free_model", lambda m: True)   # the mock model counts as free here
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    try:
        assert (await c.get("/api/crew")).status == 401
        r = await (await c.get("/api/crew", headers=H)).json()
        assert r["crews"] == [] and len(r["templates"]) == 4
        # the designer turn (mock answers with a tool call, then prose) falls back to the template
        r = await c.post("/api/crew/propose", json={"goal": "Bandingkan harga laptop"}, headers=H)
        crew = await r.json()
        assert r.status == 200, crew
        assert crew["status"] == "proposed" and crew["template"] == "riset"
        bad = await c.post("/api/crew/approve", json={"id": "nope"}, headers=H)
        assert bad.status == 404
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        res = await ws.call("crew.update", {"id": crew["id"], "patch": {"members": [{"role": "x", "tools": ["root"]}]}})
        assert res["error"]["code"] == -32602
        res = await ws.call("crew.approve", {"id": crew["id"]})
        assert res["result"]["status"] == "running"
        done = await asyncio.wait_for(gw.crew.engine.wait(crew["id"]), 30)
        assert done["status"] == "done", done
        assert all(t["output"] for t in done["tasks"])
        # members ran with only their own tools: the mock's shell call was refused, nothing ran
        assert all("alat 'shell' tidak ada" in t["output"] for t in done["tasks"])
        assert "rancangan agen" in crew["note"]
        lst = await ws.call("crew.list", {})
        assert lst["result"]["crews"][0]["status"] == "done"
        assert (await ws.call("crew.delete", {"id": crew["id"]}))["result"]["ok"] is True
    finally:
        await c.close()


def test_main_agent_gets_the_crew_tool_but_members_do_not():
    from neovarch.tools import ToolContext, tool_schemas

    class GW:
        crew = object()

    main = ToolContext(cwd=".", approve=None, gateway=GW())
    assert "crew" in {t["function"]["name"] for t in tool_schemas(main)}
    member = ToolContext(cwd=".", approve=None, gateway=GW())
    member.company = crewmod.CrewBinding({"role": "x", "tools": ["web"]}, False)
    names = {t["function"]["name"] for t in tool_schemas(member)}
    assert "crew" not in names and "shell" not in names and "web_search" in names
    assert "crew" not in {t["function"]["name"] for t in tool_schemas(ToolContext(cwd=".", approve=None))}
