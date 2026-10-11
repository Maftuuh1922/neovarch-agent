"""Keep two cores on one PC in step: the desktop's own core and the phone's LAN core.

The desktop app runs its core on loopback and, when the phone remote is on, a
second ``neovarch serve --host 0.0.0.0 --isolated`` for the phone (see the
desktop's neovarch-remote.ts). Both read and write the same
``~/.neovarch/sessions`` folder, but each only announced *its own* writes, so a
chat started on the phone never showed up on the desktop until a restart (and
the other way round), and each process counted only its own running turns
("0 sesi aktif" on the phone while the desktop was busy).

* :class:`SessionWatcher` polls the sessions folder (cheap: one ``scandir``)
  and calls back when another process changed it; the gateway then broadcasts
  ``sessions.changed`` so every client refreshes its list.
* Turn markers (``~/.neovarch/run/turns/<session>.json``) say which sessions
  have a turn running in which process, so ``session.active_list`` and
  ``/api/status`` count the running turns of both cores.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

from neovarch.paths import neovarch_home

MARKER_MAX_AGE_S = 6 * 3600


def turns_dir() -> Path:
    return neovarch_home() / "run" / "turns"


def _safe(sid: str) -> str:
    return "".join(c for c in str(sid) if c.isalnum() or c in "_-")


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":  # os.kill(pid, 0) would send CTRL_C there
        try:
            import ctypes
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def mark_turn(sid: str, *, title: str = "", model: str = "", preview: str = "") -> None:
    try:
        d = turns_dir()
        d.mkdir(parents=True, exist_ok=True)
        data = {"session_id": sid, "pid": os.getpid(), "started_at": time.time(), "title": title or "",
                "model": model or "", "preview": (preview or "")[:160]}
        tmp = d / f"{_safe(sid)}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / f"{_safe(sid)}.json")
    except OSError:
        pass  # a marker is a courtesy to the other core, never a reason to fail a turn


def clear_turn(sid: str) -> None:
    p = turns_dir() / f"{_safe(sid)}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if int(data.get("pid") or 0) != os.getpid():
            return  # another core runs a turn there now
        p.unlink()
    except (OSError, ValueError):
        pass


def foreign_turns() -> list[dict]:
    """Running turns of *other* live processes (stale markers are removed)."""
    out: list[dict] = []
    d = turns_dir()
    try:
        entries = list(d.glob("*.json"))
    except OSError:
        return out
    now = time.time()
    for p in entries:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid = int(data.get("pid") or 0)
        if pid == os.getpid():
            continue
        if not pid_alive(pid) or now - float(data.get("started_at") or 0) > MARKER_MAX_AGE_S:
            try:
                p.unlink()
            except OSError:
                pass
            continue
        out.append(data)
    return out


def folder_signature(root: Path) -> tuple[int, int]:
    """(number of chats, newest change) of a sessions folder."""
    n, newest = 0, 0
    try:
        with os.scandir(root) as it:
            for e in it:
                if not e.name.endswith(".json"):
                    continue
                n += 1
                try:
                    newest = max(newest, e.stat().st_mtime_ns)
                except OSError:
                    pass
    except OSError:
        return (-1, 0)
    return (n, newest)


class SessionWatcher:
    """Calls ``on_change`` when the sessions folder changed in a way this process did not announce."""

    def __init__(self, root: Path, on_change: Callable[[], None], interval: float = 2.0):
        self.root = Path(root)
        self.on_change = on_change
        self.interval = interval
        self.sig = folder_signature(self.root)
        self.turns = self._turn_ids()
        self._task: asyncio.Task | None = None

    def _turn_ids(self) -> frozenset[str]:
        return frozenset(str(t.get("session_id")) for t in foreign_turns())

    def note_own_write(self) -> None:
        """This process just wrote and announced it: do not announce it twice."""
        self.sig = folder_signature(self.root)

    def poll(self) -> bool:
        return self._apply(folder_signature(self.root), self._turn_ids())

    def _apply(self, sig: tuple[int, int], turns: frozenset[str]) -> bool:
        changed = sig != self.sig or turns != self.turns
        self.sig, self.turns = sig, turns
        if changed:
            try:
                self.on_change()
            except Exception:
                pass
        return changed

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            loop = asyncio.get_running_loop()
            try:  # disk work off the loop; the callback (a broadcast) on it
                sig = await loop.run_in_executor(None, folder_signature, self.root)
                turns = await loop.run_in_executor(None, self._turn_ids)
            except Exception:
                continue
            self._apply(sig, turns)
