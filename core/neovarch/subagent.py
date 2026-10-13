"""``task``: read-only sub-agents, run in parallel (Claude Code Task / Codex sub-agents, lite).

The main agent hands out up to ``MAX_PARALLEL`` independent questions ("where is auth
handled?", "what does the release workflow do?", "find the docs for X"). Each runs in a
fresh, small context with read-only tools only (read_file, grep, glob, repo_map,
web_search, web_fetch), a step cap, and must answer with a short report. Only those
reports enter the main context, so exploration that would cost the main turn tens of
thousands of tokens of file dumps costs a few hundred - and the questions run at the same
time. Sub-agents cannot write, run shell, spawn more sub-agents or talk to the user.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

MAX_PARALLEL = 4
MAX_STEPS = 8
TOOL_CLIP = 6000
REPORT_CLIP = 3000
SUB_TOOLS = ("read_file", "grep", "glob", "repo_map", "web_search", "web_fetch")

SYSTEM = ("You are a read-only research sub-agent of Neovarch Agent. Investigate ONE question with the tools "
          "(read_file, grep, glob, repo_map, web_search, web_fetch) - you cannot edit files or run commands. Be fast: "
          "batch independent tool calls, stop as soon as you can answer, at most {steps} steps. Then reply with a "
          "compact report: the answer, the evidence (file:line or URL), and what you could not establish. "
          "No preamble. Working folder: {cwd}")

SCHEMA = {
    "description": ("Run up to 4 read-only sub-agents IN PARALLEL, each on one independent question (code search, "
                    "reading, web research). Each gets a fresh context and returns a short report with file:line/URL "
                    "evidence; their file dumps never enter your context. Use for broad exploration; not for edits."),
    "parameters": {"type": "object", "properties": {
        "tasks": {"type": "array", "items": {"type": "string"}, "description": "1-4 self-contained questions"},
        "steps": {"type": "integer", "description": "max steps per sub-agent (default 8)"}},
        "required": ["tasks"]},
}

LLM = Callable[[list[dict], list[dict]], Awaitable[Any]]


def _schemas() -> list[dict]:
    from neovarch.tools import TOOLS
    return [{"type": "function", "function": {"name": n, **TOOLS[n][1]}} for n in SUB_TOOLS if n in TOOLS]


async def run_one(question: str, ctx, llm: LLM, steps: int = MAX_STEPS) -> str:
    from neovarch.tools import run_tool
    tools = _schemas()
    allowed = {t["function"]["name"] for t in tools}
    wire: list[dict] = [{"role": "system", "content": SYSTEM.format(steps=steps, cwd=getattr(ctx, "cwd", "."))},
                        {"role": "user", "content": question}]
    text = ""
    for step in range(steps):
        last = step == steps - 1
        comp = await llm(wire, [] if last else tools)
        text = (getattr(comp, "text", "") or "").strip()
        calls = list(getattr(comp, "tool_calls", []) or [])
        if not calls:
            break
        wire.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments or "{}"}}
            for c in calls]})

        async def one(c):
            if c.name not in allowed:
                return f"refused: sub-agents are read-only ({', '.join(sorted(allowed))})"
            try:
                args = json.loads(c.arguments or "{}")
            except ValueError:
                return "error: arguments are not valid JSON"
            out = await run_tool(c.name, args if isinstance(args, dict) else {}, ctx)
            out = str(out)
            return out if len(out) <= TOOL_CLIP else out[:TOOL_CLIP] + f"\n…[clipped {len(out) - TOOL_CLIP} chars]"

        results = await asyncio.gather(*(one(c) for c in calls))
        for c, r in zip(calls, results):
            wire.append({"role": "tool", "tool_call_id": c.id, "content": r})
        if step == steps - 2:
            wire.append({"role": "user", "content": "Step limit reached: write the report now from what you have."})
        text = ""
    if not text:
        text = "(sub-agent ended without a report)"
    return text if len(text) <= REPORT_CLIP else text[:REPORT_CLIP] + "\n…[report clipped]"


async def tool_task(args: dict, ctx) -> str:
    llm = getattr(ctx, "llm", None)
    if llm is None:
        return "error: task is only available inside a chat turn"
    tasks = args.get("tasks")
    if isinstance(tasks, str):
        tasks = [tasks]
    tasks = [str(t).strip() for t in (tasks or []) if str(t).strip()]
    if not tasks:
        return "error: tasks (1-4 questions) is required"
    dropped = tasks[MAX_PARALLEL:]
    tasks = tasks[:MAX_PARALLEL]
    steps = max(2, min(int(args.get("steps") or MAX_STEPS), 15))

    async def guarded(q: str) -> str:
        try:
            return await run_one(q, ctx, llm, steps)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one failed sub-agent never sinks the others
            return f"error: {type(exc).__name__}: {exc}"

    reports = await asyncio.gather(*(guarded(q) for q in tasks))
    out = [f"## Sub-agent {i}: {q}\n{r}" for i, (q, r) in enumerate(zip(tasks, reports), 1)]
    if dropped:
        out.append(f"(not run, max {MAX_PARALLEL} per call: {'; '.join(dropped)})")
    return "\n\n".join(out)
