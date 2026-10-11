"""PowerPoint via PPT Master: Python 3.10+ detection, on-demand install (mocked
download + pip), tool registration/routing and export. No network, no real pip,
no model calls."""

import asyncio
import hashlib
import io
import subprocess
import zipfile
from pathlib import Path

import pytest

from neovarch import pptmaster as ppt
from neovarch.tools import TOOLS, ToolContext, list_skills, run_tool, tool_schemas


def _cp(cmd, code=0, out="", err=""):
    return subprocess.CompletedProcess(cmd, code, out, err)


def _fake_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt-master/", "")
        z.writestr("ppt-master/skills/ppt-master/SKILL.md",
                   '---\nname: ppt-master\ndescription: >\n  AI-driven presentation workflow\n  for PPTX decks.\n'
                   f'metadata:\n  version: "{ppt.PPT_MASTER_VERSION}"\n---\n# PPT Master Skill\n')
        z.writestr("ppt-master/skills/ppt-master/LICENSE", "MIT License\n\nCopyright (c) 2025-2026 Hugo He\n")
        z.writestr("ppt-master/skills/ppt-master/scripts/svg_to_pptx.py", "print('x')\n")
        z.writestr("ppt-master/skills/ppt-master/scripts/attribution_guard.py", "")
        z.writestr("ppt-master/projects/example.pptx", "not part of the skill")
    return buf.getvalue()


class FakeRun:
    """Records argv; pretends to be python/venv/pip/exporter."""

    def __init__(self, version="3.12.1", has=(), export_writes=None):
        self.calls, self.version, self.has, self.export_writes = [], version, set(has), export_writes

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        joined = " ".join(map(str, cmd))
        if "sys.version_info" in joined:
            return _cp(cmd, 0, self.version + "\n")
        if "-m venv" in joined:
            py = ppt.venv_python(Path(cmd[-1]))
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
            return _cp(cmd)
        if cmd[1:2] == ["-c"] and str(cmd[2]).startswith("import "):
            return _cp(cmd, 0 if cmd[2].split()[1] in self.has else 1)
        if "pip install" in joined:
            self.has |= {"pptx", "pathops"} | ({"fitz"} if any("PyMuPDF" in c for c in cmd) else set())
            return _cp(cmd)
        if "attribution_guard.py" in joined:
            return _cp(cmd)
        if "svg_to_pptx.py" in joined:
            if self.export_writes:
                self.export_writes.parent.mkdir(parents=True, exist_ok=True)
                self.export_writes.write_bytes(b"PK\x03\x04pptx")
            return _cp(cmd, 0, "exported")
        return _cp(cmd, 1, "", "unexpected")


def _download(data):
    return lambda url: data


def test_find_python_requires_310():
    run = FakeRun(version="3.9.7")
    with pytest.raises(ppt.PptError) as e:
        ppt.find_python(run, candidates=[["python3"]])
    msg = str(e.value)
    assert "Python 3.10" in msg and "python.org" in msg and "3.9.7" in msg
    assert "tidak ditemukan" in msg and "not found" in msg          # bilingual
    argv, ver = ppt.find_python(FakeRun(version="3.11.4"), candidates=[["python3"]])
    assert argv == ["python3"] and ver == "3.11.4"


def test_find_python_nothing_installed():
    def boom(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    with pytest.raises(ppt.PptError, match="Python 3.10"):
        ppt.find_python(boom, candidates=[["python3"], ["python"]])


def test_install_skill_unpacks_only_the_skill_and_checks_sha(home):
    data = _fake_zip()
    with pytest.raises(ppt.PptError, match="checksum"):
        ppt.install_skill(_download(data))
    d = ppt.install_skill(_download(data), sha256=hashlib.sha256(data).hexdigest())
    assert d == home / "skills" / "ppt-master"
    assert (d / "SKILL.md").is_file() and (d / "LICENSE").is_file() and (d / "scripts" / "svg_to_pptx.py").is_file()
    assert not list(d.rglob("*.pptx"))                               # no example decks
    assert ppt.installed_version() == ppt.PPT_MASTER_VERSION
    skills = {s["name"]: s for s in list_skills()}
    assert "AI-driven presentation workflow" in skills["ppt-master"]["description"]


def test_install_skill_rejects_path_traversal(home):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt-master/skills/ppt-master/../../../evil.txt", "x")
    data = buf.getvalue()
    with pytest.raises(ppt.PptError, match="unsafe"):
        ppt.install_skill(_download(data), sha256=hashlib.sha256(data).hexdigest())


def test_setup_installs_core_deps_without_pymupdf(home, monkeypatch):
    data = _fake_zip()
    monkeypatch.setattr(ppt, "PPT_MASTER_SHA256", hashlib.sha256(data).hexdigest())
    run = FakeRun()
    res = ppt.setup(download=_download(data), run=run)
    pip = [c for c in run.calls if "pip" in c and "install" in c]
    assert len(pip) == 1 and any(a.startswith("python-pptx") for a in pip[0])
    assert not any("PyMuPDF" in a for a in pip[0])                  # AGPL dep only on request
    assert res["python"] == str(ppt.venv_python()) and res["pdf_input"] is False
    assert Path(res["presentations_dir"]).is_dir()
    run2 = FakeRun(has={"pptx", "pathops"})
    ppt.setup(pdf=True, download=_download(data), run=run2)
    pip2 = [c for c in run2.calls if "pip" in c and "install" in c]
    assert len(pip2) == 1 and pip2[0][-1].startswith("PyMuPDF")


def test_setup_fails_clearly_without_python(home):
    with pytest.raises(ppt.PptError, match="Python 3.10"):
        ppt.setup(download=lambda url: pytest.fail("must not download without Python"),
                  run=FakeRun(version="3.8.10"))


def test_export_runs_skill_exporter_with_venv_python(home, tmp_path):
    proj = tmp_path / "deck_ppt169"
    (proj / "svg_output").mkdir(parents=True)
    with pytest.raises(ppt.PptError, match="ppt_setup"):
        ppt.export(str(proj), run=FakeRun())
    data = _fake_zip()
    ppt.install_skill(_download(data), sha256=hashlib.sha256(data).hexdigest())
    ppt.venv_python().parent.mkdir(parents=True, exist_ok=True)
    ppt.venv_python().write_text("")
    run = FakeRun(export_writes=proj / "exports" / "deck.pptx")
    res = ppt.export(str(proj), run=run)
    assert res["files"] == [str(proj / "exports" / "deck.pptx")]
    cmd = [c for c in run.calls if any("svg_to_pptx.py" in str(a) for a in c)][0]
    assert cmd[0] == str(ppt.venv_python()) and "--quick-generate" in cmd and "--with-notes" in cmd
    with pytest.raises(ppt.PptError, match="tidak ditemukan"):
        ppt.export(str(tmp_path / "nope"), run=run)


def test_tools_registered_and_listed_for_main_agent(home):
    assert "ppt_setup" in TOOLS and "ppt_export" in TOOLS
    names = {t["function"]["name"] for t in tool_schemas(ToolContext(cwd=Path("."), approve=None))}
    assert {"ppt_setup", "ppt_export", "report_export"} <= names
    skills = {s["name"] for s in list_skills()}
    assert "ppt" in skills                                           # built-in guide, /ppt on desktop + phone
    text = (home / "skills" / "ppt" / "SKILL.md").read_text(encoding="utf-8")
    assert "ppt_setup" in text and "ppt_export" in text and "hugohe3/ppt-master" in text
    assert "hermes" not in text.lower()


async def test_tool_routing_setup_and_export(home, monkeypatch, tmp_path):
    ctx = ToolContext(cwd=tmp_path, approve=lambda *a: asyncio.sleep(0, "allow"))
    monkeypatch.setattr(ppt, "setup", lambda **kw: (_ for _ in ()).throw(ppt.PptError(ppt.NO_PYTHON)))
    out = await run_tool("ppt_setup", {}, ctx)
    assert out.startswith("error:") and "Python 3.10" in out
    seen = {}

    def fake_setup(**kw):
        seen.update(kw)
        return {"skill_dir": "/h/skills/ppt-master", "python": "/h/venv/bin/python", "system_python": "3.12.1",
                "presentations_dir": "/h/presentations", "pdf_input": True, "version": ppt.PPT_MASTER_VERSION}
    monkeypatch.setattr(ppt, "setup", fake_setup)
    out = await run_tool("ppt_setup", {"pdf": True}, ctx)
    assert seen["pdf"] is True and "SKILL_DIR=/h/skills/ppt-master" in out and "PYTHON=/h/venv/bin/python" in out
    monkeypatch.setattr(ppt, "export", lambda p, **kw: {"files": [f"{p}/exports/deck.pptx"], "log": ""})
    out = await run_tool("ppt_export", {"project_path": "/h/presentations/deck"}, ctx)
    assert "pptx: /h/presentations/deck/exports/deck.pptx" in out


async def test_skill_tool_tells_skill_dir(home, tmp_path):
    ctx = ToolContext(cwd=tmp_path, approve=lambda *a: asyncio.sleep(0, "allow"))
    out = await run_tool("skill", {"name": "ppt"}, ctx)
    assert out.startswith(f"SKILL_DIR: {home / 'skills' / 'ppt'}")


def test_system_prompt_mentions_ppt_route():
    from neovarch.agent import APP_KNOWLEDGE
    assert "ppt_setup" in APP_KNOWLEDGE and "phone" in APP_KNOWLEDGE
