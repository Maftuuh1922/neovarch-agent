"""Vault = a real Obsidian vault: projects, sessions and changed files as linked notes,
.obsidian config, non-destructive migration with a zip backup, prompt context with backlinks."""
import json
import zipfile

from aiohttp.test_utils import TestClient, TestServer

from neovarch import config as cfgmod
from neovarch import obsidian, vault_sync
from neovarch.agent import prompt_tail
from neovarch.server import Gateway, build_app
from neovarch.store import SessionStore


def _link_vault(v):
    cfg = cfgmod.load_config()
    cfgmod.set_path(cfg, "memory.obsidian_vault", str(v))
    cfgmod.save_config(cfg)
    return cfgmod.load_config()


def _rec(store, cwd, title="Perbaiki login", files=("src/app.py",)):
    rec = store.create(source="desktop", title=title, model="m1", cwd=str(cwd))
    rec["messages"] = [
        {"role": "user", "content": "Tolong perbaiki login di app"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "edit_file",
                                                         "arguments": json.dumps({"path": files[0]})}},
            {"id": "2", "type": "function", "function": {"name": "obsidian_write",
                                                         "arguments": json.dumps({"path": "Keputusan/Pakai JWT"})}}]},
        {"role": "assistant", "content": "Login sudah diperbaiki, tes hijau.", "files_changed": list(files)},
    ]
    store.save(rec)
    return rec


def test_record_session_links_project_session_files(home, tmp_path):
    v = tmp_path / "Vault"
    v.mkdir()
    (v / "Keputusan").mkdir()
    (v / "Keputusan" / "Pakai JWT.md").write_text("Kita pakai JWT. #keputusan\n")
    proj = tmp_path / "toko-online"
    (proj / "src").mkdir(parents=True)
    rec = _rec(SessionStore(), proj)
    res = vault_sync.record_session(v, rec)
    assert res["project"] == "Neovarch/Proyek/toko-online.md"
    assert res["files"] == ["Neovarch/Proyek/toko-online/Berkas/src/app.py.md"]
    s = (v / res["session"]).read_text()
    assert "[[Neovarch/Proyek/toko-online|toko-online]]" in s
    assert "[[Neovarch/Proyek/toko-online/Berkas/src/app.py|src/app.py]]" in s
    assert "[[Keputusan/Pakai JWT]]" in s
    fm, _, _ = obsidian.split_frontmatter(s)
    assert fm["neovarch"] == "session" and fm["tags"] == ["neovarch/sesi"] and fm["session_id"] == rec["id"]

    g = obsidian.graph(v)
    kinds = {n["id"]: n["kind"] for n in g["nodes"]}
    assert kinds["Neovarch/Proyek/toko-online.md"] == "project"
    assert kinds[res["session"]] == "session"
    assert kinds[res["files"][0]] == "file"
    assert kinds["Neovarch/Neovarch.md"] == "hub"
    assert kinds["Keputusan/Pakai JWT.md"] == "note"
    edges = {(e["source"], e["target"]) for e in g["edges"]}
    assert (res["session"], "Neovarch/Proyek/toko-online.md") in edges
    assert ("Neovarch/Proyek/toko-online.md", res["session"]) in edges
    assert (res["session"], "Keputusan/Pakai JWT.md") in edges
    assert ("Neovarch/Neovarch.md", "Neovarch/Proyek/toko-online.md") in edges
    assert not any(n["id"].startswith("?") for n in g["nodes"])  # every link resolves
    node = next(n for n in g["nodes"] if n["id"] == res["files"][0])
    assert node["project"] == "toko-online" and "neovarch/berkas" in node["tags"]

    # project note lists the decision; the file note remembers which session changed it
    p = (v / res["project"]).read_text()
    assert "[[Keputusan/Pakai JWT]]" in p and "## Catatan" in p
    f = (v / res["files"][0]).read_text()
    assert res["session"][:-3] in f


def test_user_text_outside_auto_block_is_kept(home, tmp_path):
    v = tmp_path / "Vault"
    v.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    store = SessionStore()
    rec = _rec(store, proj)
    res = vault_sync.record_session(v, rec)
    pnote = v / res["project"]
    pnote.write_text(pnote.read_text() + "\nCatatan pribadi saya: deadline Jumat.\n")
    rec2 = _rec(store, proj, title="Tambah checkout", files=("src/checkout.py",))
    vault_sync.record_session(v, rec2)
    text = pnote.read_text()
    assert "Catatan pribadi saya: deadline Jumat." in text
    assert text.count(vault_sync.AUTO_END) == 1
    fm, _, _ = obsidian.split_frontmatter(text)
    assert len(fm["neovarch_sessions"]) == 2
    assert "src/checkout.py" in text


def test_same_folder_name_different_project(home, tmp_path):
    v = tmp_path / "Vault"
    v.mkdir()
    a = tmp_path / "a" / "app"
    b = tmp_path / "b" / "app"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    store = SessionStore()
    r1 = vault_sync.record_session(v, _rec(store, a))
    r2 = vault_sync.record_session(v, _rec(store, b))
    assert r1["project"] == "Neovarch/Proyek/app.md"
    assert r2["project"] == "Neovarch/Proyek/app (b).md"


def test_no_project_for_home_and_files_outside(home, tmp_path, monkeypatch):
    v = tmp_path / "Vault"
    v.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    (tmp_path / "h").mkdir()
    rec = _rec(SessionStore(), tmp_path / "h", files=("/etc/passwd",))
    res = vault_sync.record_session(v, rec)
    assert res["project"] is None and res["files"] == []
    assert "[[Neovarch/Neovarch|Neovarch]]" in (v / res["session"]).read_text()


def test_migrate_is_non_destructive_with_backup(home, tmp_path):
    v = tmp_path / "Lama"
    v.mkdir()
    (v / "Ide.md").write_text("ide lama [[Lain]]\n")
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "app.json").write_text('{"mine": true}')
    mem = home / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "preferensi.md").write_text("User suka bahasa santai.\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    _rec(SessionStore(), proj)

    res = vault_sync.migrate(v)
    assert res["backup"] and zipfile.ZipFile(res["backup"]).namelist().count("Ide.md") == 1
    assert (v / "Ide.md").read_text() == "ide lama [[Lain]]\n"                 # untouched
    assert json.loads((v / ".obsidian" / "app.json").read_text()) == {"mine": True}  # user's config wins
    assert ".obsidian/graph.json" in res["obsidian_config"]
    groups = json.loads((v / ".obsidian" / "graph.json").read_text())["colorGroups"]
    assert {"query": "tag:#neovarch/proyek", "color": {"a": 1, "rgb": 0xE5484D}} in groups
    assert res["memory_imported"] == ["Neovarch/Memori/preferensi.md"]
    assert (mem / "preferensi.md").exists()                                     # original stays
    assert res["sessions"] == 1
    assert (v / "Neovarch" / "Proyek" / "proj.md").exists()
    assert "[[Neovarch/Memori/preferensi|preferensi]]" in (v / "Neovarch" / "Neovarch.md").read_text()
    assert res["open_uri"].startswith("obsidian://open?path=")
    # second run: no new backup, nothing duplicated
    again = vault_sync.migrate(v)
    assert again["new_backup"] is None and again["memory_imported"] == []
    assert len(list((v / "Neovarch" / "Sesi").glob("*.md"))) == 1
    # backfill does not reorder chats (updated_at kept)
    rec = SessionStore().list()[0]
    assert SessionStore().load(rec["id"])["vault_note"].startswith("Neovarch/Sesi/")


def test_init_default_folder_and_status(home, tmp_path, monkeypatch):
    monkeypatch.setenv("NEOVARCH_VAULT_DIR", str(tmp_path / "Neovarch Vault"))
    res = vault_sync.init()
    v = tmp_path / "Neovarch Vault"
    assert res["vault"] == str(v.resolve())
    assert (v / ".obsidian" / "core-plugins.json").exists()
    assert res["status"]["connected"] is True
    assert obsidian.configured_path() == v.resolve()


def test_context_and_turn_recording(home, tmp_path):
    v = tmp_path / "Vault"
    v.mkdir()
    cfg = _link_vault(v)
    proj = tmp_path / "proj"
    proj.mkdir()
    store = SessionStore()
    rec = _rec(store, proj)
    assert vault_sync.record_turn(cfg, rec, ["src/extra.py"], proj).startswith("Neovarch/Sesi/")
    (v / "Rapat.md").write_text("Bahas [[proj]] minggu depan.\n")
    tail = prompt_tail(cfg, "lanjutkan login", proj)
    assert "Neovarch/Proyek/proj.md" in tail and "Perbaiki login" in tail
    assert "Rapat" in tail  # a backlink from the user's own note
    cfgmod.set_path(cfg, "memory.vault_autonotes", False)
    assert vault_sync.record_turn(cfg, rec, [], proj) is None
    assert vault_sync.context_for(cfg, proj) == ""


def test_relevant_notes_carry_backlinks(home, tmp_path):
    v = tmp_path / "Vault"
    v.mkdir()
    (v / "Roadmap.md").write_text("Roadmap rilis kuartal ini.\n")
    (v / "Rapat.md").write_text("Lihat [[Roadmap]].\n")
    hits = obsidian.relevant_notes(v, "roadmap rilis")
    top = next(h for h in hits if h["path"] == "Roadmap.md")
    assert "Backlinks: [[Rapat]]" in top["content"]


def test_slug_and_safe_paths(home, tmp_path):
    assert vault_sync.slug('a/b:c*?"<>|#^[x]') == "a b c x"
    assert vault_sync.slug("") == "Tanpa judul"
    v = tmp_path / "Vault"
    v.mkdir()
    rec = _rec(SessionStore(), tmp_path / "p", files=("../../escape.py",))
    (tmp_path / "p").mkdir(exist_ok=True)
    res = vault_sync.record_session(v, rec)
    assert res["files"] == []  # outside the project folder: no note


async def test_init_and_sync_routes(home, tmp_path, monkeypatch):
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    c = TestClient(TestServer(build_app(Gateway(isolated=False))))
    await c.start_server()
    try:
        v = tmp_path / "BaruVault"
        r = await c.post("/api/obsidian/init?token=tok", json={"path": str(v)})
        assert r.status == 200
        body = await r.json()
        assert body["vault"] == str(v.resolve()) and (v / ".obsidian").is_dir()
        r = await c.get("/api/obsidian/tree?token=tok")
        assert (await r.json())["open_uri"].startswith("obsidian://open?path=")
        r = await c.post("/api/obsidian/sync?token=tok")
        assert r.status == 200
        r = await c.get("/api/obsidian/graph?token=tok")
        nodes = (await r.json())["nodes"]
        assert any(n["kind"] == "hub" for n in nodes)
    finally:
        await c.close()
