"""PC voice typing: local free STT behind /api/audio/transcribe (faster-whisper / whisper.cpp, both optional).

No engine → a clear typed refusal with the install hint (never a crash). Engines are faked here:
the real ones are optional and download models, which the tests must never do.
"""

import base64
import os
import stat

from neovarch import stt
from neovarch.server import STT_UNAVAILABLE
from test_server import _client

AUDIO = "data:audio/webm;base64," + base64.b64encode(b"\x1aE\xdf\xa3" + b"\0" * 200).decode()


def _no_engines(monkeypatch):
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: False)
    monkeypatch.setattr(stt.shutil, "which", lambda _n: None)


async def test_transcribe_without_an_engine_is_a_clear_refusal_with_install_hint(home, monkeypatch):
    _no_engines(monkeypatch)
    _gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        r = await c.post("/api/audio/transcribe?token=tok", json={"data_url": AUDIO})
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is False and body["code"] == "stt_unavailable"
        assert body["transcript"] == ""  # the desktop used to crash on undefined.trim()
        assert body["error"] == STT_UNAVAILABLE
        assert "pip install faster-whisper" in body["error"] and "not available" in body["error"]
        assert "faster-whisper" in body["install_hint"]
        st = await (await c.get("/api/audio/stt/status?token=tok")).json()
        assert st["available"] is False and st["model"] == "small" and "pip install" in st["install_hint"]
        lease = await (await c.post("/api/audio/stt-lease?token=tok", json={"lease": "voice-input", "active": True})).json()
        assert lease["ok"] is True and lease["active"] is True and lease["available"] is False
    finally:
        await c.close()


async def test_transcribe_with_faster_whisper(home, monkeypatch):
    seen = {}

    def fake(path, s):
        seen["ext"] = os.path.splitext(path)[1]
        seen["bytes"] = open(path, "rb").read()[:4]
        seen["model"] = s["model"]
        seen["language"] = s["language"]
        return "halo neovarch buka repo", "id"

    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: True)
    monkeypatch.setattr(stt, "_faster_whisper", fake)
    _gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok", NEOVARCH_STT_MODEL="base")
    try:
        # phone shape: raw base64 + mime (m4a from Android MediaRecorder)
        b64 = base64.b64encode(b"\0\0\0\x18ftypM4A " + b"\0" * 200).decode()
        body = await (await c.post("/api/audio/transcribe?token=tok", json={"audio_base64": b64, "mime_type": "audio/mp4",
                                                                                  "language": "id"})).json()
        assert body == {"ok": True, "available": True, "transcript": "halo neovarch buka repo", "engine": "faster-whisper",
                        "model": "base", "language": "id"}
        assert seen["ext"] == ".m4a" and seen["model"] == "base" and seen["language"] == "id"
        # desktop shape: data URL
        body = await (await c.post("/api/audio/transcribe?token=tok", json={"data_url": AUDIO})).json()
        assert body["ok"] is True and seen["ext"] == ".webm" and seen["bytes"] == b"\x1aE\xdf\xa3"
        st = await (await c.get("/api/audio/stt/status?token=tok")).json()
        assert st["available"] is True and st["engine"] == "faster-whisper"
    finally:
        await c.close()


async def test_engine_failure_and_bad_audio_are_typed(home, monkeypatch):
    def boom(path, s):
        raise RuntimeError("model download blocked")

    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: True)
    monkeypatch.setattr(stt, "_faster_whisper", boom)
    _gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        body = await (await c.post("/api/audio/transcribe?token=tok", json={"data_url": AUDIO})).json()
        assert body["ok"] is False and body["code"] == "stt_failed" and body["transcript"] == ""
        assert "model download blocked" in body["error"]
        body = await (await c.post("/api/audio/transcribe?token=tok", json={})).json()
        assert body["code"] == "bad_audio" and body["transcript"] == ""
        body = await (await c.post("/api/audio/transcribe?token=tok", json={"data_url": "data:audio/webm;base64,AAAA"})).json()
        assert body["code"] == "bad_audio"
    finally:
        await c.close()


def test_engine_off_and_explicit_choice(monkeypatch):
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: True)
    assert stt.pick_engine(stt.settings({"stt": {"engine": "off"}})) is None
    assert "dimatikan" in stt.status({"stt": {"engine": "off"}})["reason"]
    assert stt.pick_engine(stt.settings({"stt": {"engine": "faster-whisper"}})) == "faster-whisper"
    monkeypatch.setenv("NEOVARCH_STT_ENGINE", "whisper.cpp")
    assert stt.pick_engine(stt.settings({})) is None  # asked for whisper.cpp, which is not set up


def test_whisper_cpp_engine_with_fake_binaries(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: False)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ffmpeg = bindir / "ffmpeg"
    ffmpeg.write_text('#!/bin/sh\nfor a; do out="$a"; done\nprintf RIFF > "$out"\n')
    cli = bindir / "whisper-cli"
    cli.write_text('#!/bin/sh\necho "  selamat pagi"\necho " dunia "\n')
    for f in (ffmpeg, cli):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"x")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    cfg = {"stt": {"whisper_cpp_model": str(model), "language": "id"}}
    assert stt.status(cfg)["engine"] == "whisper.cpp"
    out = stt.transcribe_bytes(b"\0" * 200, "audio/webm", cfg)
    assert out["transcript"] == "selamat pagi dunia" and out["engine"] == "whisper.cpp" and out["model"] == "ggml-small.bin"
