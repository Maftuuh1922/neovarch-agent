"""Jalankan di latar belakang: shared state + authenticated REST controls."""

from __future__ import annotations

import asyncio
import json
import os

from aiohttp.test_utils import TestClient, TestServer

from neovarch import background as bgmod
from neovarch.background import BackgroundService, BackgroundState
from neovarch.server import Gateway, build_app


def test_state_roundtrip_and_updated_at(tmp_path):
    p = tmp_path / "bg.json"
    st = BackgroundState(p, clock=lambda: 1234.0)
    assert st.settings() == {"run_in_background": False, "start_at_login": False, "updated_at": 0.0}
    assert st.update(run_in_background=True) is True
    assert st.update(run_in_background=True) is False  # no change, no write
    again = BackgroundState(p)
    assert again.run_in_background is True and again.start_at_login is False and again.updated_at == 1234.0
    p.write_text("not json")
    assert BackgroundState(p).run_in_background is False


def test_pid_alive():
    assert bgmod.pid_alive(os.getpid())
    assert not bgmod.pid_alive(None)
    assert not bgmod.pid_alive(0)


async def _client(monkeypatch, home):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.delenv("NEOVARCH_DESKTOP_PID", raising=False)
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    return gw, c


async def test_rest_requires_token(monkeypatch, home):
    gw, c = await _client(monkeypatch, home)
    try:
        assert (await c.get("/api/remote/background")).status == 401
        assert (await c.post("/api/remote/background", json={"run_in_background": True})).status == 401
        assert (await c.post("/api/remote/background/stop-gateway")).status == 401
        assert not (home / "remote" / "background.json").exists()
    finally:
        await c.close()


async def test_get_and_toggle_from_phone(monkeypatch, home):
    gw, c = await _client(monkeypatch, home)
    try:
        st = await (await c.get("/api/remote/background?token=tok")).json()
        assert st["run_in_background"] is False and st["start_at_login"] is False
        assert st["service"]["state"] == "running" and st["service"]["pid"] == os.getpid()
        assert st["agent"] == {"sessions": 0, "running": 0}
        assert st["relay"]["state"] == "off"

        # desktop registers itself, then the phone turns the option on
        me = os.getpid()
        out = await (await c.post("/api/remote/background?token=tok", json={"desktop_pid": me})).json()
        assert out["service"]["desktop_attached"] is True and out["service"]["mode"] == "app"
        out = await (await c.post("/api/remote/background?token=tok",
                                  json={"run_in_background": True, "start_at_login": True})).json()
        assert out["run_in_background"] is True and out["start_at_login"] is True and out["updated_at"] > 0
        saved = json.loads((home / "remote" / "background.json").read_text())
        assert saved["run_in_background"] is True and saved["start_at_login"] is True

        # off while the desktop is still there: the gateway keeps running
        out = await (await c.post("/api/remote/background?token=tok", json={"run_in_background": False})).json()
        assert "will_stop" not in out and gw.background.pending is None

        assert (await c.post("/api/remote/background?token=tok", data="x")).status == 400
        assert (await c.post("/api/remote/background/nope?token=tok")).status == 404
    finally:
        await c.close()


async def test_off_without_desktop_stops_gateway(monkeypatch, home):
    gw, c = await _client(monkeypatch, home)
    exits: list[int] = []
    gw.background = BackgroundService(gw, exit_process=exits.append, exec_self=lambda: exits.append(-1))
    gw.background.desktop_pid = 2 ** 22 + 12345  # not a live process
    try:
        await c.post("/api/remote/background?token=tok", json={"run_in_background": True})
        out = await (await c.post("/api/remote/background?token=tok", json={"run_in_background": False})).json()
        assert out["will_stop"] is True and out["service"]["state"] == "stopping"
        await asyncio.sleep(0.8)
        assert exits == [0]
    finally:
        await c.close()


class _FakeAgent:
    def __init__(self):
        self.interrupted = 0

    def interrupt(self):
        self.interrupted += 1


class _FakeLive:
    def __init__(self, status):
        self.status = status
        self.agent = _FakeAgent()
        self.approvals = {}
        self.task = None


async def test_agent_and_gateway_actions(monkeypatch, home):
    gw, c = await _client(monkeypatch, home)
    calls: list[int] = []
    gw.background = BackgroundService(gw, exit_process=calls.append, exec_self=lambda: calls.append(-1))
    busy, idle = _FakeLive("running"), _FakeLive("idle")
    fut = asyncio.get_running_loop().create_future()
    busy.approvals = {"a1": {"future": fut}}
    gw.live = {"s1": busy, "s2": idle}
    try:
        st = await (await c.get("/api/remote/background?token=tok")).json()
        assert st["agent"] == {"sessions": 2, "running": 1}

        out = await (await c.post("/api/remote/background/stop-agent?token=tok")).json()
        assert out["ok"] and "1 agen dihentikan" in out["message"]
        assert busy.agent.interrupted == 1 and idle.agent.interrupted == 0 and fut.result() == "deny"
        assert len(gw.live) == 2

        out = await (await c.post("/api/remote/background/restart-agent?token=tok")).json()
        assert out["ok"] and gw.live == {}

        out = await (await c.post("/api/remote/background/restart-gateway?token=tok")).json()
        assert out["ok"] and "dimulai ulang" in out["message"]
        await asyncio.sleep(0.8)
        assert calls == ([bgmod.RESTART_EXIT_CODE] if os.name == "nt" else [-1])

        out = await (await c.post("/api/remote/background/stop-gateway?token=tok")).json()
        assert out["ok"] and "Gateway dihentikan" in out["message"]
        await asyncio.sleep(0.8)
        assert calls[-1] == 0
    finally:
        await c.close()
