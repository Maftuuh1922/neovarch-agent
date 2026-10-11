"""PC voice typing: the core has no speech engine yet and says so clearly (never a crash)."""

from neovarch.server import STT_UNAVAILABLE
from test_server import _client


async def test_transcribe_answers_a_clear_refusal_with_a_string_transcript(home, monkeypatch):
    _gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        r = await c.post("/api/audio/transcribe?token=tok", json={"data_url": "data:audio/webm;base64,AAAA"})
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is False and body["code"] == "stt_unavailable"
        assert body["transcript"] == ""  # the desktop used to crash on undefined.trim()
        assert "Dikte suara di PC belum tersedia" in body["error"] and "not available" in body["error"]
        assert body["error"] == STT_UNAVAILABLE  # exactly the Neovarch message, nothing from the upstream engine
        lease = await (await c.post("/api/audio/stt-lease?token=tok", json={"lease": "voice-input", "active": True})).json()
        assert lease["ok"] is True and lease["active"] is True
    finally:
        await c.close()
