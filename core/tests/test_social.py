"""Friends & profile via GitHub against a mocked GitHub (REST + GraphQL + OAuth device flow)."""

import asyncio
import json
import os
import stat
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from neovarch import social as socmod
from neovarch.server import Gateway, build_app

H = {"Authorization": "Bearer tok"}
BUILTIN_CLIENT_ID = socmod.DEFAULT_GITHUB_CLIENT_ID  # captured before the gh fixture clears it


class FakeGitHub:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.gists: dict[str, dict] = {}
        self.following = {"budi", "sari", "tono"}
        self.followers = {"budi", "sari", "rina"}
        self.token = "gho_secret_token_value"
        self.polls = 0
        self.rate_limited = False
        self.revoked = ""  # a token GitHub answers 401 "Bad credentials" to
        self.base = ""
        now = time.time()
        self.friend_profiles = {
            "budi": {"schema": "neovarch-profile/1", "login": "budi", "name": "Budi", "bio": "Flutter",
                     "updated_at": socmod._iso(now - 30),
                     "status": {"coding": True, "last_active_at": socmod._iso(now - 20), "project": "toko"},
                     "stack": {"languages": [{"name": "Dart", "share": 0.7}]},
                     "heatmap": {"counts": [0] * 364 + [5], "days": 365}},
        }

    def app(self):
        a = web.Application(middlewares=[self.mw])
        r = a.router
        r.add_post("/login/device/code", self.device_code)
        r.add_post("/login/oauth/access_token", self.access_token)
        r.add_get("/user", self.user)
        r.add_get("/user/repos", self.repos)
        r.add_post("/graphql", self.graphql)
        r.add_get("/gists", self.my_gists)
        r.add_post("/gists", self.create_gist)
        r.add_patch("/gists/{gid}", self.patch_gist)
        r.add_get("/user/following", self.get_following)
        r.add_get("/user/followers", self.get_followers)
        r.add_put("/user/following/{u}", self.follow)
        r.add_delete("/user/following/{u}", self.unfollow)
        r.add_get("/users/{u}/gists", self.user_gists)
        r.add_get("/users/{u}", self.user_get)
        r.add_get("/raw/{u}", self.raw)
        r.add_get("/search/users", self.search)
        return a

    @web.middleware
    async def mw(self, request, handler):
        self.calls.append((request.method, request.path))
        if self.rate_limited and request.path.startswith("/user"):
            return web.json_response({"message": "API rate limit exceeded"}, status=403,
                                     headers={"X-RateLimit-Remaining": "0",
                                              "X-RateLimit-Reset": str(int(time.time()) + 120)})
        if self.revoked and request.headers.get("Authorization") == f"Bearer {self.revoked}":
            return web.json_response({"message": "Bad credentials"}, status=401)
        if not request.path.startswith(("/login/", "/raw/")):
            assert request.headers.get("Authorization") == f"Bearer {self.token}"
        return await handler(request)

    async def device_code(self, request):
        form = await request.post()
        assert form["client_id"] == "Iv1.testclientid" and form["scope"] == "read:user gist user:follow"
        return web.json_response({"device_code": "dev-123", "user_code": "ABCD-1234",
                                  "verification_uri": "https://github.com/login/device", "expires_in": 900,
                                  "interval": 5})

    async def access_token(self, request):
        form = await request.post()
        assert form["device_code"] == "dev-123"
        self.polls += 1
        if self.polls == 1:
            return web.json_response({"error": "authorization_pending"})
        if self.polls == 2:
            return web.json_response({"error": "slow_down", "interval": 10})
        return web.json_response({"access_token": self.token, "token_type": "bearer", "scope": "gist,read:user,user:follow"})

    async def user(self, request):
        etag = '"user-v1"'
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        return web.json_response({"login": "aku", "name": "Aku Dev", "bio": "ngoding tiap hari",
                                  "avatar_url": "https://avatars.example/aku", "html_url": "https://github.com/aku",
                                  "followers": 3, "following": 3}, headers={"ETag": etag})

    async def repos(self, _):
        return web.json_response([{"language": "Python"}, {"language": "Python"}, {"language": "TypeScript"},
                                  {"language": "Go", "fork": True}, {"language": None}])

    async def graphql(self, request):
        body = await request.json()
        assert body["variables"]["login"] == "aku"
        today = time.strftime("%Y-%m-%d")
        return web.json_response({"data": {"user": {"contributionsCollection": {"contributionCalendar": {
            "weeks": [{"contributionDays": [{"date": today, "contributionCount": 4}]}]}}}}})

    async def my_gists(self, _):
        return web.json_response([g for g in self.gists.values()])

    async def create_gist(self, request):
        body = await request.json()
        assert body["public"] is True and socmod.GIST_FILE in body["files"]
        gid = f"g{len(self.gists) + 1}"
        self.gists[gid] = {"id": gid, "html_url": f"https://gist.github.com/{gid}",
                           "files": {socmod.GIST_FILE: {"content": body["files"][socmod.GIST_FILE]["content"]}}}
        return web.json_response(self.gists[gid], status=201)

    async def patch_gist(self, request):
        gid = request.match_info["gid"]
        if gid not in self.gists:
            return web.json_response({"message": "Not Found"}, status=404)
        body = await request.json()
        self.gists[gid]["files"][socmod.GIST_FILE]["content"] = body["files"][socmod.GIST_FILE]["content"]
        return web.json_response(self.gists[gid])

    async def get_following(self, request):
        return await self.people(request, self.following)

    async def get_followers(self, request):
        return await self.people(request, self.followers)

    async def people(self, request, logins):
        page = int(request.query.get("page") or 1)
        if page > 1:
            return web.json_response([])
        return web.json_response([{"login": l, "avatar_url": f"https://avatars.example/{l}",
                                   "html_url": f"https://github.com/{l}"} for l in sorted(logins)])

    async def follow(self, request):
        self.following.add(request.match_info["u"])
        return web.Response(status=204)

    async def unfollow(self, request):
        self.following.discard(request.match_info["u"])
        return web.Response(status=204)

    async def user_gists(self, request):
        u = request.match_info["u"]
        if u in self.friend_profiles:
            return web.json_response([{"id": "x", "html_url": f"https://gist.github.com/{u}/x",
                                       "files": {socmod.GIST_FILE: {"raw_url": f"{self.base}/raw/{u}"}}}],
                                     headers={"ETag": f'"g-{u}"'})
        return web.json_response([{"id": "y", "files": {"other.txt": {"raw_url": f"{self.base}/raw/none"}}}])

    async def user_get(self, request):
        u = request.match_info["u"]
        if u == "hantu":
            return web.json_response({"message": "Not Found"}, status=404)
        return web.json_response({"login": u, "name": u.title(), "bio": f"bio {u}",
                                  "avatar_url": f"https://avatars.example/{u}", "html_url": f"https://github.com/{u}"})

    async def raw(self, request):
        return web.Response(text=json.dumps(self.friend_profiles[request.match_info["u"]]), content_type="text/plain")

    async def search(self, request):
        q = request.query["q"]
        assert q.endswith(" in:login")
        return web.json_response({"items": [{"login": "rina", "avatar_url": "a"}, {"login": "rinaldi", "avatar_url": "b"}]})


@pytest.fixture
async def gh(home, monkeypatch):
    fake = FakeGitHub()
    server = TestServer(fake.app())
    await server.start_server()
    fake.base = str(server.make_url("")).rstrip("/")
    monkeypatch.setenv("NEOVARCH_GITHUB_API", fake.base)
    monkeypatch.setenv("NEOVARCH_GITHUB_OAUTH", fake.base)
    monkeypatch.setenv("NEOVARCH_SECRET_BACKEND", "file")
    monkeypatch.setenv("NEOVARCH_SOCIAL_DISABLE", "1")
    monkeypatch.setenv("NEOVARCH_SOCIAL_FAST_POLL", "1")
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.delenv("NEOVARCH_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEOVARCH_GITHUB_CLIENT_ID_DEFAULT", raising=False)
    # Most tests exercise the "no client ID yet" path; the built-in default is
    # covered by test_client_id_build_default_and_override.
    monkeypatch.setattr(socmod, "DEFAULT_GITHUB_CLIENT_ID", "")
    yield fake
    await server.close()


async def _client():
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    return gw, c


async def _login(gw, c, gh):
    r = await c.put("/api/social/settings", json={"github_client_id": "Iv1.testclientid"}, headers=H)
    assert r.status == 200
    start = await (await c.post("/api/social/login", headers=H)).json()
    assert start["state"] == "pending" and start["user_code"] == "ABCD-1234"
    assert "device_code" not in start
    for _ in range(100):
        st = await (await c.get("/api/social/login", headers=H)).json()
        if st["state"] != "pending":
            break
        await asyncio.sleep(0.05)
    assert st == {"state": "done", "login": "aku"}


async def test_device_flow_token_storage_and_logout(gh, home):
    gw, c = await _client()
    try:
        assert (await c.get("/api/social/status")).status == 401
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["signed_in"] is False and st["client_id_configured"] is False
        r = await c.post("/api/social/login", headers=H)
        assert r.status == 409 and (await r.json())["code"] == "no_client_id"
        await _login(gw, c, gh)
        assert gh.polls == 3  # pending, slow_down, token
        f = home / "secrets" / "github_token"
        assert f.read_text() == gh.token and stat.S_IMODE(os.stat(f).st_mode) == 0o600
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["signed_in"] and st["login"] == "aku" and st["token_storage"] == "file"
        assert gh.token not in json.dumps(st)
        assert gh.token not in (home / "social" / "state.json").read_text()
        await c.post("/api/social/logout", headers=H)
        assert not f.exists()
        assert (await (await c.get("/api/social/status", headers=H)).json())["signed_in"] is False
    finally:
        await c.close()


async def test_client_id_from_env(gh, monkeypatch):
    monkeypatch.setenv("NEOVARCH_GITHUB_CLIENT_ID", "Iv1.testclientid")
    gw, c = await _client()
    try:
        r = await (await c.post("/api/social/login", headers=H)).json()
        assert r["user_code"] == "ABCD-1234"
    finally:
        await c.close()


def _seed_sessions(gw):
    rec = gw.store.create(source="desktop", cwd="/home/aku/proyek-keren")
    now = time.time()
    # "today" but outside the 10-minute "coding now" window (stays on today's date
    # when the test runs shortly after local midnight)
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    today = max(now - 3600, midnight + 1)
    rec["messages"] = [
        {"role": "user", "content": "bikin api", "ts": today},
        {"role": "assistant", "content": None, "ts": today + 1, "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "app/main.py"})}},
            {"id": "2", "type": "function", "function": {"name": "edit_file", "arguments": json.dumps({"path": "web/App.tsx"})}},
            {"id": "3", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"command": "pytest"})}}]},
        {"role": "user", "content": "lama", "ts": now - 400 * 86400},
    ]
    gw.store.save(rec)
    return rec


async def test_profile_heatmap_stack_status(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        _seed_sessions(gw)
        gw.social._stats = None
        p = await (await c.get("/api/social/profile", headers=H)).json()
        assert p["login"] == "aku" and p["bio"] == "ngoding tiap hari" and p["avatar_url"].endswith("/aku")
        hm = p["heatmap"]
        assert hm["days"] == 365 and len(hm["counts"]) == 365
        assert hm["agent"][-1] == 4  # 1 user msg + 3 tool calls today (the 400-day-old one is out)
        assert hm["github"][-1] == 4 and hm["counts"][-1] == 8 and hm["streak"] >= 1
        langs = {s["name"]: s for s in p["stack"]["languages"]}
        assert {"Python", "TypeScript"} <= set(langs) and langs["Python"]["source"] == "both"
        assert "Go" not in langs  # forks do not count
        assert [t["name"] for t in p["stack"]["tools"]][:1] in (["edit_file"], ["shell"], ["write_file"])
        # last activity was an hour ago -> not coding
        assert p["status"]["coding"] is False and p["status"]["project"] is None
        gw.social.editor_heartbeat("neovarch")
        p = await (await c.get("/api/social/profile", headers=H)).json()
        assert p["status"]["coding"] is True and p["status"]["project"] is None  # opt-in only
        await c.put("/api/social/settings", json={"share_project": True}, headers=H)
        p = await (await c.get("/api/social/profile", headers=H)).json()
        assert p["status"]["project"] == "neovarch"
        # conditional request: /user answered 304 from the ETag once the cache is stale
        for v in gw.social.gh.cache.values():
            v["ts"] = 0
        await c.get("/api/social/profile", headers=H)
        assert gh.calls.count(("GET", "/user")) >= 2
    finally:
        await c.close()


async def test_publish_gist_once_throttle_and_privacy(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        _seed_sessions(gw)
        r = await (await c.post("/api/social/publish", headers=H)).json()
        assert r["published"] and r["gist_id"] == "g1"
        doc = json.loads(gh.gists["g1"]["files"][socmod.GIST_FILE]["content"])
        assert doc["schema"] == "neovarch-profile/1" and doc["login"] == "aku"
        assert len(doc["heatmap"]["counts"]) == 365 and doc["stack"]["languages"] and "status" in doc
        assert "settings" not in doc and "followers" not in doc
        # throttled: not again within 5 minutes without a status change
        r2 = await gw.social.maybe_publish()
        assert r2["published"] is False and r2["reason"] == "throttled"
        # status change publishes early (after the 30 s guard)
        gw.social.save_state(last_published_ts=time.time() - 40)
        gw.social.editor_heartbeat("x")
        r3 = await gw.social.maybe_publish()
        assert r3["published"] is True
        assert json.loads(gh.gists["g1"]["files"][socmod.GIST_FILE]["content"])["status"]["coding"] is True
        assert ("POST", "/gists") in gh.calls and gh.calls.count(("POST", "/gists")) == 1
        assert ("PATCH", "/gists/g1") in gh.calls
        # privacy toggles drop the sections
        await c.put("/api/social/settings", json={"publish_heatmap": False, "publish_stack": False,
                                                    "publish_status": False}, headers=H)
        await c.post("/api/social/publish", headers=H)
        doc = json.loads(gh.gists["g1"]["files"][socmod.GIST_FILE]["content"])
        assert "heatmap" not in doc and "stack" not in doc and "status" not in doc
        # pause stops automatic publishing
        await c.put("/api/social/settings", json={"paused": True}, headers=H)
        gw.social.save_state(last_published_ts=0)
        assert (await gw.social.maybe_publish())["reason"] == "paused"
        # the remembered id survives a restart; an existing gist is adopted, never duplicated
        gw2 = Gateway(isolated=False)
        gw2.social.save_state(gist_id=None)
        await c.put("/api/social/settings", json={"paused": False}, headers=H)
        res = await gw2.social.maybe_publish(force=True)
        assert res["gist_id"] == "g1" and len(gh.gists) == 1
        await gw2.social.gh.close()
    finally:
        await c.close()


async def test_friends_are_mutual_follows_sorted_coding_first(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        fr = await (await c.get("/api/social/friends", headers=H)).json()
        logins = [f["login"] for f in fr["friends"]]
        assert logins == ["budi", "sari"]  # tono: not following back; rina: we do not follow
        assert fr["friends"][0]["coding"] is True and fr["friends"][0]["project"] == "toko"
        assert fr["friends"][0]["has_neovarch"] and fr["friends"][1]["has_neovarch"] is False
        assert [p["login"] for p in fr["pending"]] == ["tono"]
        d = await (await c.get("/api/social/friends/budi", headers=H)).json()
        assert d["mutual"] and d["profile"]["stack"]["languages"][0]["name"] == "Dart"
        s = await (await c.get("/api/social/search?q=rina", headers=H)).json()
        assert s["items"][0]["login"] == "rina" and s["items"][0]["follows_you"] is True
        # add friend = follow -> mutual right away (rina already follows us)
        r = await (await c.post("/api/social/follow", json={"login": "rina"}, headers=H)).json()
        assert r["mutual"] is True and ("PUT", "/user/following/rina") in gh.calls
        fr = await (await c.get("/api/social/friends", headers=H)).json()
        assert "rina" in [f["login"] for f in fr["friends"]]
        # unfriend = unfollow
        r = await (await c.delete("/api/social/follow/rina", headers=H)).json()
        assert r["following"] is False
        assert (await c.post("/api/social/follow", json={"login": "bad/../x"}, headers=H)).status == 422
    finally:
        await c.close()


async def test_cache_and_rate_limit_backoff(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        await c.get("/api/social/friends", headers=H)
        n = len(gh.calls)
        await c.get("/api/social/friends", headers=H)
        assert len(gh.calls) == n  # all served from the 5-minute cache
        for v in gw.social.gh.cache.values():
            v["ts"] = 0
        gh.rate_limited = True
        fr = await (await c.get("/api/social/friends", headers=H)).json()
        assert [f["login"] for f in fr["friends"]] == ["budi", "sari"]  # stale cache served
        assert gw.social.gh.backoff_until > time.time() + 60
        m = len(gh.calls)
        await c.get("/api/social/friends", headers=H)
        assert len(gh.calls) == m  # backing off: no requests at all
        r = await c.post("/api/social/follow", json={"login": "x"}, headers=H)
        assert r.status == 429 and (await r.json())["code"] == "rate_limited"
    finally:
        await c.close()


async def test_social_changed_event_and_rpc(gh, home):
    gw, c = await _client()
    try:
        ws = await c.ws_connect("/api/ws?token=tok")
        await ws.receive_json()
        await _login(gw, c, gh)
        seen = []
        while True:
            msg = await ws.receive_json(timeout=5)
            if msg.get("method") == "event" and msg["params"]["type"] == "social.changed":
                seen.append(msg["params"]["payload"]["what"])
                if msg["params"]["payload"].get("state") == "done":
                    break
        assert "login" in seen
        await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "social.friends", "params": {}})
        while True:
            msg = await ws.receive_json(timeout=5)
            if msg.get("id") == 1:
                break
        assert [f["login"] for f in msg["result"]["friends"]] == ["budi", "sari"]
        await ws.close()
    finally:
        await c.close()


def test_heatmap_shape():
    import datetime as dt
    end = dt.date(2026, 10, 9)
    hm = socmod.heatmap({"2026-10-09": 2, "2026-10-08": 1, "2025-10-10": 7, "2025-10-09": 99}, None, end=end)
    assert hm["start"] == "2025-10-10" and hm["end"] == "2026-10-09"
    assert hm["counts"][0] == 7 and hm["counts"][-1] == 2 and hm["streak"] == 2 and hm["github"] is None
    assert hm["total"] == 10 and hm["max"] == 7


async def test_client_id_build_default_and_override(gh, monkeypatch):
    """The built-in Neovarch Agent client ID works with no setup; a build-time
    default (passed by the desktop) beats it; the manual "Pakai Client ID sendiri
    (lanjutan)" field overrides both and clearing it falls back."""
    assert BUILTIN_CLIENT_ID == "Ov23li1lB513P2W10ZM7"
    monkeypatch.setattr(socmod, "DEFAULT_GITHUB_CLIENT_ID", BUILTIN_CLIENT_ID)  # the gh fixture clears it
    assert socmod.resolve_client_id() == ("Ov23li1lB513P2W10ZM7", "default")
    monkeypatch.setenv("NEOVARCH_GITHUB_CLIENT_ID_DEFAULT", "Iv1.testclientid")
    assert socmod.resolve_client_id() == ("Iv1.testclientid", "default")
    gw, c = await _client()
    try:
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["client_id_configured"] is True and st["client_id_source"] == "default"
        assert st["settings"]["github_client_id"] == ""  # the default is not echoed into the override field
        r = await (await c.post("/api/social/login", headers=H)).json()
        assert r["user_code"] == "ABCD-1234"
        saved = await (await c.put("/api/social/settings", json={"github_client_id": "Iv1.myownclient"}, headers=H)).json()
        assert saved["github_client_id"] == "Iv1.myownclient" and saved["github_client_id_source"] == "config"
        assert gw.social.client_id() == "Iv1.myownclient"
        cleared = await (await c.put("/api/social/settings", json={"github_client_id": ""}, headers=H)).json()
        assert cleared["github_client_id"] == "" and cleared["github_client_id_source"] == "default"
        assert gw.social.client_id() == "Iv1.testclientid"
    finally:
        await c.close()


def _device_codes(gh) -> int:
    return sum(1 for m, p in gh.calls if p == "/login/device/code")


async def test_phone_login_reuses_pending_flow(gh, monkeypatch):
    """The phone's "Masuk GitHub di PC" while the desktop already shows a code:
    same pending flow, no second device code (the first stays valid)."""
    monkeypatch.delenv("NEOVARCH_SOCIAL_FAST_POLL", raising=False)  # keep it pending
    gw, c = await _client()
    try:
        await c.put("/api/social/settings", json={"github_client_id": "Iv1.testclientid"}, headers=H)
        a = await (await c.post("/api/social/login", headers=H)).json()
        b = await (await c.post("/api/social/login", headers=H)).json()
        assert a["state"] == b["state"] == "pending" and a["user_code"] == b["user_code"] == "ABCD-1234"
        assert _device_codes(gh) == 1
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["login_flow"]["state"] == "pending" and st["login_flow"]["user_code"] == "ABCD-1234"
        assert "device_code" not in json.dumps(st)
        await (await c.post("/api/social/login", json={"force": True}, headers=H)).json()
        assert _device_codes(gh) == 2
    finally:
        await c.close()


async def test_login_start_when_signed_in_is_done_and_rpc_state(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        n = _device_codes(gh)
        r = await (await c.post("/api/social/login", headers=H)).json()
        assert r == {"state": "done", "login": "aku"}
        assert _device_codes(gh) == n
        assert await gw.social.rpc("social.login.start", {}) == {"state": "done", "login": "aku"}
        assert (await gw.social.rpc("social.login.state", {}))["state"] == "done"
    finally:
        await c.close()


async def test_github_rejecting_the_pc_token_is_not_a_pairing_error(gh, home):
    """Phone bug after 1.4.7: GitHub refused the PC's stored token, the core
    answered /api/social/profile with HTTP 401 and the phone (which reads every
    401 as "PC refused my pairing token") said "token ditolak oleh PC —
    pasangkan ulang" while chat on the same token was fine."""
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        events = []
        orig = gw.broadcast_event
        gw.broadcast_event = lambda kind, sid, payload: (events.append((kind, payload)), orig(kind, sid, payload))
        gh.revoked = gh.token  # token expired / revoked on GitHub
        gw.social.gh.cache.clear()
        r = await c.get("/api/social/profile", headers=H)
        assert r.status == 409  # never 401/403: the pairing token was accepted
        body = await r.json()
        assert body["code"] == "github_token_invalid" and "GitHub" in body["detail"]
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["signed_in"] is False and st["github_token_invalid"] is True
        assert gh.token not in json.dumps(st)
        assert ("social.changed", {"what": "login", "state": "token_invalid"}) in events
        r = await c.get("/api/social/friends", headers=H)
        assert r.status == 409 and (await r.json())["code"] == "github_token_invalid"
        r = await c.post("/api/social/follow", json={"login": "budi"}, headers=H)
        assert r.status == 409
        assert (await gw.social.maybe_publish(force=True))["reason"] == "github_token_invalid"
        # Not signed in any more: a plain "Masuk GitHub" starts a new device flow.
        n = _device_codes(gh)
        start = await (await c.post("/api/social/login", headers=H)).json()
        assert start["state"] == "pending" and _device_codes(gh) == n + 1
    finally:
        await c.close()


async def test_token_replaced_on_the_pc_is_picked_up_without_restart(gh, home):
    gw, c = await _client()
    try:
        await _login(gw, c, gh)
        old = gh.token
        gh.revoked = old
        gw.social.gh.cache.clear()
        assert (await c.get("/api/social/profile", headers=H)).status == 409
        # The user saves a new token on the PC (keychain / secrets file).
        gh.token = "gho_new_token_value"
        gw.social.tokens.set(gh.token)
        st = await (await c.get("/api/social/status", headers=H)).json()
        assert st["signed_in"] is True and st["github_token_invalid"] is False
        r = await c.get("/api/social/profile", headers=H)
        assert r.status == 200 and (await r.json())["login"] == "aku"
    finally:
        await c.close()


async def test_signed_out_is_409_and_bad_pairing_token_is_still_401(gh, home):
    gw, c = await _client()
    try:
        r = await c.post("/api/social/follow", json={"login": "budi"}, headers=H)
        assert r.status == 409 and (await r.json())["code"] == "signed_out"
        # The real "pasangkan ulang" case: the core's auth refuses the token, no code.
        r = await c.get("/api/social/profile", headers={"Authorization": "Bearer salah"})
        assert r.status == 401 and "code" not in await r.json()
    finally:
        await c.close()
