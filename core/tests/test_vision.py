"""Vision fallback: detection, choice, cache, queue, timeout, config off, image_ask."""

import asyncio
import base64

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import mock_llm
from neovarch import config as cfgmod
from neovarch import uploads, vision
from neovarch.agent import Agent
from neovarch.store import SessionStore
from neovarch.tools import ToolContext, run_tool, tool_schemas

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

ROUTER_MODELS = [  # shaped like 9Router's GET /v1/models
    {"id": "oc/mimo-v2.6-flash-free", "object": "model", "owned_by": "oc",
     "capabilities": {"vision": False, "tools": True, "contextWindow": 262144}, "context_length": 262144},
    {"id": "kr/claude-opus-4.8", "object": "model", "owned_by": "kr",
     "capabilities": {"vision": True, "tools": True}},
    {"id": "gm/gemini-2.5-flash", "object": "model", "owned_by": "gm",
     "capabilities": {"vision": True, "tools": True}},
    {"id": "qw/qwen2.5-vl-7b", "object": "model", "owned_by": "qw"},  # no metadata: hints
    {"id": "emb/text-embedding-3", "object": "model", "kind": "embedding"},
]


@pytest.fixture
async def vsrv(home, monkeypatch):
    """A 9Router-like server: /v1/models plus a chat endpoint that records image requests."""
    state = {"models": [dict(m) for m in ROUTER_MODELS], "calls": [], "delay": 0.0, "inflight": 0,
             "max_inflight": 0, "reply": "Isi: tangkapan layar\nTeks: HALO DUNIA\nAngka/tabel: -\nUI: tombol OK"}

    async def models(_r):
        return web.json_response({"object": "list", "data": state["models"]})

    async def chat(r):
        body = await r.json()
        state["calls"].append(body)
        state["inflight"] += 1
        state["max_inflight"] = max(state["max_inflight"], state["inflight"])
        try:
            if state["delay"]:
                await asyncio.sleep(state["delay"])
        finally:
            state["inflight"] -= 1
        return web.json_response({"choices": [{"message": {"role": "assistant", "content": state["reply"]},
                                               "finish_reason": "stop"}], "usage": {}})

    app = web.Application()
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/chat/completions", chat)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", str(server.make_url("/v1")))
    vision.reset()
    yield state
    vision.reset()
    await server.close()


def _active():
    # A text-only chat model on an endpoint without a model list.
    return {"model": "deepseek-chat", "provider": "custom", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}


def _img(tmp_path, name, extra=b""):
    p = tmp_path / name
    p.write_bytes(PNG + extra)
    return {"id": "a" * 12, "name": name, "mime": "image/png", "size": p.stat().st_size, "kind": "image",
            "path": str(p)}


def _set_vision(**kw):
    cfg = cfgmod.load_config()
    cfg["vision"] = kw
    cfgmod.save_config(cfg)
    return cfg


def _image_of(call):
    return call["messages"][0]["content"][1]["image_url"]["url"]


def test_detection_from_metadata_and_hints():
    assert vision.classify({"id": "kr/x", "capabilities": {"vision": True}}) == (True, "metadata")
    # metadata wins over a name that looks like a vision model
    assert vision.classify({"id": "gpt-4o", "capabilities": {"vision": False}}) == (False, "metadata")
    assert vision.classify({"id": "or/foo", "architecture": {"input_modalities": ["text", "image"]}}) == \
        (True, "metadata")
    assert vision.classify({"id": "or/bar", "architecture": {"modality": "text+image->text"}}) == (True, "metadata")
    assert vision.classify({"id": "x/y", "input_modalities": ["text"]}) == (False, "metadata")
    # partial capabilities (9Router live catalogs often only say tools) -> hints
    assert vision.classify({"id": "gemini-2.5-flash", "capabilities": {"tools": True}}) == (True, "hints")
    assert vision.classify({"id": "qwen2.5-vl-7b"}) == (True, "hints")
    assert vision.classify({"id": "deepseek-chat"}) == (False, "hints")


def test_rank_prefers_cheap_fast_models():
    mk = lambda mid, price=None: vision.VisionModel(model=mid, provider="custom:x", base_url="http://h/v1",  # noqa: E731
                                                    source="metadata", price=price)
    ranked = vision.rank([mk("x/claude-opus-4"), mk("x/gpt-4o"), mk("x/gemini-2.5-flash")])
    assert ranked[0].model == "x/gemini-2.5-flash" and ranked[-1].model == "x/claude-opus-4"
    # a published price beats name hints
    ranked = vision.rank([mk("x/gemini-flash", None), mk("x/big-pro", 0.5), mk("x/other", 0.1)])
    assert [m.model for m in ranked] == ["x/other", "x/big-pro", "x/gemini-flash"]
    # the active model itself is never its own fallback
    assert vision.rank([mk("a/gpt-4o-mini"), mk("a/gpt-4o")], {"model": "a/gpt-4o-mini"})[0].model == "a/gpt-4o"


async def test_pick_fallback_from_9router_models(vsrv):
    cfg = cfgmod.load_config()
    models = await vision.vision_models(cfg, _active())
    ids = {m.model: m.source for m in models}
    assert ids == {"kr/claude-opus-4.8": "metadata", "gm/gemini-2.5-flash": "metadata", "qw/qwen2.5-vl-7b": "hints"}
    vm = await vision.pick_fallback(cfg, _active())
    assert vm.model == "gm/gemini-2.5-flash" and vm.provider == "9router"
    # the list is cached: a changed server list is not seen within the TTL
    vsrv["models"] = []
    assert (await vision.pick_fallback(cfg, _active())).model == "gm/gemini-2.5-flash"
    # explicit override, and off
    cfg = _set_vision(fallback_model="kr/claude-opus-4.8")
    vm = await vision.pick_fallback(cfg, _active())
    assert vm.model == "kr/claude-opus-4.8" and vm.source == "config"
    assert await vision.pick_fallback(_set_vision(fallback="off"), _active()) is None


async def test_cache_hit_avoids_second_call(vsrv, tmp_path):
    cfg = cfgmod.load_config()
    vm = await vision.pick_fallback(cfg, _active())
    a = _img(tmp_path, "satu.png")
    first = await vision.describe(cfg, vm, a)
    assert first["ok"] and not first["cached"] and "HALO DUNIA" in first["text"]
    b = _img(tmp_path, "salinan.png")  # same bytes under another name -> same sha256
    second = await vision.describe(cfg, vm, b)
    assert second["ok"] and second["cached"] and second["model"] == "gm/gemini-2.5-flash"
    assert len(vsrv["calls"]) == 1
    assert (vision.cache_dir() / f"{first['sha256']}.json").is_file()
    prompt = vsrv["calls"][0]["messages"][0]["content"][0]["text"]
    assert "Bahasa Indonesia" in prompt and "verbatim" in prompt


async def test_queue_keeps_order_and_limits_concurrency(vsrv, tmp_path):
    vsrv["delay"] = 0.05
    cfg = _set_vision(concurrency=1)
    vm = await vision.pick_fallback(cfg, _active())
    imgs = [_img(tmp_path, f"g{i}.png", bytes([i]) * 4) for i in range(4)]
    results = await vision.describe_all(cfg, vm, imgs)
    assert all(r["ok"] for r in results) and len(vsrv["calls"]) == 4
    assert vsrv["max_inflight"] == 1
    expected = [uploads.data_url(a) for a in imgs]
    assert [_image_of(c) for c in vsrv["calls"]] == expected
    assert [r["sha256"] for r in results] == [vision.image_sha(a["path"]) for a in imgs]


async def test_timeout_falls_back_to_notice(vsrv, tmp_path):
    vsrv["delay"] = 1.5
    cfg = _set_vision(timeout_s=0.3)
    atts = [_img(tmp_path, "lambat.png")]
    events = []
    ok = await vision.prepare_attachments(cfg, _active(), atts, lambda k, p: events.append((k, p)))
    assert ok is False and "vision_text" not in atts[0]
    notices = [p for k, p in events if k == "attachment.notice"]
    assert notices[-1]["level"] == "warning" and uploads.VISION_NOTICE in notices[-1]["message"]
    assert "tidak menjawab" in notices[-1]["message"]
    # the wire keeps the old notice plus path
    m = {"role": "user", "content": "apa ini?", "attachments": atts}
    w = vision.augment_wire(uploads.user_wire(m, False, True), m, False)
    assert atts[0]["path"] in w["content"] and uploads.VISION_NOTICE in w["content"]


async def test_config_off_keeps_old_behaviour(vsrv, tmp_path):
    cfg = _set_vision(fallback="off")
    atts = [_img(tmp_path, "mati.png")]
    events = []
    ok = await vision.prepare_attachments(cfg, _active(), atts, lambda k, p: events.append((k, p)))
    assert ok is False and vsrv["calls"] == []
    assert events == [("attachment.notice", {"level": "warning", "message": uploads.VISION_NOTICE})]
    assert vision.submit_notice(cfg) == uploads.VISION_NOTICE
    out = await run_tool("image_ask", {"path": atts[0]["path"], "question": "apa?"},
                         ToolContext(cwd=tmp_path, approve=None))
    assert out.startswith("error:") and "off" in out


async def test_image_ask_tool(vsrv, tmp_path):
    names = {t["function"]["name"] for t in tool_schemas()}
    assert "image_ask" in names
    vsrv["reply"] = "Tombolnya bertuliskan SIMPAN."
    a = _img(tmp_path, "ui.png")
    ctx = ToolContext(cwd=tmp_path, approve=None)
    out = await run_tool("image_ask", {"path": "ui.png", "question": "Tombol apa yang ada?"}, ctx)
    assert out == "[gm/gemini-2.5-flash] Tombolnya bertuliskan SIMPAN."
    text = vsrv["calls"][-1]["messages"][0]["content"][0]["text"]
    assert text.endswith("Tombol apa yang ada?")
    # same question again: cached, no new call
    assert await run_tool("image_ask", {"path": a["path"], "question": "Tombol apa yang ada?"}, ctx) == out
    assert len(vsrv["calls"]) == 1
    (tmp_path / "x.txt").write_text("bukan gambar")
    assert (await run_tool("image_ask", {"path": "x.txt", "question": "?"}, ctx)).startswith("error:")


async def test_agent_turn_injects_description(vsrv, mock_provider, tmp_path):
    """A text-only main model gets the fallback's description, labelled, plus a UI notice."""
    meta = uploads.UploadStore().save_bytes("s1", "layar.png", PNG, "image/png")
    events = []
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: events.append((k, p)))
    await agent.run_turn("apa isi gambar ini?", [meta])
    notices = [p for k, p in events if k == "attachment.notice"]
    assert notices and notices[0]["level"] == "info"
    assert notices[0]["message"] == vision.notice_text("gm/gemini-2.5-flash")
    sent = mock_provider.app[mock_llm.REQUESTS][0]["messages"][-1]
    assert isinstance(sent["content"], str)
    assert "Deskripsi otomatis gambar layar.png oleh model gm/gemini-2.5-flash" in sent["content"]
    assert "HALO DUNIA" in sent["content"] and uploads.VISION_NOTICE not in sent["content"]
    saved = store.load(rec["id"])["messages"][0]["attachments"][0]
    assert saved["vision_model"] == "gm/gemini-2.5-flash" and "HALO DUNIA" in saved["vision_text"]
    # a later turn replays the stored description without asking the vision model again
    await agent.run_turn("terus?")
    assert len(vsrv["calls"]) == 1
    again = mock_provider.app[mock_llm.REQUESTS][-1]["messages"]
    assert any("HALO DUNIA" in str(m.get("content")) for m in again if m["role"] == "user")
