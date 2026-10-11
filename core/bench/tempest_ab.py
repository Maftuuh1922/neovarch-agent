"""Deterministic A/B replay: legacy harness vs Tempest arms, through the real Agent loop.

No live model: ``neovarch.agent.stream_chat`` is replaced by a scripted policy per task
(bench/tempest_tasks.py) that reacts only to what the harness shows it (tool output,
"rejected:", verify/lint feedback, masked observations, recited progress). Tools, files,
pytest, git and the harness code all run for real; only the model's choices are simulated.
Tokens: tiktoken cl100k_base on the exact wire (tools schema + messages) the harness sends.

Cache accounting (per run, across all calls and sessions):

* OpenAI-style arms (default): automatic exact-prefix cache - the leading wire chunks identical
  to the previous call count as cached (>=1024 tokens, 128-token steps), like OpenAI/DeepSeek/
  most 9Router upstreams.
* ``@anth`` arms: Anthropic-style explicit cache - nothing is cached unless the request carries
  ``cache_control`` breakpoints; a read hits the longest previously written breakpoint prefix
  within a 20-block lookback; written segments cost 1.25x, reads 0.1x.

The clock is simulated (+3 minutes per user turn) so runs are deterministic and a harness
that puts the time in its system prompt pays for it the way it would in a real chat.

    python3 bench/tempest_ab.py run <task> <arm> [seed]            # one run -> JSON line
    python3 bench/tempest_ab.py all OUT.jsonl [--arms a,b] [--tasks x,y] [--seeds 0,1,2] [--jobs 2]
    python3 bench/tempest_report.py OUT.jsonl                      # tables
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
RUNS = Path(os.environ.get("TEMPEST_BENCH_DIR", "/workspace/work/tempest-bench-runs"))

from tempest_tasks import TASKS, P  # noqa: E402

# Assumed price of a cheap OpenAI-compatible model (USD per 1M tokens). Not a quote.
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.30, 0.03, 1.20
# Anthropic-style multipliers on PRICE_IN (docs: read 0.1x, 5-minute write 1.25x).
ANTH_READ, ANTH_WRITE = 0.10, 1.25

_OFF = {"tempest_cache_v2": False, "tempest_compact": False, "tempest_lint_gate": False,
        "tempest_checkpoints": False, "tempest_progress": False}
_NOMASK = {"harness_mode": "tempest", "tempest_profile": "ringan", "tempest_mask": False,
           "tempest_mask_mode": "off", **_OFF}

# arm -> (agent.* overrides, model name). Feature arms are tempest-nomask + one feature, so an
# arm means the same thing whatever the shipped defaults are; "tempest-default" sets nothing.
ARMS: dict[str, tuple[dict, str]] = {
    "legacy": ({"harness_mode": "legacy"}, "bench-model"),
    "tempest-mask": ({**_NOMASK, "tempest_mask": True, "tempest_mask_mode": "turn"}, "bench-model"),
    "tempest-nomask": (dict(_NOMASK), "bench-model"),
    "tempest-tinggi": ({"harness_mode": "tempest", "tempest_profile": "tinggi", **_OFF}, "bench-model"),
    "+cache2": ({**_NOMASK, "tempest_cache_v2": True}, "bench-model"),
    "+compact": ({**_NOMASK, "tempest_compact": True, "tempest_mask_mode": "compact"}, "bench-model"),
    "+lint": ({**_NOMASK, "tempest_lint_gate": True}, "bench-model"),
    "+ckpt": ({**_NOMASK, "tempest_checkpoints": True}, "bench-model"),
    "+progress": ({**_NOMASK, "tempest_progress": True}, "bench-model"),
    "tempest-default": ({"harness_mode": "tempest"}, "bench-model"),
    "legacy@anth": ({"harness_mode": "legacy"}, "claude-bench-haiku"),
    "nomask@anth": (dict(_NOMASK), "claude-bench-haiku"),
    "+cache2@anth": ({**_NOMASK, "tempest_cache_v2": True}, "claude-bench-haiku"),
    "default@anth": ({"harness_mode": "tempest"}, "claude-bench-haiku"),
}
DEFAULT_ARMS = ["legacy", "tempest-mask", "tempest-nomask", "tempest-default",
                "legacy@anth", "nomask@anth", "default@anth"]

# ----------------------------------------------------------------- tokens -----

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def ntok(s: str) -> int:
        return len(_ENC.encode(s, disallowed_special=()))
    TOKENIZER = "tiktoken cl100k_base"
except Exception:  # pragma: no cover
    def ntok(s: str) -> int:
        return (len(s) + 3) // 4
    TOKENIZER = "chars/4"


def serialize(tools, messages) -> list[tuple[str, bool]]:
    """Wire as chunks in provider order (tools, then each message / content part).

    Returns (chunk_text, is_cache_breakpoint). A list-content message contributes one chunk
    per part so a breakpoint inside the system message lands where the harness put it."""
    tools = tools or []
    out = [(json.dumps(tools, ensure_ascii=False, sort_keys=True),
            bool(tools and isinstance(tools[-1], dict) and tools[-1].get("cache_control")))]
    for m in messages:
        head = {k: m[k] for k in ("role", "tool_calls", "tool_call_id") if k in m}
        c = m.get("content")
        if isinstance(c, list) and c:
            for i, part in enumerate(c):
                body = dict(head) if i == 0 else {"role": m.get("role"), "part": i}
                body["content"] = {k: v for k, v in part.items() if k != "cache_control"}
                out.append((json.dumps(body, ensure_ascii=False, sort_keys=True), bool(part.get("cache_control"))))
        else:
            body = dict(head)
            body["content"] = c
            out.append((json.dumps(body, ensure_ascii=False, sort_keys=True), bool(m.get("cache_control"))))
    return out


class CacheSim:
    """Provider cache across all calls of one run."""

    def __init__(self, style: str):
        self.style = style
        self.prev: list[str] | None = None
        self.written: set[str] = set()

    def account(self, chunks: list[tuple[str, bool]], toks: list[int]) -> tuple[int, int]:
        """(cache_read, cache_write) tokens for this call."""
        texts = [c for c, _ in chunks]
        if self.style == "openai":
            cached = 0
            if self.prev is not None:
                for a, b, t in zip(self.prev, texts, toks):
                    if a != b:
                        break
                    cached += t
            self.prev = texts
            return ((cached // 128) * 128 if cached >= 1024 else 0), 0
        # anthropic: explicit breakpoints, 20-block lookback, min 1024 tokens
        hashes, cum, h, total = [], [], hashlib.sha256(), 0
        for text, t in zip(texts, toks):
            h.update(text.encode())
            hashes.append(h.copy().hexdigest())
            total += t
            cum.append(total)
        bps = [i for i, (_, bp) in enumerate(chunks) if bp]
        if not bps:
            return 0, 0
        hit = -1
        for b in bps:
            for j in range(b, max(b - 20, -1), -1):
                if hashes[j] in self.written:
                    hit = max(hit, j)
                    break
        read = cum[hit] if hit >= 0 and cum[hit] >= 1024 else 0
        last = bps[-1]
        write = max(cum[last] - read, 0) if cum[last] >= 1024 else 0
        for b in bps:
            self.written.add(hashes[b])
        return read, write


# ------------------------------------------------------------------ hooks -----

def hook_add_memory_and_skill(agent, root: Path, home: Path) -> None:
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "memory" / "proyek.md").write_text("kode-proyek: TULIP-7 (dipakai di nama rilis)\n", encoding="utf-8")
    sk = home / "skills" / "bench-skill"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("---\nname: bench-skill\ndescription: contoh skill yang baru dipasang\n---\nIsi.\n",
                                 encoding="utf-8")


def hook_chdir_sub(agent, root: Path, home: Path) -> None:
    agent.ctx.cwd = root / "sub"


HOOKS = {"add_memory_and_skill": hook_add_memory_and_skill, "chdir_sub": hook_chdir_sub}


# ------------------------------------------------------------------ run one -----

def run_one(task: str, arm: str, seed: int = 0) -> dict:
    spec = TASKS[task]
    overrides, model_name = ARMS[arm]
    base = RUNS / f"{task}--{arm.replace('@', '_at_').replace('+', 'plus-')}--s{seed}"
    if base.exists():
        shutil.rmtree(base)
    root, home = base / "proj", base / "home"
    root.mkdir(parents=True)
    os.environ.update({"NEOVARCH_HOME": str(home), "NEOVARCH_9ROUTER_SUPERVISE": "0",
                       "NEOVARCH_9ROUTER_AUTOSTART": "0", "NEOVARCH_9ROUTER_URL": "http://127.0.0.1:9/v1",
                       "NEOVARCH_9ROUTER_DATA_DIR": str(base / "no9r"), "NEOVARCH_9ROUTER_BIN": str(base / "no9r/x"),
                       "NEOVARCH_API_KEY": "bench"})
    spec["fixture"](root, seed)
    from neovarch.paths import ensure_home
    ensure_home()
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": model_name, "base_url": "http://127.0.0.1:9/v1",
                    "context_length": spec["window"]}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {})["max_turns"] = 60
    cfg["agent"].update(overrides)
    cfg["timezone"] = "Asia/Jakarta"
    vault = base / "proj-vault"
    if vault.exists():
        cfg["memory"] = {"obsidian_vault": str(vault), "obsidian_enabled": True}
    cfgmod.save_config(cfg)

    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion, LLMError
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    clock = {"turn": 0}
    agentmod.now_text = lambda _cfg: f"2026-10-11 {9 + (clock['turn'] * 3) // 60:02d}:{(clock['turn'] * 3) % 60:02d} Asia/Jakarta"

    calls: list[dict] = []
    state: dict = {}
    helper = P()
    sim = CacheSim("anthropic" if "@anth" in arm else "openai")
    prev_chunks: list = [None]
    window = spec["window"]
    overflow = [0]

    async def fake_stream_chat(*, base_url, api_key, model, messages, tools=None, on_text=None,
                               on_reasoning=None, **_kw):
        chunks = serialize(tools or [], messages)
        toks = [ntok(c) + 4 for c, _ in chunks]
        total = sum(toks)
        texts = [c for c, _ in chunks]
        brk = False
        if prev_chunks[0] is not None and len(prev_chunks[0]) > 1:
            pv = prev_chunks[0]
            # a prefix break = something before the previous call's last chunk changed
            brk = len(texts) < len(pv) - 1 or any(a != b for a, b in zip(pv[:-1], texts))
        prev_chunks[0] = texts
        if total > window:
            overflow[0] += 1
            calls.append({"input": total, "cached": 0, "written": 0, "output": 0, "brk": brk, "overflow": True})
            raise LLMError(f"provider returned HTTP 400: context_length_exceeded ({total} > {window} tokens)")
        read, write = sim.account(chunks, toks)
        state["_tools"] = {t.get("function", {}).get("name") for t in (tools or []) if isinstance(t, dict)}
        text, tcs = spec["policy"](state, messages, helper, root)
        out_tok = ntok(text) + sum(ntok(c.arguments) + 8 for c in tcs)
        calls.append({"input": total, "cached": read, "written": write, "output": out_tok, "brk": brk})
        if text and on_text:
            on_text(text)
        return Completion(text=text, tool_calls=tcs, usage={"prompt_tokens": total, "completion_tokens": out_tok})

    agentmod.stream_chat = fake_stream_chat
    store = SessionStore()
    events: list = []

    async def approve(*_a):
        return "once"

    sessions = spec.get("sessions") or [(spec["prompts"], 60)]
    hooks = spec.get("hooks") or {}
    finals: list[str] = []
    recs: list[dict] = []
    t0 = time.monotonic()

    async def go():
        turn_idx = 0
        for si, (prompts, max_turns) in enumerate(sessions):
            c = cfgmod.load_config()
            c["agent"]["max_turns"] = max_turns
            cfgmod.save_config(c)
            state["_session"] = si
            prev_chunks[0] = None  # a new chat; prefix checks restart
            rec = store.create(cwd=str(root))
            recs.append(rec)
            agent = Agent(rec, store, ToolContext(cwd=root, approve=approve), lambda k, pl: events.append((k, pl)))
            for q in prompts:
                if turn_idx in hooks:
                    HOOKS[hooks[turn_idx]](agent, root, home)
                clock["turn"] = turn_idx
                finals.append(await agent.run_turn(q))
                turn_idx += 1
    asyncio.run(go())
    wall = time.monotonic() - t0
    final = finals[-1] if finals else ""
    if spec.get("check_all"):
        passed = bool(spec["check_all"](root, finals))
    else:
        passed = bool(spec["check"](root, final))
    tin = sum(c["input"] for c in calls)
    tread = sum(c["cached"] for c in calls)
    twrite = sum(c["written"] for c in calls)
    tout = sum(c["output"] for c in calls)
    errors = [pl.get("message") for k, pl in events if k == "error"]
    status_kinds: dict[str, int] = {}
    for k, pl in events:
        if k == "status.update":
            status_kinds[pl.get("kind", "?")] = status_kinds.get(pl.get("kind", "?"), 0) + 1
    msgs = [m for r in recs for m in r.get("messages", [])]
    if "@anth" in arm:
        cost = ((tin - tread - twrite) * PRICE_IN + twrite * PRICE_IN * ANTH_WRITE + tread * PRICE_IN * ANTH_READ
                + tout * PRICE_OUT) / 1e6
    else:
        cost = ((tin - tread) * PRICE_IN + tread * PRICE_CACHED + tout * PRICE_OUT) / 1e6
    return {
        "task": task, "arm": arm, "seed": seed, "family": spec["family"], "split": spec["split"],
        "passed": passed, "turns": len(calls), "input_tokens": tin, "cache_read": tread, "cache_write": twrite,
        "cache_read_ratio": round(tread / tin, 4) if tin else 0.0, "input_uncached": tin - tread,
        "output_tokens": tout, "peak_context": max((c["input"] for c in calls), default=0),
        "prefix_breaks": sum(1 for c in calls if c["brk"]), "overflow": overflow[0],
        "cost_usd": cost, "cost_nocache_usd": (tin * PRICE_IN + tout * PRICE_OUT) / 1e6,
        "wall_s": round(wall, 2), "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "rereads": state.get("rereads", 0), "false_reject": bool(state.get("false_reject")),
        "verify_feedback": sum(1 for m in msgs if m.get("kind") == "verify"),
        "lint_feedback": sum(1 for m in msgs if m.get("kind") == "lint"),
        "status": status_kinds, "errors": errors[:5], "final": final[:300],
    }


def _run_sub(task: str, arm: str, seed: int) -> dict:
    try:
        r = subprocess.run([sys.executable, __file__, "run", task, arm, str(seed)], capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        return {"task": task, "arm": arm, "seed": seed, "crash": "timeout"}
    line = (r.stdout.strip().splitlines() or [""])[-1]
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"task": task, "arm": arm, "seed": seed, "family": TASKS[task]["family"],
                "split": TASKS[task]["split"], "crash": (r.stderr or r.stdout)[-2000:]}


def main() -> None:
    if sys.argv[1] == "run":
        seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        print(json.dumps(run_one(sys.argv[2], sys.argv[3], seed)))
        return
    if sys.argv[1] != "all":
        raise SystemExit(__doc__)
    out = Path(sys.argv[2])
    opts = {"--arms": ",".join(DEFAULT_ARMS), "--tasks": ",".join(TASKS), "--seeds": "", "--jobs": "2"}
    args = sys.argv[3:]
    for i in range(0, len(args) - 1, 2):
        opts[args[i]] = args[i + 1]
    arms = [a for a in opts["--arms"].split(",") if a]
    tasks = [t for t in opts["--tasks"].split(",") if t]
    todo = []
    done = set()
    if out.exists():  # resume: keep finished runs
        for line in out.read_text().splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "crash" not in d:
                done.add((d["task"], d["arm"], d["seed"]))
    for t in tasks:
        seeds = [int(s) for s in opts["--seeds"].split(",")] if opts["--seeds"] else list(TASKS[t]["seeds"])
        for s in seeds:
            if s not in TASKS[t]["seeds"]:
                continue
            for a in arms:
                if (t, a, s) not in done:
                    todo.append((t, a, s))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(todo)} runs ({len(done)} already done)", flush=True)
    with ThreadPoolExecutor(max_workers=int(opts["--jobs"])) as pool, out.open("a") as fh:
        for res in pool.map(lambda x: _run_sub(*x), todo):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            print(res["task"], res["arm"], res["seed"], "CRASH" if "crash" in res else res["passed"], flush=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
