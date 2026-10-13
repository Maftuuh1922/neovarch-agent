"""User hooks around tool calls (Claude Code style), from ``~/.neovarch/hooks.json`` only.

    {"pre_tool":  [{"match": "shell|write_file", "command": "my-guard.sh", "timeout": 20}],
     "post_tool": [{"match": "write_file|edit_file|apply_patch", "command": "ruff format -q ."}]}

* ``match`` is a regex on the tool name (default: every tool).
* The hook gets JSON on stdin: ``{"event", "tool", "args", "cwd", "result"(post)}``, plus the
  env vars ``NEOVARCH_HOOK_EVENT``, ``NEOVARCH_TOOL`` and runs in the chat's working folder.
* pre_tool exit code 2 blocks the call; its stderr (or stdout) is the reason the model sees.
  Any other non-zero exit is ignored (a broken hook never stops the agent).
* post_tool stdout (clipped) is appended to the tool result, so a formatter/linter's
  findings reach the model.

Only the user's own file is read; a hooks file inside a repository is never executed,
so opening a cloned project cannot run its commands.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from neovarch.paths import neovarch_home

_cache: dict = {"mtime": None, "data": {}}
CLIP = 2000


def load(home: Path | None = None) -> dict:
    path = Path(home or neovarch_home()) / "hooks.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, data={})
        return {}
    if _cache["mtime"] == (str(path), mtime):
        return _cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache.update(mtime=(str(path), mtime), data=data)
    return data


def _matching(event: str, tool: str, home: Path | None = None) -> list[dict]:
    out = []
    for h in load(home).get(event) or []:
        if not isinstance(h, dict) or not str(h.get("command") or "").strip():
            continue
        try:
            if re.fullmatch(str(h.get("match") or ".*"), tool):
                out.append(h)
        except re.error:
            continue
    return out


async def _run(h: dict, payload: dict, cwd: Path) -> tuple[int, str, str]:
    env = {**os.environ, "NEOVARCH_HOOK_EVENT": payload["event"], "NEOVARCH_TOOL": payload["tool"]}
    try:
        proc = await asyncio.create_subprocess_shell(
            str(h["command"]), cwd=str(cwd) if Path(cwd).is_dir() else None, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload, ensure_ascii=False, default=str).encode()),
                                          timeout=float(h.get("timeout") or 30))
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return -1, "", "hook timed out"
    except Exception as exc:  # a broken hook never stops the agent
        return -1, "", str(exc)


async def pre_tool(tool: str, args: dict, cwd: Path, home: Path | None = None) -> str | None:
    """A reason when a hook blocks the call, else None."""
    for h in _matching("pre_tool", tool, home):
        code, out, err = await _run(h, {"event": "pre_tool", "tool": tool, "args": args, "cwd": str(cwd)}, cwd)
        if code == 2:
            reason = (err.strip() or out.strip() or "blocked")[:CLIP]
            return f"blocked by hook ({h['command'][:60]}): {reason}"
    return None


async def post_tool(tool: str, args: dict, result: str, cwd: Path, home: Path | None = None) -> str:
    """Extra text to append to the tool result ('' when nothing)."""
    notes = []
    for h in _matching("post_tool", tool, home):
        code, out, err = await _run(h, {"event": "post_tool", "tool": tool, "args": args, "cwd": str(cwd),
                                         "result": str(result)[:CLIP]}, cwd)
        text = (out.strip() or (err.strip() if code not in (0, -1) else ""))[:CLIP]
        if text:
            notes.append(f"[hook {h['command'][:40]}] {text}")
    return ("\n" + "\n".join(notes)) if notes else ""
