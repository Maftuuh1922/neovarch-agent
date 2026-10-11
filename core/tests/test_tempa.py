"""Tempa harness layer (opt-in): legacy stays the default; each mechanism in isolation."""

import json

from neovarch import tempa


def test_default_is_legacy():
    assert tempa.mode({}) == "legacy"
    assert tempa.settings({"agent": {"harness_mode": "legacy"}}) is None
    st = tempa.settings({"agent": {"harness_mode": "tempa"}})
    assert st["profile"] == "ringan" and st["mask"] and st["verify_retries"] == 2
    assert tempa.settings({"agent": {"harness_mode": "tempa", "tempa_profile": "tinggi"}})["mask"] is False
    assert tempa.settings({"agent": {"harness_mode": "tempa", "tempa_mask": False}})["mask"] is False


def test_offload_keeps_head_tail_and_path(tmp_path):
    big = "\n".join(f"line {i} " + "x" * 40 for i in range(2000))
    out = tempa.offload(big, "shell", "c1", tmp_path, 2000)
    assert "line 0 " in out and "line 1999 " in out and "line 1000 " not in out
    saved = next(tmp_path.glob("*.txt"))
    assert str(saved) in out and saved.read_text() == big
    assert tempa.offload("small", "shell", "c2", tmp_path, 2000) == "small"
    assert tempa.offload(big, "read_file", "c3", tmp_path, 2000) == big


def _wire(n):
    w = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(n):
        args = json.dumps({"command": f"cmd{i}"})
        w.append({"role": "assistant", "content": None,
                  "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "shell", "arguments": args}}]})
        w.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 1000})
    return w


def test_mask_old_observations_in_blocks():
    st = tempa.settings({"agent": {"harness_mode": "tempa"}})
    masked = [m for m in tempa.mask_wire(_wire(9), st) if m["role"] == "tool"
              and m["content"].startswith("[output alat lama")]
    assert masked == []  # 9 - 6 = 3 old turns < block of 4: nothing moves yet
    out = tempa.mask_wire(_wire(10), st)
    tools = [m for m in out if m["role"] == "tool"]
    assert all(m["content"].startswith("[output alat lama") for m in tools[:4])
    assert all(m["content"] == "y" * 1000 for m in tools[4:])


def test_live_reads_are_not_masked():
    st = tempa.settings({"agent": {"harness_mode": "tempa"}})
    w = _wire(10)
    w[2]["tool_calls"][0]["function"] = {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}
    out = tempa.mask_wire(w, st)
    assert out[3]["content"] == "y" * 1000  # a.py was read and not touched since


def test_syntax_error(tmp_path):
    good, bad = tmp_path / "a.py", tmp_path / "b.py"
    good.write_text("x = 1\n")
    bad.write_text("def f():\n  return 1\n    x\n")
    assert tempa.syntax_error(good) is None and "IndentationError" in tempa.syntax_error(bad)
    j = tmp_path / "c.json"
    j.write_text('{"a": 1,}')
    assert "JSONDecodeError" in tempa.syntax_error(j)
    (tmp_path / "d.txt").write_text("{{{")
    assert tempa.syntax_error(tmp_path / "d.txt") is None


def test_detect_verify(tmp_path):
    assert tempa.detect_verify(tmp_path) is None
    (tmp_path / "tests").mkdir()
    assert "pytest" in tempa.detect_verify(tmp_path)
    other = tmp_path / "js"
    other.mkdir()
    (other / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert tempa.detect_verify(other)[:2] == ["npm", "test"]


async def test_agent_legacy_wire_unchanged_and_tempa_gate(home, tmp_path, monkeypatch):
    """Legacy: no tail, date in system prompt, no gate. Tempa: broken .py write is rejected
    and a failing test triggers one verify retry."""
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion, ToolCall
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
        "from m import f\n\ndef test_f():\n    assert f() == 2\n")
    seen = []
    script = []

    async def fake(*, messages, **_kw):
        seen.append(messages)
        text, calls = script.pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)

    def w(cid, content):
        return ToolCall(id=cid, name="write_file", arguments=json.dumps({"path": "m.py", "content": content}))

    # legacy: writes the wrong value, says done, no verification
    script[:] = [("", [w("a", "def f():\n    return 1\n")]), ("done", [])]
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    assert await agent.run_turn("buat f") == "done"
    assert "Date:" in seen[0][0]["content"] and "Konteks saat ini" not in seen[0][-1]["content"]
    assert len(seen) == 2

    # tempa: broken syntax rejected, then wrong value caught by the gate, then fixed
    cfg = cfgmod.load_config()
    cfg["agent"]["harness_mode"] = "tempa"
    cfgmod.save_config(cfg)
    seen.clear()
    script[:] = [("", [w("b", "def f(:\n")]), ("", [w("c", "def f():\n    return 1\n")]), ("done", []),
                 ("refleksi: nilai salah", [w("d", "def f():\n    return 2\n")]), ("done 2", [])]
    rec2 = store.create(cwd=str(tmp_path))
    agent2 = Agent(rec2, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    assert await agent2.run_turn("buat f") == "done 2"
    assert "Date:" not in seen[0][0]["content"] and "Konteks saat ini" in seen[0][-1]["content"]
    assert seen[1][-1]["content"].startswith("rejected:")
    assert "[verifikasi otomatis gagal" in seen[3][-1]["content"]
    assert (tmp_path / "m.py").read_text().endswith("return 2\n")
