"""Default working method: tool-call repair, self-check, evidence, compaction, escalation (fake weak model)."""

import sys
from pathlib import Path

import pytest

from neovarch import config as cfgmod
from neovarch import scaffold
from neovarch.agent import Agent
from neovarch.llm import Completion, ToolCall
from neovarch.store import SessionStore
from neovarch.tools import ToolContext, tool_schemas


# ------------------------------------------------------------------ units --

@pytest.mark.parametrize("raw,expected", [
    ('{"path": "a.txt"}', {"path": "a.txt"}),
    ("```json\n{\"path\": \"a.txt\"}\n```", {"path": "a.txt"}),
    ('{"path": "a.txt",}', {"path": "a.txt"}),
    ("{'path': 'a.txt', 'force': True}", {"path": "a.txt", "force": True}),
    ('{path: "a.txt"}', {"path": "a.txt"}),
    ('"{\\"path\\": \\"a.txt\\"}"', {"path": "a.txt"}),
    ('{"path": "a.txt"', {"path": "a.txt"}),
    ("Sure! Here: {\"path\": \"a.txt\"} hope it helps", {"path": "a.txt"}),
    ("", {}),
])
def test_repair_json(raw, expected):
    args, _how = scaffold.repair_json(raw)
    assert args == expected


def test_repair_json_gives_up_on_garbage():
    assert scaffold.repair_json("just do it please")[0] is None


def test_resolve_tool_name():
    known = ["read_file", "write_file", "shell"]
    assert scaffold.resolve_tool_name("read-file", known) == "read_file"
    assert scaffold.resolve_tool_name("ReadFile", known) == "read_file"
    assert scaffold.resolve_tool_name("readfile", known) == "read_file"
    assert scaffold.resolve_tool_name("delete_everything", known) is None


def test_prepare_call_reasks_with_schema(home):
    schemas = tool_schemas(None)
    bad = scaffold.prepare_call("shell", "run ls please", schemas)
    assert bad.error and "command" in bad.error and "JSON" in bad.error
    missing = scaffold.prepare_call("shell", "{}", schemas)
    assert missing.error and "command" in missing.error
    ok = scaffold.prepare_call("Shell", "{'command': 'echo hi'}", schemas)
    assert ok.error is None and ok.name == "shell" and ok.args == {"command": "echo hi"}
    unknown = scaffold.prepare_call("teleport", "{}", schemas)
    assert unknown.error and "tidak ada" in unknown.error


REPORT = ("**Temuan**\nFungsi add sudah benar.\n\n**Bukti**\n- `calc.py:1` berisi `return a + b`\n"
          "- `python -m py_compile calc.py` → exit code 0\n\n**Batasan**\n- Belum ada unit test.\n\n"
          "**Langkah berikutnya**\n- Tambah tes.")


def test_parse_evidence_sections():
    ev = scaffold.parse_evidence(REPORT)
    assert set(ev) == {"findings", "evidence", "unknowns", "next"}
    assert "calc.py:1" in ev["evidence"] and scaffold.has_concrete_evidence(ev["evidence"])
    assert scaffold.parse_evidence("Halo! Ada yang bisa dibantu?") is None


def test_self_check_rejects_claims_without_evidence():
    led = scaffold.TurnLedger()
    assert scaffold.self_check("Sudah saya perbaiki dan semua tes lulus.", led)  # nothing ran
    small_talk = scaffold.TurnLedger()
    assert scaffold.self_check("Senang bisa membantu! Selesai untuk hari ini.", small_talk) is None
    led = scaffold.TurnLedger()
    for i in range(3):
        led.record("read_file", {"path": f"f{i}.py"}, "     1\tx = 1")
    note = scaffold.self_check("Kesimpulannya kodenya aman.", led)
    assert note and "Bukti" in note
    vague = "**Temuan**\nAman.\n**Bukti**\nsaya yakin.\n**Batasan**\n-"
    assert "konkret" in scaffold.self_check(vague, led)
    assert scaffold.self_check(REPORT, scaffold.TurnLedger()) is None


def test_self_check_is_capped():
    led = scaffold.TurnLedger()
    for _ in range(scaffold.MAX_VERIFY_RETRIES):
        assert scaffold.self_check("Sudah saya perbaiki.", led)
    assert scaffold.self_check("Sudah saya perbaiki.", led) is None


def test_code_change_requires_tests():
    led = scaffold.TurnLedger()
    led.record("write_file", {"path": "calc.py"}, "wrote 10 characters to calc.py")
    note = scaffold.self_check(REPORT.replace("py_compile", "cat"), led)
    assert note and "tes" in note
    led.record("shell", {"command": "python -m pytest -q"}, "exit code 0 (0.1s)\n1 passed")
    assert scaffold.self_check(REPORT, led) is None


def test_compact_wire_keeps_recent_and_summarises():
    wire = [{"role": "system", "content": "sys"}]
    for i in range(30):
        wire.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "function": {"name": "read_file", "arguments": "{}"}}]})
        wire.append({"role": "tool", "tool_call_id": f"c{i}", "name": "read_file", "content": f"hasil {i}\n" + "x" * 2000})
    out = scaffold.compact_wire(wire, 8000)
    assert out[-1] == wire[-1] and len(out) == len(wire)
    assert "Ringkasan langkah sebelumnya" in out[0]["content"] and "hasil 0" in out[0]["content"]
    assert out[2]["content"].startswith("[diringkas")
    assert scaffold.estimate_tokens(out) < scaffold.estimate_tokens(wire)


def test_relevant_skills_hint():
    skills = [{"name": "ppt", "description": "Buat presentasi PowerPoint"}, {"name": "x", "description": "lain"}]
    assert "`ppt`" in scaffold.skills_hint("tolong buatkan presentasi tentang kopi", skills)
    assert scaffold.skills_hint("halo", skills) == ""


# ------------------------------------------------- fake weak model, full loop --

def _weak(home, extra: dict | None = None):
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "tiny-free", "base_url": "http://127.0.0.1:9/v1",
                    "context_length": 8000}
    for k, v in (extra or {}).items():
        cfgmod.set_path(cfg, k, v)
    cfgmod.save_config(cfg)


def _script(monkeypatch, steps):
    """Replace the model with a scripted weak one; returns the list of (model, wire) it was called with."""
    calls = []

    async def fake_stream(self, endpoint, wire, started, on_first=None):
        calls.append((endpoint["model"], [dict(m) for m in wire]))
        step = steps.pop(0)
        return step(wire) if callable(step) else step
    monkeypatch.setattr(Agent, "_stream", fake_stream)
    return calls


def _tool(name, args, cid="c1"):
    return Completion(tool_calls=[ToolCall(id=cid, name=name, arguments=args)])


async def _never(*_a):
    raise AssertionError("no approval expected")


def _agent(tmp_path, events=None):
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    events = events if events is not None else []
    return Agent(rec, store, ToolContext(cwd=tmp_path, approve=_never), lambda k, p: events.append((k, p))), store, rec


async def test_weak_model_malformed_tool_call_is_repaired(home, tmp_path, monkeypatch):
    _weak(home)
    _script(monkeypatch, [
        _tool("write-file", "{'path': 'notes.txt', 'content': 'halo',}"),
        Completion(text="**Temuan**\nFile dibuat.\n\n**Bukti**\n- `notes.txt` ditulis (write_file: wrote 4 characters)\n\n"
                        "**Batasan**\n- -\n\n**Langkah berikutnya**\n- -"),
    ])
    agent, store, rec = _agent(tmp_path)
    final = await agent.run_turn("buat file notes.txt isinya halo")
    assert (tmp_path / "notes.txt").read_text() == "halo"
    assert final.startswith("**Temuan**")
    msgs = store.load(rec["id"])["messages"]
    assert not any(m.get("hidden") for m in msgs)
    assert msgs[-1]["evidence"]["evidence"].startswith("- `notes.txt`")


async def test_weak_model_unparseable_args_get_the_schema(home, tmp_path, monkeypatch):
    _weak(home)
    calls = _script(monkeypatch, [
        _tool("shell", "please list the files"),
        lambda wire: _tool("shell", '{"command": "echo ok"}', "c2"),
        Completion(text="Isinya: ok"),
    ])
    agent, store, rec = _agent(tmp_path)
    assert await agent.run_turn("jalankan echo") == "Isinya: ok"
    retry_wire = calls[1][1]
    tool_msg = [m for m in retry_wire if m["role"] == "tool"][0]
    assert "JSON" in tool_msg["content"] and "command" in tool_msg["content"]


async def test_failing_first_attempt_then_verify_then_retry_succeeds(home, tmp_path, monkeypatch):
    _weak(home)
    py = sys.executable
    calls = _script(monkeypatch, [
        _tool("write_file", '{"path": "calc.py", "content": "def add(a, b)\\n    return a + b\\n"}'),
        _tool("shell", f'{{"command": "{py} -m py_compile calc.py"}}', "c2"),
        Completion(text="Sudah saya perbaiki, semua beres."),            # lies: compile failed
        _tool("write_file", '{"path": "calc.py", "content": "def add(a, b):\\n    return a + b\\n"}', "c3"),
        _tool("shell", f'{{"command": "{py} -m py_compile calc.py"}}', "c4"),
        Completion(text=REPORT),
    ])
    events = []
    agent, store, rec = _agent(tmp_path, events)
    final = await agent.run_turn("perbaiki calc.py")
    assert final == REPORT
    nudge = [m for m in calls[3][1] if m["role"] == "user" and "Pemeriksaan otomatis" in str(m["content"])]
    assert nudge and "gagal" in nudge[0]["content"]
    saved = store.load(rec["id"])
    assert any(m.get("hidden") for m in saved["messages"])
    from neovarch.server import to_ui_messages
    assert not any("Pemeriksaan otomatis" in str(m["content"]) for m in to_ui_messages(saved))
    done = [p for k, p in events if k == "message.complete"][-1]
    assert done["files_changed"] == ["calc.py"] and done["evidence"]["findings"]


async def test_escalates_one_step_when_stuck(home, tmp_path, monkeypatch):
    _weak(home, {"agent.escalate_on_stuck": True, "agent.escalation_model": "big-model",
                 "agent.escalation_provider": "custom"})
    calls = _script(monkeypatch, [
        _tool("read_file", '{"path": "nope1.txt"}'),
        _tool("read_file", '{"path": "nope2.txt"}', "c2"),
        Completion(text="File tidak ada."),
    ])
    events = []
    agent, *_ = _agent(tmp_path, events)
    await agent.run_turn("baca file")
    assert [m for m, _ in calls] == ["tiny-free", "tiny-free", "big-model"]
    assert any(p.get("kind") == "escalation" for k, p in events if k == "status.update")


async def test_stuck_without_escalation_only_suggests_setting(home, tmp_path, monkeypatch):
    _weak(home)
    calls = _script(monkeypatch, [
        _tool("read_file", '{"path": "nope1.txt"}'),
        _tool("read_file", '{"path": "nope2.txt"}', "c2"),
        Completion(text="File tidak ada."),
    ])
    events = []
    agent, *_ = _agent(tmp_path, events)
    await agent.run_turn("baca file")
    assert {m for m, _ in calls} == {"tiny-free"}
    assert any("lebih kuat" in str(p.get("text")) for k, p in events if k == "status")


async def test_system_prompt_carries_method_and_project_context(home, tmp_path, monkeypatch):
    _weak(home)
    (tmp_path / "AGENTS.md").write_text("Selalu pakai tab, bukan spasi.")
    calls = _script(monkeypatch, [Completion(text="ok")])
    agent, *_ = _agent(tmp_path)
    await agent.run_turn("halo")
    system = calls[0][1][0]["content"]
    assert "Cara kerja" in system and "Temuan" in system and "Bukti" in system
    assert "Selalu pakai tab" in system and "manage" in system
