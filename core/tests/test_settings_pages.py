"""Settings › Obrolan › Perilaku and Ruang kerja › Proyek / Shell / File are not empty, and each field does something."""

from pathlib import Path

from neovarch import config as cfgmod
from neovarch.agent import default_cwd, now_text, system_prompt
from neovarch.server import config_schema_payload
from neovarch.tools import ToolContext, tool_read_file, tool_shell


async def _deny(*_a):
    return "deny"


def _set(**values):
    cfg = cfgmod.load_config()
    for k, v in values.items():
        cfgmod.set_path(cfg, k, v)
    cfgmod.save_config(cfg)


def test_schema_fills_behavior_projects_shell_and_files(home):
    fields = config_schema_payload()["fields"]
    # Perilaku
    for key in ("timezone", "display.show_reasoning", "agent.system_prompt"):
        assert key in fields, key
    # Proyek / Shell / File
    for key in ("terminal.cwd", "terminal.timeout", "file_read_max_chars"):
        assert fields[key]["category"] == "workspace", key
    cfg = cfgmod.load_config()
    assert cfgmod.get_path(cfg, "terminal.timeout") == 60 and cfgmod.get_path(cfg, "file_read_max_chars") == 20000


def test_project_folder_is_where_new_chats_start(home, tmp_path, monkeypatch):
    monkeypatch.delenv("NEOVARCH_CWD", raising=False)
    proj = tmp_path / "proyek"
    proj.mkdir()
    _set(**{"terminal.cwd": str(proj)})
    assert default_cwd() == proj
    _set(**{"terminal.cwd": str(tmp_path / "hilang")})  # a folder that is gone falls back
    assert default_cwd() == Path.cwd()


def test_timezone_sets_the_agents_clock(home):
    _set(timezone="Asia/Jakarta")
    cfg = cfgmod.load_config()
    assert now_text(cfg).endswith("Asia/Jakarta")
    assert "Asia/Jakarta" in system_prompt(cfg, Path("/tmp"))
    _set(timezone="Bukan/Zona")
    assert "Bukan/Zona" not in now_text(cfgmod.load_config())


async def test_file_read_limit_and_shell_timeout(home, tmp_path):
    ctx = ToolContext(cwd=tmp_path, approve=_deny)
    big = tmp_path / "besar.txt"
    big.write_text("x" * 50_000)
    _set(file_read_max_chars=2000)
    out = await tool_read_file({"path": str(big)}, ctx)
    assert "characters omitted" in out and len(out) < 2200
    _set(**{"terminal.timeout": 1})
    out = await tool_shell({"command": "sleep 5"}, ctx)
    assert "timed out after 1s" in out
