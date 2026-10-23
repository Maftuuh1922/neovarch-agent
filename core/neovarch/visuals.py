"""Checks for inline ```visual blocks before the agent sends them.

A ```visual fence in a chat answer is drawn as a vector card by the desktop app and
the phone (desktop/apps/desktop/src/lib/visual, bundled for Android as
assets/diagram/visual.js). This module mirrors that renderer's rules so the agent can
catch a broken block *before* the user sees "gagal digambar":

* declarative specs (JSON): ``graph`` | ``flow`` | ``bar`` | ``timeline`` | ``sequence`` | ``compare``
  - known type, required lists present, edges point at existing nodes, sane sizes,
    palette colours, compare panels with a caption and a ✓/✗ verdict;
* raw SVG: parses as XML, has a viewBox (or width/height), nothing the sanitiser
  would strip (scripts, event handlers, foreignObject, external links/urls), readable
  text sizes, text inside the viewBox;
* HTML+CSS fragments: no scripts, frames, forms, handlers or external resources.

Pure standard library, no network, no model calls. ``check_visual`` returns a dict;
``format_report`` turns it into the short text the ``visual_check`` tool returns.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

MAX_CHARS = 200_000
TYPES = ("graph", "flow", "bar", "timeline", "sequence", "compare")
ALIASES = {
    "bars": "bar", "chart": "bar", "comparison": "compare", "flowchart": "flow", "network": "graph",
    "side-by-side": "compare", "steps": "flow", "tree": "graph", "versus": "compare", "vs": "compare",
    "seq": "sequence", "sequencediagram": "sequence",
}
PALETTE = {"blue", "green", "red", "amber", "purple", "teal", "pink", "accent", "gray", "grey", "muted",
           "good", "ok", "bad", "error"}
GOOD = {"good", "ok", "yes", "true", "benar", "ya", "pass", "✓"}
BAD = {"bad", "no", "false", "salah", "tidak", "fail", "✗"}
HEADER = re.compile(r"^\s*(title|judul|caption|keterangan)\s*:\s*(.*)$", re.I)
FORBIDDEN_TAGS = {"script", "foreignobject", "iframe", "object", "embed", "form", "input", "textarea", "select",
                  "button", "link", "meta", "base", "audio", "video", "animate", "set", "animatemotion",
                  "animatetransform"}
EXTERNAL_URL = re.compile(r"url\(\s*['\"]?(?!data:image/|#)[^)]*\)", re.I)


def _strip_header(code: str) -> tuple[str, str | None, str | None]:
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = caption = None
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        m = HEADER.match(lines[i])
        if not m:
            break
        if m.group(1).lower() in ("title", "judul"):
            title = m.group(2).strip()
        else:
            caption = m.group(2).strip()
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
    return "\n".join(lines[i:]).strip(), title, caption


def lenient_json(text: str) -> Any:
    """JSON with // and /* */ comments and trailing commas (outside strings)."""
    out: list[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def _node_ids(raw: Any) -> list[str]:
    ids = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            ids.append(str(item))
        elif isinstance(item, dict):
            v = item.get("id", item.get("name", item.get("label")))
            if v is not None:
                ids.append(str(v))
    return ids


def _edge_ends(item: Any) -> tuple[str, str] | None:
    if isinstance(item, list) and len(item) >= 2:
        return str(item[0]), str(item[1])
    if isinstance(item, str):
        m = re.match(r"^\s*(.+?)\s*(?:->|--|→)\s*(.+?)\s*$", item)
        return (m.group(1), m.group(2)) if m else None
    if isinstance(item, dict):
        a, b = item.get("from", item.get("source")), item.get("to", item.get("target"))
        return (str(a), str(b)) if a is not None and b is not None else None
    return None


def _colors(items: list[Any], path: str, errors: list[str]) -> None:
    for k, item in enumerate(items):
        if isinstance(item, dict) and "color" in item:
            c = str(item["color"]).strip().lower()
            if c not in PALETTE and not re.fullmatch(r"#[0-9a-f]{3,8}", c):
                errors.append(f"{path}[{k}].color '{item['color']}' tidak dikenal (pakai blue/green/red/amber/purple/teal/pink/gray atau #hex)")


def _check_spec(spec: Any, path: str, errors: list[str], warnings: list[str], depth: int = 0) -> None:
    if not isinstance(spec, dict):
        errors.append(f"{path}: harus objek JSON")
        return
    raw_type = str(spec.get("type", "")).lower()
    typ = ALIASES.get(raw_type, raw_type)
    if typ not in TYPES:
        errors.append(f"{path}.type '{raw_type or '?'}' tidak dikenal; pakai {' | '.join(TYPES)}")
        return
    if typ == "graph":
        nodes = spec.get("nodes")
        ids = _node_ids(nodes)
        if not ids:
            errors.append(f"{path}.nodes kosong (daftar id atau objek {{id, label, highlight}})")
            return
        if len(set(ids)) != len(ids):
            warnings.append(f"{path}.nodes punya id ganda; yang kedua diabaikan")
        if len(ids) > 40:
            warnings.append(f"{path}: {len(ids)} simpul terlalu ramai; maks ±15 supaya terbaca, pecah jadi beberapa visual")
        idset = set(ids)
        for k, e in enumerate(spec.get("edges", spec.get("links", [])) or []):
            ends = _edge_ends(e)
            if not ends:
                errors.append(f"{path}.edges[{k}] tidak terbaca (pakai [\"A\",\"B\"] atau {{from,to}})")
            elif ends[0] not in idset or ends[1] not in idset:
                errors.append(f"{path}.edges[{k}] menunjuk simpul yang tidak ada: {ends[0]} → {ends[1]}")
        hl = [n for n in nodes if isinstance(n, dict) and n.get("highlight")]
        if len(ids) >= 4 and len(hl) > len(ids) / 2 and not spec.get("highlightEdges"):
            warnings.append(f"{path}: terlalu banyak simpul disorot ({len(hl)}/{len(ids)}); sorot hanya yang penting")
        long = [i for i in ids if len(i) > 3 and not any(isinstance(n, dict) and n.get("label") for n in nodes)]
        if len(long) > 12:
            warnings.append(f"{path}: label panjang di banyak simpul membuat graf lebar; pakai huruf + keterangan")
        _colors(nodes if isinstance(nodes, list) else [], f"{path}.nodes", errors)
    elif typ == "flow":
        steps = spec.get("steps", spec.get("nodes"))
        if not isinstance(steps, list) or not steps:
            errors.append(f"{path}.steps kosong")
            return
        if len(steps) > 20:
            warnings.append(f"{path}: {len(steps)} langkah terlalu panjang; maks ±12, pecah alurnya")
        ids = [str(s.get("id", f"s{i + 1}")) if isinstance(s, dict) else f"s{i + 1}" for i, s in enumerate(steps)]
        idset = set(ids)
        for k, e in enumerate(spec.get("edges", []) or []):
            ends = _edge_ends(e)
            if not ends or ends[0] not in idset or ends[1] not in idset:
                errors.append(f"{path}.edges[{k}] menunjuk langkah yang tidak ada (id langkah: {', '.join(ids[:8])})")
        for k, s in enumerate(steps):
            label = s if isinstance(s, str) else (s.get("label") or s.get("title") or "") if isinstance(s, dict) else ""
            if len(str(label)) > 70:
                warnings.append(f"{path}.steps[{k}] label > 70 karakter; ringkas, detail taruh di note")
        _colors(steps, f"{path}.steps", errors)
    elif typ == "bar":
        data = spec.get("data", spec.get("bars", spec.get("items")))
        if not isinstance(data, list) or not data:
            errors.append(f"{path}.data kosong (daftar {{label, value}})")
            return
        for k, d in enumerate(data):
            v = d.get("value") if isinstance(d, dict) else None
            try:
                float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                errors.append(f"{path}.data[{k}].value bukan angka")
        if len(data) > 16:
            warnings.append(f"{path}: {len(data)} batang terlalu banyak; tampilkan 3-10 yang penting")
        _colors(data, f"{path}.data", errors)
    elif typ == "timeline":
        events = spec.get("events", spec.get("items", spec.get("steps")))
        if not isinstance(events, list) or not events:
            errors.append(f"{path}.events kosong (daftar {{date, label}})")
            return
        if len(events) > 14:
            warnings.append(f"{path}: {len(events)} peristiwa; maks ±10 supaya terbaca")
        _colors(events, f"{path}.events", errors)
    elif typ == "sequence":
        msgs = spec.get("messages", spec.get("steps", spec.get("items")))
        if not isinstance(msgs, list) or not msgs:
            errors.append(f"{path}.messages kosong (daftar {{from, to, label}}, {{note, over}}, {{group}}/{{else}}/{{end}})")
            return
        parts = spec.get("participants", spec.get("actors")) or []
        ids = {str(p.get("id", p.get("name", p.get("label", "")))) if isinstance(p, dict) else str(p) for p in parts}
        for m in msgs:
            if isinstance(m, dict) and "from" in m:
                ids.add(str(m.get("from")))
                ids.add(str(m.get("to", m.get("from"))))
        if len(ids) > 10:
            errors.append(f"{path}: {len(ids)} peserta; maks 10")
        elif len(ids) > 6:
            warnings.append(f"{path}: {len(ids)} peserta membuat kolom sempit di HP; maks ±5")
        if len(msgs) > 40:
            warnings.append(f"{path}: {len(msgs)} pesan terlalu panjang; pecah jadi beberapa visual")
        opened = 0
        for k, m in enumerate(msgs):
            if not isinstance(m, dict):
                errors.append(f"{path}.messages[{k}] harus objek")
                continue
            if "group" in m:
                opened += 1
            elif m.get("end"):
                if opened == 0:
                    errors.append(f"{path}.messages[{k}] end tanpa group")
                opened = max(0, opened - 1)
            elif "from" in m:
                if len(str(m.get("label", ""))) > 60:
                    warnings.append(f"{path}.messages[{k}] label > 60 karakter; ringkas")
            elif "note" not in m and "else" not in m:
                errors.append(f"{path}.messages[{k}] tidak dikenal (pakai from/to, note, group, else, end)")
        if opened:
            warnings.append(f"{path}: {opened} group belum ditutup dengan " + '{"end": true}')
        _colors(msgs, f"{path}.messages", errors)
    elif typ == "compare":
        panels = spec.get("panels", spec.get("items"))
        if not isinstance(panels, list) or not panels:
            errors.append(f"{path}.panels kosong (2-4 panel {{title, visual, caption, verdict}})")
            return
        if depth > 0:
            errors.append(f"{path}: compare di dalam compare tidak didukung")
            return
        if len(panels) < 2:
            warnings.append(f"{path}: perbandingan butuh minimal 2 panel")
        if len(panels) > 4:
            warnings.append(f"{path}: hanya 4 panel pertama yang digambar")
        for k, p in enumerate(panels[:4]):
            if not isinstance(p, dict):
                errors.append(f"{path}.panels[{k}] harus objek")
                continue
            _check_spec(p.get("visual", p.get("spec")), f"{path}.panels[{k}].visual", errors, warnings, depth + 1)
            if not p.get("caption"):
                warnings.append(f"{path}.panels[{k}] tanpa caption; tulis alasan singkat (✓ ... / ✗ ...)")
            verdict = str(p.get("verdict", "")).lower()
            if verdict and verdict not in GOOD | BAD:
                warnings.append(f"{path}.panels[{k}].verdict '{verdict}' tidak dikenal; pakai good atau bad")


def _num(v: str | None) -> float | None:
    try:
        return float(re.sub(r"[a-z%]+$", "", (v or "").strip(), flags=re.I))
    except ValueError:
        return None


def _check_svg(body: str, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if re.search(r"<!ENTITY", body, re.I):
        errors.append("SVG memakai <!ENTITY>; tidak diizinkan")
        return info
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        errors.append(f"SVG bukan XML yang valid: {e}")
        return info
    tag = lambda el: el.tag.rsplit("}", 1)[-1].lower()  # noqa: E731
    if tag(root) != "svg":
        errors.append("elemen akar harus <svg>")
        return info
    vb = [_num(x) for x in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if x]
    w, h = _num(root.get("width")), _num(root.get("height"))
    if len(vb) == 4 and all(v is not None for v in vb) and vb[2] and vb[3] and vb[2] > 0 and vb[3] > 0:  # type: ignore[operator]
        box = (vb[0], vb[1], vb[2], vb[3])
    elif w and h and "%" not in (root.get("width") or ""):
        box = (0.0, 0.0, w, h)
        warnings.append("tambahkan viewBox supaya gambar tajam di semua ukuran")
    else:
        errors.append("SVG butuh viewBox (mis. viewBox=\"0 0 520 240\")")
        return info
    info["size"] = (box[2], box[3])
    if box[2] > 1400 or box[3] > 1400:
        warnings.append(f"viewBox {box[2]:g}×{box[3]:g} besar; teks akan mengecil di HP. Usahakan lebar ≤ 720")
    elif box[2] > 480:
        pct = round(360 / box[2] * 100)
        warnings.append(f"viewBox lebar {box[2]:g}: di HP (~360px) teks mengecil jadi ~{pct}%. Usahakan lebar ≤ 420, atau pakai spec")
    els = list(root.iter())
    if len(els) > 2500:
        warnings.append(f"{len(els)} elemen; terlalu rumit untuk kartu chat")
    seen_text: set[tuple[int, int]] = set()
    for el in els:
        t = tag(el)
        if t in FORBIDDEN_TAGS:
            errors.append(f"<{t}> akan dibuang sanitizer (tidak boleh di visual)")
        for k, v in el.attrib.items():
            name = k.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                errors.append(f"atribut {name} di <{t}> akan dibuang (tanpa skrip)")
            if name in ("href", "src") and not (v.startswith("#") or re.match(r"data:image/(png|jpe?g|gif|webp);", v)):
                errors.append(f"tautan {name}=\"{v[:40]}\" di <{t}> akan dibuang (hanya #id atau data:image)")
            if name == "style" and EXTERNAL_URL.search(v):
                errors.append(f"style di <{t}> memuat url() eksternal; tidak akan dimuat")
        if t == "style" and el.text and (EXTERNAL_URL.search(el.text) or "@import" in el.text):
            errors.append("<style> memuat @import/url() eksternal; tidak akan dimuat")
        if t == "text":
            fs = _num(el.get("font-size"))
            if fs is not None and fs < 10:
                warnings.append(f"teks \"{(el.text or '').strip()[:20]}\" font-size {fs:g} terlalu kecil (min 11)")
            x, y = _num(el.get("x")), _num(el.get("y"))
            if x is not None and y is not None:
                if not (box[0] - 1 <= x <= box[0] + box[2] + 1 and box[1] - 1 <= y <= box[1] + box[3] + 1):
                    warnings.append(f"teks \"{(el.text or '').strip()[:20]}\" di ({x:g},{y:g}) di luar viewBox")
                key = (round(x), round(y))
                if key in seen_text:
                    warnings.append(f"dua teks di posisi sama ({x:g},{y:g}); label bisa bertumpuk")
                seen_text.add(key)
    return info


def _check_html(body: str, errors: list[str], warnings: list[str]) -> None:
    low = body.lower()
    for t in ("script", "iframe", "object", "embed", "form", "input", "link", "meta", "base"):
        if re.search(rf"<{t}\b", low):
            errors.append(f"<{t}> akan dibuang sanitizer (HTML visual tanpa skrip/form/embed)")
    if re.search(r"\son\w+\s*=", low):
        errors.append("atribut on…= (event handler) akan dibuang")
    if "javascript:" in low:
        errors.append("tautan javascript: tidak diizinkan")
    if re.search(r"(?:src|href)\s*=\s*['\"]?https?:", low) or EXTERNAL_URL.search(body) or "@import" in low:
        errors.append("sumber eksternal (http/url()/@import) tidak dimuat; visual harus mandiri")
    if len(body) > 40_000:
        warnings.append("HTML panjang; kartu chat sebaiknya ringkas")


def check_visual(code: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    code = str(code or "")
    fence = re.match(r"^\s*```\s*visual\s*\n([\s\S]*?)\n?```\s*$", code)
    if fence:
        code = fence.group(1)
    if len(code) > MAX_CHARS:
        return {"ok": False, "kind": None, "errors": [f"terlalu besar ({len(code)} karakter, maks {MAX_CHARS})"], "warnings": []}
    body, title, caption = _strip_header(code)
    if not body:
        return {"ok": False, "kind": None, "errors": ["blok kosong"], "warnings": []}
    kind = "spec" if body.startswith("{") else "svg"
    head = re.sub(r"^(<\?xml[^>]*\?>\s*|<!--[\s\S]*?-->\s*|<!DOCTYPE[^>]*>\s*)+", "", body, flags=re.I)
    info: dict[str, Any] = {}
    if body.startswith("{"):
        try:
            spec = lenient_json(body)
        except ValueError as e:
            return {"ok": False, "kind": "spec", "errors": [f"JSON tidak valid: {e}"], "warnings": []}
        if isinstance(spec, dict):
            title = spec.get("title", title) if isinstance(spec.get("title", title), str) else title
            caption = spec.get("caption", caption) if isinstance(spec.get("caption", caption), str) else caption
            info["type"] = ALIASES.get(str(spec.get("type", "")).lower(), str(spec.get("type", "")).lower())
        _check_spec(spec, "spec", errors, warnings)
    elif head.startswith("<svg"):
        info = _check_svg(head, errors, warnings)
    elif head.startswith("<"):
        kind = "html"
        _check_html(head, errors, warnings)
    else:
        return {"ok": False, "kind": None, "errors": ["format tidak dikenal: mulai dengan { (spec JSON), <svg, atau HTML"], "warnings": []}
    if not title:
        warnings.append("tanpa judul: tambahkan \"title\" (spec) atau baris title: (SVG/HTML)")
    if not caption:
        warnings.append("tanpa caption: satu kalimat apa yang harus dilihat pembaca")
    return {"ok": not errors, "kind": kind, "title": title, "caption": caption, "errors": errors,
            "warnings": warnings, **info}


def format_report(res: dict[str, Any]) -> str:
    head = "OK: visual siap dikirim" if res["ok"] else "GAGAL: perbaiki sebelum dikirim"
    parts = [f"{head} ({res.get('kind') or '?'}{', ' + res['type'] if res.get('type') else ''})"]
    parts += [f"- error: {e}" for e in res["errors"][:20]]
    parts += [f"- saran: {w}" for w in res["warnings"][:12]]
    if res["ok"]:
        parts.append("Kirim sebagai blok ```visual di jawaban (bukan file).")
    return "\n".join(parts)
