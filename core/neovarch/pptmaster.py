"""PowerPoint (.pptx) decks with PPT Master, installed on demand.

PPT Master (https://github.com/hugohe3/ppt-master, MIT, Copyright (c) 2025-2026
Hugo He) is an agent workflow: the agent plans the deck, hand-writes one SVG per
slide, checks them and exports a native, editable .pptx with python-pptx. The
skill ships with an integrity gate (``scripts/attribution_guard.py``) that
refuses to run when its attribution files are changed, so Neovarch never edits
or trims it: the official skill-only release zip is downloaded once, checked
against a pinned SHA-256 and unpacked unchanged into ``~/.neovarch/skills/ppt-master``
(where it also shows up in the Skills tab and the phone's skill picker).

Python packages go into a private venv (``~/.neovarch/ppt-master/venv``) so the
user's own Python stays untouched. Only the packages the PPTX path needs are
installed by default. PyMuPDF (PDF sources) is AGPL-3.0 and therefore installed
only when the user asks for PDF input (``pdf=True``).

Needs Python 3.10+ on the PC; without it every entry point raises
``PptError`` with a bilingual (ID/EN) message saying how to fix it.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

from neovarch.paths import neovarch_home

PPT_MASTER_VERSION = "6.7.0"
PPT_MASTER_REPO = "https://github.com/hugohe3/ppt-master"
PPT_MASTER_ZIP = (f"{PPT_MASTER_REPO}/releases/download/v{PPT_MASTER_VERSION}/"
                  f"ppt-master-skill-v{PPT_MASTER_VERSION}.zip")
PPT_MASTER_SHA256 = "40424d9784fa25f771da8b312258c3c67a168925122aa6bb7faf6848e77ceee9"
ZIP_PREFIX = "ppt-master/skills/ppt-master/"
SKILL_NAME = "ppt-master"
MIN_PYTHON = (3, 10)

# What the SVG -> PPTX path, the checker and the common source converters need
# (subset of the skill's requirements.txt; image generation, narration, the
# web editor and notebooks are left out to keep the install small).
CORE_REQUIREMENTS = [
    "PyYAML>=6.0",
    "python-pptx>=0.6.21",
    "XlsxWriter>=3.0.0",
    "skia-pathops>=0.9.2",
    "uharfbuzz>=0.50.0",
    "Pillow>=9.0.0",
    "numpy>=1.20.0",
    "mammoth>=1.6.0",
    "markdownify>=0.11.6",
    "openpyxl>=3.1.0",
    "requests>=2.31.0",
    "beautifulsoup4>=4.12.0",
]
# AGPL-3.0: installed only on explicit request (PDF sources).
PDF_REQUIREMENTS = ["PyMuPDF>=1.23.0"]

Download = Callable[[str], bytes]
Run = Callable[..., subprocess.CompletedProcess]


class PptError(Exception):
    pass


NO_PYTHON = ("Python 3.10 atau lebih baru tidak ditemukan di PC ini, padahal dibutuhkan untuk membuat PPT. "
             "Pasang dari https://www.python.org/downloads/ (Windows: centang \"Add python.exe to PATH\"), "
             "lalu coba lagi. / Python 3.10+ was not found on this PC; it is required to make PowerPoint decks. "
             "Install it from https://www.python.org/downloads/ (Windows: tick \"Add python.exe to PATH\") and try again.")


# ----------------------------------------------------------------- paths ----

def skill_dir() -> Path:
    return neovarch_home() / "skills" / SKILL_NAME


def base_dir() -> Path:
    return neovarch_home() / "ppt-master"


def venv_dir() -> Path:
    return base_dir() / "venv"


def presentations_dir() -> Path:
    d = neovarch_home() / "presentations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def venv_python(root: Path | None = None) -> Path:
    root = root or venv_dir()
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ---------------------------------------------------------------- python ----

def _default_run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)  # noqa: S603 (fixed argv, no shell)


def parse_version(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def python_candidates() -> list[list[str]]:
    out: list[list[str]] = []
    env = os.environ.get("NEOVARCH_PYTHON")
    if env:
        out.append([env])
    if sys.executable and not getattr(sys, "frozen", False):
        out.append([sys.executable])
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p:
            out.append([p])
    if os.name == "nt" and shutil.which("py"):
        out.append(["py", "-3"])
    seen, uniq = set(), []
    for c in out:
        if tuple(c) not in seen:
            seen.add(tuple(c))
            uniq.append(c)
    return uniq


def find_python(run: Run = _default_run, candidates: list[list[str]] | None = None) -> tuple[list[str], str]:
    """First interpreter that is Python 3.10+ (argv, version) or PptError."""
    found = []
    for cand in (python_candidates() if candidates is None else candidates):
        try:
            res = run([*cand, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"], timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        ver = (res.stdout or "").strip()
        v = parse_version(ver)
        if res.returncode == 0 and v:
            if v >= MIN_PYTHON:
                return cand, ver
            found.append(f"{' '.join(cand)} = {ver}")
    raise PptError(NO_PYTHON + (f" (ditemukan / found: {', '.join(found)})" if found else ""))


# ------------------------------------------------------------- download -----

def http_bytes(url: str, timeout: float = 300) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Neovarch-Agent (ppt-master installer)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.read()


def skill_installed() -> bool:
    d = skill_dir()
    return (d / "SKILL.md").is_file() and (d / "scripts" / "svg_to_pptx.py").is_file() \
        and (d / "LICENSE").is_file()


def installed_version() -> str | None:
    f = skill_dir() / "SKILL.md"
    if not f.is_file():
        return None
    m = re.search(r'(?m)^\s*version:\s*"?([0-9][0-9.]*)"?', f.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def install_skill(download: Download = http_bytes, *, force: bool = False,
                  sha256: str | None = None) -> Path:
    """Download the official skill-only release and unpack it unchanged."""
    target = skill_dir()
    if skill_installed() and installed_version() == PPT_MASTER_VERSION and not force:
        return target
    try:
        data = download(PPT_MASTER_ZIP)
    except Exception as exc:  # network errors become one clear message
        raise PptError(f"gagal mengunduh PPT Master / download failed: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    sha256 = sha256 or PPT_MASTER_SHA256
    if digest != sha256:
        raise PptError(f"checksum PPT Master tidak cocok / checksum mismatch ({digest[:12]}…); unduhan ditolak")
    tmp = target.with_name(target.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [m for m in zf.infolist() if m.filename.startswith(ZIP_PREFIX) and m.filename != ZIP_PREFIX]
        if not members:
            raise PptError("arsip PPT Master tidak berisi skill / archive has no skill folder")
        for m in members:
            rel = m.filename[len(ZIP_PREFIX):]
            dest = (tmp / rel).resolve()
            if not str(dest).startswith(str(tmp.resolve())):
                raise PptError(f"jalur tidak aman di arsip / unsafe path in archive: {m.filename}")
            if m.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.rename(target)
    return target


# ------------------------------------------------------------------ venv ----

def _pip_has(py: Path, module: str, run: Run) -> bool:
    try:
        return run([str(py), "-c", f"import {module}"], timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_venv(run: Run = _default_run, *, pdf: bool = False, python: list[str] | None = None) -> Path:
    """Create the private venv and install the PPTX requirements (PDF only on request)."""
    py = venv_python()
    if not py.exists():
        base = python or find_python(run)[0]
        venv_dir().parent.mkdir(parents=True, exist_ok=True)
        res = run([*base, "-m", "venv", str(venv_dir())], timeout=600)
        if res.returncode != 0 or not py.exists():
            raise PptError("gagal membuat venv Python / could not create the Python venv: "
                           + ((res.stderr or res.stdout or "").strip()[-600:]))
    wanted = []
    if not _pip_has(py, "pptx", run) or not _pip_has(py, "pathops", run):
        wanted += CORE_REQUIREMENTS
    if pdf and not _pip_has(py, "fitz", run):
        wanted += PDF_REQUIREMENTS
    if wanted:
        res = run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", *wanted], timeout=1800)
        if res.returncode != 0:
            raise PptError("pip install gagal / failed: " + ((res.stderr or res.stdout or "").strip()[-800:]))
    return py


def status(run: Run = _default_run) -> dict:
    py = venv_python()
    out = {
        "version": PPT_MASTER_VERSION,
        "skill_installed": skill_installed(),
        "skill_dir": str(skill_dir()),
        "installed_version": installed_version(),
        "venv_python": str(py) if py.exists() else None,
        "pdf_input": bool(py.exists() and _pip_has(py, "fitz", run)),
        "presentations_dir": str(neovarch_home() / "presentations"),
    }
    try:
        argv, ver = find_python(run)
        out["python"] = {"argv": argv, "version": ver}
    except PptError as exc:
        out["python"] = None
        out["error"] = str(exc)
    return out


def setup(*, pdf: bool = False, force: bool = False, download: Download = http_bytes,
          run: Run = _default_run) -> dict:
    """Python check -> skill download -> venv; returns where everything lives."""
    argv, ver = find_python(run)  # clear error first, before any download
    sdir = install_skill(download, force=force)
    py = ensure_venv(run, pdf=pdf, python=argv)
    guard = run([str(py), str(sdir / "scripts" / "attribution_guard.py")], timeout=120)
    if guard.returncode != 0:
        raise PptError("pemeriksaan integritas PPT Master gagal / integrity check failed: "
                       + ((guard.stdout or "") + (guard.stderr or "")).strip()[-400:])
    return {"skill_dir": str(sdir), "python": str(py), "system_python": ver,
            "presentations_dir": str(presentations_dir()), "pdf_input": pdf,
            "version": PPT_MASTER_VERSION}


# ---------------------------------------------------------------- export ----

def list_pptx(project: Path) -> list[Path]:
    return sorted(project.rglob("*.pptx"), key=lambda p: p.stat().st_mtime)


def export(project_path: str, *, quick: bool = True, notes: bool = True, output: str | None = None,
           run: Run = _default_run) -> dict:
    """Run PPT Master's own exporter (svg_to_pptx.py) and return the new .pptx."""
    project = Path(os.path.expanduser(project_path or "")).resolve()
    if not project_path or not project.is_dir():
        raise PptError(f"folder proyek tidak ditemukan / project folder not found: {project_path}")
    py = venv_python()
    if not py.exists() or not skill_installed():
        raise PptError("PPT Master belum terpasang; jalankan ppt_setup dulu / not installed yet: run ppt_setup first")
    before = {p: p.stat().st_mtime for p in list_pptx(project)}
    cmd = [str(py), str(skill_dir() / "scripts" / "svg_to_pptx.py"), str(project)]
    if quick:
        cmd.append("--quick-generate")
    cmd.append("--with-notes" if notes else "--no-notes")
    if output:
        cmd += ["-o", str(Path(os.path.expanduser(output)))]
    res = run(cmd, timeout=1800, cwd=str(project))
    log = ((res.stdout or "") + (res.stderr or "")).strip()
    if res.returncode != 0:
        raise PptError("ekspor PPTX gagal / export failed:\n" + log[-1500:])
    files = [p for p in list_pptx(project) if before.get(p) != p.stat().st_mtime]
    if output and Path(os.path.expanduser(output)).is_file():
        files = [Path(os.path.expanduser(output)).resolve()]
    if not files:
        raise PptError("exporter selesai tapi tidak ada .pptx baru / no new .pptx was written:\n" + log[-800:])
    return {"files": [str(p) for p in files], "log": log[-600:]}
