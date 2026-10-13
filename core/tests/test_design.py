"""Mode Desain: catalog, design store under .neovarch/design, prompt injection, token check,
brand import, artifacts + preview send, critique, export, /desain command and desktop dispatch."""

import json
from pathlib import Path

import pytest

from neovarch import design, skillpack
from neovarch.agent import system_prompt, system_sections
from neovarch.tools import TOOLS, ToolContext, run_tool


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "app"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    return root


def test_catalog_has_directions_systems_templates():
    ids = [d["id"] for d in design.directions()]
    assert ids == ["editorial-monocle", "modern-minimal", "human-approachable", "tech-utility",
                   "brutalist-experimental"]
    systems = {s["id"] for s in design.systems()}
    assert {"default", "minimal", "editorial", "brutalism", "dashboard", "stripe", "vercel"} <= systems
    groups = {t["group"] for t in design.templates()}
    assert {"landing", "dashboard", "deck", "mobile", "docs", "prototype"} <= groups
    assert design.template_path("landing").name == "saas-landing"
    text = design.catalog_text()
    assert "modern-minimal" in text and "saas-landing" in text and "stripe" in text


@pytest.mark.parametrize("raw,hexv", [
    ("#2F6FEB", "#2f6feb"), ("#abc", "#aabbcc"), ("rgb(10, 20, 30)", "#0a141e"), ("rgba(255 0 0 / .5)", "#ff0000"),
    ("hsl(0, 100%, 50%)", "#ff0000"), ("Color(0xFFE0262F)", "#e0262f"), ("oklch(100% 0 0)", "#ffffff"),
    ("oklch(0% 0 0)", "#000000"),
])
def test_parse_color(raw, hexv):
    assert design.to_hex(design.parse_color(raw)) == hexv


def test_oklch_close_to_reference():
    # oklch(62.8% 0.2577 29.23) is CSS red #ff0000
    assert design.delta_e(design.parse_color("oklch(62.8% 0.2577 29.23)"), (255, 0, 0)) < 2


def test_use_direction_writes_project_design_system(proj):
    paths = design.use_direction(proj / "src", "modern-minimal", brief="aplikasi kasir", name="Kasirku")
    d = proj / ".neovarch" / "design"
    assert paths["design"] == d / "DESIGN.md" and paths["css"].is_file() and paths["json"].is_file()
    css = (d / "tokens.css").read_text()
    assert ":root {" in css and "--accent: oklch(58% 0.18 255);" in css
    meta = json.loads((d / "tokens.json").read_text())
    assert meta["source"] == "direction:modern-minimal" and meta["inject"] is True
    assert set(design.REQUIRED_TOKENS) <= set(meta["tokens"])
    md = (d / "DESIGN.md").read_text()
    assert md.startswith("# Kasirku") and "aplikasi kasir" in md and "## Color Palette & Roles" in md
    assert design.load(proj)["tokens"] == meta["tokens"]
    assert (proj / ".neovarch" / ".gitignore").is_file()


def test_use_system_keeps_attribution(proj):
    design.use_system(proj, "stripe")
    ds = design.load(proj)
    assert ds["meta"]["source"] == "system:stripe"
    assert "nexu-io/open-design (Apache-2.0)" in ds["design_md"]
    assert design.parse_color(ds["tokens"]["--accent"]) is not None
    with pytest.raises(design.DesignError):
        design.use_system(proj, "tidak-ada")


def test_save_validates_tokens(proj):
    with pytest.raises(design.DesignError, match="token wajib"):
        design.save(proj, "# x", {"--bg": "#fff"})
    toks = {**design.direction_tokens(design.direction("tech")), "--accent": "bukan-warna"}
    with pytest.raises(design.DesignError, match="tidak terbaca"):
        design.save(proj, "# x", toks)


def test_prompt_injection_and_handoff_toggle(proj, home):
    assert design.prompt_section(proj) == ""
    design.use_direction(proj, "tech-utility", name="Ops")
    sp = system_prompt({}, proj / "src", "ubah tombol login")
    assert "# Design system proyek" in sp and "--accent: oklch(58% 0.16 145)" in sp
    assert "design` action=check" in sp
    keys = [k for k, _ in system_sections({}, proj, "x", stable=True)]
    assert keys.index("design") < keys.index("skills")
    design.set_inject(proj, False)
    assert "# Design system proyek" not in system_prompt({}, proj, "x")
    design.set_inject(proj, True)
    assert "# Design system proyek" in system_prompt({}, proj, "x")


def test_prompt_section_survives_broken_folder(proj):
    d = proj / ".neovarch" / "design"
    d.mkdir(parents=True)
    (d / "tokens.json").write_text("{nope")
    assert design.prompt_section(proj) == ""


def test_token_check_finds_drift(proj):
    design.save(proj, "# Brand\n", {"--bg": "#ffffff", "--surface": "#fafafa", "--fg": "#111111", "--muted": "#6b6b6b",
                                    "--border": "#e5e5e5", "--accent": "#e0262f",
                                    "--font-display": "'Inter', sans-serif", "--font-body": "'Inter', sans-serif"})
    (proj / "src" / "App.css").write_text(
        ":root { --local: #123456; }\n"
        ".btn { background: #E0262F; color: #fff; }\n"
        ".hero { color: #3b82f6; font-family: 'Comic Sans MS', cursive; }\n"
        ".cta { background: var(--accent); font-family: var(--font-body); }\n"
        ".bad { border-color: #6366f1; }\n")
    (proj / "src" / "Card.tsx").write_text("export const C = () => <div style={{color: 'rgb(17,17,17)'}} />\n")
    (proj / "lib").mkdir()
    (proj / "lib" / "main.dart").write_text("final c = Color(0xFF00AA00);\nfinal ok = Color(0xFFE0262F);\n")
    (proj / "node_modules" / "x").mkdir(parents=True)
    (proj / "node_modules" / "x" / "a.css").write_text(".x{color:#00ff00}")
    res = design.check(proj)
    kinds = [(f["file"], f["kind"], f["value"]) for f in res["findings"]]
    assert ("src/App.css", "hardcoded", "#E0262F") in kinds
    assert ("src/App.css", "off-palette", "#3b82f6") in kinds
    assert ("src/App.css", "off-font", "Comic Sans MS") in kinds
    assert ("src/App.css", "ai-indigo", "#6366f1") in kinds
    assert ("src/Card.tsx", "hardcoded", "rgb(17,17,17)") in kinds
    assert ("lib/main.dart", "off-palette", "Color(0xFF00AA00)") in kinds
    assert ("lib/main.dart", "hardcoded", "Color(0xFFE0262F)") in kinds
    assert not any(f["file"].startswith("node_modules") for f in res["findings"])
    assert not any(f["value"] == "#123456" for f in res["findings"])  # token definitions are skipped
    assert not res["ok"] and res["score"] < 100
    text = design.format_check(res)
    assert "var(--accent)" in text and "off-palette" in text


def test_token_check_clean_project(proj):
    design.use_direction(proj, "modern-minimal")
    (proj / "src" / "a.css").write_text(".a{color:var(--fg);background:var(--bg)}\n")
    res = design.check(proj)
    assert res["ok"] and res["findings"] == [] and "✅" in design.format_check(res)


def test_check_without_design_system(proj):
    with pytest.raises(design.DesignError):
        design.check(proj)


def test_analyze_brand_from_html():
    html = """<html><head><title> Kopi Senja </title><meta name="theme-color" content="#c8101a">
    <style>:root{--brand:#c8101a;--ink:#1a1a1a}
    body{background:#faf7f2;color:#1a1a1a;font-family:'Fraunces', serif}
    .btn{background-color:#c8101a;color:#fff} p{font-family: "Inter", sans-serif} a{color:#c8101a}</style>
    <link rel="stylesheet" href="/main.css"></head><body></body></html>"""
    res = design.analyze_brand(html, [".x{font-family:Inter}"], "https://kopi.example")
    t = res["tokens"]
    assert res["title"] == "Kopi Senja" and res["dark"] is False
    assert t["--bg"] == "#faf7f2" and t["--fg"] == "#1a1a1a" and t["--accent"] == "#c8101a"
    assert "Inter" in res["fonts"] and "Fraunces" in res["fonts"]
    assert design.stylesheet_links(html) == ["/main.css"]
    assert set(design.REQUIRED_TOKENS) <= set(t)


def test_analyze_brand_dark_page():
    res = design.analyze_brand("<style>body{background:#0b0b0d;color:#f2ede4}.c{color:#22c55e}</style>")
    assert res["dark"] and res["tokens"]["--bg"] == "#0b0b0d" and res["tokens"]["--fg"] == "#f2ede4"
    assert res["tokens"]["--accent"] == "#22c55e"


def test_artifact_critique_export(proj, home):
    design.use_direction(proj, "human-approachable", name="Sehatku")
    with pytest.raises(design.DesignError):
        design.save_artifact(proj, "x", "<div>bukan dokumen</div>")
    page = "<!doctype html><html><head><style>:root{}</style></head><body style='color:var(--fg)'></body></html>"
    p = design.save_artifact(proj, "Landing Sehatku!", page)
    assert p == proj / ".neovarch" / "design" / "artifacts" / "landing-sehatku.html"
    with pytest.raises(design.DesignError):
        design.record_critique(proj, {"philosophy": 4})
    row = design.record_critique(proj, {"philosophy": 4, "hierarchy": 2, "execution": 4, "specificity": 3,
                                        "restraint": 5}, artifact="landing-sehatku")
    assert row["weak"] == ["hierarchy"] and row["average"] == 3.6
    hist = json.loads((proj / ".neovarch" / "design" / "critique.json").read_text())
    assert hist[-1]["scores"]["hierarchy"] == 2
    dart = design.export(proj, "dart").read_text()
    assert "class NvTokens" in dart and "static const Color accent = Color(0xFF" in dart and "ThemeData theme()" in dart
    tw = design.export(proj, "tailwind").read_text()
    assert "@theme {" in tw and "--color-accent:" in tw
    with pytest.raises(design.DesignError):
        design.export(proj, "pdf")


def test_remember_goes_to_memory_note(home):
    p = design.remember("Jangan pernah pakai gradient; sudut membulat 12px")
    assert p == home / "memory" / "desain-preferensi.md"
    design.remember("Jangan pernah pakai gradient; sudut membulat 12px")  # no duplicate line
    text = p.read_text()
    assert text.count("Jangan pernah pakai gradient") == 1
    assert "desain-preferensi" in system_prompt({}, Path.cwd(), "halo")


async def test_design_tool_end_to_end(proj, home):
    assert "design" in TOOLS
    ctx = ToolContext(cwd=proj, approve=None, session_id="s1")
    out = await run_tool("design", {"action": "catalog", "kind": "directions"}, ctx)
    assert "brutalist-experimental" in out
    out = await run_tool("design", {"action": "use_direction", "direction": "editorial-monocle",
                                    "overrides": {"--accent": "#c8101a"}}, ctx)
    assert "Arah dikunci" in out and design.load(proj)["tokens"]["--accent"] == "#c8101a"
    out = await run_tool("design", {"action": "template", "id": "dashboard"}, ctx)
    assert "TEMPLATE_DIR:" in out and "dashboard" in out
    page = ("<!doctype html><html><head><style>:root{--bg:#fff}</style></head>"
            "<body style='background:var(--bg);color:var(--fg)'><a style='color:var(--accent)'>Daftar</a></body></html>")
    out = await run_tool("design", {"action": "artifact", "name": "hero", "html": page}, ctx)
    assert "artifacts/hero.html" in out and "philosophy" in out
    assert ctx.outbox and ctx.outbox[0]["name"] == "hero.html"  # sent to the chat for the preview card
    out = await run_tool("design", {"action": "critique", "scores": {k: 4 for k in design.CRITIQUE_DIMS}}, ctx)
    assert "rata-rata 4.0/5" in out
    out = await run_tool("design", {"action": "handoff"}, ctx)
    assert "Siap dipakai untuk coding" in out
    out = await run_tool("design", {"action": "check"}, ctx)
    assert "Cek konsistensi token" in out
    out = await run_tool("design", {"action": "use_system", "system": "nope"}, ctx)
    assert out.startswith("error:")


def test_desain_command(proj):
    kind, reply, follow = design.command("/desain landing page kopi susu", proj / "src")
    assert kind == "desain" and "Mode Desain aktif" in reply
    assert "skill `desain`" in follow and "landing page kopi susu" in follow and str(proj) in follow
    _, _, follow = design.command("/desain", proj)
    assert "tanyakan" in follow
    _, reply, follow = design.command("/desain status", proj)
    assert "Belum ada design system" in reply and follow == ""
    _, reply, _ = design.command("/desain cek", proj)
    assert "belum punya design system" in reply
    assert design.command("desain landing", proj) is None
    assert design.command("/desainer", proj) is None


def test_pack_ships_design_skills_with_licenses():
    pack = skillpack.by_id()
    for sid, lic in (("desain", "Apache-2.0"), ("ui-ux-pro-max", "MIT"), ("taste", "MIT"), ("impeccable", "Apache-2.0"),
                     ("design-to-code", "MIT")):
        assert pack[sid]["license"] == lic
    root = skillpack.PACK_DIR
    assert (root / "ui-ux-pro-max" / "upstream" / "scripts" / "search.py").is_file()
    assert (root / "impeccable" / "NOTICE.md").is_file()
    assert (root / "desain" / "upstream" / "craft" / "anti-ai-slop.md").is_file()
    notice = (root / "THIRD_PARTY_SKILLS.md").read_text(encoding="utf-8")
    for src in ("nexu-io/open-design", "nextlevelbuilder/ui-ux-pro-max-skill", "Leonxlnx/taste-skill",
                "pbakaus/impeccable"):
        assert src in notice


@pytest.mark.parametrize("prompt,expected", [
    ("/desain landing page kopi", "desain"),
    ("bikin design system untuk aplikasi saya", "desain"),
    ("implementasikan desain ini ke flutter pakai tokens.css", "design-to-code"),
    ("pilih palet warna dan font pairing buat app finansial", "ui-ux-pro-max"),
    ("redesign web lama saya biar gak generik", "taste"),
    ("tolong audit ux halaman checkout ini", "impeccable"),
])
def test_matcher_picks_design_skills(prompt, expected):
    assert expected in [h["name"] for h in skillpack.match(prompt)]


async def test_desktop_slash_dispatch_and_catalogs(mock_provider, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from neovarch.server import Gateway, build_app
    from test_server import WS
    monkeypatch.setenv("NEOVARCH_SESSION_TOKEN", "tok")
    gw = Gateway(isolated=False)
    c = TestClient(TestServer(build_app(gw)))
    await c.start_server()
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        names = [x["name"] for x in (await ws.call("commands.catalog", {}))["result"]["commands"]]
        assert "desain" in names
        res = (await ws.call("slash.exec", {"session_id": "s", "command": "desain landing kopi"}))["result"]
        assert res == {"type": "send", "message": "/desain landing kopi", "display": "/desain landing kopi"}
        res = (await ws.call("command.dispatch", {"session_id": "s", "name": "perbaiki", "arg": ""}))["result"]
        assert res["type"] == "send" and res["message"] == "/perbaiki"
        err = await ws.call("command.dispatch", {"name": "bukan-perintah"})
        assert err["error"]["code"] == -32601
        r = await c.get("/api/composer/catalog?token=tok")
        assert "desain" in [x["name"] for x in (await r.json())["commands"]]
    finally:
        await c.close()


async def test_desain_command_in_a_turn(mock_provider, tmp_path):
    """/desain answers at once and hands the model a hidden follow-up with the workflow."""
    from neovarch.agent import Agent
    from neovarch.store import SessionStore
    store = SessionStore()
    rec = store.create()
    events = []
    ctx = ToolContext(cwd=tmp_path, approve=None)
    agent = Agent(rec, store, ctx, lambda kind, data: events.append((kind, data)))
    await agent.run_turn("/desain status")
    msgs = rec["messages"]
    assert msgs[-1]["role"] == "assistant" and msgs[-1].get("command") == "desain"
    assert "Belum ada design system" in msgs[-1]["content"]
