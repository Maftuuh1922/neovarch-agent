"""The default skill pack: installed and enabled by default, in the prompt index for
every model, picked by the matcher, licensed, and diagrams saved as openable files."""

import json
from pathlib import Path

import pytest

from neovarch import skillpack
from neovarch.agent import system_prompt
from neovarch.tools import ToolContext, list_skills, run_tool, save_diagram

PACK_IDS = {s["id"] for s in skillpack.pack_skills()}
EXPECTED = {
    # obra/superpowers (MIT)
    "test-driven-development", "systematic-debugging", "requesting-code-review", "verification-before-completion",
    "writing-plans", "finishing-a-development-branch", "brainstorming",
    # addyosmani/agent-skills (MIT)
    "security-and-hardening", "code-review-and-quality", "ci-cd-and-automation", "git-workflow-and-versioning",
    "frontend-ui-engineering", "performance-optimization", "shipping-and-launch", "documentation-and-adrs",
    "api-and-interface-design",
    # anthropics/skills (Apache-2.0), diagram-design, archify, rea (MIT)
    "frontend-design", "diagram", "diagram-interaktif", "investigasi",
    # Mode Desain: nexu-io/open-design + pbakaus/impeccable (Apache-2.0), ui-ux-pro-max + taste-skill (MIT)
    "desain", "ui-ux-pro-max", "taste", "impeccable",
    # original
    "disiplin-koding", "design-to-code",
    "riset-akademik", "tulis-akademik", "review-sejawat", "revisi-akademik", "finalisasi-akademik",
}


def test_manifest_lists_the_whole_pack():
    assert PACK_IDS == EXPECTED
    for s in skillpack.pack_skills():
        assert (skillpack.PACK_DIR / s["id"] / "SKILL.md").is_file(), s["id"]
        assert s["summary"] and s["keywords"] and s["license"] and s["source"]


def test_licenses_and_attribution_present():
    notice = (skillpack.PACK_DIR / "THIRD_PARTY_SKILLS.md").read_text(encoding="utf-8")
    for s in skillpack.pack_skills():
        assert f"`{s['id']}`" in notice
        folder = skillpack.PACK_DIR / s["id"]
        if s["source"].startswith("Neovarch"):
            continue
        lic = [p for p in (folder / "LICENSE", folder / "LICENSE.txt") if p.is_file()]
        assert lic, f"{s['id']} has no upstream license file"
        text = lic[0].read_text(encoding="utf-8")
        assert ("MIT License" in text) if s["license"] == "MIT" else ("Apache License" in text)
    # Skipped sources are never vendored; the originals only credit them.
    for sid in ("riset-akademik", "tulis-akademik", "review-sejawat", "revisi-akademik", "finalisasi-akademik"):
        body = (skillpack.PACK_DIR / sid / "SKILL.md").read_text(encoding="utf-8")
        assert "inspired by the workflow of Imbad0202/academic-research-skills" in body
        assert not (skillpack.PACK_DIR / sid / "LICENSE").exists()
    assert not any((skillpack.PACK_DIR / n).exists() for n in ("pdf", "docx", "xlsx", "pptx"))


def test_no_other_agent_brand_in_pack():
    for p in skillpack.PACK_DIR.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".json", ".txt", ""):
            assert "hermes" not in p.read_text(encoding="utf-8", errors="replace").lower(), p


def test_pack_installed_enabled_and_toggleable(home):
    names = {s["name"]: s for s in list_skills()}
    assert EXPECTED <= set(names)
    assert names["security-and-hardening"]["label"] == "Keamanan & Hardening"
    assert all(names[i]["enabled"] for i in EXPECTED)
    from neovarch import skills_admin
    assert skills_admin.set_enabled("diagram", False)["ok"]
    assert "diagram" not in {s["name"] for s in list_skills()}
    assert "diagram" in {s["name"] for s in list_skills(include_disabled=True)}


def test_user_edit_is_kept_on_upgrade(home):
    list_skills()
    md = home / "skills" / "diagram" / "SKILL.md"
    md.write_text("---\nname: diagram\ndescription: punyaku\n---\nmine\n", encoding="utf-8")
    marker = md.parent / skillpack.MARKER
    meta = json.loads(marker.read_text())
    marker.write_text(json.dumps({**meta, "version": "0"}))
    skillpack.install(home / "skills")
    assert md.read_text(encoding="utf-8").endswith("mine\n")


def test_skill_index_in_system_prompt_for_any_model(home):
    sp = system_prompt({}, Path.cwd(), "halo")
    assert "# Skills" in sp and "panggil alat `skill`" in sp
    for sid in EXPECTED:
        assert f"- {sid}" in sp


@pytest.mark.parametrize("prompt,expected", [
    ("cek keamanan aplikasi web saya, takut ada SQL injection dan XSS", "security-and-hardening"),
    ("tolong audit security API login ini", "security-and-hardening"),
    ("bikinin desain landing page yang keren buat produk kopi", "frontend-design"),
    ("buatkan diagram flowchart alur pendaftaran mahasiswa", "diagram"),
    ("gambarin ERD database toko online", "diagram"),
    ("bikin diagram interaktif arsitektur sistem microservice kami", "diagram-interaktif"),
    ("bantu bikin skripsi tentang machine learning", "tulis-akademik"),
    ("bantu bikin jurnal ilmiah tentang IoT pertanian", "tulis-akademik"),
    ("bantu bikin literature review tentang deep learning", "riset-akademik"),
    ("carikan referensi jurnal tentang IoT", "riset-akademik"),
    ("tolong peer review naskah jurnal saya", "review-sejawat"),
    ("ini catatan dosen pembimbing, bantu revisi bab 3", "revisi-akademik"),
    ("cek plagiarisme dan rapikan daftar pustaka sebelum submit jurnal", "finalisasi-akademik"),
    ("programku error traceback KeyError, kenapa ya", "systematic-debugging"),
    ("bongkar APK ini dan cari kenapa crash", "investigasi"),
])
def test_matcher_picks_the_right_skill(prompt, expected):
    names = [h["name"] for h in skillpack.match(prompt)]
    assert expected in names, (prompt, names)


def test_matcher_stays_quiet_on_small_talk():
    assert skillpack.match("halo, apa kabar?") == []
    assert skillpack.match("") == []


def test_hint_reaches_the_prompt(home):
    sp = system_prompt({}, Path.cwd(), "bantu bikin skripsi dan literature review")
    assert "Skill yang cocok untuk pesan ini" in sp
    assert "`tulis-akademik`" in sp and "`riset-akademik`" in sp


def test_matcher_skips_disabled_skills(home):
    from neovarch import skills_admin
    list_skills()
    skills_admin.set_enabled("diagram", False)
    hits = skillpack.match("buatkan diagram flowchart", list_skills())
    assert "diagram" not in [h["name"] for h in hits]


def test_diagram_save_formats(home):
    page, src = save_diagram("Alur Daftar", "mermaid", "flowchart TD\n A-->B")
    assert page.suffix == ".html" and src.suffix == ".mmd"
    assert "mermaid" in page.read_text() and "A--&gt;B" in page.read_text()
    page, svg = save_diagram("erd", "svg", '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
    assert svg.suffix == ".svg" and "<svg" in page.read_text()
    (only,) = save_diagram("x", "html", "<html><body>hi</body></html>")
    assert only.parent == home / "diagrams"
    with pytest.raises(ValueError):
        save_diagram("bad", "svg", "not svg")


async def test_diagram_save_tool_returns_path(home, tmp_path):
    out = await run_tool("diagram_save", {"name": "alur", "format": "mermaid", "content": "graph LR; a-->b"},
                         ToolContext(cwd=tmp_path, approve=None))
    assert str(home / "diagrams") in out and ".html" in out
