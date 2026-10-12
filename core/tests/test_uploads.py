"""Chat attachments: upload endpoint (phone POST /api/uploads), binary downloads,
vision / non-vision wiring, desktop staging RPCs (image.attach*, file.attach) and
the chunked upload RPC."""

import asyncio
import base64
import json

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from neovarch import config as cfgmod
from neovarch.server import Gateway, build_app

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
H = {"Authorization": "Bearer tok"}


@pytest.fixture
async def capture(home):
    """OpenAI-compatible provider that records every request body."""
    seen: list[dict] = []

    async def completions(request):
        seen.append(await request.json())
        return web.json_response({"choices": [{"message": {"role": "assistant", "content": "siap"},
                                               "finish_reason": "stop"}], "usage": {}})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    server = TestServer(app)
    await server.start_server()
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "gpt-4o-mini", "base_url": str(server.make_url("/v1")),
                    "context_length": 1000}
    cfgmod.save_config(cfg)
    yield seen
    await server.close()


async def _client(monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setenv("NEOVARCH_SOCIAL_DISABLE", "1")
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    return gw, c


def _set_model(model: str, vision=None):
    cfg = cfgmod.load_config()
    cfg["model"]["default"] = model
    if vision is None:
        cfg["model"].pop("vision", None)
    else:
        cfg["model"]["vision"] = vision
    cfgmod.save_config(cfg)


async def _wait_idle(gw, sid, timeout=10):
    for _ in range(int(timeout * 20)):
        live = gw.live.get(sid)
        if live and live.task and live.task.done():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("turn did not finish")


async def _upload(c, sid, name, data, ctype):
    fd = FormData()
    fd.add_field("session_id", sid)
    fd.add_field("file", data, filename=name, content_type=ctype)
    return await c.post("/api/uploads", data=fd, headers=H)


async def test_upload_download_and_auth(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        fd = FormData()
        fd.add_field("file", b"x", filename="a.txt")
        assert (await c.post("/api/uploads", data=fd)).status == 401
        r = await _upload(c, "s1", "../../etc/foto saya.png", PNG, "application/octet-stream")
        assert r.status == 200
        meta = await r.json()
        assert meta["kind"] == "image" and meta["mime"] == "image/png" and meta["size"] == len(PNG)
        assert meta["name"] == "foto saya.png" and meta["url"] == f"/api/uploads/{meta['id']}"
        assert str(home / "uploads" / "s1") in meta["path"]
        d = await c.get(meta["url"], headers=H)
        assert d.status == 200 and await d.read() == PNG and d.headers["Content-Type"] == "image/png"
        assert (await c.get(meta["url"])).status == 401
        dl = await c.get(meta["url"] + "?download=1", headers=H)
        assert dl.headers["Content-Disposition"].startswith("attachment")
        lst = await (await c.get("/api/uploads?session_id=s1", headers=H)).json()
        assert [a["id"] for a in lst["attachments"]] == [meta["id"]]
        # binary download of any file (reports etc.)
        f = home / "laporan.docx"
        f.write_bytes(b"PK\x03\x04binary\x00\xff")
        fsr = await c.get(f"/api/fs/download?path={f}", headers=H)
        assert fsr.status == 200 and await fsr.read() == b"PK\x03\x04binary\x00\xff"
        assert "laporan.docx" in fsr.headers["Content-Disposition"]
        assert (await c.get(f"/api/fs/download?path={home}/nope.bin", headers=H)).status == 404
        assert (await c.delete(meta["url"], headers=H)).status == 200
        assert (await c.get(meta["url"], headers=H)).status == 404
    finally:
        await c.close()


async def test_upload_limit_25mb(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        big = b"0" * (25 * 1024 * 1024 + 1)
        r = await _upload(c, "s1", "big.bin", big, "application/octet-stream")
        assert r.status == 413
        assert not list((home / "uploads").rglob("*big.bin"))
        r = await c.post("/api/uploads?filename=raw.txt&session_id=s2", data=b"halo", headers={**H, "Content-Type": "text/plain"})
        assert r.status == 200 and (await r.json())["kind"] == "file"
        assert (await _upload(c, "s1", "empty.txt", b"", "text/plain")).status == 400
    finally:
        await c.close()


async def _session(c):
    ws = await c.ws_connect("/api/ws?token=tok")
    await ws.receive_json()  # gateway.ready
    n = 0

    async def call(method, params):
        nonlocal n
        n += 1
        await ws.send_json({"jsonrpc": "2.0", "id": n, "method": method, "params": params})
        while True:
            msg = await ws.receive_json(timeout=10)
            if msg.get("id") == n and "method" not in msg:
                return msg
    created = await call("session.create", {})
    return ws, call, created["result"]["session_id"]


async def test_image_goes_to_vision_model_as_data_url(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        meta = await (await _upload(c, sid, "layar.png", PNG, "image/png")).json()
        res = await call("prompt.submit", {"session_id": sid, "text": "apa ini?", "attachments": [meta["id"]]})
        assert res["result"]["ok"] and "notice" not in res["result"]
        await _wait_idle(gw, sid)
        user = capture[-1]["messages"][-1]
        assert user["role"] == "user" and isinstance(user["content"], list)
        assert user["content"][0]["type"] == "text" and user["content"][0]["text"].startswith("apa ini?")
        img = user["content"][1]
        assert img["type"] == "image_url"
        assert img["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
        # transcript keeps a reference (not bytes) and the UI sees a downloadable attachment
        msgs = (await (await c.get(f"/api/sessions/{sid}/messages", headers=H)).json())["messages"]
        u = [m for m in msgs if m["role"] == "user"][0]
        assert u["attachments"][0]["id"] == meta["id"] and u["attachments"][0]["url"].startswith("/api/uploads/")
        assert "base64" not in json.dumps(gw.store.load(sid)["messages"])
        await ws.close()
    finally:
        await c.close()


async def test_image_without_vision_gets_notice_and_path(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        _set_model("deepseek-chat")
        ws, call, sid = await _session(c)
        meta = await (await _upload(c, sid, "layar.png", PNG, "image/png")).json()
        res = await call("prompt.submit", {"session_id": sid, "text": "", "attachments": [meta["id"]]})
        assert "tidak mendukung input gambar" in res["result"]["notice"]
        await _wait_idle(gw, sid)
        user = capture[-1]["messages"][-1]
        assert isinstance(user["content"], str)
        assert meta["path"] in user["content"] and "tidak mendukung input gambar" in user["content"]
        # explicit override wins over the name heuristic
        _set_model("deepseek-chat", vision=True)
        res = await call("prompt.submit", {"session_id": sid, "text": "lagi", "attachments": [meta["id"]]})
        await _wait_idle(gw, sid)
        assert isinstance(capture[-1]["messages"][-1]["content"], list)
        bad = await call("prompt.submit", {"session_id": sid, "text": "x", "attachments": ["000000000000"]})
        assert "error" in bad
        await ws.close()
    finally:
        await c.close()


async def test_text_and_code_files_are_extracted(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        code = await (await _upload(c, sid, "main.py", b"def halo():\n    return 42\n", "text/x-python")).json()
        blob = await (await _upload(c, sid, "data.bin", b"\x00\x01\x02binary", "application/octet-stream")).json()
        await call("prompt.submit", {"session_id": sid, "text": "review", "attachments": [code["id"], blob["id"]]})
        await _wait_idle(gw, sid)
        content = capture[-1]["messages"][-1]["content"]
        assert "def halo():" in content and code["path"] in content
        assert blob["path"] in content and "tidak bisa diekstrak" in content
        await ws.close()
    finally:
        await c.close()


async def test_desktop_staging_rpcs(capture, monkeypatch, home, tmp_path):
    """The desktop composer: image.attach_bytes / image.attach stage images for the next
    prompt.submit; file.attach returns an @file: ref whose text reaches the model."""
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        r = await call("image.attach_bytes", {"session_id": sid, "content_base64": base64.b64encode(PNG).decode(),
                                              "filename": "tempel.png"})
        assert r["result"]["attached"] and r["result"]["count"] == 1
        host_img = tmp_path / "drop.png"
        host_img.write_bytes(PNG)
        r2 = await call("image.attach", {"session_id": sid, "path": str(host_img)})
        assert r2["result"]["attached"] and r2["result"]["count"] == 2
        det = await call("image.detach", {"session_id": sid, "path": r2["result"]["path"]})
        assert det["result"] == {"detached": True, "count": 1}
        note = tmp_path / "catatan rapat.md"
        note.write_text("# Rapat\nkeputusan: rilis jumat\n")
        f = await call("file.attach", {"session_id": sid, "path": str(note), "name": note.name})
        assert f["result"]["attached"] and f["result"]["ref_text"] == f'@file:"{note}"'
        up = await call("file.attach", {"session_id": sid, "name": "x.txt",
                                        "data_url": "data:text/plain;base64," + base64.b64encode(b"isi remote").decode()})
        assert up["result"]["uploaded"] and up["result"]["ref_text"].startswith("@file:")
        text = f["result"]["ref_text"] + "\n" + up["result"]["ref_text"] + "\n\nringkas"
        await call("prompt.submit", {"session_id": sid, "text": text})
        await _wait_idle(gw, sid)
        user = capture[-1]["messages"][-1]
        assert [p["type"] for p in user["content"]] == ["text", "image_url"]
        assert "keputusan: rilis jumat" in user["content"][0]["text"] and "isi remote" in user["content"][0]["text"]
        assert gw.live[sid].pending_attachments == []
        bad = await call("image.attach", {"session_id": sid, "path": str(note)})
        assert bad["result"]["attached"] is False
        await ws.close()
    finally:
        await c.close()


async def test_chunked_upload_rpc(capture, monkeypatch, home):
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        data = PNG * 3
        first = await call("attachment.upload_chunk", {"session_id": sid, "filename": "p.png", "mime": "image/png",
                                                       "data": base64.b64encode(data[:40]).decode()})
        uid = first["result"]["upload_id"]
        assert first["result"]["done"] is False and first["result"]["received"] == 40
        last = await call("attachment.upload_chunk", {"session_id": sid, "upload_id": uid, "final": True,
                                                      "data": base64.b64encode(data[40:]).decode()})
        assert last["result"]["done"] and last["result"]["size"] == len(data) and last["result"]["kind"] == "image"
        got = await (await c.get(last["result"]["url"], headers=H)).read()
        assert got == data
        await ws.close()
    finally:
        await c.close()


async def test_upload_is_not_swallowed_by_the_quiet_fallback(capture, monkeypatch, home):
    """Regression (phone 1.4.5 on a core without the route): the compat fallback
    answered POST /api/uploads with 200 {"name": "uploads", ...} and no id, so the
    phone showed an "uploads · 0 B" card and the agent got no image."""
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        r = await _upload(c, sid, "scaled_1000000034.jpg", PNG, "image/jpeg")
        assert r.status == 200
        meta = await r.json()
        assert meta["name"] == "scaled_1000000034.jpg" and meta["name"] != "uploads"
        assert meta["size"] == len(PNG) and len(meta["id"]) == 12 and meta["kind"] == "image"
        assert "available" not in meta
        res = await call("prompt.submit", {"session_id": sid, "text": "ini", "attachments": [meta["id"]]})
        assert res["result"]["attachments"][0]["id"] == meta["id"]
        await _wait_idle(gw, sid)
        parts = capture[-1]["messages"][-1]["content"]
        # Tempest (default) appends the per-message context after the typed text, image stays attached
        assert parts[0]["type"] == "text" and parts[0]["text"].split("\n\n# Konteks saat ini")[0] == "ini"
        assert parts[1]["type"] == "image_url"
        # an empty / unknown id is refused instead of silently dropping the image
        bad = await call("prompt.submit", {"session_id": sid, "text": "ini", "attachments": [""]})
        assert "error" in bad
        await ws.close()
    finally:
        await c.close()


async def test_one_message_carries_several_images_and_files(capture, monkeypatch, home):
    """v1.4.7 multi-lampiran: several images + a file in one prompt.submit reach the
    model as one user turn (one image_url part per image, file text inline)."""
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        ids = []
        for i in range(3):
            ids.append((await (await _upload(c, sid, f"foto-{i}.png", PNG, "image/png")).json())["id"])
        ids.append((await (await _upload(c, sid, "catatan.md", b"# Catatan\nisi catatan multi", "text/markdown")).json())["id"])
        res = await call("prompt.submit", {"session_id": sid, "text": "bandingkan", "attachments": ids})
        assert res["result"]["ok"] and len(res["result"]["attachments"]) == 4
        await _wait_idle(gw, sid)
        user = capture[-1]["messages"][-1]
        assert [p["type"] for p in user["content"]] == ["text", "image_url", "image_url", "image_url"]
        assert "isi catatan multi" in user["content"][0]["text"]
        msgs = (await (await c.get(f"/api/sessions/{sid}/messages", headers=H)).json())["messages"]
        users = [m for m in msgs if m["role"] == "user"]
        assert len(users) == 1 and [a["id"] for a in users[0]["attachments"]] == ids
        await ws.close()
    finally:
        await c.close()


async def test_attachment_count_limit_is_clear(capture, monkeypatch, home):
    from neovarch import uploads as upmod
    gw, c = await _client(monkeypatch)
    try:
        ws, call, sid = await _session(c)
        ids = [(await (await _upload(c, sid, f"f{i}.txt", b"x%d" % i, "text/plain")).json())["id"]
               for i in range(upmod.MAX_PER_MESSAGE + 1)]
        res = await call("prompt.submit", {"session_id": sid, "text": "kebanyakan", "attachments": ids})
        assert "error" in res and res["error"]["message"] == upmod.TOO_MANY
        assert "Maksimal 10 lampiran" in res["error"]["message"]
        ok = await call("prompt.submit", {"session_id": sid, "text": "pas", "attachments": ids[:upmod.MAX_PER_MESSAGE]})
        assert ok["result"]["ok"]
        await _wait_idle(gw, sid)
        # desktop staging stops at the same limit with the same plain message
        b64 = base64.b64encode(PNG).decode()
        for i in range(upmod.MAX_PER_MESSAGE):
            r = await call("image.attach_bytes", {"session_id": sid, "content_base64": b64, "filename": f"p{i}.png"})
            assert r["result"]["attached"] and r["result"]["count"] == i + 1
        over = await call("image.attach_bytes", {"session_id": sid, "content_base64": b64, "filename": "lagi.png"})
        assert over["result"]["attached"] is False and over["result"]["message"] == upmod.TOO_MANY
        assert len(gw.live[sid].pending_attachments) == upmod.MAX_PER_MESSAGE
        await ws.close()
    finally:
        await c.close()
