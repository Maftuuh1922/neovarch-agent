"""Tempest progress artefact: update_plan, session-start recitation, tail recitation, verify flag."""

import json

from neovarch import tempest, tempest_progress as tp


def test_update_render_and_verified(tmp_path):
    prog = tp.Progress(tmp_path / "proj", tmp_path / "home")
    assert tp.session_start_note(prog) == "" and tp.recitation(prog) == ""
    assert prog.update({"items": []}).startswith("error")
    out = prog.update({"items": [{"id": "core", "text": "3 TODO", "status": "done"},
                                 {"id": "net", "text": "hitung", "status": "todo"}], "note": "pakai grep"})
    assert out.startswith("plan diperbarui: 2 item, 1 selesai")
    text = tp.recitation(prog)
    assert text.startswith(tp.PLAN_MARK) and "- [x] core: 3 TODO" in text and "- [ ] net: hitung" in text
    assert "Catatan: pakai grep" in text
    assert "dari sesi sebelumnya" in tp.session_start_note(prog)
    prog.mark_verified(False)
    assert "belum terverifikasi" in tp.recitation(prog)
    prog.mark_verified(True)
    assert "(terverifikasi)" in tp.recitation(prog)
    assert prog.path.with_suffix(".md").read_text().startswith(tp.PLAN_MARK)
    assert not str(prog.path).startswith(str(tmp_path / "proj"))  # never inside the user's repo
    prog.update({"items": [{"id": "core", "text": "x", "status": "done"}]})
    assert tp.session_start_note(prog) == ""  # nothing unfinished: no recitation in a new chat


async def _agent(home, tmp_path, monkeypatch, agent_cfg, script, prompts_per_session):
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    seen = []

    async def fake(*, messages, tools=None, **_kw):
        seen.append((messages, tools))
        return script(messages, tools, len(seen))
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    for prompts in prompts_per_session:
        rec = store.create(cwd=str(tmp_path))
        agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
        for q in prompts:
            await agent.run_turn(q)
    return seen, Completion


async def test_plan_survives_a_new_chat(home, tmp_path, monkeypatch):
    from neovarch.llm import Completion, ToolCall

    def script(messages, tools, n):
        if n == 1:
            assert "update_plan" in [t["function"]["name"] for t in tools]
            return Completion(text="", tool_calls=[ToolCall(id="p1", name="update_plan", arguments=json.dumps(
                {"items": [{"id": "a", "text": "langkah a", "status": "done"},
                           {"id": "b", "text": "langkah b", "status": "todo"}]}))])
        return Completion(text="ok")
    seen, _ = await _agent(home, tmp_path, monkeypatch, {"harness_mode": "tempest", "tempest_progress": True},
                           script, [["mulai"], ["lanjutkan"]])
    assert seen[1][0][-1]["content"].startswith("plan diperbarui")
    first_of_chat2 = seen[2][0][1]["content"]
    assert "lanjutkan" in first_of_chat2 and "[x] a: langkah a" in first_of_chat2 and "[ ] b" in first_of_chat2


async def test_tail_recitation_in_long_session_keeps_prefix(home, tmp_path, monkeypatch):
    from neovarch.llm import Completion, ToolCall
    (tmp_path / "f.txt").write_text("isi\n")

    def script(messages, tools, n):
        if n == 1:
            return Completion(text="", tool_calls=[ToolCall(id="p", name="update_plan", arguments=json.dumps(
                {"items": [{"id": "x", "text": "baca file", "status": "doing"}]}))])
        if n <= 6:
            return Completion(text="", tool_calls=[ToolCall(id=f"r{n}", name="read_file",
                                                            arguments=json.dumps({"path": "f.txt"}))])
        return Completion(text="selesai")
    seen, _ = await _agent(home, tmp_path, monkeypatch,
                           {"harness_mode": "tempest", "tempest_progress": True, "tempest_recite_after": 3,
                            "tempest_mask": False, "tempest_cache_v2": True}, script, [["kerjakan"]])
    recited = [i for i, (w, _) in enumerate(seen) if tp.PLAN_MARK in str(w[-1]["content"])]
    assert recited and recited[0] == 3  # after 3 tool results, then on every call
    assert recited == list(range(3, len(seen)))
    for (prev, _), (cur, _) in zip(seen, seen[1:]):
        assert tempest.prefix_violation(prev, cur) is None
    assert all(tp.PLAN_MARK not in str(m.get("content")) for w, _ in seen for m in w[:-1])


async def test_progress_off_by_default(home, tmp_path, monkeypatch):
    from neovarch.llm import Completion

    def script(messages, tools, n):
        assert "update_plan" not in [t["function"]["name"] for t in tools]
        return Completion(text="ok")
    await _agent(home, tmp_path, monkeypatch, {"harness_mode": "tempest"}, script, [["hai"]])
