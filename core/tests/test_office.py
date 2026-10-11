import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from neovarch import config as cfgmod
from neovarch.server import Gateway, build_app, normalize_appearance

from test_server import WS


async def _client(monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    gw = Gateway(isolated=False)
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    return gw, client


async def test_office_snapshot_requires_auth_and_is_empty(home, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        assert (await c.get("/api/office")).status == 401
        snap = await (await c.get("/api/office?token=tok")).json()
        assert snap["agents"] == [] and snap["counts"]["total"] == 0
        assert {k: snap["vault"][k] for k in ("configured", "connected", "path", "note_count")} == \
            {"configured": False, "connected": False, "path": "", "note_count": 0}
    finally:
        await c.close()


async def test_chat_is_not_a_kantor_desk_but_feeds_activity(mock_provider, monkeypatch, tmp_path):
    """A normal chat is answered by the main agent: no desk, no hashed staff name; the feed still logs it."""
    monkeypatch.setenv("NEOVARCH_CWD", str(tmp_path))
    gw, c = await _client(monkeypatch)
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        sid = (await ws.call("session.create", {"source": "desktop"}))["result"]["session_id"]
        monitor = WS(await c.ws_connect("/api/ws?token=tok"))   # a phone that never attached
        await monitor.pump()
        await ws.call("prompt.submit", {"session_id": sid, "text": "kerjakan dengan lambat"})
        await ws.until("message.complete", timeout=20)
        upd = await monitor.until("office.update", timeout=5)
        assert upd["session_id"] is None and "agents" in upd["payload"]
        await asyncio.sleep(0.4)
        snap = await (await c.get("/api/office?token=tok")).json()
        assert snap["agents"] == [] and snap["counts"]["total"] == 0
        kinds = [f["kind"] for f in snap["feed"]]
        assert {"message.user", "tool", "tool.done", "message"} <= set(kinds)
        assert snap["feed"][0]["kind"] == "message"  # newest first
    finally:
        await c.close()


async def test_office_waiting_approval_feed(mock_provider, monkeypatch, tmp_path):
    monkeypatch.setenv("NEOVARCH_CWD", str(tmp_path))
    gw, c = await _client(monkeypatch)
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        await ws.call("prompt.submit", {"session_id": sid, "text": "danger please"})
        await ws.until("approval.request")
        assert gw.office.snapshot()["agents"] == []
        await ws.call("approval.respond", {"session_id": sid, "choice": "deny"})
        await ws.until("message.complete")
        kinds = [f["kind"] for f in gw.office.snapshot()["feed"]]
        assert "approval" in kinds and "approval.done" in kinds
    finally:
        await c.close()


async def test_office_kanban_staff_and_moves(home, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        t = await (await c.post("/api/plugins/kanban/tasks?token=tok", json={"title": "Riset pasar", "assignee": "Riset"})).json()
        await c.patch(f"/api/plugins/kanban/tasks/{t['id']}?token=tok", json={"status": "running"})
        snap = await (await c.get("/api/office?token=tok")).json()
        desk = next(a for a in snap["agents"] if a["kind"] == "kanban")
        assert desk["name"] == "Riset" and desk["status"] == "working" and desk["current_task"] == "Riset pasar"
        texts = [f["text"] for f in snap["feed"]]
        assert any("todo → running" in x for x in texts) and any("tugas baru" in x for x in texts)
        assert snap["kanban"]["running"] == 1
    finally:
        await c.close()


async def test_office_sse_stream(home, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        r = await c.get("/api/office/events?token=tok")
        assert r.headers["Content-Type"].startswith("text/event-stream")
        first = await r.content.readuntil(b"\n\n")
        assert first.startswith(b"event: office.update\ndata: ")
        await c.post("/api/plugins/kanban/tasks?token=tok", json={"title": "Baru"})
        second = await asyncio.wait_for(r.content.readuntil(b"\n\n"), 5)
        data = json.loads(second.split(b"data: ", 1)[1])
        assert any("Baru" in f["text"] for f in data["feed"])
        r.close()
    finally:
        await c.close()


async def test_office_vault_status(home, monkeypatch, tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "a.md").write_text("x")
    (v / "b.md").write_text("y")
    gw, c = await _client(monkeypatch)
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        await ws.call("config.set", {"key": "memory.obsidian_vault", "value": str(v)})
        snap = await (await c.get("/api/office?token=tok")).json()
        assert snap["vault"]["connected"] is True and snap["vault"]["note_count"] == 2
        st = await (await c.get("/api/memory/obsidian?token=tok")).json()
        assert st["note_count"] == 2
    finally:
        await c.close()


def test_normalize_appearance_contrast():
    assert normalize_appearance({"accent": "#ee1c1c"})["on_accent"] == "#FFFFFF"
    assert normalize_appearance({"accent": "#FACC15", "base": "light"}) == {"accent": "#FACC15", "base": "light", "on_accent": "#000000"}
    assert normalize_appearance({"accent": "fff"})["accent"] == "#FFFFFF"


async def test_appearance_api_and_event(home, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        assert (await (await c.get("/api/appearance?token=tok")).json())["accent"] == "#EE1C1C"
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        r = await c.put("/api/appearance?token=tok", json={"accent": "#2563eb", "base": "light"})
        assert (await r.json()) == {"accent": "#2563EB", "base": "light", "on_accent": "#FFFFFF"}
        ev = await ws.until("appearance.changed")
        assert ev["payload"]["accent"] == "#2563EB"
        assert cfgmod.load_config()["appearance"] == {"accent": "#2563EB", "base": "light"}
        assert (await c.put("/api/appearance?token=tok", json={"accent": "merah"})).status == 422
    finally:
        await c.close()


def test_persona_prompt_is_always_the_main_agent():
    from neovarch.agent import persona_prompt, system_prompt
    snap = {"agents": [{"id": "session:s1", "session_id": "s1", "name": "Raka", "status": "working"}]}
    text = persona_prompt("s1", snap)
    assert "**Neovarch Agent**" in text and "Raka" not in text and "`kantor`" in text
    assert "**Neovarch Agent**" in persona_prompt("abc", None)
    assert persona_prompt(None, None) == ""
    assert "**Neovarch Agent**" in system_prompt({}, __import__("pathlib").Path("."), "", text)
