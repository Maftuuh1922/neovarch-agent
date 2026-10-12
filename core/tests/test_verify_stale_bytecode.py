"""The Tempest verify gate must test the code on disk, never a stale __pycache__.

Root cause behind the flaky test_agent_auto_skill_and_failed_skill_repair_hint:
an edit made within the same second that keeps the file size leaves the old
.pyc looking valid (mtime in whole seconds + size match), so the gate ran the
old code and passed a broken change. This reproduces it deterministically.
"""
from __future__ import annotations

import os
import subprocess
import sys

from neovarch import tempest


def _project(tmp_path, ret: int, expect: int):
    (tmp_path / "m.py").write_text(f"def f():\n    return {ret}\n")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_m.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
        f"from m import f\n\ndef test_f():\n    assert f() == {expect}\n")


def test_verify_ignores_stale_bytecode_from_same_second_same_size_edit(tmp_path):
    _project(tmp_path, ret=2, expect=2)
    stamp = (1_700_000_000, 1_700_000_000)
    for p in (tmp_path / "m.py", tmp_path / "tests" / "test_m.py"):
        os.utime(p, stamp)
    # an earlier plain `pytest` run (e.g. the agent's shell tool) leaves bytecode behind
    first = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert first.returncode == 0, first.stdout + first.stderr
    assert list(tmp_path.rglob("__pycache__/*.pyc"))

    # same-size edits within the "same second": the old pycs still look valid
    _project(tmp_path, ret=4, expect=3)
    for p in (tmp_path / "m.py", tmp_path / "tests" / "test_m.py"):
        os.utime(p, stamp)

    cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    ok, out = tempest.run_verify(cmd, tmp_path, timeout=120)
    assert not ok, out
    assert "assert 4 == 3" in out or "AssertionError" in out
