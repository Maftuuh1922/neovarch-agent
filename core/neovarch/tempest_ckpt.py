"""Tempest shadow-git checkpoints: per-turn snapshots of the working directory, tagged with
the verify status, and rollback to the last green one. The user's own git is never touched.

The shadow repository lives under ``~/.neovarch/checkpoints/<hash of the project path>``
and is driven only through ``GIT_DIR``/``GIT_WORK_TREE`` with an isolated config (no global
or system config, no hooks, no signing), so the project's ``.git`` (ignored by git as a
path), branches, index and stash are untouched. The project's .gitignore applies, plus a
built-in exclude list for bulky dirs. Projects that are too big (``max_files``) or the home
directory itself are skipped.

Status per checkpoint tree: ``green`` (verify passed), ``red`` (verify failed), ``unknown``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

EXCLUDES = [".git/", "node_modules/", ".venv/", "venv/", "env/", "__pycache__/", "*.pyc", ".mypy_cache/",
            ".pytest_cache/", ".ruff_cache/", ".tox/", "dist/", "build/", ".next/", "target/", ".gradle/",
            ".dart_tool/", ".idea/", ".DS_Store", "*.log"]
SKIP_DIRS = {e.rstrip("/") for e in EXCLUDES if e.endswith("/")}


class CheckpointError(RuntimeError):
    pass


def git_available() -> bool:
    return shutil.which("git") is not None


def _count_files(root: Path, limit: int) -> int:
    n = 0
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        n += len(files)
        if n > limit:
            return n
    return n


class ShadowRepo:
    def __init__(self, work: Path, home: Path, max_files: int = 5000):
        self.work = Path(work).resolve()
        key = hashlib.sha1(str(self.work).encode("utf-8")).hexdigest()[:16]
        self.dir = Path(home) / "checkpoints" / key
        self.max_files = max_files
        self._status_file = self.dir / "tempest-status.json"

    # -------------------------------------------------------------- plumbing --
    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"GIT_DIR": str(self.dir), "GIT_WORK_TREE": str(self.work), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                    "GIT_AUTHOR_NAME": "tempest", "GIT_AUTHOR_EMAIL": "tempest@neovarch.local",
                    "GIT_COMMITTER_NAME": "tempest", "GIT_COMMITTER_EMAIL": "tempest@neovarch.local"})
        return env

    def git(self, *args: str, check: bool = True, timeout: int = 120) -> str:
        cmd = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
               "-c", "core.quotepath=false", "-c", "gc.auto=0", *args]
        proc = subprocess.run(cmd, cwd=str(self.work), env=self._env(), capture_output=True, text=True,
                              timeout=timeout)
        if check and proc.returncode != 0:
            raise CheckpointError(f"git {' '.join(args)}: {(proc.stderr or proc.stdout).strip()[:300]}")
        return proc.stdout

    def usable(self) -> tuple[bool, str]:
        if not git_available():
            return False, "git tidak terpasang"
        if not self.work.is_dir():
            return False, "folder kerja tidak ada"
        if self.work == Path.home().resolve() or self.work == Path(self.work.anchor):
            return False, "folder kerja adalah home/root"
        if _count_files(self.work, self.max_files) > self.max_files:
            return False, f"proyek lebih dari {self.max_files} file"
        return True, ""

    def ensure(self) -> None:
        if (self.dir / "HEAD").exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        (self.dir / "info").mkdir(exist_ok=True)
        (self.dir / "info" / "exclude").write_text("\n".join(EXCLUDES) + "\n", encoding="utf-8")
        (self.dir / "tempest-workdir").write_text(str(self.work) + "\n", encoding="utf-8")

    # --------------------------------------------------------------- status --
    def _statuses(self) -> dict[str, str]:
        try:
            return json.loads(self._status_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def set_status(self, sha: str, status: str) -> None:
        data = self._statuses()
        data[self.tree(sha)] = status
        self._status_file.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def status(self, sha: str) -> str:
        return self._statuses().get(self.tree(sha), "unknown")

    def tree(self, sha: str) -> str:
        return self.git("rev-parse", f"{sha}^{{tree}}").strip()

    # ------------------------------------------------------------ operations --
    def checkpoint(self, label: str, status: str | None = None) -> str:
        """Snapshot the whole working tree (honouring ignores); returns the commit sha."""
        self.ensure()
        self.git("add", "-A", ".")
        self.git("commit", "-q", "--allow-empty", "--no-verify", "-m", label)
        sha = self.git("rev-parse", "HEAD").strip()
        if status:
            self.set_status(sha, status)
        return sha

    def restore(self, sha: str) -> list[str]:
        """Make the working tree match checkpoint ``sha`` (tracked files only). Files created
        after it are deleted, changed/deleted ones are brought back. Returns the paths touched.
        The current state is checkpointed first, so a restore can itself be undone."""
        self.checkpoint(f"sebelum pemulihan ke {sha[:8]}")
        changed = [l for l in self.git("diff", "--name-status", "--no-renames", sha, "HEAD").splitlines() if l.strip()]
        touched = []
        for line in changed:
            flag, _, path = line.partition("\t")
            if flag == "A":  # exists now, not in the checkpoint
                p = self.work / path
                if p.is_file() or p.is_symlink():
                    p.unlink()
                touched.append(path)
        rest = [l.partition("\t")[2] for l in changed if not l.startswith("A\t")]
        if rest:
            self.git("checkout", sha, "--", *rest)
            touched += rest
        return touched

    def log(self, n: int = 20) -> list[dict]:
        if not (self.dir / "HEAD").exists():
            return []
        out = []
        for line in self.git("log", f"-{n}", "--format=%H%x1f%s%x1f%ct", check=False).splitlines():
            sha, subject, ts = (line.split("\x1f") + ["", ""])[:3]
            out.append({"sha": sha, "label": subject, "ts": int(ts or 0), "status": self.status(sha)})
        return out

    def last_green(self) -> str | None:
        for entry in self.log(200):
            if entry["status"] == "green":
                return entry["sha"]
        return None


def rewind(work: Path, home: Path, ref: str = "last-green") -> str:
    """``neovarch rewind``: restore files to a checkpoint (``last-green`` or a sha prefix)."""
    repo = ShadowRepo(work, home)
    if not (repo.dir / "HEAD").exists():
        raise CheckpointError("belum ada checkpoint untuk folder ini")
    sha = repo.last_green() if ref == "last-green" else repo.git("rev-parse", ref).strip()
    if not sha:
        raise CheckpointError("tidak ada checkpoint hijau")
    touched = repo.restore(sha)
    repo.checkpoint(f"rewind ke {sha[:8]}", repo.status(sha))
    return f"dipulihkan ke {sha[:8]} ({len(touched)} file)"
