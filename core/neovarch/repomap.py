"""``repo_map``: a cheap, dependency-free symbol map of a code base (Aider-style, without tree-sitter).

One regex pass per file pulls out top-level definitions (classes, functions, types,
methods) with their line numbers; files are ranked by how often *other* files mention
their symbols (a reference count standing in for Aider's PageRank), boosted by a
``focus`` (words or paths the task is about). The output is clipped to a token budget,
so the model gets the shape of an unfamiliar repo in one call instead of ten
``read_file``/``grep`` round trips. Read-only; runs in parallel with other reads.
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter
from pathlib import Path

from neovarch.tools_code import SKIP_DIRS, _is_binary

MAX_FILES = 3000
MAX_BYTES = 400_000
DEADLINE_S = 8.0  # stop parsing more files after this (cold disks, huge monorepos); the map says so
VENDOR_DIRS = {"vendor", "third_party", "third-party", "external", "Pods", "bower_components", "coverage"}
COMMON = {"__init__", "main", "init", "get", "set", "run", "start", "stop", "close", "open", "update", "build",
          "render", "load", "save", "create", "delete", "test", "setup", "toString", "default", "constructor"}

_PY = re.compile(r"^(\s{0,8})(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)\s*([(:].*)?$")
_JS = re.compile(r"^(\s{0,4})(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?"
                 r"(?:(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)|class\s+([A-Za-z_$][\w$]*)|"
                 r"interface\s+([A-Za-z_$][\w$]*)|type\s+([A-Za-z_$][\w$]*)\s*[=<]|enum\s+([A-Za-z_$][\w$]*)|"
                 r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$]\w*)\s*(?::[^=]+)?=>)")
_JS_METHOD = re.compile(r"^(\s{2,4})(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*"
                        r"([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{\s*$")
_DART = re.compile(r"^(\s{0,2})(?:abstract\s+|sealed\s+|final\s+|base\s+)*(class|mixin|enum|extension|typedef)\s+([A-Za-z_]\w*)")
_DART_FN = re.compile(r"^(\s{0,2})(?:static\s+|Future<[^>]*>\s+|Stream<[^>]*>\s+|void\s+|[A-Z]\w*(?:<[^>]*>)?\??\s+|"
                      r"int\s+|double\s+|bool\s+|String\s+|dynamic\s+)+([a-z_]\w*)\s*\([^;]*$")
_GO = re.compile(r"^()(func|type)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")
_RS = re.compile(r"^(\s{0,4})(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(fn|struct|enum|trait|impl|mod|type)\s+(?:<[^>]*>\s*)?([A-Za-z_]\w*)")
_JVM = re.compile(r"^(\s{0,4})(?:@\w+\s+)*(?:(?:public|private|protected|internal|static|final|abstract|open|data|sealed|"
                  r"override|suspend|async|partial|virtual)\s+)*(class|interface|enum|record|object|fun|struct)\s+([A-Za-z_]\w*)")
_JVM_METHOD = re.compile(r"^(\s{2,4})(?:(?:public|private|protected|internal|static|final|abstract|override|async|virtual)\s+)+"
                         r"[\w<>\[\],? ]+\s+([A-Za-z_]\w*)\s*\([^;]*$")
_RB = re.compile(r"^(\s{0,4})(class|module|def)\s+([A-Za-z_][\w.?!]*)")
_PHP = re.compile(r"^(\s{0,4})(?:(?:public|private|protected|static|abstract|final)\s+)*(class|interface|trait|function)\s+([A-Za-z_]\w*)")
_C = re.compile(r"^()(?:static\s+|inline\s+|extern\s+)*(?:struct\s+|enum\s+|unsigned\s+|const\s+)*[A-Za-z_][\w:<>,*& ]*?[\s*&]"
                r"([A-Za-z_][\w:~]*)\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$")

LANG = {".py": "py", ".pyi": "py", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
        ".dart": "dart", ".go": "go", ".rs": "rs", ".java": "jvm", ".kt": "jvm", ".kts": "jvm", ".cs": "jvm",
        ".scala": "jvm", ".swift": "jvm", ".rb": "rb", ".php": "php", ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c",
        ".hpp": "c"}
KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "else", "new", "function", "constructor", "super", "await"}


def symbols(text: str, lang: str) -> list[tuple[int, str, str]]:
    """[(line number, name, short signature)] for one file."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 400 or not line.strip() or line.lstrip().startswith(("//", "#", "*", "/*")) and lang != "py":
            continue
        name = ""
        if lang == "py":
            m = _PY.match(line)
            if m and (not m.group(1) or m.group(2) == "def"):
                name = m.group(3)
                if m.group(1) and name.startswith("_") and not name.startswith("__init"):
                    name = ""  # private methods are noise in a map
        elif lang == "js":
            m = _JS.match(line)
            if m:
                name = next((g for g in m.groups()[1:] if g), "")
            else:
                m = _JS_METHOD.match(line)
                if m and m.group(2) not in KEYWORDS:
                    name = m.group(2)
        elif lang == "dart":
            m = _DART.match(line) or _DART_FN.match(line)
            if m:
                name = m.group(3) if m.re is _DART else m.group(2)
                if name in KEYWORDS:
                    name = ""
        else:
            rx = {"go": _GO, "rs": _RS, "jvm": _JVM, "rb": _RB, "php": _PHP, "c": _C}[lang]
            m = rx.match(line)
            if m:
                name = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(2)
            elif lang == "jvm":
                m = _JVM_METHOD.match(line)
                if m and m.group(2) not in KEYWORDS:
                    name = m.group(2)
            if name in KEYWORDS:
                name = ""
        if name:
            sig = " ".join(line.strip().rstrip("{:").split())
            out.append((i, name, sig[:110]))
    return out


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    if root.is_file():
        return [root] if root.suffix.lower() in LANG else []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in VENDOR_DIRS
                             and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() in LANG and ".min." not in name and not name.endswith((".g.dart", ".freezed.dart")):
                out.append(p)
                if len(out) >= MAX_FILES:
                    return out
    return out


def build(root: Path, focus: str = "", budget: int = 1500) -> str:
    root = Path(root)
    files = _files(root)
    if not files:
        return f"repo_map: no source files under {root}"
    per_file: dict[Path, list[tuple[int, str, str]]] = {}
    words: dict[Path, Counter] = {}
    ident = re.compile(r"[A-Za-z_]\w{2,}")
    t0, cut = time.monotonic(), 0
    for n, p in enumerate(files):
        if time.monotonic() - t0 > DEADLINE_S:
            cut = len(files) - n
            break
        try:
            if p.stat().st_size > MAX_BYTES or _is_binary(p):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        per_file[p] = symbols(text, LANG[p.suffix.lower()])
        words[p] = Counter(ident.findall(text))
    total = Counter()
    for c in words.values():
        total.update(c.keys())  # in how many files a word appears
    common = {w for w, c in total.items() if c > max(len(words) // 4, 8)} | COMMON
    focus_terms = {w.lower() for w in re.findall(r"[\w./-]{3,}", focus or "")}
    scored = []
    for p, syms in per_file.items():
        rel = p.relative_to(root).as_posix() if p != root else p.name
        own = words.get(p, Counter())
        refs = sum(max(total[name] - (1 if own[name] else 0), 0) for _, name, _ in syms
                   if name not in common and len(name) > 3)
        score = refs / (1 + len(syms)) ** 0.5 + len(syms) * 0.05  # big files must not win on size alone
        if focus_terms:
            hay = rel.lower() + " " + " ".join(n.lower() for _, n, _ in syms)
            hits = sum(1 for t in focus_terms if t in hay)
            score = score * (1 + 3 * hits) + 50 * hits
        if "test" in rel.lower():
            score *= 0.5
        scored.append((score, rel, syms))
    scored.sort(key=lambda x: (-x[0], x[1]))
    limit = max(int(budget), 200) * 4  # ~4 chars per token
    out, used, shown = [], 0, 0
    cap = 40 if len(scored) <= 30 else 12  # wide repo: breadth first; one folder: depth
    for _, rel, syms in scored:
        block = rel + ":" + ("" if syms else " (no symbols)")
        lines = [block] + [f"  {ln}: {sig}" for ln, _, sig in syms[:cap]]
        if len(syms) > cap:
            lines.append(f"  … +{len(syms) - cap} more (repo_map path={rel})")
        text = "\n".join(lines)
        if used + len(text) > limit:
            if used + len(block) + 1 <= limit:
                out.append(block + " …")
                used += len(block) + 3
                shown += 1
            continue
        out.append(text)
        used += len(text) + 1
        shown += 1
    head = (f"repo_map {root} — {shown}/{len(per_file)} files (ranked by references"
            + (f", focus: {focus}" if focus else "") + "; read_file for bodies)"
            + (f"\n(stopped after {DEADLINE_S:.0f}s, {cut} files not scanned: pass path= a subfolder)" if cut else ""))
    return head + "\n" + "\n".join(out)


SCHEMA = {
    "description": ("Symbol map of a code base (classes/functions with line numbers, most-referenced files first) "
                    "within a token budget. Use first in an unfamiliar repo; focus = words/paths the task is about."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "folder (default: working folder)"},
        "focus": {"type": "string"}, "budget": {"type": "integer", "description": "tokens, default 1500"}}},
}
