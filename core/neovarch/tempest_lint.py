"""Tempest delta static gate: only diagnostics a turn's own edits introduced.

At the end of a turn that changed files, every available checker runs twice on the changed
files: once with the files as they were before the turn (restored in place for the moment,
then put back) and once as they are now. Only diagnostics present now and absent before
are reported (keyed by file, code and message; line numbers ignored because edits shift
them). Nothing is injected after individual edits.

Checkers, all optional and skipped when missing:

* ``builtin`` (always, pure Python, .py): syntax errors, undefined names (conservative,
  module-wide: a name bound anywhere in the module counts as defined; skipped when the module
  uses ``import *``), and wrong positional/keyword arity in calls to plain module-level
  functions of the same file.
* ``ruff`` (``ruff`` on PATH or ``python -m ruff``): pyflakes + syntax rules only (F, E9).
* ``pyright`` / ``mypy`` when on PATH (errors only).
* ``tsc`` for .ts/.tsx when the project has tsconfig.json and node_modules/.bin/tsc or tsc
  on PATH (whole project, filtered to the changed files).
"""

from __future__ import annotations

import ast
import builtins
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PY_EXTS = {".py"}
TS_EXTS = {".ts", ".tsx"}
MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__loader__", "__package__",
                  "__path__", "__annotations__", "__dict__", "__class__", "__debug__", "__cached__"}


@dataclass(frozen=True)
class Diag:
    path: str      # relative to the project root when possible
    line: int
    code: str
    message: str
    tool: str

    def key(self) -> tuple[str, str, str]:
        return (self.path, self.code, re.sub(r"\s+", " ", self.message).strip())

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message} ({self.tool})"


# ------------------------------------------------------------- builtin -----

def builtin_python(text: str, rel: str) -> list[Diag]:
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [Diag(rel, exc.lineno or 0, "E999", f"{type(exc).__name__}: {exc.msg}", "builtin")]
    out = _undefined_names(tree, rel)
    out += _arity(tree, rel)
    return out


def _bound_names(tree: ast.AST) -> tuple[set[str], bool, dict[str, int]]:
    bound: set[str] = set()
    counts: dict[str, int] = {}
    star = False

    def bind(name: str | None) -> None:
        if name:
            bound.add(name)
            counts[name] = counts.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
        elif isinstance(node, ast.arguments):
            for a in node.posonlyargs + node.args + node.kwonlyargs:
                bind(a.arg)
            if node.vararg:
                bind(node.vararg.arg)
            if node.kwarg:
                bind(node.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    star = True
                    continue
                bind(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler):
            bind(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for n in node.names:
                bind(n)
        elif isinstance(node, ast.MatchAs):
            bind(node.name)
        elif isinstance(node, ast.MatchStar):
            bind(node.name)
        elif isinstance(node, ast.MatchMapping):
            bind(node.rest)
        elif hasattr(ast, "TypeVar") and isinstance(node, getattr(ast, "TypeVar")):
            bind(node.name)
    return bound, star, counts


def _undefined_names(tree: ast.AST, rel: str) -> list[Diag]:
    bound, star, _ = _bound_names(tree)
    if star:
        return []
    known = bound | set(dir(builtins)) | MODULE_DUNDERS
    out, seen = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in known:
            if node.id not in seen:
                seen.add(node.id)
                out.append(Diag(rel, node.lineno, "F821", f"undefined name '{node.id}'", "builtin"))
    return out


def _arity(tree: ast.Module, rel: str) -> list[Diag]:
    _, _, counts = _bound_names(tree)
    funcs: dict[str, ast.arguments] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.decorator_list:
            a = node.args
            if a.vararg or a.kwarg or counts.get(node.name, 0) != 1:
                continue
            funcs[node.name] = a
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs):
            continue
        if any(isinstance(x, ast.Starred) for x in node.args) or any(k.arg is None for k in node.keywords):
            continue
        a = funcs[node.func.id]
        pos = a.posonlyargs + a.args
        n_def = len(a.defaults)
        required_pos = [p.arg for p in pos[:len(pos) - n_def]]
        given_kw = {k.arg for k in node.keywords}
        name = node.func.id
        if len(node.args) > len(pos):
            out.append(Diag(rel, node.lineno, "E1121", f"call to '{name}' has too many positional arguments "
                                                       f"({len(node.args)} > {len(pos)})", "builtin"))
            continue
        covered = {p.arg for p in pos[:len(node.args)]} | given_kw
        missing = [p for p in required_pos if p not in covered]
        missing += [k.arg for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None and k.arg not in given_kw]
        if missing:
            out.append(Diag(rel, node.lineno, "E1120", f"call to '{name}' is missing argument '{missing[0]}'", "builtin"))
        valid = {p.arg for p in a.args} | {k.arg for k in a.kwonlyargs}
        bad = sorted(k for k in given_kw if k not in valid)
        if bad:
            out.append(Diag(rel, node.lineno, "E1123", f"call to '{name}' has unexpected keyword argument '{bad[0]}'",
                            "builtin"))
    return out


# ------------------------------------------------------------ external -----

def _which_ruff() -> list[str] | None:
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    try:
        r = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return [sys.executable, "-m", "ruff"]
    except Exception:
        pass
    return None


def available(root: Path) -> list[str]:
    tools = ["builtin"]
    if _which_ruff():
        tools.append("ruff")
    if shutil.which("pyright"):
        tools.append("pyright")
    if shutil.which("mypy"):
        tools.append("mypy")
    if _tsc(root):
        tools.append("tsc")
    return tools


def _tsc(root: Path) -> list[str] | None:
    if not (root / "tsconfig.json").exists():
        return None
    local = root / "node_modules" / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
    if local.exists():
        return [str(local)]
    exe = shutil.which("tsc")
    return [exe] if exe else None


def _run(cmd: list[str], cwd: Path, timeout: int) -> str | None:
    try:
        from neovarch import tempest  # Stop kills a running checker (tempest.killable)
        r = tempest.run_proc(cmd, cwd=cwd, timeout=timeout, env={**os.environ, "NO_COLOR": "1"})
    except Exception:
        return None
    return (r.stdout or "") + (r.stderr or "")


def _rel(root: Path, p: str) -> str:
    try:
        return str(Path(p).resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return str(p)


def run_ruff(root: Path, files: list[Path], timeout: int) -> list[Diag]:
    base = _which_ruff()
    py = [str(f) for f in files if f.suffix in PY_EXTS and f.exists()]
    if not base or not py:
        return []
    out = _run(base + ["check", "--output-format=json", "--select", "F,E9", "--no-cache", "--isolated",
                       "--exit-zero"] + py, root, timeout)
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    return [Diag(_rel(root, d.get("filename", "")), int((d.get("location") or {}).get("row") or 0),
                 str(d.get("code") or "ruff"), str(d.get("message") or ""), "ruff") for d in data]


def run_pyright(root: Path, files: list[Path], timeout: int) -> list[Diag]:
    exe = shutil.which("pyright")
    py = [str(f) for f in files if f.suffix in PY_EXTS and f.exists()]
    if not exe or not py:
        return []
    out = _run([exe, "--outputjson"] + py, root, timeout)
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return []
    res = []
    for d in data.get("generalDiagnostics") or []:
        if d.get("severity") != "error":
            continue
        line = int(((d.get("range") or {}).get("start") or {}).get("line") or 0) + 1
        res.append(Diag(_rel(root, d.get("file", "")), line, str(d.get("rule") or "pyright"),
                        str(d.get("message") or "").splitlines()[0], "pyright"))
    return res


MYPY_RE = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+): error: (?P<msg>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$")


def run_mypy(root: Path, files: list[Path], timeout: int) -> list[Diag]:
    exe = shutil.which("mypy")
    py = [str(f) for f in files if f.suffix in PY_EXTS and f.exists()]
    if not exe or not py:
        return []
    out = _run([exe, "--no-error-summary", "--show-error-codes", "--hide-error-context", "--no-color-output",
                "--follow-imports=silent", "--ignore-missing-imports", "--no-incremental"] + py, root, timeout)
    res = []
    for line in (out or "").splitlines():
        m = MYPY_RE.match(line.strip())
        if m:
            res.append(Diag(_rel(root, m["file"]), int(m["line"]), m["code"] or "mypy", m["msg"], "mypy"))
    return res


TSC_RE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),\d+\): error (?P<code>TS\d+): (?P<msg>.*)$")


def run_tsc(root: Path, files: list[Path], timeout: int) -> list[Diag]:
    base = _tsc(root)
    want = {_rel(root, str(f)) for f in files if f.suffix in TS_EXTS}
    if not base or not want:
        return []
    out = _run(base + ["--noEmit", "--pretty", "false", "-p", str(root / "tsconfig.json")], root, timeout)
    res = []
    for line in (out or "").splitlines():
        m = TSC_RE.match(line.strip())
        if m and _rel(root, str(root / m["file"])) in want:
            res.append(Diag(_rel(root, str(root / m["file"])), int(m["line"]), m["code"], m["msg"], "tsc"))
    return res


RUNNERS = {"ruff": run_ruff, "pyright": run_pyright, "mypy": run_mypy, "tsc": run_tsc}


def lint(root: Path, files: list[Path], tools: list[str], timeout: int = 60) -> list[Diag]:
    out: list[Diag] = []
    if "builtin" in tools:
        for f in files:
            if f.suffix in PY_EXTS and f.is_file():
                out += builtin_python(f.read_text(encoding="utf-8", errors="replace"), _rel(root, str(f)))
    for name in tools:
        if name in RUNNERS:
            try:
                out += RUNNERS[name](root, files, timeout)
            except Exception:  # a broken checker must never block a turn
                continue
    return out


def delta(root: Path, before: dict[str, bytes | None], tools: list[str] | None = None,
          timeout: int = 60) -> list[Diag]:
    """New diagnostics in the changed files vs their content before the turn.

    ``before`` maps absolute path -> original bytes (None = the file did not exist). The
    originals are put back in place only while the baseline is measured."""
    root = Path(root)
    files = [Path(p) for p in before]
    lintable = [f for f in files if f.suffix in PY_EXTS | TS_EXTS]
    if not lintable:
        return []
    tools = tools or available(root)
    after = lint(root, lintable, tools, timeout)
    if not after:
        return []
    current: dict[Path, bytes | None] = {f: (f.read_bytes() if f.is_file() else None) for f in lintable}
    try:
        for f in lintable:
            orig = before[str(f)]
            if orig is None:
                f.unlink(missing_ok=True)
            else:
                f.write_bytes(orig)
        base = lint(root, [f for f in lintable if before[str(f)] is not None], tools, timeout)
    finally:
        for f, data in current.items():
            if data is None:
                f.unlink(missing_ok=True)
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
    old = {d.key() for d in base}
    seen, out = set(), []
    for d in after:
        if d.key() not in old and (d.path, d.line, d.message) not in seen:
            seen.add((d.path, d.line, d.message))
            out.append(d)
    return out


def gate_prompt(diags: list[Diag], attempt: int, retries: int) -> str:
    lines = [d.render() for d in diags[:20]]
    more = f"\n… dan {len(diags) - 20} lagi" if len(diags) > 20 else ""
    return (f"[pemeriksaan statis gagal — {len(diags)} diagnostik BARU dari perubahanmu "
            f"(percobaan {attempt}/{retries}; diagnostik yang sudah ada sebelumnya diabaikan)]\n"
            + "\n".join(lines) + more +
            "\n\nPerbaiki hanya diagnostik baru di atas (jangan merapikan hal lain), lalu selesaikan.")


def leftover_note(diags: list[Diag]) -> str:
    return ("\n\n⚠️ Masih ada diagnostik statis baru (tidak memblokir lagi):\n"
            + "\n".join(d.render() for d in diags[:8]))
