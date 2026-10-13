"""Mode Desain: the OpenDesign-style design workflow, native in the Neovarch core.

Flow (adapted from nexu-io/open-design, Apache-2.0; no Node daemon is bundled):
brief → template (landing, dashboard, deck, mobile, …) → lock a direction (one of five
curated directions, a bundled design system, or a brand imported from a URL/screenshot)
→ design system (DESIGN.md + tokens.css + tokens.json) → single-file HTML artifact with a
preview → self-critique on five dimensions + tweaks → handoff "Pakai untuk coding" →
remembered design preferences.

The design system lives in the user's project under ``.neovarch/design/``:

* ``DESIGN.md``    the prose contract (9-section OpenDesign shape)
* ``tokens.css``   ``:root { --bg: …; --accent: …; }`` with the shared token names
* ``tokens.json``  ``{"version": 1, "source": …, "tokens": {"--bg": "#…", …}, "inject": true}``
* ``artifacts/``   the HTML artifacts made in Mode Desain
* ``critique.json`` the self-critique history

While a design system is present (and not switched off with the handoff), :func:`prompt_section`
puts it in the main agent's system prompt, so every React/Vue/HTML/Flutter change uses the
tokens; :func:`check` finds hard-coded colours and fonts that drift from them.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from neovarch.skillpack import PACK_DIR

KIT = PACK_DIR / "desain"
UPSTREAM = KIT / "upstream"
DESIGN_SUBDIR = Path(".neovarch") / "design"
PREFS_NOTE = "desain-preferensi"

# The shared semantic token contract (OpenDesign craft/color.md + tokens.css).
COLOR_TOKENS = ("--bg", "--surface", "--surface-warm", "--fg", "--fg-2", "--muted", "--meta", "--border",
                "--border-soft", "--accent", "--accent-on", "--accent-hover", "--accent-active",
                "--success", "--warn", "--danger")
FONT_TOKENS = ("--font-display", "--font-body", "--font-mono")
REQUIRED_TOKENS = ("--bg", "--surface", "--fg", "--muted", "--border", "--accent", "--font-display", "--font-body")

# Neutral defaults for everything a direction does not set (OpenDesign design-systems/default/tokens.css).
BASE_TOKENS: dict[str, str] = {
    "--success": "#17a34a", "--warn": "#eab308", "--danger": "#dc2626", "--accent-on": "#ffffff",
    "--font-mono": "ui-monospace, 'JetBrains Mono', Menlo, monospace",
    "--text-xs": "12px", "--text-sm": "14px", "--text-base": "16px", "--text-lg": "20px", "--text-xl": "24px",
    "--text-2xl": "32px", "--text-3xl": "48px", "--text-4xl": "64px",
    "--leading-body": "1.5", "--leading-tight": "1.2", "--tracking-display": "-0.01em",
    "--space-1": "4px", "--space-2": "8px", "--space-3": "12px", "--space-4": "16px", "--space-5": "20px",
    "--space-6": "24px", "--space-8": "32px", "--space-12": "48px", "--space-20": "80px",
    "--radius-sm": "6px", "--radius-md": "8px", "--radius-lg": "12px", "--radius-pill": "9999px",
    "--elev-flat": "none", "--elev-raised": "0 2px 8px rgba(17, 17, 17, 0.08)",
    "--motion-fast": "120ms", "--motion-base": "200ms", "--ease-standard": "cubic-bezier(0.2, 0, 0, 1)",
    "--container-max": "1200px",
}

# Template ids grouped by what the user asks for (the "pilih template/plugin" step).
TEMPLATE_GROUPS: dict[str, tuple[str, ...]] = {
    "landing": ("saas-landing", "waitlist-page", "pricing-page"),
    "dashboard": ("dashboard",),
    "deck": ("simple-deck",),
    "mobile": ("mobile-app", "mobile-onboarding"),
    "docs": ("docs-page", "blog-post"),
    "prototype": ("web-prototype",),
}

# Self-critique (OpenDesign discovery prompt, step 8): 1-5 each, anything under 3 is a regression.
CRITIQUE_DIMS: dict[str, str] = {
    "philosophy": "Filosofi: apakah gaya visual sesuai arah yang dikunci (editorial/minimal/brutalist…), "
                  "bukan kembali ke gaya default favoritmu?",
    "hierarchy": "Hierarki: mata langsung jatuh ke satu titik per layar, atau semua berebut perhatian?",
    "execution": "Eksekusi: tipografi, jarak, perataan, kontras benar-benar tepat, bukan cuma mendekati?",
    "specificity": "Spesifik: setiap kata, angka, gambar khusus untuk brief ini, bukan isian generik?",
    "restraint": "Menahan diri: satu aksen dipakai paling banyak dua kali, satu flourish yang tegas?",
}

# Default Tailwind indigo/violet used as the accent: the textbook "AI slop" tell (craft/anti-ai-slop.md).
AI_INDIGO = {"#6366f1", "#4f46e5", "#4338ca", "#3730a3", "#8b5cf6", "#7c3aed", "#a855f7"}

CODE_EXTS = {".css", ".scss", ".sass", ".less", ".html", ".htm", ".vue", ".svelte", ".jsx", ".tsx", ".js",
             ".ts", ".mjs", ".dart"}
SKIP_DIRS = {".git", "node_modules", "build", "dist", ".dart_tool", ".next", ".nuxt", "out", "coverage",
             ".venv", "venv", "__pycache__", ".neovarch", "vendor", "Pods", ".gradle", ".idea", "target"}
GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif",
                 "ui-serif", "ui-monospace", "ui-rounded", "-apple-system", "blinkmacsystemfont", "inherit",
                 "initial", "unset", "emoji", "math", "fangsong", "revert"}


class DesignError(ValueError):
    pass


# ------------------------------------------------------------------ paths ----

def project_root(cwd: Path | str) -> Path:
    """The git root above ``cwd`` (the project), else ``cwd`` itself."""
    cwd = Path(cwd).expanduser().resolve()
    for p in (cwd, *cwd.parents):
        if (p / ".git").exists():
            return p
    return cwd


def design_dir(cwd: Path | str) -> Path:
    return project_root(cwd) / DESIGN_SUBDIR


def slugify(text: str, default: str = "desain") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s[:48].strip("-") or default)


# ---------------------------------------------------------------- catalog ----

@lru_cache(maxsize=1)
def directions() -> list[dict[str, Any]]:
    """The five curated directions (adapted from OpenDesign's direction library)."""
    return json.loads((KIT / "directions.json").read_text(encoding="utf-8"))["directions"]


def direction(did: str) -> dict[str, Any] | None:
    did = str(did or "").strip().lower()
    return next((d for d in directions() if d["id"] == did or d["id"].split("-")[0] == did), None)


@lru_cache(maxsize=1)
def systems() -> list[dict[str, Any]]:
    """Bundled DESIGN.md systems (curated OpenDesign subset)."""
    out = []
    root = UPSTREAM / "design-systems"
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        md = d / "DESIGN.md"
        if not md.is_file():
            continue
        meta: dict[str, Any] = {}
        try:
            meta = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        text = md.read_text(encoding="utf-8", errors="replace")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), d.name)
        desc = str(meta.get("description") or "")
        if not desc or desc.startswith("Bundled OpenDesign package"):
            quote = [ln.lstrip("> ").strip() for ln in text.splitlines()[1:12] if ln.startswith(">")]
            desc = " ".join(q for q in quote if not q.lower().startswith("category"))[:220]
        out.append({"id": d.name, "name": str(meta.get("name") or title), "category": str(meta.get("category") or ""),
                    "description": desc})
    return out


def system_path(sid: str) -> Path:
    sid = slugify(sid, "")
    d = UPSTREAM / "design-systems" / sid
    if not sid or not (d / "DESIGN.md").is_file():
        raise DesignError(f"design system tidak dikenal: {sid or '(kosong)'}; lihat design action=catalog")
    return d


def _frontmatter_desc(text: str) -> str:
    m = re.search(r"^description:\s*(\|?)\s*\n?((?:[ \t]+.*\n)+|.*)", text, re.M)
    if not m:
        return ""
    return " ".join(ln.strip() for ln in m.group(2).splitlines() if ln.strip())[:260]


@lru_cache(maxsize=1)
def templates() -> list[dict[str, Any]]:
    out = []
    root = UPSTREAM / "templates"
    group_of = {t: g for g, ids in TEMPLATE_GROUPS.items() for t in ids}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        out.append({"id": d.name, "group": group_of.get(d.name, "proses"), "description": _frontmatter_desc(text),
                    "example": str(d / "example.html") if (d / "example.html").is_file() else ""})
    return out


def template_path(tid: str) -> Path:
    tid = slugify(tid, "")
    if tid in TEMPLATE_GROUPS:
        tid = TEMPLATE_GROUPS[tid][0]
    d = UPSTREAM / "templates" / tid
    if not tid or not (d / "SKILL.md").is_file():
        raise DesignError(f"template tidak dikenal: {tid or '(kosong)'}; lihat design action=catalog")
    return d


# ----------------------------------------------------------------- colour ----

_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
_FUNC = re.compile(r"\b(rgba?|hsla?|oklch)\(\s*([^)]*)\)", re.I)
_DART = re.compile(r"\bColor\(\s*0x([0-9a-fA-F]{8})\s*\)")


def _num(tok: str, scale: float = 1.0) -> float:
    tok = tok.strip()
    if tok.endswith("%"):
        return float(tok[:-1]) / 100.0 * scale
    return float(tok)


def _oklch_to_rgb(L: float, C: float, H: float) -> tuple[int, int, int]:
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def gamma(x: float) -> int:
        x = min(1.0, max(0.0, x))
        v = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
        return int(round(v * 255))
    return gamma(lin[0]), gamma(lin[1]), gamma(lin[2])


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    import colorsys
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l, s)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def parse_color(value: str) -> tuple[int, int, int] | None:
    """#rgb / #rrggbb(aa) / rgb() / hsl() / oklch() / Flutter Color(0xAARRGGBB) → (r, g, b)."""
    v = str(value or "").strip()
    m = _DART.search(v)
    if m:
        h = m.group(1)
        return int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    m = _HEX.fullmatch(v) or _HEX.match(v)
    if m:
        h = m.group(0)[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = _FUNC.match(v)
    if not m:
        return None
    kind, raw = m.group(1).lower(), m.group(2)
    parts = [p for p in re.split(r"[\s,/]+", raw.strip()) if p]
    try:
        if kind.startswith("rgb") and len(parts) >= 3:
            return tuple(int(round(min(255.0, max(0.0, _num(p, 255.0))))) for p in parts[:3])  # type: ignore[return-value]
        if kind.startswith("hsl") and len(parts) >= 3:
            return _hsl_to_rgb(float(parts[0].rstrip("deg")), _num(parts[1]), _num(parts[2]))
        if kind == "oklch" and len(parts) >= 3:
            L = _num(parts[0]) if parts[0].endswith("%") else float(parts[0])
            return _oklch_to_rgb(L, float(parts[1]), float(parts[2].rstrip("deg")))
    except (ValueError, OverflowError):
        return None
    return None


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def lin(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _lab(a), _lab(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def _luma(rgb: tuple[int, int, int]) -> float:
    return _lab(rgb)[0]


def _chroma(rgb: tuple[int, int, int]) -> float:
    _, a, b = _lab(rgb)
    return math.hypot(a, b)


# ----------------------------------------------------------------- tokens ----

def parse_css_vars(css: str) -> dict[str, str]:
    """Custom properties declared in ``:root`` blocks (first value wins), in source order."""
    out: dict[str, str] = {}
    for block in re.finditer(r":root[^{]*\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)):
        for m in re.finditer(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);", block.group(1)):
            out.setdefault(m.group(1), " ".join(m.group(2).split()))
    return out


def tokens_css(tokens: dict[str, str], title: str = "") -> str:
    head = ("/* tokens.css - Neovarch Mode Desain" + (f" · {title}" if title else "") + "\n"
            " * Salin blok :root ini ke <style> pertama setiap artifact, lalu pakai var(--nama). */\n")
    body = "\n".join(f"  {k}: {v};" for k, v in tokens.items())
    return f"{head}:root {{\n{body}\n}}\n"


def _first_family(stack: str) -> str:
    for part in str(stack or "").split(","):
        name = part.strip().strip("'\"").strip()
        if name and name.lower() not in GENERIC_FONTS and not name.lower().startswith("var("):
            return name
    return ""


def resolve(tokens: dict[str, str], value: str, depth: int = 0) -> str:
    m = re.fullmatch(r"var\((--[A-Za-z0-9_-]+)(?:\s*,\s*([^)]*))?\)", str(value or "").strip())
    if not m or depth > 6:
        return value
    return resolve(tokens, tokens.get(m.group(1), m.group(2) or ""), depth + 1)


def palette(tokens: dict[str, str]) -> dict[str, tuple[int, int, int]]:
    """Every token that resolves to a plain colour, by name."""
    out = {}
    for k, v in tokens.items():
        rgb = parse_color(resolve(tokens, v))
        if rgb is not None:
            out[k] = rgb
    return out


def font_families(tokens: dict[str, str]) -> set[str]:
    fams = set()
    for k, v in tokens.items():
        if k.startswith("--font"):
            for part in resolve(tokens, v).split(","):
                name = part.strip().strip("'\"").strip().lower()
                if name:
                    fams.add(name)
    return fams


def direction_tokens(d: dict[str, Any]) -> dict[str, str]:
    p = d["palette"]
    toks = {"--bg": p["bg"], "--surface": p["surface"], "--fg": p["fg"], "--muted": p["muted"],
            "--border": p["border"], "--accent": p["accent"],
            "--accent-hover": "color-mix(in oklab, var(--accent), black 8%)",
            "--font-display": d["displayFont"], "--font-body": d["bodyFont"]}
    if d.get("monoFont"):
        toks["--font-mono"] = d["monoFont"]
    accent = parse_color(p["accent"])
    if accent is not None and _luma(accent) > 70:
        toks["--accent-on"] = "#111111"
    return {**toks, **{k: v for k, v in BASE_TOKENS.items() if k not in toks}}


def direction_design_md(d: dict[str, Any], name: str = "", brief: str = "") -> str:
    p = d["palette"]
    lines = [f"# {name or d['label']}", "",
             f"> Arah: {d['label']} (Mode Desain Neovarch, diadaptasi dari OpenDesign).",
             *([f"> Brief: {brief.strip()}"] if brief.strip() else []), "",
             "## Visual Theme & Atmosphere", d["mood"], "", "Referensi: " + ", ".join(d["references"]), "",
             "## Color Palette & Roles",
             f"- **Background (--bg):** `{p['bg']}`", f"- **Surface (--surface):** `{p['surface']}` (kartu, modal)",
             f"- **Foreground (--fg):** `{p['fg']}`", f"- **Muted (--muted):** `{p['muted']}` (teks sekunder)",
             f"- **Border (--border):** `{p['border']}`",
             f"- **Accent (--accent):** `{p['accent']}` (CTA utama, maksimal dua kali per layar)",
             "- Status: --success / --warn / --danger dari tokens.css.", "",
             "## Typography Rules", f"- **Display:** `{d['displayFont']}`", f"- **Body:** `{d['bodyFont']}`",
             *([f"- **Mono:** `{d['monoFont']}`"] if d.get("monoFont") else []),
             "- Skala (px): 12 · 14 · 16 · 20 · 24 · 32 · 48 · 64; line-height body 1.5, heading 1.2.", "",
             "## Layout Principles", *[f"- {x}" for x in d["posture"]], "",
             "## Component Stylings",
             "- Tombol, input, kartu memakai var(--radius-*) dan var(--border); fokus selalu terlihat (--focus-ring).", "",
             "## Depth & Elevation", "- Datar secara default; elevasi hanya untuk dropdown/modal (var(--elev-raised)).", "",
             "## Do's and Don'ts", "- ✅ Semua warna lewat var(--…); tidak ada hex mentah di komponen.",
             "- ✅ Satu aksen, satu titik fokus per layar.",
             "- ❌ Tidak ada indigo Tailwind default, emoji sebagai ikon, atau isian generik.", "",
             "## Responsive Behavior", "- Mobile-first; breakpoint 640 / 1024 / 1280; tidak ada scroll horizontal.", "",
             "## Agent Prompt Guide", "- Saat ragu, kurangi. Pakai token, bukan nilai baru."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ store ----

def load(cwd: Path | str) -> dict[str, Any] | None:
    """The project's design system, or None when the project has none."""
    d = design_dir(cwd)
    tj = d / "tokens.json"
    md = d / "DESIGN.md"
    if not tj.is_file() and not md.is_file():
        return None
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(tj.read_text(encoding="utf-8")) if tj.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    tokens = dict(meta.get("tokens") or {})
    if not tokens and (d / "tokens.css").is_file():
        tokens = parse_css_vars((d / "tokens.css").read_text(encoding="utf-8", errors="replace"))
    return {"dir": d, "design_md": md.read_text(encoding="utf-8", errors="replace") if md.is_file() else "",
            "tokens": tokens, "meta": {k: v for k, v in meta.items() if k != "tokens"}}


def save(cwd: Path | str, design_md: str, tokens: dict[str, str], source: str = "", name: str = "",
         extra: dict[str, Any] | None = None) -> dict[str, Path]:
    """Write DESIGN.md + tokens.css + tokens.json under the project's .neovarch/design/."""
    tokens = {str(k) if str(k).startswith("--") else "--" + str(k): " ".join(str(v).split())
              for k, v in (tokens or {}).items() if str(v).strip()}
    missing = [t for t in REQUIRED_TOKENS if t not in tokens]
    if missing:
        raise DesignError("token wajib belum ada: " + ", ".join(missing))
    bad = [k for k in COLOR_TOKENS if k in tokens and parse_color(resolve(tokens, tokens[k])) is None
           and not tokens[k].startswith(("color-mix", "var(", "transparent", "currentcolor"))]
    if bad:
        raise DesignError("nilai warna tidak terbaca: " + ", ".join(f"{k}={tokens[k]}" for k in bad))
    if not str(design_md or "").strip():
        raise DesignError("DESIGN.md kosong")
    d = design_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    prev = load(cwd)
    meta = {"version": 1, "name": name or (prev or {}).get("meta", {}).get("name", ""), "source": source,
            "updated": _dt.datetime.now().isoformat(timespec="seconds"),
            "inject": bool((prev or {}).get("meta", {}).get("inject", True)), **(extra or {}), "tokens": tokens}
    paths = {"design": d / "DESIGN.md", "css": d / "tokens.css", "json": d / "tokens.json"}
    paths["design"].write_text(design_md.rstrip() + "\n", encoding="utf-8")
    paths["css"].write_text(tokens_css(tokens, meta["name"]), encoding="utf-8")
    paths["json"].write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    gi = d.parent / ".gitignore"
    if not gi.exists():  # keep the design system in git, but not throwaway screenshots
        gi.write_text("design/shots/\n", encoding="utf-8")
    return paths


def use_direction(cwd: Path | str, did: str, brief: str = "", name: str = "",
                  overrides: dict[str, str] | None = None) -> dict[str, Path]:
    d = direction(did)
    if d is None:
        raise DesignError(f"arah tidak dikenal: {did}; pilih salah satu: " + ", ".join(x["id"] for x in directions()))
    toks = {**direction_tokens(d), **(overrides or {})}
    return save(cwd, direction_design_md(d, name, brief), toks, source=f"direction:{d['id']}", name=name or d["label"])


def use_system(cwd: Path | str, sid: str, name: str = "", overrides: dict[str, str] | None = None) -> dict[str, Path]:
    src = system_path(sid)
    toks = parse_css_vars((src / "tokens.css").read_text(encoding="utf-8", errors="replace")) \
        if (src / "tokens.css").is_file() else {}
    toks = {**BASE_TOKENS, **toks, **(overrides or {})}
    md = (src / "DESIGN.md").read_text(encoding="utf-8", errors="replace")
    attribution = (f"\n\n---\nSumber: design system `{src.name}` dari nexu-io/open-design (Apache-2.0), "
                   "lihat THIRD_PARTY_SKILLS.md. Nama merek hanya acuan gaya; jangan pakai logo/aset merek itu.\n")
    return save(cwd, md.rstrip() + attribution, toks, source=f"system:{src.name}", name=name or src.name)


def set_inject(cwd: Path | str, on: bool) -> bool:
    d = design_dir(cwd) / "tokens.json"
    if not d.is_file():
        raise DesignError("proyek ini belum punya design system (.neovarch/design/tokens.json)")
    meta = json.loads(d.read_text(encoding="utf-8"))
    meta["inject"] = bool(on)
    d.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return bool(on)


# ----------------------------------------------------------- brand import ----

_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""(\w[\w-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_FONT_DECL = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_COLOR_DECL = re.compile(r"(?:^|[;{\s])(--[\w-]+|color|background(?:-color)?|border(?:-color)?|fill|stroke)\s*:\s*([^;}{]+)",
                         re.I)


def _attrs(tag: str) -> dict[str, str]:
    return {k.lower(): v.strip("'\"") for k, v in _ATTR.findall(tag)}


def stylesheet_links(html: str) -> list[str]:
    out = []
    for tag in _LINK.findall(html or ""):
        a = _attrs(tag)
        if "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            out.append(a["href"])
    return out


def analyze_brand(html: str, css_texts: list[str] | None = None, url: str = "") -> dict[str, Any]:
    """Draft tokens from a page's HTML + CSS: colours by role and frequency, fonts, theme-color."""
    css = "\n".join(_STYLE.findall(html or "")) + "\n" + "\n".join(css_texts or [])
    inline = " ".join(re.findall(r'style\s*=\s*"([^"]*)"', html or "", re.I))
    css_all = re.sub(r"/\*.*?\*/", "", css + "\n" + inline, flags=re.S)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    title = " ".join(title_m.group(1).split())[:80] if title_m else ""
    theme = ""
    for tag in re.findall(r"<meta\b[^>]*>", html or "", re.I):
        a = _attrs(tag)
        if a.get("name", "").lower() == "theme-color" and a.get("content"):
            theme = a["content"]
    vars_ = parse_css_vars(css_all)
    counts: dict[str, int] = {}
    roles: dict[str, dict[str, int]] = {"bg": {}, "fg": {}, "accent": {}}
    for prop, raw in _COLOR_DECL.findall(css_all):
        prop = prop.lower()
        for tok in re.findall(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch)\([^)]*\)", raw):
            rgb = parse_color(tok)
            if rgb is None:
                continue
            hx = to_hex(rgb)
            counts[hx] = counts.get(hx, 0) + 1
            role = ("bg" if "background" in prop or re.search(r"bg|background|surface", prop) else
                    "fg" if prop == "color" or re.search(r"text|fg|foreground|ink", prop) else
                    "accent" if re.search(r"accent|brand|primary|link|cta", prop) else "")
            if role:
                roles[role][hx] = roles[role].get(hx, 0) + 1
    fonts: dict[str, int] = {}
    for stack in _FONT_DECL.findall(css_all) + [v for k, v in vars_.items() if "font" in k.lower()]:
        fam = _first_family(stack)
        if fam:
            fonts[fam] = fonts.get(fam, 0) + 1

    def top(d: dict[str, int], pred=lambda rgb: True) -> str:
        for hx, _ in sorted(d.items(), key=lambda kv: -kv[1]):
            rgb = parse_color(hx)
            if rgb is not None and pred(rgb):
                return hx
        return ""
    light = lambda rgb: _luma(rgb) >= 88  # noqa: E731
    dark = lambda rgb: _luma(rgb) <= 30  # noqa: E731
    vivid = lambda rgb: _chroma(rgb) >= 28 and 25 <= _luma(rgb) <= 85  # noqa: E731
    bg = top(roles["bg"], light) or top(roles["bg"], dark) or top(counts, light) or "#ffffff"
    bg_rgb = parse_color(bg) or (255, 255, 255)
    is_dark = _luma(bg_rgb) < 50
    fg = (top(roles["fg"], light if is_dark else dark) or top(counts, light if is_dark else dark)
          or ("#f5f5f5" if is_dark else "#111111"))
    accent = (to_hex(parse_color(theme)) if parse_color(theme) and vivid(parse_color(theme)) else "") \
        or top(roles["accent"], vivid) or top(counts, vivid) or ("#e0262f" if is_dark else "#2f6feb")
    fg_rgb = parse_color(fg) or (17, 17, 17)
    mix = lambda a, b, t: to_hex(tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b)))  # noqa: E731
    fam = [f for f, _ in sorted(fonts.items(), key=lambda kv: -kv[1])]
    display = fam[0] if fam else ""
    body = fam[1] if len(fam) > 1 else display
    stack = lambda f: (f"'{f}', " if f else "") + "system-ui, -apple-system, 'Segoe UI', sans-serif"  # noqa: E731
    tokens = {"--bg": bg, "--surface": mix(bg_rgb, fg_rgb, 0.04), "--fg": fg, "--muted": mix(fg_rgb, bg_rgb, 0.45),
              "--border": mix(bg_rgb, fg_rgb, 0.14), "--accent": accent,
              "--font-display": stack(display), "--font-body": stack(body)}
    accent_rgb = parse_color(accent)
    if accent_rgb is not None and _luma(accent_rgb) > 70:
        tokens["--accent-on"] = "#111111"
    return {"url": url, "title": title, "theme_color": theme, "dark": is_dark,
            "colors": [hx for hx, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:12]],
            "fonts": fam[:6], "css_vars": {k: v for k, v in list(vars_.items())[:40]},
            "tokens": {**tokens, **{k: v for k, v in BASE_TOKENS.items() if k not in tokens}}}


async def fetch_brand(url: str, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch a page (and up to 4 linked stylesheets) and :func:`analyze_brand` it."""
    import aiohttp
    from urllib.parse import urljoin
    if not re.match(r"^https?://", url or "", re.I):
        raise DesignError("URL harus diawali http:// atau https://")
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NeovarchDesign/1.0"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers=headers) as s:
        async with s.get(url) as r:
            html = (await r.content.read(1_500_000)).decode(r.charset or "utf-8", errors="replace")
        css = []
        for href in stylesheet_links(html)[:4]:
            try:
                async with s.get(urljoin(str(url), href)) as r:
                    if r.status == 200:
                        css.append((await r.content.read(1_000_000)).decode("utf-8", errors="replace"))
            except Exception:  # one broken stylesheet must not lose the rest
                continue
    return analyze_brand(html, css, url)


def brand_from_image(path: Path | str, colors: int = 6) -> dict[str, Any]:
    """Dominant colours of a screenshot (needs Pillow; otherwise the agent reads it with vision)."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DesignError("Pillow tidak terpasang: baca screenshot dengan alat image_ask (warna, font, gaya), "
                          "lalu simpan tokennya dengan design action=save_system.") from exc
    img = Image.open(path).convert("RGB")
    img.thumbnail((240, 240))
    q = img.quantize(colors=max(2, min(12, colors)))
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    found = [to_hex(tuple(pal[i * 3:i * 3 + 3])) for _, i in counts]  # type: ignore[arg-type]
    fake_css = ":root{" + "".join(f"--c{i}:{c};" for i, c in enumerate(found)) + "}" \
        + "".join(f"body{{background:{found[0]}}}" for _ in [0]) if found else ""
    res = analyze_brand(f"<style>{fake_css}</style>", [], str(path))
    res["colors"] = found
    return res


# -------------------------------------------------------------- artifacts ----

def save_artifact(cwd: Path | str, name: str, html: str) -> Path:
    text = str(html or "")
    if not re.search(r"<html|<!doctype html", text[:2000], re.I) or "</html>" not in text[-400:].lower():
        raise DesignError("artifact harus satu dokumen HTML utuh (<!doctype html> … </html>)")
    out = design_dir(cwd) / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slugify(name)}.html"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- critique ----

def critique_rubric() -> str:
    return ("Nilai artifact 1-5 untuk tiap dimensi (jujur, jangan murah hati):\n"
            + "\n".join(f"- {k}: {v}" for k, v in CRITIQUE_DIMS.items())
            + "\nDimensi di bawah 3 = regresi: perbaiki yang paling lemah, nilai ulang (dua putaran itu normal). "
              "Simpan nilai dengan design action=critique scores={...}.")


def record_critique(cwd: Path | str, scores: dict[str, Any], notes: str = "", artifact: str = "") -> dict[str, Any]:
    clean: dict[str, int] = {}
    for k in CRITIQUE_DIMS:
        try:
            v = int(round(float((scores or {}).get(k))))
        except (TypeError, ValueError):
            raise DesignError(f"nilai '{k}' belum ada (1-5); dimensi: " + ", ".join(CRITIQUE_DIMS)) from None
        if not 1 <= v <= 5:
            raise DesignError(f"nilai '{k}' harus 1-5")
        clean[k] = v
    weak = [k for k, v in clean.items() if v < 3]
    row = {"at": _dt.datetime.now().isoformat(timespec="seconds"), "artifact": artifact, "scores": clean,
           "average": round(sum(clean.values()) / len(clean), 2), "notes": str(notes or "")[:2000], "weak": weak}
    d = design_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "critique.json"
    try:
        hist = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except (OSError, ValueError):
        hist = []
    hist = (hist if isinstance(hist, list) else [])[-19:] + [row]
    p.write_text(json.dumps(hist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return row


# ------------------------------------------------------------ preferences ----

def remember(text: str, home: Path | None = None) -> Path:
    """Append a design preference to the memory note the system prompt already carries."""
    from neovarch.config import neovarch_home
    from neovarch import selfedit
    text = " ".join(str(text or "").split())
    if not text:
        raise DesignError("preferensi kosong")
    root = (home or neovarch_home()) / "memory"
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{PREFS_NOTE}.md"
    line = f"- {_dt.date.today().isoformat()}: {text[:400]}\n"
    if p.is_file() and line.split(": ", 1)[1] in p.read_text(encoding="utf-8"):
        return p
    try:
        selfedit.memory_update("append", p.name,
                               content=("# Preferensi desain pengguna (Mode Desain)\n" if not p.is_file() else "") + line)
    except Exception:  # the versioned path is a nicety; the note itself is what matters
        with p.open("a", encoding="utf-8") as fh:
            if fh.tell() == 0:
                fh.write("# Preferensi desain pengguna (Mode Desain)\n")
            fh.write(line)
    return p


# ------------------------------------------------------------------- check ----

def _iter_files(root: Path, paths: list[str] | None, limit: int) -> list[Path]:
    picked: list[Path] = []
    targets = [root / p if not Path(p).is_absolute() else Path(p) for p in (paths or [])] or [root]
    for t in targets:
        if t.is_file():
            if t.suffix.lower() in CODE_EXTS:
                picked.append(t)
            continue
        if not t.is_dir():
            continue
        stack = [t]
        while stack and len(picked) < limit:
            d = stack.pop()
            try:
                entries = sorted(d.iterdir())
            except OSError:
                continue
            for e in entries:
                if e.is_dir():
                    if e.name not in SKIP_DIRS and not e.name.startswith("."):
                        stack.append(e)
                elif e.suffix.lower() in CODE_EXTS and not e.name.endswith((".min.js", ".min.css", ".g.dart",
                                                                          ".freezed.dart")):
                    picked.append(e)
                    if len(picked) >= limit:
                        break
    return picked[:limit]


def _nearest(rgb: tuple[int, int, int], pal: dict[str, tuple[int, int, int]]) -> tuple[str, float]:
    best, dist = "", 1e9
    for k, v in pal.items():
        d = delta_e(rgb, v)
        if d < dist:
            best, dist = k, d
    return best, dist


_COLOR_ANY = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|(?:rgba?|hsla?|oklch)\([^)]*\)"
                        r"|\bColor\(\s*0x[0-9a-fA-F]{8}\s*\)")
_FONT_USE = re.compile(r"font-family\s*:\s*([^;}\"'`]+(?:['\"][^'\"]+['\"][^;}`]*)?)|fontFamily\s*:\s*['\"]([^'\"]+)['\"]",
                       re.I)


def check(cwd: Path | str, paths: list[str] | None = None, limit_files: int = 400,
          tolerance: float = 4.0) -> dict[str, Any]:
    """Token consistency: hard-coded colours/fonts in UI code that are not the design system's tokens.

    Kinds: ``off-palette`` (colour not in the palette; nearest token suggested), ``hardcoded``
    (exact token value written as a literal: use var(--x) / the Dart token), ``off-font`` (font family
    outside the --font-* tokens), ``ai-indigo`` (default Tailwind indigo/violet). Token definitions
    (``--x: …``) and tokens.css itself are skipped."""
    ds = load(cwd)
    if ds is None:
        raise DesignError("proyek ini belum punya design system; jalankan /desain dulu")
    tokens = ds["tokens"]
    pal = palette(tokens)
    fams = font_families(tokens)
    root = project_root(cwd)
    files = _iter_files(root, paths, limit_files)
    findings: list[dict[str, Any]] = []
    for f in files:
        if f.name in ("tokens.css",) or "neovarch_tokens" in f.name:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > 400_000:
            continue
        rel = str(f.relative_to(root)) if f.is_relative_to(root) else str(f)
        for no, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith(("//", "/*", "*", "#!", "<!--")) or re.match(r"^\s*--[\w-]+\s*:", line):
                continue
            if f.suffix.lower() in (".js", ".ts", ".mjs", ".jsx", ".tsx", ".vue", ".svelte", ".html", ".htm") \
                    and re.search(r"#[0-9a-fA-F]{3,8}\b", s) and not re.search(
                        r"color|background|border|fill|stroke|shadow|style|#[0-9a-fA-F]{6}\b", s, re.I):
                continue  # "#123" in JS is more likely an id/anchor than a colour
            scan = re.sub(r"--[\w-]+\s*:\s*[^;}]*", "", line)  # custom-property definitions are tokens
            for m in _COLOR_ANY.finditer(scan):
                raw = m.group(0)
                rgb = parse_color(raw)
                if rgb is None:
                    continue
                hx = to_hex(rgb)
                if hx in AI_INDIGO:
                    findings.append({"file": rel, "line": no, "kind": "ai-indigo", "value": raw,
                                     "suggest": "--accent", "note": "indigo Tailwind default (tanda AI slop)"})
                    continue
                name, dist = _nearest(rgb, pal) if pal else ("", 1e9)
                if dist <= tolerance:
                    findings.append({"file": rel, "line": no, "kind": "hardcoded", "value": raw, "suggest": name})
                elif hx not in ("#000000", "#ffffff") or not pal:
                    findings.append({"file": rel, "line": no, "kind": "off-palette", "value": raw,
                                     "suggest": name, "delta_e": round(dist, 1)})
            for m in _FONT_USE.finditer(scan):
                stack = (m.group(1) or m.group(2) or "").strip()
                if not stack or "var(" in stack or "inherit" in stack.lower():
                    continue
                fam = _first_family(stack)
                if fam and fams and fam.lower() not in fams:
                    findings.append({"file": rel, "line": no, "kind": "off-font", "value": fam,
                                     "suggest": "--font-body / --font-display"})
    kinds: dict[str, int] = {}
    for x in findings:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    score = max(0, 100 - 5 * kinds.get("off-palette", 0) - 3 * kinds.get("off-font", 0)
                - 10 * kinds.get("ai-indigo", 0) - kinds.get("hardcoded", 0))
    return {"files_scanned": len(files), "findings": findings, "counts": kinds, "score": score,
            "ok": not any(k in kinds for k in ("off-palette", "off-font", "ai-indigo"))}


def format_check(res: dict[str, Any], limit: int = 40) -> str:
    c = res["counts"]
    head = (f"Cek konsistensi token: {res['files_scanned']} file, skor {res['score']}/100 — "
            f"{c.get('off-palette', 0)} warna di luar palet, {c.get('off-font', 0)} font di luar token, "
            f"{c.get('ai-indigo', 0)} indigo default, {c.get('hardcoded', 0)} nilai token ditulis mentah.")
    if not res["findings"]:
        return head + "\nSemua warna dan font memakai token. ✅"
    order = {"ai-indigo": 0, "off-palette": 1, "off-font": 2, "hardcoded": 3}
    rows = sorted(res["findings"], key=lambda x: (order.get(x["kind"], 9), x["file"], x["line"]))[:limit]
    lines = [head]
    for x in rows:
        tip = f" → pakai var({x['suggest']})" if x.get("suggest", "").startswith("--") and x["kind"] != "off-font" \
            else (f" → {x['suggest']}" if x.get("suggest") else "")
        extra = f" (ΔE {x['delta_e']})" if "delta_e" in x else ""
        lines.append(f"- {x['file']}:{x['line']} [{x['kind']}] {x['value']}{extra}{tip}")
    if len(res["findings"]) > limit:
        lines.append(f"… dan {len(res['findings']) - limit} temuan lain.")
    return "\n".join(lines)


# ------------------------------------------------------------------ export ----

def _dart_name(token: str) -> str:
    parts = token.lstrip("-").split("-")
    return parts[0] + "".join(p.title() for p in parts[1:])


def export(cwd: Path | str, fmt: str) -> Path:
    """tokens as css | json | dart (Flutter ThemeData helpers) | tailwind (v4 @theme)."""
    ds = load(cwd)
    if ds is None:
        raise DesignError("proyek ini belum punya design system")
    toks, d = ds["tokens"], ds["dir"]
    fmt = (fmt or "").lower()
    if fmt == "css":
        p = d / "tokens.css"
        p.write_text(tokens_css(toks, ds["meta"].get("name", "")), encoding="utf-8")
        return p
    if fmt == "json":
        return d / "tokens.json"
    if fmt == "tailwind":
        lines = ["/* Tailwind v4 - generated by Neovarch Mode Desain from tokens.json */", "@theme {"]
        for k, v in toks.items():
            if k in COLOR_TOKENS:
                lines.append(f"  --color{k[1:]}: {v};")
            elif k.startswith("--font"):
                lines.append(f"  {k}: {v};")
            elif k.startswith(("--radius", "--text-", "--space")):
                lines.append(f"  {k}: {v};")
        p = d / "tailwind-theme.css"
        p.write_text("\n".join(lines) + "\n}\n", encoding="utf-8")
        return p
    if fmt == "dart":
        pal = palette(toks)
        out = ["// GENERATED by Neovarch Mode Desain from .neovarch/design/tokens.json - jangan edit manual;",
               "// ubah design system lalu jalankan `design action=export format=dart` lagi.",
               "import 'package:flutter/material.dart';", "", "class NvTokens {", "  NvTokens._();"]
        for k in COLOR_TOKENS:
            if k in pal:
                out.append(f"  static const Color {_dart_name(k)} = Color(0xFF{to_hex(pal[k])[1:].upper()});")
        for k in FONT_TOKENS:
            if k in toks:
                fam = _first_family(resolve(toks, toks[k]))
                if fam:
                    out.append(f"  static const String {_dart_name(k)} = '{fam}';")
        for k, v in toks.items():
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", resolve(toks, v))
            if m and k.startswith(("--radius", "--space", "--text-")):
                out.append(f"  static const double {_dart_name(k)} = {float(m.group(1))};")
        dark = _luma(pal.get("--bg", (255, 255, 255))) < 50
        out += ["", "  static ThemeData theme() {", "    final scheme = ColorScheme.fromSeed(",
                f"      seedColor: accent, brightness: Brightness.{'dark' if dark else 'light'},",
                "    ).copyWith(primary: accent, onPrimary: " + ("accentOn" if "--accent-on" in pal else "Colors.white")
                + ", surface: " + ("surface" if "--surface" in pal else "bg") + ", onSurface: fg"
                + (", error: danger" if "--danger" in pal else "") + ");",
                "    return ThemeData(colorScheme: scheme, scaffoldBackgroundColor: bg"
                + (", fontFamily: fontBody" if "--font-body" in toks and _first_family(resolve(toks, toks['--font-body']))
                   else "") + ", useMaterial3: true);", "  }", "}"]
        p = d / "neovarch_tokens.dart"
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
        return p
    raise DesignError("format: css | json | dart | tailwind")


# ---------------------------------------------------------- prompt context ----

def prompt_section(cwd: Path | str, limit: int = 5000) -> str:
    """The project's design system for the main agent's system prompt ('' when none / switched off)."""
    try:
        ds = load(cwd)
    except Exception:  # a broken design folder must never break a turn
        return ""
    if ds is None or not ds["tokens"] or ds["meta"].get("inject") is False:
        return ""
    toks = ds["tokens"]
    key = [k for k in toks if k in COLOR_TOKENS or k in FONT_TOKENS or k.startswith("--radius")]
    tok_lines = "\n".join(f"  {k}: {toks[k]}" for k in key)
    md = ds["design_md"].strip()
    if len(md) > limit:
        md = md[:limit] + f"\n…[dipotong; baca lengkap: {ds['dir'] / 'DESIGN.md'}]"
    rel = ds["dir"]
    return (f"# Design system proyek ({rel})\n"
            "Proyek ini punya design system dari Mode Desain. Setiap kali kamu menulis atau mengubah UI "
            "(React/Next/Vue/Svelte/HTML/CSS/Tailwind/Flutter), WAJIB pakai token ini, jangan nilai baru:\n"
            f"- Web: salin/import {rel / 'tokens.css'} dan pakai var(--nama); Tailwind: design action=export "
            "format=tailwind.\n"
            "- Flutter: design action=export format=dart → NvTokens (warna, font, radius) + NvTokens.theme().\n"
            "- Sebelum menyatakan selesai, jalankan alat `design` action=check dan perbaiki temuan off-palette/"
            "off-font/ai-indigo. Untuk alur lengkap baca skill `design-to-code`.\n"
            f"Token inti:\n{tok_lines}\n\n## DESIGN.md\n{md}")


def status_text(cwd: Path | str) -> str:
    ds = load(cwd)
    if ds is None:
        return (f"Belum ada design system di {design_dir(cwd)}. Mulai dengan /desain <brief> atau "
                "design action=use_direction / use_system / import_brand.")
    m = ds["meta"]
    arts = sorted((ds["dir"] / "artifacts").glob("*.html")) if (ds["dir"] / "artifacts").is_dir() else []
    return (f"Design system: {m.get('name') or '(tanpa nama)'} · sumber {m.get('source') or '-'} · "
            f"{len(ds['tokens'])} token · disuntik ke agent coding: {'ya' if m.get('inject', True) else 'tidak'}\n"
            f"Folder: {ds['dir']}\nArtifact: " + (", ".join(a.name for a in arts[-6:]) or "-"))


def catalog_text(kind: str = "") -> str:
    out = []
    if kind in ("", "templates"):
        out.append("## Template (pilih satu; template=<id> atau grup landing|dashboard|deck|mobile|docs|prototype)")
        out += [f"- {t['id']} [{t['group']}]: {t['description'][:140]}" for t in templates()]
    if kind in ("", "directions"):
        out.append("## 5 arah kurasi (kunci arah: design action=use_direction direction=<id>)")
        out += [f"- {d['id']}: {d['label']} — {d['mood'][:150]}" for d in directions()]
    if kind in ("", "systems"):
        out.append("## Design system bawaan (design action=use_system system=<id>)")
        out += [f"- {s['id']}: {s['name']}{' · ' + s['category'] if s['category'] else ''}"
                f"{' — ' + s['description'][:110] if s['description'] else ''}" for s in systems()]
    return "\n".join(out)


# -------------------------------------------------------------------- tool ----

ACTIONS = ["status", "catalog", "template", "use_direction", "use_system", "import_brand", "save_system",
           "artifact", "critique", "check", "export", "handoff", "remember"]

SCHEMA = {
    "description": "Mode Desain (alur ala OpenDesign). action: status | catalog (kind: templates|directions|systems) | "
                   "template (id: baca SKILL.md + contoh HTML template) | use_direction (direction, name?, brief?, "
                   "overrides?) | use_system (system, overrides?) | import_brand (url ATAU image path → draft token) "
                   "| save_system (design_md, tokens{--bg,--surface,--fg,--muted,--border,--accent,--font-display,"
                   "--font-body,…}) | artifact (name, html: satu file HTML utuh; disimpan + dikirim ke chat dengan "
                   "pratinjau) | critique (scores{philosophy,hierarchy,execution,specificity,restraint} 1-5, notes) | "
                   "check (paths?: cek konsistensi token di kode) | export (format css|json|dart|tailwind) | handoff "
                   "(enable?: 'Pakai untuk coding', suntik ke agent coding) | remember (text: preferensi desain). "
                   "Disimpan di <proyek>/.neovarch/design/.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "kind": {"type": "string"}, "id": {"type": "string"}, "direction": {"type": "string"},
        "system": {"type": "string"}, "name": {"type": "string"}, "brief": {"type": "string"},
        "overrides": {"type": "object", "description": "token → nilai, mis. {\"--accent\": \"#e0262f\"}"},
        "url": {"type": "string"}, "image": {"type": "string"},
        "design_md": {"type": "string"}, "tokens": {"type": "object"},
        "html": {"type": "string"}, "scores": {"type": "object"}, "notes": {"type": "string"},
        "artifact": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}},
        "format": {"type": "string", "enum": ["css", "json", "dart", "tailwind"]},
        "enable": {"type": "boolean"}, "text": {"type": "string"},
        "send": {"type": "boolean", "description": "artifact: kirim ke chat (default true)"}},
        "required": ["action"]},
}


def _send(ctx: Any, path: Path) -> str:
    from neovarch import outbox
    from neovarch import uploads as upmod
    if getattr(ctx, "outbox", None) is None:
        return ""
    try:
        if any(m.get("source_path") == str(path) for m in ctx.outbox):
            return ""
        meta = outbox.stage(getattr(ctx, "uploads", None) or upmod.UploadStore(), getattr(ctx, "session_id", ""),
                            str(path), getattr(ctx, "cwd", path.parent))
        ctx.outbox.append(meta)
        return f"\nDikirim ke chat sebagai berkas {meta['name']} (pratinjau HTML di HP/desktop)."
    except Exception as exc:  # sending is a bonus; the file is saved either way
        return f"\n(Tidak terkirim otomatis: {exc}; pakai send_file.)"


async def tool_design(args: dict, ctx: Any) -> str:
    action = str(args.get("action") or "status")
    cwd = Path(getattr(ctx, "cwd", ".") or ".")
    try:
        if action == "status":
            return status_text(cwd)
        if action == "catalog":
            return catalog_text(str(args.get("kind") or ""))
        if action == "template":
            d = template_path(str(args.get("id") or args.get("name") or ""))
            body = (d / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            ex = d / "example.html"
            refs = sorted(str(p) for p in d.rglob("*") if p.is_file() and p.name not in ("SKILL.md",))
            return (f"TEMPLATE_DIR: {d}\nFile: " + ", ".join(refs[:12]) + "\n"
                    "Catatan: frontmatter `od:` adalah metadata OpenDesign; abaikan langkah khusus daemon `od`. "
                    "Ikat warna/font ke tokens.css proyek.\n\n" + body[:9000]
                    + (f"\n\n(Contoh lengkap: read_file {ex})" if ex.is_file() else ""))
        if action == "use_direction":
            paths = use_direction(cwd, str(args.get("direction") or args.get("id") or ""), str(args.get("brief") or ""),
                                  str(args.get("name") or ""), args.get("overrides") or None)
            return "Arah dikunci. Ditulis: " + ", ".join(str(p) for p in paths.values())
        if action == "use_system":
            paths = use_system(cwd, str(args.get("system") or args.get("id") or ""), str(args.get("name") or ""),
                               args.get("overrides") or None)
            return "Design system dipasang. Ditulis: " + ", ".join(str(p) for p in paths.values())
        if action == "import_brand":
            if args.get("url"):
                res = await fetch_brand(str(args["url"]))
            elif args.get("image"):
                p = Path(str(args["image"])).expanduser()
                res = brand_from_image(p if p.is_absolute() else cwd / p)
            else:
                raise DesignError("berikan url atau image")
            return ("Draft brand (periksa dulu, lalu simpan dengan save_system; jangan menebak bila ragu):\n"
                    + json.dumps({k: res[k] for k in ("url", "title", "theme_color", "dark", "colors", "fonts",
                                                      "tokens")}, indent=1, ensure_ascii=False)[:6000])
        if action == "save_system":
            paths = save(cwd, str(args.get("design_md") or ""), dict(args.get("tokens") or {}),
                         source=str(args.get("kind") or "custom"), name=str(args.get("name") or ""))
            return "Design system disimpan: " + ", ".join(str(p) for p in paths.values())
        if action == "artifact":
            path = save_artifact(cwd, str(args.get("name") or "artifact"), str(args.get("html") or ""))
            ds = load(cwd)
            note = ""
            if ds is not None and ds["tokens"]:
                missing = [t for t in ("--bg", "--fg", "--accent") if f"var({t})" not in str(args.get("html"))]
                if missing:
                    note = "\nPeringatan: artifact belum memakai " + ", ".join(f"var({m})" for m in missing) + "."
                indigo = [c for c in AI_INDIGO if c in str(args.get("html")).lower()]
                if indigo:
                    note += "\nPeringatan: ada indigo Tailwind default " + ", ".join(indigo) + " (ganti var(--accent))."
            sent = _send(ctx, path) if args.get("send", True) else ""
            return f"Artifact disimpan: {path}{sent}{note}\nLanjut: self-critique 5 dimensi.\n{critique_rubric()}"
        if action == "critique":
            if not args.get("scores"):
                return critique_rubric()
            row = record_critique(cwd, dict(args.get("scores") or {}), str(args.get("notes") or ""),
                                  str(args.get("artifact") or ""))
            tail = (("Perbaiki dulu: " + ", ".join(row["weak"]) + " (di bawah 3), lalu nilai ulang.") if row["weak"]
                    else "Semua dimensi ≥ 3. Tawarkan tweak ke pengguna, lalu handoff 'Pakai untuk coding'.")
            return f"Kritik tercatat: rata-rata {row['average']}/5 {row['scores']}. {tail}"
        if action == "check":
            return format_check(check(cwd, list(args.get("paths") or []) or None))
        if action == "export":
            return f"Diekspor: {export(cwd, str(args.get('format') or 'css'))}"
        if action == "handoff":
            on = set_inject(cwd, bool(args.get("enable", True)))
            if not on:
                return "Design system tidak lagi disuntik ke agent coding (file tetap ada)."
            return ("Siap dipakai untuk coding: design system ini sekarang ikut di konteks agent utama untuk setiap "
                    "perubahan UI di proyek ini. Langkah: baca skill `design-to-code`, export format sesuai stack "
                    "(css/tailwind/dart), lalu design action=check sebelum selesai.\n" + status_text(cwd))
        if action == "remember":
            p = remember(str(args.get("text") or ""))
            return f"Preferensi desain diingat di {p} (ikut di catatan memori setiap sesi)."
        return "error: action tidak dikenal; pilih: " + ", ".join(ACTIONS)
    except DesignError as exc:
        return f"error: {exc}"


# --------------------------------------------------------------- /desain ----

DESAIN_COMMAND = re.compile(r"^\s*/desain(?:\s+([\s\S]*))?$", re.I)


def command(user_text: str, cwd: Path | str) -> tuple[str, str, str] | None:
    """``/desain [brief | status | cek | katalog]`` → (kind, reply, follow_up_for_the_model)."""
    m = DESAIN_COMMAND.match(user_text or "")
    if not m:
        return None
    arg = (m.group(1) or "").strip()
    low = arg.lower()
    if low in ("status", "info"):
        return "desain", status_text(cwd), ""
    if low in ("cek", "check", "periksa"):
        try:
            return "desain", format_check(check(cwd)), ""
        except DesignError as exc:
            return "desain", str(exc), ""
    if low in ("katalog", "catalog", "template", "templates"):
        return "desain", catalog_text(), ""
    if low in ("off", "matikan"):
        try:
            set_inject(cwd, False)
            return "desain", "Design system tidak lagi disuntik ke agent coding. `/desain pakai` untuk menyalakan.", ""
        except DesignError as exc:
            return "desain", str(exc), ""
    if low in ("pakai", "on", "pakai untuk coding", "handoff"):
        try:
            set_inject(cwd, True)
            return "desain", "Siap dipakai untuk coding: design system ikut di konteks agent utama.\n" + status_text(cwd), ""
        except DesignError as exc:
            return "desain", str(exc), ""
    reply = ("🎨 Mode Desain aktif. Alurnya: brief → template → kunci arah → design system → artifact + "
             "pratinjau → kritik 5 dimensi → Pakai untuk coding.")
    follow = ("[Perintah /desain — bukan pesan baru] Masuk Mode Desain. Baca skill `desain` dengan alat `skill` "
              "dan ikuti alurnya langkah demi langkah. "
              + (f"Brief dari pengguna: {arg}" if arg else
                 "Pengguna belum memberi brief: tanyakan singkat apa yang mau didesain (jenis, untuk siapa, "
                 "rasa visual / brand), maksimal dua pertanyaan.")
              + f"\nFolder kerja: {project_root(cwd)} (design system → .neovarch/design/).")
    return "desain", reply, follow
