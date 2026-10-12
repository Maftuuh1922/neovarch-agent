"""Tempest shadow-git checkpoints: snapshots, restore, isolation from the user's git, rollback."""

import json
import subprocess

import pytest

from neovarch import tempest_ckpt as tc

pytestmark = pytest.mark.skipif(not tc.git_available(), reason="git not installed")


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=u", "-c", "user.email=u@x", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


def test_checkpoint_restore_and_user_git_untouched(tmp_path):
    work, home = tmp_path / "proj", tmp_path / "home"
    work.mkdir()
    (work / "a.py").write_text("A1\n")
    (work / "keep.txt").write_text("K\n")
    (work / "node_modules").mkdir()
    (work / "node_modules" / "big.js").write_text("x")
    _git(work, "init", "-q")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "user commit")
    user_log, user_status = _git(work, "log", "--oneline"), _git(work, "status", "--porcelain")

    repo = tc.ShadowRepo(work, home)
    assert repo.usable() == (True, "")
    base = repo.checkpoint("awal", "green")
    (work / "a.py").write_text("A2 broken\n")
    (work / "new.py").write_text("new\n")
    (work / "keep.txt").unlink()
    touched = repo.restore(base)
    assert sorted(touched) == ["a.py", "keep.txt", "new.py"]
    assert (work / "a.py").read_text() == "A1\n" and (work / "keep.txt").read_text() == "K\n"
    assert not (work / "new.py").exists() and (work / "node_modules" / "big.js").exists()
    # the user's repository saw nothing: same log, same clean status, no shadow files inside .git
    assert _git(work, "log", "--oneline") == user_log and _git(work, "status", "--porcelain") == user_status
    assert repo.dir.is_relative_to(home) and not (work / ".git" / "tempest-status.json").exists()
    files = repo.git("ls-tree", "-r", "--name-only", base).split()
    assert ".git" not in " ".join(files) and "node_modules/big.js" not in files
    assert repo.status(base) == "green" and repo.last_green() is not None


def test_usable_guards(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    for i in range(12):
        (work / f"f{i}.txt").write_text("x")
    assert tc.ShadowRepo(work, tmp_path / "h", max_files=10).usable()[0] is False
    assert tc.ShadowRepo(tmp_path / "missing", tmp_path / "h").usable()[0] is False


def test_big_files_stay_out_and_huge_projects_skip(tmp_path, monkeypatch):
    """Tempest runs by default (1.4.7): a snapshot never copies a video/dataset into ~/.neovarch,
    hidden dirs count like git sees them, and an oversized folder just runs without checkpoints."""
    monkeypatch.setattr(tc, "MAX_FILE_BYTES", 1000)
    work, home = tmp_path / "p", tmp_path / "h"
    work.mkdir()
    (work / "code.py").write_text("x = 1\n")
    (work / "data [v1]*.bin").write_bytes(b"0" * 5000)
    (work / ".cache").mkdir()
    for i in range(8):
        (work / ".cache" / f"c{i}").write_text("c")
    repo = tc.ShadowRepo(work, home)
    assert repo.usable() == (True, "")
    sha = repo.checkpoint("awal")
    files = repo.git("ls-tree", "-r", "--name-only", sha).splitlines()
    assert "code.py" in files and "data [v1]*.bin" not in files and ".cache/c0" in files
    (work / "code.py").write_text("x = 2\n")
    repo.restore(sha)
    assert (work / "code.py").read_text() == "x = 1\n" and (work / "data [v1]*.bin").exists()
    assert tc.ShadowRepo(work, home, max_files=5).usable()[0] is False  # .cache counts
    monkeypatch.setattr(tc, "MAX_TOTAL_BYTES", 10)
    ok, why = tc.ShadowRepo(work, home).usable()
    assert ok is False and "MB" in why


def test_rewind_last_green(tmp_path):
    work, home = tmp_path / "p", tmp_path / "h"
    work.mkdir()
    (work / "m.py").write_text("good\n")
    repo = tc.ShadowRepo(work, home)
    repo.checkpoint("ok", "green")
    (work / "m.py").write_text("bad\n")
    repo.checkpoint("bad", "red")
    assert "dipulihkan" in tc.rewind(work, home)
    assert (work / "m.py").read_text() == "good\n"
    with pytest.raises(tc.CheckpointError):
        tc.rewind(tmp_path / "other", home)


async def _run(home, tmp_path, monkeypatch, script, test_src, src, agent_cfg=None):
    import neovarch.agent as agentmod
    from neovarch import config as cfgmod
    from neovarch.agent import Agent
    from neovarch.llm import Completion
    from neovarch.store import SessionStore
    from neovarch.tools import ToolContext

    cfg = cfgmod.load_config()
    cfg["model"] = {"provider": "custom", "default": "m", "base_url": "http://127.0.0.1:9/v1"}
    cfg["approvals"] = {"mode": "off"}
    cfg.setdefault("agent", {}).update(agent_cfg or {"harness_mode": "tempest", "tempest_checkpoints": True})
    cfgmod.save_config(cfg)
    monkeypatch.setenv("NEOVARCH_API_KEY", "x")
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "m.py").write_text(src)
    (proj / "tests" / "test_m.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n" + test_src)

    async def fake(*, messages, **_kw):
        text, calls = script.pop(0)
        return Completion(text=text, tool_calls=calls)
    monkeypatch.setattr(agentmod, "stream_chat", fake)
    events = []
    store = SessionStore()
    rec = store.create(cwd=str(proj))
    agent = Agent(rec, store, ToolContext(cwd=proj, approve=None), lambda k, p: events.append((k, p)))
    final = await agent.run_turn("ubah m.py")
    return final, proj, events


def _w(cid, content):
    from neovarch.llm import ToolCall
    return ToolCall(id=cid, name="write_file", arguments=json.dumps({"path": "m.py", "content": content}))


TEST_OK = "from m import f\n\ndef test_f():\n    assert f() == 1\n"


async def test_agent_rolls_back_to_green_when_verify_gives_up(home, tmp_path, monkeypatch):
    script = [("", [_w("a", "def f():\n    return 2\n")]), ("selesai", []),
              ("coba lagi", [_w("b", "def f():\n    return 3\n")]), ("selesai", []),
              ("coba lagi", [_w("c", "def f():\n    return 4\n")]), ("selesai", [])]
    final, proj, events = await _run(home, tmp_path, monkeypatch, script, TEST_OK, "def f():\n    return 1\n")
    assert "↩️ File dikembalikan" in final and (proj / "m.py").read_text() == "def f():\n    return 1\n"
    assert any(k == "status.update" and p.get("kind") == "rollback" for k, p in events)
    red = final.split("checkpoint ")[-1].split(";")[0]
    repo = tc.ShadowRepo(proj, home)
    assert repo.status(red) == "red" and "return 4" in repo.git("show", f"{red}:m.py")


async def test_agent_no_rollback_when_turn_start_was_red(home, tmp_path, monkeypatch):
    script = [("", [_w("a", "def f():\n    return 2\n")]), ("selesai", []),
              ("x", [_w("b", "def f():\n    return 3\n")]), ("selesai", []),
              ("x", [_w("c", "def f():\n    return 4\n")]), ("selesai", [])]
    final, proj, _ = await _run(home, tmp_path, monkeypatch, script, TEST_OK, "def f():\n    return 0\n")
    assert "↩️" not in final and (proj / "m.py").read_text() == "def f():\n    return 4\n"


async def test_agent_green_turn_is_tagged_and_kept(home, tmp_path, monkeypatch):
    script = [("", [_w("a", "def f():\n    return 1\n")]), ("selesai", [])]
    final, proj, _ = await _run(home, tmp_path, monkeypatch, script, TEST_OK, "def f():\n    return 0\n")
    assert final == "selesai" and (proj / "m.py").read_text() == "def f():\n    return 1\n"
    log = tc.ShadowRepo(proj, home).log()
    assert log[0]["status"] == "green" and len(log) == 2


async def test_checkpoints_can_be_turned_off(home, tmp_path, monkeypatch):
    script = [("", [_w("a", "def f():\n    return 1\n")]), ("selesai", [])]
    await _run(home, tmp_path, monkeypatch, script, TEST_OK, "def f():\n    return 0\n",
               {"harness_mode": "tempest", "tempest_checkpoints": False})
    assert not (home / "checkpoints").exists()


async def test_checkpoints_on_by_default_in_tempest(home, tmp_path, monkeypatch):
    script = [("", [_w("a", "def f():\n    return 1\n")]), ("selesai", [])]
    await _run(home, tmp_path, monkeypatch, script, TEST_OK, "def f():\n    return 0\n", {"harness_mode": "tempest"})
    assert (home / "checkpoints").exists()


def test_neovarch_home_inside_project_is_excluded(tmp_path):
    work = tmp_path / "p"
    home = work / "nvhome"
    (home / "sessions").mkdir(parents=True)
    (home / "sessions" / "s.json").write_text("{}")
    (work / "a.py").write_text("x = 1\n")
    repo = tc.ShadowRepo(work, home)
    sha = repo.checkpoint("awal")
    assert repo.git("ls-tree", "-r", "--name-only", sha).split() == ["a.py"]
