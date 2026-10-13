"""Optional extras (Obsidian): detection, official-asset selection, install per platform,
ensure_all (skip when present, auto-install toggle, retry back-off), CLI + REST hooks."""
import json
import os
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from neovarch import cli
from neovarch import config as cfgmod
from neovarch import extras
from neovarch.server import Gateway, build_app

REL = {
    "tag_name": "v1.14.4",
    "assets": [
        {"name": "Obsidian-1.14.4-arm64.AppImage", "size": 3,
         "browser_download_url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/Obsidian-1.14.4-arm64.AppImage"},
        {"name": "Obsidian-1.14.4.AppImage", "size": 3,
         "browser_download_url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/Obsidian-1.14.4.AppImage"},
        {"name": "Obsidian-1.14.4.exe", "size": 3,
         "browser_download_url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/Obsidian-1.14.4.exe"},
        {"name": "Obsidian-1.14.4.dmg", "size": 3,
         "browser_download_url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/Obsidian-1.14.4.dmg"},
        {"name": "obsidian_1.14.4_amd64.deb", "size": 3,
         "browser_download_url": "https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/obsidian_1.14.4_amd64.deb"},
        {"name": "Obsidian-9.9.9.exe", "size": 3, "browser_download_url": "https://evil.example/Obsidian-9.9.9.exe"},
    ],
}


@pytest.fixture
def clean_home(home, tmp_path, monkeypatch):
    """A machine without Obsidian: fake HOME/XDG/LOCALAPPDATA, nothing on PATH."""
    h = tmp_path / "userhome"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_DATA_HOME", str(h / ".local" / "share"))
    monkeypatch.setenv("LOCALAPPDATA", str(h / "AppData" / "Local"))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setattr(extras, "_which", lambda *_: None)
    monkeypatch.setattr(extras, "_obsidian_candidates", _only_home(extras._obsidian_candidates))
    monkeypatch.setenv("NEOVARCH_EXTRAS_AUTO", "1")
    return h


def _only_home(orig):
    def cands(plat):
        home = Path(os.environ["HOME"])
        return [p for p in orig(plat) if str(p).startswith(str(home)) or str(p).startswith(os.environ.get("LOCALAPPDATA", "/x"))]
    return cands


def _fake_download(url, dest, progress=None, size=0, opener=None):
    assert url.startswith("https://github.com/obsidianmd/obsidian-releases/releases/download/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"bin")
    if progress:
        progress({"phase": "download", "percent": 100.0})
    return dest


def test_platform_key():
    assert extras.platform_key("win32", "AMD64") == "windows-x64"
    assert extras.platform_key("linux", "aarch64") == "linux-arm64"
    assert extras.platform_key("darwin", "arm64") == "mac-arm64"


def test_pick_official_asset_only():
    assert extras.pick_asset("obsidian", {"assets": [{"name": a["name"], "url": a["browser_download_url"]}
                                                     for a in REL["assets"]]}, "linux-x64")["name"] == "Obsidian-1.14.4.AppImage"
    rel = extras.latest_release("obsidian", fetch=lambda url: REL)
    assert rel["version"] == "1.14.4"
    assert extras.pick_asset("obsidian", rel, "linux-arm64")["name"] == "Obsidian-1.14.4-arm64.AppImage"
    assert extras.pick_asset("obsidian", rel, "windows-x64")["name"] == "Obsidian-1.14.4.exe"  # not the evil one
    assert extras.pick_asset("obsidian", {"assets": [{"name": "Obsidian-9.9.9.exe", "url": "https://evil.example/x"}]},
                             "windows-x64") is None
    assert extras.pick_asset("obsidian", rel, "freebsd") is None


def test_linux_install_appimage_launcher_and_uri_handler(clean_home):
    assert extras.detect("obsidian", "linux-x64")["installed"] is False
    events = []
    res = extras.install("obsidian", plat="linux-x64", fetch=lambda url: REL, downloader=_fake_download,
                         progress=events.append)
    assert res["status"] == "installed" and res["version"] == "1.14.4"
    app = clean_home / ".local" / "share" / "neovarch" / "extras" / "obsidian" / "Obsidian.AppImage"
    assert app.exists() and os.access(app, os.X_OK)
    assert (clean_home / ".local" / "bin" / "obsidian").exists()
    desktop = (clean_home / ".local" / "share" / "applications" / "obsidian.desktop").read_text()
    assert "x-scheme-handler/obsidian" in desktop and str(app) in desktop
    assert [e["phase"] for e in events][0] == "release" and events[-1]["phase"] == "done"
    # now present: install again is a no-op
    assert extras.install("obsidian", plat="linux-x64", fetch=lambda url: pytest.fail("no fetch")) ["status"] == "present"


def test_windows_install_runs_official_installer_silently(clean_home):
    ran = []

    class R:
        returncode = 0

    def runner(cmd, **kw):
        ran.append(cmd)
        exe = clean_home / "AppData" / "Local" / "Programs" / "Obsidian" / "Obsidian.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("x")
        return R()

    res = extras.install("obsidian", plat="windows-x64", fetch=lambda url: REL, downloader=_fake_download, runner=runner)
    assert ran and ran[0][0].endswith("Obsidian-1.14.4.exe") and ran[0][1] == "/S"
    assert res["status"] == "installed" and res["installed"] is True


def test_android_opens_play_store(clean_home):
    res = extras.install("obsidian", plat="android")
    assert res["status"] == "store" and res["open"] == "market://details?id=md.obsidian"


def test_ensure_all_toggle_backoff_and_state(clean_home, monkeypatch):
    cfg = cfgmod.load_config()
    cfgmod.set_path(cfg, "extras.auto_install", False)
    cfgmod.save_config(cfg)
    assert extras.ensure_all(plat="linux-x64", reason="update")[0]["status"] == "disabled"
    cfgmod.set_path(cfg, "extras.auto_install", True)
    cfgmod.save_config(cfg)

    def boom(url):
        raise OSError("offline")

    res = extras.ensure_all(plat="linux-x64", reason="install", fetch=boom)
    assert res[0]["status"] == "failed" and "offline" in res[0]["detail"]
    assert extras.state()["obsidian"]["status"] == "failed"
    # failed recently: not retried until tomorrow…
    assert extras.ensure_all(plat="linux-x64", fetch=boom)[0]["status"] == "skipped"
    # …unless forced (button / `neovarch extras install --force`)
    ok = extras.ensure_all(plat="linux-x64", force=True, fetch=lambda u: REL, downloader=_fake_download)
    assert ok[0]["status"] == "installed"
    assert extras.ensure_all(plat="linux-x64")[0]["status"] == "present"
    st = extras.state()["obsidian"]
    assert st["status"] == "present" and time.time() - st["ts"] < 60
    # env switch (installer --no-extras) wins
    monkeypatch.setenv("NEOVARCH_EXTRAS_AUTO", "0")
    assert extras.auto_enabled() is False


def test_cli_extras_status_json(clean_home, capsys):
    # not cli.main(): that installs the process-wide foreign-path guard for every later test
    args = cli.build_parser().parse_args(["extras", "status", "--json"])
    assert cli.cmd_extras(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["name"] == "obsidian" and out[0]["installed"] is False


def test_never_bundled():
    """Obsidian's licence forbids redistribution: no Obsidian binary anywhere in the repo."""
    root = Path(__file__).resolve().parents[2]
    for sub in ("core", "desktop/apps/desktop/src", "scripts", "android"):
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".appimage", ".exe", ".dmg", ".deb") and "obsidian" in p.name.lower():
                pytest.fail(f"bundled Obsidian binary: {p}")


async def test_rest_status_install_job_and_open(clean_home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    monkeypatch.setattr(extras, "platform_key", lambda *a, **k: "linux-x64")
    monkeypatch.setattr(extras, "_http_json", lambda url, timeout=20: REL)
    monkeypatch.setattr(extras, "download", _fake_download)
    opened = []
    monkeypatch.setattr(extras, "open_uri", lambda uri: opened.append(uri) or True)
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    try:
        st = await (await c.get("/api/extras?token=tok")).json()
        assert st["extras"][0]["installed"] is False
        r = await c.post("/api/extras/open?token=tok", json={"uri": "obsidian://open?path=%2Fv"})
        assert r.status == 409 and (await r.json())["installed"] is False
        r = await c.post("/api/extras/install?token=tok", json={"name": "obsidian"})
        assert r.status == 202
        for _ in range(100):
            job = (await (await c.get("/api/extras?token=tok")).json())["job"]
            if job and job["state"] != "running":
                break
            import asyncio
            await asyncio.sleep(0.05)
        assert job["state"] == "done" and job["status"] == "installed"
        r = await c.post("/api/extras/open?token=tok", json={"uri": "obsidian://open?path=%2Fv"})
        assert (await r.json())["opened"] is True and opened == ["obsidian://open?path=%2Fv"]
        assert (await c.post("/api/extras/open?token=tok", json={"uri": "https://x"})).status == 400
        assert (await c.post("/api/extras/install?token=tok", json={"name": "nope"})).status == 400
    finally:
        await c.close()


async def test_gateway_ensures_once_per_version(clean_home, monkeypatch):
    calls = []
    monkeypatch.setattr(extras, "ensure_all", lambda **kw: calls.append(kw) or [])
    gw = Gateway(isolated=False)
    import asyncio
    gw.ensure_extras_after_install_or_update()
    await asyncio.sleep(0.2)
    assert calls and calls[0]["reason"] == "install"
    gw.ensure_extras_after_install_or_update()  # same version: nothing
    await asyncio.sleep(0.1)
    assert len(calls) == 1
    data = extras.state()
    data["_checked_version"] = "0.0.1"
    extras._save_state(data)
    gw.ensure_extras_after_install_or_update()
    await asyncio.sleep(0.2)
    assert calls[-1]["reason"] == "update"
