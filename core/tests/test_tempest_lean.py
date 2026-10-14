"""Tempest lean turns (agent.tempest_lean): fewer model calls for the same work."""

import json
import sys

import pytest

from neovarch import scaffold, skillpack, tempest, tempest_diet


def test_lean_is_default_and_switchable():
    assert tempest.lean(tempest.settings({}))
    assert not tempest.lean(tempest.settings({"agent": {"tempest_lean": False}}))
    assert not tempest.lean(None)  # legacy loop


def test_full_verify_run_has_no_stop_at_first_failure(tmp_path):
    (tmp_path / "tests").mkdir()
    assert "-x" in tempest.detect_verify(tmp_path)
    assert "-x" not in tempest.detect_verify(tmp_path, full=True)


def test_lean_prompt_texts():
    m = scaffold.LEAN_METHOD
    assert "SATU respons" in m and "plan_update" in m and "Jangan membaca ulang" in m
    assert "PERSIS format" in m and "tidak dipakai" in m
    hint = skillpack.hint_block("perbaiki bug tes yang gagal", None, lean=True)
    assert hint.startswith("# Skill terkait (opsional)") and "langsung kerjakan" in hint
    assert "Sebelum mengerjakan, panggil" not in hint
    assert "SEBELUM mulai" not in tempest_diet.skills_names([{"name": "a"}], lean=True)
    assert "SEBELUM mulai" in tempest_diet.skills_names([{"name": "a"}])


def test_lean_verify_prompt_and_claim_helpers():
    p = tempest.lean_verify_prompt(["pytest"], "E assert", 1, 2, {"t/test_a.py::test_new"}, {"t/test_b.py::test_old"})
    assert "test_new" in p and "test_old" in p and "refleksi singkat" not in p
    p_old = tempest.lean_verify_prompt(["pytest"], "E", 1, 2, set(), {"t/test_b.py::test_old"})
    assert "sudah gagal SEBELUM" in p_old
    assert tempest.claims_all_green("Semua tes lulus.") and tempest.claims_all_green("all tests pass now")
    assert not tempest.claims_all_green("tes pajak lulus; test_take_too_many masih gagal")
    ids = {"tests/test_inventory.py::test_take_too_many"}
    assert tempest.mentions_failures("test_take_too_many masih gagal (bug lama)", ids)
    assert tempest.mentions_failures("Ada tes yang sudah gagal sebelum perubahan ini.", ids)
    assert not tempest.mentions_failures("Selesai.", ids)


# ---------------------------------------------------------------- agent loop ----

def _agent(home, tmp_path, monkeypatch, script, seen, agent_cfg=None):
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update({"tempest_skill_learn": "off", "tempest_memory_nudge": False,
                                        **(agent_cfg or {})})
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")

    async def fake(*, messages, **_kw):
        seen.append(messages)
        text, calls = script.pop(0) if script else ("selesai lagi", [])
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    return Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None), rec


def _call(cid, name, **args):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name=name, arguments=json.dumps(args))


def _two_bug_project(root):
    (root / "tests").mkdir()
    (root / "a.py").write_text("def a():\n    return 0\n")
    (root / "b.py").write_text("def b():\n    return 0\n")
    for n in ("a", "b"):
        (root / "tests" / f"test_{n}.py").write_text(
            "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
            f"from {n} import {n}\n\ndef test_{n}():\n    assert {n}() == 1\n")


@pytest.mark.skipif(not tempest.pytest_available(sys.executable), reason="pytest not importable")
async def test_old_failure_named_in_answer_costs_no_extra_call(home, tmp_path, monkeypatch):
    """Two old bugs; the user asks for one. With -x the second old failure used to look new (the first one
    hid it), which forced fix-up rounds and could roll back a correct fix. Lean: full run, old failure named
    in the answer -> the turn ends, the fix stays."""
    monkeypatch.setattr(tempest, "_python", lambda: sys.executable)
    _two_bug_project(tmp_path)
    seen = []
    script = [("", [_call("w", "write_file", path="a.py", content="def a():\n    return 1\n")]),
              ("a() diperbaiki. test_b masih gagal (bug lama, tidak diminta).", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    final = await agent.run_turn("perbaiki a")
    assert len(seen) == 2 and not script
    assert (tmp_path / "a.py").read_text().endswith("return 1\n")
    assert not [m for m in rec["messages"] if m.get("kind") == "verify"]
    assert "sudah gagal sebelum" in final


@pytest.mark.skipif(not tempest.pytest_available(sys.executable), reason="pytest not importable")
async def test_new_failure_still_gets_a_retry_without_essay(home, tmp_path, monkeypatch):
    monkeypatch.setattr(tempest, "_python", lambda: sys.executable)
    _two_bug_project(tmp_path)
    (tmp_path / "b.py").write_text("def b():\n    return 1\n")  # project green except a
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    seen = []
    script = [("", [_call("w", "write_file", path="b.py", content="def b():\n    return 2\n")]), ("beres", []),
              ("", [_call("w2", "write_file", path="b.py", content="def b():\n    return 1\n")]), ("beres 2", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    assert await agent.run_turn("ubah b") == "beres 2"
    verify = [m for m in rec["messages"] if m.get("kind") == "verify"]
    assert len(verify) == 1 and "test_b" in verify[0]["content"] and "refleksi singkat" not in verify[0]["content"]


async def test_read_cache_pointer_and_diff(home, tmp_path, monkeypatch):
    lines = "".join(f"baris {i}\n" for i in range(60))
    (tmp_path / "big.txt").write_text(lines)
    seen = []
    script = [("", [_call("r1", "read_file", path="big.txt")]),
              ("", [_call("r2", "read_file", path="big.txt")]),
              ("", [_call("e", "edit_file", path="big.txt", old_string="baris 30\n", new_string="baris TIGA PULUH\n")]),
              ("", [_call("r3", "read_file", path="big.txt")]),
              ("", [_call("r4", "read_file", path="big.txt", offset=10, limit=5)]),
              ("ok", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    await agent.run_turn("lihat big.txt")
    tools = [m["content"] for m in rec["messages"] if m.get("role") == "tool"]
    assert "baris 59" in tools[0]
    assert tools[1].startswith("(tidak dibaca ulang") and "baris" not in tools[1].split(";")[0][-10:]
    assert tools[3].startswith("(file berubah") and "+baris TIGA PULUH" in tools[3] and "baris 5\n" not in tools[3]
    assert "baris 10" in tools[4]  # another range is a real read


async def test_read_cache_off_when_lean_off(home, tmp_path, monkeypatch):
    (tmp_path / "f.txt").write_text("isi\n")
    seen = []
    script = [("", [_call("r1", "read_file", path="f.txt")]), ("", [_call("r2", "read_file", path="f.txt")]),
              ("ok", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen, {"tempest_lean": False})
    await agent.run_turn("baca")
    tools = [m["content"] for m in rec["messages"] if m.get("role") == "tool"]
    assert tools[0] == tools[1] and "isi" in tools[1]


async def test_lean_system_prompt_and_tail(home, tmp_path, monkeypatch):
    seen = []
    agent, rec = _agent(home, tmp_path, monkeypatch, [("halo", [])], seen)
    await agent.run_turn("perbaiki bug tes yang gagal")
    system, last = seen[0][0]["content"], seen[0][-1]["content"]
    assert "langkah BESAR" in system and "Rencana dulu untuk tugas bertahap" not in system
    assert "Sebelum mengerjakan, panggil alat `skill`" not in last


def test_project_snapshot(tmp_path):
    assert tempest.project_snapshot(tmp_path) == ""  # not a project (e.g. the home folder)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    (tmp_path / "a.py").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("")
    snap = tempest.project_snapshot(tmp_path, [sys.executable, "-m", "pytest", "-q"])
    assert "a.py" in snap and "tests/test_a.py" in snap and "node_modules" not in snap
    assert "python -m pytest -q" in snap
    for i in range(80):
        (tmp_path / f"m{i}.py").write_text("")
    big = tempest.project_snapshot(tmp_path)
    assert "Isi teratas" in big and "tests/" in big


@pytest.mark.skipif(not tempest.pytest_available(sys.executable), reason="pytest not importable")
async def test_auto_verify_after_edit_and_gate_reuses_it(home, tmp_path, monkeypatch):
    """The test result rides on the edit result (no model call to run tests); the end gate reuses it."""
    monkeypatch.setattr(tempest, "_python", lambda: sys.executable)
    _two_bug_project(tmp_path)
    (tmp_path / "b.py").write_text("def b():\n    return 1\n")
    runs = []
    real = tempest.run_verify

    def counting(cmd, cwd, timeout=300):
        runs.append(1)
        return real(cmd, cwd, timeout)
    monkeypatch.setattr(tempest, "run_verify", counting)
    seen = []
    script = [("", [_call("w", "edit_file", path="a.py", old_string="return 0", new_string="return 1")]),
              ("a() kini mengembalikan 1; tes lulus.", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    final = await agent.run_turn("perbaiki a")
    assert len(seen) == 2 and final.startswith("a() kini")
    edit = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert "[tes otomatis setelah edit:" in edit and "LULUS" in edit
    assert "[tes otomatis setelah edit:" in seen[1][-1]["content"]  # the model saw it with the edit
    assert len(runs) == 1  # the end-of-turn gate reused the automatic run


@pytest.mark.skipif(not tempest.pytest_available(sys.executable), reason="pytest not importable")
async def test_auto_verify_marks_old_failures(home, tmp_path, monkeypatch):
    monkeypatch.setattr(tempest, "_python", lambda: sys.executable)
    _two_bug_project(tmp_path)
    seen = []
    script = [("", [_call("w", "edit_file", path="a.py", old_string="return 0", new_string="return 1")]),
              ("a diperbaiki; test_b sudah gagal sebelumnya.", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    await agent.run_turn("perbaiki a")
    edit = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert "GAGAL" in edit and "gagal sejak sebelum turn ini: tests/test_b.py::test_b" in edit
    assert "baru di turn ini" not in edit
    assert len(seen) == 2  # named in the answer: no retry


async def test_auto_verify_skips_docs_only_writes(home, tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    seen = []
    script = [("", [_call("w", "write_file", path="README.md", content="# hi\n")]), ("ok", [])]
    agent, rec = _agent(home, tmp_path, monkeypatch, script, seen)
    await agent.run_turn("tulis readme")
    tool = [m for m in rec["messages"] if m.get("role") == "tool"][0]["content"]
    assert "tes otomatis" not in tool


def test_dsml_markup_in_text_becomes_tool_calls():
    from neovarch.llm import Completion, ToolCall, recover_text_tool_calls
    text = ("Now let me search.\n\n<｜DSML｜tool_calls>\n<｜DSML｜invoke name=\"grep\">\n"
            "<｜DSML｜parameter name=\"pattern\" string=\"true\">TAX_RATE|CURRENCY</｜DSML｜parameter>\n"
            "<｜DSML｜parameter name=\"limit\" string=\"false\">20</｜DSML｜parameter>\n</｜DSML｜invoke>\n"
            "<｜DSML｜invoke name=\"read_file\">\n<｜DSML｜parameter name=\"path\" string=\"true\">a.py</｜DSML｜parameter>\n"
            "</｜DSML｜invoke>\n</｜DSML｜tool_calls>")
    out = recover_text_tool_calls(Completion(text=text, finish_reason="stop"))
    assert [c.name for c in out.tool_calls] == ["grep", "read_file"]
    assert json.loads(out.tool_calls[0].arguments) == {"pattern": "TAX_RATE|CURRENCY", "limit": 20}
    assert out.text == "Now let me search." and out.finish_reason == "tool_calls"
    real = Completion(text="ok", tool_calls=[ToolCall(id="1", name="grep", arguments="{}")])
    assert recover_text_tool_calls(real) is real
    assert recover_text_tool_calls(Completion(text="DSML is a format")).tool_calls == []
