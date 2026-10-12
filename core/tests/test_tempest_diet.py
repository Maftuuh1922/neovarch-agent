"""Tempest prompt diet: lazy skill index, deferred tool schemas behind extra_tool, cache stability."""

import json

import pytest

from neovarch import tempest, tempest_diet


def _cfg(agent_cfg):
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)


def _agent(tmp_path, monkeypatch, script, seen, tools_seen):
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
    return Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None), rec


def _call(cid, tool, **args):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name=tool, arguments=json.dumps(args))


def test_diet_default_on_in_tempest_only():
    assert tempest.settings({})["prompt_diet"] is True  # Tempest (with the diet) is the default since 1.4.7
    assert tempest.settings({"agent": {"harness_mode": "legacy"}}) is None
    assert tempest.settings({"agent": {"harness_mode": "tempest"}})["prompt_diet"] is True
    off = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_prompt_diet": False}})
    assert off["prompt_diet"] is False and not tempest_diet.enabled(off)


def test_split_and_proxy_schema():
    from neovarch.tools import tool_schemas
    tools = tool_schemas(None)
    sent, deferred = tempest_diet.diet_tools(tools, set())
    names = [t["function"]["name"] for t in sent]
    assert names[-1] == tempest_diet.PROXY
    assert {"shell", "read_file", "write_file", "edit_file", "skill"} <= set(names)
    assert "manage" in deferred and "report_export" in deferred and "manage" not in names
    desc = sent[-1]["function"]["description"]
    for n in deferred:
        assert f"- {n}:" in desc  # every deferred tool is named in the catalog
    # company (Kantor employee) tools are never deferred
    sent2, deferred2 = tempest_diet.diet_tools(tools, {"report_export"})
    assert "report_export" not in deferred2


def test_resolve_describe_run_and_unknown():
    from neovarch.tools import tool_schemas
    _, deferred = tempest_diet.diet_tools(tool_schemas(None), set())
    real, args, reply = tempest_diet.resolve({"action": "describe", "name": "diagram_save"}, deferred)
    assert real is None and '"format"' in reply and "action=run" in reply
    real, args, reply = tempest_diet.resolve({"action": "run", "name": "diagram_save",
                                              "arguments": {"format": "svg", "content": "<svg/>"}}, deferred)
    assert real == "diagram_save" and json.loads(args)["format"] == "svg" and reply is None
    real, args, reply = tempest_diet.resolve({"action": "run", "name": "diagram_save",
                                              "arguments": '{"format": "mermaid", "content": "graph TD"}'}, deferred)
    assert json.loads(args)["format"] == "mermaid"  # double-encoded arguments still work
    real, _, reply = tempest_diet.resolve({"action": "run", "name": "shell", "arguments": {}}, deferred)
    assert real is None and "Alat inti" in reply


def test_system_prompt_is_much_smaller_with_diet(home, tmp_path):
    from neovarch import agent as A, config as cfgmod
    from neovarch.tools import list_skills
    cfg = cfgmod.load_config()
    full = A.system_prompt(cfg, tmp_path, "x", A.persona_prompt("s", None), stable=True)
    diet = A.system_prompt(cfg, tmp_path, "x", A.persona_prompt("s", None, diet=True), stable=True, diet=True)
    assert len(diet) < 0.7 * len(full)
    for s in list_skills():  # every skill is still named
        assert s["name"] in diet
    assert "send_file" in diet and "office_status" in diet  # app rules kept


@pytest.mark.asyncio
async def test_agent_extra_tool_run_and_cache_stable(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest"})
    seen, tools_seen = [], []
    script = [("", [_call("c1", tempest_diet.PROXY, action="describe", name="memory_update")]),
              ("", [_call("c2", tempest_diet.PROXY, action="run", name="memory_update",
                          arguments={"action": "append", "name": "prefs", "content": "Pengguna suka teh."})]),
              ("", [_call("c3", "memory_update", action="list")]),  # direct call to a deferred tool
              ("selesai", []),
              ("halo lagi", [])]
    agent, rec = _agent(tmp_path, monkeypatch, script, seen, tools_seen)
    await agent.run_turn("simpan preferensiku")
    tool_msgs = [m for m in rec["messages"] if m.get("role") == "tool"]
    assert '"parameters"' in tool_msgs[0]["content"]
    assert "error" not in tool_msgs[1]["content"].lower()[:20]
    assert "teh" in (home / "memory" / "prefs.md").read_text(encoding="utf-8")
    assert not tool_msgs[2]["content"].startswith("error: alat")
    await agent.run_turn("halo")
    assert len(set(tools_seen)) == 1  # the tools array never changes inside the session
    assert seen[0][0] == seen[-1][0]  # nor the system prompt
    names = [t["function"]["name"] for t in json.loads(tools_seen[0])]
    assert tempest_diet.PROXY in names and "manage" not in names


@pytest.mark.asyncio
async def test_diet_off_sends_every_tool(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_prompt_diet": False})
    seen, tools_seen = [], []
    agent, rec = _agent(tmp_path, monkeypatch, [("ok", [])], seen, tools_seen)
    await agent.run_turn("halo")
    names = [t["function"]["name"] for t in json.loads(tools_seen[0])]
    assert tempest_diet.PROXY not in names and "manage" in names
