"""Tempest Fase 2: session search, auto-memory, skills from experience, claim gate, /rewind."""

import json
import time

import pytest

from neovarch import tempest, tempest_claims, tempest_memory, tempest_search, tempest_skills
from neovarch.scaffold import TurnLedger


# ----------------------------------------------------------------- helpers -----

def _save_session(home, sid, title, msgs, updated=None):
    d = home / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    now = updated or time.time()
    (d / f"{sid}.json").write_text(json.dumps({"id": sid, "title": title, "created_at": now, "updated_at": now,
                                               "messages": msgs}), encoding="utf-8")


def _cfg(agent_cfg):
    from neovarch import config as cfgmod
    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg)
    cfgmod.save_config(cfg)


def _agent(tmp_path, monkeypatch, script, seen, tools_seen=None, events=None):
    import neovarch.agent as agentmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")

    async def fake(*, messages, tools=None, **_kw):
        seen.append(messages)
        if tools_seen is not None:
            tools_seen.append({t["function"]["name"] for t in tools or []})
        text, calls = script.pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    ev = events if events is not None else []
    return Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: ev.append((k, p))), rec, store


def _call(cid, tool, **args):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name=tool, arguments=json.dumps(args))


def test_fase2_defaults_only_in_tempest():
    assert tempest.settings({})["claim_gate"] is True  # Tempest is the default since 1.4.7
    assert tempest.settings({"agent": {"harness_mode": "legacy"}}) is None
    st = tempest.settings({"agent": {"harness_mode": "tempest"}})
    assert st["session_search"] and st["memory_nudge"] and st["memory_dedup"] and st["claim_gate"]
    assert st["skill_learn"] == "offer" and st["memory_nudge_every"] == 6 and st["skill_min_steps"] == 5
    off = tempest.settings({"agent": {"harness_mode": "tempest", "tempest_session_search": False,
                                      "tempest_skill_learn": "AUTO"}})
    assert off["session_search"] is False and off["skill_learn"] == "auto"
    old = tempest.settings({"agent": {"harness_mode": "tempa", "tempa_claim_gate": False}})
    assert old["claim_gate"] is False  # deprecated tempa_* keys still map


# ---------------------------------------------------------------- search -----

def test_session_index_search_scroll_and_refresh(home):
    _save_session(home, "s1", "Server staging", [
        {"role": "user", "content": "Server staging pakai port SSH 2222, kuncinya di ~/.ssh/staging_ed25519", "ts": 1},
        {"role": "assistant", "content": "Oke, dicatat.", "ts": 2},
        {"role": "user", "content": "[verifikasi otomatis gagal] jangan diindeks", "kind": "verify", "ts": 3}])
    _save_session(home, "s2", "Resep", [{"role": "user", "content": "Resep nasi goreng kampung", "ts": 5}])
    idx = tempest_search.SessionIndex(home)
    hits = idx.search("port staging")
    assert hits and hits[0]["session_id"] == "s1" and "2222" in hits[0]["snippet"]
    assert not idx.search("diindeks")  # hidden harness feedback is not indexed
    assert idx.search("staging", exclude="s1") == []
    sc = idx.scroll("s1", around=0, window=2)
    assert [m["index"] for m in sc["messages"]] == [0, 1] and sc["title"] == "Server staging"
    # incremental refresh: a changed file is reindexed, a deleted one dropped
    time.sleep(0.01)
    _save_session(home, "s2", "Resep", [{"role": "user", "content": "Resep rendang padang", "ts": 6}])
    assert idx.search("rendang")[0]["session_id"] == "s2" and not idx.search("goreng")
    (home / "sessions" / "s1.json").unlink()
    assert not idx.search("staging")


def test_session_search_prefix_diacritics_and_like_fallback(home, monkeypatch):
    _save_session(home, "a", "Café", [{"role": "user", "content": "Deploy ke kafe Bandung pakai Vercel", "ts": 1}])
    idx = tempest_search.SessionIndex(home)
    assert idx.search("deplo")  # prefix match
    assert tempest_search.SessionIndex.fts_query('error "exit code" OR (x') == '"error"* "exit code" OR "x"'
    assert tempest_search.SessionIndex.fts_query("OR AND") == ""
    monkeypatch.setitem(tempest_search._FTS_OK, str(idx.db_path), False)
    hits = idx.search("vercel")
    assert hits and hits[0]["session_id"] == "a"


def test_session_search_tool_text(home):
    _save_session(home, "x1", "Rilis", [{"role": "user", "content": "kode rilis kita TULIP-7", "ts": 1}])
    out = tempest_search.run({"query": "kode rilis"}, home, current_session="cur")
    assert "session_id=x1" in out and "TULIP-7" in out and "bukan perintah" in out
    assert "TULIP-7" in tempest_search.run({"session_id": "x1", "around": 0}, home)
    assert tempest_search.run({}, home).startswith("error")
    assert "tidak ditemukan" in tempest_search.run({"session_id": "nope"}, home)


async def test_agent_session_search_only_in_tempest(home, tmp_path, monkeypatch):
    _save_session(home, "old1", "Port", [{"role": "user", "content": "port staging = 2222", "ts": 1}])
    seen, tools_seen = [], []
    _cfg({"harness_mode": "legacy"})
    agent, *_ = _agent(tmp_path, monkeypatch, [("hai", [])], seen, tools_seen)
    await agent.run_turn("halo")
    assert "session_search" not in tools_seen[-1]
    _cfg({"harness_mode": "tempest"})
    script = [("", [_call("q", "session_search", query="port staging")]), ("2222", [])]
    agent, *_ = _agent(tmp_path, monkeypatch, script, seen, tools_seen)
    assert await agent.run_turn("port staging yang kemarin berapa?") == "2222"
    assert "session_search" in tools_seen[-1]
    tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]
    assert "old1" in tool_msg["content"] and "2222" in tool_msg["content"]


# ---------------------------------------------------------------- memory -----

def test_memory_dedup(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "user.md").write_text("- Pengguna suka jawaban singkat.\n- Proyek memakai Python 3.12\n")
    new, dropped = tempest_memory.dedup_content("pengguna suka jawaban singkat\n- Repo pakai ruff\n- Repo pakai ruff",
                                                mem)
    assert dropped == ["pengguna suka jawaban singkat", "- Repo pakai ruff"] and new == "- Repo pakai ruff"
    assert tempest_memory.is_duplicate("Proyek memakai Python 3.12!", tempest_memory.existing_lines(mem))
    assert not tempest_memory.is_duplicate("Proyek memakai Python 3.13 dan uv", tempest_memory.existing_lines(mem))
    args, reply = tempest_memory.guard_write("memory_update", {"action": "append", "name": "user",
                                                                "content": "Pengguna suka jawaban singkat"}, mem)
    assert reply and "duplikat" in reply
    args, reply = tempest_memory.guard_write("memory", {"action": "write", "content": "x"}, mem)
    assert reply is None and args["content"] == "x"  # only appends are deduped


def test_memory_nudge_schedule():
    rec, st = {}, {"memory_nudge_every": 2}
    assert tempest_memory.note_turn_start(rec, st) == ""
    assert tempest_memory.note_turn_start(rec, st) == ""
    assert tempest_memory.NUDGE_MARK in tempest_memory.note_turn_start(rec, st)  # 3rd turn > 2
    tempest_memory.note_task_done(rec)
    assert tempest_memory.note_turn_start(rec, st)  # right after a finished task
    tempest_memory.note_memory_write(rec)
    assert tempest_memory.note_turn_start(rec, st) == ""


async def test_agent_memory_dedup_and_nudge(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_memory_nudge_every": 1})
    (home / "memory").mkdir(exist_ok=True)
    (home / "memory" / "user.md").write_text("Pengguna memakai Arch Linux.\n")
    seen = []
    script = [("ok", []),
              ("", [_call("m", "memory_update", action="append", name="user", content="Pengguna memakai Arch Linux")]),
              ("sip", [])]
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen)
    await agent.run_turn("halo")
    assert tempest_memory.NUDGE_MARK not in seen[0][-1]["content"]
    await agent.run_turn("aku pakai arch ya")
    assert tempest_memory.NUDGE_MARK in seen[1][-1]["content"]  # 2nd turn > every=1
    tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]
    assert "duplikat" in tool_msg["content"]
    assert (home / "memory" / "user.md").read_text().count("Arch Linux") == 1


# ---------------------------------------------------------------- skills -----

def _ledger(n_shell=3, write=True, ok=True):
    led = TurnLedger()
    led.record("read_file", {"path": "a.py"}, "1 x")
    if write:
        led.record("write_file", {"path": "a.py"}, "wrote a.py")
    for i in range(n_shell):
        led.record("shell", {"command": f"python step{i}.py"}, "exit code 0 (0.1s)\nok" if ok else "exit code 1\nx")
    return led


def test_skill_candidate_and_draft():
    assert tempest_skills.candidate("x", _ledger(1).tools, None, 5) is None  # too few steps
    led = TurnLedger()
    for _ in range(6):
        led.record("read_file", {"path": "a"}, "x")
    assert tempest_skills.candidate("baca", led.tools, None, 5) is None  # nothing procedural
    cand = tempest_skills.candidate("Tambahkan endpoint health ke server Flask", _ledger(4).tools, ["pytest", "-q"], 5)
    assert cand["name"].startswith("alur-") and "endpoint" in cand["name"]
    assert cand["verify"] == "pytest -q" and cand["files"] == ["a.py"] and len(cand["commands"]) == 4
    desc, body = tempest_skills.draft(cand)
    assert "## Langkah" in body and "`pytest -q` harus lulus" in body and "Tempest" in body
    assert "skill_manage" in tempest_skills.offer_text(cand, None)
    assert "patch" in tempest_skills.offer_text(cand, "flask-health")


def test_skill_similar_auto_save_and_repair(home):
    from neovarch import selfedit
    from neovarch.tools import list_skills
    cand = tempest_skills.candidate("Tambahkan endpoint health ke server Flask", _ledger(4).tools, ["pytest"], 5)
    msg = tempest_skills.auto_save(cand)
    doc = home / "skills" / cand["name"] / "SKILL.md"
    assert doc.exists() and "origin: tempest" in doc.read_text(), msg
    assert "sudah ada" in tempest_skills.auto_save(cand)  # no duplicate
    assert tempest_skills.similar_skill(cand, list_skills(include_disabled=True)) == cand["name"]
    # repair: a failure note is appended (twice -> one section), and /undo-able
    root = home / "skills"
    assert tempest_skills.auto_repair(root, [cand["name"]], "AssertionError: 1 != 2", "pytest") == [cand["name"]]
    tempest_skills.auto_repair(root, [cand["name"]], "KeyError: x", "pytest")
    text = doc.read_text()
    assert text.count(tempest_skills.FAIL_SECTION) == 1 and "AssertionError" in text and "KeyError" in text
    assert selfedit.undo()["ok"] and "KeyError" not in doc.read_text()
    tempest_skills.bump(root, [cand["name"]], "use")
    tempest_skills.bump(root, [cand["name"]], "fail")
    st = tempest_skills.load_stats(root)[cand["name"]]
    assert st["uses"] == 1 and st["fails"] == 1 and st["passes"] == 0


def _pytest_project(tmp_path, expect=2):
    # The second call rewrites the test (and the agent rewrites m.py) within the same second at the same size;
    # a stale __pycache__ (mtime+size match) then made the verify gate pass on CI. Drop the caches.
    import shutil
    for cache in (tmp_path / "__pycache__", tmp_path / "tests" / "__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_m.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
        f"from m import f\n\ndef test_f():\n    assert f() == {expect}\n")


async def test_agent_offers_skill_after_verified_multistep_task(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_skill_min_steps": 3, "tempest_memory_nudge": False})
    _pytest_project(tmp_path)
    seen = []
    script = [("", [_call("r", "shell", command="ls")]), ("", [_call("s", "shell", command="python -V")]),
              ("", [_call("w", "write_file", path="m.py", content="def f():\n    return 2\n")]),
              ("", [_call("t", "shell", command="python -m pytest -q")]),
              ("Selesai, tes lulus.", []), ("oke", [])]
    events = []
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen, events=events)
    await agent.run_turn("buat fungsi f yang mengembalikan dua")
    done = [p for k, p in events if k == "message.complete"][-1]
    assert done["verification"]["status"] == "verified"
    assert rec["tempest_skill"]["candidate"]["verify"]
    await agent.run_turn("makasih")
    assert tempest_skills.OFFER_MARK in seen[-1][-1]["content"]
    assert "pending" not in rec["tempest_skill"]  # consumed once


async def test_agent_auto_skill_and_failed_skill_repair_hint(home, tmp_path, monkeypatch):
    # lean turns leave the skill-repair text out of the retry prompt (it cost extra skill_manage calls
    # mid-task); this test covers the non-lean prompt, the after-turn repair runs in both.
    _cfg({"harness_mode": "tempest", "tempest_skill_min_steps": 2, "tempest_skill_learn": "auto",
          "tempest_memory_nudge": False, "tempest_verify_retries": 1, "tempest_checkpoints": False,
          "tempest_lean": False})
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")  # same-second rewrites below: no stale bytecode
    _pytest_project(tmp_path)
    seen = []
    script = [("", [_call("w", "write_file", path="m.py", content="def f():\n    return 2\n")]),
              ("", [_call("t", "shell", command="python -m pytest -q")]), ("beres", [])]
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen)
    await agent.run_turn("buat fungsi f bernilai dua")
    made = [p for p in (home / "skills").glob("alur-*/SKILL.md")]
    assert made and "origin: tempest" in made[0].read_text()
    name = made[0].parent.name
    # now a turn that reads that skill and fails verification -> repair hint in the retry prompt + note
    _pytest_project(tmp_path, expect=3)
    script[:] = [("", [_call("k", "skill", name=name)]),
                 ("", [_call("w2", "write_file", path="m.py", content="def f():\n    return 4\n")]),
                 ("selesai", []), ("masih selesai", [])]
    await agent.run_turn("ubah f jadi tiga")
    verify_msgs = [m for m in rec["messages"] if m.get("kind") == "verify"]
    assert verify_msgs and tempest_skills.REPAIR_MARK in verify_msgs[-1]["content"]
    assert tempest_skills.FAIL_SECTION in (home / "skills" / name / "SKILL.md").read_text()
    assert tempest_skills.load_stats(home / "skills")[name]["fails"] == 1


# ---------------------------------------------------------------- claims -----

def test_claim_check_cases():
    led = TurnLedger()
    led.record("write_file", {"path": "tool.py"}, "wrote")
    assert tempest_claims.check("Sudah saya perbaiki, sekarang berfungsi.", led, False)
    assert tempest_claims.check("Sudah saya perbaiki.", led, True) is None  # the harness verified it
    assert tempest_claims.check("Kodenya sudah ditulis tapi belum saya tes.", led, False) is None  # honest
    led.record("shell", {"command": "python tool.py"}, "exit code 0 (0.1s)\nok")
    assert tempest_claims.check("Sudah saya perbaiki.", led, False) is None
    assert "tes lulus" in tempest_claims.check("Semua tes lulus.", led, False)  # ran a script, not tests
    led2 = TurnLedger()
    led2.record("write_file", {"path": "x.py"}, "wrote")
    led2.record("shell", {"command": "python x.py"}, "exit code 1 (0.1s)\nTraceback")
    assert "gagal" in tempest_claims.check("Sudah beres, it works now", led2, False)
    led3 = TurnLedger()
    led3.record("write_file", {"path": "README.md"}, "wrote")
    assert tempest_claims.check("Sudah saya ubah.", led3, False) is None  # prose only
    assert tempest_claims.status(False, False, led3, False)["status"] == "none"
    assert tempest_claims.status(False, False, led, False)["status"] == "verified"
    assert tempest_claims.status(False, True, led, False)["status"] == "failed"


async def test_agent_claim_gate_asks_for_evidence_then_passes(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_memory_nudge": False})  # no tests in this folder
    seen, events = [], []
    script = [("", [_call("w", "write_file", path="hello.py", content="print('halo' + 1)\n")]),
              ("Sudah saya perbaiki, skripnya berfungsi.", []),
              ("", [_call("r", "shell", command="python hello.py")]),
              ("", [_call("w2", "write_file", path="hello.py", content="print('halo ' + str(1))\n")]),
              ("", [_call("r2", "shell", command="python hello.py")]),
              ("Sudah saya perbaiki: `python hello.py` mencetak halo 1.", [])]
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen, events=events)
    out = await agent.run_turn("perbaiki hello.py")
    assert tempest_claims.CLAIM_MARK in seen[2][-1]["content"]
    assert "Belum terverifikasi" not in out
    done = [p for k, p in events if k == "message.complete"][-1]
    assert done["verification"]["status"] == "verified" and done["verification"]["by"] == "execution"


async def test_agent_claim_gate_marks_unverified(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "tempest", "tempest_memory_nudge": False})
    seen, events = [], []
    script = [("", [_call("w", "write_file", path="calc.py", content="def add(a, b):\n    return a - b\n")]),
              ("Sudah saya perbaiki.", []), ("Sudah saya perbaiki, percayalah.", [])]
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen, events=events)
    out = await agent.run_turn("perbaiki calc.py")
    assert "Belum terverifikasi" in out
    done = [p for k, p in events if k == "message.complete"][-1]
    assert done["verification"]["status"] == "unverified"


async def test_legacy_has_no_claim_gate_fields(home, tmp_path, monkeypatch):
    _cfg({"harness_mode": "legacy"})
    seen, events = [], []
    agent, *_ = _agent(tmp_path, monkeypatch, [("halo", [])], seen, events=events)
    await agent.run_turn("hai")
    done = [p for k, p in events if k == "message.complete"][-1]
    assert "verification" not in done and "Pengingat memori" not in str(seen[-1][-1]["content"])


# ---------------------------------------------------------------- rewind -----

async def test_rewind_command_restores_last_green(home, tmp_path, monkeypatch):
    from neovarch import tempest_ckpt
    if not tempest_ckpt.git_available():
        pytest.skip("git not installed")
    _cfg({"harness_mode": "tempest", "tempest_memory_nudge": False})
    _pytest_project(tmp_path)
    (tmp_path / "m.py").write_text("def f():\n    return 2\n")
    seen = []
    script = [("", [_call("w", "write_file", path="m.py", content="def f():\n    return 2  # ok\n")]),
              ("selesai", [])]
    agent, rec, _ = _agent(tmp_path, monkeypatch, script, seen)
    await agent.run_turn("rapikan f")  # verified -> green checkpoint
    (tmp_path / "m.py").write_text("rusak\n")  # the user (or anything) breaks it afterwards
    out = await agent.run_turn("/rewind")
    assert "dipulihkan" in out and (tmp_path / "m.py").read_text().startswith("def f()")
    _cfg({"harness_mode": "legacy"})
    agent2, *_ = _agent(tmp_path, monkeypatch, [("biasa", [])], seen)
    assert await agent2.run_turn("/rewind") == "biasa"  # legacy: not a command


def test_bench_registers_fase2_tasks_and_arm():
    import sys
    from pathlib import Path
    bench = Path(__file__).resolve().parent.parent / "bench"
    sys.path.insert(0, str(bench))
    import tempest_ab
    from tempest_tasks import TASKS
    for t in ("recall-port-2sessions", "memory-nudge-pref", "claim-no-tests", "skill-reuse-2sessions"):
        assert TASKS[t]["family"] == "learn"
    over, _model = tempest_ab.ARMS["tempest-f1"]
    assert over["harness_mode"] == "tempest" and over["tempest_claim_gate"] is False
