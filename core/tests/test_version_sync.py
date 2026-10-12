"""The version the core reports to the phone must be the app's real version.

The phone shows ``serverInfo['version']`` (the core's ``/api/status`` / gateway
hello), which is ``neovarch.__version__``. That string is written by hand in
``core/neovarch/__init__.py``; when a release bumped the desktop and the phone
but not the core, the phone showed an old "PC version" (1.3.0 next to a 1.4.5
desktop). Keep every place that names the release in step.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from neovarch import __version__

ROOT = Path(__file__).resolve().parents[2]


def _need(path: Path) -> Path:
    if not path.exists():  # running from an sdist / installed core without the repo
        pytest.skip(f"{path} not present")
    return path


def test_core_version_matches_desktop_package():
    for rel in ("desktop/package.json", "desktop/apps/desktop/package.json"):
        data = json.loads(_need(ROOT / rel).read_text(encoding="utf-8"))
        assert data["version"] == __version__, f"{rel} says {data['version']}, core says {__version__}"


def test_core_version_matches_phone_pubspec():
    text = _need(ROOT / "pubspec.yaml").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", text, re.M)
    assert m, "pubspec.yaml has no version line"
    assert m.group(1) == __version__


def test_installers_default_core_ref_matches():
    sh = _need(ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    ps = _need(ROOT / "scripts/install.ps1").read_text(encoding="utf-8")
    assert f'DEFAULT_CORE_REF="v{__version__}"' in sh
    assert f"$DefaultCoreRef = 'v{__version__}'" in ps

