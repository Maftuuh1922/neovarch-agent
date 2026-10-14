"""`neovarch update` (neovarch/pull_update.py): git and release paths with mocked git/subprocess/network."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from neovarch import cli, pull_update
from neovarch.pull_update import Ctx, UpdateError

OLD = "a" * 40
NEW = "b" * 40


class FakeGit:
    """Answers the git/pip/npm commands pull_update runs, and records them."""

    def __init__(self, root: Path, *, dirty: str = "", branch: str = "main", upstream: str = "origin/main",
                 ahead: int = 0, behind: int = 2, fetch_rc: int = 0, merge_rc: int = 0, pip_rc: int = 0,
                 npm_rc: int = 0, lock_changed: bool = False, toplevel: bool = True):
        self.root, self.dirty, self.branch, self.upstream = root, dirty, branch, upstream
        self.ahead, self.behind, self.fetch_rc, self.merge_rc = ahead, behind, fetch_rc, merge_rc
        self.pip_rc, self.npm_rc, self.lock_changed, self.toplevel = pip_rc, npm_rc, lock_changed, toplevel
        self.head = OLD
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *, cwd=None, timeout=0, env=None):
        self.calls.append(list(cmd))
        ok = lambda out="": subprocess.CompletedProcess(cmd, 0, out, "")  # noqa: E731
        bad = lambda rc, err="boom": subprocess.CompletedProcess(cmd, rc, "", err)  # noqa: E731
        if cmd[0] != "git":
            if "pip" in cmd:
                return ok("installed") if self.pip_rc == 0 else bad(self.pip_rc, "pip exploded")
            if cmd[1:2] == ["install"]:  # npm
                return ok("added 3 packages") if self.npm_rc == 0 else bad(self.npm_rc)
            return ok()
        a = cmd[1:]
        if a[:2] == ["rev-parse", "--show-toplevel"]:
            return ok(str(self.root) + "\n") if self.toplevel else bad(128, "not a git repository")
        if a[:2] == ["rev-parse", "--abbrev-ref"] and a[-1] == "HEAD":
            return ok(self.branch + "\n")
        if a[:2] == ["rev-parse", "--abbrev-ref"] and a[-1] == "@{u}":
            return ok(self.upstream + "\n") if self.upstream else bad(128, "no upstream")
        if a == ["rev-parse", "HEAD"]:
            return ok(self.head + "\n")
        if a[0] == "status":
            return ok(self.dirty)
        if a[0] == "fetch":
            return ok() if self.fetch_rc == 0 else bad(self.fetch_rc, "could not resolve host")
        if a[0] == "rev-list":
            return ok(f"{self.ahead}\t{self.behind}\n")
        if a[0] == "log":
            return ok("bbbbbbb fix: something\nccccccc feat: more\n")
        if a[0] == "merge":
            if self.merge_rc:
                return bad(self.merge_rc, "Not possible to fast-forward")
            self.head = NEW
            return ok()
        if a[0] == "diff":
            return ok("desktop/package-lock.json\n" if self.lock_changed else "")
        if a[0] == "reset":
            self.head = a[-1]
            return ok()
        return ok()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "clone"
    (root / "core" / "neovarch").mkdir(parents=True)
    (root / "core" / "neovarch" / "__init__.py").write_text("")
    return root


def ctx_for(git, *, extras=None, restart=None, which=None, **kw):
    events = []
    c = Ctx(run=git, progress=events.append, which=which or (lambda n: f"/usr/bin/{n}" if n in ("git", "npm") else None),
            ensure_extras=extras or (lambda: [{"name": "obsidian", "label": "Obsidian", "status": "present"}]),
            restart=restart or (lambda: {"requested": True}), python="/venv/bin/python", **kw)
    return c, events


def steps(events):
    return {e["step"]: e["status"] for e in events if e.get("kind") == "step"}


# ------------------------------------------------------------------ detect --

def test_find_repo_requires_the_neovarch_tree(repo, tmp_path):
    git = FakeGit(repo)
    assert pull_update.find_repo(Ctx(run=git)) == repo
    other = tmp_path / "other"
    other.mkdir()
    assert pull_update.find_repo(Ctx(run=FakeGit(other))) is None  # some other project's git tree
    assert pull_update.find_repo(Ctx(run=FakeGit(repo, toplevel=False))) is None


def test_find_repo_without_git_binary(repo):
    def missing(*_a, **_k):
        raise FileNotFoundError("git")
    assert pull_update.find_repo(Ctx(run=missing)) is None


def test_detect_git_reports_branch_head_dirty(repo, home):
    info = pull_update.detect(Ctx(run=FakeGit(repo, dirty=" M core/neovarch/agent.py\n")))
    assert info["kind"] == "git" and info["branch"] == "main" and info["upstream"] == "origin/main"
    assert info["head"] == OLD and info["dirty"] == ["core/neovarch/agent.py"]


def test_detect_non_git_kinds(home, monkeypatch, tmp_path):
    nogit = FakeGit(tmp_path, toplevel=False)
    assert pull_update.detect(Ctx(run=nogit, platform="linux"))["kind"] == "package"
    core = home / "neovarch-agent"
    core.mkdir(parents=True)
    monkeypatch.setattr(pull_update, "package_dir", lambda: core)
    assert pull_update.detect(Ctx(run=nogit, platform="linux"))["kind"] == "installer"
    assert pull_update.detect(Ctx(run=nogit, platform="win32"))["kind"] == "installer-windows"


# ---------------------------------------------------------------- git path --

def test_git_update_fast_forwards_reinstalls_and_restarts(repo, home):
    git = FakeGit(repo)
    ctx, events = ctx_for(git)
    res = pull_update.run(ctx)
    assert res["updated"] and res["old"] == OLD and res["new"] == NEW and res["deps"] == ["python"]
    assert res["restart"] == {"requested": True}
    assert res["extras"][0]["status"] == "present"
    assert steps(events) == {"detect": "done", "clean": "done", "fetch": "done", "pull": "done",
                             "deps": "done", "extras": "done", "restart": "done"}
    assert ["git", "merge", "--ff-only", "--quiet", "@{u}"] in git.calls
    assert ["git", "fetch", "--quiet", "origin"] in git.calls
    pip = next(c for c in git.calls if "pip" in c)
    assert pip[:4] == ["/venv/bin/python", "-m", "pip", "install"] and pip[-1].endswith("core")
    st = pull_update.read_state()
    assert st["prev"] == OLD and st["new"] == NEW and st["status"] == "updated"


def test_git_update_uses_uv_when_present(repo, home):
    git = FakeGit(repo)
    ctx, _ = ctx_for(git, which=lambda n: f"/bin/{n}")
    pull_update.run(ctx)
    pip = next(c for c in git.calls if "pip" in c)
    assert pip[:3] == ["/bin/uv", "pip", "install"] and "--python" in pip


def test_dirty_tree_is_refused_before_fetch(repo, home):
    git = FakeGit(repo, dirty=" M core/neovarch/cli.py\n M README.md\n")
    ctx, events = ctx_for(git)
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_DIRTY and "core/neovarch/cli.py" in ei.value.message
    assert "stash" in ei.value.message
    assert not any(c[:2] == ["git", "fetch"] for c in git.calls)
    assert not any(c[:2] == ["git", "merge"] for c in git.calls)
    assert steps(events)["clean"] == "failed"


@pytest.mark.parametrize("kw,code", [
    ({"branch": "HEAD"}, pull_update.ERR_DETACHED),
    ({"upstream": ""}, pull_update.ERR_NO_UPSTREAM),
    ({"fetch_rc": 128}, pull_update.ERR_FETCH),
    ({"ahead": 1, "behind": 3}, pull_update.ERR_DIVERGED),
    ({"merge_rc": 1}, pull_update.ERR_MERGE),
])
def test_git_refusals_have_stable_codes(repo, home, kw, code):
    git = FakeGit(repo, **kw)
    ctx, _ = ctx_for(git)
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == code
    assert not any(c[:2] == ["git", "reset"] for c in git.calls)  # nothing changed, nothing to undo
    assert git.head == OLD


def test_up_to_date_still_runs_extras_but_not_restart(repo, home):
    git = FakeGit(repo, behind=0)
    ran = []
    ctx, events = ctx_for(git, extras=lambda: ran.append(1) or [], restart=lambda: pytest.fail("no restart"))
    res = pull_update.run(ctx)
    assert res["up_to_date"] and not res["updated"] and ran == [1]
    assert steps(events)["pull"] == "skipped" and steps(events)["restart"] == "skipped"
    assert not any("pip" in c for c in git.calls)


def test_check_only_does_not_merge(repo, home):
    git = FakeGit(repo, behind=4)
    ctx, _ = ctx_for(git, extras=lambda: pytest.fail("no extras on --check"))
    res = pull_update.run(ctx, check_only=True)
    assert res["available"] and res["behind"] == 4
    assert not any(c[:2] == ["git", "merge"] for c in git.calls)


def test_python_deps_failure_rolls_back_to_previous_commit(repo, home):
    git = FakeGit(repo, pip_rc=1)
    ctx, events = ctx_for(git, extras=lambda: pytest.fail("no extras after a failed update"))
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_DEPS and ei.value.rolled_back
    assert "pip exploded" in ei.value.message and OLD[:10] in ei.value.message
    assert ["git", "reset", "--keep", OLD] in git.calls and git.head == OLD
    assert pull_update.read_state()["status"] == "rolled_back"
    assert steps(events)["deps"] == "failed"


def test_desktop_deps_only_when_lockfile_changed_and_node_modules_exist(repo, home):
    (repo / "desktop" / "node_modules").mkdir(parents=True)
    git = FakeGit(repo, lock_changed=True)
    ctx, _ = ctx_for(git)
    res = pull_update.run(ctx)
    assert res["deps"] == ["python", "desktop"]
    assert ["/usr/bin/npm", "install", "--no-audit", "--no-fund"] in git.calls

    git2 = FakeGit(repo, lock_changed=False)
    ctx2, _ = ctx_for(git2)
    assert pull_update.run(ctx2)["deps"] == ["python"]


def test_desktop_npm_failure_rolls_back(repo, home):
    (repo / "desktop" / "node_modules").mkdir(parents=True)
    git = FakeGit(repo, lock_changed=True, npm_rc=1)
    ctx, _ = ctx_for(git)
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_DEPS and ei.value.rolled_back and git.head == OLD


def test_interrupt_during_deps_rolls_back(repo, home):
    git = FakeGit(repo)
    real = git.__call__

    def run(cmd, **kw):
        if "pip" in cmd and git.head == NEW:
            raise KeyboardInterrupt
        return real(cmd, **kw)
    ctx, _ = ctx_for(run)
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_ABORTED and ei.value.rolled_back and git.head == OLD


def test_no_deps_flag_skips_install(repo, home):
    git = FakeGit(repo)
    ctx, events = ctx_for(git)
    pull_update.run(ctx, deps=False)
    assert not any("pip" in c for c in git.calls) and steps(events)["deps"] == "skipped"


def test_extras_failure_never_fails_the_update(repo, home):
    git = FakeGit(repo)

    def broken():
        raise RuntimeError("github down")
    ctx, events = ctx_for(git, extras=broken)
    res = pull_update.run(ctx)
    assert res["updated"] and steps(events)["extras"] == "warning"


def test_manual_rollback_after_update(repo, home):
    git = FakeGit(repo)
    ctx, _ = ctx_for(git)
    pull_update.run(ctx)
    assert git.head == NEW
    res = pull_update.rollback(Ctx(run=git, which=lambda n: None, python="/venv/bin/python"))
    assert res["rolled_back"] and git.head == OLD
    git.head = "c" * 40  # moved on since: refuse
    pull_update.write_state({"kind": "git", "prev": OLD, "new": NEW})
    with pytest.raises(UpdateError) as ei:
        pull_update.rollback(Ctx(run=git))
    assert ei.value.code == pull_update.ERR_NO_ROLLBACK


def test_rollback_without_state(repo, home):
    with pytest.raises(UpdateError) as ei:
        pull_update.rollback(Ctx(run=FakeGit(repo)))
    assert ei.value.code == pull_update.ERR_NO_ROLLBACK


# ------------------------------------------------------------ release path --

RELEASE = {"tag_name": "v9.9.9", "name": "Neovarch Agent 9.9.9", "html_url": "https://github.com/x/y/releases/tag/v9.9.9",
           "assets": [{"name": "neovarch-agent-linux-x64.tar.gz", "browser_download_url": "https://dl/linux.tgz"},
                      {"name": "neovarch-agent-windows-x64-setup.exe", "browser_download_url": "https://dl/setup.exe"}]}


def _installer_home(home, monkeypatch):
    core = home / "neovarch-agent"
    core.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pull_update, "package_dir", lambda: core)


def test_release_fallback_runs_official_installer_for_the_tag(home, monkeypatch, tmp_path):
    _installer_home(home, monkeypatch)
    git = FakeGit(tmp_path, toplevel=False)
    downloads = []
    ctx, events = ctx_for(git, fetch_release=lambda: RELEASE, platform="linux",
                          download=lambda url, dest: downloads.append(url) or dest.write_text("#!/bin/sh\n"))
    seen_env = {}
    real = git.__call__

    def run(cmd, **kw):
        if cmd[0] == "sh":
            seen_env.update(kw.get("env") or {})
        return real(cmd, **kw)
    ctx.run = run
    res = pull_update.run(ctx)
    assert res["updated"] and res["latest"] == "9.9.9" and res["kind"] == "installer"
    assert downloads == [pull_update.INSTALL_SH]
    assert seen_env["NEOVARCH_VERSION"] == "v9.9.9"
    assert steps(events) == {"detect": "done", "check": "done", "install": "done", "extras": "done", "restart": "done"}


def test_release_fallback_windows_uses_install_ps1(home, monkeypatch, tmp_path):
    _installer_home(home, monkeypatch)
    cmd, env = pull_update.installer_command("installer-windows", tmp_path / "install.ps1", "9.9.9")
    assert cmd[0] == "powershell" and cmd[-1].endswith("install.ps1") and env["NEOVARCH_VERSION"] == "v9.9.9"
    git = FakeGit(tmp_path, toplevel=False)
    urls = []
    ctx, _ = ctx_for(git, fetch_release=lambda: RELEASE, platform="win32",
                     download=lambda url, dest: urls.append(url) or dest.write_text(""))
    assert pull_update.run(ctx)["updated"] and urls == [pull_update.INSTALL_PS1]
    assert any(c[0] == "powershell" for c in git.calls)


def test_release_installer_failure_keeps_old_version(home, monkeypatch, tmp_path):
    _installer_home(home, monkeypatch)
    git = FakeGit(tmp_path, toplevel=False)

    def run(cmd, **kw):
        if cmd[0] == "sh":
            return subprocess.CompletedProcess(cmd, 1, "", "no network")
        return git(cmd, **kw)
    ctx, _ = ctx_for(run, fetch_release=lambda: RELEASE, platform="linux",
                     download=lambda url, dest: dest.write_text(""),
                     extras=lambda: pytest.fail("no extras after a failed update"))
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_RELEASE and "versi lama" in ei.value.message


def test_release_package_install_points_to_release_page(home, tmp_path):
    git = FakeGit(tmp_path, toplevel=False)
    ctx, events = ctx_for(git, fetch_release=lambda: RELEASE, platform="linux",
                          download=lambda *_: pytest.fail("no download for a package install"))
    res = pull_update.run(ctx)
    assert res["manual"] and res["download_url"] == "https://dl/linux.tgz" and not res["updated"]
    assert steps(events)["install"] == "manual" and steps(events)["restart"] == "skipped"


def test_release_up_to_date_and_offline(home, tmp_path):
    git = FakeGit(tmp_path, toplevel=False)
    ctx, _ = ctx_for(git, fetch_release=lambda: {"tag_name": "v0.0.1"}, platform="linux")
    assert pull_update.run(ctx)["up_to_date"]

    def offline():
        raise OSError("network unreachable")
    ctx2, _ = ctx_for(git, fetch_release=offline, platform="linux")
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx2)
    assert ei.value.code == pull_update.ERR_RELEASE and "network unreachable" in ei.value.message


def test_git_missing_on_a_git_install(home, monkeypatch, tmp_path):
    root = tmp_path / "clone"
    (root / "core").mkdir(parents=True)
    (root / ".git").mkdir()
    monkeypatch.setattr(pull_update, "package_dir", lambda: root / "core")
    ctx, _ = ctx_for(FakeGit(root, toplevel=False), which=lambda n: None)
    with pytest.raises(UpdateError) as ei:
        pull_update.run(ctx)
    assert ei.value.code == pull_update.ERR_GIT_MISSING


# ------------------------------------------------------------- restart / CLI --

def test_restart_request_file(home):
    res = pull_update.request_gateway_restart()
    assert res["requested"]
    data = json.loads(pull_update.restart_request_path().read_text())
    assert data["by"] == "neovarch update" and data["ts"] > 0


async def test_gateway_watcher_restarts_on_new_request(home, monkeypatch):
    import asyncio
    from neovarch.server import Gateway
    gw = Gateway(False)
    called = []
    monkeypatch.setattr(gw, "request_restart", lambda sid="": called.append(sid))
    task = asyncio.get_running_loop().create_task(gw.watch_update_restart(interval=0.05))
    await asyncio.sleep(0.12)
    assert not called
    pull_update.request_gateway_restart()
    await asyncio.wait_for(task, 2)
    assert called == [""] and not pull_update.restart_request_path().exists()


def test_cli_update_prints_steps_and_exit_codes(repo, home, monkeypatch, capsys):
    git = FakeGit(repo)
    real_ctx = pull_update.Ctx

    def make(**kw):
        return real_ctx(run=git, which=lambda n: None, python="/venv/bin/python",
                        ensure_extras=lambda: [], restart=lambda: {"requested": True}, **kw)
    monkeypatch.setattr(pull_update, "Ctx", make)
    with pytest.raises(SystemExit) as ex:
        cli.main(["update"])
    assert ex.value.code == 0
    out = capsys.readouterr().out
    assert "git pull (fast-forward)" in out and f"{OLD[:10]} → {NEW[:10]}" in out and "2 commit" in out

    git2 = FakeGit(repo, dirty=" M x.py\n")
    monkeypatch.setattr(pull_update, "Ctx", lambda **kw: real_ctx(run=git2, which=lambda n: None, **kw))
    with pytest.raises(SystemExit) as ex:
        cli.main(["update"])
    assert ex.value.code == 1
    assert "perubahan lokal" in capsys.readouterr().err


def test_cli_update_json(repo, home, monkeypatch, capsys):
    git = FakeGit(repo, behind=0)
    real_ctx = pull_update.Ctx
    monkeypatch.setattr(pull_update, "Ctx", lambda **kw: real_ctx(run=git, which=lambda n: None,
                                                                  ensure_extras=lambda: [], **kw))
    with pytest.raises(SystemExit):
        cli.main(["update", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["up_to_date"]


async def test_api_update_pull_job(home, monkeypatch):
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from neovarch.server import Gateway, build_app
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    gw = Gateway(False)

    def fake_run(ctx, **kw):
        ctx.step("detect", "done", "git")
        ctx.line("hello")
        if kw.get("check_only"):
            return {"kind": "git", "available": True}
        raise UpdateError(pull_update.ERR_DIRTY, "Ada perubahan lokal")
    monkeypatch.setattr(pull_update, "run", fake_run)
    monkeypatch.setattr(pull_update, "detect", lambda ctx=None: {"kind": "git", "dirty": []})
    client = TestClient(TestServer(build_app(gw)))
    await client.start_server()
    try:
        h = {"Authorization": "Bearer tok"}
        r = await client.get("/api/update/pull", headers=h)
        assert (await r.json())["install"]["kind"] == "git"
        r = await client.post("/api/update/pull", json={}, headers=h)
        assert r.status == 202
        for _ in range(50):
            job = (await (await client.get("/api/update/pull", headers=h)).json())["job"]
            if job["state"] != "running":
                break
            await asyncio.sleep(0.02)
        assert job["state"] == "failed" and job["code"] == "dirty" and job["lines"] == ["hello"]
        assert job["steps"]["detect"]["status"] == "done"
        r = await client.post("/api/update/pull", json={"check_only": True}, headers=h)
        assert r.status == 202
        r = await client.get("/api/update/pull")
        assert r.status == 401
    finally:
        await client.close()
