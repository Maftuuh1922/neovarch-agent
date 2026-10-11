"""Remote dari mana saja: link crypto, device store, encrypted peer and the
PC's outbound relay connection (against the Node relay when node is present)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

pytest.importorskip("cryptography")

from neovarch.remote_link import DEFAULT_RELAY_URL  # noqa: E402
from neovarch.remote_link.crypto import (  # noqa: E402
    CHUNK, KeyPair, LinkError, b64d, b64e, derive, device_id, hello, pc_accept, pc_id_for_room_key,
    phone_finish, transcript)
from neovarch.remote_link.peer import PeerLink, make_phone_side  # noqa: E402
from neovarch.remote_link.relay_client import RelayClient, normalize_relay_url  # noqa: E402
from neovarch.remote_link.store import LinkStore  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
VECTORS = REPO / "test" / "fixtures" / "link_vectors.json"


# ------------------------------------------------------------------ crypto --

def test_vectors_match_fixture():
    v = json.loads(VECTORS.read_text())
    dev, pc = KeyPair.from_private(b64d(v["dev_sk"])), KeyPair.from_private(b64d(v["pc_sk"]))
    ep, es = KeyPair.from_private(b64d(v["eph_phone_sk"])), KeyPair.from_private(b64d(v["eph_pc_sk"]))
    assert b64e(dev.public) == v["dev_pk"] and b64e(pc.public) == v["pc_pk"]
    assert hello(dev, ep) == v["hello"]
    welcome, pcs = pc_accept(pc, v["hello"], eph=es)
    assert welcome == v["welcome"]
    th = transcript(dev.public, pc.public, ep.public, es.public)
    assert b64e(th) == v["transcript"]
    ku, kd = derive(dev.dh(pc.public) + ep.dh(es.public), th)
    assert (b64e(ku), b64e(kd)) == (v["k_up"], v["k_down"])
    assert device_id(dev.public) == v["device_id"]
    assert pc_id_for_room_key(v["room_key"]) == v["pc_id"] == "hkPbq-MaVpvc2ZsNQZYXL6"  # same as relay/test
    # PC decrypts what the phone sent, and its own first frame is deterministic
    for f in v["up_frames"]:
        out = pcs.decrypt(f)
    assert out == v["up_message"]
    assert pcs.encrypt(v["down_message"]) == v["down_frames"]
    # multi-part message
    out = None
    for f in v["big_up_frames_after_auth"]:
        out = pcs.decrypt(f)
    assert out == {"t": "ws", "d": "x" * (CHUNK + 10)}


def _pair():
    dev, pc, ep = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
    welcome, pcs = pc_accept(pc, hello(dev, ep))
    return pcs, phone_finish(dev, ep, pc.public, welcome), pc


def test_round_trip_and_fragments():
    pcs, ph, _ = _pair()
    msg = {"t": "http", "b": "é" * (CHUNK * 2)}
    frames = ph.encrypt(msg)
    assert len(frames) >= 4
    got = [pcs.decrypt(f) for f in frames]
    assert got[:-1] == [None] * (len(frames) - 1) and got[-1] == msg
    assert ph.decrypt(pcs.encrypt({"t": "pong"})[0]) == {"t": "pong"}


def test_replay_reorder_and_tamper_rejected():
    pcs, ph, _ = _pair()
    a, b = ph.encrypt({"n": 1})[0], ph.encrypt({"n": 2})[0]
    with pytest.raises(LinkError):
        pcs.decrypt(b)  # reordered
    pcs2, ph2, _ = _pair()
    f = ph2.encrypt({"n": 1})[0]
    assert pcs2.decrypt(f) == {"n": 1}
    with pytest.raises(LinkError):
        pcs2.decrypt(f)  # replayed
    pcs3, ph3, _ = _pair()
    g = json.loads(ph3.encrypt({"n": 1})[0])
    ct = bytearray(b64d(g["c"]))
    ct[0] ^= 1
    with pytest.raises(LinkError):
        pcs3.decrypt({"t": "d", "c": b64e(bytes(ct))})


def test_phone_rejects_wrong_pc_key():
    dev, pc, ep = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
    welcome, _ = pc_accept(pc, hello(dev, ep))
    with pytest.raises(LinkError):
        phone_finish(dev, ep, KeyPair.generate().public, welcome)


def test_relay_url_normalization_and_default():
    assert normalize_relay_url("https://r.example.com/") == "wss://r.example.com"
    assert normalize_relay_url("r.example.com") == "wss://r.example.com"
    assert normalize_relay_url("ws://10.0.0.2:8787") == "ws://10.0.0.2:8787"
    assert normalize_relay_url("ftp://x") is None
    ts = REPO / "desktop" / "apps" / "desktop" / "electron" / "relay-defaults.ts"
    if ts.exists():  # single default, mirrored in the desktop app
        assert f"'{DEFAULT_RELAY_URL}'" in ts.read_text()


# ------------------------------------------------------------------- store --

def test_store_devices_codes_and_permissions(tmp_path):
    clock = [1000.0]
    st = LinkStore(tmp_path / "link.json", clock=lambda: clock[0])
    assert len(st.pc_id) == 22 and len(b64d(st.pc_public)) == 32
    if os.name == "posix":
        assert (tmp_path / "link.json").stat().st_mode & 0o077 == 0
    st2 = LinkStore(tmp_path / "link.json")
    assert st2.pc_public == st.pc_public and st2.room_key == st.room_key  # stable identity
    pk = KeyPair.generate().public
    d = st.enroll(pk, "HP Andi", "lan")
    assert st.device_for_key(pk)["id"] == d["id"] == device_id(pk)
    code, exp = st.pair_code()
    assert st.check_pair_code(code) and not st.check_pair_code("nope")
    assert st.pair_code()[0] == code  # stable while fresh
    clock[0] += 11 * 60
    code2, _ = st.pair_code()
    assert code2 != code and st.check_pair_code(code)  # old one valid until expiry
    clock[0] += 30 * 60
    assert not st.check_pair_code(code)
    assert st.revoke(d["id"]) and st.device_for_key(pk) is None and st.is_revoked(pk)


# ----------------------------------------------------------- peer (bridge) --

@pytest.fixture
async def local_gateway():
    """A tiny stand-in for the gateway: /api/ws echo + /api/echo, internal token auth."""
    token = "internal-token"
    app = web.Application()

    def ok(req):
        return req.query.get("token") == token or req.headers.get("Authorization") == f"Bearer {token}"

    async def ws(req):
        if not ok(req):
            return web.Response(status=401)
        w = web.WebSocketResponse()
        await w.prepare(req)
        await w.send_str(json.dumps({"method": "event", "params": {"type": "gateway.ready"}}))
        async for m in w:
            if m.type == aiohttp.WSMsgType.TEXT:
                f = json.loads(m.data)
                await w.send_str(json.dumps({"id": f.get("id"), "result": {"echo": f.get("method")}}))
        return w

    async def echo(req):
        if not ok(req):
            return web.json_response({"detail": "Unauthorized"}, status=401)
        body = await req.read()
        return web.json_response({"method": req.method, "q": req.query.get("q"), "len": len(body),
                                  "auth_from_phone": req.headers.get("X-Evil")})

    app.router.add_get("/api/ws", ws)
    app.router.add_route("*", "/api/echo", echo)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", token
    await runner.cleanup()


class PhoneSim:
    """Phone side of a link, driven over an in-memory transport."""

    def __init__(self, dev: KeyPair, pc_pk: bytes):
        self.dev, self.pc_pk = dev, pc_pk
        self.hello, self._finish = make_phone_side(dev)
        self.session = None
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed: list[str] = []

    def recv_raw(self, text: str):
        if self.session is None:
            self.session = self._finish(json.loads(text), self.pc_pk)
            return
        m = self.session.decrypt(text)
        if m is not None:
            self.inbox.put_nowait(m)

    async def next(self, t=None, timeout=5):
        while True:
            m = await asyncio.wait_for(self.inbox.get(), timeout)
            if t is None or m.get("t") == t:
                return m


async def _link(store, base, token, phone):
    peer = PeerLink(store=store, local_base=base, local_token=token, send=phone.recv_raw,
                    close=phone.closed.append, via="test", pc_name="PC Uji")
    await peer.feed(json.dumps(phone.hello))
    return peer


async def _send(peer, phone, msg):
    for f in phone.session.encrypt(msg):
        await peer.feed(f)


async def test_peer_pairs_with_code_then_proxies_ws_and_http(tmp_path, local_gateway):
    base, token = local_gateway
    store = LinkStore(tmp_path / "l.json")
    dev = KeyPair.generate()
    phone = PhoneSim(dev, store.pc_keys.public)
    peer = await _link(store, base, token, phone)
    await _send(peer, phone, {"t": "auth"})
    assert (await phone.next())["reason"] == "unknown_device"
    assert phone.closed

    phone = PhoneSim(dev, store.pc_keys.public)
    peer = await _link(store, base, token, phone)
    code, _ = store.pair_code()
    await _send(peer, phone, {"t": "pair", "code": code, "name": "HP Uji"})
    ready = await phone.next("ready")
    assert ready["device"] == device_id(dev.public) and ready["name"] == "PC Uji"

    await _send(peer, phone, {"t": "ws.open"})
    await phone.next("ws.opened")
    first = await phone.next("ws")
    assert json.loads(first["d"])["params"]["type"] == "gateway.ready"
    await _send(peer, phone, {"t": "ws", "d": json.dumps({"jsonrpc": "2.0", "id": "m1", "method": "ping"})})
    assert json.loads((await phone.next("ws"))["d"]) == {"id": "m1", "result": {"echo": "ping"}}

    body = base64.b64encode(b"z" * 100_000).decode()
    await _send(peer, phone, {"t": "http", "id": 7, "m": "POST", "p": "/api/echo?q=1",
                              "h": {"Authorization": "Bearer stolen", "X-Evil": "1", "Content-Type": "text/plain"},
                              "b": body})
    res = await phone.next("http.res")
    assert res["id"] == 7 and res["s"] == 200
    j = json.loads(base64.b64decode(res["b"]))
    assert j == {"method": "POST", "q": "1", "len": 100_000, "auth_from_phone": None}
    peer.close_local()

    # known device now: plain auth works on a fresh connection
    phone2 = PhoneSim(dev, store.pc_keys.public)
    peer2 = await _link(store, base, token, phone2)
    await _send(peer2, phone2, {"t": "auth"})
    assert (await phone2.next("ready"))["device"] == device_id(dev.public)
    peer2.close_local()


async def test_peer_bad_code_and_revoked(tmp_path, local_gateway):
    base, token = local_gateway
    store = LinkStore(tmp_path / "l.json")
    dev = KeyPair.generate()
    phone = PhoneSim(dev, store.pc_keys.public)
    peer = await _link(store, base, token, phone)
    await _send(peer, phone, {"t": "pair", "code": "guess", "name": "x"})
    assert (await phone.next("denied"))["reason"] == "bad_code"
    d = store.enroll(dev.public, "HP", "lan")
    store.revoke(d["id"])
    phone = PhoneSim(dev, store.pc_keys.public)
    peer = await _link(store, base, token, phone)
    await _send(peer, phone, {"t": "auth"})
    assert (await phone.next("denied"))["reason"] == "revoked"


async def test_peer_closes_on_garbage(tmp_path, local_gateway):
    base, token = local_gateway
    store = LinkStore(tmp_path / "l.json")
    closed = []
    peer = PeerLink(store=store, local_base=base, local_token=token, send=lambda _f: None,
                    close=closed.append, via="test")
    await peer.feed("not json")
    assert closed and peer.closed


# --------------------------------------------- PC ↔ Node relay ↔ phone e2e --

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def node_relay():
    node = shutil.which("node")
    if not node or not (REPO / "relay" / "src" / "node-server.js").exists():
        pytest.skip("node not available")
    port = _free_port()
    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1"}
    proc = subprocess.Popen([node, str(REPO / "relay" / "src" / "node-server.js")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"ws://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(5)


async def test_pc_relay_client_end_to_end(tmp_path, local_gateway, node_relay):
    base, token = local_gateway
    store = LinkStore(tmp_path / "l.json")
    dev = KeyPair.generate()
    store.enroll(dev.public, "HP", "lan")

    def make_peer(*, send, close, via):
        return PeerLink(store=store, local_base=base, local_token=token, send=send, close=close, via=via)

    rc = RelayClient(store=store, url=node_relay, make_peer=make_peer)
    rc.start()
    for _ in range(100):
        if rc.state == "online":
            break
        await asyncio.sleep(0.05)
    assert rc.state == "online"

    hello_frame, finish = make_phone_side(dev)
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(f"{node_relay}/v1/phone/{store.pc_id}") as ws:
            assert json.loads((await ws.receive(5)).data) == {"relay": "pc_online"}
            await ws.send_str(json.dumps(hello_frame))
            sess = finish(json.loads((await ws.receive(5)).data), store.pc_keys.public)
            for f in sess.encrypt({"t": "auth"}):
                await ws.send_str(f)
            assert sess.decrypt((await ws.receive(5)).data)["t"] == "ready"
            assert rc.phones() == 1
            for f in sess.encrypt({"t": "http", "id": 1, "m": "GET", "p": "/api/echo?q=relay"}):
                await ws.send_str(f)
            res = None
            while res is None:
                res = sess.decrypt((await ws.receive(5)).data)
            assert res["s"] == 200 and json.loads(base64.b64decode(res["b"]))["q"] == "relay"
            # revoke kicks the live phone
            rc.drop_device(device_id(dev.public))
            msg = await ws.receive(5)
            assert msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING)
    await rc.stop()
    assert rc.state == "off"


# ------------------------------------------------------- gateway REST routes --

async def test_gateway_remote_link_routes(home, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from neovarch.server import Gateway, build_app
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setenv("NEOVARCH_RELAY_URL", "https://relay.example.test")
    gw = Gateway(False)
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    try:
        h = {"Authorization": "Bearer tok"}
        assert (await client.get("/api/remote/link")).status == 401
        info = await (await client.get("/api/remote/link", headers=h)).json()
        assert info["relay"]["url"] == "wss://relay.example.test" and info["relay"]["state"] == "off"
        assert len(info["pc_id"]) == 22 and info["pair_code"] and info["devices"] == []
        dev = KeyPair.generate()
        r = await client.post("/api/remote/devices", json={"pk": b64e(dev.public), "name": "HP Uji"}, headers=h)
        enr = await r.json()
        assert enr["device"] == device_id(dev.public) and enr["pc_pk"] == info["pc_pk"]
        assert enr["relay_url"] == "wss://relay.example.test"
        assert (await client.post("/api/remote/devices", json={"pk": "bad"}, headers=h)).status == 400
        r = await client.post("/api/remote/link/config", json={"relay_url": "ftp://x"}, headers=h)
        assert r.status == 400
        r = await client.post("/api/remote/link/config", json={"relay_enabled": False}, headers=h)
        assert (await r.json())["relay"]["enabled"] is False
        r = await client.delete(f"/api/remote/devices/{enr['device']}", headers=h)
        assert (await r.json())["found"] is True
        info = await (await client.get("/api/remote/link", headers=h)).json()
        assert info["devices"] == []
        # the internal bridge token is loopback-only and works like a session token
        r = await client.get("/api/remote/link", headers={"Authorization": f"Bearer {gw.auth.internal_token}"})
        assert r.status == 200
    finally:
        await client.close()
