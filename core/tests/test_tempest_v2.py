"""Tempest v2: web_search/web_fetch, in-context clipping (no offload for reads), parallel reads,
adaptive effort, explicit step-limit extension, diminishing-returns nudge and the grounding check.

Every network call is mocked."""

import asyncio
import base64
import re
import time

import pytest

from neovarch import config as cfgmod
from neovarch import tempest
from neovarch import tempest_ground as ground
from neovarch import tools as toolsmod
from neovarch import turn_budget as tb
from neovarch import web
from neovarch.agent import Agent
from neovarch.llm import Completion, ToolCall
from neovarch.store import SessionStore
from neovarch.tools import ToolContext

ARTICLE = ("<html><head><title>UMK Jabar 2026</title><script>var x=1</script></head><body>"
           "<nav>Beranda Berita Login</nav><header>Menu</header>"
           "<article><h1>UMK Kota Bandung 2026</h1>"
           + "".join(f"<p>Paragraf pengantar nomor {i} tentang ekonomi daerah dan berbagai hal lain.</p>" for i in range(8))
           + "<p>UMK Kota Bandung 2026 ditetapkan sebesar Rp4.482.914 oleh Gubernur Jawa Barat.</p>"
           "</article><footer>Copyright 2026</footer></body></html>")


@pytest.fixture(autouse=True)
def _clean_cache():
    web.cache_clear()
    yield
    web.cache_clear()


# ------------------------------------------------------------------ web.py -----

def test_extract_readable_keeps_article_drops_chrome():
    title, text = web.extract_readable(ARTICLE)
    assert title == "UMK Jabar 2026"
    assert "Rp4.482.914" in text and "var x" not in text and "Beranda Berita" not in text
    assert "Copyright" not in text


def test_js_shell_detection():
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    assert web.looks_js_shell(shell, web.extract_readable(shell)[1])
    assert not web.looks_js_shell(ARTICLE * 3, web.extract_readable(ARTICLE * 3)[1] * 3)


def test_smart_clip_keeps_the_matching_paragraph_deep_in_the_page():
    filler = "\n\n".join(f"Bagian {i}: teks umum yang panjang sekali tanpa kata kunci apa pun di dalamnya." for i in range(400))
    text = filler + "\n\nUMK Kota Bandung 2026 adalah Rp4.482.914.\n\n" + filler
    out = web.smart_clip(text, "UMK Kota Bandung 2026", 3000)
    assert "Rp4.482.914" in out and len(out) <= 3200
    assert web.smart_clip("pendek", "x", 3000) == "pendek"


def test_parse_ddg_and_bing():
    ddg = ('<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
           'https%3A%2F%2Fjabarprov.go.id%2Fumk&amp;rut=x">UMK <b>Bandung</b></a>'
           '<a class="result__snippet" href="#">UMK Kota Bandung 2026 Rp4.482.914</a></div>')
    res = web.parse_ddg(ddg)
    assert res == [{"title": "UMK Bandung", "url": "https://jabarprov.go.id/umk", "snippet": "UMK Kota Bandung 2026 Rp4.482.914"}]
    u = "a1" + base64.urlsafe_b64encode(b"https://example.id/umk").decode().rstrip("=")
    bing = (f'<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&amp;&amp;p=1&amp;u={u}&amp;ntb=1">UMK</a></h2>'
            '<div class="b_caption"><p>UMK Bandung naik</p></div></li>')
    assert web.parse_bing(bing)[0]["url"] == "https://example.id/umk"


async def test_search_falls_back_when_duckduckgo_blocks(monkeypatch):
    calls = []

    async def fake_get(url, *, data=None, timeout=20):
        calls.append(url)
        if "duckduckgo" in url:
            return 202, "text/html", "<div class='anomaly-modal'>bots</div>"
        if "bing.com" in url:
            u = "a1" + base64.urlsafe_b64encode(b"https://jabarprov.go.id/umk").decode().rstrip("=")
            return 200, "text/html", (f'<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u={u}">UMK Kota '
                                      'Bandung 2026</a></h2><p>UMK Kota Bandung 2026 resmi</p></li>')
        raise AssertionError(url)

    monkeypatch.setattr(web, "http_get", fake_get)
    res, backend = await web.search("UMK Kota Bandung 2026", lambda k, d=None: {"web.browser": "off"}.get(k, d), session="s")
    assert backend == "bing" and res[0]["url"] == "https://jabarprov.go.id/umk"
    n = len(calls)
    res2, backend2 = await web.search("UMK Kota Bandung 2026", lambda k, d=None: d, session="s")
    assert backend2 == "bing (cache)" and len(calls) == n  # per-session cache: no second request


async def test_search_irrelevant_filler_is_not_accepted(monkeypatch):
    async def fake_get(url, *, data=None, timeout=20):
        if "duckduckgo" in url:
            return 202, "text/html", ""
        if "bing.com" in url:
            return 200, "text/html", '<li class="b_algo"><h2><a href="https://umr.com">Sign in - UMR</a></h2><p>health plans</p></li>'
        return 200, "application/json", '{"query": {"search": [{"title": "Kota Bandung", "snippet": "kota"}]}}'

    monkeypatch.setattr(web, "http_get", fake_get)
    res, backend = await web.search("UMK Kota Bandung 2026 upah", lambda k, d=None: {"web.browser": "off"}.get(k, d))
    assert backend == "wikipedia" and "wikipedia.org" in res[0]["url"]


async def test_fetch_renders_js_shell_and_caches(monkeypatch):
    gets = []

    async def fake_get(url, *, data=None, timeout=20):
        gets.append(url)
        return 200, "text/html", '<html><body><div id="root"></div><script src="a.js"></script></body></html>'

    async def fake_render(url, timeout_ms=25000):
        return ARTICLE

    monkeypatch.setattr(web, "http_get", fake_get)
    monkeypatch.setattr(web, "browser_html", fake_render)
    page = await web.fetch("https://spa.example/umk", session="s")
    assert page["rendered"] and "Rp4.482.914" in page["text"]
    again = await web.fetch("https://spa.example/umk", session="s")
    assert again["cached"] and len(gets) == 1


async def test_web_search_tool_reads_top_pages_in_parallel(monkeypatch, tmp_path):
    async def fake_search(query, cfg_get=None, *, session="", n=6):
        return [{"title": f"R{i}", "url": f"https://s{i}.id/x", "snippet": "UMK"} for i in range(3)], "duckduckgo"

    active = {"now": 0, "max": 0}

    async def fake_fetch(url, *, session="", render="auto", cfg_get=None):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return {"url": url, "status": 200, "title": "t", "text": "UMK Kota Bandung 2026 Rp4.482.914", "rendered": False,
                "error": ""}

    monkeypatch.setattr(web, "search", fake_search)
    monkeypatch.setattr(web, "fetch", fake_fetch)
    out = await toolsmod.tool_web_search({"query": "UMK Kota Bandung 2026"}, ToolContext(cwd=tmp_path, approve=None))
    assert out.count("Isi halaman") == 2 and "https://s0.id/x" in out and "Rp4.482.914" in out
    assert active["max"] == 2  # both pages at once


# ----------------------------------------------------------- offload rules -----

def test_read_only_results_stay_in_context(tmp_path):
    big = "\n\n".join(f"baris {i} isi halaman biasa" for i in range(4000)) + "\n\nUMK Bandung Rp4.482.914"
    out = tempest.offload(big, "web_fetch", "c1", tmp_path / "obs", 2000, "UMK Bandung")
    assert not (tmp_path / "obs").exists()             # no file, so no read_file round trip
    assert "Rp4.482.914" in out and tempest.est_tokens(out) <= 6200
    small = "hasil pendek"
    assert tempest.offload(small, "web_search", "c2", tmp_path / "obs", 2000) == small
    shell = tempest.offload(big, "shell", "c3", tmp_path / "obs", 2000)
    assert "Lengkapnya di" in shell and (tmp_path / "obs").exists()  # non-read tools still offload


# ------------------------------------------------------------ turn budget -----

def _cfg(**kw):
    vals = {"agent.max_turns": 3, **kw}
    return lambda k, d: vals.get(k, d)


def test_step_limit_is_extended_explicitly_never_overrun():
    b = tb.TurnBudget.from_config(_cfg())
    notes = []
    for i in range(9):
        assert b.before_call() is None
        note = b.take_extension()
        if note:
            notes.append(note)
        p = b.progress_payload()
        assert p["step"] <= p["limit"], p  # never "langkah 9/3"
        b.record_tool("write_file", {"path": f"f{i}"}, "ok", True)
    assert len(notes) == 2 and "diperpanjang ke 6" in notes[0] and "diperpanjang ke 9" in notes[1]
    assert b.progress_payload()["extended"] == 2


def test_diminishing_returns_nudge_once():
    b = tb.TurnBudget.from_config(_cfg())
    for i in range(tb.WEB_NUDGE_CALLS - 1):
        b.record_tool("web_search", {"query": f"q{i}"}, "r", True)
        assert b.nudge() is None
    b.record_tool("web_fetch", {"url": "u"}, "r", True)
    assert "Jawab sekarang" in b.nudge()
    assert b.nudge() is None


# -------------------------------------------------------- adaptive effort -----

def test_step_effort_rules():
    tool_msg = [{"role": "assistant"}, {"role": "tool", "content": "ok"}]
    assert tempest.step_effort("ultra", "high", [{"role": "user"}], False, True) == "high"      # planning
    assert tempest.step_effort("ultra", "high", tool_msg, False, False) == "medium"              # routine
    assert tempest.step_effort("ultra", "high", tool_msg, True, False) == "high"                 # after failure
    assert tempest.step_effort("ultra", "high", tool_msg + [{"role": "user", "kind": "verify"}], False, False) == "high"
    assert tempest.step_effort("high", "high", tool_msg, False, False) == "low"
    assert tempest.step_effort("medium", "medium", tool_msg, False, False) == "medium"           # user's own pick
    assert tempest.step_effort("", None, tool_msg, False, False) is None


async def test_agent_adapts_effort_per_step(home, tmp_path, monkeypatch):
    efforts, n = [], {"i": 0}
    (tmp_path / "a.txt").write_text("isi")

    async def fake_complete(self, active, wire, pinned):
        efforts.append(self._effort)
        n["i"] += 1
        if n["i"] == 1:
            return Completion(tool_calls=[ToolCall(id="c1", name="read_file", arguments='{"path": "a.txt"}')])
        if n["i"] == 2:
            return Completion(tool_calls=[ToolCall(id="c2", name="read_file", arguments='{"path": "nope.txt"}')])
        if n["i"] == 3:
            return Completion(tool_calls=[ToolCall(id="c3", name="read_file", arguments='{"path": "a.txt", "offset": 1}')])
        return Completion(text="selesai")

    monkeypatch.setattr(Agent, "_complete", fake_complete)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    rec["reasoning_effort"] = "ultra"
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    await agent.run_turn("baca a.txt")
    # plan=high, routine=medium, after the failed read=high, routine again=medium
    assert efforts == ["high", "medium", "high", "medium"]
    assert tempest.PLAN_ONCE in rec["messages"][0]["wire_tail"]


# ------------------------------------------------------------ parallel reads -----

async def test_read_only_calls_of_one_message_run_in_parallel(home, tmp_path, monkeypatch):
    state = {"now": 0, "max": 0}

    async def slow_fetch(args, ctx):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.2)
        state["now"] -= 1
        return f"page {args['url']}"

    monkeypatch.setitem(toolsmod.TOOLS, "web_fetch", (slow_fetch, toolsmod.TOOLS["web_fetch"][1]))
    n = {"i": 0}

    async def fake_complete(self, active, wire, pinned):
        n["i"] += 1
        if n["i"] == 1:
            return Completion(tool_calls=[ToolCall(id=f"c{i}", name="web_fetch", arguments=f'{{"url": "https://x{i}.id"}}')
                                          for i in range(3)])
        return Completion(text="tidak ada angka di sini")

    monkeypatch.setattr(Agent, "_complete", fake_complete)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    t0 = time.monotonic()
    await agent.run_turn("buka 3 halaman")
    took = time.monotonic() - t0
    assert state["max"] == 3 and took < 0.5
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert [m["content"] for m in tool_msgs] == [f"page https://x{i}.id" for i in range(3)]  # order kept


# ------------------------------------------------------------- grounding -----

def test_grounding_numbers():
    src = ["UMK Kota Bandung 2026 ditetapkan Rp4.482.914, naik 6,5% dari Rp4.209.309."]
    assert ground.unsupported("UMK Bandung 2026: Rp 4.482.914 (naik 6,5%).", src) == []
    assert ground.unsupported("UMK Bandung 2026: Rp 5.100.000.", src) == ["Rp 5.100.000"]
    assert ground.unsupported("Rp 5.100.000", []) == []  # no web this turn: no check
    assert ground.unsupported("Lihat https://x.id/2026/9999 untuk 2026", src) == []


async def test_agent_grounding_check_asks_once_then_notes(home, tmp_path, monkeypatch):
    async def fake_fetch(args, ctx):
        return "URL: https://jabarprov.go.id\n\nUMK Kota Bandung 2026 Rp4.482.914"

    monkeypatch.setitem(toolsmod.TOOLS, "web_fetch", (fake_fetch, toolsmod.TOOLS["web_fetch"][1]))
    n = {"i": 0}
    seen = []

    async def fake_complete(self, active, wire, pinned):
        n["i"] += 1
        seen.append(wire[-1]["content"])
        if n["i"] == 1:
            return Completion(tool_calls=[ToolCall(id="c1", name="web_fetch", arguments='{"url": "https://jabarprov.go.id"}')])
        if n["i"] == 2:
            return Completion(text="UMK Bandung 2026 Rp5.100.000")
        return Completion(text="UMK Kota Bandung 2026 Rp4.482.914 (https://jabarprov.go.id)")

    monkeypatch.setattr(Agent, "_complete", fake_complete)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    final = await agent.run_turn("berapa UMK Bandung 2026?")
    assert n["i"] == 3 and ground.GROUND_MARK in seen[2] and "5.100.000" in seen[2]
    assert final.startswith("UMK Kota Bandung 2026 Rp4.482.914") and "tidak ditemukan di sumber" not in final


# --------------------------------------------- mocked lookup benchmark -----

async def _lookup_run(tmp_path, monkeypatch, v2: bool) -> dict:
    """'cari UMR Bandung 2026' with a scripted model: v1 had no web_search, so the model fetched a search
    page, got it offloaded to a file (>2000 tokens), read the file back, then did the same for the source."""
    cfg = cfgmod.load_config()
    cfg.setdefault("agent", {}).update({"tempest_adaptive_effort": v2, "tempest_parallel_tools": v2,
                                        "tempest_ground_check": v2})
    cfgmod.save_config(cfg)
    big_page = "\n".join(f"hasil {i}: berita ekonomi umum" for i in range(1500)) + "\nUMK Kota Bandung 2026 Rp4.482.914"

    async def fake_fetch(args, ctx):
        return "HTTP 200 text/html\n" + big_page

    async def fake_search(args, ctx):
        return ("Hasil pencarian 'UMK Kota Bandung 2026':\n1. UMK Jabar\n   https://jabarprov.go.id/umk\n"
                "--- Isi halaman ---\nURL: https://jabarprov.go.id/umk\n\nUMK Kota Bandung 2026 Rp4.482.914")

    monkeypatch.setitem(toolsmod.TOOLS, "web_fetch", (fake_fetch, toolsmod.TOOLS["web_fetch"][1]))
    monkeypatch.setitem(toolsmod.TOOLS, "web_search", (fake_search, toolsmod.TOOLS["web_search"][1]))
    stats = {"calls": 0, "prompt": 0}

    async def fake_complete(self, active, wire, pinned):
        stats["calls"] += 1
        stats["prompt"] += sum(len(str(m.get("content") or "")) for m in wire) // 4
        last = str(wire[-1].get("content") or "")
        if v2:
            if stats["calls"] == 1:
                return Completion(tool_calls=[ToolCall(id="s1", name="web_search",
                                                       arguments='{"query": "UMK Kota Bandung 2026"}')])
            return Completion(text="UMK Kota Bandung 2026: Rp4.482.914 (https://jabarprov.go.id/umk)")
        if stats["calls"] in (1, 3):
            url = "https://duckduckgo.com/html/?q=umk+bandung+2026" if stats["calls"] == 1 else "https://jabarprov.go.id/umk"
            return Completion(tool_calls=[ToolCall(id=f"f{stats['calls']}", name="web_fetch", arguments=f'{{"url": "{url}"}}')])
        if stats["calls"] in (2, 4):
            path = re.search(r"Lengkapnya di (\S+)", last).group(1)
            return Completion(tool_calls=[ToolCall(id=f"r{stats['calls']}", name="read_file",
                                                   arguments=f'{{"path": "{path}", "offset": 1490}}')])
        return Completion(text="UMK Kota Bandung 2026: Rp4.482.914 (https://jabarprov.go.id/umk)")

    monkeypatch.setattr(Agent, "_complete", fake_complete)
    if not v2:  # v1 behaviour: every big read-only result except read_file was offloaded
        monkeypatch.setattr(toolsmod, "READ_ONLY_TOOLS", frozenset({"read_file"}))
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    final = await agent.run_turn("cari UMR Bandung 2026")
    stats["tools"] = sum(1 for m in rec["messages"] if m.get("role") == "tool")
    stats["ok"] = "Rp4.482.914" in final
    return stats


async def test_mock_lookup_benchmark_v1_vs_v2(home, tmp_path, monkeypatch, capsys):
    with monkeypatch.context() as mp:
        before = await _lookup_run(tmp_path / "v1", mp, v2=False)
    with monkeypatch.context() as mp:
        after = await _lookup_run(tmp_path / "v2", mp, v2=True)
    with capsys.disabled():
        print(f"\n[tempest v2 mock bench] before: {before}  after: {after}")
    assert before["ok"] and after["ok"]
    assert before["calls"] == 5 and after["calls"] == 2
    assert after["prompt"] < before["prompt"]
