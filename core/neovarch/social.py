"""Friends & profile via GitHub — no Neovarch server; GitHub is the backend.

* Sign-in: OAuth **device flow** (no client secret). The OAuth App client id comes
  from ``social.github_client_id`` in config.yaml or ``NEOVARCH_GITHUB_CLIENT_ID``.
  Scopes ``read:user gist user:follow``. The token lives in the OS keychain
  (python ``keyring`` when installed) or ``~/.neovarch/secrets/github_token`` (0600);
  it is never logged or returned by any route.
* Profile: GitHub avatar/name/bio/login + what this PC computes: a 365-day
  activity heatmap (agent sessions/tool calls per day, plus optionally the
  GitHub contribution calendar via GraphQL), the top stack (languages from file
  extensions the agent touched + tools used + top languages of the user's repos)
  and a "coding now" status (activity in the last 10 minutes; project name only
  when ``social.share_project`` is on).
* Publishing: JSON in a public Gist with the file ``neovarch-profile.json``
  (created once, id remembered), at most every 5 minutes and on status change,
  honouring the privacy toggles ``publish_heatmap / publish_stack /
  publish_status / paused``.
* Friends: mutual follows (following ∩ followers); each friend's card comes from
  their public ``neovarch-profile.json`` gist. Add friend = PUT
  /user/following/{u}; unfriend = DELETE.
* Rate limits: conditional requests (ETag / If-None-Match), 5-minute cache,
  back-off on 403/429 (Retry-After / X-RateLimit-Reset); stale cache is served
  while backing off.

The phone needs no GitHub login: it reads ``/api/social/*`` through the paired PC,
and every change is pushed as the realtime event ``social.changed``. When the PC
is signed out the phone can only ask the PC to start its own device flow
(``POST /api/social/login`` / ``social.login.start``) and shows the code.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import stat
import time
from collections import Counter
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from neovarch import __version__
from neovarch import config as cfgmod
from neovarch.paths import neovarch_home

GIST_FILE = "neovarch-profile.json"
SCHEMA = "neovarch-profile/1"
SCOPES = "read:user gist user:follow"
CACHE_TTL = 300
PUBLISH_EVERY = 300
STATUS_MIN_GAP = 30
ACTIVE_WINDOW = 600
HEATMAP_DAYS = 365
DEFAULTS = {"publish_heatmap": True, "publish_stack": True, "publish_status": True,
            "share_project": False, "paused": False, "include_github_contributions": True}

EXT_LANG = {
    ".py": "Python", ".ipynb": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".dart": "Dart", ".kt": "Kotlin",
    ".kts": "Kotlin", ".java": "Java", ".swift": "Swift", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".vue": "Vue", ".svelte": "Svelte",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".lua": "Lua",
    ".r": "R", ".scala": "Scala", ".md": "Markdown", ".tex": "TeX", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".json": "JSON", ".gradle": "Gradle", ".ex": "Elixir", ".exs": "Elixir", ".zig": "Zig",
    ".hs": "Haskell", ".ml": "OCaml", ".clj": "Clojure", ".erl": "Erlang", ".nim": "Nim", ".jl": "Julia",
}
PATH_KEYS = ("path", "file", "file_path", "filename", "target", "notebook_path")


# Built-in GitHub OAuth App client ID (Neovarch Agent, device flow). A client ID
# is public (no secret), so it lives in the repo and GitHub login works in one
# click. A build-time NEOVARCH_GITHUB_CLIENT_ID_DEFAULT (CI variable) or the
# user's own Client ID in Profil & Teman still takes precedence.
DEFAULT_GITHUB_CLIENT_ID = "Ov23li1lB513P2W10ZM7"


def resolve_client_id() -> tuple[str, str]:
    """(client_id, source): the user's override in config.yaml wins, then the
    NEOVARCH_GITHUB_CLIENT_ID env, then the build-time / built-in default."""
    raw = str(cfgmod.get_path(cfgmod.load_config(), "social.github_client_id", "") or "").strip()
    if raw:
        return raw, "config"
    env = str(os.environ.get("NEOVARCH_GITHUB_CLIENT_ID") or "").strip()
    if env:
        return env, "env"
    baked = str(os.environ.get("NEOVARCH_GITHUB_CLIENT_ID_DEFAULT") or DEFAULT_GITHUB_CLIENT_ID or "").strip()
    if baked:
        return baked, "default"
    return "", "none"


class SocialError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.code = code


class RateLimited(SocialError):
    def __init__(self, until: float):
        super().__init__(f"Batas API GitHub tercapai; coba lagi sekitar {time.strftime('%H:%M', time.localtime(until))}.",
                         429, "rate_limited")
        self.until = until


# ------------------------------------------------------------- token store ---

class TokenStore:
    """OS keychain via ``keyring`` when available, else a 0600 file in the core home."""

    SERVICE = "neovarch-agent"
    USER = "github"

    def __init__(self) -> None:
        self.backend = "file"
        self._kr = None
        if os.environ.get("NEOVARCH_SECRET_BACKEND", "").lower() != "file":
            try:
                import keyring  # type: ignore
                from keyring.backends import fail  # type: ignore
                if not isinstance(keyring.get_keyring(), fail.Keyring):
                    self._kr = keyring
                    self.backend = "keychain"
            except Exception:
                self._kr = None

    @staticmethod
    def _file() -> Path:
        return neovarch_home() / "secrets" / "github_token"

    def get(self) -> str:
        if self._kr is not None:
            try:
                return self._kr.get_password(self.SERVICE, self.USER) or ""
            except Exception:
                pass
        try:
            return self._file().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def set(self, token: str) -> None:
        if self._kr is not None:
            try:
                self._kr.set_password(self.SERVICE, self.USER, token)
                return
            except Exception:
                self.backend = "file"
        f = self._file()
        f.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(f.parent, stat.S_IRWXU)
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.chmod(f, 0o600)

    def clear(self) -> None:
        if self._kr is not None:
            try:
                self._kr.delete_password(self.SERVICE, self.USER)
            except Exception:
                pass
        try:
            self._file().unlink()
        except OSError:
            pass


# ----------------------------------------------------------- GitHub client ---

class GitHub:
    """Small REST/GraphQL client: ETag cache (5 min), back-off on 403/429."""

    def __init__(self, token_fn):
        self.api = (os.environ.get("NEOVARCH_GITHUB_API") or "https://api.github.com").rstrip("/")
        self.oauth = (os.environ.get("NEOVARCH_GITHUB_OAUTH") or "https://github.com").rstrip("/")
        self.token_fn = token_fn
        self.cache: dict[str, dict] = {}
        self.backoff_until = 0.0
        self.rate: dict[str, Any] = {}
        self._session: aiohttp.ClientSession | None = None
        self.requests = 0

    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self, auth: bool = True) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": f"Neovarch-Agent/{__version__}"}
        tok = self.token_fn() if auth else ""
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def url(self, path: str) -> str:
        return path if path.startswith(("http://", "https://")) else self.api + path

    def _note_rate(self, resp: aiohttp.ClientResponse) -> None:
        rem = resp.headers.get("X-RateLimit-Remaining")
        if rem is not None:
            try:
                self.rate = {"remaining": int(rem), "limit": int(resp.headers.get("X-RateLimit-Limit") or 0),
                             "reset": int(resp.headers.get("X-RateLimit-Reset") or 0)}
            except ValueError:
                pass

    def _backoff(self, resp: aiohttp.ClientResponse) -> float:
        now = time.time()
        ra = resp.headers.get("Retry-After")
        reset = resp.headers.get("X-RateLimit-Reset")
        if ra and ra.isdigit():
            until = now + int(ra)
        elif reset and reset.isdigit() and resp.headers.get("X-RateLimit-Remaining") == "0":
            until = float(reset)
        else:
            until = now + 60
        self.backoff_until = max(self.backoff_until, min(until, now + 3600))
        return self.backoff_until

    @staticmethod
    def _is_rate_limit(status: int, resp: aiohttp.ClientResponse, body: str) -> bool:
        if status == 429:
            return True
        if status != 403:
            return False
        return (resp.headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in resp.headers
                or "rate limit" in body.lower())

    async def get(self, path: str, *, params: dict | None = None, ttl: float = CACHE_TTL,
                  auth: bool = True, raw: bool = False) -> Any:
        url = self.url(path)
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        hit = self.cache.get(key)
        now = time.time()
        if hit and now - hit["ts"] < ttl:
            return hit["data"]
        if now < self.backoff_until:
            if hit:
                return hit["data"]
            raise RateLimited(self.backoff_until)
        headers = self._headers(auth)
        if hit and hit.get("etag"):
            headers["If-None-Match"] = hit["etag"]
        self.requests += 1
        try:
            async with self.session().get(url, params=params, headers=headers) as resp:
                self._note_rate(resp)
                if resp.status == 304 and hit:
                    hit["ts"] = now
                    return hit["data"]
                text = await resp.text()
                if self._is_rate_limit(resp.status, resp, text):
                    until = self._backoff(resp)
                    if hit:
                        return hit["data"]
                    raise RateLimited(until)
                if resp.status == 401:
                    raise SocialError("Token GitHub tidak valid lagi; masuk ulang.", 401, "unauthorized")
                if resp.status == 404:
                    raise SocialError("Tidak ditemukan di GitHub.", 404, "not_found")
                if resp.status >= 400:
                    raise SocialError(f"GitHub HTTP {resp.status}: {text[:200]}", 502, "github_error")
                data: Any = text if raw else (json.loads(text) if text.strip() else None)
                self.cache[key] = {"ts": now, "etag": resp.headers.get("ETag"), "data": data}
                if len(self.cache) > 2000:
                    for k in sorted(self.cache, key=lambda k: self.cache[k]["ts"])[:500]:
                        self.cache.pop(k, None)
                return data
        except aiohttp.ClientError as exc:
            if hit:
                return hit["data"]
            raise SocialError(f"GitHub tidak bisa dihubungi: {exc}", 502, "unreachable") from exc

    async def get_all(self, path: str, *, pages: int = 10, ttl: float = CACHE_TTL) -> list:
        out: list = []
        for page in range(1, pages + 1):
            chunk = await self.get(path, params={"per_page": 100, "page": page}, ttl=ttl)
            if not isinstance(chunk, list):
                break
            out.extend(chunk)
            if len(chunk) < 100:
                break
        return out

    async def send(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if time.time() < self.backoff_until:
            raise RateLimited(self.backoff_until)
        self.requests += 1
        try:
            async with self.session().request(method, self.url(path), json=body, headers=self._headers()) as resp:
                self._note_rate(resp)
                text = await resp.text()
                if self._is_rate_limit(resp.status, resp, text):
                    raise RateLimited(self._backoff(resp))
                if resp.status == 401:
                    raise SocialError("Token GitHub tidak valid lagi; masuk ulang.", 401, "unauthorized")
                if resp.status >= 400:
                    raise SocialError(f"GitHub HTTP {resp.status}: {text[:200]}",
                                      404 if resp.status == 404 else 502, "github_error")
                try:
                    return resp.status, json.loads(text) if text.strip() else None
                except json.JSONDecodeError:
                    return resp.status, text
        except aiohttp.ClientError as exc:
            raise SocialError(f"GitHub tidak bisa dihubungi: {exc}", 502, "unreachable") from exc

    def invalidate(self, prefix: str) -> None:
        url = self.url(prefix)
        for k in [k for k in self.cache if k.startswith(url)]:
            self.cache.pop(k, None)

    async def oauth_post(self, path: str, data: dict) -> dict:
        try:
            async with self.session().post(self.oauth + path, data=data,
                                           headers={"Accept": "application/json",
                                                    "User-Agent": f"Neovarch-Agent/{__version__}"}) as resp:
                text = await resp.text()
                try:
                    out = json.loads(text)
                except json.JSONDecodeError:
                    raise SocialError(f"GitHub OAuth HTTP {resp.status}", 502, "github_error") from None
                if resp.status >= 400 and not out.get("error"):
                    raise SocialError(f"GitHub OAuth HTTP {resp.status}", 502, "github_error")
                return out
        except aiohttp.ClientError as exc:
            raise SocialError(f"GitHub tidak bisa dihubungi: {exc}", 502, "unreachable") from exc


# ------------------------------------------------------------- local stats ---

def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _paths_in(args: Any) -> list[str]:
    out = []
    if isinstance(args, dict):
        for k in PATH_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v:
                out.append(v)
        for v in args.get("paths") or [] if isinstance(args.get("paths"), list) else []:
            if isinstance(v, str):
                out.append(v)
    return out


def scan_sessions(store, days: int = HEATMAP_DAYS) -> dict:
    """Agent activity per day + extensions + tools from the stored transcripts."""
    cutoff = time.time() - days * 86400
    per_day: Counter = Counter()
    exts: Counter = Counter()
    tools: Counter = Counter()
    last = 0.0
    last_cwd = ""
    for summary in store.list(limit=100000):
        rec = store.load(summary["id"]) or {}
        for m in rec.get("messages", []):
            ts = m.get("ts")
            if not isinstance(ts, (int, float)) or ts < cutoff:
                continue
            role = m.get("role")
            if role == "user":
                per_day[_day(ts)] += 1
            elif role == "assistant":
                for call in m.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "")
                    if not name:
                        continue
                    tools[name] += 1
                    per_day[_day(ts)] += 1
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    for p in _paths_in(args):
                        suf = Path(p).suffix.lower()
                        if suf in EXT_LANG:
                            exts[EXT_LANG[suf]] += 1
            if ts > last:
                last = ts
                last_cwd = str(rec.get("cwd") or "")
    return {"per_day": dict(per_day), "languages": dict(exts), "tools": dict(tools),
            "last_activity": last, "last_cwd": last_cwd}


def heatmap(agent: dict[str, int], github: dict[str, int] | None, end: dt.date | None = None,
            days: int = HEATMAP_DAYS) -> dict:
    end = end or dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    a = [int(agent.get(d, 0)) for d in dates]
    g = [int((github or {}).get(d, 0)) for d in dates]
    counts = [x + y for x, y in zip(a, g)]
    streak = 0
    for c in reversed(counts):
        if c <= 0:
            break
        streak += 1
    return {"start": dates[0], "end": dates[-1], "days": days, "counts": counts, "agent": a,
            "github": g if github is not None else None, "total": sum(counts),
            "active_days": sum(1 for c in counts if c), "streak": streak, "max": max(counts) if counts else 0}


def top_shares(counter: dict[str, int], n: int = 8) -> list[dict]:
    total = sum(counter.values()) or 1
    return [{"name": k, "count": v, "share": round(v / total, 3)}
            for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def merged_stack(agent_langs: dict[str, int], gh_langs: dict[str, int], n: int = 8) -> list[dict]:
    score: Counter = Counter()
    for weight, src in ((0.6, agent_langs), (0.4, gh_langs)):
        total = sum(src.values())
        for k, v in src.items():
            if total:
                score[k] += weight * v / total
    total = sum(score.values()) or 1
    return [{"name": k, "share": round(v / total, 3),
             "source": "both" if k in agent_langs and k in gh_langs else ("agent" if k in agent_langs else "github")}
            for k, v in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def _iso(ts: float | None) -> str | None:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z") if ts else None


def _parse_iso(s: Any) -> float:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ social ---

class Social:
    def __init__(self, gw):
        self.gw = gw
        self.tokens = TokenStore()
        self._token = None
        self.gh = GitHub(self.token)
        self.login_state: dict[str, Any] = {"state": "idle"}
        self._login_task: asyncio.Task | None = None
        self._loop_task: asyncio.Task | None = None
        self.last_agent_activity = 0.0
        self.last_editor_activity = 0.0
        self.editor_project = ""
        self._stats: dict | None = None
        self._stats_ts = 0.0
        self._coding: bool | None = None
        self._publish_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.tick = float(os.environ.get("NEOVARCH_SOCIAL_TICK") or 60)

    # ---- settings / state -------------------------------------------------
    def token(self) -> str:
        if self._token is None:
            self._token = self.tokens.get()
        return self._token

    def settings(self) -> dict:
        raw = cfgmod.get_path(cfgmod.load_config(), "social", {}) or {}
        out = {**DEFAULTS, **{k: bool(raw[k]) for k in DEFAULTS if k in raw}}
        cid, source = resolve_client_id()
        # Only the user's own override is echoed back into the editable field;
        # a built-in default stays out of it (the field is an advanced override).
        out["github_client_id"] = cid if source == "config" else ""
        out["github_client_id_source"] = source
        return out

    def client_id(self) -> str:
        return resolve_client_id()[0]

    def client_id_source(self) -> str:
        return resolve_client_id()[1]

    def save_settings(self, body: dict) -> dict:
        cfg = cfgmod.load_config()
        cur = dict(cfgmod.get_path(cfg, "social", {}) or {})
        for k in DEFAULTS:
            if k in body:
                cur[k] = bool(body[k])
        if "github_client_id" in body:
            cid = str(body.get("github_client_id") or "").strip()
            if cid and not re.fullmatch(r"[A-Za-z0-9._-]{8,64}", cid):
                raise SocialError("Client ID GitHub tidak valid.", 422, "bad_client_id")
            cur["github_client_id"] = cid
        cfgmod.set_path(cfg, "social", cur)
        cfgmod.save_config(cfg)
        self.changed("settings")
        self.kick()
        return self.settings()

    @staticmethod
    def _state_path() -> Path:
        return neovarch_home() / "social" / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_state(self, **kw) -> dict:
        st = {**self.state(), **kw}
        p = self._state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        return st

    def changed(self, what: str, **extra) -> None:
        self.gw.broadcast_event("social.changed", None, {"what": what, **extra})

    # ---- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._loop_task is None and os.environ.get("NEOVARCH_SOCIAL_DISABLE") != "1":
            self._loop_task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        for t in (self._loop_task, self._login_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self._loop_task = None
        await self.gh.close()

    def kick(self) -> None:
        try:
            asyncio.get_running_loop().create_task(self.maybe_publish())
        except RuntimeError:
            pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.maybe_publish()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never kill the gateway
                self.last_error = str(exc)
            await asyncio.sleep(self.tick)

    # ---- activity -----------------------------------------------------------
    def observe(self, kind: str, sid: str | None, payload: Any) -> None:
        if kind in ("message.start", "message.delta", "tool.start", "tool.complete", "reasoning.delta"):
            first = self.last_agent_activity < time.time() - ACTIVE_WINDOW
            self.last_agent_activity = time.time()
            if kind == "tool.start":
                self._stats_ts = 0  # stack/heatmap recomputed on next read
            if first:
                self._status_flip()

    def editor_heartbeat(self, project: str = "") -> None:
        first = self.last_editor_activity < time.time() - ACTIVE_WINDOW
        self.last_editor_activity = time.time()
        if project:
            self.editor_project = project[:80]
        if first:
            self._status_flip()

    def _status_flip(self) -> None:
        # Signed out there is no profile to update; signed in, maybe_publish emits
        # social.changed {what: status} on the idle -> coding transition.
        if self._coding is not True and self.token():
            self.kick()

    async def local_stats(self) -> dict:
        if self._stats is None or time.time() - self._stats_ts > CACHE_TTL:
            self._stats = await asyncio.to_thread(scan_sessions, self.gw.store)
            self._stats_ts = time.time()
        return self._stats

    def status(self, stats: dict, settings: dict) -> dict:
        now = time.time()
        live_running = [l for l in self.gw.live.values() if l.status == "running"]
        last = max(self.last_agent_activity, self.last_editor_activity, stats.get("last_activity") or 0,
                   now if live_running else 0)
        coding = bool(live_running) or now - last < ACTIVE_WINDOW
        project = None
        if coding and settings.get("share_project"):
            cwd = str(live_running[0].ctx.cwd) if live_running else stats.get("last_cwd") or ""
            project = self.editor_project or (Path(cwd).name if cwd else None) or None
        return {"coding": coding, "last_active_at": _iso(last), "project": project,
                "source": "agent" if live_running or self.last_agent_activity >= self.last_editor_activity else "editor"}

    # ---- GitHub-side data ---------------------------------------------------
    async def me(self) -> dict:
        if not self.token():
            raise SocialError("Belum masuk dengan GitHub.", 401, "signed_out")
        u = await self.gh.get("/user")
        return {"login": u.get("login"), "name": u.get("name") or u.get("login"), "bio": u.get("bio") or "",
                "avatar_url": u.get("avatar_url"), "html_url": u.get("html_url"),
                "followers": u.get("followers"), "following": u.get("following")}

    async def github_languages(self) -> dict[str, int]:
        repos = await self.gh.get("/user/repos", params={"per_page": 100, "sort": "pushed", "affiliation": "owner"})
        c: Counter = Counter()
        for r in repos or []:
            if isinstance(r, dict) and r.get("language") and not r.get("fork"):
                c[r["language"]] += 1
        return dict(c)

    async def github_contributions(self, login: str) -> dict[str, int] | None:
        q = ("query($login:String!){user(login:$login){contributionsCollection{contributionCalendar"
             "{weeks{contributionDays{date contributionCount}}}}}}")
        key = f"graphql:{login}"
        hit = self.gh.cache.get(key)
        if hit and time.time() - hit["ts"] < CACHE_TTL:
            return hit["data"]
        try:
            _, data = await self.gh.send("POST", "/graphql", {"query": q, "variables": {"login": login}})
        except SocialError:
            return hit["data"] if hit else None
        days: dict[str, int] = {}
        try:
            weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
            for w in weeks:
                for d in w.get("contributionDays") or []:
                    if d.get("contributionCount"):
                        days[d["date"]] = int(d["contributionCount"])
        except (KeyError, TypeError):
            return None
        self.gh.cache[key] = {"ts": time.time(), "data": days}
        return days

    async def build_profile(self, *, for_publish: bool = False) -> dict:
        settings = self.settings()
        stats = await self.local_stats()
        me = await self.me() if self.token() else None
        gh_langs: dict[str, int] = {}
        contrib = None
        if me:
            try:
                gh_langs = await self.github_languages()
            except SocialError:
                gh_langs = {}
            if settings["include_github_contributions"]:
                contrib = await self.github_contributions(me["login"])
        hm = heatmap(stats["per_day"], contrib)
        stack = {"languages": merged_stack(stats["languages"], gh_langs),
                 "agent_languages": top_shares(stats["languages"]),
                 "github_languages": top_shares(gh_langs), "tools": top_shares(stats["tools"])}
        status = self.status(stats, settings)
        prof: dict[str, Any] = {"schema": SCHEMA, "app": "neovarch", "version": __version__,
                                **(me or {"login": None, "name": None, "bio": "", "avatar_url": None, "html_url": None})}
        if for_publish:
            prof.pop("followers", None)
            prof.pop("following", None)
            if settings["publish_heatmap"]:
                prof["heatmap"] = {k: hm[k] for k in ("start", "end", "days", "counts", "total", "active_days", "streak", "max")}
            if settings["publish_stack"]:
                prof["stack"] = {"languages": stack["languages"], "tools": stack["tools"][:6]}
            if settings["publish_status"]:
                prof["status"] = {"coding": status["coding"], "last_active_at": status["last_active_at"],
                                  **({"project": status["project"]} if status["project"] else {})}
            return prof
        st = self.state()
        prof.update({"heatmap": hm, "stack": stack, "status": status, "settings": settings,
                     "publish": {"gist_id": st.get("gist_id"), "gist_url": st.get("gist_url"),
                                 "last_published_at": st.get("last_published_at"),
                                 "paused": settings["paused"], "error": st.get("last_publish_error")}})
        return prof

    # ---- publishing -----------------------------------------------------------
    async def maybe_publish(self, force: bool = False) -> dict:
        if not self.token():
            return {"published": False, "reason": "signed_out"}
        settings = self.settings()
        async with self._publish_lock:
            stats = await self.local_stats()
            coding = self.status(stats, settings)["coding"]
            if coding != self._coding:
                if self._coding is not None:
                    self.changed("status", coding=coding)
                self._coding = coding
            if settings["paused"] and not force:
                return {"published": False, "reason": "paused"}
            st = self.state()
            now = time.time()
            last = float(st.get("last_published_ts") or 0)
            status_changed = coding != st.get("last_coding") and settings["publish_status"]
            due = now - last >= PUBLISH_EVERY
            if not force and not due and not (status_changed and now - last >= STATUS_MIN_GAP):
                return {"published": False, "reason": "throttled", "next_in": round(PUBLISH_EVERY - (now - last))}
            try:
                payload = await self.build_profile(for_publish=True)
                body = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
                digest = hashlib.sha256(json.dumps({**payload, "status": {**(payload.get("status") or {}), "last_active_at": None}},
                                                   sort_keys=True).encode()).hexdigest()
                if not force and digest == st.get("last_hash") and not status_changed and now - last < 6 * 3600:
                    self.save_state(last_published_ts=now, last_coding=coding)
                    return {"published": False, "reason": "unchanged"}
                payload["updated_at"] = _iso(now)
                body = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
                gist_id, created = await self._ensure_gist(st, body)
                if not created:
                    try:
                        await self.gh.send("PATCH", f"/gists/{gist_id}", {"files": {GIST_FILE: {"content": body}}})
                    except SocialError as exc:
                        if exc.status != 404:
                            raise
                        # the gist was deleted on github.com: create it again once
                        self.save_state(gist_id=None, gist_url=None)
                        gist_id, _ = await self._ensure_gist({}, body, search=False)
                st = self.save_state(last_published_ts=now, last_published_at=_iso(now), last_hash=digest,
                                     last_coding=coding, last_publish_error=None)
            except SocialError as exc:
                self.save_state(last_publish_error=str(exc))
                self.last_error = str(exc)
                return {"published": False, "reason": exc.code, "error": str(exc)}
            self.changed("profile", published=True)
            return {"published": True, "gist_id": st.get("gist_id"), "gist_url": st.get("gist_url")}

    async def _ensure_gist(self, st: dict, body: str, search: bool = True) -> tuple[str, bool]:
        """(gist id, created now). Uses the remembered id; otherwise adopts an existing
        neovarch-profile.json gist of this user, or creates the public gist once."""
        gid = st.get("gist_id")
        if gid:
            return gid, False
        if search:
            for g in await self.gh.get_all("/gists", pages=3, ttl=0):
                if isinstance(g, dict) and GIST_FILE in (g.get("files") or {}):
                    self.save_state(gist_id=g["id"], gist_url=g.get("html_url"))
                    return g["id"], False
        _, g = await self.gh.send("POST", "/gists", {"description": "Neovarch profile (dibuat otomatis oleh Neovarch Agent)",
                                                     "public": True, "files": {GIST_FILE: {"content": body}}})
        self.save_state(gist_id=g["id"], gist_url=g.get("html_url"))
        return g["id"], True

    # ---- friends ----------------------------------------------------------------
    async def _follow_sets(self) -> tuple[set[str], set[str]]:
        following = {u["login"] for u in await self.gh.get_all("/user/following") if isinstance(u, dict)}
        followers = {u["login"] for u in await self.gh.get_all("/user/followers") if isinstance(u, dict)}
        return following, followers

    async def friend_profile(self, login: str) -> dict | None:
        try:
            gists = await self.gh.get(f"/users/{login}/gists", params={"per_page": 100})
        except SocialError as exc:
            if exc.code == "not_found":
                return None
            raise
        for g in gists or []:
            f = (g.get("files") or {}).get(GIST_FILE) if isinstance(g, dict) else None
            if f and f.get("raw_url"):
                try:
                    text = await self.gh.get(f["raw_url"], raw=True)
                    data = json.loads(text)
                except (SocialError, json.JSONDecodeError, TypeError):
                    return None
                if isinstance(data, dict) and str(data.get("schema", "")).startswith("neovarch-profile/"):
                    data["gist_url"] = g.get("html_url")
                    return data
        return None

    def card(self, login: str, base: dict, prof: dict | None) -> dict:
        status = (prof or {}).get("status") or {}
        last = status.get("last_active_at")
        updated = _parse_iso((prof or {}).get("updated_at"))
        # a stale "coding" (publisher went offline) is not "lagi ngoding"
        coding = bool(status.get("coding")) and (time.time() - max(_parse_iso(last), updated)) < 2 * ACTIVE_WINDOW + PUBLISH_EVERY
        return {"login": login, "name": (prof or {}).get("name") or base.get("name") or login,
                "avatar_url": (prof or {}).get("avatar_url") or base.get("avatar_url"),
                "html_url": base.get("html_url") or f"https://github.com/{login}",
                "bio": (prof or {}).get("bio") or "", "has_neovarch": prof is not None,
                "coding": coding, "project": status.get("project") if coding else None,
                "last_active_at": last, "updated_at": (prof or {}).get("updated_at"),
                "top_stack": [s.get("name") for s in ((prof or {}).get("stack") or {}).get("languages", [])[:3]]}

    async def friends(self) -> dict:
        if not self.token():
            return {"signed_in": False, "friends": [], "pending": []}
        following_list = await self.gh.get_all("/user/following")
        followers = {u["login"] for u in await self.gh.get_all("/user/followers") if isinstance(u, dict)}
        by_login = {u["login"]: u for u in following_list if isinstance(u, dict)}
        mutual = [l for l in by_login if l in followers]
        sem = asyncio.Semaphore(6)

        async def one(login: str) -> dict:
            async with sem:
                try:
                    prof = await self.friend_profile(login)
                except SocialError:
                    prof = None
                return self.card(login, by_login[login], prof)

        cards = await asyncio.gather(*(one(l) for l in mutual[:200]))
        cards.sort(key=lambda c: (not c["coding"], not c["has_neovarch"], -_parse_iso(c["last_active_at"]), c["login"].lower()))
        pending = [{"login": l, "avatar_url": by_login[l].get("avatar_url")} for l in by_login if l not in followers][:100]
        return {"signed_in": True, "friends": cards, "pending": pending,
                "counts": {"friends": len(cards), "coding": sum(1 for c in cards if c["coding"]),
                           "following": len(by_login), "followers": len(followers)}}

    async def friend_detail(self, login: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login or ""):
            raise SocialError("Username GitHub tidak valid.", 422, "bad_login")
        base = await self.gh.get(f"/users/{login}", ttl=3600)
        prof = await self.friend_profile(login)
        following, followers = await self._follow_sets() if self.token() else (set(), set())
        card = self.card(login, base or {}, prof)
        card.update({"bio": (prof or {}).get("bio") or (base or {}).get("bio") or "",
                     "name": (prof or {}).get("name") or (base or {}).get("name") or login,
                     "mutual": login in following and login in followers, "following": login in following,
                     "follows_you": login in followers, "profile": prof})
        return card

    async def search(self, q: str) -> dict:
        q = (q or "").strip()
        if not q:
            return {"items": []}
        if re.fullmatch(r"[A-Za-z0-9-]{1,39}", q):
            try:
                exact = await self.gh.get(f"/users/{q}", ttl=3600)
            except SocialError:
                exact = None
        else:
            exact = None
        res = await self.gh.get("/search/users", params={"q": f"{q} in:login", "per_page": 10}, ttl=600)
        items = [u for u in (res or {}).get("items", []) if isinstance(u, dict)]
        if exact and all(u.get("login", "").lower() != exact.get("login", "").lower() for u in items):
            items.insert(0, exact)
        following, followers = await self._follow_sets() if self.token() else (set(), set())
        return {"items": [{"login": u["login"], "avatar_url": u.get("avatar_url"), "html_url": u.get("html_url"),
                           "following": u["login"] in following, "follows_you": u["login"] in followers}
                          for u in items[:10]]}

    async def follow(self, login: str, on: bool) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login or ""):
            raise SocialError("Username GitHub tidak valid.", 422, "bad_login")
        if not self.token():
            raise SocialError("Belum masuk dengan GitHub.", 401, "signed_out")
        await self.gh.send("PUT" if on else "DELETE", f"/user/following/{login}")
        self.gh.invalidate("/user/following")
        self.gh.invalidate("/user/followers")
        following, followers = await self._follow_sets()
        self.changed("friends", login=login, following=on)
        return {"ok": True, "login": login, "following": login in following, "follows_you": login in followers,
                "mutual": login in following and login in followers}

    # ---- device flow ----------------------------------------------------------
    async def login_start(self, force: bool = False) -> dict:
        """Start the GitHub device flow on this PC (desktop button or the paired
        phone's "Masuk GitHub di PC"). Idempotent unless ``force``: signed in →
        ``{state: done}``; a flow already pending → the same code, so a tap on
        the phone never invalidates the code the desktop is showing."""
        if not force:
            if self.token():
                return {"state": "done", "login": self.state().get("login")}
            cur = self.login_state
            if (cur.get("state") == "pending" and float(cur.get("expires_at") or 0) > time.time() + 30
                    and self._login_task is not None and not self._login_task.done()):
                return self.public_login()
        cid = self.client_id()
        if not cid:
            raise SocialError("Client ID OAuth App GitHub belum diatur (Pengaturan → Profil & Teman, "
                              "atau env NEOVARCH_GITHUB_CLIENT_ID).", 409, "no_client_id")
        res = await self.gh.oauth_post("/login/device/code", {"client_id": cid, "scope": SCOPES})
        if res.get("error"):
            raise SocialError(f"GitHub menolak: {res.get('error_description') or res['error']}", 400, str(res["error"]))
        self.login_state = {"state": "pending", "user_code": res.get("user_code"),
                            "verification_uri": res.get("verification_uri") or "https://github.com/login/device",
                            "expires_at": time.time() + float(res.get("expires_in") or 900),
                            "interval": max(int(res.get("interval") or 5), 1)}
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()
        self._login_task = asyncio.get_running_loop().create_task(self._poll(cid, str(res.get("device_code") or "")))
        self.changed("login", state="pending")
        return self.public_login()

    def public_login(self) -> dict:
        st = {k: v for k, v in self.login_state.items() if k != "device_code"}
        return st

    async def _poll(self, cid: str, device_code: str) -> None:
        interval = float(self.login_state.get("interval") or 5)
        if os.environ.get("NEOVARCH_SOCIAL_FAST_POLL") == "1":
            interval = 0.05
        while time.time() < float(self.login_state.get("expires_at") or 0):
            await asyncio.sleep(interval)
            try:
                res = await self.gh.oauth_post("/login/oauth/access_token", {
                    "client_id": cid, "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            except SocialError:
                continue
            err = res.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval = float(res.get("interval") or interval + 5) if os.environ.get("NEOVARCH_SOCIAL_FAST_POLL") != "1" else interval
                continue
            if err:
                self.login_state = {"state": "error", "error": "Kode kedaluwarsa, ulangi." if err == "expired_token"
                                    else ("Akses ditolak." if err == "access_denied" else str(res.get("error_description") or err))}
                self.changed("login", state="error")
                return
            token = str(res.get("access_token") or "")
            if token:
                self.tokens.set(token)
                self._token = token
                self.gh.cache.clear()
                try:
                    me = await self.me()
                except SocialError:
                    me = {}
                self.save_state(login=me.get("login"), scopes=res.get("scope"))
                self.login_state = {"state": "done", "login": me.get("login")}
                self.changed("login", state="done")
                self.kick()
                return
        self.login_state = {"state": "error", "error": "Kode kedaluwarsa, ulangi."}
        self.changed("login", state="error")

    def logout(self) -> dict:
        self.tokens.clear()
        self._token = ""
        self.gh.cache.clear()
        self.login_state = {"state": "idle"}
        self.save_state(login=None)
        self.changed("login", state="signed_out")
        return {"ok": True}

    def overview(self) -> dict:
        st = self.state()
        return {"signed_in": bool(self.token()), "login": st.get("login") if self.token() else None,
                "client_id_configured": bool(self.client_id()), "client_id_source": self.client_id_source(), "login_flow": self.public_login(),
                "token_storage": self.tokens.backend, "settings": self.settings(),
                "rate": self.gh.rate, "backoff_until": self.gh.backoff_until or None,
                "gist_id": st.get("gist_id"), "gist_url": st.get("gist_url"),
                "last_published_at": st.get("last_published_at"), "last_error": st.get("last_publish_error")}

    # ---- RPC + HTTP ---------------------------------------------------------------
    async def rpc(self, method: str, p: dict) -> Any:
        from neovarch.server import RpcError
        try:
            if method == "social.status":
                return self.overview()
            if method == "social.profile":
                return await self.build_profile()
            if method == "social.friends":
                return await self.friends()
            if method == "social.friend":
                return await self.friend_detail(str(p.get("login") or ""))
            if method == "social.search":
                return await self.search(str(p.get("q") or ""))
            if method == "social.follow":
                return await self.follow(str(p.get("login") or ""), True)
            if method == "social.unfollow":
                return await self.follow(str(p.get("login") or ""), False)
            if method == "social.settings":
                return self.save_settings(p) if p else self.settings()
            if method == "social.publish":
                return await self.maybe_publish(force=True)
            if method == "social.login.start":
                return await self.login_start(force=bool(p.get("force")))
            if method == "social.login.state":
                return self.public_login()
            if method == "social.logout":
                return self.logout()
            if method == "social.activity":
                self.editor_heartbeat(str(p.get("project") or ""))
                return {"ok": True}
        except SocialError as exc:
            raise RpcError(-32000 - min(exc.status, 999), str(exc)) from None
        raise RpcError(-32601, f"method not implemented in the Neovarch core: {method}")

    def install_routes(self, r: web.UrlDispatcher) -> None:
        def wrap(fn):
            async def h(request):
                try:
                    return web.json_response(await fn(request), dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))
                except SocialError as exc:
                    return web.json_response({"detail": str(exc), "code": exc.code}, status=exc.status)
            return h

        async def body(request) -> dict:
            try:
                b = await request.json()
                return b if isinstance(b, dict) else {}
            except Exception:
                return {}

        async def status(_):
            return self.overview()

        async def profile(_):
            return await self.build_profile()

        async def friends(_):
            return await self.friends()

        async def friend(request):
            return await self.friend_detail(request.match_info["login"])

        async def search(request):
            return await self.search(request.query.get("q") or "")

        async def follow(request):
            return await self.follow(str((await body(request)).get("login") or request.match_info.get("login") or ""), True)

        async def unfollow(request):
            return await self.follow(request.match_info["login"], False)

        async def settings_get(_):
            return self.settings()

        async def settings_put(request):
            return self.save_settings(await body(request))

        async def publish(_):
            return await self.maybe_publish(force=True)

        async def login_start(request):
            return await self.login_start(force=bool((await body(request)).get("force")))

        async def login_get(_):
            return self.public_login()

        async def logout(_):
            return self.logout()

        async def activity(request):
            self.editor_heartbeat(str((await body(request)).get("project") or ""))
            return {"ok": True}

        r.add_get("/api/social/status", wrap(status))
        r.add_get("/api/social/profile", wrap(profile))
        r.add_get("/api/social/friends", wrap(friends))
        r.add_get("/api/social/friends/{login}", wrap(friend))
        r.add_get("/api/social/search", wrap(search))
        r.add_post("/api/social/follow", wrap(follow))
        r.add_put("/api/social/follow/{login}", wrap(follow))
        r.add_delete("/api/social/follow/{login}", wrap(unfollow))
        r.add_get("/api/social/settings", wrap(settings_get))
        r.add_put("/api/social/settings", wrap(settings_put))
        r.add_post("/api/social/settings", wrap(settings_put))
        r.add_post("/api/social/publish", wrap(publish))
        r.add_post("/api/social/login", wrap(login_start))
        r.add_get("/api/social/login", wrap(login_get))
        r.add_post("/api/social/logout", wrap(logout))
        r.add_post("/api/social/activity", wrap(activity))
