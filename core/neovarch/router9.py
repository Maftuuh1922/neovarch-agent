"""9Router: the built-in, default model provider.

9Router (https://9router.com, MIT) is a local OpenAI-compatible router: ``npm i -g
9router`` then ``9router`` serves ``http://localhost:20128/v1`` with a dashboard at
``/dashboard``. Its "OpenCode Free" provider needs no account, so a fresh Neovarch
install can chat without any API key from the user.

This module:

* resolves the 9Router URL (``router9.base_url`` in config.yaml, env
  ``NEOVARCH_9ROUTER_URL``, default ``http://localhost:20128/v1``);
* detects whether the ``9router`` command is installed and whether the server answers;
* starts and supervises a local 9Router when it is installed but not running
  (``router9.autostart``, default on; env ``NEOVARCH_9ROUTER_AUTOSTART=0`` turns it off);
* provisions a 9Router API key for Neovarch with 9Router's local CLI token (same
  machine only), stored in ``.env`` as ``NEOVARCH_9ROUTER_API_KEY``;
* registers the live OpenCode Free model ids so they show in ``/v1/models``.

Status shape and events: docs/9router.md (``RouterStatus``).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import aiohttp

from neovarch import config as cfgmod

PROVIDER = "9router"
LABEL = "9Router"
DEFAULT_BASE_URL = "http://localhost:20128/v1"
# Default model on a fresh install: Xiaomi MiMo V2.6 Flash through OpenCode Free.
DEFAULT_MODEL = "oc/mimo-v2.6-flash-free"
# MiMo V2.6 Pro: the default instead once 9Router lists it (a MiMo account is connected).
PRO_MODEL = "mimo/mimo-v2.6-pro"
# Used in this order when the live OpenCode Free list no longer has the default.
FREE_FALLBACKS = ["oc/nemotron-3-ultra-free", "oc/ling-3.1-flash-free", "oc/big-pickle"]
# OpenCode Free models whose id has no "-free" suffix.
FREE_NAMED = {"oc/big-pickle"}
KEY_ENV = "NEOVARCH_9ROUTER_API_KEY"
KEY_NAME = "neovarch"
INSTALL_COMMAND = "npm install -g 9router"
OPENCODE_MODELS_URL = "https://opencode.ai/zen/v1/models"
CLI_TOKEN_HEADER = "x-9r-cli-token"
CLI_TOKEN_SALT = "9r-cli-auth"
HEALTH_TIMEOUT_S = 2.5
START_WAIT_S = 25.0
SUPERVISE_EVERY_S = 15.0
MAX_RESTARTS = 3            # within RESTART_WINDOW_S, then give up and report
RESTART_WINDOW_S = 300.0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# 9Router alias prefix -> group label shown in the model picker.
ALIAS_GROUPS = {
    "oc": "OpenCode Free", "ocg": "OpenCode Go", "ocz": "OpenCode Zen", "kr": "Kiro", "cc": "Claude Code",
    "cx": "Codex", "gh": "GitHub Copilot", "gc": "Gemini CLI", "ag": "Antigravity", "vertex": "Vertex AI",
    "if": "iFlow", "qw": "Qwen", "cu": "Cursor", "openrouter": "OpenRouter", "or": "OpenRouter",
    "glm": "GLM", "kimi": "Kimi", "mimo": "MiMo", "minimax": "MiniMax", "ds": "DeepSeek", "deepseek": "DeepSeek",
    "openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini", "groq": "Groq", "xai": "xAI",
}
FREE_ALIASES = {"oc"}
# Ids from the last successful GET /v1/models (filled by models.ModelCatalog).
LAST_MODEL_IDS: list[str] = []

# ----------------------------------------------------- free-model fallback ---
# OpenCode Free answers HTTP 429 (FreeUsageLimitError) when a model's free quota is
# used up. A chat turn then retries the same request on the next free model, and the
# limited model rests for COOLDOWN_S (in memory only; the saved default never changes).
COOLDOWN_S = 600.0
MAX_FALLBACKS = 6           # extra models tried per failed request
_LIMITED: dict[str, float] = {}   # model id -> monotonic time its cooldown ends


def is_free_model(model: str) -> bool:
    mid = str(model or "")
    alias, _, name = mid.partition("/")
    return alias in FREE_ALIASES and bool(name) and (mid == DEFAULT_MODEL or mid in FREE_NAMED or name.endswith("-free"))


def free_order(live_ids: list[str] | None = None) -> list[str]:
    """OpenCode Free models in fallback order: the default (MiMo V2.6 Flash), the named fallbacks, then the
    other ``oc/*-free`` models 9Router lists."""
    ids = LAST_MODEL_IDS if live_ids is None else live_ids
    order = [DEFAULT_MODEL] + list(FREE_FALLBACKS)
    order += sorted(i for i in ids if is_free_model(i) and i not in order)
    return order


def mark_limited(model: str, seconds: float = COOLDOWN_S) -> None:
    _LIMITED[str(model)] = time.monotonic() + seconds


def clear_limited(model: str | None = None) -> None:
    if model is None:
        _LIMITED.clear()
    else:
        _LIMITED.pop(str(model), None)


def cooldown_left(model: str) -> float:
    end = _LIMITED.get(str(model))
    if end is None:
        return 0.0
    left = end - time.monotonic()
    if left <= 0:
        _LIMITED.pop(str(model), None)
        return 0.0
    return left


def fallback_candidates(model: str, live_ids: list[str] | None = None) -> list[str]:
    """Free models to try after ``model`` failed: the fallback order without ``model``,
    models still cooling down last (tried only when every other one failed too)."""
    rest = [m for m in free_order(live_ids) if m != model]
    fresh = [m for m in rest if not cooldown_left(m)]
    resting = [m for m in rest if cooldown_left(m)]
    return (fresh + resting)[:MAX_FALLBACKS]


def retryable_status(error: str) -> int | None:
    """HTTP status of a chat failure another free model may not have (429 / 5xx /
    upstream unavailable), else None."""
    import re
    m = re.search(r"HTTP (\d{3})", error or "")
    if m:
        code = int(m.group(1))
        return code if code == 429 or 500 <= code <= 599 else None
    low = (error or "").lower()
    if "freeusagelimit" in low or "rate limit" in low:
        return 429
    if any(w in low for w in ("unavailable", "overloaded", "no available", "upstream error")):
        return 503
    return None


def fallback_notice(limited: str, used: str) -> str:
    return f"Model {limited} sedang dibatasi, pakai {used} sementara."


# ------------------------------------------------------------------ config ---

def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else cfgmod.load_config()


def settings(cfg: dict | None = None) -> dict[str, Any]:
    raw = cfgmod.get_path(_cfg(cfg), "router9", {}) or {}
    return raw if isinstance(raw, dict) else {}


def base_url(cfg: dict | None = None) -> str:
    url = os.environ.get("NEOVARCH_9ROUTER_URL") or str(settings(cfg).get("base_url") or "") or DEFAULT_BASE_URL
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    if not urlparse(url).path.rstrip("/"):
        url += "/v1"
    return url


def root_url(base: str) -> str:
    p = urlparse(base)
    path = p.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return f"{p.scheme}://{p.netloc}{path}"


def dashboard_url(base: str) -> str:
    return root_url(base) + "/dashboard"


def is_local(base: str) -> bool:
    return (urlparse(base).hostname or "").lower() in LOCAL_HOSTS


def port_of(base: str) -> int:
    p = urlparse(base)
    return p.port or (443 if p.scheme == "https" else 80)


def autostart_enabled(cfg: dict | None = None) -> bool:
    env = os.environ.get("NEOVARCH_9ROUTER_AUTOSTART")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(settings(cfg).get("autostart", True))


def api_key() -> str:
    return cfgmod.secret(KEY_ENV)


def require_api_key(cfg: dict | None = None) -> bool:
    """9Router asks for a key on /v1/chat/completions unless its owner turned that off."""
    return bool(settings(cfg).get("require_api_key", True))


def endpoint_spec(cfg: dict | None = None) -> dict[str, Any]:
    """The provider entry ``config.resolve_endpoint`` uses for provider ``9router``."""
    return {"base_url": base_url(cfg), "key_env": KEY_ENV, "model": default_model_id(cfg)}


def default_model_id(cfg: dict | None = None, live_ids: list[str] | None = None) -> str:
    """The built-in default: ``router9.default_model`` if set, else MiMo V2.6 Pro when
    9Router lists it, else MiMo V2.6 Flash (OpenCode Free)."""
    ids = LAST_MODEL_IDS if live_ids is None else live_ids
    return str(settings(cfg).get("default_model") or (PRO_MODEL if PRO_MODEL in ids else DEFAULT_MODEL))


def choose_default(free_ids: list[str], all_ids: list[str] | None = None) -> str:
    """Best default available: MiMo V2.6 Pro when 9Router lists it (``all_ids``), else
    MiMo V2.6 Flash, else the free fallbacks, else the first free model."""
    if all_ids and PRO_MODEL in all_ids:
        return PRO_MODEL
    ids = [i if i.startswith("oc/") else f"oc/{i}" for i in free_ids]
    if not ids or DEFAULT_MODEL in ids:
        return DEFAULT_MODEL
    for cand in FREE_FALLBACKS:
        if cand in ids:
            return cand
    return ids[0]


def find_binary(cfg: dict | None = None) -> str | None:
    cmd = os.environ.get("NEOVARCH_9ROUTER_BIN") or str(settings(cfg).get("command") or "")
    if cmd:
        found = shutil.which(cmd) or (cmd if Path(cmd).exists() else None)
        return found
    found = shutil.which("9router")
    if found:
        return found
    # npm's global bin is not always on the PATH of a desktop-launched process.
    for d in _npm_bin_dirs():
        for name in ("9router.cmd", "9router.exe", "9router") if sys.platform == "win32" else ("9router",):
            p = d / name
            if p.exists():
                return str(p)
    return None


def _npm_bin_dirs() -> list[Path]:
    home = Path.home()
    out = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            out.append(Path(appdata) / "npm")
        from neovarch.paths import neovarch_home
        out += [neovarch_home() / "tools" / "npm", neovarch_home() / "tools" / "node"]
    else:
        from neovarch.paths import neovarch_home
        tools = neovarch_home() / "tools"
        out += [tools / "npm" / "bin", tools / "node" / "bin", home / ".npm-global" / "bin",
                home / ".local" / "bin", Path("/usr/local/bin")]
        nvm = home / ".nvm" / "versions" / "node"
        if nvm.is_dir():
            out += sorted((p / "bin" for p in nvm.iterdir()), reverse=True)
    return out


# --------------------------------------------------------- 9router auth ----

def data_dir() -> Path:
    """9Router's data dir, the same rule its CLI uses."""
    env = os.environ.get("NEOVARCH_9ROUTER_DATA_DIR") or os.environ.get("DATA_DIR")
    if env and not (sys.platform == "win32" and env.startswith("/")):
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "9router"
    return Path.home() / ".9router"


def cli_token(ddir: Path | None = None) -> str | None:
    """9Router's local CLI token: sha256(machine_id + salt + cli_secret)[:16].

    Both files are written by the 9Router server the first time it checks a CLI token
    (see ``_prime_cli_token``); we never create them ourselves."""
    d = ddir or data_dir()
    try:
        raw = (d / "machine-id").read_text(encoding="utf-8").strip()
        secret = (d / "auth" / "cli-secret").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or not secret:
        return None
    return hashlib.sha256((raw + CLI_TOKEN_SALT + secret).encode()).hexdigest()[:16]


# ------------------------------------------------------------- the router ---

class Router9:
    """Detects, starts, supervises and provisions the local 9Router."""

    def __init__(self, on_status: Callable[[dict], Any] | None = None,
                 on_models: Callable[[list[str]], Any] | None = None):
        self.on_status = on_status
        self.on_models = on_models
        self.proc: subprocess.Popen | None = None
        self.managed = False
        self.state = "stopped"
        self.error: str | None = None
        self.version: str | None = None
        self.running = False
        self.free_models: list[str] = []
        self.user_stopped = False
        self._restarts: list[float] = []
        self._task: asyncio.Task | None = None
        self._last_sig: tuple | None = None
        self._lock = asyncio.Lock()
        self._provision_error: str | None = None

    # ---- probes ----------------------------------------------------------
    async def health(self, cfg: dict | None = None) -> bool:
        root = root_url(base_url(cfg))
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_S)) as s:
                async with s.get(root + "/api/health") as r:
                    ok = r.status == 200
                if ok and not self.version:
                    try:
                        async with s.get(root + "/api/version") as rv:
                            if rv.status == 200:
                                data = await rv.json(content_type=None)
                                v = data.get("currentVersion") or data.get("version") if isinstance(data, dict) else None
                                self.version = str(v) if v else None
                    except Exception:  # noqa: BLE001 - version is cosmetic
                        pass
                return ok
        except Exception:  # noqa: BLE001 - unreachable is a state, not an error
            return False

    def _proc_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---- status ----------------------------------------------------------
    def status(self, cfg: dict | None = None) -> dict[str, Any]:
        cfg = _cfg(cfg)
        base = base_url(cfg)
        binary = find_binary(cfg)
        installed = bool(binary)
        has_key = bool(api_key())
        state = self.state
        if self.running:
            state = "running"
        elif state not in ("starting", "error"):
            state = "stopped" if installed or not is_local(base) else "not_installed"
        ready = self.running and (has_key or not require_api_key(cfg))
        action, message, url = None, None, None
        if not ready:
            if self.running:
                action, url = "api_key", dashboard_url(base)
                message = (self._provision_error or "9Router berjalan, tetapi Neovarch belum punya API key-nya.") + \
                    " Buka dashboard 9Router \u25b8 Endpoint, buat API key, lalu tempel di sini."
            elif state == "starting":
                message = "9Router sedang dijalankan\u2026"
            elif not is_local(base):
                action, url = "start", dashboard_url(base)
                message = f"9Router di {root_url(base)} tidak menjawab. Pastikan server itu berjalan."
            elif not installed:
                action = "install"
                message = f"9Router belum terpasang. Jalankan: {INSTALL_COMMAND}"
            else:
                action = "start"
                message = self.error or "9Router berhenti. Tekan Jalankan untuk menyalakannya."
        return {
            "state": state, "installed": installed, "running": self.running, "managed": self.managed and self._proc_alive(),
            "pid": self.proc.pid if self._proc_alive() else None, "base_url": base,
            "dashboard_url": dashboard_url(base), "version": self.version if self.running else None,
            "binary": binary, "has_api_key": has_key, "autostart": autostart_enabled(cfg),
            "error": self.error,
            "setup": {"ready": ready, "action": action, "message": message, "action_url": url,
                      "install_command": INSTALL_COMMAND},
        }

    def _publish(self, cfg: dict | None = None) -> dict:
        st = self.status(cfg)
        sig = (st["state"], st["installed"], st["running"], st["managed"], st["has_api_key"], st["error"],
               st["setup"]["action"], st["version"])
        if sig != self._last_sig:
            self._last_sig = sig
            if self.on_status:
                try:
                    self.on_status(st)
                except Exception:  # noqa: BLE001 - a listener never breaks the router
                    pass
        return st

    async def refresh(self, cfg: dict | None = None) -> dict:
        cfg = _cfg(cfg)
        was = self.running
        self.running = await self.health(cfg)
        if self.running:
            if self.state != "running":
                self.error = None
            self.state = "running"
            if not was or not api_key():
                await self.provision(cfg)
        elif self.state == "running":
            self.state = "stopped"
            self.version = None
        return self._publish(cfg)

    # ---- process control ---------------------------------------------------
    async def start(self, cfg: dict | None = None, *, wait: float = START_WAIT_S) -> dict:
        cfg = _cfg(cfg)
        async with self._lock:
            self.user_stopped = False
            if await self.health(cfg):
                self.running = True
                self.state = "running"
                await self.provision(cfg)
                return self._publish(cfg)
            base = base_url(cfg)
            if not is_local(base):
                self.error = f"URL 9Router ({root_url(base)}) bukan di komputer ini, jadi Neovarch tidak bisa menjalankannya."
                self.state = "error"
                return self._publish(cfg)
            binary = find_binary(cfg)
            if not binary:
                self.state = "not_installed"
                self.error = None
                return self._publish(cfg)
            self.state = "starting"
            self.error = None
            self._publish(cfg)
            try:
                self.proc = self._spawn(binary, port_of(base))
                self.managed = True
            except OSError as exc:
                self.state, self.error = "error", f"Gagal menjalankan 9Router: {exc}"
                return self._publish(cfg)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if await self.health(cfg):
                    self.running = True
                    self.state = "running"
                    await self.provision(cfg)
                    return self._publish(cfg)
                if not self._proc_alive():
                    break
                await asyncio.sleep(0.5)
            self.running = False
            code = self.proc.poll() if self.proc else None
            self.state = "error"
            self.error = ("9Router berhenti saat dinyalakan" + (f" (kode {code})" if code is not None else "") +
                          f". Lihat log: {log_path()}") if code is not None else \
                f"9Router belum menjawab setelah {int(wait)} detik. Lihat log: {log_path()}"
            return self._publish(cfg)

    @staticmethod
    def _spawn(binary: str, port: int) -> subprocess.Popen:
        # --tray: no interactive menu (it needs a TTY); the tray icon is optional and
        # skipped quietly on a headless machine. Bound to loopback only.
        args = [binary, "--tray", "--no-browser", "--skip-update", "-p", str(port), "-H", "127.0.0.1"]
        lp = log_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        log = open(lp, "ab")  # noqa: SIM115 - handed to the child
        kw: dict[str, Any] = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        try:
            return subprocess.Popen(args, **kw)
        finally:
            log.close()

    async def stop(self, cfg: dict | None = None) -> dict:
        cfg = _cfg(cfg)
        self.user_stopped = True
        if self._proc_alive():
            assert self.proc is not None
            self.proc.terminate()
            for _ in range(20):
                if self.proc.poll() is not None:
                    break
                await asyncio.sleep(0.25)
            if self.proc.poll() is None:
                self.proc.kill()
        self.proc = None
        self.managed = False
        self.running = await self.health(cfg)
        self.state = "running" if self.running else "stopped"
        return self._publish(cfg)

    # ---- supervision ---------------------------------------------------------
    def start_supervisor(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._supervise())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # A 9Router this core started keeps running for other tools; it is not ours to kill
        # on a gateway restart. Only `stop()` (the user's button) ends it.

    async def _supervise(self) -> None:
        first = True
        while True:
            try:
                await self.tick(first=first)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep supervising
                self.error = f"{type(exc).__name__}: {exc}"
            first = False
            await asyncio.sleep(float(os.environ.get("NEOVARCH_9ROUTER_TICK") or SUPERVISE_EVERY_S))

    async def tick(self, *, first: bool = False) -> dict:
        cfg = cfgmod.load_config()
        st = await self.refresh(cfg)
        if st["running"] or self.user_stopped or not autostart_enabled(cfg) or not st["installed"]:
            return st
        if not is_local(base_url(cfg)):
            return st
        crashed = self.managed and not self._proc_alive()
        if not (first or crashed):
            return st
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW_S]
        if len(self._restarts) >= MAX_RESTARTS:
            self.state = "error"
            self.error = (f"9Router berhenti {MAX_RESTARTS}x dalam 5 menit; Neovarch berhenti mencoba. "
                          f"Lihat log: {log_path()}")
            return self._publish(cfg)
        self._restarts.append(now)
        return await self.start(cfg)

    # ---- provisioning -------------------------------------------------------
    async def provision(self, cfg: dict | None = None) -> bool:
        """Get Neovarch a 9Router API key and register the OpenCode Free models."""
        cfg = _cfg(cfg)
        root = root_url(base_url(cfg))
        if not is_local(base_url(cfg)):
            if not api_key():
                self._provision_error = "API key 9Router di server lain harus ditempel manual."
            return bool(api_key())
        token = cli_token()
        if not token and not api_key():
            token = await _prime_cli_token(root)
        if not token:
            if not api_key():
                self._provision_error = "Neovarch tidak bisa membaca token lokal 9Router."
            return bool(api_key())
        headers = {CLI_TOKEN_HEADER: token, "Accept": "application/json"}
        ok = bool(api_key())
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                if not ok:
                    key = await _ensure_key(s, root, headers)
                    if key:
                        cfgmod.write_env_value(KEY_ENV, key)
                        ok = True
                        self._provision_error = None
                    else:
                        self._provision_error = "9Router menolak membuat API key otomatis."
                await self._register_free_models(s, root, headers)
        except Exception as exc:  # noqa: BLE001 - reported in status
            if not ok:
                self._provision_error = f"Gagal menyiapkan API key 9Router: {exc}"
        return ok

    async def _register_free_models(self, s: aiohttp.ClientSession, root: str, headers: dict) -> None:
        try:
            async with s.get(root + "/api/providers/suggested-models",
                             params={"url": OPENCODE_MODELS_URL, "type": "opencode-free"}, headers=headers) as r:
                if r.status != 200:
                    return
                data = await r.json(content_type=None)
        except Exception:  # noqa: BLE001 - best effort
            return
        ids = [str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
        if not ids:
            return
        changed = ids != self.free_models
        self.free_models = ids
        try:
            async with s.get(root + "/api/models/custom", headers=headers) as r:
                existing_raw = await r.json(content_type=None) if r.status == 200 else {}
        except Exception:  # noqa: BLE001
            existing_raw = {}
        rows = existing_raw.get("models") if isinstance(existing_raw, dict) else existing_raw
        existing = {(str(m.get("providerAlias")), str(m.get("id"))) for m in rows or [] if isinstance(m, dict)}
        for mid in ids:
            if ("oc", mid) in existing:
                continue
            try:
                async with s.post(root + "/api/models/custom", json={"providerAlias": "oc", "id": mid, "type": "llm"},
                                  headers=headers) as r:
                    await r.read()
            except Exception:  # noqa: BLE001
                break
        if changed and self.on_models:
            try:
                self.on_models(ids)
            except Exception:  # noqa: BLE001
                pass


async def _prime_cli_token(root: str) -> str | None:
    """A fresh 9Router writes machine-id and auth/cli-secret only the first time it checks a
    CLI token. One request carrying a (wrong) token makes it create them; then we can derive
    the real token. Verified against 9router 0.5.99."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(root + "/api/keys", headers={CLI_TOKEN_HEADER: "0" * 16}) as r:
                await r.read()
    except Exception:  # noqa: BLE001 - provisioning reports the outcome
        return None
    return cli_token()


async def _ensure_key(s: aiohttp.ClientSession, root: str, headers: dict) -> str | None:
    async with s.get(root + "/api/keys", headers=headers) as r:
        if r.status == 200:
            data = await r.json(content_type=None)
            for k in (data.get("keys") or []) if isinstance(data, dict) else []:
                if isinstance(k, dict) and k.get("name") == KEY_NAME and k.get("key") and k.get("isActive", True) is not False:
                    return str(k["key"])
        elif r.status in (401, 403):
            return None
    async with s.post(root + "/api/keys", json={"name": KEY_NAME}, headers=headers) as r:
        if r.status in (200, 201):
            data = await r.json(content_type=None)
            return str(data.get("key") or "") or None
    return None


async def ensure_ready(r: Router9, cfg: dict | None = None) -> dict:
    """Before a turn on 9Router: refresh, start it when installed and allowed, provision."""
    st = await r.refresh(cfg)
    if (not st["running"] and st["installed"] and not r.user_stopped and autostart_enabled(cfg)
            and is_local(st["base_url"])):
        st = await r.start(cfg)
    return st


def log_path() -> Path:
    from neovarch.paths import neovarch_home
    return neovarch_home() / "logs" / "9router.log"
