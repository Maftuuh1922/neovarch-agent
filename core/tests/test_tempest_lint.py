"""Tempest delta static gate: builtin checker, delta vs baseline, agent integration."""

import json
import textwrap

import pytest

from neovarch import tempest_lint as tl


def _codes(src):
    return sorted((d.code, d.message) for d in tl.builtin_python(textwrap.dedent(src), "m.py"))


def test_builtin_catches_seeded_defects():
    assert _codes("""
        def f(p):
            if p < 0:
                raise ValeuError("x")
            return p
        """) == [("F821", "undefined name 'ValeuError'")]
    assert ("F821", "undefined name 'json'") in _codes("def f(r):\n    return json.dumps(r)\n")
    assert _codes("""
        def clamp(x, lo, hi):
            return max(lo, min(hi, x))

        def g(v):
            return clamp(v, 100)
        """) == [("E1120", "call to 'clamp' is missing argument 'hi'")]
    assert _codes("def h(a):\n    return a\n\nh(1, 2)\n")[0][0] == "E1121"
    assert _codes("def h(a, *, b=1):\n    return a\n\nh(1, c=2)\n")[0][0] == "E1123"
    assert _codes("def f(:\n")[0][0] == "E999"


def test_builtin_has_no_false_positives_on_common_code():
    assert _codes("""
        import os, os.path as osp
        from typing import Any
        X = [i for i in range(3)]
        CONST = {k: v for k, v in zip("ab", "cd")}

        class A:
            attr = 1

            def m(self, *args, **kw):
                return self.attr, args, kw, __class__, __name__, __file__

        def deco(f):
            return f

        @deco
        def wrapped(a):
            return a

        def uses(**kw):
            global G
            G = 1
            try:
                pass
            except Exception as exc:
                print(exc)
            if (n := len(X)) > 1:
                print(n)
            match kw:
                case {"a": aa, **rest}:
                    print(aa, rest)
                case [first, *others]:
                    print(first, others)
            f = lambda q: q + 1
            wrapped(1, 2)  # decorated: signature unknown, not checked
            return f(osp.join(os.sep, "x")), Any
        """) == []
    assert _codes("from x import *\nprint(anything)\n") == []  # star import: undefined-name check off


def test_delta_reports_only_new_diagnostics(tmp_path):
    f = tmp_path / "mod.py"
    old = "def old():\n    return render_table()  # pre-existing, not ours\n"
    f.write_text(old + "\ndef wc(s):\n    return len(s.split())\n")
    before = {str(f): f.read_bytes()}
    f.write_text(old + "\ndef wc(s):\n    return len(s.split()) + extra\n")
    out = tl.delta(tmp_path, before, ["builtin"])
    assert [d.message for d in out] == ["undefined name 'extra'"]
    assert "extra" in f.read_text()  # the current content is back in place
    f.write_text(old + "\ndef wc(s):\n    return len(s.split()) + 0\n")
    assert tl.delta(tmp_path, before, ["builtin"]) == []  # clean edit in a file with old debt
    new = tmp_path / "new.py"
    new.write_text("def f():\n    return missing\n")
    out = tl.delta(tmp_path, {str(new): None}, ["builtin"])
    assert [d.code for d in out] == ["F821"] and new.exists()


def test_external_checkers_skip_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(tl.shutil, "which", lambda _n: None)
    monkeypatch.setattr(tl, "_which_ruff", lambda: None)
    assert tl.available(tmp_path) == ["builtin"]
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    for runner in tl.RUNNERS.values():
        assert runner(tmp_path, [f], 5) == []
    assert tl.delta(tmp_path, {str(tmp_path / "notes.md"): b""}) == []  # nothing lintable


@pytest.mark.skipif(tl._which_ruff() is None, reason="ruff not installed")
def test_ruff_runner(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return nope\n")
    assert any(d.code == "F821" for d in tl.run_ruff(tmp_path, [f], 60))


def test_gate_prompt_text():
    d = tl.Diag("a.py", 3, "F821", "undefined name 'x'", "builtin")
    text = tl.gate_prompt([d], 1, 1)
    assert text.startswith("[pemeriksaan statis gagal") and "a.py:3: F821 undefined name 'x'" in text
    assert "hanya diagnostik baru" in text


async def _gate_run(home, tmp_path, monkeypatch, agent_cfg, script, base_src):
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
    (tmp_path / "shop.py").write_text(base_src)
    seen = []

    async def fake(*, messages, **_kw):
        seen.append(messages)
        text, calls = script.pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=None), lambda k, p: None)
    final = await agent.run_turn("tambahkan discount")
    return final, seen, rec


def _edit(cid, old, new):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name="edit_file", arguments=json.dumps({"path": "shop.py", "old_text": old, "new_text": new}))


BASE = "def legacy():\n    return render_table()\n\n\ndef fee(p):\n    return p + 1\n"


async def test_agent_lint_gate_blocks_new_diagnostic_once(home, tmp_path, monkeypatch):
    script = [("", [_edit("a", "    return p + 1\n", "    if p < 0:\n        raise ValeuError('x')\n    return p + 1\n")]),
              ("selesai", []),
              ("diperbaiki", [_edit("b", "ValeuError", "ValueError")]),
              ("selesai 2", [])]
    final, seen, rec = await _gate_run(home, tmp_path, monkeypatch,
                                       {"harness_mode": "tempest", "tempest_lint_gate": True}, script, BASE)
    assert final == "selesai 2"
    lint_msgs = [m for m in rec["messages"] if m.get("kind") == "lint"]
    assert len(lint_msgs) == 1 and "ValeuError" in lint_msgs[0]["content"]
    assert "render_table" not in lint_msgs[0]["content"]  # pre-existing diagnostic is not ours


async def test_agent_lint_gate_gives_up_after_retries_with_note(home, tmp_path, monkeypatch):
    script = [("", [_edit("a", "    return p + 1\n", "    return p + bonus\n")]), ("selesai", []), ("tetap", [])]
    final, seen, rec = await _gate_run(home, tmp_path, monkeypatch,
                                       {"harness_mode": "tempest", "tempest_lint_gate": True}, script, BASE)
    assert final.startswith("tetap") and "Masih ada diagnostik statis baru" in final and "bonus" in final
    assert len([m for m in rec["messages"] if m.get("kind") == "lint"]) == 1


async def test_agent_lint_gate_off_and_clean_edit(home, tmp_path, monkeypatch):
    script = [("", [_edit("a", "    return p + 1\n", "    return p + bonus\n")]), ("selesai", [])]
    final, _, rec = await _gate_run(home, tmp_path, monkeypatch, {"harness_mode": "tempest", "tempest_lint_gate": False},
                                    script, BASE)
    assert final == "selesai" and not [m for m in rec["messages"] if m.get("kind") == "lint"]
    script = [("", [_edit("a", "    return p + 1\n", "    return p + 2\n")]), ("selesai", [])]
    final, _, rec = await _gate_run(home, tmp_path, monkeypatch,
                                    {"harness_mode": "tempest", "tempest_lint_gate": True}, script, BASE)
    assert final == "selesai" and not [m for m in rec["messages"] if m.get("kind") == "lint"]
