"""Stop really stops (v1.4.7): an interrupt cancels the model request that is in
flight, the running tool, and every process a shell command started (its process
group), and the turn ends as "interrupted" right away instead of when they finish."""

import asyncio
import json
import os
import sys
import time

import pytest


def _cfg():
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfgmod.save_config(cfg)


def _agent(tmp_path, monkeypatch, fake, events):
    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    return Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: events.append((k, p))), rec


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie (killed, not yet reaped by its parent) counts as gone
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] != "Z"
    except OSError:
        return True


async def _wait_for(cond, timeout=30.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("timeout")
        await asyncio.sleep(0.02)


async def test_stop_cancels_the_model_request_in_flight(home, tmp_path, monkeypatch):
    _cfg()
    started, cancelled = asyncio.Event(), []

    async def slow(**_kw):
        started.set()
        try:
            await asyncio.sleep(60)  # a model that takes forever to answer
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    events: list = []
    agent, rec = _agent(tmp_path, monkeypatch, slow, events)
    turn = asyncio.create_task(agent.run_turn("halo"))
    await asyncio.wait_for(started.wait(), 30)
    t0 = time.monotonic()
    agent.interrupt()
    await asyncio.wait_for(turn, 5)
    assert time.monotonic() - t0 < 3
    assert cancelled == [True]
    done = [p for k, p in events if k == "message.complete"]
    assert done and done[-1].get("status") == "interrupted"
    assert not [p for k, p in events if k == "error"]  # a stop is not an error


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
async def test_stop_kills_the_running_shell_and_its_children(home, tmp_path, monkeypatch):
    from neovarch.llm import Completion, ToolCall
    _cfg()
    pidfile = tmp_path / "child.pid"
    cmd = f"sleep 120 & echo $! > {pidfile}; wait"
    calls = []

    async def fake(**_kw):
        calls.append(1)
        if len(calls) == 1:
            return Completion(text="", tool_calls=[ToolCall(id="s1", name="shell",
                                                             arguments=json.dumps({"command": cmd, "timeout": 300}))])
        return Completion(text="tidak boleh sampai sini", tool_calls=[])
    events: list = []
    agent, rec = _agent(tmp_path, monkeypatch, fake, events)
    turn = asyncio.create_task(agent.run_turn("jalankan"))
    await _wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    child = int(pidfile.read_text().strip())
    assert _alive(child)
    t0 = time.monotonic()
    agent.interrupt()
    await asyncio.wait_for(turn, 10)
    assert time.monotonic() - t0 < 6
    try:
        await _wait_for(lambda: not _alive(child), 5)
    except AssertionError:
        raise AssertionError(open(f"/proc/{child}/stat").read() + " msgs=" + repr(rec["messages"][-2:]))
    assert len(calls) == 1  # no further model call after Stop
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[-1]["content"].startswith("interrupted")
    assert [p for k, p in events if k == "message.complete"][-1].get("status") == "interrupted"


async def test_session_works_again_after_stop(home, tmp_path, monkeypatch):
    from neovarch.llm import Completion
    _cfg()
    gate = asyncio.Event()
    mode = {"slow": True}

    async def fake(**_kw):
        if mode["slow"]:
            gate.set()
            await asyncio.sleep(60)
        return Completion(text="jawaban baru", tool_calls=[])
    events: list = []
    agent, rec = _agent(tmp_path, monkeypatch, fake, events)
    turn = asyncio.create_task(agent.run_turn("pertama"))
    await asyncio.wait_for(gate.wait(), 30)
    agent.interrupt()
    await asyncio.wait_for(turn, 5)
    mode["slow"] = False
    out = await asyncio.wait_for(agent.run_turn("kedua"), 5)
    assert out == "jawaban baru" and agent._inflight is None


async def test_outside_cancel_is_not_swallowed(home, tmp_path, monkeypatch):
    """A gateway shutdown cancelling the turn task still propagates (not turned into a stop)."""
    _cfg()
    started = asyncio.Event()

    async def slow(**_kw):
        started.set()
        await asyncio.sleep(60)
    agent, rec = _agent(tmp_path, monkeypatch, slow, [])
    turn = asyncio.create_task(agent.run_turn("halo"))
    await asyncio.wait_for(started.wait(), 30)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
