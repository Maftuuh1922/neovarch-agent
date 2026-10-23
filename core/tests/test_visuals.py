"""``visual_check``: the agent-side validator for inline ```visual blocks."""
from __future__ import annotations

from pathlib import Path

import pytest

from neovarch import skillpack, tempest_diet
from neovarch.tools import TOOLS, ToolContext
from neovarch.visuals import check_visual, format_report, lenient_json

EXAMPLES = Path(skillpack.PACK_DIR) / "visual-inline" / "examples"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.visual")), ids=lambda p: p.name)
def test_bundled_examples_pass(path):
    res = check_visual(path.read_text(encoding="utf-8"))
    assert res["ok"], res["errors"]
    assert res["title"] and res["caption"]


def test_skill_ships_six_examples_and_the_star_reference():
    assert len(list(EXAMPLES.glob("*.visual"))) >= 6
    body = (EXAMPLES.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "visual_check" in body and "```visual" in body and "Star vs graf kamu" in body


def test_lenient_json():
    assert lenient_json('{"a": [1, 2,], // komentar\n "b": "x//y", /* c */}') == {"a": [1, 2], "b": "x//y"}


def test_spec_errors_are_specific():
    res = check_visual('{"type": "graph", "nodes": ["A", "B"], "edges": [["A", "C"]]}')
    assert not res["ok"]
    assert any("A → C" in e for e in res["errors"])
    assert not check_visual('{"type": "pie"}')["ok"]
    assert not check_visual('{"type": "bar", "data": [{"label": "x", "value": "banyak"}]}')["ok"]
    assert not check_visual('{"type": "graph", "nodes": [{"id": "A", "color": "chartreuse"}]}')["ok"]
    assert not check_visual('{"type": "graph", "nodes": [ ')["ok"]


def test_compare_wants_captions_and_verdicts():
    res = check_visual('{"type": "compare", "title": "t", "caption": "c", "panels": ['
                       '{"visual": {"type": "graph", "nodes": ["A"]}},'
                       '{"verdict": "mungkin", "caption": "x", "visual": {"type": "graph", "nodes": ["A"]}}]}')
    assert res["ok"]
    assert any("tanpa caption" in w for w in res["warnings"])
    assert any("verdict" in w for w in res["warnings"])


def test_svg_rules():
    bad = check_visual('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" onload="x()">'
                       '<script>1</script><image href="https://x/y.png"/><text x="500" y="10" font-size="7">t</text></svg>')
    assert not bad["ok"]
    joined = " ".join(bad["errors"])
    assert "onload" in joined and "<script>" in joined and "https://x" in joined
    assert any("di luar viewBox" in w for w in bad["warnings"]) and any("terlalu kecil" in w for w in bad["warnings"])
    assert not check_visual("<svg><rect/></svg>")["ok"]  # no viewBox
    assert not check_visual("<svg viewBox='0 0 1 1'><rect></svg>")["ok"]  # not XML
    assert not check_visual('<!DOCTYPE x [<!ENTITY a "b">]><svg viewBox="0 0 1 1"/>')["ok"]
    ok = check_visual('title: T\ncaption: C\n---\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
                      '<text x="10" y="20" class="nv-t" font-size="13">ok</text></svg>')
    assert ok["ok"] and ok["warnings"] == []


def test_html_rules_and_fence_stripping():
    assert not check_visual('<div onclick="x()"><script>1</script></div>')["ok"]
    assert not check_visual('<div style="background:url(https://x)">a</div>')["ok"]
    res = check_visual('```visual\ntitle: T\ncaption: C\n---\n<div class="a">ok</div><style>.a{color:var(--nv-fg)}</style>\n```')
    assert res["ok"] and res["kind"] == "html"


def test_report_text():
    assert format_report(check_visual('{"type":"bar","title":"t","caption":"c","data":[{"label":"a","value":1}]}')).startswith("OK")
    assert format_report(check_visual("")).startswith("GAGAL")


def test_tool_is_deferred_behind_extra_tool():
    assert "visual_check" in TOOLS
    assert "visual_check" not in tempest_diet.CORE_TOOLS
    assert "visual_check" in tempest_diet.ONE_LINERS


async def test_tool_runs(tmp_path):
    fn, _schema = TOOLS["visual_check"]
    ctx = ToolContext.__new__(ToolContext)
    out = await fn({"code": '{"type": "timeline", "title": "t", "caption": "c", "events": [{"date": "1", "label": "a"}]}'}, ctx)
    assert out.startswith("OK")


def test_matcher_suggests_visual_inline():
    names = [h["name"] for h in skillpack.match("tolong gambarkan perbandingan graf bintang vs graf ini")]
    assert "visual-inline" in names, names


def test_sequence_spec():
    ok = check_visual('{"type": "sequence", "title": "t", "caption": "c", "participants": ["A", "B"],'
                      '"messages": [{"from": "A", "to": "B", "label": "halo"}, {"group": "alt", "label": "x"},'
                      '{"from": "B", "to": "A", "label": "ok", "dashed": true}, {"else": "y"},'
                      '{"note": "catatan", "over": ["A", "B"]}, {"end": true}]}')
    assert ok["ok"], ok["errors"]
    assert ok["type"] == "sequence"
    assert not check_visual('{"type": "sequence", "messages": []}')["ok"]
    bad = check_visual('{"type": "sequence", "messages": [{"end": true}, {"what": 1}]}')
    assert any("end tanpa group" in e for e in bad["errors"])
    assert any("tidak dikenal" in e for e in bad["errors"])
    many = check_visual('{"type": "sequence", "messages": [' + ",".join(
        f'{{"from": "P{i}", "to": "P{i + 1}", "label": "m"}}' for i in range(11)) + "]}")
    assert any("maks 10" in e for e in many["errors"])
    unclosed = check_visual('{"type": "sequence", "messages": [{"group": "loop"}, {"from": "A", "to": "B"}]}')
    assert unclosed["ok"] and any("belum ditutup" in w for w in unclosed["warnings"])


def test_visual_inline_skill_steers_away_from_mermaid_in_chat():
    body = (EXAMPLES.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "`sequence`" in body and "```mermaid" in body
