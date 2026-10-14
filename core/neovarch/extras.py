"""Optional extras: apps Neovarch can use but never needs (Obsidian first).

Each extra is detected on this machine and, when missing, installed from its official
source, never from a copy shipped inside Neovarch (Obsidian's licence does not allow
redistribution, so its binaries are never bundled):

* Windows: the official installer (``Obsidian-<v>.exe`` from github.com/obsidianmd/obsidian-releases,
  the same file obsidian.md links to), run silently with ``/S`` (per-user, no admin).
* Linux: the official AppImage into ``~/.local/share/neovarch/extras/obsidian/`` with a launcher
  in ``~/.local/bin/obsidian`` and a .desktop entry that registers ``obsidian://`` links.
* macOS: the official .dmg is opened for the user (macOS needs the drag to Applications).
* Android (phone app): opens the Play Store page (``market://details?id=md.obsidian``).

Already installed = skipped. :func:`ensure_all` is the hook for the desktop installer's first run,
app updates and ``neovarch update``: it checks every extra, installs what is missing
(when ``extras.auto_install`` is on), records the outcome in ``<home>/extras.json`` and does not
retry a failed install more than once a day. Nothing here raises into its caller.
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from neovarch import config as cfgmod

ProgressFn = Callable[[dict], None]
RETRY_AFTER = 24 * 3600
USER_AGENT = "neovarch-extras"


@dataclass
class Extra:
    name: str
    label: str
    homepage: str
    repo: str  # GitHub owner/repo with the official release assets
    play_store: str = ""
    licence: str = ""
    purpose: str = ""
    assets: dict[str, str] = field(default_factory=dict)  # platform key -> asset name regex


OBSIDIAN = Extra(
    name="obsidian",
    label="Obsidian",
    homepage="https://obsidian.md/download",
    repo="obsidianmd/obsidian-releases",
    play_store="market://details?id=md.obsidian",
    licence="Proprietary, free to use (obsidian.md/license). Downloaded from the official release; never bundled.",
    purpose="Buka vault Neovarch di aplikasi Obsidian (opsional; graf bawaan Neovarch tetap jalan tanpanya).",
    assets={
        "windows-x64": r"^Obsidian-[\d.]+\.exe$",
        "windows-arm64": r"^Obsidian-[\d.]+\.exe$",  # the universal installer
        "linux-x64": r"^Obsidian-[\d.]+\.AppImage$",
        "linux-arm64": r"^Obsidian-[\d.]+-arm64\.AppImage$",
        "mac-x64": r"^Obsidian-[\d.]+\.dmg$",
        "mac-arm64": r"^Obsidian-[\d.]+\.dmg$",
    },
)

REGISTRY: dict[str, Extra] = {OBSIDIAN.name: OBSIDIAN}


# ---------------------------------------------------------------- platform --
def platform_key(sys_platform: str | None = None, machine: str | None = None) -> str:
    plat = sys_platform or sys.platform
    mach = (machine or _platform.machine() or "").lower()
    arch = "arm64" if mach in ("arm64", "aarch64", "armv8", "armv8l") else "x64"
    if plat == "win32":
        return f"windows-{arch}"
    if plat == "darwin":
        return f"mac-{arch}"
    if plat.startswith("linux"):
        if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
            return "android"
        return f"linux-{arch}"
    return plat


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def linux_dirs() -> dict[str, Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")
    return {
        "app": data / "neovarch" / "extras" / "obsidian",
        "bin": _home() / ".local" / "bin",
        "desktop": data / "applications",
    }


# ------------------------------------------------------------------ detect --
def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _obsidian_candidates(plat: str) -> list[Path]:
    if plat.startswith("windows"):
        out = []
        for env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env)
            if base:
                out.append(Path(base) / ("Programs/Obsidian" if env == "LOCALAPPDATA" else "Obsidian") / "Obsidian.exe")
        return out
    if plat.startswith("mac"):
        return [Path("/Applications/Obsidian.app"), _home() / "Applications" / "Obsidian.app"]
    if plat.startswith("linux"):
        d = linux_dirs()
        return [d["app"] / "Obsidian.AppImage", d["bin"] / "obsidian", _home() / "Applications" / "Obsidian.AppImage",
                Path("/opt/Obsidian/obsidian"), Path("/usr/bin/obsidian"), Path("/snap/bin/obsidian"),
                Path("/var/lib/flatpak/exports/bin/md.obsidian.Obsidian"),
                _home() / ".local/share/flatpak/exports/bin/md.obsidian.Obsidian"]
    return []


def _windows_uri_handler() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
            try:
                key = winreg.OpenKey(hive, r"Software\Classes\obsidian\shell\open\command" if hive == winreg.HKEY_CURRENT_USER
                                     else r"obsidian\shell\open\command")
                val, _ = winreg.QueryValueEx(key, "")
                if val:
                    return str(val)
            except OSError:
                continue
    except ImportError:
        return None
    return None


def detect(name: str = "obsidian", plat: str | None = None) -> dict[str, Any]:
    """Is the extra installed here? ``{"name", "installed", "path", "platform"}``."""
    ex = REGISTRY[name]
    plat = plat or platform_key()
    out: dict[str, Any] = {"name": ex.name, "label": ex.label, "platform": plat, "installed": False, "path": None,
                           "homepage": ex.homepage, "purpose": ex.purpose}
    if plat == "android":
        out["store"] = ex.play_store
        return out
    for p in _obsidian_candidates(plat):
        if p.exists():
            out.update(installed=True, path=str(p))
            return out
    hit = _which("obsidian", "Obsidian", "md.obsidian.Obsidian") if not plat.startswith("windows") else None
    if hit:
        out.update(installed=True, path=hit)
        return out
    handler = _windows_uri_handler()
    if handler:
        out.update(installed=True, path=handler)
    return out


# ----------------------------------------------------------------- release --
def _http_json(url: str, timeout: float = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def latest_release(name: str = "obsidian", fetch: Callable[[str], Any] | None = None) -> dict[str, Any]:
    ex = REGISTRY[name]
    data = (fetch or _http_json)(f"https://api.github.com/repos/{ex.repo}/releases/latest")
    return {"version": str(data.get("tag_name") or "").lstrip("v"),
            "assets": [{"name": a.get("name"), "url": a.get("browser_download_url"), "size": a.get("size") or 0}
                       for a in data.get("assets") or []]}


def pick_asset(name: str, release: dict, plat: str) -> dict | None:
    pattern = REGISTRY[name].assets.get(plat)
    if not pattern:
        return None
    rx = re.compile(pattern)
    for a in release.get("assets") or []:
        url = str(a.get("url") or "")
        # official source only
        if rx.match(str(a.get("name") or "")) and url.startswith(f"https://github.com/{REGISTRY[name].repo}/releases/download/"):
            return a
    return None


def download(url: str, dest: Path, progress: ProgressFn | None = None, size: int = 0,
             opener: Callable[..., Any] | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with (opener or urllib.request.urlopen)(req, timeout=60) as resp, open(tmp, "wb") as fh:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or size or 0) if hasattr(resp, "headers") else size
        done = 0
        last = 0.0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if progress and (now - last > 0.25):
                last = now
                progress({"phase": "download", "done": done, "total": total,
                          "percent": round(100 * done / total, 1) if total else None})
    if size and tmp.stat().st_size != size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"download incomplete ({tmp.stat().st_size if tmp.exists() else 0} of {size} bytes)")
    os.replace(tmp, dest)
    if progress:
        progress({"phase": "download", "done": done, "total": total or done, "percent": 100.0})
    return dest


# ----------------------------------------------------------------- install --
def _install_linux(appimage: Path) -> dict[str, Any]:
    d = linux_dirs()
    d["app"].mkdir(parents=True, exist_ok=True)
    target = d["app"] / "Obsidian.AppImage"
    shutil.move(str(appimage), target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    d["bin"].mkdir(parents=True, exist_ok=True)
    launcher = d["bin"] / "obsidian"
    if not launcher.exists():
        launcher.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    d["desktop"].mkdir(parents=True, exist_ok=True)
    entry = d["desktop"] / "obsidian.desktop"
    entry.write_text(
        "[Desktop Entry]\nName=Obsidian\nComment=Installed by Neovarch from obsidian.md\n"
        f'Exec="{target}" %u\nTerminal=false\nType=Application\nIcon=obsidian\n'
        "MimeType=x-scheme-handler/obsidian;\nCategories=Office;\n", encoding="utf-8")
    # register obsidian:// so "Buka di Obsidian" links open the app (best effort)
    for cmd in (["xdg-mime", "default", "obsidian.desktop", "x-scheme-handler/obsidian"],
                ["update-desktop-database", str(d["desktop"])]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False, timeout=20, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                pass
    return {"path": str(target), "launcher": str(launcher), "desktop_entry": str(entry)}


def _install_windows(exe: Path, runner: Callable[..., Any] | None = None) -> dict[str, Any]:
    # electron-builder NSIS installer: /S = silent per-user install (%LOCALAPPDATA%\Programs\Obsidian)
    run = runner or subprocess.run
    res = run([str(exe), "/S"], check=False, timeout=900)
    code = getattr(res, "returncode", 0)
    if code not in (0, None):
        raise OSError(f"Obsidian installer exited with {code}")
    return {"path": str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Obsidian" / "Obsidian.exe")}


def open_uri(uri: str) -> bool:
    """Open a URL / obsidian:// link with the OS handler."""
    try:
        if sys.platform == "win32":
            os.startfile(uri)  # type: ignore[attr-defined]  # noqa: S606
            return True
        cmd = ["open", uri] if sys.platform == "darwin" else ["xdg-open", uri]
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
            return True
    except OSError:
        return False
    import webbrowser
    return bool(webbrowser.open(uri))


def install(name: str = "obsidian", *, plat: str | None = None, progress: ProgressFn | None = None,
            fetch: Callable[[str], Any] | None = None, downloader: Callable[..., Path] | None = None,
            runner: Callable[..., Any] | None = None, force: bool = False) -> dict[str, Any]:
    """Install one extra from its official source. Skips when it is already installed."""
    ex = REGISTRY[name]
    plat = plat or platform_key()
    found = detect(name, plat)
    if found["installed"] and not force:
        return {**found, "status": "present"}
    if plat == "android":
        return {**found, "status": "store", "open": ex.play_store}
    emit = progress or (lambda _e: None)
    emit({"phase": "release", "name": name})
    release = latest_release(name, fetch)
    asset = pick_asset(name, release, plat)
    if not asset:
        return {**found, "status": "unsupported", "detail": f"no official {ex.label} build for {plat}",
                "open": ex.homepage}
    tmpdir = Path(tempfile.mkdtemp(prefix="neovarch-extra-"))
    try:
        file = (downloader or download)(asset["url"], tmpdir / asset["name"], emit, int(asset.get("size") or 0))
        emit({"phase": "install", "name": name, "version": release["version"]})
        if plat.startswith("linux"):
            info = _install_linux(Path(file))
        elif plat.startswith("windows"):
            info = _install_windows(Path(file), runner)
        elif plat.startswith("mac"):
            # macOS: the .dmg needs the user's drag into Applications; open it for them
            keep = cfgmod.neovarch_home() / "downloads" / asset["name"]
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(file), keep)
            open_uri(str(keep))
            return {**found, "status": "opened", "version": release["version"], "path": str(keep)}
        else:
            return {**found, "status": "unsupported", "open": ex.homepage}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    emit({"phase": "done", "name": name, "version": release["version"]})
    return {**detect(name, plat), **info, "status": "installed", "version": release["version"]}


# ------------------------------------------------------------- ensure (hook) --
def auto_enabled(cfg: dict | None = None, name: str | None = None) -> bool:
    cfg = cfg if cfg is not None else cfgmod.load_config()

    def flag(key: str, default: bool = True) -> bool:
        val = cfgmod.get_path(cfg, key, default)
        if isinstance(val, str):
            return val.strip().lower() not in ("0", "false", "no", "off")
        return val is not False

    if os.environ.get("NEOVARCH_EXTRAS_AUTO", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return flag("extras.auto_install") and (name is None or flag(f"extras.{name}", True))


def _state_path() -> Path:
    return cfgmod.neovarch_home() / "extras.json"


def state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def status_all(plat: str | None = None) -> list[dict[str, Any]]:
    st = state()
    out = []
    for name, ex in REGISTRY.items():
        d = detect(name, plat)
        out.append({**d, "auto": auto_enabled(name=name), "licence": ex.licence, "last": st.get(name)})
    return out


def ensure_all(*, reason: str = "manual", plat: str | None = None, progress: ProgressFn | None = None,
               force: bool = False, **kw: Any) -> list[dict[str, Any]]:
    """Check every extra and install the missing ones. Called by the desktop app on its first
    run after an install or update (``reason="install"`` / ``"update"``), by ``neovarch extras
    ensure`` (installer scripts, ``neovarch update``) and on demand. Never raises."""
    plat = plat or platform_key()
    st = state()
    results = []
    for name in REGISTRY:
        try:
            found = detect(name, plat)
            if found["installed"]:
                res = {**found, "status": "present"}
            elif not force and not auto_enabled(name=name):
                res = {**found, "status": "disabled"}
            elif plat == "android":
                res = {**found, "status": "store", "open": REGISTRY[name].play_store}
            elif (not force and (st.get(name) or {}).get("status") == "failed"
                  and time.time() - float((st.get(name) or {}).get("ts") or 0) < RETRY_AFTER):
                res = {**found, "status": "skipped", "detail": "last install failed; retrying tomorrow"}
            else:
                res = install(name, plat=plat, progress=progress, **kw)
        except Exception as exc:  # noqa: BLE001 - an optional extra must never break install/update
            res = {"name": name, "status": "failed", "detail": str(exc)[:300]}
        res["reason"] = reason
        if res.get("status") in ("installed", "failed", "present", "opened", "unsupported"):
            st[name] = {"status": res["status"], "ts": time.time(), "reason": reason,
                        **({"version": res["version"]} if res.get("version") else {}),
                        **({"detail": res["detail"]} if res.get("detail") else {})}
        results.append(res)
    try:
        _save_state(st)
    except OSError:
        pass
    return results
