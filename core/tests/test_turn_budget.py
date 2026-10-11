"""v1.4.7: progress-based turn stopping, silent auto-continue, friendly stop codes."""

import itertools

from neovarch import config as cfgmod
from neovarch import turn_budget as tb
from neovarch.agent import Agent
from neovarch.llm import Completion, LLMError, ToolCall
from neovarch.store import SessionStore
from neovarch.tools import ToolContext


def _cfg(**kw):
    vals = {"agent.max_turns": 30, **kw}
    return lambda k, d: vals.get(k, d)


def test_checkpoint_continues_while_progressing():
    b = tb.TurnBudget.from_config(_cfg(**{"agent.max_turn_steps": 100}))
    for i in range(100):
        assert b.before_call() is None, i
        b.record_tool("write_file", {"path": f"s{i}.svg"}, "ok", True)
    assert b.steps == 100 and b.segments == 4
    assert b.before_call() == "step_limit"  # hard ceiling


def test_checkpoint_stops_segment_without_progress():
    b = tb.TurnBudget.from_config(_cfg())
    for i in range(30):
        assert b.before_call() is None
        b.record_tool("read_file", {"path": "same.txt"}, f"r{i}", True)  # same call: progress only once
    # the first call was new work, so the first checkpoint continues ...
    assert b.before_call() is None and b.segments == 2
    for i in range(29):
        assert b.before_call() is None
        b.record_tool("read_file", {"path": "same.txt"}, f"x{i}", True)
    assert b.before_call() == "step_limit"


def test_loop_and_no_progress_detection():
    b = tb.TurnBudget.from_config(_cfg())
    codes = [b.record_tool("shell", {"command": "ls"}, "same", True) for _ in range(tb.LOOP_REPEATS)]
    assert codes[-1] == "loop" and codes[:-1] == [None] * (tb.LOOP_REPEATS - 1) and b.loop_tool == "shell"
    b = tb.TurnBudget.from_config(_cfg())
    codes = [b.record_tool("shell", {"command": f"x{i}"}, "error: boom", False) for i in range(tb.NO_PROGRESS_FAILS)]
    assert codes[-1] == "no_progress"


def test_time_and_token_budgets():
    now = itertools.count(0, 120)  # every clock read advances 2 minutes
    b = tb.TurnBudget.from_config(_cfg(**{"agent.max_turn_minutes": 5}), clock=lambda: next(now))
    stops = [b.before_call() for _ in range(5)]
    assert "budget_time" in stops
    b = tb.TurnBudget.from_config(_cfg(**{"agent.max_turn_tokens": 10000}))
    assert b.before_call() is None
    b.add_usage({"prompt_tokens": 9000, "completion_tokens": 2000})
    assert b.before_call() == "budget_tokens"


def test_describe_is_plain_indonesian_with_one_action():
    d = tb.describe("step_limit", steps=150)
    assert d["title"] == "Batas langkah tercapai" and d["action"] == "continue" and d["action_label"] == "Lanjutkan"
    assert "150 langkah" in d["message"] and "model calls" not in d["message"]
    assert tb.describe("auth")["action_label"] == "Buka pengaturan"
    assert tb.describe("no_progress")["action_label"] == "Ganti model"
    assert tb.describe("rate_limit")["action_label"] == "Coba lagi"
    assert tb.classify_llm_error("HTTP 429 Too Many Requests") == "rate_limit"
    assert tb.classify_llm_error("HTTP 401: invalid api key") == "auth"
    assert tb.classify_llm_error("could not reach http://x") == "connection"
    assert tb.classify_llm_error("HTTP 400 model_not_found") == "model"
    assert tb.is_continue("Lanjutkan!") and tb.is_continue(" lanjut ") and not tb.is_continue("lanjutkan bab 3 tolong")


async def test_long_tool_job_passes_old_30_call_cap(home, tmp_path, monkeypatch):
    """A PPT-like job writing one slide per call keeps going past 30 calls and finishes."""
    cfg = cfgmod.load_config()
    cfg.setdefault("agent", {})["max_turns"] = 30  # what pre-1.4.7 configs carry
    cfgmod.save_config(cfg)
    calls = {"n": 0}

    async def fake_complete(self, active, wire, pinned):
        calls["n"] += 1
        if calls["n"] <= 45:
            return Completion(tool_calls=[ToolCall(id=f"c{calls['n']}", name="write_file",
                                                   arguments=f'{{"path": "P{calls["n"]:02d}.svg", "content": "<svg/>"}}')],
                              usage={"prompt_tokens": 100, "completion_tokens": 10})
        return Completion(text="Deck selesai: 45 slide.", usage={"prompt_tokens": 100, "completion_tokens": 10})

    monkeypatch.setattr(Agent, "_complete", fake_complete)
    events = []
    store = SessionStore()
    agent = Agent(store.create(cwd=str(tmp_path)), store, ToolContext(cwd=tmp_path, approve=None),
                  lambda k, p: events.append((k, p)))
    final = await agent.run_turn("buat ppt 45 slide")
    assert final == "Deck selesai: 45 slide."
    assert not [p for k, p in events if k == "error"]
    progress = [p for k, p in events if k == "turn.progress"]
    assert progress[-1]["step"] >= 46 and progress[0] == {"step": 1, "limit": 30, "max": 600}
    assert (tmp_path / "P45.svg").exists()


async def test_stop_is_coded_and_lanjutkan_resumes(home, tmp_path, monkeypatch):
    cfg = cfgmod.load_config()
    cfg.setdefault("agent", {})["max_turns"] = 5
    cfgmod.save_config(cfg)
    seen_tails = []

    async def fake_complete(self, active, wire, pinned):
        seen_tails.append(wire[-1].get("content") if isinstance(wire[-1].get("content"), str) else "")
        return Completion(tool_calls=[ToolCall(id="x", name="read_file", arguments='{"path": "a.txt"}')])

    (tmp_path / "a.txt").write_text("a")
    monkeypatch.setattr(Agent, "_complete", fake_complete)
    events = []
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: events.append((k, p)))
    await agent.run_turn("kerjakan")
    err = [p for k, p in events if k == "error"][-1]
    assert err["code"] in ("step_limit", "loop") and err["title"] and err["action_label"]
    done = [p for k, p in events if k == "message.complete"][-1]
    assert done["error_info"]["code"] == err["code"] and "model calls" not in done["error"]


async def test_provider_error_is_labelled(home, tmp_path, monkeypatch):
    async def boom(self, active, wire, pinned):
        raise LLMError("HTTP 429 rate limited")

    monkeypatch.setattr(Agent, "_complete", boom)
    events = []
    store = SessionStore()
    agent = Agent(store.create(cwd=str(tmp_path)), store, ToolContext(cwd=tmp_path, approve=None),
                  lambda k, p: events.append((k, p)))
    await agent.run_turn("halo")
    err = [p for k, p in events if k == "error"][-1]
    assert err["code"] == "rate_limit" and err["action"] == "retry"
