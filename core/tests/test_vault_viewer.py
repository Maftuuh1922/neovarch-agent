"""Obsidian vault viewer REST: tree, note with backlinks + obsidian:// link, graph, search."""
from aiohttp.test_utils import TestClient, TestServer

from neovarch import config as cfgmod
from neovarch import obsidian
from neovarch.server import Gateway, build_app


def _vault(tmp_path):
    v = tmp_path / "Kuliah"
    (v / "Bab").mkdir(parents=True)
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "hidden.md").write_text("[[Skripsi]]")
    (v / "Skripsi.md").write_text("---\ntags: [ta]\n---\n# Skripsi\nLihat [[Bab/Pendahuluan]] dan [[Metode|metode]] dan [[Belum Ada]].\n")
    (v / "Bab" / "Pendahuluan.md").write_text("Kembali ke [[Skripsi]].")
    (v / "Metode.md").write_text("Metode penelitian, rujuk [[Skripsi#Bab 1]].")
    return v


def test_tree_and_graph(tmp_path):
    v = _vault(tmp_path)
    t = obsidian.tree(v)
    assert [c["name"] for c in t["children"]] == ["Bab", "Metode", "Skripsi"]
    assert t["children"][0]["children"][0]["path"] == "Bab/Pendahuluan.md"
    g = obsidian.graph(v)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"Skripsi.md", "Bab/Pendahuluan.md", "Metode.md", "?Belum Ada"}
    edges = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("Skripsi.md", "Bab/Pendahuluan.md") in edges and ("Metode.md", "Skripsi.md") in edges
    assert ("Skripsi.md", "?Belum Ada") in edges
    deg = {n["id"]: n["degree"] for n in g["nodes"]}
    assert deg["Skripsi.md"] == 5  # 3 out + 2 in
    assert obsidian.open_uri(v, "Bab/Pendahuluan.md") == "obsidian://open?vault=Kuliah&file=Bab/Pendahuluan"


async def test_viewer_routes(home, tmp_path, monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    c = TestClient(TestServer(build_app(Gateway(isolated=False))))
    await c.start_server()
    try:
        empty = await (await c.get("/api/obsidian/tree?token=tok")).json()
        assert empty["configured"] is False
        assert (await (await c.get("/api/obsidian/graph?token=tok")).json())["nodes"] == []
        v = _vault(tmp_path)
        cfg = cfgmod.load_config()
        cfgmod.set_path(cfg, "memory.obsidian_vault", str(v))
        cfgmod.save_config(cfg)
        tree = await (await c.get("/api/obsidian/tree?token=tok")).json()
        assert tree["configured"] and tree["vault"] == "Kuliah"
        note = await (await c.get("/api/obsidian/note?token=tok&path=Skripsi.md")).json()
        assert note["title"] == "Skripsi" and note["tags"] == ["ta"]
        assert {b["path"] for b in note["backlinks"]} == {"Bab/Pendahuluan.md", "Metode.md"}
        out = {o["target"]: o["path"] for o in note["outgoing"]}
        assert out["Bab/Pendahuluan"] == "Bab/Pendahuluan.md" and out["Belum Ada"] is None
        assert note["open_uri"] == "obsidian://open?vault=Kuliah&file=Skripsi"
        assert (await c.get("/api/obsidian/note?token=tok&path=../../etc/passwd")).status == 400
        assert (await c.get("/api/obsidian/note?token=tok&path=Tidak.md")).status == 404
        graph = await (await c.get("/api/obsidian/graph?token=tok")).json()
        assert len(graph["nodes"]) == 4 and len(graph["edges"]) == 5
        found = await (await c.get("/api/obsidian/search?token=tok&q=metode")).json()
        assert any(r["path"] == "Metode.md" for r in found["results"])
    finally:
        await c.close()


async def test_configure_vault_from_settings(home, tmp_path, monkeypatch):
    """Settings ▸ Vault Obsidian saves the folder through POST /api/memory/obsidian
    and the viewer loads it straight away; switching it off hides it again."""
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    c = TestClient(TestServer(build_app(Gateway(isolated=False))))
    await c.start_server()
    try:
        st = await (await c.get("/api/memory/obsidian?token=tok")).json()
        assert st["configured"] is False and st["enabled"] is True and st["path"] == ""
        missing = await c.post("/api/memory/obsidian?token=tok", json={"path": str(tmp_path / "nope"), "enabled": True})
        assert missing.status == 400 and "does not exist" in (await missing.json())["error"]
        v = _vault(tmp_path)
        saved = await (await c.post("/api/memory/obsidian?token=tok", json={"path": str(v), "enabled": True})).json()
        assert saved["ok"] and saved["configured"] and saved["connected"] and saved["note_count"] == 3
        assert cfgmod.get_path(cfgmod.load_config(), "memory.obsidian_vault") == str(v.resolve())
        tree = await (await c.get("/api/obsidian/tree?token=tok")).json()
        assert tree["configured"] and tree["vault"] == "Kuliah"
        off = await (await c.post("/api/memory/obsidian?token=tok", json={"path": str(v), "enabled": False})).json()
        assert off["configured"] is False and off["enabled"] is False and off["path"] == str(v.resolve())
        assert (await (await c.get("/api/obsidian/tree?token=tok")).json())["configured"] is False
        assert obsidian.vault_path() is None
        cleared = await (await c.post("/api/memory/obsidian?token=tok", json={"path": "", "enabled": True})).json()
        assert cleared["configured"] is False and cleared["path"] == ""
    finally:
        await c.close()
