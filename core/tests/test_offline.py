"""Mode 1 (luring): fallback ke model lokal saat provider online gagal total."""

import json

from aiohttp import web

from test_server import _client

H = {"Authorization": "Bearer tok"}


def build_local_app(models: list[str] | None = None, fail: bool = False) -> web.Application:
    app = web.Application()

    async def list_models(_):
        return web.json_response({"data": [{"id": m} for m in (models or ["local-tiny"])]})

    async def completions(request):
        if fail:
            return web.json_response({"error": {"message": "boom"}}, status=500)
        body = await request.json()
        text = f"JAWABAN LOKAL: {body.get('messages', [{}])[-1].get('content', '')[:80]}"
        if not body.get("stream"):
            return web.json_response({"choices": [{"message": {"role": "assistant", "content": text}}]})
        event = {"id": "local", "object": "chat.completion.chunk", "model": body.get("model", "local"),
                 "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
        done = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
        end = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        payload = "".join(f"data: {json.dumps(e)}\n\n" for e in (event, done, end)) + "data: [DONE]\n\n"
        return web.Response(body=payload.encode(), content_type="text/event-stream")

    app.router.add_get("/models", list_models)
    app.router.add_post("/chat/completions", completions)
    return app


async def test_offline_status_endpoint(monkeypatch):
    monkeypatch.setenv("NEOVARCH_OFFLINE_ENABLED", "1")
    monkeypatch.setenv("NEOVARCH_OFFLINE_BASE_URL", "http://127.0.0.1:9/v1")
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        st = await (await c.get("/api/offline/status", headers=H)).json()
        assert st["enabled"] is True
        assert st["available"] is False  # nothing listens on port 9
    finally:
        await c.close()


async def test_offline_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NEOVARCH_OFFLINE_ENABLED", "0")
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        st = await (await c.get("/api/offline/status", headers=H)).json()
        assert st["enabled"] is False and st["available"] is False
    finally:
        await c.close()


async def test_offline_module_finds_local_server(monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    client = TestClient(TestServer(build_local_app(["tiny-id", "small-id"])))
    await client.start_server()
    try:
        from neovarch import offline
        monkeypatch.setenv("NEOVARCH_OFFLINE_ENABLED", "1")
        monkeypatch.setenv("NEOVARCH_OFFLINE_BASE_URL", f"http://127.0.0.1:{client.server.port}")
        monkeypatch.setenv("NEOVARCH_OFFLINE_MODEL", "small-id")
        offline.reset()
        ep = await offline.endpoint({"model": {"base_url": "", "provider": ""}})
        assert ep is not None
        assert ep["model"] == "small-id"
        text = await offline.answer(ep["base_url"], ep["model"], "halo")
        assert text.startswith("JAWABAN LOKAL")
        st = await offline.status({"model": {"base_url": "", "provider": ""}})
        assert st["available"] is True and "tiny-id" in st["models"]
    finally:
        await client.close()
