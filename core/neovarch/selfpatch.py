"""Code-level self-repair, only for an install that runs from a git checkout.

Flow: :func:`prepare` builds the patch on a NEW local branch inside a separate
git worktree (the user's checkout is untouched), commits it there and runs the
tests; :func:`apply` — called only after the user tapped *Setujui* — puts that
single commit onto the current branch with ``git cherry-pick``; undo is
``git revert`` of that commit. A packaged install (frozen binary, app.asar,
site-packages) is never modified: :func:`source_checkout` returns None there.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from neovarch.paths import neovarch_home

GIT_TIMEOUT = 60
TEST_TIMEOUT = 600
AGENT_IDENT = ["-c", "user.name=Neovarch Agent", "-c", "user.email=agent@neovarch.local"]


class PatchError(RuntimeError):
    pass


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT, check: bool = True, stdin: str | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout,
                          input=stdin)
    if check and proc.returncode != 0:
        raise PatchError(f"git {' '.join(args[:2])} gagal: {(proc.stderr or proc.stdout).strip()[:500]}")
    return proc.stdout.strip()


def source_checkout(start: Path | None = None) -> Path | None:
    """The git work tree the running core comes from, or None for a packaged install."""
    if getattr(sys, "frozen", False):
        return None
    here = (start or Path(__file__)).resolve()
    s = str(here)
    if "app.asar" in s or "site-packages" in s or "dist-packages" in s:
        return None
    for p in [here, *here.parents]:
        if (p / ".git").exists():
            return p
    return None


def patches_dir() -> Path:
    d = neovarch_home() / "self" / "patches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(pid: str) -> Path:
    return patches_dir() / f"{pid}.json"


def load(pid: str) -> dict:
    p = _meta_path(pid)
    if not p.exists():
        raise PatchError(f"patch {pid} tidak ditemukan")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(meta: dict) -> None:
    _meta_path(meta["id"]).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(diff: str, title: str, *, repo: Path | None = None, test_cmd: str = "") -> dict:
    """Apply ``diff`` (unified, git-style) on a new branch in a separate worktree and run tests."""
    repo = repo or source_checkout()
    if repo is None:
        raise PatchError("Perbaikan kode hanya bisa untuk instalasi dari kode sumber (git checkout). Aplikasi "
                         "terpaket tidak pernah diubah; perbarui lewat Tentang ▸ Pembaruan.")
    if not str(diff or "").strip():
        raise PatchError("diff kosong")
    pid = time.strftime("%Y%m%d-%H%M%S")
    branch = f"perbaikan/{pid}"
    work = patches_dir() / f"wt-{pid}"
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "worktree", "add", "-b", branch, str(work), base)
    meta = {"id": pid, "title": str(title or "perbaikan")[:120], "branch": branch, "worktree": str(work),
            "repo": str(repo), "base": base, "status": "preparing", "created": time.time()}
    try:
        _git(work, "apply", "--whitespace=nowarn", "-", stdin=diff if diff.endswith("\n") else diff + "\n")
        _git(work, "add", "-A")
        _git(work, *AGENT_IDENT, "commit", "-m", f"Perbaikan otomatis: {meta['title']}")
        meta["commit"] = _git(work, "rev-parse", "HEAD")
        meta["files"] = _git(work, "show", "--name-only", "--format=", "HEAD").splitlines()
        meta["diffstat"] = _git(work, "show", "--stat", "--format=", "HEAD")
    except PatchError as exc:
        meta.update(status="failed", error=str(exc))
        _save(meta)
        cleanup(meta)
        raise
    cmd = test_cmd or default_test_cmd(work, meta["files"])
    meta["test_cmd"] = cmd
    if cmd:
        try:
            proc = subprocess.run(cmd, shell=True, cwd=str(work), capture_output=True, text=True,
                                  timeout=TEST_TIMEOUT, env={**os.environ, "NEOVARCH_CORE": "1"})
            meta["tests_ok"] = proc.returncode == 0
            meta["test_output"] = ((proc.stdout or "") + (proc.stderr or ""))[-3000:]
        except subprocess.TimeoutExpired:
            meta["tests_ok"] = False
            meta["test_output"] = f"tes melebihi {TEST_TIMEOUT}s"
    else:
        meta["tests_ok"] = None
        meta["test_output"] = "tidak ada tes yang cocok untuk file ini"
    meta["status"] = "ready" if meta["tests_ok"] is not False else "tests_failed"
    _save(meta)
    return meta


def default_test_cmd(work: Path, files: list[str]) -> str:
    """Narrow tests for the touched files: core pytest for Python under core/."""
    py = [f for f in files if f.endswith(".py")]
    if py and (work / "core" / "tests").is_dir():
        names = sorted({Path(f).stem.replace("test_", "") for f in py})
        tests = [str(t.relative_to(work / "core")) for t in (work / "core" / "tests").glob("test_*.py")
                 if any(n in t.stem for n in names)]
        target = " ".join(shlex.quote(t) for t in tests[:6]) or "tests"
        return f"cd core && {shlex.quote(sys.executable)} -m pytest -q -x {target}"
    if py:
        return f"{shlex.quote(sys.executable)} -m py_compile " + " ".join(shlex.quote(f) for f in py)
    return ""


def apply(pid: str, *, session_id: str = "") -> dict:
    """Cherry-pick the prepared commit onto the checkout's current branch (after approval)."""
    from neovarch import selfedit
    meta = load(pid)
    if meta.get("status") not in ("ready", "tests_failed"):
        raise PatchError(f"patch {pid} belum siap (status {meta.get('status')})")
    repo = Path(meta["repo"])
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise PatchError("Ada perubahan yang belum di-commit di checkout ini; simpan dulu, lalu coba lagi.")
    before = _git(repo, "rev-parse", "HEAD")
    _git(repo, *AGENT_IDENT, "cherry-pick", meta["commit"])
    applied = _git(repo, "rev-parse", "HEAD")
    meta.update(status="applied", applied_commit=applied, applied_on=_git(repo, "rev-parse", "--abbrev-ref", "HEAD"))
    _save(meta)
    e = selfedit.record("code", "apply", meta["branch"], None, summary=f"patch kode: {meta['title']}",
                        before=before, after=applied, session_id=session_id,
                        extra={"repo": str(repo), "commit": applied, "patch_id": pid})
    cleanup(meta)
    return {**meta, "change_id": e["id"]}


def revert(entry: dict) -> None:
    repo = Path(entry["repo"])
    _git(repo, *AGENT_IDENT, "revert", "--no-edit", entry["commit"])


def cleanup(meta: dict) -> None:
    """Drop the temporary worktree (the branch stays, so the patch can still be inspected)."""
    try:
        _git(Path(meta["repo"]), "worktree", "remove", "--force", meta["worktree"], check=False)
    except Exception:
        pass


def summary(meta: dict) -> str:
    tests = {True: "lulus", False: "GAGAL", None: "tidak dijalankan"}[meta.get("tests_ok")]
    return (f"Patch `{meta['id']}` — {meta['title']}\nBranch lokal: `{meta['branch']}` (commit {meta.get('commit', '')[:10]})\n"
            f"File: {', '.join(meta.get('files') or [])}\nTes (`{meta.get('test_cmd') or '-'}`): {tests}\n"
            + (f"```\n{meta.get('test_output', '')[-1200:]}\n```" if meta.get("test_output") else ""))
