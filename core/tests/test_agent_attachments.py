"""Files the agent sends into the chat (send_file) and how clients fetch them.

Covers: the send_file tool, the store-on-reply flow in the agent loop, the
final-answer safety net, refusal of credentials, and GET /api/uploads/<id>
(auth required, id lookup only, no path traversal).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _ctx(tmp_path, session_id="s1"):
    from neovarch.tools import ToolContext

    async def approve(*_a):
        return "once"
    return ToolContext(cwd=tmp_path, approve=approve, session_id=session_id)


# ------------------------------------------------------------------ tool -----

async def test_send_file_stages_copy_with_agent_origin(home, tmp_path):
    from neovarch.tools import run_tool
    from neovarch import uploads
    shot = tmp_path / "landing" / "screenshot.png"
    shot.parent.mkdir()
    shot.write_bytes(PNG)
    ctx = _ctx(tmp_path)
    out = await run_tool("send_file", {"paths": [str(shot)]}, ctx)
    assert out.startswith("sent image: screenshot.png"), out
    assert len(ctx.outbox) == 1
    meta = ctx.outbox[0]
    assert meta["origin"] == "agent" and meta["kind"] == "image" and meta["mime"] == "image/png"
    assert meta["source_path"] == str(shot)
    # a copy inside the uploads store, not the original path
    assert Path(meta["path"]).parent.parent == uploads.root()
    assert Path(meta["path"]).read_bytes() == PNG
    pub = uploads.public(meta)
    assert pub["url"] == f"/api/uploads/{meta['id']}" and pub["origin"] == "agent"


async def test_send_file_relative_path_and_dedupe(home, tmp_path):
    from neovarch.tools import run_tool
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 hello")
    ctx = _ctx(tmp_path)
    await run_tool("send_file", {"path": "report.pdf"}, ctx)
    again = await run_tool("send_file", {"paths": ["report.pdf"]}, ctx)
    assert "already sent" in again
    assert len(ctx.outbox) == 1 and ctx.outbox[0]["kind"] == "file"


@pytest.mark.parametrize("rel", [".ssh/id_ed25519", "proj/.env", "keys/server.pem", ".aws/credentials"])
async def test_send_file_refuses_credentials(home, tmp_path, rel):
    from neovarch.tools import run_tool
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("secret")
    ctx = _ctx(tmp_path)
    out = await run_tool("send_file", {"paths": [str(p)]}, ctx)
    assert out.startswith("error"), out
    assert ctx.outbox == []


async def test_send_file_refuses_core_config_and_missing(home, tmp_path):
    from neovarch.tools import run_tool
    (home / "config.yaml").write_text("model: x")
    ctx = _ctx(tmp_path)
    out = await run_tool("send_file", {"paths": [str(home / "config.yaml"), str(tmp_path / "nope.png"), str(tmp_path)]}, ctx)
    assert out.count("error") == 3, out
    assert ctx.outbox == []


def test_send_file_in_schema():
    from neovarch.tools import tool_schemas
    names = {t["function"]["name"] for t in tool_schemas(None)}
    assert "send_file" in names


def test_system_prompt_mentions_send_file(home, tmp_path):
    from neovarch.agent import system_prompt
    assert "send_file" in system_prompt({}, tmp_path, "kirim screenshot ke sini")


# --------------------------------------------------------- agent loop --------

class _Comp:
    def __init__(self, text="", tool_calls=None):
        self.text, self.tool_calls, self.usage, self.reasoning = text, tool_calls or [], {}, ""
        self.reasoning_skipped = False


class _Call:
    def __init__(self, cid, name, args):
        self.id, self.name, self.arguments = cid, name, json.dumps(args)

    def parsed_args(self):
        return json.loads(self.arguments)


def _agent(home, tmp_path, script):
    from neovarch.agent import Agent
    from neovarch.store import SessionStore
    store = SessionStore()
    rec = store.create(source="test", cwd=str(tmp_path))
    events: list[tuple[str, dict]] = []
    ctx = _ctx(tmp_path, rec["id"])
    agent = Agent(rec, store, ctx, lambda k, p: events.append((k, p)))
    replies = iter(script)

    async def fake_complete(active, wire, pinned):
        return next(replies)
    agent._complete = fake_complete  # type: ignore[assignment]
    return agent, rec, store, events


def _patch_endpoint(monkeypatch):
    from neovarch import models as modelsmod
    monkeypatch.setattr(modelsmod, "endpoint_for", lambda cfg, key: {
        "provider": "custom:test", "model": "test-model", "base_url": "http://x", "api_key": ""})


async def test_turn_stores_sent_files_on_reply_and_emits(home, tmp_path, monkeypatch):
    _patch_endpoint(monkeypatch)
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    agent, rec, store, events = _agent(home, tmp_path, [
        _Comp(tool_calls=[_Call("c1", "send_file", {"paths": [str(shot)]})]),
        _Comp(text="Ini screenshot-nya."),
    ])
    await agent.run_turn("buat screenshot lalu kirim ke sini")
    kinds = [k for k, _ in events]
    assert "message.attachment" in kinds
    att_ev = next(p for k, p in events if k == "message.attachment")["attachment"]
    assert att_ev["kind"] == "image" and att_ev["origin"] == "agent" and att_ev["url"].startswith("/api/uploads/")
    done = next(p for k, p in events if k == "message.complete")
    assert [a["id"] for a in done["attachments"]] == [att_ev["id"]]
    saved = store.load(rec["id"])
    last = saved["messages"][-1]
    assert last["role"] == "assistant" and last["content"] == "Ini screenshot-nya."
    assert last["attachments"][0]["id"] == att_ev["id"]
    # history the phone/desktop read carries them on the assistant row
    from neovarch.server import to_ui_messages
    ui = to_ui_messages(saved)
    assert ui[-1]["attachments"][0]["url"] == f"/api/uploads/{att_ev['id']}"
    # and they never go to the model as content
    from neovarch.agent import wire_messages
    assert all("attachments" not in m for m in wire_messages(saved["messages"], False, tmp_path))


async def test_safety_net_attaches_fresh_files_named_in_answer(home, tmp_path, monkeypatch):
    _patch_endpoint(monkeypatch)
    old = tmp_path / "old.png"
    old.write_bytes(PNG)
    past = time.time() - 3600
    os.utime(old, (past, past))
    agent, rec, store, events = _agent(home, tmp_path, [
        _Comp(tool_calls=[_Call("c1", "write_file", {"path": str(tmp_path / "landing" / "screenshot.png"), "content": "x"})]),
        _Comp(text=f"Sudah, screenshot ada di `{tmp_path / 'landing' / 'screenshot.png'}` dan juga {old}."),
    ])
    await agent.run_turn("ambil screenshot lalu kirim ke sini ya")
    done = next(p for k, p in events if k == "message.complete")
    names = [a["name"] for a in done.get("attachments", [])]
    assert names == ["screenshot.png"]  # the stale file is not attached


async def test_safety_net_off_when_not_asked(home, tmp_path, monkeypatch):
    _patch_endpoint(monkeypatch)
    agent, rec, store, events = _agent(home, tmp_path, [
        _Comp(tool_calls=[_Call("c1", "write_file", {"path": str(tmp_path / "a.png"), "content": "x"})]),
        _Comp(text=f"Dibuat: {tmp_path / 'a.png'}"),
    ])
    await agent.run_turn("buat gambar a.png")
    done = next(p for k, p in events if k == "message.complete")
    assert "attachments" not in done


def test_paths_in_text_windows_and_posix(tmp_path):
    from neovarch import outbox
    f = tmp_path / "x.png"
    f.write_bytes(PNG)
    found = outbox.paths_in_text(f"lihat {f}.", tmp_path, time.time() - 10)
    assert found == [f]
    # Windows-style paths are recognised by the pattern (resolution is per-OS)
    m = outbox._PATH_RE.search(r"tersimpan di C:\Users\me\landing\shot.png sekarang")
    assert m and m.group(1) == r"C:\Users\me\landing\shot.png"


# --------------------------------------------------------- HTTP endpoint -----

@pytest.fixture()
async def client(home, monkeypatch):
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok-123")
    monkeypatch.setenv("NEOVARCH_SOCIAL_DISABLE", "1")
    from neovarch.server import Gateway, build_app
    gw = Gateway(isolated=False)
    app = build_app(gw)
    c = TestClient(TestServer(app))
    await c.start_server()
    try:
        yield c, gw
    finally:
        await c.close()


async def test_upload_download_requires_auth_and_serves_by_id(client, tmp_path):
    c, gw = client
    from neovarch import outbox
    src = tmp_path / "shot.png"
    src.write_bytes(PNG)
    meta = outbox.stage(gw.uploads, "s1", str(src), tmp_path)
    r = await c.get(f"/api/uploads/{meta['id']}")
    assert r.status == 401
    r = await c.get(f"/api/uploads/{meta['id']}", headers={"Authorization": "Bearer tok-123"})
    assert r.status == 200 and await r.read() == PNG
    assert r.headers["Content-Type"] == "image/png"
    r = await c.get(f"/api/uploads/{meta['id']}?token=tok-123&download=1")
    assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]


@pytest.mark.parametrize("bad", ["..%2F..%2Fconfig.yaml", "%2e%2e", "../../etc/passwd", "*", "abc", "0123456789ab/../x"])
async def test_upload_get_rejects_traversal(client, bad):
    c, gw = client
    r = await c.get(f"/api/uploads/{bad}", headers={"Authorization": "Bearer tok-123"})
    assert r.status in (404, 400), (bad, r.status)
    if r.status == 200:
        pytest.fail("served something for a non-id")


async def test_sidecar_pointing_outside_store_is_ignored(client, home, tmp_path):
    c, gw = client
    from neovarch import uploads
    secret = tmp_path / "outside.txt"
    secret.write_text("top secret")
    d = uploads.root() / "s1"
    d.mkdir(parents=True, exist_ok=True)
    uid = "aaaaaaaaaaaa"
    (d / f"{uid}.json").write_text(json.dumps({"id": uid, "name": "x.txt", "mime": "text/plain", "size": 10,
                                                "kind": "file", "path": str(secret)}))
    r = await c.get(f"/api/uploads/{uid}", headers={"Authorization": "Bearer tok-123"})
    assert r.status == 404
