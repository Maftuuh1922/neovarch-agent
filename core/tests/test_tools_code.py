"""Coding tools upgrade: forgiving edit_file, grep/glob (ripgrep + Python fallback), background shell jobs."""

import asyncio
import os
import sys

import pytest

from neovarch import tempest_diet, tools_code
from neovarch.tools import READ_ONLY_TOOLS, ToolContext, run_tool, tool_schemas


async def _approve(*_a):
    return "once"


def _ctx(tmp_path):
    return ToolContext(cwd=tmp_path, approve=_approve, approvals_mode="off")


SRC = "class A:\n    def f(self):\n        x = 1\n        return x\n\n    def g(self):\n        return 2\n"


# ------------------------------------------------------------------ edit -----

async def test_edit_exact_returns_snippet(home, tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "return 2", "new_text": "return 3"}, _ctx(tmp_path))
    assert out.startswith("edited") and "(1 replacement(s))" in out
    assert "return 3" in out and "\t" in out  # numbered lines around the change
    assert "return 3" in (tmp_path / "a.py").read_text()


async def test_edit_tolerates_indentation_and_reindents(home, tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "x = 1\nreturn x",
                                       "new_text": "x = 2\nreturn x * 10"}, _ctx(tmp_path))
    assert out.startswith("edited") and "ignoring indentation" in out
    assert "        x = 2\n        return x * 10\n" in (tmp_path / "a.py").read_text()


async def test_edit_tolerates_trailing_whitespace_and_smart_quotes(home, tmp_path):
    (tmp_path / "a.py").write_text("msg = 'hi'   \nprint(msg)\n")
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "msg = \u2018hi\u2019\nprint(msg)",
                                       "new_text": "msg = 'yo'\nprint(msg)"}, _ctx(tmp_path))
    assert "ignoring trailing whitespace" in out
    assert (tmp_path / "a.py").read_text() == "msg = 'yo'\nprint(msg)\n"


async def test_edit_not_found_shows_closest_region(home, tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "def g(self):\n    return 22",
                                       "new_text": "x"}, _ctx(tmp_path))
    assert out.startswith("error: old_text was not found")
    assert "Closest match (lines 6-7" in out and "def g(self)" in out
    assert (tmp_path / "a.py").read_text() == SRC


async def test_edit_non_unique_names_lines(home, tmp_path):
    (tmp_path / "a.py").write_text("a = 1\nb = 2\na = 1\n")
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "a = 1", "new_text": "a = 3"}, _ctx(tmp_path))
    assert "occurs 2 times (lines 1, 3)" in out
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "a = 1", "new_text": "a = 3", "replace_all": True},
                         _ctx(tmp_path))
    assert "(2 replacement(s))" in out and (tmp_path / "a.py").read_text() == "a = 3\nb = 2\na = 3\n"


async def test_fuzzy_match_must_be_unique(home, tmp_path):
    (tmp_path / "a.py").write_text("if x:\n    y()\nif x:\n        y()\n")
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "if x:\n  y()", "new_text": "z()"}, _ctx(tmp_path))
    assert "matches 2 places when ignoring indentation (lines 1, 3)" in out


async def test_multi_edit_is_all_or_nothing(home, tmp_path):
    (tmp_path / "a.py").write_text(SRC)
    ctx = _ctx(tmp_path)
    bad = await run_tool("edit_file", {"path": "a.py", "edits": [
        {"old_text": "x = 1", "new_text": "x = 5"}, {"old_text": "nope", "new_text": "y"}]}, ctx)
    assert bad.startswith("error: edit 2 of 2") and (tmp_path / "a.py").read_text() == SRC
    ok = await run_tool("edit_file", {"path": "a.py", "edits": [
        {"old_text": "x = 1", "new_text": "x = 5"}, {"old_text": "return 2", "new_text": "return 7"}]}, ctx)
    assert ok.startswith("edited") and "(2 replacement(s))" in ok
    assert "x = 5" in (tmp_path / "a.py").read_text() and "return 7" in (tmp_path / "a.py").read_text()


async def test_edit_keeps_crlf_and_aliases(home, tmp_path):
    (tmp_path / "w.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
    out = await run_tool("edit_file", {"path": "w.txt", "old_string": "one\ntwo", "new_string": "1\n2"}, _ctx(tmp_path))
    assert out.startswith("edited")
    assert (tmp_path / "w.txt").read_bytes() == b"1\r\n2\r\nthree\r\n"


async def test_edit_errors(home, tmp_path):
    ctx = _ctx(tmp_path)
    assert "write_file" in await run_tool("edit_file", {"path": "missing.py", "old_text": "a", "new_text": "b"}, ctx)
    (tmp_path / "a.py").write_text("a\n")
    assert "identical" in await run_tool("edit_file", {"path": "a.py", "old_text": "a", "new_text": "a"}, ctx)
    assert "old_text is required" in await run_tool("edit_file", {"path": "a.py", "new_text": "b"}, ctx)
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00bad")
    assert "not UTF-8" in await run_tool("edit_file", {"path": "bin.dat", "old_text": "a", "new_text": "b"}, ctx)


async def test_edit_deleting_lines(home, tmp_path):
    (tmp_path / "a.py").write_text("a = 1\n  b = 2  \nc = 3\n")
    out = await run_tool("edit_file", {"path": "a.py", "old_text": "b = 2\n", "new_text": ""}, _ctx(tmp_path))
    assert out.startswith("edited") and (tmp_path / "a.py").read_text() == "a = 1\nc = 3\n"


# ------------------------------------------------------------- read_file -----

async def test_read_file_binary_and_long_lines(home, tmp_path):
    ctx = _ctx(tmp_path)
    (tmp_path / "x.bin").write_bytes(b"\x00\x01\x02")
    assert "binary file" in await run_tool("read_file", {"path": "x.bin"}, ctx)
    (tmp_path / "min.js").write_text("a" * 5000 + "\nok\n")
    out = await run_tool("read_file", {"path": "min.js"}, ctx)
    assert "[+3000 chars]" in out and "ok" in out
    assert "past the end" in await run_tool("read_file", {"path": "min.js", "offset": 50}, ctx)


# ------------------------------------------------------------- grep/glob -----

def _tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    return helper()\n\ndef helper():\n    return 1\n")
    (tmp_path / "src" / "util.ts").write_text("export const helper = 1;\n")
    (tmp_path / "README.md").write_text("Helper docs\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.py").write_text("def helper(): pass\n")


@pytest.fixture(params=["rg", "python"])
def engine(request, monkeypatch):
    if request.param == "rg" and not tools_code.shutil.which("rg"):
        pytest.skip("ripgrep not installed")
    if request.param == "python":
        monkeypatch.setenv("NEOVARCH_NO_RG", "1")
    else:
        monkeypatch.delenv("NEOVARCH_NO_RG", raising=False)
    return request.param


async def test_grep_content_files_count(home, tmp_path, engine):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    ctx = _ctx(tmp_path)
    out = await run_tool("grep", {"pattern": r"def helper"}, ctx)
    assert "src/app.py:4:def helper():" in out and "node_modules" not in out
    out = await run_tool("grep", {"pattern": "helper", "output": "files", "glob": "*.py"}, ctx)
    assert out.strip() == "src/app.py"
    out = await run_tool("grep", {"pattern": "helper", "ignore_case": True, "output": "count"}, ctx)
    assert "README.md:1" in out and "src/app.py:2" in out
    assert "no matches" in await run_tool("grep", {"pattern": "zzz_nothing"}, ctx)
    out = await run_tool("grep", {"pattern": "helper", "path": "src", "output": "files"}, ctx)
    assert sorted(out.split()) == ["src/app.py", "src/util.ts"]


async def test_skip_dirs_without_gitignore(home, tmp_path, engine):
    _tree(tmp_path)  # no .gitignore, not a git repo: node_modules still skipped, also with a glob
    ctx = _ctx(tmp_path)
    assert "node_modules" not in await run_tool("grep", {"pattern": "helper", "glob": "*.py"}, ctx)
    assert "node_modules" not in await run_tool("glob", {"pattern": "*.py"}, ctx)


async def test_grep_single_file_outside_cwd(home, tmp_path, engine):
    big = home / "obs" / "call1.txt"  # where Tempest offloads big tool output
    big.parent.mkdir(parents=True)
    big.write_text("noise\n" * 50 + "ERROR: boom\n")
    (tmp_path / "proj").mkdir()
    out = await run_tool("grep", {"pattern": "ERROR", "path": str(big)}, _ctx(tmp_path / "proj"))
    assert "51:ERROR: boom" in out


async def test_grep_caps_and_bad_regex(home, tmp_path, engine):
    (tmp_path / "big.txt").write_text("hit\n" * 300)
    ctx = _ctx(tmp_path)
    out = await run_tool("grep", {"pattern": "hit", "limit": 10}, ctx)
    assert len(out.splitlines()) == 11 and "290 more" in out
    assert "invalid regex" in await run_tool("grep", {"pattern": "(unclosed"}, ctx)


async def test_glob_newest_first(home, tmp_path, engine):
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    os.utime(tmp_path / "src" / "app.py", (1, 1))
    ctx = _ctx(tmp_path)
    out = await run_tool("glob", {"pattern": "**/*.py"}, ctx)
    assert out.splitlines() == ["src/app.py"]
    out = await run_tool("glob", {"pattern": "*.{md,ts}"}, ctx)
    assert set(out.splitlines()) == {"README.md", "src/util.ts"}
    assert "no files match" in await run_tool("glob", {"pattern": "*.rs"}, ctx)


# ---------------------------------------------------------------- shell -----

@pytest.mark.skipif(sys.platform == "win32", reason="posix shell")
async def test_shell_timeout_keeps_partial_output(home, tmp_path):
    out = await run_tool("shell", {"command": "echo started; sleep 5", "timeout": 1}, _ctx(tmp_path))
    assert out.startswith("error: timed out after 1s") and "started" in out and "background=true" in out


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell")
async def test_background_job_lifecycle(home, tmp_path):
    ctx = _ctx(tmp_path)
    out = await run_tool("shell", {"command": "echo one; sleep 0.5; echo two", "background": True}, ctx)
    assert out.startswith("started background job ")
    jid = out.split()[3]
    waited = await run_tool("shell_job", {"action": "wait", "id": jid, "timeout": 10}, ctx)
    assert "exited 0" in waited and "two" in waited
    assert "(no new output)" in await run_tool("shell_job", {"action": "output", "id": jid}, ctx)
    assert jid in await run_tool("shell_job", {"action": "list"}, ctx)
    out = await run_tool("shell", {"command": "sleep 30", "background": True}, ctx)
    jid2 = out.split()[3]
    killed = await run_tool("shell_job", {"action": "kill", "id": jid2}, ctx)
    assert "exited" in killed
    assert "no background job" in await run_tool("shell_job", {"action": "output", "id": "nope"}, ctx)


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell")
async def test_background_still_asks_for_dangerous_commands(home, tmp_path):
    asked = []

    async def deny(cmd, reason, kind):
        asked.append(cmd)
        return "deny"
    ctx = ToolContext(cwd=tmp_path, approve=deny)
    out = await run_tool("shell", {"command": "rm -rf build", "background": True}, ctx)
    assert out.startswith("denied") and asked == ["rm -rf build"]


# ------------------------------------------------------------ wiring -----

def test_schemas_registered_and_cache_stable():
    names = [t["function"]["name"] for t in tool_schemas()]
    for n in ("grep", "glob", "shell_job", "edit_file"):
        assert n in names
    assert {"grep", "glob"} <= READ_ONLY_TOOLS and "shell_job" not in READ_ONLY_TOOLS
    assert {"grep", "glob"} <= set(tempest_diet.CORE_TOOLS) and "shell_job" not in tempest_diet.CORE_TOOLS
    assert "shell_job" in tempest_diet.ONE_LINERS
    edit = next(t for t in tool_schemas() if t["function"]["name"] == "edit_file")["function"]["parameters"]
    assert edit["required"] == ["path"] and "edits" in edit["properties"]
    # Same schemas twice -> byte-identical (prompt cache).
    assert tool_schemas() == tool_schemas()


def test_glob_regex_semantics():
    rx = tools_code.glob_regex
    assert rx("*.py").match("a/b/c.py") and rx("*.py").match("c.py")
    assert rx("src/**/*.ts").match("src/y.ts") and rx("src/**/*.ts").match("src/a/b/y.ts")
    assert not rx("src/*.ts").match("src/a/y.ts")
    assert rx("*.{py,md}").match("x.md") and not rx("*.{py,md}").match("x.ts")


def test_output_buffer_bounds_memory():
    buf = tools_code.OutputBuffer(head=10, tail=10)
    for _ in range(100):
        buf.add(b"0123456789")
    data = buf.bytes()
    assert data.startswith(b"0123456789") and b"omitted" in data and len(data) < 80


@pytest.fixture(autouse=True)
def _cleanup_jobs():
    yield
    for job in list(tools_code.JOBS.values()):
        if job.proc.returncode is None:
            try:
                os.killpg(job.proc.pid, 9)
            except Exception:
                pass
    tools_code.JOBS.clear()


def test_asyncio_mode_is_auto():
    # The async tests above rely on pytest-asyncio auto mode (pyproject); guard against silent skips.
    assert asyncio.iscoroutinefunction(test_edit_exact_returns_snippet)
