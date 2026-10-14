"""Codemode (``agent.tempest_codemode``): one model call runs many tools.

Idea from Reason Agent 1.1 ("codemode"): instead of one model round-trip per tool, the model writes
ONE short Python program that calls the other tools (several at once with ``parallel``) and prints
only what matters. A search, five file reads and a test run then cost one model call, and the
context only grows by the program's printed summary instead of every raw tool output.

How it runs
-----------
* The program runs in a **separate Python process** (``python -I``), working directory = the chat's
  folder, a minimal environment, a wall-clock timeout and (POSIX) CPU / memory / file-size rlimits.
* Inside the program ``tools`` is the only door to the outside: ``tools.read_file(path="a.py")``,
  ``tools.call("grep", pattern="x")``, ``tools.parallel([("read_file", {...}), ...])``,
  ``tools.list()``, ``tools.describe(name)``. Each call is sent to the agent over a pipe and runs
  through the agent's normal path (``dispatch``), so approvals, plan mode, write checks, checkpoints,
  hooks, the disabled-tools list and the evidence ledger apply exactly as for a direct call.
* Guard rails in the child (not a security boundary - the real boundary is that side effects go
  through ``tools``): no network sockets unless ``network=true`` *and* the config allows it, no
  subprocess / os.system / fork / exec, no writing, deleting or renaming files directly
  (``open(..., "w")`` -> use ``tools.write_file`` / ``tools.edit_file`` / ``tools.apply_patch``).
* Calls in one ``parallel`` batch: read-only tools (and shell commands that need no approval)
  run at the same time; tools with side effects or approval prompts run one after another in order.

Limits: ``MAX_CALLS`` tool calls per program, ``MAX_BATCH`` per ``parallel``, output clipped to
``MAX_OUTPUT`` chars, timeout default ``DEFAULT_TIMEOUT`` s (max ``MAX_TIMEOUT``).

Cache: the schema below is static text, so the tool list stays byte-identical across turns.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

NAME = "codemode"
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300
MAX_CALLS = 64
MAX_BATCH = 16
MAX_PARALLEL = 8
MAX_OUTPUT = 12_000
MEMORY_MB = 1024
PROTO = "\x1eNVCM "  # record separator + tag: never produced by normal prints

# Tools a program may never call (recursion, or they make no sense from inside a program).
BLOCKED = frozenset({NAME, "extra_tool"})

SCHEMA: dict[str, Any] = {
    "description": (
        "Run ONE short Python program that calls your other tools and prints only what you need. Use it "
        "instead of several separate tool calls: e.g. grep + read 5 files + run the tests in one step. "
        "Inside the program: `tools.<name>(**args)` (or `tools.call(name, **args)`) runs one tool and "
        "returns its text output; `tools.parallel([(name, {args}), ...])` runs several at once and returns "
        "a list of texts in the same order; `tools.list()` names every tool incl. extra ones, "
        "`tools.describe(name)` gives a schema. Approvals and permissions apply as usual. The program "
        "itself has no network, cannot start processes and cannot write files directly - use "
        "tools.shell / tools.write_file / tools.edit_file / tools.apply_patch. Print a compact result "
        "(matching lines, failing test names, a diff summary), not whole files. Limits: "
        f"{MAX_CALLS} tool calls, {DEFAULT_TIMEOUT}s by default (timeout up to {MAX_TIMEOUT}), "
        f"output clipped to {MAX_OUTPUT} chars."),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python 3 source; `tools` is predefined; print() the result"},
            "timeout": {"type": "integer", "description": f"seconds (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})"},
            "network": {"type": "boolean",
                        "description": "let the program itself open sockets (only if the config allows it)"},
        },
        "required": ["code"],
    },
}

Dispatch = Callable[[str, dict], Awaitable[str]]


@dataclass
class Stats:
    calls: int = 0
    batches: int = 0
    parallel_calls: int = 0
    names: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# The child: a bootstrap that installs the guard rails, then exec()s the model's program.
# --------------------------------------------------------------------------------------------
BOOTSTRAP = r'''
import builtins, io, json, os, sys, traceback
_TAG = "\x1eNVCM "
_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
_in = sys.stdin
_cfg = json.loads(_in.readline())
try:
    import resource, signal
    _mb = int(_cfg.get("memory_mb") or 0)
    if _mb:
        resource.setrlimit(resource.RLIMIT_AS, (_mb << 20, _mb << 20))
    _cpu = int(_cfg.get("cpu_s") or 0)
    if _cpu:
        resource.setrlimit(resource.RLIMIT_CPU, (_cpu, _cpu))
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
except Exception:
    pass

def _deny(what, use):
    def f(*a, **k):
        raise PermissionError("codemode: " + what + " tidak diizinkan di program; pakai " + use)
    return f

if not _cfg.get("network"):
    import socket as _s
    class _NoNet(_s.socket):
        def connect(self, *a, **k): raise PermissionError("codemode: jaringan mati di program; pakai tools.web_fetch / tools.web_search")
        connect_ex = connect
        def bind(self, *a, **k): raise PermissionError("codemode: jaringan mati di program")
    _s.socket = _NoNet
    _s.create_connection = _deny("jaringan", "tools.web_fetch")
    _s.getaddrinfo = _deny("jaringan", "tools.web_fetch")
import subprocess as _sp
for _n in ("Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
    setattr(_sp, _n, _deny("subprocess", "tools.shell(command=...)"))
for _n in ("system", "popen", "fork", "forkpty", "execv", "execve", "execl", "execle", "execlp", "execlpe",
           "execvp", "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp",
           "spawnvpe", "posix_spawn", "posix_spawnp", "kill", "killpg"):
    if hasattr(os, _n):
        setattr(os, _n, _deny("os." + _n, "tools.shell(command=...)"))
for _n in ("remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "truncate", "chmod",
           "chown", "link", "symlink", "mkdir", "makedirs", "utime"):
    if hasattr(os, _n):
        setattr(os, _n, _deny("os." + _n, "tools.write_file / tools.shell"))
import shutil as _sh
for _n in ("rmtree", "move", "copy", "copy2", "copyfile", "copytree", "chown"):
    setattr(_sh, _n, _deny("shutil." + _n, "tools.shell"))
_open = builtins.open
def _ro_open(file, mode="r", *a, **k):
    if any(c in str(mode) for c in "wax+"):
        raise PermissionError("codemode: menulis file langsung tidak diizinkan; pakai tools.write_file / tools.edit_file / tools.apply_patch")
    return _open(file, mode, *a, **k)
builtins.open = _ro_open
io.open = _ro_open
try:
    import pathlib as _pl
    _pl.Path.write_text = _deny("Path.write_text", "tools.write_file")
    _pl.Path.write_bytes = _deny("Path.write_bytes", "tools.write_file")
    _pl.Path.unlink = _deny("Path.unlink", "tools.shell")
    _pl.Path.rename = _deny("Path.rename", "tools.shell")
    _pl.Path.replace = _deny("Path.replace", "tools.shell")
    _pl.Path.mkdir = _deny("Path.mkdir", "tools.shell")
    _pl.Path.touch = _deny("Path.touch", "tools.write_file")
except Exception:
    pass

def _send(obj):
    _out.write(_TAG + json.dumps(obj, ensure_ascii=False) + "\n")
    _out.flush()
    line = _in.readline()
    if not line:
        raise SystemExit("codemode: agent menutup saluran")
    return json.loads(line)

class ToolError(Exception):
    pass

class _Tools:
    def parallel(self, calls):
        norm = []
        for c in calls:
            if isinstance(c, dict):
                name, args = c.get("name") or c.get("tool"), c.get("args") or c.get("arguments") or {}
            else:
                name, args = c[0], (c[1] if len(c) > 1 else {})
            if not isinstance(args, dict):
                raise TypeError("codemode: argumen alat harus dict")
            norm.append({"name": str(name), "args": args})
        if not norm:
            return []
        rep = _send({"op": "call", "calls": norm})
        if rep.get("error"):
            raise ToolError(rep["error"])
        return rep["results"]
    def call(self, _tool, /, **args):
        return self.parallel([(_tool, args)])[0]
    def list(self):
        return _send({"op": "list"})["result"]
    def describe(self, name):
        return _send({"op": "describe", "name": str(name)})["result"]
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda **args: self.parallel([(name, args)])[0]

tools = _Tools()
_buf = io.StringIO()
sys.stdout = _buf
sys.stderr = _buf
_err = None
try:
    code = compile(_cfg["code"], "<codemode>", "exec")
    exec(code, {"__name__": "__main__", "tools": tools, "ToolError": ToolError})
except SystemExit as e:
    if e.code not in (None, 0):
        _err = "SystemExit: " + str(e.code)
except BaseException:
    _err = "".join(traceback.format_exc().splitlines(True)[-12:])
_out.write(_TAG + json.dumps({"op": "done", "output": _buf.getvalue(), "error": _err}, ensure_ascii=False) + "\n")
_out.flush()
'''


def available() -> str | None:
    """None when codemode can run here, else the reason (frozen builds have no ``python -c``)."""
    if getattr(sys, "frozen", False):
        return "core berjalan sebagai binary beku (tanpa interpreter Python)"
    if not sys.executable:
        return "interpreter Python tidak ditemukan"
    return None


def _env(cwd: Path) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": tempfile.gettempdir(), "NEOVARCH_CODEMODE": "1"})
    return env


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.25):]
    return f"{head}\n... [{len(text) - len(head) - len(tail)} karakter dipotong] ...\n{tail}"


async def run_batch(calls: list[dict], dispatch: Dispatch, is_parallel_safe: Callable[[str, dict], bool],
                    stats: Stats) -> list[str]:
    """Run one ``parallel`` batch: safe calls together, the rest one by one in order."""
    results: list[str] = [""] * len(calls)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def one(i: int) -> None:
        c = calls[i]
        name, args = str(c.get("name") or ""), c.get("args") if isinstance(c.get("args"), dict) else {}
        if name in BLOCKED:
            results[i] = f"error: {name} tidak bisa dipanggil dari dalam codemode"
            return
        try:
            results[i] = str(await dispatch(name, args))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a tool error is data for the program, never a crash
            results[i] = f"error: {type(exc).__name__}: {exc}"

    async def guarded(i: int) -> None:
        async with sem:
            await one(i)

    safe = [i for i, c in enumerate(calls)
            if len(calls) > 1 and is_parallel_safe(str(c.get("name") or ""), c.get("args") or {})]
    serial = [i for i in range(len(calls)) if i not in safe]

    async def serial_lane() -> None:
        for i in serial:
            await one(i)

    stats.batches += 1
    stats.calls += len(calls)
    stats.parallel_calls += len(safe)
    stats.names.extend(str(c.get("name") or "") for c in calls)
    await asyncio.gather(serial_lane(), *(guarded(i) for i in safe))
    return results


async def run(code: str, dispatch: Dispatch, cwd: Path, *, timeout: float = DEFAULT_TIMEOUT,
              network: bool = False, list_tools: Callable[[], str] | None = None,
              describe_tool: Callable[[str], str] | None = None,
              is_parallel_safe: Callable[[str, dict], bool] | None = None,
              memory_mb: int = MEMORY_MB) -> tuple[str, Stats]:
    """Run one program; returns (text for the model, stats)."""
    stats = Stats()
    why = available()
    if why:
        return f"error: codemode tidak tersedia ({why}); panggil alat satu per satu.", stats
    if not str(code or "").strip():
        return "error: code kosong", stats
    timeout = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    safe_fn = is_parallel_safe or (lambda _n, _a: False)
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-c", BOOTSTRAP, cwd=str(cwd), env=_env(cwd),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt", limit=8 << 20)
    assert proc.stdin and proc.stdout and proc.stderr
    cfg = {"code": code, "network": bool(network), "memory_mb": memory_mb, "cpu_s": int(timeout) + 5}
    done: dict | None = None
    stray: list[str] = []

    async def reply(obj: dict) -> None:
        proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def loop() -> None:
        nonlocal done
        await reply(cfg)
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line.startswith(PROTO):
                stray.append(line)
                continue
            msg = json.loads(line[len(PROTO):])
            op = msg.get("op")
            if op == "done":
                done = msg
                return
            if op == "list":
                await reply({"result": list_tools() if list_tools else ""})
            elif op == "describe":
                await reply({"result": describe_tool(str(msg.get("name") or "")) if describe_tool else ""})
            elif op == "call":
                calls = msg.get("calls") or []
                if len(calls) > MAX_BATCH:
                    await reply({"error": f"maks {MAX_BATCH} panggilan per parallel"})
                elif stats.calls + len(calls) > MAX_CALLS:
                    await reply({"error": f"batas {MAX_CALLS} panggilan alat per program tercapai"})
                else:
                    await reply({"results": await run_batch(calls, dispatch, safe_fn, stats)})
            else:
                await reply({"error": f"op tidak dikenal: {op}"})

    timed_out = False
    try:
        await asyncio.wait_for(loop(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
    except (BrokenPipeError, ConnectionResetError, json.JSONDecodeError):
        pass
    finally:
        if proc.returncode is None:
            await _kill(proc)
    err_tail = ""
    try:
        err_tail = (await asyncio.wait_for(proc.stderr.read(), 2)).decode("utf-8", "replace")[-1500:]
    except Exception:
        pass
    dur = time.monotonic() - started
    parts: list[str] = []
    if done is not None:
        out = str(done.get("output") or "")
        if out.strip():
            parts.append(out.rstrip())
        if done.get("error"):
            parts.append("Program error:\n" + str(done["error"]).rstrip())
    else:
        if stray:
            parts.append("\n".join(stray[-40:]))
        parts.append(f"error: program dihentikan setelah {timeout:.0f}s (timeout)" if timed_out
                     else "error: program berhenti tanpa hasil" + (f"\n{err_tail.strip()}" if err_tail.strip() else ""))
    if not parts:
        parts.append("(program tidak mencetak apa pun; print() hasil yang kamu butuhkan)")
    footer = (f"[codemode: {stats.calls} panggilan alat"
              + (f", {stats.parallel_calls} paralel" if stats.parallel_calls else "")
              + f", {dur:.1f}s]")
    return _clip("\n".join(parts)) + "\n" + footer, stats


async def _kill(proc) -> None:
    try:
        if os.name != "nt":
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except Exception:
        pass


def tool_list_text(sent: list[dict], deferred: dict[str, dict]) -> str:
    """``tools.list()``: every callable tool, deferred ones with a one-liner."""
    def nm(t: dict) -> str:
        return str((t.get("function") or {}).get("name") or "")

    def short(t: dict) -> str:
        d = " ".join(str((t.get("function") or {}).get("description") or "").split())
        return d.split(". ")[0][:90]
    names = [nm(t) for t in sent if nm(t) and nm(t) not in BLOCKED]
    lines = ["Alat inti: " + ", ".join(names)]
    if deferred:
        lines.append("Alat tambahan (tools.describe(name) untuk schema):")
        lines += [f"- {n}: {short(t)}" for n, t in sorted(deferred.items())]
    return "\n".join(lines)


def describe_text(name: str, schemas: dict[str, dict]) -> str:
    t = schemas.get(name)
    if not t:
        return f"error: alat '{name}' tidak ada. Lihat tools.list()."
    fn = t.get("function") or {}
    return json.dumps({"name": name, "description": fn.get("description", ""),
                       "parameters": fn.get("parameters", {})}, ensure_ascii=False)


def config_allows_network(cfg: dict) -> bool:
    cur: Any = cfg
    for part in ("agent", "tempest_codemode_network"):
        if not isinstance(cur, dict):
            return False
        cur = cur.get(part)
    return cur is True or str(cur).strip().lower() in ("1", "true", "yes", "on", "ya")


def as_bool(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on", "ya")

