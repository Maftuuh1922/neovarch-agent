"""9Router as the built-in default provider: detection, provisioning, model list,
global default and per-agent models — all against a mocked 9Router (no network)."""
import asyncio
import hashlib
import os
import socket
import stat
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import mock_9router
from neovarch import config as cfgmod
from neovarch import models as modelsmod
from neovarch import router9
from neovarch.server import Gateway, build_app

from test_server import WS

MACHINE_ID = "test-machine-1234"
CLI_SECRET = "s3cr3t" * 4


def _token() -> str:
    return hashlib.sha256((MACHINE_ID + "9r-cli-auth" + CLI_SECRET).encode()).hexdigest()[:16]


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "9r-data"
    (d / "auth").mkdir(parents=True)
    (d / "machine-id").write_text(MACHINE_ID)
    (d / "auth" / "cli-secret").write_text(CLI_SECRET)
    return d


@pytest.fixture
async def router(home, tmp_path, monkeypatch):
    """A running mock 9Router whose local CLI token Neovarch can derive."""
    app = mock_9router.build_app(_token())
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", str(server.make_url("/v1")))
    monkeypatch.setenv("NEOVARCH_9ROUTER_DATA_DIR", str(_data_dir(tmp_path)))
    yield app[mock_9router.STATE]
    await server.close()


async def _client(monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    return gw, c


def H():
    return {"Authorization": "Bearer tok"}


async def _ws(c):
    ws = WS(await c.ws_connect("/api/ws?token=tok"))
    await ws.pump()
    return ws


async def _chat(ws, sid, text="halo"):
    ws.events.clear()
    await ws.call("prompt.submit", {"session_id": sid, "text": text})
    return (await ws.until("message.complete", timeout=20))["payload"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ units ---

def test_urls_and_token(tmp_path, monkeypatch):
    monkeypatch.delenv("NEOVARCH_9ROUTER_URL", raising=False)
    cfg = {"router9": {}}
    assert router9.base_url(cfg) == "http://localhost:20128/v1"
    assert router9.dashboard_url(router9.base_url(cfg)) == "http://localhost:20128/dashboard"
    assert router9.base_url({"router9": {"base_url": "127.0.0.1:3000"}}) == "http://127.0.0.1:3000/v1"
    assert router9.base_url({"router9": {"base_url": "http://box:20128/v1/"}}) == "http://box:20128/v1"
    assert router9.is_local("http://localhost:20128/v1") and not router9.is_local("https://r.example.com/v1")
    assert router9.port_of("http://localhost:20128/v1") == 20128
    assert router9.cli_token(tmp_path / "missing") is None
    assert router9.cli_token(_data_dir(tmp_path)) == _token()


def test_choose_default_prefers_mimo_then_fallbacks():
    assert router9.choose_default([]) == "oc/mimo-v2.6-flash-free"
    assert router9.choose_default(["exo-free", "mimo-v2.6-flash-free"]) == "oc/mimo-v2.6-flash-free"
    assert router9.choose_default(["exo-free", "ling-3.1-flash-free"]) == "oc/ling-3.1-flash-free"
    assert router9.choose_default(["exo-free"]) == "oc/exo-free"


def test_mimo_pro_is_default_when_9router_lists_it(home, monkeypatch):
    assert router9.DEFAULT_MODEL == "oc/mimo-v2.6-flash-free"
    assert router9.choose_default(["mimo-v2.6-flash-free"], ["mimo/mimo-v2.6-pro", "oc/mimo-v2.6-flash-free"]) \
        == "mimo/mimo-v2.6-pro"
    assert router9.choose_default(["mimo-v2.6-flash-free"], ["kr/glm-5"]) == "oc/mimo-v2.6-flash-free"
    assert router9.default_model_id({}, []) == "oc/mimo-v2.6-flash-free"
    assert router9.default_model_id({}, ["mimo/mimo-v2.6-pro"]) == "mimo/mimo-v2.6-pro"
    assert router9.is_free_model("oc/big-pickle") and not router9.is_free_model("mimo/mimo-v2.6-pro")
    assert router9.ALIAS_GROUPS["mimo"] == "MiMo"
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", "http://localhost:20128/v1")
    monkeypatch.setattr(router9, "LAST_MODEL_IDS", ["oc/mimo-v2.6-flash-free", "mimo/mimo-v2.6-pro"])
    cfg = cfgmod.load_config()
    assert modelsmod.default_ref(cfg) == {"model": "mimo/mimo-v2.6-pro", "provider": "9router", "source": "builtin"}
    assert cfgmod.resolve_endpoint(cfg)["model"] == "mimo/mimo-v2.6-pro"


def test_new_kantor_employee_follows_pc_default(home, monkeypatch):
    from neovarch import session_settings
    from neovarch.company import CompanyStore
    from neovarch.company_runtime import CompanyRuntime
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", "http://localhost:20128/v1")
    s = CompanyStore()
    try:
        s.setup("Neovarch Studio", "uji")
        a = s.save_agent({"name": "Sari", "title": "Engineer", "skip_approval": True})
        assert a["model"] == "" and a["provider"] == ""
        rec = {"model_override": {"model": "kr/glm-5", "provider": "9router"}}
        CompanyRuntime._apply_model(rec, a)
        assert "model_override" not in rec
        cfg = cfgmod.load_config()
        assert session_settings.effective_endpoint(cfg, rec)["model"] == "oc/mimo-v2.6-flash-free"
        modelsmod.set_default(cfg, "kr/glm-5", "9router")
        assert session_settings.effective_endpoint(cfg, rec)["model"] == "kr/glm-5"
    finally:
        s.close()


def test_fresh_install_defaults_to_9router(home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", "http://localhost:20128/v1")
    cfg = cfgmod.load_config()
    ep = cfgmod.resolve_endpoint(cfg)
    assert ep["provider"] == "9router" and ep["model"] == "oc/mimo-v2.6-flash-free"
    assert ep["base_url"] == "http://localhost:20128/v1"
    assert modelsmod.default_ref(cfg) == {"model": "oc/mimo-v2.6-flash-free", "provider": "9router", "source": "builtin"}
    # an explicitly configured provider still wins
    cfg["model"] = {"provider": "groq", "default": ""}
    assert cfgmod.resolve_endpoint(cfg)["provider"] == "groq"
    assert modelsmod.default_ref(cfg)["source"] == "config"


def test_per_agent_override_routing(home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", "http://localhost:20128/v1")
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    cfg = cfgmod.load_config()
    a = modelsmod.set_agent_model(cfg, "abc", "kr/glm-5", None, {"kr/glm-5"})
    assert a == {"agent_id": "session:abc", "model": "kr/glm-5", "provider": "9router",
                 "override": {"model": "kr/glm-5", "provider": "9router"}, "source": "agent"}
    assert modelsmod.endpoint_for(cfg, "session:abc")["model"] == "kr/glm-5"
    assert modelsmod.endpoint_for(cfg, "session:other")["model"] == "oc/mimo-v2.6-flash-free"
    # an override on another provider goes to that provider's URL and key
    modelsmod.set_agent_model(cfg, "kanban:Ayu", "llama-3.1-8b-instant", "groq")
    ep = modelsmod.endpoint_for(cfg, "kanban:Ayu")
    assert ep["base_url"].startswith("https://api.groq.com") and ep["api_key"] == "gk"
    # clearing falls back to the global default
    b = modelsmod.set_agent_model(cfg, "session:abc", None)
    assert b["source"] == "global" and b["override"] is None and b["model"] == "oc/mimo-v2.6-flash-free"
    with pytest.raises(modelsmod.ModelError):
        modelsmod.normalize_agent_id("  ")


# ------------------------------------------------------------ integration ---

async def test_status_provisions_key_and_registers_free_models(router, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        st = await (await c.get("/api/router/status", headers=H())).json()
        assert st["state"] == "running" and st["running"] and st["version"] == "0.5.99"
        assert st["has_api_key"] and st["setup"] == {**st["setup"], "ready": True, "action": None}
        assert len(router["keys"]) == 1 and router["keys"][0]["name"] == "neovarch"
        assert cfgmod.read_env_file()[router9.KEY_ENV] == router["keys"][0]["key"]
        assert {("oc", i) for i in mock_9router.FREE_IDS} <= {(m["providerAlias"], m["id"]) for m in router["custom"]}
        # a second check reuses the key, never creates another
        await gw.router.provision()
        cfgmod.write_env_value(router9.KEY_ENV, "")
        await gw.router.provision()
        assert len(router["keys"]) == 1

        data = await (await c.get("/api/models?refresh=1", headers=H())).json()
        ids = [m["id"] for m in data["models"]]
        assert ids[0] == "oc/mimo-v2.6-flash-free" and data["models"][0]["recommended"] and data["models"][0]["free"]
        assert data["models"][0]["group"] == "OpenCode Free" and data["models"][0]["provider"] == "9router"
        assert "kr/glm-5" in ids and next(m for m in data["models"] if m["id"] == "kr/glm-5")["group"] == "Kiro"
        assert data["default"] == {"model": "oc/mimo-v2.6-flash-free", "provider": "9router"}
        assert data["router"]["running"] and data["error"] is None
        assert {"id": "oc/mimo-v2.6-flash-free", "object": "model", "owned_by": "9router"} in data["data"]

        opts = await (await c.get("/api/model/options", headers=H())).json()
        assert opts["providers"][0]["slug"] == "9router" and "kr/glm-5" in opts["providers"][0]["models"]
    finally:
        await c.close()


async def test_chat_uses_default_then_agent_override_live_events(router, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        out = await _chat(ws, sid)
        assert "(oc/mimo-v2.6-flash-free)" in out["text"] and "error" not in out
        assert router["chats"][-1]["model"] == "oc/mimo-v2.6-flash-free"

        aid = f"session:{sid}"
        ws.events.clear()
        r = await c.put(f"/api/agents/{aid}/model", json={"model": "kr/glm-5"}, headers=H())
        body = await r.json()
        assert r.status == 200 and body["ok"] and body["source"] == "agent" and body["provider"] == "9router"
        ev = await ws.until("agent.model.changed")
        assert ev["session_id"] is None and ev["payload"]["model"] == "kr/glm-5"
        office = (await ws.until("office.update"))["payload"]
        # chats are not Kantor desks any more (the Kantor starts empty)
        assert not any(d["id"] == aid for d in office["agents"])
        assert office["default_model"] == {"model": "oc/mimo-v2.6-flash-free", "provider": "9router"}

        out = await _chat(ws, sid, "lagi")
        assert "(kr/glm-5)" in out["text"]
        # another agent still follows the global default
        sid2 = (await ws.call("session.create", {}))["result"]["session_id"]
        assert "(oc/mimo-v2.6-flash-free)" in (await _chat(ws, sid2))["text"]
        assert (await ws.call("session.status", {"session_id": sid}))["result"]["model"] == "kr/glm-5"

        listing = await (await c.get("/api/agents/models", headers=H())).json()
        assert listing["agents"][aid]["model"] == "kr/glm-5" and aid in listing["agents"] and len(listing["agents"]) == 1

        # global default via RPC (the phone's path); the override keeps winning for its agent
        ws.events.clear()
        res = (await ws.call("models.default.set", {"model": "kr/claude-sonnet-4.5"}))["result"]
        assert res == {"model": "kr/claude-sonnet-4.5", "provider": "9router", "ok": True}
        assert (await ws.until("model.default.changed"))["payload"]["model"] == "kr/claude-sonnet-4.5"
        assert "(kr/claude-sonnet-4.5)" in (await _chat(ws, sid2))["text"]
        assert "(kr/glm-5)" in (await _chat(ws, sid))["text"]

        # clearing the override (DELETE) -> back to the global default
        r = await c.delete(f"/api/agents/{aid}/model", headers=H())
        assert (await r.json())["source"] == "global"
        assert "(kr/claude-sonnet-4.5)" in (await _chat(ws, sid))["text"]
        got = (await ws.call("agent.model.get", {"agent_id": sid}))["result"]
        assert got["agent_id"] == aid and got["source"] == "global"
        bad = await ws.call("agent.model.set", {"agent_id": "", "model": "x"})
        assert bad["error"]["code"] == -32602
        assert (await c.put(f"/api/agents/{aid}/model", json={}, headers=H())).status == 400
        assert (await c.put("/api/models/default", json={"model": ""}, headers=H())).status == 400
        d = await (await c.get("/api/models/default", headers=H())).json()
        assert d == {"model": "kr/claude-sonnet-4.5", "provider": "9router", "source": "config"}
    finally:
        await c.close()


async def test_not_installed_and_unreachable_chat(home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", f"http://127.0.0.1:{_free_port()}/v1")
    gw, c = await _client(monkeypatch)
    try:
        st = await (await c.get("/api/router/status", headers=H())).json()
        assert st["state"] == "not_installed" and not st["installed"] and not st["running"]
        assert st["setup"]["action"] == "install" and st["setup"]["install_command"] == "npm install -g 9router"
        r = await c.post("/api/router/start", headers=H())
        assert r.status == 409 and "9Router belum terpasang" in (await r.json())["error"]
        assert (await c.post("/api/router/stop", headers=H())).status == 409
        data = await (await c.get("/api/models", headers=H())).json()
        assert data["models"][0]["id"] == "oc/mimo-v2.6-flash-free" and data["error"]
        ws = await _ws(c)
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        out = await _chat(ws, sid)
        assert "9Router belum berjalan" in out["error"]
    finally:
        await c.close()


async def test_running_without_token_asks_for_key_then_accepts_pasted_key(home, tmp_path, monkeypatch):
    app = mock_9router.build_app("")  # CLI token unknown to us
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", str(server.make_url("/v1")))
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        st = await (await c.get("/api/router/status", headers=H())).json()
        assert st["running"] and not st["setup"]["ready"] and st["setup"]["action"] == "api_key"
        assert st["setup"]["action_url"].endswith("/dashboard") and "Buka dashboard 9Router" in st["setup"]["message"]
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        out = await _chat(ws, sid)
        assert "9Router meminta API key" in out["error"]
        app[mock_9router.STATE]["keys"].append({"name": "manual", "key": "sk-manual", "isActive": True})
        ws.events.clear()
        st = await (await c.put("/api/router/config", json={"api_key": "sk-manual"}, headers=H())).json()
        assert st["has_api_key"] and st["setup"]["ready"]
        assert (await ws.until("router.status"))["payload"]["setup"]["ready"]
        assert "(oc/mimo-v2.6-flash-free)" in (await _chat(ws, sid))["text"]
    finally:
        await c.close()
        await server.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shim")
async def test_start_and_stop_a_local_9router(home, tmp_path, monkeypatch):
    port = _free_port()
    shim = tmp_path / "bin" / "9router"
    shim.parent.mkdir()
    mock = Path(mock_9router.__file__).resolve()
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{mock}" --cli-token {_token()} "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NEOVARCH_9ROUTER_BIN", str(shim))
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("NEOVARCH_9ROUTER_DATA_DIR", str(_data_dir(tmp_path)))
    gw, c = await _client(monkeypatch)
    try:
        st = await (await c.get("/api/router/status", headers=H())).json()
        assert st["state"] == "stopped" and st["installed"] and st["setup"]["action"] == "start"
        st = await (await c.post("/api/router/start", headers=H())).json()
        assert st["state"] == "running" and st["managed"] and st["pid"] and st["has_api_key"], st
        st = await (await c.post("/api/router/stop", headers=H())).json()
        assert st["state"] == "stopped" and not st["managed"]
        # supervisor: autostart at boot, restart after a crash
        monkeypatch.setenv("NEOVARCH_9ROUTER_AUTOSTART", "1")
        gw.router.user_stopped = False
        st = await gw.router.tick(first=True)
        assert st["running"] and st["managed"]
        gw.router.proc.kill()
        gw.router.proc.wait()
        await asyncio.sleep(0.2)
        st = await gw.router.tick()
        assert st["running"] and st["managed"], st
        await gw.router.stop()
    finally:
        if gw.router.proc and gw.router.proc.poll() is None:
            gw.router.proc.kill()
        await c.close()


def test_cli_router_status_and_setup_9router(tmp_path):
    import subprocess
    core = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEOVARCH_")}
    env.update(HOME=str(tmp_path), NEOVARCH_HOME=str(tmp_path / ".nv"), PYTHONPATH=str(core),
               NEOVARCH_9ROUTER_URL=f"http://127.0.0.1:{_free_port()}/v1",
               NEOVARCH_9ROUTER_BIN=str(tmp_path / "none"))
    run = lambda *a: subprocess.run([sys.executable, "-m", "neovarch", *a], env=env, capture_output=True,
                                    text=True, timeout=60)
    r = run("router", "status")
    assert r.returncode == 0 and "9Router: not_installed" in r.stdout and "npm install -g 9router" in r.stdout
    assert "Model default: oc/mimo-v2.6-flash-free via 9router" in r.stdout
    r = run("router", "setup", "--wait", "1")
    assert r.returncode == 1
    r = run("setup", "--provider", "9router", "--non-interactive")
    assert r.returncode == 0, r.stderr
    import yaml
    cfg = yaml.safe_load((tmp_path / ".nv" / "config.yaml").read_text())
    assert cfg["model"]["provider"] == "9router" and cfg["model"]["default"] == "oc/mimo-v2.6-flash-free"


async def test_composer_picker_paths(router, monkeypatch):
    """The desktop composer: model.options lists 9Router first; a pick in a live chat
    (config.set model "<m> --provider <p> --session") is that agent's own model;
    session.create with a model starts the chat on it; --global changes the default."""
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        opts = (await ws.call("model.options", {"refresh": True}))["result"]
        r9 = opts["providers"][0]
        assert r9["slug"] == "9router" and r9["is_current"] and "oc/mimo-v2.6-flash-free" in r9["models"]
        assert "oc/mimo-v2.6-flash-free" in r9["free_models"] and "kr/glm-5" not in r9["free_models"]
        assert r9["status"]["running"] and opts["model"] == "oc/mimo-v2.6-flash-free"

        sid = (await ws.call("session.create", {"model": "kr/glm-5", "provider": "9router"}))["result"]["session_id"]
        assert "(kr/glm-5)" in (await _chat(ws, sid))["text"]
        ws.events.clear()
        res = (await ws.call("config.set", {"session_id": sid, "key": "model",
                                            "value": "kr/claude-sonnet-4.5 --provider 9router --session"}))["result"]
        assert res["scope"] == "session" and res["model"] == "kr/claude-sonnet-4.5"
        info = await ws.until("session.info")
        assert info["session_id"] == sid and info["payload"]["model"] == "kr/claude-sonnet-4.5"
        assert info["payload"]["provider"] == "9router"
        assert "(kr/claude-sonnet-4.5)" in (await _chat(ws, sid))["text"]
        o2 = (await ws.call("model.options", {"session_id": sid}))["result"]
        assert o2["model"] == "kr/claude-sonnet-4.5"
        # the global default is untouched by a session pick
        assert (await ws.call("models.default.get", {}))["result"]["model"] == "oc/mimo-v2.6-flash-free"
        cfg = cfgmod.load_config()
        assert cfg["model"].get("default", "") in ("", None) or cfg["model"]["default"] == "oc/mimo-v2.6-flash-free"
        res = (await ws.call("config.set", {"key": "model", "value": "kr/glm-5 --provider 9router --global"}))["result"]
        assert res["scope"] == "global"
        assert (await ws.call("models.default.get", {}))["result"] == {"model": "kr/glm-5", "provider": "9router",
                                                                         "source": "config"}
        # other config keys still work as before
        assert (await ws.call("config.set", {"key": "agent.max_turns", "value": 7}))["result"]["ok"]
        assert cfgmod.load_config()["agent"]["max_turns"] == 7
    finally:
        await c.close()


async def test_router_rpcs_for_the_phone_and_picker_order(router, monkeypatch):
    """router.stop / router.config / router.provision over JSON-RPC, and the composer
    picker lists the default first, then the OpenCode Free models, then the rest."""
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        st = (await ws.call("router.provision", {}))["result"]
        assert st["running"] and st["has_api_key"] and st["setup"]["ready"]
        err = (await ws.call("router.stop", {}))["error"]
        assert err["code"] == -32010 and "tidak dijalankan oleh Neovarch" in err["message"]
        assert (await ws.call("router.config", {"base_url": "not a url ::"})).get("error", {}).get("code") == -32602
        st = (await ws.call("router.config", {"autostart": False}))["result"]
        assert st["autostart"] is False and cfgmod.load_config()["router9"]["autostart"] is False
        st = (await ws.call("router.config", {"api_key": ""}))["result"]
        assert "running" in st
        opts = (await ws.call("model.options", {"refresh": True}))["result"]
        models = opts["providers"][0]["models"]
        assert models[0] == "oc/mimo-v2.6-flash-free"
        free = [m.startswith("oc/") for m in models]
        assert free == sorted(free, reverse=True), models
    finally:
        await c.close()


async def test_fresh_9router_token_files_are_primed(home, tmp_path, monkeypatch):
    """A fresh 9Router has no machine-id / cli-secret until it first checks a CLI token:
    the core primes them with one request, derives the token and gets its key."""
    d = tmp_path / "fresh-9r"
    app = mock_9router.build_app(_token(), lazy_files=(d, MACHINE_ID, CLI_SECRET))
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setenv("NEOVARCH_9ROUTER_URL", str(server.make_url("/v1")))
    monkeypatch.setenv("NEOVARCH_9ROUTER_DATA_DIR", str(d))
    gw, c = await _client(monkeypatch)
    try:
        assert not (d / "machine-id").exists()
        st = await (await c.get("/api/router/status", headers=H())).json()
        assert st["has_api_key"] and st["setup"]["ready"], st
        assert (d / "machine-id").exists() and app[mock_9router.STATE]["keys"][0]["name"] == "neovarch"
    finally:
        await c.close()
        await server.close()


def test_rate_limit_is_explained_in_indonesian():
    from neovarch.agent import _explain
    err = 'provider returned HTTP 429: {"error":{"message":"FreeUsageLimitError Rate limit exceeded"}}'
    out = _explain(err, {"provider": "9router", "model": "oc/mimo-v2.6-flash-free"})
    assert "OpenCode Free" in out and "oc/mimo-v2.6-flash-free" in out and "pilih model lain" in out
    assert "HTTP 429" in _explain("provider returned HTTP 429: slow down", {"provider": "9router", "model": "kr/glm-5"})
    assert _explain(err, {"provider": "openai", "model": "gpt"}) == err


# ------------------------------------------------- free-model fallback (429) ---

@pytest.fixture(autouse=True)
def _no_cooldowns():
    router9.clear_limited()
    yield
    router9.clear_limited()


def test_free_fallback_order_cooldown_and_retryable_errors():
    live = ["oc/zeta-free", "oc/mimo-v2.6-flash-free", "kr/glm-5", "oc/alpha-free", "oc/gpt-paid", "ocg/x-free"]
    order = router9.free_order(live)
    assert order[:4] == ["oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free", "oc/ling-3.1-flash-free",
                         "oc/big-pickle"]
    assert order[4:] == ["oc/alpha-free", "oc/zeta-free"]          # other oc/*-free, sorted
    assert router9.is_free_model("oc/mimo-v2.6-flash-free") and not router9.is_free_model("kr/glm-5")
    assert not router9.is_free_model("oc/gpt-paid") and not router9.is_free_model("ocg/x-free")
    cands = router9.fallback_candidates("oc/mimo-v2.6-flash-free", live)
    assert cands[0] == "oc/nemotron-3-ultra-free" and "oc/mimo-v2.6-flash-free" not in cands
    router9.mark_limited("oc/nemotron-3-ultra-free")
    assert router9.cooldown_left("oc/nemotron-3-ultra-free") > 590
    cands = router9.fallback_candidates("oc/mimo-v2.6-flash-free", live)
    assert cands[0] == "oc/ling-3.1-flash-free" and cands[-1] == "oc/nemotron-3-ultra-free"  # resting last
    router9.mark_limited("oc/ling-3.1-flash-free", seconds=-1)          # expired
    assert router9.cooldown_left("oc/ling-3.1-flash-free") == 0
    r = router9.retryable_status
    assert r('provider returned HTTP 429: {"error":"FreeUsageLimitError"}') == 429
    assert r("provider returned HTTP 503: down") == 503 and r("provider returned HTTP 401: key") is None
    assert r("FreeUsageLimitError: Rate limit exceeded") == 429 and r("could not reach the model provider") is None
    assert router9.fallback_notice("oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free") == \
        "Model oc/mimo-v2.6-flash-free sedang dibatasi, pakai oc/nemotron-3-ultra-free sementara."


async def test_rate_limited_default_falls_back_with_notice_and_cooldown(router, monkeypatch):
    router["limited"].add("oc/mimo-v2.6-flash-free")
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        out = await _chat(ws, sid)
        assert "(oc/nemotron-3-ultra-free)" in out["text"] and "error" not in out, out
        assert router["attempts"] == ["oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free"]
        assert out["model"] == "oc/nemotron-3-ultra-free" and out["model_fallback"][0]["status"] == 429
        fb = next(e for e in ws.events if e["type"] == "model.fallback")["payload"]
        assert fb["from"] == "oc/mimo-v2.6-flash-free" and fb["to"] == "oc/nemotron-3-ultra-free"
        assert fb["reason"] == "rate_limited" and fb["cooldown_s"] > 590
        st = next(e for e in ws.events if e["type"] == "status.update")
        assert st["session_id"] == sid and st["payload"]["kind"] == "fallback"
        assert "Model oc/mimo-v2.6-flash-free sedang dibatasi, pakai oc/nemotron-3-ultra-free sementara" in st["payload"]["text"]
        # the notice comes before the answer's text
        kinds = [e["type"] for e in ws.events]
        assert kinds.index("status.update") < kinds.index("message.delta")
        # the user's saved default is untouched
        d = await (await c.get("/api/models/default", headers=H())).json()
        assert d["model"] == "oc/mimo-v2.6-flash-free"
        assert "model" not in (cfgmod.load_config().get("model") or {}) or \
            cfgmod.load_config()["model"].get("default") in (None, "", "oc/mimo-v2.6-flash-free")

        # within the cooldown the next turn goes straight to the fallback (one request)
        router["attempts"].clear()
        out = await _chat(ws, sid, "lagi")
        assert "(oc/nemotron-3-ultra-free)" in out["text"] and router["attempts"] == ["oc/nemotron-3-ultra-free"]
        fb = next(e for e in ws.events if e["type"] == "model.fallback")["payload"]
        assert fb["reason"] == "cooldown"

        # cooldown over (and quota back) -> the default again, no notice
        router["limited"].clear()
        router9.clear_limited()
        router["attempts"].clear()
        out = await _chat(ws, sid, "sekali lagi")
        assert "(oc/mimo-v2.6-flash-free)" in out["text"] and router["attempts"] == ["oc/mimo-v2.6-flash-free"]
        assert not any(e["type"] == "model.fallback" for e in ws.events) and "model_fallback" not in out
    finally:
        await c.close()


async def test_fallback_skips_limited_and_unavailable_then_gives_up_in_indonesian(router, monkeypatch):
    router["limited"].update({"oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free"})
    router["down"].add("oc/ling-3.1-flash-free")
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        out = await _chat(ws, sid)
        assert "(oc/big-pickle)" in out["text"], out
        assert router["attempts"] == ["oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free", "oc/ling-3.1-flash-free",
                                      "oc/big-pickle"]
        fb = [e["payload"] for e in ws.events if e["type"] == "model.fallback"]
        assert len(fb) == 1 and fb[0]["from"] == "oc/mimo-v2.6-flash-free" and fb[0]["to"] == "oc/big-pickle"
        for m in ("oc/mimo-v2.6-flash-free", "oc/nemotron-3-ultra-free", "oc/ling-3.1-flash-free"):
            assert router9.cooldown_left(m) > 0
        assert not router9.cooldown_left("oc/big-pickle")

        # every free model limited: each tried once, then one Indonesian error
        router9.clear_limited()
        router["limited"].update(router9.free_order())
        router["attempts"].clear()
        out = await _chat(ws, sid, "lagi")
        assert out["error"].startswith("Semua model gratis yang dicoba sedang dibatasi"), out
        assert "oc/mimo-v2.6-flash-free" in out["error"]
        assert len(router["attempts"]) == len(set(router["attempts"])) <= 1 + router9.MAX_FALLBACKS
        assert not any(e["type"] == "model.fallback" for e in ws.events)
    finally:
        await c.close()


async def test_pinned_agent_model_is_tried_first_and_paid_pins_never_switch(router, monkeypatch):
    gw, c = await _client(monkeypatch)
    try:
        ws = await _ws(c)
        sid = (await ws.call("session.create", {}))["result"]["session_id"]
        aid = f"session:{sid}"
        # a pinned free model that is cooling down is still tried first (it answers)
        await c.put(f"/api/agents/{aid}/model", json={"model": "oc/ling-3.1-flash-free"}, headers=H())
        router9.mark_limited("oc/ling-3.1-flash-free")
        out = await _chat(ws, sid)
        assert "(oc/ling-3.1-flash-free)" in out["text"] and router["attempts"][-1:] == ["oc/ling-3.1-flash-free"]
        assert not router9.cooldown_left("oc/ling-3.1-flash-free")   # it answered: rest cleared
        assert not any(e["type"] == "model.fallback" for e in ws.events)

        # the pinned free model fails -> only then the free chain, with the notice
        router["limited"].add("oc/ling-3.1-flash-free")
        router["attempts"].clear()
        out = await _chat(ws, sid, "lagi")
        assert "(oc/mimo-v2.6-flash-free)" in out["text"]
        assert router["attempts"] == ["oc/ling-3.1-flash-free", "oc/mimo-v2.6-flash-free"]
        assert (await ws.call("agent.model.get", {"agent_id": sid}))["result"]["model"] == "oc/ling-3.1-flash-free"

        # a pinned paid/non-free model is never swapped for a free one
        await c.put(f"/api/agents/{aid}/model", json={"model": "kr/glm-5"}, headers=H())
        router["limited"].add("kr/glm-5")
        router["attempts"].clear()
        out = await _chat(ws, sid, "sekali lagi")
        assert router["attempts"] == ["kr/glm-5"] and "kr/glm-5" in out["error"] and "pilih model lain" in out["error"]
    finally:
        await c.close()
