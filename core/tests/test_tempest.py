"""Tempest harness layer (opt-in): legacy stays the default; each mechanism in isolation."""

import json

from neovarch import tempest


def test_default_is_legacy():
    assert tempest.mode({}) == "legacy"
    assert tempest.settings({"agent": {"harness_mode": "legacy"}}) is None
    st = tempest.settings({"agent": {"harness_mode": "tempest"}})
    assert st["profile"] == "ringan" and st["mask_mode"] == "compact" and st["verify_retries"] == 2
    assert st["cache_v2"] and st["lint_gate"] and st["checkpoints"] and not st["progress"]
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_compact": False}})["mask"] is True
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_profile": "tinggi"}})["mask"] is False
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_mask": False}})["mask"] is False
    # deprecated pre-rename alias: harness_mode "tempa" and tempa_* keys still work
    assert tempest.mode({"agent": {"harness_mode": "tempa"}}) == "tempest"
    old = tempest.settings({"agent": {"harness_mode": "tempa", "tempa_profile": "tinggi"}})
    assert old["profile"] == "tinggi" and old["mask"] is False


def test_offload_keeps_head_tail_and_path(tmp_path):
    big = "\n".join(f"line {i} " + "x" * 40 for i in range(2000))
    out = tempest.offload(big, "shell", "c1", tmp_path, 2000)
    assert "line 0 " in out and "line 1999 " in out and "line 1000 " not in out
    saved = next(tmp_path.glob("*.txt"))
    assert str(saved) in out and saved.read_text() == big
    assert tempest.offload("small", "shell", "c2", tmp_path, 2000) == "small"
    assert tempest.offload(big, "read_file", "c3", tmp_path, 2000) == big


def _wire(n):
    w = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(n):
        args = json.dumps({"command": f"cmd{i}"})
        w.append({"role": "assistant", "content": None,
                  "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "shell", "arguments": args}}]})
        w.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 1000})
    return w


def test_mask_old_observations_in_blocks():
    st = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_mask_mode": "turn"}})
    masked = [m for m in tempest.mask_wire(_wire(9), st) if m["role"] == "tool"
              and m["content"].startswith("[output alat lama")]
    assert masked == []  # 9 - 6 = 3 old turns < block of 4: nothing moves yet
    out = tempest.mask_wire(_wire(10), st)
    tools = [m for m in out if m["role"] == "tool"]
    assert all(m["content"].startswith("[output alat lama") for m in tools[:4])
    assert all(m["content"] == "y" * 1000 for m in tools[4:])


def test_live_reads_are_not_masked():
    st = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_mask_mode": "turn"}})
    w = _wire(10)
    w[2]["tool_calls"][0]["function"] = {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}
    out = tempest.mask_wire(w, st)
    assert out[3]["content"] == "y" * 1000  # a.py was read and not touched since


def test_syntax_error(tmp_path):
    good, bad = tmp_path / "a.py", tmp_path / "b.py"
    good.write_text("x = 1\n")
    bad.write_text("def f():\n  return 1\n    x\n")
    assert tempest.syntax_error(good) is None and "IndentationError" in tempest.syntax_error(bad)
    j = tmp_path / "c.json"
    j.write_text('{"a": 1,}')
    assert "JSONDecodeError" in tempest.syntax_error(j)
    (tmp_path / "d.txt").write_text("{{{")
    assert tempest.syntax_error(tmp_path / "d.txt") is None


def test_detect_verify(tmp_path):
    assert tempest.detect_verify(tmp_path) is None
    (tmp_path / "tests").mkdir()
    assert "pytest" in tempest.detect_verify(tmp_path)
    other = tmp_path / "js"
    other.mkdir()
    (other / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert tempest.detect_verify(other)[:2] == ["npm", "test"]


async def test_agent_legacy_wire_unchanged_and_tempest_gate(home, tmp_path, monkeypatch):
    """Legacy: no tail, date in system prompt, no gate. Tempest: broken .py write is rejected
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

    # tempest: broken syntax rejected, then wrong value caught by the gate, then fixed
    cfg = cfgmod.load_config()
    cfg["agent"]["harness_mode"] = "tempest"
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


# ------------------------------------------------------------ cache layout v2 -----

def test_stable_tools_order_and_keys():
    a = [{"type": "function", "function": {"name": "b", "parameters": {"y": 1, "x": 2}, "description": "d"}},
         {"function": {"description": "d", "name": "a"}, "type": "function"}]
    b = [{"function": {"name": "a", "description": "d"}, "type": "function"},
         {"function": {"parameters": {"x": 2, "y": 1}, "description": "d", "name": "b"}, "type": "function"}]
    assert json.dumps(tempest.stable_tools(a)) == json.dumps(tempest.stable_tools(b))
    assert [t["function"]["name"] for t in tempest.stable_tools(a)] == ["a", "b"]


def test_config_change_note():
    old = [["soul", "s"], ["memory", "m1"], ["cwd", "Current working directory: /a"]]
    new = [["soul", "s"], ["memory", "m2"], ["skills", "k"], ["cwd", "Current working directory: /b"]]
    note = tempest.config_change_note(old, new)
    assert note.startswith("# Perubahan konfigurasi") and "m2" in note and "/b" in note and "k" in note
    assert "Persona dasar" not in note  # unchanged sections are not repeated
    assert "dihapus" in tempest.config_change_note(old, old[:2])
    assert tempest.config_change_note(old, old) == ""


def test_place_breakpoints_max_four_and_stable_bytes():
    wire = [{"role": "system", "content": "STATIC PART\n\nsemi static"}, {"role": "user", "content": "u"}]
    for i in range(6):
        wire.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]})
        wire.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"out {i}"})
    out = tempest.place_breakpoints(wire, len("STATIC PART") + 2, 9)
    assert tempest.count_breakpoints(out) == 4
    assert out[0]["content"][0]["text"] == "STATIC PART\n\n" and out[0]["content"][0]["cache_control"]
    assert out[-1]["content"][-1]["cache_control"] and out[9]["content"][-1]["cache_control"]
    assert isinstance(out[1]["content"], list) and out[2]["content"] is None  # tool-call turn untouched
    assert wire[1]["content"] == "u"  # input not mutated
    # without a split: system + 2 messages = 3, never more than 4
    assert tempest.count_breakpoints(tempest.place_breakpoints(wire, None, 5)) == 3
    one = tempest.place_breakpoints(wire, None, None, ttl="1h")
    assert one[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # the next call (two more messages) keeps every earlier message byte-identical (markers aside)
    nxt = wire + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "lagi"}]
    assert tempest.prefix_violation(out, tempest.place_breakpoints(nxt, len("STATIC PART") + 2, len(wire) - 1)) is None


def test_wants_breakpoints():
    st = {"cache_v2": True, "cache_breakpoints": "auto"}
    assert tempest.wants_breakpoints(st, {"model": "anthropic/claude-sonnet-4.5"})
    assert tempest.wants_breakpoints(st, {"model": "x", "base_url": "https://api.anthropic.com/v1"})
    assert not tempest.wants_breakpoints(st, {"model": "deepseek-chat"})
    assert not tempest.wants_breakpoints({"cache_v2": False}, {"model": "claude-3"})
    assert tempest.wants_breakpoints({**st, "cache_breakpoints": "on"}, {"model": "gpt"})
    assert not tempest.wants_breakpoints({**st, "cache_breakpoints": "off"}, {"model": "claude"})


def test_prefix_violation_and_cached_tokens():
    a = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert tempest.prefix_violation(None, a) is None
    assert tempest.prefix_violation(a, a + [{"role": "assistant", "content": "x"}]) is None
    assert tempest.prefix_violation(a, [{"role": "system", "content": "s2"}, a[1]]) == 0
    # the previous call's LAST message may differ (ephemeral tail), anything before may not
    assert tempest.prefix_violation(a, [a[0], {"role": "user", "content": "u + tail"}]) is None
    assert tempest.cached_tokens({"prompt_tokens_details": {"cached_tokens": 1280}}) == 1280
    assert tempest.cached_tokens({"cache_read_input_tokens": 77}) == 77
    assert tempest.cached_tokens({}) == 0


async def _multi_turn(home, tmp_path, monkeypatch, agent_cfg, model="m"):
    """4 turns with tool calls; between turns the clock moves, a memory note and a skill
    appear, and the working directory changes. Returns every wire + tools the model saw."""
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion, ToolCall
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": model, "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "sub").mkdir()
    clock = ["2026-10-11 09:00"]
    monkeypatch.setattr(agentmod, "now_text", lambda _c: clock[0])
    seen = []

    async def fake(*, messages, tools=None, **_kw):
        seen.append((messages, tools))
        if messages[-1]["role"] == "user":
            return Completion(text="", tool_calls=[ToolCall(id=f"r{len(seen)}", name="read_file",
                                                            arguments=json.dumps({"path": "a.txt"}))])
        return Completion(text="ok")
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    await agent.run_turn("satu")
    clock[0] = "2026-10-11 09:07"
    await agent.run_turn("dua")
    (home / "memory").mkdir(exist_ok=True)
    (home / "memory" / "proyek.md").write_text("kode: TULIP-7\n")
    sk = home / "skills" / "baru"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: baru\ndescription: skill baru\n---\n")
    await agent.run_turn("tiga")
    agent.ctx.cwd = tmp_path / "sub"
    await agent.run_turn("empat")
    return seen, rec


async def test_cache_v2_prefix_never_changes_across_turns(home, tmp_path, monkeypatch):
    """The prefix lint: with cache v2 every call's wire extends the previous one byte for byte,
    even across clock, memory, skill and cwd changes; the changes arrive as appended notes."""
    seen, rec = await _multi_turn(home, tmp_path, monkeypatch,
                                  {"harness_mode": "tempest", "tempest_mask": False, "tempest_cache_v2": True})
    assert len(seen) == 8
    for (prev, _), (cur, _) in zip(seen, seen[1:]):
        assert tempest.prefix_violation(prev, cur) is None
    tools = [json.dumps(t, sort_keys=False) for _, t in seen]
    assert len(set(tools)) == 1 and json.loads(tools[0]) == tempest.stable_tools(json.loads(tools[0]))
    last_user = [m for m in seen[-1][0] if m["role"] == "user"]
    assert "TULIP-7" in last_user[2]["content"] and "baru" in last_user[2]["content"]
    assert "Perubahan konfigurasi" in last_user[3]["content"] and str(tmp_path / "sub") in last_user[3]["content"]
    assert "TULIP-7" not in seen[-1][0][0]["content"]  # the system prompt stayed frozen


async def test_without_cache_v2_the_prefix_breaks(home, tmp_path, monkeypatch):
    """Sanity check for the lint: Phase-1 Tempest rebuilds the system prompt (memory/skill/cwd)."""
    seen, _ = await _multi_turn(home, tmp_path, monkeypatch, {"harness_mode": "tempest", "tempest_mask": False,
                                                              "tempest_cache_v2": False, "tempest_compact": False})
    breaks = [tempest.prefix_violation(p, c) for (p, _), (c, _) in zip(seen, seen[1:])]
    assert any(b == 0 for b in breaks)


async def test_cache_v2_anthropic_breakpoints(home, tmp_path, monkeypatch):
    seen, _ = await _multi_turn(home, tmp_path, monkeypatch,
                                {"harness_mode": "tempest", "tempest_mask": False, "tempest_cache_v2": True},
                                model="claude-haiku-4.5")
    for wire, _ in seen:
        assert 1 <= tempest.count_breakpoints(wire) <= 4
        assert wire[0]["content"][-1].get("cache_control")
    for (prev, _), (cur, _) in zip(seen, seen[1:]):
        assert tempest.prefix_violation(prev, cur) is None


# ------------------------------------------------------ recoverable compaction -----

def test_compact_settings_and_model_override():
    st = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_compact": True}})
    assert st["mask_mode"] == "compact" and st["compact"] and st["mask"] is False
    st = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_compact": True,
                                     "tempest_model_overrides": {"gemini-2.5-flash*": {"compact": False}}}})
    assert tempest.for_model(st, "gemini-2.5-flash-thinking")["compact"] is False
    assert tempest.for_model(st, "deepseek-chat")["compact"] is True
    # Phase-1 behaviour is unchanged when compaction is off
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_compact": False}})["mask_mode"] == "turn"
    # tempest_mask: false only ever meant "no per-turn masking"; boundary compaction stays on
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_mask": False}})["mask_mode"] == "compact"
    assert tempest.settings({"agent": {"harness_mode": "tempest", "tempest_mask": False,
                                       "tempest_compact": False}})["mask_mode"] == "off"


def _transcript(tmp_path):
    """user, then 8 assistant turns: shell (big), read_file (big), a small failing test run, ..."""
    (tmp_path / "big.py").write_text("x = 1\n" * 400)
    msgs = [{"role": "user", "content": "audit repo"}]
    for i in range(8):
        name, args = [("shell", {"command": f"cat log{i}"}), ("read_file", {"path": str(tmp_path / f"big{i}.py")}),
                      ("shell", {"command": "pytest"})][i % 3]
        content = {"shell": "line\n" * 600, "read_file": "     1\tx = 1\n" * 300}[name]
        if args.get("command") == "pytest":
            content = "FAILED tests/test_a.py::test_x - assert 1 == 2\n1 failed in 0.01s"
        msgs.append({"role": "assistant", "content": f"catatan {i}",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": name, "arguments": json.dumps(args)}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": name, "content": content})
    return msgs


def _measure(msgs):
    base = [{"role": "system", "content": "sys"}] + [dict(m) for m in msgs]
    return base, (lambda state: tempest.wire_tokens(tempest.apply_compaction(base, state)))


def test_compact_stage1_masks_old_outputs_keeps_live_reads_and_errors(tmp_path):
    msgs = _transcript(tmp_path)
    base, measure = _measure(msgs)
    st = {"compact_target": 0.9, "compact_keep_turns": 2}
    state, rep = tempest.compact(msgs, None, st, measure(None), tmp_path / "obs", measure)
    assert rep["stage"] == 1 and rep["after"] < rep["before"]
    out = tempest.apply_compaction(base, state)
    by_id = {m.get("tool_call_id"): m["content"] for m in out if m["role"] == "tool"}
    assert by_id["c0"].startswith("[output alat lama dipindah ke ")
    saved = by_id["c0"].split("dipindah ke ")[1].split(" ")[0]
    assert open(saved).read() == "line\n" * 600  # recoverable: the full text is on disk
    assert by_id["c2"].startswith("FAILED")  # small failure kept in
    assert by_id["c7"] == msgs[-1]["content"]  # newest turns untouched
    assert not by_id["c4"].startswith("[output")  # read of big4.py is live (never edited/re-read)
    assert tempest.apply_compaction(base, state) == out  # deterministic: same prefix every call


def test_compact_stage2_and_stage3(tmp_path):
    msgs = _transcript(tmp_path)
    base, measure = _measure(msgs)
    full = measure(None)
    state, rep = tempest.compact(msgs, None, {"compact_target": 0.25, "compact_keep_turns": 2}, full,
                                 tmp_path / "obs", measure)
    assert rep["stage"] >= 2
    assert "isi file yang dibaca" in state["masked"]["c1"] and "big1.py" in state["masked"]["c1"]
    state, rep = tempest.compact(msgs, None, {"compact_target": 0.01, "compact_keep_turns": 2}, full,
                                 tmp_path / "obs", measure)
    assert rep["stage"] == 3
    out = tempest.apply_compaction(base, state)
    assert out[1]["content"].startswith(tempest.SUMMARY_MARK)
    summ = out[1]["content"]
    assert "audit repo" in summ and "catatan 0" in summ and "big4.py" in summ and "1 failed" in summ
    # the summary replaced whole turns: no orphan tool result right after it
    assert out[2]["role"] == "assistant"


async def test_agent_compacts_at_threshold_only(home, tmp_path, monkeypatch):
    """Small window: compaction fires when the wire crosses 50%, not on every call, and the
    prefix stays byte-identical between compactions."""
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion, ToolCall
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1",
                    "context_length": 16000}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update({"harness_mode": "tempest", "tempest_compact": True, "tempest_cache_v2": True,
                                        "tempest_offload_tokens": 100000})
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    for i in range(14):
        (tmp_path / f"f{i}.txt").write_text(f"file {i}\n" + "data " * 500)
    seen, events = [], []

    async def fake(*, messages, tools=None, **_kw):
        seen.append(messages)
        n = len(seen)
        if n <= 14:
            return Completion(text=f"catatan {n}", tool_calls=[ToolCall(
                id=f"s{n}", name="shell", arguments=json.dumps({"command": f"cat f{n - 1}.txt"}))])
        return Completion(text="selesai")
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: events.append((k, p)))
    assert await agent.run_turn("baca semua file") == "selesai"
    compactions = [p for k, p in events if k == "status.update" and p.get("kind") == "compact"]
    assert 1 <= len(compactions) <= 4
    assert all(tempest.wire_tokens(w) < 16000 for w in seen)
    breaks = [i for i, (a, b) in enumerate(zip(seen, seen[1:])) if tempest.prefix_violation(a, b) is not None]
    assert len(breaks) == len(compactions)  # the cache breaks once per compaction, never in between
    assert rec["tempest_compact"]["masked"]
