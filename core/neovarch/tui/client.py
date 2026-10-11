"""Clients for the gateway's JSON-RPC session API (the one the desktop and phone use).

* ``EmbeddedClient`` runs the gateway in this process (no port, no token) and
  calls its ``rpc`` dispatcher directly, so the terminal uses exactly the same
  session/model/reasoning/approval code paths as the apps.
* ``RemoteClient`` talks to a running ``neovarch serve`` over ``/api/ws``.

Both deliver server events as ``(type, session_id, payload)`` on ``events``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import itertools
import json
from typing import Any


class ClientError(Exception):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class BaseClient:
    kind = "base"

    def __init__(self) -> None:
        self.events: asyncio.Queue[tuple[str, str | None, dict]] = asyncio.Queue()
        self.connected = False
        self.label = ""

    async def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def call(self, method: str, params: dict | None = None) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        self.connected = False

    def _event(self, frame: dict) -> None:
        params = frame.get("params") or {}
        if frame.get("method") == "event":
            self.events.put_nowait((str(params.get("type") or ""), params.get("session_id"),
                                    params.get("payload") or {}))


class EmbeddedClient(BaseClient):
    """The gateway object in-process; events arrive through a local connection."""

    kind = "embedded"

    def __init__(self) -> None:
        super().__init__()
        self.gw = None
        self.conn = None
        self.label = "lokal"

    async def start(self) -> None:
        from neovarch import server

        client = self

        class _WS:
            closed = False

        class LocalConn(server.Conn):
            async def send(self, obj: dict) -> None:  # noqa: D401 - same contract as Conn.send
                client._event(obj)

        # Auth prints a fresh token when none is configured; keep it off the TUI.
        with contextlib.redirect_stdout(io.StringIO()):
            self.gw = server.Gateway(isolated=False)
        self.conn = LocalConn(_WS())  # type: ignore[arg-type]
        self.gw.conns.add(self.conn)
        self.connected = True

    async def call(self, method: str, params: dict | None = None) -> Any:
        from neovarch.server import RpcError
        if self.gw is None:
            raise ClientError("gateway belum berjalan")
        try:
            return await self.gw.rpc(self.conn, method, dict(params or {}))
        except RpcError as exc:
            raise ClientError(exc.message, exc.code) from None

    async def close(self) -> None:
        self.connected = False
        if self.gw is not None:
            for live in list(self.gw.live.values()):
                if live.task and not live.task.done():
                    live.agent.interrupt()
            with contextlib.suppress(Exception):
                await self.gw.router.close()


class RemoteClient(BaseClient):
    """``neovarch chat --connect http://127.0.0.1:9319 --token …``."""

    kind = "remote"

    def __init__(self, url: str, token: str) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self.token = token
        self.label = self.url.split("://", 1)[-1]
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._session = None
        self._ws = None
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        import aiohttp
        self._session = aiohttp.ClientSession()
        ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://") + "/api/ws"
        try:
            self._ws = await self._session.ws_connect(ws_url, headers={"Authorization": f"Bearer {self.token}"},
                                                      heartbeat=30, timeout=10)
        except Exception as exc:  # noqa: BLE001 - shown in the header
            await self._session.close()
            raise ClientError(f"tidak bisa terhubung ke {self.url}: {exc}") from None
        self.connected = True
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        import aiohttp
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    frame = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                fid = frame.get("id")
                if "method" not in frame and fid in self._pending:
                    fut = self._pending.pop(fid)
                    if not fut.done():
                        fut.set_result(frame)
                    continue
                self._event(frame)
        finally:
            self.connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ClientError("koneksi ke gateway terputus"))
            self.events.put_nowait(("connection.lost", None, {}))

    async def call(self, method: str, params: dict | None = None) -> Any:
        if not self.connected or self._ws is None:
            raise ClientError("tidak terhubung ke gateway")
        fid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[fid] = fut
        await self._ws.send_str(json.dumps({"jsonrpc": "2.0", "id": fid, "method": method, "params": params or {}}))
        frame = await asyncio.wait_for(fut, 120)
        if "error" in frame:
            err = frame["error"] or {}
            raise ClientError(str(err.get("message") or "error"), int(err.get("code") or 0))
        return frame.get("result")

    async def close(self) -> None:
        self.connected = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
        if self._reader is not None:
            self._reader.cancel()
