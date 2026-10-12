"""Live A/B bench for Tempest v2 on small samples of public benchmarks (no datasets in the repo).

One task per process (keeps the PC light). Example:

    python bench/tempest_v2_live.py --zen --core /path/to/core --label after --suite web --task 0 --out runs/
    python bench/tempest_v2_live.py --summary runs/

Suites (downloaded on demand into ``--cache``):

* ``coding`` - Aider polyglot benchmark, Python practice exercises (github.com/Aider-AI/polyglot-benchmark):
  the agent gets ``.docs/instructions.md`` + the stub and must make ``<name>_test.py`` pass; graded by running
  pytest on the untouched test file afterwards. IDs: :data:`CODING_IDS`.
* ``web`` - OpenAI SimpleQA test set (openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv),
  the 5 rows simple-evals itself picks for ``num_examples=5`` (``random.Random(0).sample``). Graded with the
  official SimpleQA grader prompt (bench/simpleqa_grader.txt, same model) plus a normalized substring check.
* Terminal-Bench needs Docker per task, so it is not part of this harness.

Model: any OpenAI-compatible endpoint (``--base-url``/``--model``/``NV_API_KEY``). ``--zen`` talks to OpenCode Zen's
free tier directly through a small in-process adapter that sends the OpenCode client headers and maps the tool
names Zen's free tier requires (``bash``/``read``) to Neovarch's (``shell``/``read_file``) and back - the same
models a fresh Neovarch install reaches through 9Router's "OpenCode Free" provider (``oc/<model>``).

Per task: pass, LLM calls, steps, agent seconds, prompt/completion/cached tokens (provider usage), first-call
prompt tokens, tool calls by name.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CODING_IDS = ["wordy", "bowling", "transpose", "two-bucket"]
POLYGLOT_RAW = "https://raw.githubusercontent.com/Aider-AI/polyglot-benchmark/main/python/exercises/practice/{name}/{file}"
SIMPLEQA_CSV = "https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv"
SIMPLEQA_N = 5
ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"
ZEN_UA = "opencode/1.19.0"
TOOL_MAP = {"shell": "bash", "read_file": "read"}
TOOL_BACK = {v: k for k, v in TOOL_MAP.items()}
_GRADER_FILE = Path(__file__).with_name("simpleqa_grader.txt")
GRADER = _GRADER_FILE.read_text(encoding="utf-8") if _GRADER_FILE.exists() else ""


# ------------------------------------------------------------------ data -----

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "neovarch-bench"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def coding_task(name: str, cache: Path) -> dict:
    d = cache / "polyglot" / name
    mod = name.replace("-", "_")
    files = {"instructions.md": ".docs/instructions.md", f"{mod}.py": f"{mod}.py", f"{mod}_test.py": f"{mod}_test.py"}
    for local, remote in files.items():
        p = d / local
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(_get(POLYGLOT_RAW.format(name=name, file=remote)))
    return {"id": f"polyglot/python/{name}", "dir": d, "module": mod}


def simpleqa_rows(cache: Path) -> list[dict]:
    p = cache / "simple_qa_test_set.csv"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_get(SIMPLEQA_CSV))
    rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8"))))
    picked = random.Random(0).sample(rows, SIMPLEQA_N)  # what simple-evals uses for num_examples=5
    for r in picked:
        r["index"] = rows.index(r)
    return picked


# --------------------------------------------------------------- adapter -----

def _rid(prefix: str) -> str:
    v = (int(time.time() * 1000) * 0x1000 + random.randint(0, 4095)) & 0xFFFFFFFFFFFF
    return prefix + format(v, "012x") + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(14))


class Meter:
    def __init__(self):
        self.calls: list[dict] = []  # {prompt, completion, cached, status, dt, error?}


async def start_zen_adapter(meter: Meter):
    """Local OpenAI-compatible endpoint -> OpenCode Zen free tier. Returns (base_url, runner)."""
    import aiohttp
    from aiohttp import web as aweb
    session_id = _rid("ses_")

    def rewrite(line: bytes, rec: dict) -> bytes:
        if not line.startswith(b"data:") or line.strip() == b"data: [DONE]":
            return line
        try:
            data = json.loads(line[5:])
        except ValueError:
            return line
        u = data.get("usage")
        if u:
            rec["prompt"] = int(u.get("prompt_tokens") or 0)
            rec["completion"] = int(u.get("completion_tokens") or 0)
            rec["cached"] = int((u.get("prompt_tokens_details") or {}).get("cached_tokens")
                                or u.get("cache_read_input_tokens") or 0)
        for ch in data.get("choices") or []:
            for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name") in TOOL_BACK:
                    fn["name"] = TOOL_BACK[fn["name"]]
        return b"data: " + json.dumps(data, ensure_ascii=False).encode()

    async def handle(request):
        body = await request.json()
        body["model"] = str(body.get("model") or "").removeprefix("oc/")
        for t in body.get("tools") or []:
            t["function"]["name"] = TOOL_MAP.get(t["function"]["name"], t["function"]["name"])
        names = {t["function"]["name"] for t in body.get("tools") or []}
        for need in ("bash", "read"):
            if need not in names:
                body.setdefault("tools", []).append({"type": "function", "function": {
                    "name": need, "description": "unavailable", "parameters": {"type": "object", "properties": {}}}})
        for m in body.get("messages") or []:
            for c in m.get("tool_calls") or []:
                c["function"]["name"] = TOOL_MAP.get(c["function"]["name"], c["function"]["name"])
        body["stream"] = True
        body.setdefault("stream_options", {"include_usage": True})
        headers = {"Content-Type": "application/json", "Authorization": "Bearer public", "User-Agent": ZEN_UA,
                   "x-opencode-client": "cli", "x-opencode-project": "global", "x-opencode-session": session_id,
                   "x-opencode-session-id": session_id, "x-opencode-request": _rid("msg_")}
        t0 = time.monotonic()
        rec = {"prompt": 0, "completion": 0, "cached": 0, "status": 0}
        meter.calls.append(rec)  # counted when it starts (the answer can be fully read before this handler ends)
        resp = aweb.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as s:
                async with s.post(ZEN_URL, json=body, headers=headers) as up:
                    rec["status"] = up.status
                    if up.status >= 400:
                        txt = await up.text()
                        rec["error"] = txt[:300]
                        return aweb.Response(status=up.status, text=txt, content_type="application/json")
                    await resp.prepare(request)
                    buf = b""
                    async for chunk in up.content.iter_any():
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            await resp.write(rewrite(line, rec) + b"\n")
                    if buf:
                        await resp.write(rewrite(buf, rec))
        finally:
            rec["dt"] = round(time.monotonic() - t0, 2)
        await resp.write_eof()
        return resp

    app = aweb.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_post("/v1/chat/completions", handle)
    runner = aweb.AppRunner(app)
    await runner.setup()
    site = aweb.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}/v1", runner


# ---------------------------------------------------------------- runner -----

def setup_core(core: Path, home: Path, base_url: str, model: str, effort: str) -> None:
    sys.path.insert(0, str(core))
    os.environ.update({"NEOVARCH_HOME": str(home), "NEOVARCH_9ROUTER_SUPERVISE": "0", "NEOVARCH_9ROUTER_AUTOSTART": "0",
                       "NEOVARCH_9ROUTER_URL": "http://127.0.0.1:9/v1", "NEOVARCH_9ROUTER_DATA_DIR": str(home / "no9r"),
                       "NEOVARCH_9ROUTER_BIN": str(home / "no9r/x"),
                       "NEOVARCH_API_KEY": os.environ.get("NV_API_KEY", "public")})
    from neovarch.paths import ensure_home
    ensure_home()
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": model, "base_url": base_url, "context_length": 128000}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {})["harness_mode"] = "tempest"
    if effort:
        cfg["agent"]["reasoning_effort"] = effort
    cfg["timezone"] = "Asia/Jakarta"
    cfgmod.save_config(cfg)


async def run_agent(prompt: str, cwd: Path, budget_s: float) -> dict:
    from neovarch.agent import Agent
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext
    events = []
    store = SessionStore()
    rec = store.create(cwd=str(cwd))

    async def approve(*_a):
        return "once"

    agent = Agent(rec, store, ToolContext(cwd=cwd, approve=approve), lambda k, p: events.append((k, p)))
    out = {"final": "", "timed_out": False, "errors": []}
    try:
        out["final"] = await asyncio.wait_for(agent.run_turn(prompt), timeout=budget_s)
    except asyncio.TimeoutError:
        out["timed_out"] = True
    except Exception as exc:  # recorded, the task just fails
        out["errors"].append(f"{type(exc).__name__}: {exc}"[:400])
    out["errors"] += [str(p.get("message"))[:300] for k, p in events if k == "error"][:3]
    tools: dict[str, int] = {}
    for m in rec["messages"]:
        for c in m.get("tool_calls") or []:
            n = c["function"]["name"]
            tools[n] = tools.get(n, 0) + 1
    out["tools"] = tools
    out["steps"] = getattr(getattr(agent, "budget", None), "steps", None)
    out["status_kinds"] = sorted({p.get("kind", "?") for k, p in events if k == "status.update"})
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


async def grade_simpleqa(base_url: str, model: str, q: str, gold: str, answer: str) -> dict:
    sub = norm(gold) in norm(answer)
    verdict = None
    if GRADER and answer.strip():
        import aiohttp
        prompt = GRADER.format(question=q, target=gold, predicted_answer=answer[-3000:])
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
                async with s.post(base_url.rstrip("/") + "/chat/completions",
                                  json={"model": model, "stream": True, "messages": [{"role": "user", "content": prompt}]},
                                  headers={"Authorization": "Bearer public"}) as r:
                    text = ""
                    async for line in r.content:
                        if line.startswith(b"data:") and b"[DONE]" not in line:
                            try:
                                d = json.loads(line[5:])
                            except ValueError:
                                continue
                            for ch in d.get("choices") or []:
                                text += (ch.get("delta") or {}).get("content") or ""
            m = re.search(r"\b([ABC])\b", text.strip()[-20:]) or re.search(r"([ABC])", text)
            verdict = {"A": "CORRECT", "B": "INCORRECT", "C": "NOT_ATTEMPTED"}.get(m.group(1)) if m else None
        except Exception as exc:
            verdict = f"grader error {type(exc).__name__}"
    graded = verdict in ("CORRECT", "INCORRECT", "NOT_ATTEMPTED")
    return {"substring": sub, "grader": verdict, "pass": (verdict == "CORRECT") if graded else sub}


async def main_task(a) -> dict:
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"nvb-{a.label}-"))
    meter = Meter()
    runner = None
    base_url = a.base_url
    if a.zen:
        base_url, runner = await start_zen_adapter(meter)
    setup_core(Path(a.core), work / "home", base_url, a.model, a.effort)
    cache = Path(a.cache)
    row: dict = {"label": a.label, "suite": a.suite, "model": a.model, "effort": a.effort}
    t0 = time.monotonic()
    proj = work / "proj"
    proj.mkdir()
    if a.suite == "coding":
        name = CODING_IDS[int(a.task)] if str(a.task).isdigit() else a.task
        task = coding_task(name, cache)
        for f in task["dir"].iterdir():
            if f.name != "instructions.md":
                shutil.copy(f, proj / f.name)
        test_file = f"{task['module']}_test.py"
        prompt = (task["dir"] / "instructions.md").read_text(encoding="utf-8") + (
            f"\n\nImplement `{task['module']}.py` in the current directory so that `{test_file}` passes. "
            f"Use only the Python standard library. Do not modify `{test_file}`.")
        row["task_id"] = task["id"]
        res = await run_agent(prompt, proj, a.budget)
        row["agent_s"] = round(time.monotonic() - t0, 1)
        shutil.copy(task["dir"] / test_file, proj / test_file)  # grade against the untouched tests
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test_file], cwd=proj,
                           capture_output=True, text=True, timeout=120)
        row["pass"] = p.returncode == 0
        tail = (p.stdout or p.stderr or "").strip().splitlines()
        row["test_tail"] = tail[-1:] if tail else []
        n_agent = len(meter.calls)
    else:
        r = simpleqa_rows(cache)[int(a.task)]
        row["task_id"] = f"simpleqa/test/{r['index']}"
        row["question"], row["gold"] = r["problem"], r["answer"]
        prompt = r["problem"] + "\n\nCari di web dan jawab singkat (satu kalimat), sertakan URL sumber."
        res = await run_agent(prompt, proj, a.budget)
        row["agent_s"] = round(time.monotonic() - t0, 1)
        n_agent = len(meter.calls)
        row.update(await grade_simpleqa(base_url, a.model, r["problem"], r["answer"], res["final"]))
    calls = meter.calls[:n_agent]  # the grader call is not the agent's cost
    row["llm_calls"] = len(calls) if a.zen else None
    row["prompt_tokens"] = sum(c.get("prompt", 0) for c in calls)
    row["completion_tokens"] = sum(c.get("completion", 0) for c in calls)
    row["cached_tokens"] = sum(c.get("cached", 0) for c in calls)
    row["first_prompt_tokens"] = calls[0].get("prompt") if calls else None
    row["http_errors"] = [c.get("error") for c in calls if c.get("error")][:3]
    row.update({k: res[k] for k in ("steps", "tools", "timed_out", "errors", "status_kinds")})
    row["final"] = res["final"][-600:]
    with open(out_dir / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if runner is not None:
        await runner.cleanup()
    shutil.rmtree(work, ignore_errors=True)
    return row


def summary(out: Path) -> str:
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    lines = ["| suite | arm | n | pass | avg LLM calls | avg steps | avg agent s | avg prompt tok | avg compl tok |",
             "|---|---|---|---|---|---|---|---|---|"]
    for suite, label in sorted({(r["suite"], r["label"]) for r in rows}):
        rs = [r for r in rows if r["suite"] == suite and r["label"] == label]

        def avg(k):
            return round(sum((r.get(k) or 0) for r in rs) / len(rs), 1)
        lines.append(f"| {suite} | {label} | {len(rs)} | {sum(1 for r in rs if r.get('pass'))}/{len(rs)} | "
                     f"{avg('llm_calls')} | {avg('steps')} | {avg('agent_s')} | {avg('prompt_tokens')} | "
                     f"{avg('completion_tokens')} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", help="path to the core/ dir of the checkout under test")
    ap.add_argument("--label", default="run")
    ap.add_argument("--suite", choices=["coding", "web"], default="web")
    ap.add_argument("--task", default="0", help="index (or exercise name for coding)")
    ap.add_argument("--out", default="bench-runs")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/neovarch-bench"))
    ap.add_argument("--zen", action="store_true", help="OpenCode Zen free tier via the in-process adapter")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--model", default="mimo-v2.6-flash-free")
    ap.add_argument("--effort", default="ultra")
    ap.add_argument("--budget", type=float, default=420)
    ap.add_argument("--summary", help="print the table for a results dir")
    a = ap.parse_args()
    if a.summary:
        print(summary(Path(a.summary)))
    else:
        print(json.dumps(asyncio.run(main_task(a)), ensure_ascii=False))
