"""Glue between the gateway and the encrypted link transports.

Environment (set by the desktop app when it starts the remote gateway)::

    NEOVARCH_RELAY=1|0          relay on/off (default on)
    NEOVARCH_RELAY_URL=wss://…  relay to use (default: DEFAULT_RELAY_URL)
    NEOVARCH_BT=1|0             Bluetooth on/off (default off)
    NEOVARCH_REMOTE_NAME=…      PC name shown on the phone

REST (gateway token required)::

    GET    /api/remote/link            identity, pairing code, transports, devices
    POST   /api/remote/link/config     {relay_enabled?, relay_url?, bluetooth_enabled?}
    POST   /api/remote/devices         {pk, name} enroll this phone's device key (LAN pairing)
    DELETE /api/remote/devices/{id}    revoke a device
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any

from aiohttp import web

from . import DEFAULT_RELAY_URL
from .crypto import PROTOCOL, b64d
from .peer import PeerLink
from .relay_client import RelayClient, normalize_relay_url
from .store import LinkStore

log = logging.getLogger("neovarch.remote_link")


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() not in ("0", "false", "off", "no")


class LinkService:
    def __init__(self, gw: Any, store: LinkStore | None = None):
        self.gw = gw
        self.store = store or LinkStore()
        self.relay_enabled = _flag("NEOVARCH_RELAY", True)
        self.relay_url = normalize_relay_url(os.environ.get("NEOVARCH_RELAY_URL") or DEFAULT_RELAY_URL) or DEFAULT_RELAY_URL
        self.bluetooth_enabled = _flag("NEOVARCH_BT", False)
        self.pc_name = (os.environ.get("NEOVARCH_REMOTE_NAME") or socket.gethostname() or "PC Neovarch").strip()[:64]
        self.relay: RelayClient | None = None
        self.bluetooth = None  # BluetoothServer when enabled (see bluetooth.py)
        self.started = False

    # ------------------------------------------------------------------ peers --
    @property
    def local_base(self) -> str:
        return f"http://127.0.0.1:{self.gw.port}"

    def make_peer(self, *, send, close, via: str) -> PeerLink:
        return PeerLink(store=self.store, local_base=self.local_base, local_token=self.gw.auth.internal_token,
                        send=send, close=close, via=via, pc_name=self.pc_name, on_change=self._changed)

    def _changed(self) -> None:
        try:
            self.gw.broadcast_event("remote.link", None, self.public_status())
        except Exception:  # pragma: no cover - status push is best effort
            pass

    # -------------------------------------------------------------- lifecycle --
    async def start(self) -> None:
        self.started = True
        await self._apply()

    async def stop(self) -> None:
        self.started = False
        if self.relay:
            await self.relay.stop()
            self.relay = None
        if self.bluetooth:
            await self.bluetooth.stop()
            self.bluetooth = None

    async def _apply(self) -> None:
        if not self.started:
            return
        want_relay = self.relay_enabled and bool(self.relay_url)
        if self.relay and (not want_relay or self.relay.url != self.relay_url):
            await self.relay.stop()
            self.relay = None
        if want_relay and not self.relay:
            self.relay = RelayClient(store=self.store, url=self.relay_url, make_peer=self.make_peer,
                                     on_change=self._changed)
            self.relay.start()
        await self._apply_bluetooth()
        self._changed()

    async def _apply_bluetooth(self) -> None:
        if self.bluetooth and not self.bluetooth_enabled:
            await self.bluetooth.stop()
            self.bluetooth = None
        if self.bluetooth_enabled and not self.bluetooth:
            try:
                from .bluetooth import BluetoothServer
            except ImportError:  # module added with the Bluetooth transport
                return
            self.bluetooth = BluetoothServer(make_peer=self.make_peer, on_change=self._changed)
            await self.bluetooth.start()

    async def configure(self, *, relay_enabled: bool | None = None, relay_url: str | None = None,
                        bluetooth_enabled: bool | None = None) -> None:
        if relay_enabled is not None:
            self.relay_enabled = bool(relay_enabled)
        if relay_url is not None:
            n = normalize_relay_url(relay_url) if relay_url.strip() else DEFAULT_RELAY_URL
            if not n:
                raise ValueError("Relay URL harus diawali wss:// atau https://")
            self.relay_url = n
        if bluetooth_enabled is not None:
            self.bluetooth_enabled = bool(bluetooth_enabled)
        await self._apply()

    def revoke(self, device_id: str) -> bool:
        found = self.store.revoke(device_id)
        if self.relay:
            self.relay.drop_device(device_id)
        if self.bluetooth:
            self.bluetooth.drop_device(device_id)
        self._changed()
        return found

    # ----------------------------------------------------------------- status --
    def transports(self) -> dict:
        relay = {"enabled": self.relay_enabled, "url": self.relay_url, "default_url": DEFAULT_RELAY_URL,
                 "state": self.relay.state if self.relay else "off",
                 "error": self.relay.error if self.relay else None,
                 "phones": self.relay.phones() if self.relay else 0}
        bt: dict = {"enabled": self.bluetooth_enabled, "state": "off", "error": None, "address": None,
                    "channel": None, "phones": 0}
        if self.bluetooth:
            bt.update(self.bluetooth.status())
        return {"relay": relay, "bluetooth": bt}

    def public_status(self) -> dict:
        return {"protocol": PROTOCOL, "pc_id": self.store.pc_id, "pc_pk": self.store.pc_public,
                "name": self.pc_name, **self.transports(), "devices": self.store.devices()}

    def link_info(self) -> dict:
        code, exp = self.store.pair_code()
        return {**self.public_status(), "pair_code": code, "pair_expires": int(exp)}

    def enroll_info(self, device: dict) -> dict:
        t = self.transports()
        return {"device": device["id"], "pc_id": self.store.pc_id, "pc_pk": self.store.pc_public,
                "name": self.pc_name, "protocol": PROTOCOL,
                "relay_url": self.relay_url if self.relay_enabled else None,
                "bluetooth": {"address": t["bluetooth"].get("address"), "channel": t["bluetooth"].get("channel"),
                              "uuid": t["bluetooth"].get("uuid")} if self.bluetooth_enabled else None}


def add_routes(app: web.Application, gw: Any) -> None:
    """Register /api/remote/* on the gateway app (auth handled by the gateway middleware)."""
    r = app.router

    def svc() -> LinkService:
        s = getattr(gw, "link", None)
        if s is None:
            s = gw.link = LinkService(gw)
        return s

    async def link_get(_request):
        return web.json_response(await asyncio.to_thread(svc().link_info))

    async def link_config(request):
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"detail": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"detail": "invalid JSON"}, status=400)
        try:
            await svc().configure(
                relay_enabled=body.get("relay_enabled") if isinstance(body.get("relay_enabled"), bool) else None,
                relay_url=body.get("relay_url") if isinstance(body.get("relay_url"), str) else None,
                bluetooth_enabled=body.get("bluetooth_enabled") if isinstance(body.get("bluetooth_enabled"), bool) else None)
        except ValueError as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        return web.json_response(svc().link_info())

    async def device_enroll(request):
        try:
            body = await request.json()
            pk = b64d(str(body.get("pk") or ""))
        except Exception:
            return web.json_response({"detail": "invalid device key"}, status=400)
        if len(pk) != 32:
            return web.json_response({"detail": "invalid device key"}, status=400)
        dev = svc().store.enroll(pk, str(body.get("name") or "HP"), "lan")
        svc()._changed()
        return web.json_response(svc().enroll_info(dev))

    async def device_revoke(request):
        found = svc().revoke(request.match_info["device_id"])
        return web.json_response({"ok": True, "found": found})

    r.add_get("/api/remote/link", link_get)
    r.add_post("/api/remote/link/config", link_config)
    r.add_post("/api/remote/devices", device_enroll)
    r.add_delete("/api/remote/devices/{device_id}", device_revoke)
