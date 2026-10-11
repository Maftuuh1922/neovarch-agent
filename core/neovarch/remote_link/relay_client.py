"""Outbound connection from this PC to a Neovarch relay (``relay/`` in the repo).

The PC holds one WebSocket to ``<relay>/v1/pc/<pc_id>?k=<room_key>``. Phones
join the same room; the relay wraps their frames as ``{"type":"msg","cid",…}``.
Each phone connection becomes a :class:`PeerLink`. The relay never sees
plaintext. Reconnects with backoff (1 s … 60 s, jittered).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
from typing import Callable

import aiohttp

from .peer import PeerLink
from .store import LinkStore

log = logging.getLogger("neovarch.remote_link")


def normalize_relay_url(url: str) -> str | None:
    """``https://x`` → ``wss://x``; strips trailing slashes. None when unusable."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return None
    if u.startswith("https://"):
        u = "wss://" + u[8:]
    elif u.startswith("http://"):
        u = "ws://" + u[7:]
    elif "://" not in u:
        u = "wss://" + u
    if not (u.startswith("wss://") or u.startswith("ws://")) or len(u) > 300:
        return None
    return u


class RelayClient:
    def __init__(self, *, store: LinkStore, url: str, make_peer: Callable[..., PeerLink],
                 on_change: Callable[[], None] | None = None, ping_interval: float = 30.0):
        self.store = store
        self.url = url
        self.make_peer = make_peer
        self.on_change = on_change
        self.ping_interval = ping_interval
        self.state = "off"  # off | connecting | online | offline
        self.error: str | None = None
        self.peers: dict[str, PeerLink] = {}
        self._task: asyncio.Task | None = None
        self._stop = False
        self._attempt = 0

    def _set(self, state: str, error: str | None = None) -> None:
        if (state, error) != (self.state, self.error):
            self.state, self.error = state, error
            if self.on_change:
                self.on_change()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = False
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._stop = True
        for p in list(self.peers.values()):
            p.close_local()
        self.peers.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._set("off")

    def drop_device(self, device_id: str) -> None:
        for p in list(self.peers.values()):
            if p.device and p.device.get("id") == device_id:
                p.fail("revoked")

    def backoff(self) -> float:
        base = min(60.0, 2 ** min(self._attempt, 6))
        return base * (0.8 + random.random() * 0.4)

    async def _run(self) -> None:
        while not self._stop:
            self._set("connecting", self.error)
            try:
                await self._session()
                self._attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set("offline", _short(exc))
            for p in list(self.peers.values()):
                p.close_local()
            self.peers.clear()
            if self._stop:
                break
            self._attempt += 1
            await asyncio.sleep(self.backoff())

    async def _session(self) -> None:
        target = f"{self.url}/v1/pc/{self.store.pc_id}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10)) as http:
            async with http.ws_connect(target, params={"k": self.store.room_key}, heartbeat=None,
                                       max_msg_size=1024 * 1024, autoping=True) as ws:
                self._attempt = 0
                self._set("online", None)
                out: asyncio.Queue[str] = asyncio.Queue()

                async def writer():
                    while True:
                        await ws.send_str(await out.get())

                async def pinger():
                    while True:
                        await asyncio.sleep(self.ping_interval)
                        out.put_nowait("ping")

                tasks = [asyncio.ensure_future(writer()), asyncio.ensure_future(pinger())]
                try:
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        if m.data == "pong":
                            continue
                        await self._on_frame(m.data, out)
                finally:
                    for t in tasks:
                        t.cancel()
                code = ws.close_code
                raise ConnectionError(f"relay closed ({code})" if code != 4000 else "replaced by another connection")

    async def _on_frame(self, text: str, out: asyncio.Queue) -> None:
        try:
            f = json.loads(text)
        except ValueError:
            return
        if not isinstance(f, dict):
            return
        cid = f.get("cid")
        if not isinstance(cid, str):
            return
        kind = f.get("type")
        if kind == "join":
            old = self.peers.pop(cid, None)
            if old:
                old.close_local()

            def send(frame: str, cid=cid):
                out.put_nowait(json.dumps({"type": "msg", "cid": cid, "data": frame}, separators=(",", ":")))

            def close(_reason: str, cid=cid):
                self.peers.pop(cid, None)
                out.put_nowait(json.dumps({"type": "close", "cid": cid}))
                if self.on_change:
                    self.on_change()

            self.peers[cid] = self.make_peer(send=send, close=close, via="relay")
        elif kind == "msg":
            p = self.peers.get(cid)
            if p is None:  # joined before we connected and the join was lost
                await self._on_frame(json.dumps({"type": "join", "cid": cid}), out)
                p = self.peers.get(cid)
            if p is not None and isinstance(f.get("data"), str):
                await p.feed(f["data"])
        elif kind == "leave":
            p = self.peers.pop(cid, None)
            if p:
                p.close_local()
                if self.on_change:
                    self.on_change()

    def phones(self) -> int:
        return sum(1 for p in self.peers.values() if p.ready)


def _short(exc: BaseException) -> str:
    """One Indonesian sentence for the PC's Remote settings (never a raw stack message)."""
    msg = str(exc) or exc.__class__.__name__
    low = msg.lower()
    chain = [exc, getattr(exc, "__cause__", None), getattr(exc, "os_error", None)]
    if any(isinstance(e, socket.gaierror) for e in chain if e is not None) or \
            "name or service not known" in low or "nodename nor servname" in low or "getaddrinfo" in low \
            or "no address associated" in low or "temporary failure in name resolution" in low:
        return ("Alamat relay tidak ditemukan (DNS). Relay ini belum aktif: sambungkan HP lewat Wi-Fi yang sama "
                "atau Tailscale, atau isi Relay URL milikmu sendiri di Pengaturan › Remote.")
    if "replaced by another connection" in low:
        return "PC lain memakai identitas relay yang sama; koneksi ini digantikan."
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in low or "timed out" in low:
        return "Relay tidak menjawab (waktu habis). Periksa koneksi internet PC."
    if "403" in low or "401" in low:
        return "Relay menolak PC ini (kunci ruang tidak cocok)."
    return msg[:160]
