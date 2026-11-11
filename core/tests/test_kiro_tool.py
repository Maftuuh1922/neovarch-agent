"""kiro tool: Kiro CLI proposes a diff in a temp worktree; apply needs approval."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from neovarch import kiro_tool
from neovarch.paths import neovarch_home
from neovarch.tools import READ_ONLY_TOOLS, TOOLS, ToolContext

FAKE_KIRO = """#!/bin/sh
# Fake kiro-cli for tests: logs argv + prompt, then edits files in cwd.
# FAKE_KIRO_MODE: edit (default) | noop | fail. FAKE_KIRO_LOG: dir for logs.
logdir="${FAKE_KIRO_LOG:-/tmp}"
printf '%s\\n' "$@" > "$logdir/argv.txt"
prompt=""
for a in "$@"; do prompt="$a"; done
printf '%s' "$prompt" > "$logdir/prompt.txt"
mode="${FAKE_KIRO_MODE:-edit}"
if [ "$mode" = "fail" ]; then
  echo "boom: fake kiro failed" >&2
  exit 1
fi
if [ "$mode" = "noop" ]; then
  echo "nothing to do"
  exit 0
fi
if [ -f target.txt ]; then
  printf '# edited by fake kiro\\n' >> target.txt
else
  printf 'created by fake kiro\\n' > newfile.txt
fi
echo "fake kiro finished"
"""


async def _allow(command, description, tool):
    return "allow"


async def _deny(command, description, tool):
    return "deny"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.email", "test@neovarch.local"], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.name", "Test"], check=True)
    (r / "target.txt").write_text("line one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "init"], check=True)
    return r


@pytest.fixture
def fake_kiro(tmp_path, monkeypatch):
    script = tmp_path / "fake-kiro"
    script.write_text(FAKE_KIRO, encoding="utf-8")
    script.chmod(0o755)
    logdir = tmp_path / "kirolog"
    logdir.mkdir()
    monkeypatch.setenv("KIRO_BIN", str(script))
    monkeypatch.setenv("FAKE_KIRO_LOG", str(logdir))
    monkeypatch.delenv("KIRO_COMMAND", raising=False)
    monkeypatch.delenv("FAKE_KIRO_MODE", raising=False)
    return script, logdir


def _ctx(repo, approve=_allow):
    return ToolContext(cwd=repo, approve=approve)


def _proposals(home) -> list[Path]:
    d = neovarch_home() / "kiro-proposals"
    return sorted(d.iterdir()) if d.exists() else []


def _proposal_id(result: str) -> str:
    for token in result.replace("(", " ").replace(")", " ").split():
        if token.startswith("kp") and len(token) == 10:
            return token
    raise AssertionError(f"no proposal id in result:\n{result}")


# ------------------------------------------------------------------ registry --
def test_kiro_registered_and_not_read_only():
    assert "kiro" in TOOLS
    assert "kiro" not in READ_ONLY_TOOLS  # it changes files: must go through approval
    schema = TOOLS["kiro"][1]
    props = schema["parameters"]["properties"]
    assert props["action"]["enum"] == ["propose", "apply", "discard", "list_specs"]
    assert schema["parameters"]["required"] == ["action"]
    assert "task" in props and "proposal_id" in props and "timeout" in props


def test_build_command_default_and_template(monkeypatch):
    monkeypatch.delenv("KIRO_COMMAND", raising=False)
    assert kiro_tool.build_command("kiro-cli", "do X") == [
        "kiro-cli", "chat", "--v3", "--no-interactive", "--trust-all-tools", "do X"]
    monkeypatch.setenv("KIRO_COMMAND", "kiro-cli chat --no-interactive {prompt}")
    assert kiro_tool.build_command("kiro-cli", "do X") == ["kiro-cli", "chat", "--no-interactive", "do X"]
    monkeypatch.setenv("KIRO_COMMAND", "kiro-cli chat --no-interactive")
    assert kiro_tool.build_command("kiro-cli", "do X") == ["kiro-cli", "chat", "--no-interactive", "do X"]


# ------------------------------------------------------------------- propose --
@pytest.mark.asyncio
async def test_propose_captures_diff_and_leaves_repo_untouched(home, repo, fake_kiro):
    _, logdir = fake_kiro
    (repo / ".kiro" / "steering").mkdir(parents=True)
    (repo / ".kiro" / "steering" / "product.md").write_text(
        "# Product\nMARKER-STEERING-123\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "steering"], check=True)

    result = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment to target.txt", "paths": ["target.txt"]},
        _ctx(repo))
    pid = _proposal_id(result)
    assert "Diff (dipotong)" in result
    assert "# edited by fake kiro" in result
    # The real repo is untouched: still one line, no worktree left behind.
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"
    assert _git(repo, "worktree", "list").count("\n") == 0
    # The patch + metadata are stored.
    patch = neovarch_home() / "kiro-proposals" / f"{pid}.patch"
    meta = json.loads((neovarch_home() / "kiro-proposals" / f"{pid}.json").read_text(encoding="utf-8"))
    assert "# edited by fake kiro" in patch.read_text(encoding="utf-8")
    assert meta["repo"] == str(repo) and meta["files"] == ["target.txt"]
    # The steering file reached Kiro as prompt context, with the target file named.
    prompt = (logdir / "prompt.txt").read_text(encoding="utf-8")
    assert "MARKER-STEERING-123" in prompt
    assert "target.txt" in prompt
    assert "Do NOT commit" in prompt


@pytest.mark.asyncio
async def test_propose_no_changes(home, repo, fake_kiro, monkeypatch):
    monkeypatch.setenv("FAKE_KIRO_MODE", "noop")
    result = await kiro_tool.tool_kiro({"action": "propose", "task": "Do nothing"}, _ctx(repo))
    assert "tanpa mengusulkan perubahan" in result
    assert _proposals(home) == []
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"


@pytest.mark.asyncio
async def test_propose_cli_failure(home, repo, fake_kiro, monkeypatch):
    monkeypatch.setenv("FAKE_KIRO_MODE", "fail")
    result = await kiro_tool.tool_kiro({"action": "propose", "task": "Break things"}, _ctx(repo))
    assert "Kiro CLI gagal (exit 1)" in result
    assert "Repo asli tidak diubah" in result
    assert _proposals(home) == []
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"


@pytest.mark.asyncio
async def test_propose_denied_at_gate(home, repo, fake_kiro):
    result = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment"}, _ctx(repo, _deny))
    assert result.startswith("denied:")
    assert _proposals(home) == []
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"


@pytest.mark.asyncio
async def test_propose_missing_cli(home, repo, monkeypatch):
    monkeypatch.setattr(kiro_tool, "resolve_binary", lambda: None)
    result = await kiro_tool.tool_kiro({"action": "propose", "task": "Do X"}, _ctx(repo))
    assert "Kiro CLI tidak ditemukan" in result
    assert "KIRO_API_KEY" in result
    assert _proposals(home) == []


@pytest.mark.asyncio
async def test_propose_rejects_non_git_dir(home, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Do X", "cwd": str(plain)}, _ctx(plain))
    assert "bukan repo git" in result


@pytest.mark.asyncio
async def test_propose_rejects_paths_outside_repo(home, repo, fake_kiro):
    result = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Do X", "paths": ["../outside.txt"]}, _ctx(repo))
    assert "di luar repo" in result
    assert _proposals(home) == []


# ------------------------------------------------------------- apply/discard --
@pytest.mark.asyncio
async def test_apply_applies_patch_and_cleans_up(home, repo, fake_kiro):
    res = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment", "paths": ["target.txt"]}, _ctx(repo))
    pid = _proposal_id(res)
    out = await kiro_tool.tool_kiro({"action": "apply", "proposal_id": pid}, _ctx(repo))
    assert out.startswith("Diterapkan:")
    assert "target.txt" in out
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n# edited by fake kiro\n"
    assert _proposals(home) == []


@pytest.mark.asyncio
async def test_apply_denied_discards_proposal(home, repo, fake_kiro):
    res = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment", "paths": ["target.txt"]}, _ctx(repo))
    pid = _proposal_id(res)
    out = await kiro_tool.tool_kiro({"action": "apply", "proposal_id": pid}, _ctx(repo, _deny))
    assert "ditolak pengguna" in out and "dibuang" in out
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"
    assert _proposals(home) == []


@pytest.mark.asyncio
async def test_apply_unknown_proposal(home, repo):
    out = await kiro_tool.tool_kiro({"action": "apply", "proposal_id": "kpdeadbeef"}, _ctx(repo))
    assert "tidak ditemukan" in out


@pytest.mark.asyncio
async def test_apply_twice_fails_second_time(home, repo, fake_kiro):
    res = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment", "paths": ["target.txt"]}, _ctx(repo))
    pid = _proposal_id(res)
    await kiro_tool.tool_kiro({"action": "apply", "proposal_id": pid}, _ctx(repo))
    out = await kiro_tool.tool_kiro({"action": "apply", "proposal_id": pid}, _ctx(repo))
    assert "tidak ditemukan" in out


@pytest.mark.asyncio
async def test_discard_drops_proposal(home, repo, fake_kiro):
    res = await kiro_tool.tool_kiro(
        {"action": "propose", "task": "Append a comment", "paths": ["target.txt"]}, _ctx(repo))
    pid = _proposal_id(res)
    out = await kiro_tool.tool_kiro({"action": "discard", "proposal_id": pid}, _ctx(repo))
    assert "dibuang" in out
    assert (repo / "target.txt").read_text(encoding="utf-8") == "line one\n"
    assert _proposals(home) == []


# ----------------------------------------------------------------- list_specs --
@pytest.mark.asyncio
async def test_list_specs(home, repo):
    specs = repo / ".kiro" / "specs" / "my-feature"
    specs.mkdir(parents=True)
    (specs / "requirements.md").write_text("# req\n", encoding="utf-8")
    (specs / "tasks.md").write_text("# tasks\n", encoding="utf-8")
    out = await kiro_tool.tool_kiro({"action": "list_specs"}, _ctx(repo))
    assert "my-feature: requirements.md, tasks.md" in out


@pytest.mark.asyncio
async def test_list_specs_none(home, repo):
    out = await kiro_tool.tool_kiro({"action": "list_specs"}, _ctx(repo))
    assert "tidak ada .kiro/specs" in out


@pytest.mark.asyncio
async def test_unknown_action(home, repo):
    out = await kiro_tool.tool_kiro({"action": "explode"}, _ctx(repo))
    assert "action harus propose | apply | discard | list_specs" in out
