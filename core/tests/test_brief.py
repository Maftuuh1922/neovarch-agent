"""Mode 3 (proaktif mini): brief pagi — disusun dari data lokal, tanpa panggilan model."""

import time

from test_server import _client

H = {"Authorization": "Bearer tok"}


def test_build_reports_failed_cron_and_errored_sessions(home):
    from neovarch import brief
    from neovarch.cron import CronStore
    from neovarch.store import SessionStore

    store = SessionStore()
    rec = store.create(source="desktop", title="Kerja gagal")
    rec["messages"].append({"role": "user", "content": "tolong deploy", "ts": 1})
    rec["messages"].append({"role": "assistant", "content": "HTTP 500 saat deploy",
                            "meta": {"error": "deploy gagal"}, "ts": 2})
    rec["last_error"] = "deploy gagal"
    store.save(rec)

    cron = CronStore()
    cron.create({"name": "backup", "prompt": "jalankan backup", "schedule": "0 8 * * *"})
    jobs = cron.list()
    cron.update(jobs[0]["id"], {"_last_error": "9router down"})

    out = brief.build(store, cron, {"available": False, "enabled": True})
    assert out["alerts"] >= 2
    assert "backup" in out["body"] and "9router down" in out["body"]
    assert "Kerja gagal" in out["body"]
    assert "Mode luring" in out["body"]


def test_build_all_clear(home):
    from neovarch import brief
    from neovarch.cron import CronStore
    from neovarch.store import SessionStore

    out = brief.build(SessionStore(), CronStore(), None)
    assert out["alerts"] == 0
    assert "aman" in out["body"]


def test_next_epoch_tomorrow_when_passed():
    from neovarch import brief
    now = time.time()
    nxt = brief.next_epoch(0, 0, now)  # tengah malam sudah lewat sebagian besar hari
    import datetime
    lt = datetime.datetime.fromtimestamp(nxt)
    assert lt.hour == 0 and lt.minute == 0 and nxt > now


async def test_brief_routes(home, monkeypatch):
    monkeypatch.setenv("NEOVARCH_BRIEF_ENABLED", "1")
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        st = await (await c.get("/api/brief/status", headers=H)).json()
        assert st["enabled"] is True
        out = await (await c.post("/api/brief/send", headers=H)).json()
        assert out["title"].startswith("Brief pagi")
        # session berisi pesan asisten brief
        from neovarch import brief as briefmod
        rec = gw.store.find(briefmod.SESSION_ID)
        assert rec is not None
        roles = [m["role"] for m in rec["messages"]]
        assert roles and roles[-1] == "assistant"
        assert rec["messages"][-1]["meta"]["brief"] == "morning"
        # kirim kedua kali menambah pesan di sesi yang sama (tidak dobel sesi)
        await (await c.post("/api/brief/send", headers=H)).json()
        rec2 = gw.store.find(briefmod.SESSION_ID)
        assert len(rec2["messages"]) == 2
    finally:
        await c.close()
