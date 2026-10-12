"""v1.4.7: messages sent while a turn runs are queued per session (never refused)."""

import asyncio

import pytest

from neovarch import msg_queue as mq
from test_server import WS, _client


def test_queue_basics():
    rec = {"queued": ["lama"]}  # legacy steer list folds in
    assert [i["text"] for i in mq.items(rec)] == ["lama"] and "queued" not in rec
    a = mq.push(rec, "satu")
    b = mq.push(rec, "dua")
    mq.edit(rec, a["id"], "satu (edit)")
    mq.to_front(rec, b["id"])
    assert [i["text"] for i in mq.items(rec)] == ["dua", "lama", "satu (edit)"]
    mq.remove(rec, mq.items(rec)[1]["id"])
    p = mq.payload(rec)
    assert p["count"] == 2 and p["paused"] is False and p["items"][0]["text"] == "dua"
    mq.set_paused(rec, True, "stopped")
    assert mq.payload(rec)["paused"] and mq.payload(rec)["paused_reason"] == "stopped"
    assert mq.pop_next(rec)["text"] == "dua"
    with pytest.raises(mq.QueueError):
        mq.push(rec, "   ")
    with pytest.raises(mq.QueueError):
        mq.edit(rec, "q-nope", "x")
    for i in range(mq.MAX_ITEMS - 1):
        mq.push(rec, f"m{i}")
    with pytest.raises(mq.QueueError):
        mq.push(rec, "penuh")
    assert mq.clear(rec) == mq.MAX_ITEMS and not mq.paused(rec)


@pytest.fixture
def gated(monkeypatch):
    """Agent.run_turn that waits for a release, recording each turn's text."""
    from neovarch.agent import Agent
    state = {"seen": [], "gates": []}

    async def fake(self, text, attachments=None):
        state["seen"].append(text)
        self._nv_int = False
        gate = asyncio.Event()
        state["gates"].append(gate)
        try:
            await asyncio.wait_for(gate.wait(), 5)
        except asyncio.CancelledError:
            raise
        if getattr(self, "interrupted", False) or getattr(self, "_nv_int", False):
            self.emit("message.complete", {"text": "", "error": "interrupted", "status": "interrupted"})
            return ""
        self.emit("message.complete", {"text": f"ok {text}"})
        return f"ok {text}"

    def interrupt(self):
        self._nv_int = True
        if state["gates"]:
            state["gates"][-1].set()

    monkeypatch.setattr(Agent, "run_turn", fake)
    monkeypatch.setattr(Agent, "interrupt", interrupt)
    return state


async def _wait(cond, timeout=5):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timeout")
        await asyncio.sleep(0.01)


async def test_submit_while_running_queues_then_drains_in_order(mock_provider, monkeypatch, gated):
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        assert (await ws.call("prompt.submit", {"session_id": sid, "text": "pertama"}))["result"]["status"] == "running"
        r = (await ws.call("prompt.submit", {"session_id": sid, "text": "kedua"}))["result"]
        assert r["ok"] and r["status"] == "queued" and r["position"] == 1  # no "a turn is already running"
        r = (await ws.call("prompt.submit", {"session_id": sid, "text": "ketiga"}))["result"]
        assert r["position"] == 2 and [i["text"] for i in r["queue"]["items"]] == ["kedua", "ketiga"]
        assert any(e["type"] == "queue.update" for e in ws.events)
        # edit + list are visible to every client (resume carries the queue too)
        qid = r["queue"]["items"][1]["id"]
        await ws.call("queue.edit", {"session_id": sid, "id": qid, "text": "ketiga!"})
        resumed = (await ws.call("session.resume", {"session_id": sid}))["result"]
        assert [i["text"] for i in resumed["queue"]["items"]] == ["kedua", "ketiga!"]
        for n in range(3):
            await _wait(lambda: len(gated["gates"]) > n)
            gated["gates"][n].set()
        await _wait(lambda: gated["seen"] == ["pertama", "kedua", "ketiga!"] and gw.live[sid].status == "idle")
        assert (await ws.call("queue.list", {"session_id": sid}))["result"]["count"] == 0
    finally:
        await c.close()


async def test_stop_pauses_queue_and_send_now_interrupts(mock_provider, monkeypatch, gated):
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        await ws.call("prompt.submit", {"session_id": sid, "text": "a"})
        await ws.call("prompt.submit", {"session_id": sid, "text": "b"})
        await ws.call("session.interrupt", {"session_id": sid})  # the person pressed Stop
        await _wait(lambda: gw.live[sid].status == "idle")
        q = (await ws.call("queue.list", {"session_id": sid}))["result"]
        assert q["count"] == 1 and q["paused"] and q["paused_reason"] == "stopped" and gated["seen"] == ["a"]
        # resume sends it
        await ws.call("queue.resume", {"session_id": sid})
        await _wait(lambda: gated["seen"] == ["a", "b"])
        # while "b" runs: queue c, d; "kirim sekarang" on d interrupts b and runs d next, then c
        await ws.call("prompt.submit", {"session_id": sid, "text": "c"})
        d = (await ws.call("prompt.submit", {"session_id": sid, "text": "d"}))["result"]["queue_id"]
        r = (await ws.call("queue.send_now", {"session_id": sid, "id": d}))["result"]
        assert r["status"] == "interrupting" and [i["text"] for i in r["items"]] == ["d", "c"]
        await _wait(lambda: gated["seen"] == ["a", "b", "d"])
        gated["gates"][-1].set()
        await _wait(lambda: gated["seen"] == ["a", "b", "d", "c"])
        gated["gates"][-1].set()
        await _wait(lambda: gw.live[sid].status == "idle")
        # remove + unknown id → clear JSON-RPC error, never a crash
        await ws.call("prompt.submit", {"session_id": sid, "text": "e"})
        e = (await ws.call("prompt.submit", {"session_id": sid, "text": "f"}))["result"]["queue_id"]
        assert (await ws.call("queue.remove", {"session_id": sid, "id": e}))["result"]["count"] == 0
        assert (await ws.call("queue.remove", {"session_id": sid, "id": "q-x"}))["error"]["code"] == -32602
        gated["gates"][-1].set()
    finally:
        await c.close()
