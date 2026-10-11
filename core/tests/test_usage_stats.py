"""v1.4.7: token usage per day / lifetime / model / session, live usage events, GET /api/usage."""

import time

from neovarch import usage_stats as us
from neovarch.agent import Agent
from neovarch.llm import Completion
from neovarch.store import SessionStore
from neovarch.tools import ToolContext


def test_record_and_summary(tmp_path):
    p = tmp_path / "usage.json"
    day1 = time.mktime((2026, 10, 11, 12, 0, 0, 0, 0, -1))
    day2 = time.mktime((2026, 10, 12, 12, 0, 0, 0, 0, -1))
    assert us.record("mimo", {"prompt_tokens": 100, "completion_tokens": 20}, provider="9router", now=day1, path=p)
    us.record("mimo", {"prompt_tokens": 300, "completion_tokens": 30,
                       "prompt_tokens_details": {"cached_tokens": 250}}, now=day2, path=p)
    us.record("gpt", {"input_tokens": 50, "output_tokens": 5}, now=day2, path=p)
    assert us.record("x", {}, path=p) is None  # no usage from the provider: nothing counted
    s = us.summary(now=day2, path=p)
    assert s["today"] == {"input": 350, "output": 35, "cached": 250, "calls": 2, "total": 385}
    assert s["lifetime"]["total"] == 505 and s["lifetime"]["calls"] == 3
    assert [m["model"] for m in s["models"]] == ["mimo", "gpt"] and s["models"][0]["provider"] == "9router"
    assert [d["date"] for d in s["trend"]] == ["2026-10-11", "2026-10-12"]
    assert {m["model"] for m in s["today_models"]} == {"mimo", "gpt"}


def test_session_totals():
    rec = {}
    us.add_session(rec, {"input": 10, "output": 2, "cached": 0})
    assert us.add_session(rec, {"input": 5, "output": 1, "cached": 3}) == {
        "input": 15, "output": 3, "cached": 3, "calls": 2, "total": 18}
    assert us.summary(session=rec)["session"]["total"] == 18


async def test_agent_counts_and_streams_usage(home, tmp_path, monkeypatch):
    async def fake(self, active, wire, pinned):
        return Completion(text="ok", usage={"prompt_tokens": 1200, "completion_tokens": 40})

    monkeypatch.setattr(Agent, "_complete", fake)
    events = []
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    await Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: events.append((k, p))).run_turn("hai")
    live = [p for k, p in events if k == "usage.update"]
    assert live and live[-1]["context_tokens"] == 1200 and live[-1]["context_window"] == 128000
    assert live[-1]["session"]["total"] >= 1240
    desk = [p for k, p in events if k == "session.usage"]
    assert desk and desk[-1]["usage"]["context_used"] == 1200 and desk[-1]["usage"]["context_max"] == 128000
    assert desk[-1]["usage"]["total"] >= 1240 and desk[-1]["usage"]["calls"] >= 1
    done = [p for k, p in events if k == "message.complete"][-1]["usage"]
    assert done["prompt_tokens"] == 1200 and done["context_max"] == 128000 and done["input"] >= 1200
    s = us.summary(session=store.load(rec["id"]))
    assert s["today"]["total"] >= 1240 and s["session"]["total"] >= 1240


def test_desktop_usage_shape():
    d = us.desktop_usage({"input": 1000, "output": 50, "cached": 400, "calls": 2, "total": 1050}, 64000, 128000)
    assert d == {"input": 1000, "output": 50, "total": 1050, "calls": 2, "cached": 400, "cache_hit_pct": 40.0,
                 "context_used": 64000, "context_max": 128000, "context_percent": 50.0}
    assert "context_max" not in us.desktop_usage({}, 10, 0)
