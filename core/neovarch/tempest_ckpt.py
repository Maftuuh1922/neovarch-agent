"""Tempest shadow-git checkpoints: per-turn snapshots of the working directory, tagged with
the verify status, and rollback to the last green one. The user's own git is never touched.

The shadow repository lives under ``~/.neovarch/checkpoints/<hash of the project path>``
and is driven only through ``GIT_DIR``/``GIT_WORK_TREE`` with an isolated config (no global
or system config, no hooks, no signing), so the project's ``.git`` (ignored by git as a
path), branches, index and stash are untouched. The project's .gitignore applies, plus a
built-in exclude list for bulky dirs. Single files over ``MAX_FILE_BYTES`` (videos, datasets,
model weights) are left out of the snapshot. Projects that are too big (``max_files`` or
``MAX_TOTAL_BYTES``) or the home directory itself are skipped.

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


# Tempest is the default harness since 1.4.7, so checkpoints run in whatever folder a chat
# works in: never copy huge files into ~/.neovarch, and give up on folders too big to snapshot
# quickly (the turn just runs without checkpoints, like the legacy loop).
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


def _scan(root: Path, limit: int) -> tuple[int, int, list[str]]:
    """(files, bytes, big files) of what ``git add -A`` would take; stops early past a limit.

    Mirrors the snapshot: only SKIP_DIRS and .git are skipped (hidden dirs are snapshotted too),
    files over MAX_FILE_BYTES are listed instead of counted."""
    n, total, big = 0, 0, []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d != ".git"
                   and not os.path.islink(os.path.join(cur, d))]
        for name in files:
            if name.endswith((".pyc", ".log")) or name == ".DS_Store":
                continue
            try:
                size = os.lstat(os.path.join(cur, name)).st_size
            except OSError:
                continue
            n += 1
            if size > MAX_FILE_BYTES:
                big.append(os.path.relpath(os.path.join(cur, name), root).replace(os.sep, "/"))
            else:
                total += size
        if n > limit or total > MAX_TOTAL_BYTES:
            break
    return n, total, big


def _count_files(root: Path, limit: int) -> int:
    return _scan(root, limit)[0]


def _exclude_line(rel: str) -> str:
    """A gitignore line matching exactly this path (glob characters escaped)."""
    out = "".join("\\" + ch if ch in "[]*?\\" else ch for ch in rel)
    return "/" + out


class ShadowRepo:
    def __init__(self, work: Path, home: Path, max_files: int = 5000):
        self.work = Path(work).resolve()
        self.home = Path(home).resolve()
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
        n, total, _big = _scan(self.work, self.max_files)
        if n > self.max_files:
            return False, f"proyek lebih dari {self.max_files} file"
        if total > MAX_TOTAL_BYTES:
            return False, f"proyek lebih dari {MAX_TOTAL_BYTES // (1024 * 1024)} MB"
        return True, ""

    def ensure(self) -> None:
        if (self.dir / "HEAD").exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        (self.dir / "info").mkdir(exist_ok=True)
        self._write_excludes([])
        (self.dir / "tempest-workdir").write_text(str(self.work) + "\n", encoding="utf-8")

    def _write_excludes(self, big: list[str]) -> None:
        extra = []
        if self.home.is_relative_to(self.work):  # never snapshot Neovarch's own data (or this repo)
            extra.append("/" + self.home.relative_to(self.work).as_posix() + "/")
        extra += [_exclude_line(p) for p in big]
        (self.dir / "info").mkdir(parents=True, exist_ok=True)
        (self.dir / "info" / "exclude").write_text("\n".join(EXCLUDES + extra) + "\n", encoding="utf-8")

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
        self._write_excludes(_scan(self.work, max(self.max_files, 1) * 4)[2])  # big files stay out
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
