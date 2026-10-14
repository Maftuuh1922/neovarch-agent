"""Codemode: one sandboxed Python program calls many tools in one model call."""

import asyncio
import json
import time

import pytest

from neovarch import codemode, tempest, tempest_diet


# ---------------------------------------------------------------- runner (no agent)

async def _echo(name, args):
    await asyncio.sleep(0.3)
    return f"{name}:{json.dumps(args, sort_keys=True)}"


@pytest.mark.asyncio
async def test_parallel_batch_runs_together_and_keeps_order(tmp_path):
    code = ("r = tools.parallel([('read_file', {'path': 'a'}), ('grep', {'pattern': 'x'}), "
            "('read_file', {'path': 'b'})])\nprint('|'.join(r))")
    t0 = time.monotonic()
    out, st = await codemode.run(code, _echo, tmp_path, is_parallel_safe=lambda n, a: True)
    took = time.monotonic() - t0
    assert 'read_file:{"path": "a"}|grep:{"pattern": "x"}|read_file:{"path": "b"}' in out
    assert st.calls == 3 and st.parallel_calls == 3 and st.batches == 1
    assert took < 0.3 * 3  # three 0.3 s calls overlapped
    assert "[codemode: 3 panggilan alat, 3 paralel" in out


@pytest.mark.asyncio
async def test_unsafe_calls_run_in_order(tmp_path):
    order = []

    async def disp(name, args):
        order.append(args["i"])
        await asyncio.sleep(0.05 * (3 - args["i"]))
        return str(args["i"])
    code = "print(tools.parallel([('write_file', {'i': 0}), ('write_file', {'i': 1}), ('write_file', {'i': 2})]))"
    out, st = await codemode.run(code, disp, tmp_path, is_parallel_safe=lambda n, a: False)
    assert order == [0, 1, 2] and st.parallel_calls == 0
    assert "['0', '1', '2']" in out


@pytest.mark.asyncio
async def test_attribute_and_call_forms(tmp_path):
    code = "print(tools.read_file(path='x'))\nprint(tools.call('grep', pattern='y'))"
    out, st = await codemode.run(code, _echo, tmp_path)
    assert 'read_file:{"path": "x"}' in out and 'grep:{"pattern": "y"}' in out and st.calls == 2


@pytest.mark.asyncio
async def test_guard_rails_block_side_effects(tmp_path):
    (tmp_path / "in.txt").write_text("isi", encoding="utf-8")
    code = """
for label, fn in [
    ("write", lambda: open("out.txt", "w")),
    ("net", lambda: __import__("socket").create_connection(("example.com", 80))),
    ("proc", lambda: __import__("subprocess").run(["echo", "x"])),
    ("system", lambda: __import__("os").system("echo x")),
    ("rm", lambda: __import__("os").remove("in.txt")),
    ("path", lambda: __import__("pathlib").Path("p.txt").write_text("x")),
]:
    try:
        fn(); print(label, "LOLOS")
    except PermissionError:
        print(label, "diblokir")
print(open("in.txt").read())
"""
    out, _ = await codemode.run(code, _echo, tmp_path)
    assert "LOLOS" not in out
    for label in ("write", "net", "proc", "system", "rm", "path"):
        assert f"{label} diblokir" in out
    assert "isi" in out  # reading is fine
    assert not (tmp_path / "out.txt").exists() and (tmp_path / "in.txt").exists()


@pytest.mark.asyncio
async def test_timeout_kills_program(tmp_path):
    t0 = time.monotonic()
    out, _ = await codemode.run("while True:\n    pass", _echo, tmp_path, timeout=1)
    assert "timeout" in out and time.monotonic() - t0 < 8


@pytest.mark.asyncio
async def test_error_and_empty_output_are_reported(tmp_path):
    out, _ = await codemode.run("print('sebagian')\n1/0", _echo, tmp_path)
    assert "sebagian" in out and "ZeroDivisionError" in out
    out, _ = await codemode.run("x = 1", _echo, tmp_path)
    assert "tidak mencetak" in out
    out, _ = await codemode.run("   ", _echo, tmp_path)
    assert out.startswith("error")


@pytest.mark.asyncio
async def test_call_limit_and_blocked_tools(tmp_path):
    code = ("print(tools.codemode(code='1'))\nprint(tools.extra_tool(action='run', name='x'))\n"
            "try:\n    tools.parallel([('read_file', {})] * 17)\nexcept ToolError as e:\n    print('batch', e)\n"
            "n = 0\ntry:\n    for _ in range(100):\n        tools.read_file(path='a'); n += 1\n"
            "except ToolError as e:\n    print('limit', n, e)")

    async def fast(name, args):
        return "ok"
    out, st = await codemode.run(code, fast, tmp_path)
    assert "tidak bisa dipanggil dari dalam codemode" in out
    assert "batch maks 16" in out
    assert f"limit {codemode.MAX_CALLS - 2}" in out
    assert st.calls == codemode.MAX_CALLS


@pytest.mark.asyncio
async def test_list_and_describe(tmp_path):
    sent = [{"type": "function", "function": {"name": "read_file", "description": "Read a file. More."}},
            {"type": "function", "function": {"name": "codemode", "description": "x"}}]
    deferred = {"repo_map": {"type": "function", "function": {"name": "repo_map", "description": "Map symbols.",
                                                              "parameters": {"type": "object"}}}}
    by_name = {"repo_map": deferred["repo_map"]}
    out, _ = await codemode.run("print(tools.list())\nprint(tools.describe('repo_map'))\nprint(tools.describe('zz'))",
                                _echo, tmp_path, list_tools=lambda: codemode.tool_list_text(sent, deferred),
                                describe_tool=lambda n: codemode.describe_text(n, by_name))
    assert "Alat inti: read_file" in out and "codemode" not in out.split("\n")[0]
    assert "- repo_map: Map symbols" in out and '"parameters"' in out and "tidak ada" in out


def test_schema_static_and_flag_default():
    assert codemode.SCHEMA == json.loads(json.dumps(codemode.SCHEMA))
    assert tempest.FEATURE_DEFAULTS["codemode"] is True
    assert "codemode" in tempest_diet.CORE_TOOLS
    assert codemode.config_allows_network({"agent": {"tempest_codemode_network": True}})
    assert not codemode.config_allows_network({})


# ---------------------------------------------------------------- inside the agent

def _cfg(agent_cfg, approvals="off"):
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": approvals}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)


def _agent(tmp_path, monkeypatch, script, seen, tools_seen, approve=None):
    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")

    async def fake(*, messages, tools=None, **_kw):
        seen.append(messages)
        tools_seen.append(json.dumps(tools, sort_keys=True))
        text, calls = script.pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    events = []
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=approve), lambda k, p: events.append((k, p)))
    return agent, rec, events


def _call(cid, tool, **args):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name=tool, arguments=json.dumps(args))


def _names(tools_json):
    return [t["function"]["name"] for t in json.loads(tools_json)]


@pytest.mark.asyncio
async def test_agent_one_program_reads_greps_and_runs(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_lint_gate": False, "tempest_claim_gate": False})
    for i in range(3):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    code = ("files = tools.glob(pattern='*.py')\n"
            "reads = tools.parallel([('read_file', {'path': p}) for p in ['m0.py', 'm1.py', 'm2.py']])\n"
            "hit = tools.grep(pattern='return 2')\n"
            "run = tools.shell(command='echo tests-ok')\n"
            "print(len(reads), 'return 2' in hit, run.strip().splitlines()[-1] if run.strip() else run)")
    seen, tools_seen = [], []
    script = [("", [_call("c1", "codemode", code=code)]), ("selesai", []), ("lagi", [])]
    agent, rec, events = _agent(tmp_path, monkeypatch, script, seen, tools_seen)
    await agent.run_turn("cek modul")
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    out = tool_msgs[0]["content"]
    assert "3 True" in out and "tests-ok" in out and "6 panggilan alat" in out
    subs = [p for k, p in events if k == "tool.start" and p.get("via") == "codemode"]
    assert [s["name"] for s in subs].count("read_file") == 3 and all(s["parent"] == "c1" for s in subs)
    assert any(t["name"] == "shell" for t in agent.ledger.tools)  # evidence gate sees the test run
    assert "codemode" in _names(tools_seen[0])
    await agent.run_turn("halo")
    assert len(set(tools_seen)) == 1 and seen[0][0] == seen[-1][0]  # cache-stable prefix


@pytest.mark.asyncio
async def test_agent_writes_go_through_syntax_gate(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_lint_gate": False, "tempest_claim_gate": False})
    code = ("print(tools.write_file(path='ok.py', content='x = 1\\n'))\n"
            "print(tools.write_file(path='bad.py', content='def (:\\n'))")
    seen, tools_seen = [], []
    agent, rec, _ = _agent(tmp_path, monkeypatch, [("", [_call("c1", "codemode", code=code)]), ("ok", [])],
                           seen, tools_seen)
    await agent.run_turn("tulis")
    out = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert (tmp_path / "ok.py").read_text() == "x = 1\n"
    assert "rejected" in out and not (tmp_path / "bad.py").exists()


@pytest.mark.asyncio
async def test_agent_dangerous_shell_still_asks(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_lint_gate": False, "tempest_claim_gate": False}, approvals="ask")
    asked = []

    async def approve(cmd, why, kind):
        asked.append(cmd)
        return "deny"
    code = "print(tools.shell(command='rm -rf ./data'))"
    seen, tools_seen = [], []
    agent, rec, _ = _agent(tmp_path, monkeypatch, [("", [_call("c1", "codemode", code=code)]), ("ok", [])],
                           seen, tools_seen, approve=approve)
    await agent.run_turn("hapus")
    out = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert asked == ["rm -rf ./data"] and "denied" in out


@pytest.mark.asyncio
async def test_agent_plan_mode_refuses_writes_inside_program(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_lint_gate": False, "tempest_claim_gate": False})
    code = "print(tools.write_file(path='x.txt', content='a'))\nprint(tools.glob(pattern='*'))"
    seen, tools_seen = [], []
    agent, rec, _ = _agent(tmp_path, monkeypatch, [("", [_call("c1", "codemode", code=code)]), ("rencana", [])],
                           seen, tools_seen)
    await agent.run_turn("/rencana ubah x")
    out = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert "mode rencana" in out and not (tmp_path / "x.txt").exists()


@pytest.mark.asyncio
async def test_agent_deferred_tool_from_program(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_lint_gate": False, "tempest_claim_gate": False})
    (tmp_path / "a.py").write_text("class A:\n    def go(self):\n        pass\n", encoding="utf-8")
    code = "print('repo_map' in tools.list())\nprint(tools.repo_map()[:400])"
    seen, tools_seen = [], []
    agent, rec, _ = _agent(tmp_path, monkeypatch, [("", [_call("c1", "codemode", code=code)]), ("ok", [])],
                           seen, tools_seen)
    await agent.run_turn("peta")
    out = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert out.startswith("True\nrepo_map ") and "error" not in out[:300]
    assert "repo_map" not in _names(tools_seen[0])  # still deferred in the sent list


@pytest.mark.asyncio
async def test_flag_off_removes_tool(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_codemode": False})
    seen, tools_seen = [], []
    agent, _, _ = _agent(tmp_path, monkeypatch, [("ok", [])], seen, tools_seen)
    await agent.run_turn("halo")
    assert "codemode" not in _names(tools_seen[0])


def test_bench_replay_codemode_uses_fewer_model_calls():
    import subprocess
    import sys
    from pathlib import Path
    bench = Path(__file__).resolve().parent.parent / "bench" / "codemode_bench.py"
    rows = {}
    for arm in ("per-call", "codemode"):
        r = subprocess.run([sys.executable, str(bench), "run", "rename-line-total", arm], capture_output=True,
                           text=True, timeout=120, cwd=str(bench.parent.parent))
        rows[arm] = json.loads(r.stdout.strip().splitlines()[-1])
    assert rows["per-call"]["pass"] and rows["codemode"]["pass"]
    assert rows["codemode"]["model_calls"] < rows["per-call"]["model_calls"]
    assert rows["codemode"]["script_left"] == 0
