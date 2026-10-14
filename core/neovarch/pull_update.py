"""`neovarch update`: update Neovarch in place (git pull or the latest release).

Two paths, chosen by how this core was installed:

* **git install** (this package lives inside a clone of the Neovarch repo): refuse when the
  tracked tree has local changes, ``git fetch`` the branch's upstream, fast-forward only,
  reinstall the Python core (editable) and, when the desktop's lockfile changed and its
  ``node_modules`` exist, the desktop's npm dependencies. When a dependency install fails (or
  the run is interrupted) the clone is reset to the commit it had before, so a broken update
  never leaves a half-updated install behind. The previous commit is recorded in
  ``<home>/update/last.json`` so ``neovarch update --rollback`` can go back later.
* **anything else** (scripts/install.sh / install.ps1 installs, packaged apps, pip installs):
  the existing GitHub Releases check (:mod:`neovarch.updates`, the one PR #38 added) decides
  whether a newer release exists; the official installer for that tag is then downloaded and
  run (it updates the core and the desktop app). AppImage/.deb/pip installs get the release
  page and the matching asset, because they cannot update themselves without root.

After every update (both paths, also "already up to date") the optional extras checker
(:func:`neovarch.extras.ensure_all`, PRs #52/#53) runs with ``reason="update"``: missing
extras such as Obsidian are installed silently, present ones are skipped.

Finally a running gateway is asked to restart (it restarts once no turn is running, see
:meth:`neovarch.server.Gateway.request_restart`). The desktop's "Perbarui" button drives the
same :func:`run` through ``POST /api/update/pull`` and restarts the app itself.

Everything that touches git, subprocesses or the network goes through injectable callables
so the tests can run it without any of them. Free only: GitHub's public API, no paid service.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from neovarch import __version__
from neovarch.paths import neovarch_home

REPO = "Maftuuh1922/neovrach_Agent"
INSTALL_SH = f"https://raw.githubusercontent.com/{REPO}/main/scripts/install.sh"
INSTALL_PS1 = f"https://raw.githubusercontent.com/{REPO}/main/scripts/install.ps1"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

# Step ids, in order. The desktop shows one row per step (i18n key nvPull.step.<id>).
GIT_STEPS = ("detect", "clean", "fetch", "pull", "deps", "extras", "restart")
RELEASE_STEPS = ("detect", "check", "install", "extras", "restart")

# Error codes, stable for the desktop (i18n key nvPull.error.<code>).
ERR_DIRTY = "dirty"
ERR_DETACHED = "detached"
ERR_NO_UPSTREAM = "no_upstream"
ERR_DIVERGED = "diverged"
ERR_FETCH = "fetch_failed"
ERR_MERGE = "merge_failed"
ERR_DEPS = "deps_failed"
ERR_GIT_MISSING = "git_missing"
ERR_RELEASE = "release_failed"
ERR_NO_ROLLBACK = "no_rollback"
ERR_ABORTED = "aborted"

Runner = Callable[..., subprocess.CompletedProcess]
ProgressFn = Callable[[dict], None]


class UpdateError(Exception):
    def __init__(self, code: str, message: str, *, rolled_back: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.rolled_back = rolled_back


def _default_run(cmd: list[str], *, cwd: str | Path | None = None, timeout: float = 600,
                 env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                          timeout=timeout, env=env, check=False,
                          encoding="utf-8", errors="replace")


@dataclass
class Ctx:
    """Everything with a side effect, injectable for tests."""
    run: Runner = _default_run
    progress: ProgressFn | None = None
    which: Callable[[str], str | None] = shutil.which
    fetch_release: Callable[[], dict] | None = None   # -> GitHub "latest release" JSON
    download: Callable[[str, Path], None] | None = None
    ensure_extras: Callable[[], list] | None = None
    restart: Callable[[], dict] | None = None
    python: str = sys.executable
    platform: str = sys.platform
    events: list = field(default_factory=list)

    def emit(self, **ev: Any) -> None:
        ev.setdefault("ts", time.time())
        self.events.append(ev)
        if self.progress:
            try:
                self.progress(ev)
            except Exception:  # noqa: BLE001 - a broken UI must never break the update
                pass

    def step(self, step: str, status: str, detail: str = "") -> None:
        self.emit(kind="step", step=step, status=status, detail=detail)

    def line(self, text: str) -> None:
        for ln in str(text or "").splitlines():
            if ln.strip():
                self.emit(kind="line", text=ln.rstrip()[:500])


# ------------------------------------------------------------------ detect --

def package_dir() -> Path:
    """core/ (the folder holding the `neovarch` package)."""
    return Path(__file__).resolve().parent.parent


def find_repo(ctx: Ctx | None = None, start: Path | None = None) -> Path | None:
    """The root of the Neovarch git clone this core runs from, or None.

    ``NEOVARCH_REPO_DIR`` overrides the start folder. Only a clone that really is the Neovarch
    repo counts (it must hold core/neovarch), so a core installed inside some other project's
    git tree is never "updated" by pulling that project."""
    ctx = ctx or Ctx()
    start = Path(os.environ.get("NEOVARCH_REPO_DIR") or start or package_dir())
    try:
        r = ctx.run(["git", "rev-parse", "--show-toplevel"], cwd=start, timeout=20)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    root = Path(r.stdout.strip())
    if not (root / "core" / "neovarch" / "__init__.py").is_file():
        return None
    return root


def _installer_core_dir() -> Path:
    return neovarch_home() / "neovarch-agent"


def detect(ctx: Ctx | None = None) -> dict[str, Any]:
    """How this core is installed: ``git`` (with branch/upstream/head/dirty) or a release kind."""
    ctx = ctx or Ctx()
    root = find_repo(ctx)
    if root is not None:
        info: dict[str, Any] = {"kind": "git", "root": str(root), "version": __version__}
        info["branch"] = _git(ctx, root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        info["head"] = _git(ctx, root, "rev-parse", "HEAD").stdout.strip()
        up = _git(ctx, root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        info["upstream"] = up.stdout.strip() if up.returncode == 0 else ""
        info["dirty"] = dirty_files(ctx, root)
        return info
    core = package_dir()
    plat = ctx.platform
    if core == _installer_core_dir() or (core / ".neovarch-source-commit").is_file():
        kind = "installer-windows" if plat == "win32" else "installer"
    else:
        kind = "package"
    return {"kind": kind, "root": str(core), "version": __version__}


def _git(ctx: Ctx, root: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return ctx.run(["git", *args], cwd=root, timeout=timeout)


def dirty_files(ctx: Ctx, root: Path) -> list[str]:
    """Tracked files with local changes (untracked files do not block a fast-forward)."""
    r = _git(ctx, root, "status", "--porcelain", "--untracked-files=no")
    return [ln[3:].strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


# ------------------------------------------------------------------- state --

def state_path() -> Path:
    return neovarch_home() / "update" / "last.json"


def read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(data: dict) -> None:
    p = state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


# --------------------------------------------------------------- git path --

def _fail(ctx: Ctx, step: str, code: str, message: str, **kw: Any) -> UpdateError:
    ctx.step(step, "failed", message)
    return UpdateError(code, message, **kw)


def _python_deps_cmd(ctx: Ctx, root: Path) -> list[str]:
    uv = ctx.which("uv")
    core = str(root / "core")
    if uv:
        return [uv, "pip", "install", "--quiet", "--python", ctx.python, "-e", core]
    return [ctx.python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-e", core]


def _desktop_needs_deps(ctx: Ctx, root: Path, old: str, new: str) -> bool:
    desktop = root / "desktop"
    if not (desktop / "node_modules").is_dir():
        return False  # the desktop was never built from this clone; nothing to refresh
    r = _git(ctx, root, "diff", "--name-only", old, new, "--", "desktop/package.json", "desktop/package-lock.json")
    return bool((r.stdout or "").strip())


def install_deps(ctx: Ctx, root: Path, old: str, new: str) -> list[str]:
    """Reinstall what the new commit needs. Raises UpdateError(ERR_DEPS) on failure."""
    done = []
    cmd = _python_deps_cmd(ctx, root)
    ctx.line("$ " + " ".join(cmd))
    r = ctx.run(cmd, cwd=root, timeout=900)
    ctx.line(r.stdout)
    if r.returncode != 0:
        ctx.line(r.stderr)
        raise UpdateError(ERR_DEPS, f"pemasangan dependensi Python gagal (kode {r.returncode}): "
                                    f"{(r.stderr or r.stdout or '').strip()[-300:]}")
    done.append("python")
    if _desktop_needs_deps(ctx, root, old, new):
        npm = ctx.which("npm")
        if not npm:
            raise UpdateError(ERR_DEPS, "dependensi desktop berubah tetapi `npm` tidak ditemukan")
        cmd = [npm, "install", "--no-audit", "--no-fund"]
        ctx.line("$ (desktop) " + " ".join(cmd))
        r = ctx.run(cmd, cwd=root / "desktop", timeout=1800)
        ctx.line((r.stdout or "")[-2000:])
        if r.returncode != 0:
            ctx.line(r.stderr)
            raise UpdateError(ERR_DEPS, f"npm install desktop gagal (kode {r.returncode})")
        done.append("desktop")
    return done


def _rollback(ctx: Ctx, root: Path, old: str) -> bool:
    ctx.line(f"memulihkan ke commit sebelumnya {old[:10]}…")
    r = _git(ctx, root, "reset", "--keep", old)
    if r.returncode != 0:
        r = _git(ctx, root, "reset", "--hard", old)  # the tree was clean when we started
    if r.returncode != 0:
        ctx.line(r.stderr)
        return False
    # Best effort: put the old commit's Python deps back too.
    try:
        ctx.run(_python_deps_cmd(ctx, root), cwd=root, timeout=900)
    except Exception:  # noqa: BLE001
        pass
    return True


def update_git(ctx: Ctx, root: Path, *, check_only: bool = False, deps: bool = True) -> dict[str, Any]:
    ctx.step("detect", "done", str(root))

    ctx.step("clean", "running")
    dirty = dirty_files(ctx, root)
    if dirty:
        shown = ", ".join(dirty[:8]) + (" …" if len(dirty) > 8 else "")
        raise _fail(ctx, "clean", ERR_DIRTY,
                    f"Ada perubahan lokal yang belum di-commit ({shown}). Commit atau `git stash` dulu, "
                    "lalu jalankan `neovarch update` lagi.")
    branch = _git(ctx, root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not branch or branch == "HEAD":
        raise _fail(ctx, "clean", ERR_DETACHED, "Repo dalam keadaan detached HEAD; checkout sebuah branch dulu "
                                                 "(mis. `git checkout main`).")
    up = _git(ctx, root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = up.stdout.strip() if up.returncode == 0 else ""
    if not upstream:
        raise _fail(ctx, "clean", ERR_NO_UPSTREAM, f"Branch `{branch}` tidak punya upstream; jalankan "
                                                    f"`git branch --set-upstream-to=origin/{branch}`.")
    ctx.step("clean", "done", f"{branch} → {upstream}")

    ctx.step("fetch", "running", upstream)
    remote = upstream.split("/", 1)[0]
    r = _git(ctx, root, "fetch", "--quiet", remote, timeout=300)
    if r.returncode != 0:
        raise _fail(ctx, "fetch", ERR_FETCH, f"git fetch gagal: {(r.stderr or '').strip()[-300:]}")
    counts = _git(ctx, root, "rev-list", "--left-right", "--count", "HEAD...@{u}").stdout.split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    old = _git(ctx, root, "rev-parse", "HEAD").stdout.strip()
    ctx.step("fetch", "done", f"{behind} commit baru")
    result: dict[str, Any] = {"kind": "git", "root": str(root), "branch": branch, "upstream": upstream,
                              "old": old, "new": old, "behind": behind, "ahead": ahead, "updated": False}
    if behind == 0:
        ctx.step("pull", "skipped", "sudah terbaru")
        ctx.step("deps", "skipped")
        result["up_to_date"] = True
        return result
    if ahead:
        raise _fail(ctx, "pull", ERR_DIVERGED, f"Branch lokal punya {ahead} commit yang tidak ada di {upstream}; "
                                               "pembaruan fast-forward tidak mungkin. Rebase atau reset dulu.")
    if check_only:
        result["available"] = True
        ctx.step("pull", "skipped", "hanya cek")
        return result

    log = _git(ctx, root, "log", "--oneline", "--no-decorate", f"HEAD..{upstream}", "-n", "20").stdout
    ctx.step("pull", "running", f"{old[:10]} → {upstream}")
    write_state({"kind": "git", "root": str(root), "prev": old, "status": "pulling", "ts": time.time(),
                 "version_before": __version__})
    r = _git(ctx, root, "merge", "--ff-only", "--quiet", "@{u}", timeout=300)
    if r.returncode != 0:
        raise _fail(ctx, "pull", ERR_MERGE, f"git merge --ff-only gagal: {(r.stderr or r.stdout or '').strip()[-300:]}")
    new = _git(ctx, root, "rev-parse", "HEAD").stdout.strip()
    ctx.line(log)
    ctx.step("pull", "done", f"{old[:10]} → {new[:10]}")
    result.update(new=new, updated=True, commits=[ln for ln in log.splitlines() if ln.strip()])

    if deps:
        ctx.step("deps", "running")
        try:
            result["deps"] = install_deps(ctx, root, old, new)
        except BaseException as exc:  # noqa: BLE001 - Ctrl+C mid-install must roll back too
            err = exc if isinstance(exc, UpdateError) else UpdateError(
                ERR_ABORTED if isinstance(exc, KeyboardInterrupt) else ERR_DEPS,
                "dibatalkan" if isinstance(exc, KeyboardInterrupt) else f"{type(exc).__name__}: {exc}")
            ok = _rollback(ctx, root, old)
            write_state({"kind": "git", "root": str(root), "prev": old, "failed": new,
                         "status": "rolled_back" if ok else "rollback_failed", "ts": time.time()})
            ctx.step("deps", "failed", err.message)
            msg = err.message + (f" — dipulihkan ke {old[:10]}." if ok else
                                 f" — PEMULIHAN GAGAL; jalankan `git reset --hard {old[:10]}` di {root}.")
            raise UpdateError(err.code, msg, rolled_back=ok) from None
        ctx.step("deps", "done", ", ".join(result["deps"]))
    else:
        ctx.step("deps", "skipped", "--no-deps")
    write_state({"kind": "git", "root": str(root), "prev": old, "new": new, "status": "updated",
                 "ts": time.time()})
    return result


def rollback(ctx: Ctx | None = None) -> dict[str, Any]:
    """Go back to the commit recorded before the last successful git update."""
    ctx = ctx or Ctx()
    st = read_state()
    root = find_repo(ctx)
    if root is None or st.get("kind") != "git" or not st.get("prev"):
        raise UpdateError(ERR_NO_ROLLBACK, "Tidak ada pembaruan git yang bisa dipulihkan.")
    if dirty_files(ctx, root):
        raise UpdateError(ERR_DIRTY, "Ada perubahan lokal; commit atau stash dulu sebelum memulihkan.")
    head = _git(ctx, root, "rev-parse", "HEAD").stdout.strip()
    if st.get("new") and head != st["new"]:
        raise UpdateError(ERR_NO_ROLLBACK, f"HEAD ({head[:10]}) bukan commit hasil pembaruan terakhir "
                                           f"({str(st['new'])[:10]}); tidak dipulihkan otomatis.")
    if not _rollback(ctx, root, st["prev"]):
        raise UpdateError(ERR_NO_ROLLBACK, "git reset gagal.")
    write_state({**st, "status": "rolled_back_manual", "ts": time.time()})
    return {"kind": "git", "old": head, "new": st["prev"], "updated": True, "rolled_back": True}


# ----------------------------------------------------------- release path --

def _fetch_release_default() -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": f"neovarch-agent/{__version__}"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read().decode("utf-8"))


def _download_default(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": f"neovarch-agent/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:  # noqa: S310
        shutil.copyfileobj(r, fh)


def installer_command(kind: str, script: Path, tag: str) -> tuple[list[str], dict[str, str]]:
    """The official installer for `tag` (it updates the core and the desktop, then runs extras)."""
    env = {"NEOVARCH_VERSION": tag if tag.startswith("v") else f"v{tag}", "NO_COLOR": "1"}
    if kind == "installer-windows":
        return (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], env)
    return (["sh", str(script)], env)


def update_release(ctx: Ctx, info: dict, *, check_only: bool = False) -> dict[str, Any]:
    from neovarch import updates
    ctx.step("detect", "done", info["kind"])
    ctx.step("check", "running")
    try:
        release = (ctx.fetch_release or _fetch_release_default)()
    except Exception as exc:  # noqa: BLE001
        raise _fail(ctx, "check", ERR_RELEASE, f"Tidak bisa mengecek rilis terbaru: {type(exc).__name__}: {exc}")
    plat = "windows" if ctx.platform == "win32" else "linux"
    s = updates.summarize(release or {}, __version__, plat)
    result: dict[str, Any] = {"kind": info["kind"], "current": __version__, "latest": s.get("latest"),
                              "url": s.get("url"), "download_url": s.get("download_url"), "updated": False}
    if not s.get("available"):
        ctx.step("check", "done", f"sudah terbaru ({__version__})")
        ctx.step("install", "skipped")
        result["up_to_date"] = True
        return result
    ctx.step("check", "done", f"{__version__} → {s['latest']}")
    if check_only:
        result["available"] = True
        ctx.step("install", "skipped", "hanya cek")
        return result
    if info["kind"] not in ("installer", "installer-windows"):
        ctx.step("install", "manual", s.get("download_url") or s.get("url") or RELEASES_PAGE)
        result["manual"] = True
        return result
    ctx.step("install", "running", s.get("tag") or "")
    url = INSTALL_PS1 if info["kind"] == "installer-windows" else INSTALL_SH
    with tempfile.TemporaryDirectory(prefix="neovarch-update-") as tmp:
        script = Path(tmp) / Path(url).name
        try:
            (ctx.download or _download_default)(url, script)
        except Exception as exc:  # noqa: BLE001
            raise _fail(ctx, "install", ERR_RELEASE, f"Unduh installer gagal: {exc}")
        cmd, extra_env = installer_command(info["kind"], script, s.get("tag") or s["latest"])
        env = {**os.environ, **extra_env}
        # The installer runs extras itself, but we run ensure afterwards anyway (idempotent).
        env["NEOVARCH_EXTRAS_AUTO"] = env.get("NEOVARCH_EXTRAS_AUTO", "1")
        ctx.line("$ " + " ".join(cmd))
        r = ctx.run(cmd, timeout=1800, env=env)
        ctx.line((r.stdout or "")[-4000:])
        if r.returncode != 0:
            ctx.line(r.stderr)
            # The installer stages into a temp dir and swaps at the end: a failure leaves the old one.
            raise _fail(ctx, "install", ERR_RELEASE, f"Installer gagal (kode {r.returncode}); versi lama tetap dipakai.")
    ctx.step("install", "done", s.get("tag") or "")
    result["updated"] = True
    return result


# ------------------------------------------------------------- extras/restart --

def _ensure_extras_default() -> list:
    from neovarch import extras
    return extras.ensure_all(reason="update")


def run_extras(ctx: Ctx) -> list:
    ctx.step("extras", "running")
    try:
        res = (ctx.ensure_extras or _ensure_extras_default)()
    except Exception as exc:  # noqa: BLE001 - extras are optional; never fail the update for them
        ctx.step("extras", "warning", str(exc)[:200])
        return []
    res = list(res or [])
    summary = ", ".join(f"{r.get('label') or r.get('name')}: {r.get('status') or ('ada' if r.get('installed') else '-')}"
                        for r in res if isinstance(r, dict))
    failed = any(isinstance(r, dict) and r.get("status") == "failed" for r in res)
    ctx.step("extras", "warning" if failed else "done", summary)
    return res


def restart_request_path() -> Path:
    return neovarch_home() / "update" / "restart-request.json"


def request_gateway_restart() -> dict:
    """Ask every running gateway of this home to restart (it waits until no turn is running).

    The gateway watches this file (:func:`neovarch.server.Gateway.watch_update_restart`); a
    file instead of an HTTP call because the CLI has no session token for the gateway."""
    p = restart_request_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ts": time.time(), "by": "neovarch update", "pid": os.getpid()}), encoding="utf-8")
    except OSError as exc:
        return {"requested": False, "detail": str(exc)}
    return {"requested": True, "path": str(p)}


# --------------------------------------------------------------------- run --

def run(ctx: Ctx | None = None, *, check_only: bool = False, deps: bool = True,
        restart: bool = True, extras: bool = True) -> dict[str, Any]:
    """The whole update. Returns a result dict; raises UpdateError with a stable code."""
    ctx = ctx or Ctx()
    ctx.step("detect", "running")
    root = find_repo(ctx)
    if root is None and not ctx.which("git") and (package_dir().parent / ".git").exists():
        raise _fail(ctx, "detect", ERR_GIT_MISSING, "Ini instalasi git, tetapi `git` tidak ditemukan di PATH.")
    if root is not None:
        res = update_git(ctx, root, check_only=check_only, deps=deps)
    else:
        res = update_release(ctx, detect(ctx), check_only=check_only)
    if check_only:
        return res
    res["extras"] = run_extras(ctx) if extras else []
    if not extras:
        ctx.step("extras", "skipped", "--no-extras")
    if restart and res.get("updated"):
        ctx.step("restart", "running")
        rs = (ctx.restart or request_gateway_restart)()
        res["restart"] = rs
        ctx.step("restart", "done" if rs.get("requested") or rs.get("restarted") else "skipped",
                 rs.get("detail", ""))
    else:
        ctx.step("restart", "skipped")
    return res
