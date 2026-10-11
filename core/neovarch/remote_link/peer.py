"""One phone connected over an encrypted link (relay or Bluetooth).

Transport-agnostic: a transport feeds received wire frames into
:meth:`PeerLink.feed` and gives a ``send(text)`` callable that queues one wire
frame (it must not reorder frames). After the handshake the phone's requests
are replayed against this PC's own gateway on loopback, so every route, auth
rule and event works exactly as on the LAN.

Inner messages (inside the encryption)::

    phone → PC  {"t":"auth"}                                   known device
                {"t":"pair","code":…,"name":…}                 new device (code from the QR)
    PC → phone  {"t":"ready","device":<id>,"name":<pc name>}   | {"t":"denied","reason":…}
    phone → PC  {"t":"ws.open"}                                → {"t":"ws.opened"} | {"t":"ws.closed"}
    both        {"t":"ws","d":<one JSON-RPC frame>}
    phone → PC  {"t":"http","id":n,"m":"GET","p":"/api/…?q","h":{…},"b":<b64 body>?}
    PC → phone  {"t":"http.res","id":n,"s":200,"h":{"content-type":…},"b":<b64>}
                (s = 0 and "e" = message when the local request failed)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Awaitable, Callable

import aiohttp

from .crypto import KeyPair, LinkError, Session, pc_accept
from .store import LinkStore

log = logging.getLogger("neovarch.remote_link")

MAX_HTTP_BODY = 16 * 1024 * 1024
# Headers a phone may pass through to the local gateway (auth is added here).
PASS_HEADERS = {"content-type", "accept", "accept-language", "if-none-match", "range", "x-neovarch-client"}
RESP_HEADERS = {"content-type", "content-disposition", "etag", "cache-control", "content-range", "x-neovarch-version"}


class PeerLink:
    def __init__(self, *, store: LinkStore, local_base: str, local_token: str, send: Callable[[str], None],
                 close: Callable[[str], None], via: str, pc_name: str = "PC",
                 on_change: Callable[[], None] | None = None,
                 http: aiohttp.ClientSession | None = None):
        self.store = store
        self.local_base = local_base.rstrip("/")
        self.local_token = local_token
        self._send_raw = send
        self._close = close
        self.via = via
        self.pc_name = pc_name
        self.on_change = on_change
        self._http = http
        self._own_http = http is None
        self.session: Session | None = None
        self.device: dict | None = None
        self.ready = False
        self.closed = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- helpers --
    def _out(self, msg: dict) -> None:
        if self.closed or not self.session:
            return
        for frame in self.session.encrypt(msg):
            self._send_raw(frame)

    def fail(self, reason: str) -> None:
        if self.closed:
            return
        log.info("link %s closed: %s", self.via, reason)
        self.close_local()
        self.closed = True
        self._close(reason)

    def close_local(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._ws_task:
            self._ws_task.cancel()
        if self._ws is not None and not self._ws.closed:
            asyncio.ensure_future(self._ws.close())
        if self._own_http and self._http is not None and not self._http.closed:
            asyncio.ensure_future(self._http.close())

    def _spawn(self, coro: Awaitable) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    @property
    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=5))
            self._own_http = True
        return self._http

    # ------------------------------------------------------------------- feed --
    async def feed(self, text: str) -> None:
        """One wire frame from the phone. Protocol errors close the link."""
        if self.closed:
            return
        try:
            if self.session is None:
                try:
                    frame = json.loads(text)
                except ValueError as exc:
                    raise LinkError("bad hello") from exc
                if not isinstance(frame, dict):
                    raise LinkError("bad hello")
                welcome, self.session = pc_accept(self.store.pc_keys, frame)
                self._send_raw(json.dumps(welcome, separators=(",", ":")))
                return
            msg = self.session.decrypt(text)
            if msg is None:
                return
            await self._handle(msg)
        except LinkError as exc:
            self.fail(str(exc))

    async def _handle(self, msg: dict) -> None:
        t = msg.get("t")
        if not self.ready:
            if t == "auth":
                dev = self.store.device_for_key(self.session.peer)
                if not dev:
                    reason = "revoked" if self.store.is_revoked(self.session.peer) else "unknown_device"
                    self._out({"t": "denied", "reason": reason})
                    self.fail(reason)
                    return
                self._accept(dev)
            elif t == "pair":
                if not self.store.check_pair_code(str(msg.get("code") or "")):
                    self._out({"t": "denied", "reason": "bad_code"})
                    self.fail("bad pairing code")
                    return
                dev = self.store.enroll(self.session.peer, str(msg.get("name") or "HP"), self.via)
                self._accept(dev)
            else:
                raise LinkError("expected auth")
            return
        if t == "ws.open":
            await self._open_ws()
        elif t == "ws":
            d = msg.get("d")
            if isinstance(d, str) and self._ws is not None and not self._ws.closed:
                await self._ws.send_str(d)
        elif t == "ws.close":
            if self._ws is not None:
                await self._ws.close()
        elif t == "http":
            self._spawn(self._http_request(msg))
        elif t == "ping":
            self._out({"t": "pong"})
        # unknown types are ignored (forward compatible)

    def _accept(self, dev: dict) -> None:
        self.device = dev
        self.ready = True
        self.store.touch(dev["id"], self.via)
        self._out({"t": "ready", "device": dev["id"], "name": self.pc_name})
        if self.on_change:
            self.on_change()

    # ---------------------------------------------------------------- local ws --
    async def _open_ws(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        url = self.local_base.replace("http", "ws", 1) + "/api/ws"
        try:
            self._ws = await self.http.ws_connect(url, params={"token": self.local_token}, heartbeat=None,
                                                  max_msg_size=64 * 1024 * 1024)
        except (aiohttp.ClientError, OSError) as exc:
            log.warning("link: local gateway ws failed: %s", exc)
            self._out({"t": "ws.closed", "reason": "local"})
            return
        self._out({"t": "ws.opened"})
        self._ws_task = asyncio.ensure_future(self._pump(self._ws))

    async def _pump(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            async for m in ws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    self._out({"t": "ws", "d": m.data})
                elif m.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("link: ws pump: %s", exc)
        if ws is self._ws and not self.closed:
            self._out({"t": "ws.closed", "reason": "local"})

    # -------------------------------------------------------------- local http --
    async def _http_request(self, msg: dict) -> None:
        rid = msg.get("id")
        method = str(msg.get("m") or "GET").upper()
        path = str(msg.get("p") or "/")
        if not path.startswith("/") or "://" in path or method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            self._out({"t": "http.res", "id": rid, "s": 0, "e": "bad request"})
            return
        headers = {k: str(v) for k, v in (msg.get("h") or {}).items() if isinstance(k, str) and k.lower() in PASS_HEADERS}
        headers["Authorization"] = f"Bearer {self.local_token}"
        body = None
        if msg.get("b"):
            try:
                body = base64.b64decode(msg["b"])
            except (ValueError, TypeError):
                self._out({"t": "http.res", "id": rid, "s": 0, "e": "bad body"})
                return
            if len(body) > MAX_HTTP_BODY:
                self._out({"t": "http.res", "id": rid, "s": 413, "h": {}, "b": ""})
                return
        try:
            async with self.http.request(method, self.local_base + path, headers=headers, data=body,
                                         timeout=aiohttp.ClientTimeout(total=300)) as res:
                data = await res.content.read(MAX_HTTP_BODY + 1)
                if len(data) > MAX_HTTP_BODY:
                    self._out({"t": "http.res", "id": rid, "s": 413, "h": {}, "b": "", "e": "response too large"})
                    return
                out_h = {k.lower(): v for k, v in res.headers.items() if k.lower() in RESP_HEADERS}
                self._out({"t": "http.res", "id": rid, "s": res.status, "h": out_h,
                           "b": base64.b64encode(data).decode("ascii")})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._out({"t": "http.res", "id": rid, "s": 0, "e": str(exc)[:200]})


def make_phone_side(dev: KeyPair):
    """Tiny phone-side helper for tests: returns (hello frame, finish(welcome) -> Session)."""
    from .crypto import hello, phone_finish
    eph = KeyPair.generate()

    def finish(welcome: dict, pinned: bytes) -> Session:
        return phone_finish(dev, eph, pinned, welcome)

    return hello(dev, eph), finish
