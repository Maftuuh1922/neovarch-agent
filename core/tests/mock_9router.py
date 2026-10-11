"""A mock 9Router for tests: the parts of its API the Neovarch core uses.

    python core/tests/mock_9router.py -p 20128        # also usable as a fake `9router` command

* ``GET /api/health``, ``GET /api/version``;
* ``GET/POST /api/keys`` (need ``x-9r-cli-token``), ``GET /api/providers/suggested-models``,
  ``GET/POST /api/models/custom``;
* ``GET /v1/models`` (static aliases + registered custom models, like 9Router) and
  streaming ``POST /v1/chat/completions`` which requires the API key (``requireApiKey``)
  and answers ``Halo dari 9Router mock (<model>)``; models in state ``limited`` answer
  HTTP 429 FreeUsageLimitError (like OpenCode Free), models in ``down`` HTTP 503.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

from aiohttp import web

STATE = web.AppKey("state", dict)
FREE_IDS = ["mimo-v2.6-flash-free", "nemotron-3-ultra-free", "ling-3.1-flash-free"]
STATIC = ["oc/muse-spark-1.3-contributor-free", "kr/claude-sonnet-4.5", "kr/glm-5"]


def build_app(cli_token: str = "", *, free_ids: list[str] | None = None, require_key: bool = True,
              lazy_files: tuple | None = None) -> web.Application:
    """``lazy_files=(data_dir, machine_id, cli_secret)``: like the real 9Router, write
    machine-id and auth/cli-secret only when a request first carries a CLI token."""
    app = web.Application()
    app[STATE] = {"keys": [], "custom": [], "chats": [], "cli_token": cli_token, "limited": set(), "down": set(),
                  "attempts": [],
                  "free": list(FREE_IDS if free_ids is None else free_ids), "require_key": require_key}

    def st(r: web.Request) -> dict:
        return r.app[STATE]

    def cli_ok(r: web.Request) -> bool:
        if lazy_files and r.headers.get("x-9r-cli-token"):
            d, mid, secret = lazy_files
            (d / "auth").mkdir(parents=True, exist_ok=True)
            if not (d / "machine-id").exists():
                (d / "machine-id").write_text(mid)
                (d / "auth" / "cli-secret").write_text(secret)
        return bool(st(r)["cli_token"]) and r.headers.get("x-9r-cli-token") == st(r)["cli_token"]

    def denied() -> web.Response:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async def health(_):
        return web.json_response({"ok": True})

    async def version(_):
        return web.json_response({"currentVersion": "0.5.99", "latestVersion": "0.5.99", "hasUpdate": False})

    async def keys_get(r):
        if not cli_ok(r):
            return denied()
        return web.json_response({"keys": st(r)["keys"]})

    async def keys_post(r):
        if not cli_ok(r):
            return denied()
        body = await r.json()
        k = {"id": secrets.token_hex(4), "name": body["name"], "key": "sk-9r-" + secrets.token_hex(8), "isActive": True}
        st(r)["keys"].append(k)
        return web.json_response(k, status=201)

    async def suggested(r):
        if not cli_ok(r):
            return denied()
        return web.json_response({"data": [{"id": i, "name": i} for i in st(r)["free"]]})

    async def custom_get(r):
        if not cli_ok(r):
            return denied()
        return web.json_response({"models": st(r)["custom"]})

    async def custom_post(r):
        if not cli_ok(r):
            return denied()
        body = await r.json()
        st(r)["custom"].append({"providerAlias": body["providerAlias"], "id": body["id"], "type": "llm"})
        return web.json_response({"ok": True})

    async def models(r):
        ids = list(STATIC) + [f"{m['providerAlias']}/{m['id']}" for m in st(r)["custom"]]
        return web.json_response({"object": "list", "data": [
            {"id": i, "object": "model", "owned_by": i.split("/")[0]} for i in ids]})

    async def chat(r):
        state = st(r)
        if state["require_key"]:
            auth = r.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] not in {k["key"] for k in state["keys"]}:
                return web.json_response({"error": {"message": "Missing API key"}}, status=401)
        body = await r.json()
        state["attempts"].append(body.get("model"))
        if body.get("model") in state["limited"]:
            return web.json_response({"error": {"message": "FreeUsageLimitError: Rate limit exceeded. "
                                                "Please try again later.", "type": "FreeUsageLimitError"}}, status=429)
        if body.get("model") in state["down"]:
            return web.json_response({"error": {"message": "upstream unavailable"}}, status=503)
        state["chats"].append(body)
        text = f"Halo dari 9Router mock ({body.get('model')})"
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(r)
        for part in text.split(" "):
            ev = {"choices": [{"index": 0, "delta": {"content": part + " "}, "finish_reason": None}]}
            await resp.write(f"data: {json.dumps(ev)}\n\n".encode())
        ev = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 5, "completion_tokens": 5}}
        await resp.write(f"data: {json.dumps(ev)}\n\ndata: [DONE]\n\n".encode())
        await resp.write_eof()
        return resp

    app.router.add_get("/api/health", health)
    app.router.add_get("/api/version", version)
    app.router.add_get("/api/keys", keys_get)
    app.router.add_post("/api/keys", keys_post)
    app.router.add_get("/api/providers/suggested-models", suggested)
    app.router.add_get("/api/models/custom", custom_get)
    app.router.add_post("/api/models/custom", custom_post)
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/chat/completions", chat)
    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=20128)
    ap.add_argument("-H", "--host", default="127.0.0.1")
    ap.add_argument("--cli-token", default="")
    ap.add_argument("-t", "--tray", action="store_true")
    ap.add_argument("-n", "--no-browser", action="store_true")
    ap.add_argument("--skip-update", action="store_true")
    a = ap.parse_args(argv)
    web.run_app(build_app(a.cli_token), host=a.host, port=a.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
