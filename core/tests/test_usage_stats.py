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
    assert s["today"] == {"input": 350, "output": 35, "cached": 250, "cache_write": 0, "calls": 2, "total": 385}
    assert s["since"] == "2026-10-11"
    assert s["lifetime"]["total"] == 505 and s["lifetime"]["calls"] == 3
    assert [m["model"] for m in s["models"]] == ["mimo", "gpt"] and s["models"][0]["provider"] == "9router"
    assert [d["date"] for d in s["trend"]] == ["2026-10-11", "2026-10-12"]
    assert {m["model"] for m in s["today_models"]} == {"mimo", "gpt"}


def test_session_totals():
    rec = {}
    us.add_session(rec, {"input": 10, "output": 2, "cached": 0})
    assert us.add_session(rec, {"input": 5, "output": 1, "cached": 3}) == {
        "input": 15, "output": 3, "cached": 3, "cache_write": 0, "calls": 2, "total": 18}
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


# ---- v1.4.8: one meaning for every provider shape -------------------------------------------


def test_normalize_openai_chat_cache_is_subset():
    n = us.normalize({"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050,
                      "prompt_tokens_details": {"cached_tokens": 800}})
    assert n == {"input": 1000, "output": 50, "cached": 800, "cache_write": 0}


def test_normalize_openai_chat_9router_cache_write_and_deepseek():
    n = us.normalize({"prompt_tokens": 1000, "completion_tokens": 10,
                      "prompt_tokens_details": {"cached_tokens": 600, "cache_creation_tokens": 300}})
    assert n == {"input": 1000, "output": 10, "cached": 600, "cache_write": 300}
    d = us.normalize({"prompt_tokens": 500, "completion_tokens": 5, "prompt_cache_hit_tokens": 400,
                      "prompt_cache_miss_tokens": 100})
    assert d == {"input": 500, "output": 5, "cached": 400, "cache_write": 0}


def test_normalize_anthropic_counts_cache_into_input():
    # Anthropic's input_tokens is only the UNcached part: before v1.4.8 this counted 12 instead of 5012.
    n = us.normalize({"input_tokens": 12, "output_tokens": 40, "cache_read_input_tokens": 4800,
                      "cache_creation_input_tokens": 200})
    assert n == {"input": 5012, "output": 40, "cached": 4800, "cache_write": 200}


def test_normalize_openai_responses_and_gemini():
    r = us.normalize({"input_tokens": 900, "output_tokens": 30, "input_tokens_details": {"cached_tokens": 700}})
    assert r == {"input": 900, "output": 30, "cached": 700, "cache_write": 0}
    g = us.normalize({"promptTokenCount": 2000, "candidatesTokenCount": 100, "thoughtsTokenCount": 50,
                      "cachedContentTokenCount": 1500})
    assert g == {"input": 2000, "output": 150, "cached": 1500, "cache_write": 0}


def test_normalize_proxy_with_exclusive_prompt_tokens():
    # A proxy that copied Anthropic's cache-exclusive count into prompt_tokens: cache > prompt.
    n = us.normalize({"prompt_tokens": 10, "completion_tokens": 3, "cache_read_input_tokens": 990})
    assert n == {"input": 1000, "output": 3, "cached": 990, "cache_write": 0}


def test_normalize_empty_and_junk():
    assert us.normalize(None) is None and us.normalize({}) is None
    assert us.normalize({"prompt_tokens": 0, "completion_tokens": 0}) is None
    assert us.normalize({"foo": 1}) is None
    assert us.normalize({"prompt_tokens": "x", "completion_tokens": 7}) == {
        "input": 0, "output": 7, "cached": 0, "cache_write": 0}


def test_cached_tokens_any_shape():
    assert us.cached_tokens({"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 9}) == 9
    assert us.cached_tokens({"prompt_tokens": 9, "prompt_tokens_details": {"cached_tokens": 4}}) == 4
    assert us.cached_tokens(None) == 0


def test_record_anthropic_shape_total_is_input_plus_output(tmp_path):
    p = tmp_path / "usage.json"
    us.record("claude", {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900}, path=p)
    life = us.summary(path=p)["lifetime"]
    assert life["input"] == 1000 and life["cached"] == 900 and life["total"] == 1020


def test_merge_stream_usage_split_cumulative_and_single():
    # split: prompt in the first chunk, completion only in the last (last-wins lost the prompt)
    u = None
    for chunk in ({"prompt_tokens": 5000, "completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": 4000}},
                  {"completion_tokens": 120}):
        u = us.merge_stream_usage(u, chunk)
    assert us.normalize(u) == {"input": 5000, "output": 120, "cached": 4000, "cache_write": 0}
    # anthropic-style message_start / message_delta passed through
    u = None
    for chunk in ({"input_tokens": 10, "cache_read_input_tokens": 990, "output_tokens": 1},
                  {"output_tokens": 77}):
        u = us.merge_stream_usage(u, chunk)
    assert us.normalize(u) == {"input": 1000, "output": 77, "cached": 990, "cache_write": 0}
    # cumulative usage on every chunk: never summed twice
    u = None
    for k in (1, 2, 3):
        u = us.merge_stream_usage(u, {"prompt_tokens": 800, "completion_tokens": 10 * k})
    assert us.normalize(u)["input"] == 800 and us.normalize(u)["output"] == 30
    assert us.merge_stream_usage(None, None) is None


async def test_stream_chat_merges_split_usage(monkeypatch):
    from neovarch import llm

    lines = [
        'data: {"choices":[{"delta":{"content":"ha"}}],"usage":{"prompt_tokens":3000,"completion_tokens":0,'
        '"prompt_tokens_details":{"cached_tokens":2500}}}',
        'data: {"choices":[{"delta":{"content":"i"},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"completion_tokens":42}}',
        "data: [DONE]",
    ]

    class Resp:
        status = 200
        headers = {"Content-Type": "text/event-stream"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Sess:
        def post(self, *a, **k):
            return Resp()

    async def fake_lines(resp):
        for ln in lines:
            yield ln

    monkeypatch.setattr(llm, "_sse_lines", fake_lines)
    out = await llm._stream_chat("http://x/v1", "", "m", [], None, None, None, 10, Sess(), None, True, None)
    assert out.text == "hai"
    assert us.normalize(out.usage) == {"input": 3000, "output": 42, "cached": 2500, "cache_write": 0}


def test_persistence_lifetime_days_sessions_survive_reload(tmp_path):
    p = tmp_path / "usage.json"
    d1 = time.mktime((2026, 10, 12, 10, 0, 0, 0, 0, -1))
    d2 = time.mktime((2026, 10, 13, 10, 0, 0, 0, 0, -1))
    us.record("m", {"prompt_tokens": 100, "completion_tokens": 10}, session="s1", now=d1, path=p)
    us.record("m", {"prompt_tokens": 200, "completion_tokens": 20}, session="s1", now=d2, path=p)
    us.record("m", {"prompt_tokens": 50, "completion_tokens": 5}, session="s2", now=d2, path=p)
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no temp file behind
    s = us.summary(session_id="s1", now=d2, path=p)
    assert s["since"] == "2026-10-12"
    assert s["today"]["total"] == 275 and s["today"]["calls"] == 2
    assert s["session"]["total"] == 330 and s["session"]["calls"] == 2
    assert s["lifetime"]["total"] == 385 and s["lifetime"]["calls"] == 3
    # lifetime != today once a second day exists
    assert s["lifetime"]["total"] != s["today"]["total"]
    # a session record (no disk counter for it) still answers from usage_total
    s3 = us.summary(session={"id": "old", "usage_total": {"input": 7, "output": 1}}, now=d2, path=p)
    assert s3["session"]["total"] == 8
    # the disk counter wins over the record
    s4 = us.summary(session={"id": "s2", "usage_total": {}}, now=d2, path=p)
    assert s4["session"]["total"] == 55


def test_v1_file_gets_since_from_oldest_day(tmp_path):
    import json
    p = tmp_path / "usage.json"
    p.write_text(json.dumps({"version": 1, "lifetime": {"input": 10, "output": 1, "cached": 0, "calls": 1},
                             "days": {"2026-10-12": {"input": 10, "output": 1, "cached": 0, "calls": 1}},
                             "models": {}}))
    s = us.summary(path=p)
    assert s["since"] == "2026-10-12" and s["lifetime"]["total"] == 11
    us.record("m", {"prompt_tokens": 5, "completion_tokens": 1}, path=p)
    assert json.loads(p.read_text())["since"] == "2026-10-12"


def test_corrupt_file_starts_fresh(tmp_path):
    p = tmp_path / "usage.json"
    p.write_text("{not json")
    assert us.summary(path=p)["lifetime"]["total"] == 0
    us.record("m", {"prompt_tokens": 3, "completion_tokens": 1}, path=p)
    assert us.summary(path=p)["lifetime"]["total"] == 4


def test_session_counters_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "KEEP_SESSIONS", 3)
    p = tmp_path / "usage.json"
    for i in range(5):
        us.record("m", {"prompt_tokens": 1, "completion_tokens": 1}, session=f"s{i}", path=p)
    import json
    assert list(json.loads(p.read_text())["sessions"]) == ["s2", "s3", "s4"]


def test_trend_days_carry_the_split_for_the_phone_chart(tmp_path):
    """v1.4.8: the phone draws stacked daily bars (baru / cache / keluar) from ``trend``.
    Old readers only use date + total, which must stay."""
    p = tmp_path / "usage.json"
    day1 = time.mktime((2026, 10, 11, 12, 0, 0, 0, 0, -1))
    day2 = time.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1))
    us.record("mimo", {"prompt_tokens": 100, "completion_tokens": 20,
                       "prompt_tokens_details": {"cached_tokens": 60}}, now=day1, path=p)
    us.record("mimo", {"prompt_tokens": 300, "completion_tokens": 30}, now=day2, path=p)
    us.record("gpt", {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 40}, now=day2, path=p)
    s = us.summary(now=day2, path=p)
    assert s["trend"] == [
        {"date": "2026-10-11", "total": 120, "input": 100, "output": 20, "cached": 60, "cache_write": 0, "calls": 1},
        {"date": "2026-10-13", "total": 385, "input": 350, "output": 35, "cached": 40, "cache_write": 0, "calls": 2},
    ]
    for d in s["trend"]:
        assert d["total"] == d["input"] + d["output"] and d["cached"] <= d["input"]


def test_trend_respects_days_window(tmp_path):
    p = tmp_path / "usage.json"
    for i in range(1, 6):
        us.record("m", {"prompt_tokens": i, "completion_tokens": 0},
                  now=time.mktime((2026, 10, i, 12, 0, 0, 0, 0, -1)), path=p)
    s = us.summary(now=time.mktime((2026, 10, 5, 12, 0, 0, 0, 0, -1)), path=p, days=3)
    assert [d["date"] for d in s["trend"]] == ["2026-10-03", "2026-10-04", "2026-10-05"]
