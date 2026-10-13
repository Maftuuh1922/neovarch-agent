"""Agent upgrade: apply_patch (V4A), repo_map, task sub-agents, hooks, /rencana plan mode,
context files (CLAUDE.md + global), Tempest update_plan shown live."""

import json
import sys

import pytest

from neovarch import repomap, tools_patch
from neovarch.tools import ToolContext, run_tool


# ------------------------------------------------------------------ apply_patch --

def _ctx(tmp_path):
    return ToolContext(cwd=tmp_path, approve=None)


async def test_apply_patch_add_update_delete_move(home, tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8")
    (tmp_path / "old.txt").write_text("bye\n", encoding="utf-8")
    (tmp_path / "m.txt").write_text("x\ny\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Add File: pkg/new.py
+VALUE = 3
*** Update File: a.py
@@ def g():
-    return 2
+    return 20
*** Delete File: old.txt
*** Update File: m.txt
*** Move to: n.txt
 x
-y
+z
*** End Patch"""
    out = await run_tool("apply_patch", {"patch": patch}, _ctx(tmp_path))
    assert out.startswith("patched 4"), out
    assert (tmp_path / "pkg/new.py").read_text() == "VALUE = 3\n"
    assert "return 20" in (tmp_path / "a.py").read_text() and "return 1\n" in (tmp_path / "a.py").read_text()
    assert not (tmp_path / "old.txt").exists()
    assert not (tmp_path / "m.txt").exists() and (tmp_path / "n.txt").read_text() == "x\nz\n"


async def test_apply_patch_is_all_or_nothing(home, tmp_path):
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    patch = ("*** Begin Patch\n*** Add File: b.txt\n+new\n*** Update File: a.txt\n-missing line\n+x\n"
             "*** End Patch")
    out = await run_tool("apply_patch", {"patch": patch}, _ctx(tmp_path))
    assert out.startswith("error: patch not applied")
    assert not (tmp_path / "b.txt").exists() and (tmp_path / "a.txt").read_text() == "one\n"


def test_apply_patch_tolerates_whitespace_and_indent(tmp_path):
    text = "class A:\n    def run(self):\n        x = 1   \n        return x\n"
    hunks = tools_patch.parse("*** Begin Patch\n*** Update File: a.py\n@@ def run\n-x = 1\n+x = 2\n"
                              " return x\n*** End Patch")[0].hunks
    out, notes = tools_patch.apply_hunks(text, hunks, "a.py")
    assert "        x = 2\n        return x\n" in out and notes


def test_apply_patch_unified_diff_and_crlf(tmp_path):
    (tmp_path / "w.txt").write_bytes(b"a\r\nb\r\n")
    diff = "--- a/w.txt\n+++ b/w.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
    changes, summary = tools_patch.plan(diff, lambda r: tmp_path / r)
    tools_patch.write(changes)
    assert (tmp_path / "w.txt").read_bytes() == b"a\r\nc\r\n" and summary[0].startswith("M w.txt")


async def test_shell_heredoc_apply_patch(home, tmp_path):
    cmd = "apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: h.txt\n+hi\n*** End Patch\nEOF"
    out = await run_tool("shell", {"command": cmd}, _ctx(tmp_path))
    assert out.startswith("patched 1") and (tmp_path / "h.txt").read_text() == "hi\n"


# --------------------------------------------------------------------- repo_map --

def test_repo_map_ranks_referenced_files_and_respects_budget(tmp_path):
    (tmp_path / "core.py").write_text("class Engine:\n    def start(self):\n        pass\n\ndef helper():\n    pass\n")
    (tmp_path / "app.ts").write_text("import {x} from './x'\nexport function boot(): void {\n  Engine.start()\n}\n"
                                     "export class Server {\n  listen(port: number) {\n  }\n}\n")
    (tmp_path / "use.py").write_text("from core import Engine\nEngine().start()\nhelper()\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("function hidden() {}\n")
    out = repomap.build(tmp_path)
    assert "core.py:" in out and "class Engine" in out and "def start" in out
    assert "boot" in out and "class Server" in out and "listen" in out
    assert "hidden" not in out
    assert out.index("core.py:") < out.index("use.py")  # most referenced first
    small = repomap.build(tmp_path, budget=200)
    assert len(small) < 1200
    assert "app.ts:" in repomap.build(tmp_path, focus="server boot").split("\n")[1]


@pytest.mark.parametrize("lang,src,name", [
    ("go", "func (s *Srv) Handle(w http.ResponseWriter) {\n", "Handle"),
    ("rs", "pub async fn fetch_all(x: u8) -> u8 {\n", "fetch_all"),
    ("jvm", "public class Main {\n", "Main"),
    ("dart", "class HomePage extends StatelessWidget {\n", "HomePage"),
    ("rb", "def greet(name)\n", "greet"),
])
def test_repo_map_languages(lang, src, name):
    assert [s[1] for s in repomap.symbols(src, lang)] == [name]


# ------------------------------------------------------------------------ hooks --

async def test_hooks_block_and_annotate(home, tmp_path):
    py = sys.executable
    (home / "hooks.json").write_text(json.dumps({
        "pre_tool": [{"match": "write_file", "command": f"{py} -c \"import sys,json; d=json.load(sys.stdin); "
                      f"sys.stderr.write('no secrets'); sys.exit(2 if 'secret' in d['args']['path'] else 0)\""}],
        "post_tool": [{"match": "write_file", "command": f"{py} -c \"print('formatted')\""}]}), encoding="utf-8")
    ctx = _ctx(tmp_path)
    out = await run_tool("write_file", {"path": "secret.txt", "content": "x"}, ctx)
    assert out.startswith("blocked by hook") and "no secrets" in out and not (tmp_path / "secret.txt").exists()
    out = await run_tool("write_file", {"path": "ok.txt", "content": "x"}, ctx)
    assert out.startswith("wrote") and "formatted" in out


async def test_repo_hooks_file_is_ignored(home, tmp_path):
    (tmp_path / "hooks.json").write_text(json.dumps({"pre_tool": [{"command": "exit 2"}]}), encoding="utf-8")
    (tmp_path / ".neovarch").mkdir()
    (tmp_path / ".neovarch" / "hooks.json").write_text(json.dumps({"pre_tool": [{"command": "exit 2"}]}))
    out = await run_tool("write_file", {"path": "a.txt", "content": "x"}, _ctx(tmp_path))
    assert out.startswith("wrote")


# ---------------------------------------------------------------- context files --

def test_context_files_claude_md_and_global(home, tmp_path):
    from neovarch.agent import context_files
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("Use pnpm.", encoding="utf-8")
    sub = repo / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("Tests: pytest -q", encoding="utf-8")
    (home / "AGENTS.md").write_text("Always answer in Indonesian.", encoding="utf-8")
    out = context_files(sub, home=home)
    assert out.index("Always answer") < out.index("Use pnpm") < out.index("pytest -q")


# ------------------------------------------------------------ agent integration --

def _cfg(agent_cfg):
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)


def _call(cid, tool, **args):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name=tool, arguments=json.dumps(args))


def _agent(tmp_path, monkeypatch, main_script, sub_script=None, seen=None, emits=None, set_plan=None):
    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")

    async def fake(*, messages, tools=None, **_kw):
        if seen is not None:
            seen.append((messages, tools))
        sub = str(messages[0].get("content") or "").startswith("You are a read-only research sub-agent")
        text, calls = (sub_script if sub else main_script).pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    ctx = ToolContext(cwd=tmp_path, approve=None, set_plan=set_plan)
    return Agent(rec, store, ctx, (lambda k, p: emits.append((k, p))) if emits is not None else (lambda k, p: None)), rec


async def test_task_subagents_run_read_only_and_report(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest"})
    (tmp_path / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    main = [("", [_call("t1", "task", tasks=["where is login defined?"])]), ("Login ada di auth.py:1", [])]
    sub = [("", [_call("s1", "grep", pattern="def login"), _call("s2", "write_file", path="x.txt", content="no")]),
           ("login is defined in auth.py:1", [])]
    seen = []
    agent, rec = _agent(tmp_path, monkeypatch, main, sub, seen=seen)
    await agent.run_turn("cari fungsi login")
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert "auth.py:1" in tool_msgs[0]["content"] and "Sub-agent 1" in tool_msgs[0]["content"]
    assert not (tmp_path / "x.txt").exists()  # sub-agents cannot write
    sub_calls = [s for s in seen if str(s[0][0]["content"]).startswith("You are a read-only")]
    sub_tool_msgs = [m for m in sub_calls[1][0] if m.get("role") == "tool"]
    assert any("refused: sub-agents are read-only" in m["content"] for m in sub_tool_msgs)
    assert {t["function"]["name"] for t in sub_calls[0][1]} <= {"read_file", "grep", "glob", "repo_map",
                                                               "web_search", "web_fetch"}
    assert agent.ctx.llm is None  # cleared after the turn


async def test_task_tool_without_turn_errors(home, tmp_path):
    out = await run_tool("task", {"tasks": ["x"]}, _ctx(tmp_path))
    assert out.startswith("error: task is only available")


async def test_plan_mode_blocks_writes(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest"})
    (tmp_path / "a.txt").write_text("v1\n", encoding="utf-8")
    main = [("", [_call("c1", "read_file", path="a.txt"), _call("c2", "write_file", path="a.txt", content="v2")]),
            ("1. ubah a.txt. Balas 'lanjut' untuk mengerjakan.", []),
            ("", [_call("c3", "write_file", path="a.txt", content="v2")]), ("selesai", [])]
    seen = []
    agent, rec = _agent(tmp_path, monkeypatch, main, seen=seen)
    await agent.run_turn("/rencana ubah a.txt ke v2")
    assert (tmp_path / "a.txt").read_text() == "v1\n"
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert "v1" in tool_msgs[0]["content"] and tool_msgs[1]["content"].startswith("refused: mode rencana")
    assert "Mode rencana" in json.dumps(seen[0][0])
    await agent.run_turn("lanjut")
    assert (tmp_path / "a.txt").read_text() == "v2"


async def test_tempest_apply_patch_syntax_gate_restores_all(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest"})
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    bad = ("*** Begin Patch\n*** Update File: ok.py\n-x = 1\n+x = 2\n*** Add File: broken.py\n+def (:\n"
           "*** End Patch")
    main = [("", [_call("c1", "apply_patch", patch=bad)]), ("done", [])]
    agent, rec = _agent(tmp_path, monkeypatch, main)
    await agent.run_turn("patch it")
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert tool_msgs[0]["content"].startswith("rejected:")
    assert (tmp_path / "ok.py").read_text() == "x = 1\n" and not (tmp_path / "broken.py").exists()


async def test_update_plan_is_published_and_plan_update_not_duplicated(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_progress": True})
    plans = []
    main = [("", [_call("c1", "update_plan", items=[{"id": "1", "text": "baca kode", "status": "doing"},
                                                   {"id": "2", "text": "ubah", "status": "todo"}])]), ("ok", [])]
    seen = []
    agent, rec = _agent(tmp_path, monkeypatch, main, seen=seen, set_plan=plans.append)
    await agent.run_turn("kerjakan tugas panjang")
    assert plans and plans[0][0] == {"title": "baca kode", "status": "doing"}
    names = [t["function"]["name"] for t in seen[0][1]]
    assert "update_plan" in names and "plan_update" not in names


def test_new_tools_are_deferred_under_diet():
    from neovarch import tempest_diet
    for name in ("apply_patch", "repo_map", "task"):
        assert name not in tempest_diet.CORE_TOOLS and name in tempest_diet.ONE_LINERS
