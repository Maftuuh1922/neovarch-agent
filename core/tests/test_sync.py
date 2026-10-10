"""Two cores on one PC (desktop loopback core + phone LAN core) share sessions and running turns."""

import asyncio
import json
import os
import subprocess
import sys

from aiohttp.test_utils import TestClient, TestServer

from neovarch import sync as syncmod
from neovarch.server import Gateway, build_app
from neovarch.store import SessionStore

from test_server import WS


def test_watcher_sees_a_chat_written_by_another_process(home):
    store = SessionStore()
    hits = []
    w = syncmod.SessionWatcher(store.root, lambda: hits.append(1))
    assert w.poll() is False
    # "the phone's core" writes a chat in its own process
    code = ("import sys; sys.path.insert(0, %r); from neovarch.store import SessionStore; "
            "SessionStore().create(source='mobile', title='dari HP')") % str(os.path.dirname(os.path.dirname(__file__)))
    subprocess.run([sys.executable, "-c", code], check=True, env=os.environ.copy())
    assert w.poll() is True and hits == [1]
    assert w.poll() is False
    rec = store.list()[0]
    assert rec["title"] == "dari HP" and rec["source"] == "mobile"
    store.save(store.load(rec["id"]))
    w.note_own_write()  # our own announced write is not announced twice
    assert w.poll() is False


def test_foreign_turn_markers_count_only_live_other_processes(home):
    syncmod.mark_turn("own")
    assert syncmod.foreign_turns() == []  # our own turn is counted from memory, not the marker
    d = syncmod.turns_dir()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (d / "phone1.json").write_text(json.dumps({"session_id": "phone1", "pid": proc.pid, "started_at": __import__("time").time()}))
        (d / "dead.json").write_text(json.dumps({"session_id": "dead", "pid": 999999, "started_at": 0}))
        ids = [t["session_id"] for t in syncmod.foreign_turns()]
        assert ids == ["phone1"]
        assert not (d / "dead.json").exists()
    finally:
        proc.kill()
        proc.wait()
    assert syncmod.foreign_turns() == []
    syncmod.clear_turn("own")
    assert not (d / "own.json").exists()


async def test_gateway_announces_external_chats_and_counts_foreign_turns(home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setenv("NEOVARCH_SESSION_WATCH_S", "0.1")
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        ready = await ws.pump()
        assert ready["params"]["payload"]["change_events"] is True
        rec = SessionStore().create(source="mobile", title="dari HP")  # as if the other core wrote it
        ev = await ws.until("sessions.changed", timeout=5)
        assert ev["payload"] == {"external": True}
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            d = syncmod.turns_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{rec['id']}.json").write_text(json.dumps(
                {"session_id": rec["id"], "pid": proc.pid, "started_at": __import__("time").time(), "model": "m"}))
            active = (await ws.call("session.active_list", {}))["result"]["sessions"]
            assert [a["id"] for a in active] == [rec["id"]] and active[0]["elsewhere"] is True
            st = await (await c.get("/api/status?token=tok")).json()
            assert st["active_sessions"] == 1 and st["version"]
        finally:
            proc.kill()
            proc.wait()
        await asyncio.sleep(0)
    finally:
        await c.close()
