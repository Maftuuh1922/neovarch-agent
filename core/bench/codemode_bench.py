"""Codemode bench: the same work with and without codemode, through the real Agent loop.

No live model: ``neovarch.agent.stream_chat`` is replaced by a replay of hand-written trajectories
(bench/codemode_tasks.py). Tools, files, pytest and the whole Tempest harness run for real; only
the model's choices are fixed. So this measures what the *harness* costs for identical work -
model calls, prompt tokens (incl. an exact-prefix cache estimate), wall time - not model quality.
Pass/fail is checked on the real repo afterwards (tests / answer), as a sanity check that both
arms really did the work.

Arms (same tasks, same final answers):
  per-call   one tool call per model message (the call-per-tool loop of Pi/Codex-style harnesses);
             codemode tool off
  parallel   independent reads of one step batched into one model message (Neovarch's existing
             parallel_tools); codemode tool off
  codemode   codemode on; the trajectory uses one program per step

Tokens: tiktoken cl100k_base when installed, else chars/4, over the exact request (tools + messages).
Cache: OpenAI-style automatic exact-prefix cache - the common prefix with the previous request
counts as cached when >= 1024 tokens, in 128-token steps.

    python3 bench/codemode_bench.py run <task> <arm>          # one run -> JSON line
    python3 bench/codemode_bench.py all OUT.jsonl [--arms a,b] [--tasks x,y]
    python3 bench/codemode_bench.py report OUT.jsonl [--latency 2.5]
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from codemode_tasks import BY_ID, TASKS, setup_repo  # noqa: E402

ARMS = ("per-call", "parallel", "codemode")
READS = {"read_file", "grep", "glob", "web_fetch", "web_search", "repo_map"}

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def ntok(text: str) -> int:
        return len(_ENC.encode(text, disallowed_special=()))
    TOKENIZER = "tiktoken cl100k_base"
except Exception:  # pragma: no cover - fallback
    def ntok(text: str) -> int:
        return (len(text) + 3) // 4
    TOKENIZER = "chars/4"


def trajectory(task, arm: str) -> list[list[tuple[str, dict]]]:
    if arm == "codemode":
        return task.cm
    if arm == "per-call":
        return [[c] for step in task.steps for c in step]
    out: list[list[tuple[str, dict]]] = []  # parallel: merge consecutive read-only single-call steps
    for step in task.steps:
        if out and all(n in READS for n, _ in step) and all(n in READS for n, _ in out[-1]):
            out[-1] = out[-1] + step
        else:
            out.append(list(step))
    return out


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    step = 4096
    while i < n:
        j = min(i + step, n)
        if a[i:j] == b[i:j]:
            i = j
            continue
        while i < j and a[i] == b[i]:
            i += 1
        break
    return i


async def _run(task_id: str, arm: str) -> dict:
    task = BY_ID[task_id]
    home = Path(tempfile.mkdtemp(prefix="cmb-home-"))
    repo = Path(tempfile.mkdtemp(prefix="cmb-repo-"))
    os.environ["NEOVARCH_HOME"] = str(home)
    os.environ["NEOVARCH_API_KEY"] = "bench"
    setup_repo(repo)
    from neovarch import config as cfgmod
    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion, ToolCall
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "bench-model", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update({"harness_mode": "tempest", "tempest_codemode": arm == "codemode",
                                        "tempest_skill_learn": "off", "tempest_memory_nudge": False})
    cfgmod.save_config(cfg)

    script = [[ToolCall(id=f"c{i}_{j}", name=n, arguments=json.dumps(a)) for j, (n, a) in enumerate(step)]
              for i, step in enumerate(trajectory(task, arm))]
    calls: list[dict] = []
    prev = [""]

    async def fake(*, messages, tools=None, **_kw):
        req = json.dumps({"tools": tools, "messages": messages}, ensure_ascii=False, sort_keys=False)
        prompt = ntok(req)
        cached = 0
        if prev[0]:
            pre = _common_prefix(prev[0], req)
            cached_t = ntok(req[:pre])
            cached = (cached_t // 128) * 128 if cached_t >= 1024 else 0
        prev[0] = req
        if script:
            step = script.pop(0)
            comp = Completion(text="", tool_calls=step)
            out_text = json.dumps([{"name": c.name, "arguments": c.arguments} for c in step], ensure_ascii=False)
        else:
            comp = Completion(text=task.final)
            out_text = task.final
        calls.append({"prompt": prompt, "cached": min(cached, prompt), "output": ntok(out_text),
                      "tools": [c.name for c in comp.tool_calls]})
        return comp

    agentmod.stream_chat = fake
    store = SessionStore()
    rec = store.create(cwd=str(repo))
    agent = Agent(rec, store, ToolContext(cwd=repo, approve=None), lambda k, p: None)
    t0 = time.monotonic()
    final = await agent.run_turn(task.prompt)
    wall = time.monotonic() - t0
    ok = bool(task.check(repo, final or ""))
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    if os.environ.get("CMB_DUMP"):
        for m in tool_msgs:
            print(f"--- {m.get('name')}\n{str(m.get('content'))[:1500]}", file=sys.stderr)
    executed = [t["name"] for t in agent.ledger.tools]
    row = {"task": task_id, "kind": task.kind, "arm": arm, "pass": ok, "model_calls": len(calls),
           "prompt_tokens": sum(c["prompt"] for c in calls), "cached_tokens": sum(c["cached"] for c in calls),
           "output_tokens": sum(c["output"] for c in calls),
           "first_prompt_tokens": calls[0]["prompt"] if calls else 0,
           "final_context_tokens": calls[-1]["prompt"] if calls else 0,
           "tool_results_in_context": len(tool_msgs),
           "tool_result_chars": sum(len(str(m.get("content") or "")) for m in tool_msgs),
           "tools_executed": len(executed), "wall_s": round(wall, 3), "tokenizer": TOKENIZER,
           "script_left": len(script)}
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(repo, ignore_errors=True)
    return row


def run_one(task_id: str, arm: str) -> dict:
    return asyncio.run(_run(task_id, arm))


def run_all(out: Path, arms: list[str], tasks: list[str]) -> None:
    with out.open("a", encoding="utf-8") as fh:
        for t in tasks:
            for a in arms:
                r = subprocess.run([sys.executable, __file__, "run", t, a], capture_output=True, text=True,
                                   timeout=300, cwd=str(CORE))
                line = (r.stdout.strip().splitlines() or [""])[-1]
                if not line.startswith("{"):
                    line = json.dumps({"task": t, "arm": a, "error": (r.stderr or r.stdout)[-800:]})
                fh.write(line + "\n")
                fh.flush()
                print(line[:200])


def report(path: Path, latency: float = 2.5) -> str:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if "error" not in r]
    by: dict[str, dict[str, dict]] = {}
    for r in rows:
        by.setdefault(r["task"], {})[r["arm"]] = r
    arms = [a for a in ARMS if any(a in v for v in by.values())]
    tasks = [t.id for t in TASKS if t.id in by and all(a in by[t.id] for a in arms)]

    def tot(arm: str, key: str) -> float:
        return sum(by[t][arm][key] for t in tasks)
    lines = [f"Tugas: {len(tasks)} | tokenizer: {rows[0]['tokenizer'] if rows else '-'} | "
             f"latensi model diasumsikan {latency}s/panggilan untuk kolom 'waktu+model'", "",
             "| Arm | Lulus | Panggilan model | Token prompt | Token prompt tak-ter-cache | Token output | "
             "Waktu alat (s) | Waktu+model (s) |", "|---|---|---|---|---|---|---|---|"]
    for a in arms:
        calls = tot(a, "model_calls")
        lines.append(f"| {a} | {sum(by[t][a]['pass'] for t in tasks)}/{len(tasks)} | {calls:.0f} | "
                     f"{tot(a, 'prompt_tokens'):,.0f} | {tot(a, 'prompt_tokens') - tot(a, 'cached_tokens'):,.0f} | "
                     f"{tot(a, 'output_tokens'):,.0f} | {tot(a, 'wall_s'):.1f} | {tot(a, 'wall_s') + calls * latency:.1f} |")
    if "codemode" in arms:
        lines += ["", "Selisih codemode dibanding arm lain (negatif = lebih hemat):", ""]
        for a in arms:
            if a == "codemode":
                continue
            def pct(k):
                base = tot(a, k)
                return f"{100 * (tot('codemode', k) - base) / base:+.0f}%" if base else "-"
            unc_b = tot(a, "prompt_tokens") - tot(a, "cached_tokens")
            unc_c = tot("codemode", "prompt_tokens") - tot("codemode", "cached_tokens")
            lines.append(f"- vs {a}: panggilan model {pct('model_calls')}, token prompt {pct('prompt_tokens')}, "
                         f"tak-ter-cache {100 * (unc_c - unc_b) / unc_b:+.0f}%, token output {pct('output_tokens')}, "
                         f"waktu alat {pct('wall_s')}")
    lines += ["", "| Tugas | " + " | ".join(f"{a} (lulus/panggilan/token prompt)" for a in arms) + " |",
              "|---|" + "---|" * len(arms)]
    for t in tasks:
        cells = [f"{'✔' if by[t][a]['pass'] else '✘'} {by[t][a]['model_calls']} / {by[t][a]['prompt_tokens']:,}"
                 for a in arms]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[0] == "run":
        print(json.dumps(run_one(argv[1], argv[2]), ensure_ascii=False))
        return
    if argv and argv[0] == "all":
        out = Path(argv[1])
        arms = list(ARMS)
        tasks = [t.id for t in TASKS]
        if "--arms" in argv:
            arms = argv[argv.index("--arms") + 1].split(",")
        if "--tasks" in argv:
            tasks = argv[argv.index("--tasks") + 1].split(",")
        run_all(out, arms, tasks)
        return
    if argv and argv[0] == "report":
        lat = float(argv[argv.index("--latency") + 1]) if "--latency" in argv else 2.5
        print(report(Path(argv[1]), lat))
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
