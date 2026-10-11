import os

import pytest

from neovarch import config as cfgmod
from neovarch import obsidian
from neovarch.agent import system_prompt
from neovarch.tools import ToolContext, run_tool, tool_schemas


@pytest.fixture
def vault(home, tmp_path):
    v = tmp_path / "MyVault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Proyek").mkdir()
    (v / "Neovarch.md").write_text("---\ntags: [proyek, ai]\nalias: NV\n---\n# Neovarch\nAgen AI lokal. Lihat [[Rapat Senin]].\n")
    (v / "Proyek" / "Rapat Senin.md").write_text("Rapat soal #roadmap dan [[Neovarch|NV]] port 9319.\n")
    (v / "Resep.md").write_text("Nasi goreng pedas. #masak\n")
    cfg = cfgmod.load_config()
    cfgmod.set_path(cfg, "memory.obsidian_vault", str(v))
    cfgmod.save_config(cfg)
    return v


def ctx(tmp_path):
    async def approve(*_):
        return "deny"
    return ToolContext(cwd=tmp_path, approve=approve)


def test_search_text_filename_and_tags(vault):
    hits = obsidian.search(vault, "neovarch")
    assert hits[0]["path"] == "Neovarch.md"
    assert {h["path"] for h in hits} == {"Neovarch.md", "Proyek/Rapat Senin.md"}
    assert [h["path"] for h in obsidian.search(vault, "#roadmap")] == ["Proyek/Rapat Senin.md"]
    assert [h["path"] for h in obsidian.search(vault, "proyek")][0] == "Neovarch.md"  # frontmatter tag
    assert obsidian.search(vault, "rapat")[0]["path"] == "Proyek/Rapat Senin.md"     # filename
    assert obsidian.search(vault, "app.json") == []                                  # .obsidian skipped
    assert obsidian.note_count(vault) == 3


def test_read_by_path_or_name(vault):
    n = obsidian.read_note(vault, "Neovarch")
    assert n["frontmatter"]["alias"] == "NV" and n["tags"] == ["proyek", "ai"]
    assert n["links"] == ["Rapat Senin"]
    assert obsidian.read_note(vault, "Rapat Senin")["path"] == "Proyek/Rapat Senin.md"


def test_write_create_append_keeps_frontmatter_and_links(vault):
    r = obsidian.write_note(vault, "Harian/2026-10-08", "Catatan [[Neovarch]] #harian", frontmatter={"tags": ["harian"]})
    p = vault / "Harian" / "2026-10-08.md"
    assert r["path"] == "Harian/2026-10-08.md" and p.read_text().startswith("---\ntags:\n- harian\n---\n")
    with pytest.raises(obsidian.VaultError):
        obsidian.write_note(vault, "Harian/2026-10-08", "lagi")
    obsidian.write_note(vault, "Neovarch", "Tambahan: lihat [[Resep]].", mode="append")
    text = (vault / "Neovarch.md").read_text()
    assert text.startswith("---\ntags: [proyek, ai]\nalias: NV\n---\n") and text.rstrip().endswith("lihat [[Resep]].")
    assert "Agen AI lokal" in text
    obsidian.write_note(vault, "Neovarch", "Isi baru [[Rapat Senin]]", mode="overwrite")
    text = (vault / "Neovarch.md").read_text()
    assert text.startswith("---\ntags: [proyek, ai]") and "Agen AI lokal" not in text


@pytest.mark.parametrize("bad", ["../luar", "../../etc/passwd", "/etc/passwd", "~/x", "Proyek/../../luar",
                                 ".obsidian/app", "C:/x"])
def test_path_traversal_refused(vault, bad):
    with pytest.raises(obsidian.VaultError):
        obsidian.write_note(vault, bad, "x")
    assert not (vault.parent / "luar.md").exists()


def test_symlink_escape_refused(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, vault / "keluar")
    with pytest.raises(obsidian.VaultError):
        obsidian.write_note(vault, "keluar/bocor", "x")
    assert list(outside.iterdir()) == []


def test_hermes_home_refused(home, tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome"
    (fake_home / ".hermes").mkdir(parents=True)
    import neovarch.paths as paths
    monkeypatch.setattr(paths, "_DIRS", [os.path.normcase(str(fake_home / ".hermes"))])
    cfg = cfgmod.load_config()
    cfgmod.set_path(cfg, "memory.obsidian_vault", str(fake_home / ".hermes"))
    cfgmod.save_config(cfg)
    with pytest.raises(obsidian.VaultError):
        obsidian.require_vault()
    assert obsidian.status()["connected"] is False
    assert list((fake_home / ".hermes").iterdir()) == []


def test_backlinks(vault):
    res = obsidian.links(vault, "Neovarch")
    assert [b["path"] for b in res["backlinks"]] == ["Proyek/Rapat Senin.md"]
    assert res["outgoing"] == ["Rapat Senin"]
    assert [b["path"] for b in obsidian.links(vault, "Rapat Senin")["backlinks"]] == ["Neovarch.md"]


async def test_tools(vault, tmp_path):
    names = {t["function"]["name"] for t in tool_schemas()}
    assert {"obsidian_search", "obsidian_read", "obsidian_write", "obsidian_links"} <= names
    c = ctx(tmp_path)
    assert "Neovarch.md" in await run_tool("obsidian_search", {"query": "neovarch"}, c)
    assert "Agen AI lokal" in await run_tool("obsidian_read", {"path": "Neovarch.md"}, c)
    out = await run_tool("obsidian_write", {"path": "Baru", "content": "Halo [[Neovarch]]"}, c)
    assert out.startswith("create: Baru.md")
    assert "Baru.md" in await run_tool("obsidian_links", {"path": "Neovarch"}, c)
    assert (await run_tool("obsidian_write", {"path": "../kabur", "content": "x"}, c)).startswith("error:")
    assert not (vault.parent / "kabur.md").exists()


async def test_tools_without_vault(home, tmp_path):
    out = await run_tool("obsidian_search", {"query": "x"}, ctx(tmp_path))
    assert out.startswith("error:") and "vault" in out


def test_system_prompt_mentions_vault_and_injects_notes(vault, tmp_path):
    cfg = cfgmod.load_config()
    sp = system_prompt(cfg, tmp_path, "tolong ingat resep nasi goreng")
    assert "Obsidian vault" in sp and str(vault) in sp
    assert "## Resep.md" in sp and "Nasi goreng pedas" in sp
    sp2 = system_prompt(cfg, tmp_path, "halo")
    assert "Obsidian vault" in sp2 and "Relevant vault notes" not in sp2


def test_system_prompt_without_vault(home, tmp_path):
    sp = system_prompt(cfgmod.load_config(), tmp_path, "resep")
    assert "# Obsidian vault" not in sp and "Relevant vault notes" not in sp


def test_status(vault):
    st = obsidian.status()
    assert st == {"configured": True, "connected": True, "enabled": True, "path": str(vault), "note_count": 3}
