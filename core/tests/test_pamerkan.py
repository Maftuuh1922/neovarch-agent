"""Pamerkan radar / charts: aggregation from local sessions + usage.json only (pamerkan.py)."""

import json
import time

from neovarch import pamerkan as pk
from neovarch import usage_stats as us


def _ts(y, m, d, h=12):
    return time.mktime((y, m, d, h, 0, 0, 0, 0, -1))


NOW = _ts(2026, 10, 14, 15)


def _call(name, args=None):
    return {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


def _write_session(d, sid, messages, source="cli"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({"id": sid, "source": source, "messages": messages}), encoding="utf-8")


def test_category_mapping():
    assert pk.category("edit_file") == "coding"
    assert pk.category("shell") == "coding"
    assert pk.category("web_search") == "riset"
    assert pk.category("report_create") == "riset"
    assert pk.category("web_fetch") == "browser"
    assert pk.category("mcp__playwright__browser_navigate") == "browser"
    assert pk.category("ppt_export") == "ppt"
    assert pk.category("make_slides") == "ppt"
    assert pk.category("kantor") == "otomasi"
    assert pk.category("shell_job") == "otomasi"
    assert pk.category("cron_add") == "otomasi"
    assert pk.category("memory") is None
    assert pk.category("skill") is None
    assert pk.category("") is None


def test_codemode_program_parsing():
    code = (
        "a = tools.read_file(path='x.py')\n"
        "b = tools.call(\"grep\", pattern='x')\n"
        "r = tools.parallel([(\"web_search\", {'query': 'q'}), ('web_fetch', {'url': 'u'})])\n"
        "tools.list(); tools.describe('shell')\n"
    )
    assert pk.codemode_tools(code) == ["read_file", "grep", "web_search", "web_fetch"]
    assert pk.codemode_tools("") == []
    assert pk.codemode_tools(None) == []


def test_score_is_log_scaled_and_capped():
    assert pk.score(0, 100) == 0
    assert 0 < pk.score(1, 1500) < 20
    assert pk.score(1500, 1500) == 100
    assert pk.score(10 ** 9, 1500) == 100
    assert pk.score(10, 100) < pk.score(50, 100) < pk.score(100, 100)


def test_empty_home_gives_empty_state(tmp_path):
    out = pk.compute(home=tmp_path, now=NOW)
    assert out["empty"] is True
    assert [a["id"] for a in out["axes"]] == list(pk.AXES)
    assert all(a["value"] == 0 and a["score"] == 0 for a in out["axes"])
    assert out["donut"] == [] and out["tools_top"] == []
    assert len(out["trend"]["daily"]) == pk.TREND_DAYS and len(out["trend"]["weekly"]) == pk.TREND_WEEKS
    assert out["trend"]["daily"][-1]["date"] == "2026-10-14"
    assert out["totals"]["sessions"] == 0 and out["totals"]["streak"] == 0


def test_aggregates_real_sessions_and_tokens(tmp_path):
    sd = tmp_path / "sessions"
    t = _ts(2026, 10, 14)
    y = _ts(2026, 10, 13)
    _write_session(sd, "a", [
        {"role": "user", "content": "fix", "ts": y},
        {"role": "assistant", "ts": y, "tool_calls": [_call("read_file"), _call("edit_file"), _call("web_search")]},
        {"role": "user", "content": "hidden nudge", "ts": y, "hidden": True},
        {"role": "user", "content": "more", "ts": t},
        {"role": "assistant", "ts": t, "tool_calls": [
            _call("codemode", {"code": "tools.grep(pattern='x'); tools.web_fetch(url='u')"}),
            _call("ppt_export"), _call("memory")]},
    ])
    _write_session(sd, "cronrun", [
        {"role": "user", "content": "jadwal", "ts": t},
        {"role": "assistant", "ts": t, "tool_calls": [_call("shell_job")]},
    ], source="cron")
    # outside the 30-day window: ignored for the radar
    _write_session(sd, "old", [{"role": "assistant", "ts": _ts(2026, 8, 1), "tool_calls": [_call("edit_file")] * 9}])
    (sd / "broken.json").write_text("{nope", encoding="utf-8")
    up = tmp_path / "usage.json"
    us.record("m", {"prompt_tokens": 1000, "completion_tokens": 200}, now=t, path=up)
    us.record("m", {"prompt_tokens": 500, "completion_tokens": 0}, now=y, path=up)

    out = pk.compute(home=tmp_path, now=NOW)
    vals = {a["id"]: a["value"] for a in out["axes"]}
    assert vals == {"coding": 3, "riset": 1, "ppt": 1, "browser": 1, "otomasi": 2, "token": 1700}
    assert out["empty"] is False
    assert all(0 < a["score"] <= 100 for a in out["axes"])
    donut = {d["id"]: d["value"] for d in out["donut"]}
    assert donut == {"coding": 3, "riset": 1, "ppt": 1, "browser": 1, "otomasi": 2, "lainnya": 1}
    assert out["totals"]["tool_calls"] == 8  # codemode counts its 2 inner calls, not itself
    assert out["totals"]["sessions"] == 2 and out["totals"]["automated_sessions"] == 1
    assert out["totals"]["turns"] == 3  # hidden nudges are not turns
    assert out["totals"]["tokens"] == 1700
    assert out["totals"]["active_days"] == 2 and out["totals"]["streak"] == 2
    daily = {d["date"]: d for d in out["trend"]["daily"]}
    assert daily["2026-10-14"]["calls"] == 5 and daily["2026-10-14"]["tokens"] == 1200
    assert daily["2026-10-13"]["calls"] == 3 and daily["2026-10-13"]["turns"] == 1
    assert sum(w["calls"] for w in out["trend"]["weekly"]) == 8
    top = {r["name"]: r for r in out["tools_top"]}
    assert top["memory"]["axis"] == "lainnya" and top["edit_file"]["axis"] == "coding"


def test_window_and_reference_scale(tmp_path):
    sd = tmp_path / "sessions"
    _write_session(sd, "a", [{"role": "assistant", "ts": _ts(2026, 10, 1), "tool_calls": [_call("edit_file")]}])
    week = pk.compute(home=tmp_path, now=NOW, days=7)
    month = pk.compute(home=tmp_path, now=NOW, days=30)
    assert week["empty"] and not month["empty"]
    assert week["axes"][0]["reference"] < month["axes"][0]["reference"]
    assert pk.compute(home=tmp_path, now=NOW, days=0)["days"] == pk.DEFAULT_DAYS
    assert pk.compute(home=tmp_path, now=NOW, days=10_000)["days"] == pk.MAX_DAYS


def test_extra_tool_uses_inner_name(tmp_path):
    sd = tmp_path / "sessions"
    _write_session(sd, "a", [{"role": "assistant", "ts": _ts(2026, 10, 14),
                              "tool_calls": [_call("extra_tool", {"name": "browser_click"})]}])
    out = pk.compute(home=tmp_path, now=NOW)
    assert {a["id"]: a["value"] for a in out["axes"]}["browser"] == 1


async def test_api_pamerkan(home, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from neovarch.server import Gateway, build_app
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    gw = Gateway(False)
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    try:
        h = {"Authorization": "Bearer tok"}
        r = await client.get("/api/pamerkan?days=7", headers=h)
        data = await r.json()
        assert r.status == 200 and data["days"] == 7 and data["empty"] is True
        r = await client.get("/api/pamerkan?days=abc", headers=h)
        assert (await r.json())["days"] == pk.DEFAULT_DAYS
        assert (await client.get("/api/pamerkan")).status == 401
    finally:
        await client.close()
