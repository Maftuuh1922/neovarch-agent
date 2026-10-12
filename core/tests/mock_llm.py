"""A tiny OpenAI-compatible mock provider for tests and desktop smoke runs.

    python core/tests/mock_llm.py --port 18080

Behaviour (deterministic, no network):

* last wire message is a tool result -> streams ``Selesai. Hasil alat: <first line>``;
* user text contains ``tool`` / ``alat``   -> one ``shell`` tool call ``echo neovarch-tool-ok``;
* user text contains ``lambat`` / ``slow`` -> ``shell`` ``sleep 6 && echo neovarch-slow-tool-ok``
  (keeps the agent "working" long enough for the Office page to show it);
* user text contains ``vault``            -> one ``obsidian_search`` call for ``neovarch``;
* user text contains ``danger``           -> a ``shell`` call that needs approval
  (``rm -rf /tmp/neovarch-approval-probe``);
* anything else                           -> streams ``Halo dari mock Neovarch. Kamu bilang: <text>``
  word by word, with usage; an image part reads ``[gambar <mime>, <n> B]``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json

from aiohttp import web

REQUESTS = web.AppKey("requests", list)
DELAY = web.AppKey("delay", float)
AUTH = web.AppKey("auth", dict)


@web.middleware
async def _auth(request: web.Request, handler):
    need = request.app[AUTH]
    if need.get("api_key") and request.headers.get("Authorization") != f"Bearer {need['api_key']}":
        return web.json_response({"error": {"message": "invalid api key"}}, status=401)
    for k, v in (need.get("headers") or {}).items():
        if request.headers.get(k) != v:
            return web.json_response({"error": {"message": f"missing header {k}"}}, status=403)
    return await handler(request)


def _user_text(content) -> str:
    """Text of a user turn; image parts (vision input) show as ``[gambar <mime>, <n> B]``."""
    if not isinstance(content, list):
        return str(content or "")
    out = []
    for part in content:
        if part.get("type") == "text":
            out.append(str(part.get("text") or ""))
        elif part.get("type") == "image_url":
            url = str((part.get("image_url") or {}).get("url") or "")
            head, _, b64 = url.partition(",")
            out.append(f"[gambar {head[5:].split(';')[0] or '?'}, {len(base64.b64decode(b64 or b''))} B]")
    return " ".join(out)


TEMPEST_TAIL = "\n\n# Konteks saat ini"


def _strip_tail(text: str) -> str:
    head, sep, rest = text.partition(TEMPEST_TAIL)
    if not sep:
        return text
    # image parts are rendered after the text part: keep them
    imgs = [ln for ln in rest.split(" [gambar ")[1:]]
    return head + "".join(" [gambar " + i for i in imgs)


def _decide(messages: list[dict]) -> dict:
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":
        first = (last.get("content") or "").splitlines()
        tail = next((ln for ln in first[1:] if ln.strip()), first[0] if first else "")
        return {"text": f"Selesai. Hasil alat: {tail}"}
    text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = _user_text(m.get("content"))
            break
    # Tempest (the default harness) appends the per-message context ("# Konteks saat ini": clock,
    # skill hint, vault notes) to the user turn; the mock reacts to and echoes what the user typed.
    text = _strip_tail(text)
    low = text.lower()
    if "danger" in low:
        return {"tool": ("shell", {"command": "rm -rf /tmp/neovarch-approval-probe"})}
    if "lambat" in low or "slow" in low:
        return {"tool": ("shell", {"command": "sleep 6 && echo neovarch-slow-tool-ok"})}
    if "vault" in low:
        return {"tool": ("obsidian_search", {"query": "neovarch"})}
    if "tool" in low or "alat" in low:
        return {"tool": ("shell", {"command": "echo neovarch-tool-ok"})}
    return {"text": f"Halo dari mock Neovarch. Kamu bilang: {text}"}


def _chunk(delta: dict, finish: str | None = None) -> bytes:
    event = {"id": "mock", "object": "chat.completion.chunk", "model": "mock-model",
             "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(event)}\n\n".encode()


async def completions(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    request.app[REQUESTS].append(body)
    plan = _decide(body.get("messages") or [])
    delay = request.app[DELAY]
    if not body.get("stream"):
        if "tool" in plan:
            name, args = plan["tool"]
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
        else:
            msg = {"role": "assistant", "content": plan["text"]}
        return web.json_response({"choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
    await resp.prepare(request)
    await resp.write(_chunk({"role": "assistant"}))
    if "tool" in plan:
        name, args = plan["tool"]
        await resp.write(_chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                 "function": {"name": name, "arguments": ""}}]}))
        raw = json.dumps(args)
        for i in range(0, len(raw), 8):
            await resp.write(_chunk({"tool_calls": [{"index": 0, "function": {"arguments": raw[i:i + 8]}}]}))
        await resp.write(_chunk({}, "tool_calls"))
    else:
        words = plan["text"].split(" ")
        for i, w in enumerate(words):
            await resp.write(_chunk({"content": (" " if i else "") + w}))
            await asyncio.sleep(delay)
        await resp.write(_chunk({}, "stop"))
    usage = {"id": "mock", "object": "chat.completion.chunk", "choices": [],
             "usage": {"prompt_tokens": 42, "completion_tokens": 12, "total_tokens": 54}}
    await resp.write(f"data: {json.dumps(usage)}\n\n".encode())
    await resp.write(b"data: [DONE]\n\n")
    await resp.write_eof()
    return resp


async def models(_request: web.Request) -> web.Response:
    return web.json_response({"object": "list", "data": [{"id": "mock-model", "object": "model"}]})


def build_app(delay: float = 0.03, api_key: str | None = None, headers: dict | None = None,
              models_route: bool = True) -> web.Application:
    """api_key / headers: require them on every request (401/403 otherwise)."""
    app = web.Application(middlewares=[_auth])
    app[REQUESTS] = []
    app[DELAY] = delay
    app[AUTH] = {"api_key": api_key, "headers": headers or {}}
    app.router.add_post("/v1/chat/completions", completions)
    if models_route:
        app.router.add_get("/v1/models", models)
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--api-key", default=None, help="require this Bearer key")
    ap.add_argument("--header", action="append", default=[], help="require 'Name: value'")
    ap.add_argument("--cert", default=None, help="serve https with this cert (and --key)")
    ap.add_argument("--key", default=None)
    a = ap.parse_args()
    hdrs = dict((h.split(":", 1)[0].strip(), h.split(":", 1)[1].strip()) for h in a.header)
    ctx = None
    if a.cert:
        import ssl
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(a.cert, a.key)
    web.run_app(build_app(a.delay, a.api_key, hdrs), host=a.host, port=a.port, ssl_context=ctx,
                print=lambda *_: print(f"mock LLM on {'https' if ctx else 'http'}://{a.host}:{a.port}", flush=True))
