"""Smoke test of every route the desktop's visible pages call, against a live core.

    python core/scripts/route_smoke.py [--port 9329] [--llm-port 18090]

Starts the mock provider and `neovarch serve` in a throwaway NEOVARCH_HOME,
GETs the REST routes behind each rail page and Settings tab, calls the gateway
RPCs those pages use, runs one chat turn and checks the Kantor snapshot and the
chat's persona, then the routes behind the Kantor desk model switch, thread
timeline/around, logs level filter, skills toggle + learning node edit,
memory panel, the GitHub account page, every company.* route behind the
Kantor → Perusahaan tabs and a phone chat attachment (upload -> vision input).
Prints a JSON report (one row per check) and exits non-zero if
any check fails. A route "fails" when it answers non-2xx or, for a list route,
returns no list where the page reads one.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(CORE))
from smoke_serve import wait_port  # noqa: E402

# (page, path, key holding the list the page reads or None for an object)
ROUTES = [
    ("boot", "/api/status", None),
    ("boot", "/api/config", None),
    ("boot", "/api/config/defaults", None),
    ("settings:model", "/api/config/schema", None),
    ("settings:model", "/api/model/info", None),
    ("settings:model", "/api/model/options", "providers"),
    ("settings:model", "/api/model/auxiliary", None),
    ("settings:providers", "/api/env", None),
    ("settings:providers", "/api/providers/custom-endpoints", "endpoints"),
    ("settings:appearance", "/api/appearance", None),
    ("settings:sessions", "/api/sessions", None),
    ("settings:about", "/api/update", None),
    ("sidebar", "/api/profiles", None),
    ("sidebar", "/api/profiles/sessions/sidebar", None),
    ("sidebar", "/api/sessions/search?q=halo", None),
    ("kantor", "/api/office", "agents"),
    ("catatan", "/api/obsidian/tree", None),
    ("catatan", "/api/obsidian/graph", None),
    ("skill", "/api/skills", ""),
    ("skill", "/api/tools/toolsets", ""),
    ("kanban", "/api/plugins/kanban/board", "tasks"),
    ("jadwal", "/api/cron/jobs", ""),
    ("jadwal", "/api/cron/delivery-targets", "targets"),
    ("mcp", "/api/mcp/servers", None),
    ("logs", "/api/logs", "lines"),
    ("memory", "/api/memory", None),
    ("settings:account", "/api/account/github", None),
]

SMOKE_SKILL = "route-smoke-skill"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


async def rest(http, method: str, url: str, body: dict | None = None) -> tuple[int, object]:
    async with http.request(method, url, json=body) as resp:
        text = await resp.text()
        try:
            return resp.status, json.loads(text)
        except ValueError:
            return resp.status, {}


def has_list(body, key) -> bool:
    if key is None:
        return isinstance(body, dict)
    if key == "":
        return isinstance(body, list) or (isinstance(body, dict) and any(isinstance(v, list) for v in body.values()))
    return isinstance(body, dict) and isinstance(body.get(key), list)


async def drive(port: int, token: str) -> list[dict]:
    rows: list[dict] = []
    base = f"http://127.0.0.1:{port}"
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=headers) as http:
        for page, path, key in ROUTES:
            try:
                async with http.get(base + path) as resp:
                    text = await resp.text()
                    try:
                        body = json.loads(text)
                    except ValueError:
                        body = None
                    ok = 200 <= resp.status < 300 and has_list(body, key)
                    rows.append({"page": page, "check": f"GET {path}", "status": resp.status, "ok": ok})
            except Exception as exc:  # noqa: BLE001
                rows.append({"page": page, "check": f"GET {path}", "ok": False, "error": str(exc)})

        events: list[dict] = []
        async with http.ws_connect(f"{base}/api/ws?token={token}") as ws:
            n = 0

            async def call(method: str, params: dict) -> dict:
                nonlocal n
                n += 1
                rid = n
                await ws.send_json({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
                while True:
                    msg = await ws.receive_json(timeout=20)
                    if msg.get("method") == "event":
                        events.append(msg["params"])
                    elif msg.get("id") == rid:
                        return msg

            for method, params in [("config.get", {"key": "model"}), ("commands.catalog", {}),
                                   ("session.list", {}), ("office.snapshot", {})]:
                res = await call(method, params)
                rows.append({"page": "rpc", "check": method, "ok": "result" in res,
                             **({"error": res.get("error")} if "error" in res else {})})

            created = (await call("session.create", {"source": "desktop"}))["result"]
            sid = created["session_id"]
            rows.append({"page": "chat", "check": "session.create info.provider",
                         "ok": bool(created.get("info", {}).get("provider")),
                         "provider": created.get("info", {}).get("provider")})
            await call("prompt.submit", {"session_id": sid, "text": "jalankan tool"})
            # While the turn runs the desk must say working.
            snap = (await call("office.snapshot", {}))["result"]
            desk = next((a for a in snap.get("agents", []) if a.get("session_id") == sid), {})
            rows.append({"page": "kantor", "check": "desk working during turn",
                         "ok": desk.get("status") == "working" and snap["counts"]["working"] >= 1,
                         "status": desk.get("status"), "working": snap["counts"].get("working")})
            rows.append({"page": "kantor", "check": "desk model_provider",
                         "ok": bool(desk.get("model_provider")), "provider": desk.get("model_provider")})
            deadline = time.monotonic() + 30
            while not any(e["type"] == "message.complete" for e in events):
                msg = await ws.receive_json(timeout=max(deadline - time.monotonic(), 0.1))
                if msg.get("method") == "event":
                    events.append(msg["params"])
            rows.append({"page": "chat", "check": "turn completes", "ok": True})
            res = await call("session.context_breakdown", {"session_id": sid})
            rows.append({"page": "chat", "check": "session.context_breakdown", "ok": "result" in res})

            # Model picker follows the open chat (session_id), and a desk's
            # model switch from Kantor is chat-only for a chat desk.
            opts = (await call("model.options", {"session_id": sid})).get("result") or {}
            rows.append({"page": "chat", "check": "model.options session_id (before switch)",
                         "ok": opts.get("model") == "mock-model" and opts.get("scope") == "default"
                         and "reasoning_effort" in opts and isinstance(opts.get("providers"), list),
                         "model": opts.get("model"), "scope": opts.get("scope")})
            status, body = await rest(http, "PUT", f"{base}/api/agents/session:{sid}/model",
                                      {"model": "mock-model-b"})
            rows.append({"page": "kantor", "check": "PUT /api/agents/{id}/model (chat desk)",
                         "ok": status == 200 and body.get("agent_id") == f"session:{sid}", "status": status})
            opts = (await call("model.options", {"session_id": sid})).get("result") or {}
            rows.append({"page": "chat", "check": "model.options session_id (after desk switch)",
                         "ok": opts.get("model") == "mock-model-b" and opts.get("scope") == "session",
                         "model": opts.get("model"), "scope": opts.get("scope")})
            glob = (await call("model.options", {})).get("result") or {}
            rows.append({"page": "chat", "check": "desk switch is chat-only (default unchanged)",
                         "ok": glob.get("model") == "mock-model", "model": glob.get("model")})
            status, _ = await rest(http, "PUT", f"{base}/api/agents/session:no-such-chat/model", {"model": "x"})
            rows.append({"page": "kantor", "check": "PUT /api/agents/{unknown}/model -> 404",
                         "ok": status == 404, "status": status})
            status, _ = await rest(http, "PUT", f"{base}/api/agents/session:{sid}/model", {"model": ""})
            rows.append({"page": "kantor", "check": "PUT /api/agents/{id}/model without model -> 422",
                         "ok": status == 422, "status": status})

            # Phone chat attachment: multipart upload, then the image reaches the
            # model as vision input (the mock echoes it as "[gambar <mime>, <n> B]").
            phone = (await call("session.create", {"source": "phone"}))["result"]["session_id"]
            form = aiohttp.FormData()
            form.add_field("session_id", phone)
            form.add_field("file", PNG_1PX, filename="scaled_1000.jpg", content_type="image/jpeg")
            async with http.post(f"{base}/api/uploads", data=form) as resp:
                status, up = resp.status, await resp.json()
            rows.append({"page": "chat:phone", "check": "POST /api/uploads (multipart image)",
                         "ok": status == 200 and len(str(up.get("id") or "")) == 12
                         and up.get("name") == "scaled_1000.jpg" and up.get("size") == len(PNG_1PX)
                         and up.get("kind") == "image",
                         "status": status, "name": up.get("name"), "size": up.get("size")})
            async with http.get(f"{base}{up.get('url')}") as resp:
                got = await resp.read()
            rows.append({"page": "chat:phone", "check": "GET /api/uploads/{id} (bubble thumbnail)",
                         "ok": resp.status == 200 and got == PNG_1PX, "status": resp.status})
            events.clear()
            res = await call("prompt.submit", {"session_id": phone, "text": "ini", "attachments": [up.get("id")]})
            deadline = time.monotonic() + 30
            while not any(e["type"] == "message.complete" and e.get("session_id") == phone for e in events):
                msg = await ws.receive_json(timeout=max(deadline - time.monotonic(), 0.1))
                if msg.get("method") == "event":
                    events.append(msg["params"])
            done = next(e for e in events if e["type"] == "message.complete" and e.get("session_id") == phone)
            reply = str((done.get("payload") or {}).get("text") or "")
            rows.append({"page": "chat:phone", "check": "prompt.submit with attachment -> model sees the image",
                         "ok": "result" in res and f"[gambar image/png, {len(PNG_1PX)} B]" in reply,
                         "reply": reply[-80:]})
            hist = (await call("session.history", {"session_id": phone})).get("result") or {}
            user = next((m for m in hist.get("messages", []) if m.get("role") == "user"), {})
            rows.append({"page": "chat:phone", "check": "history keeps the attachment (id, name, size)",
                         "ok": [a.get("id") for a in user.get("attachments") or []] == [up.get("id")]
                         and user["attachments"][0].get("size") == len(PNG_1PX)})

        # Thread jump marks and the page around one of them.
        status, tl = await rest(http, "GET", f"{base}/api/sessions/{sid}/timeline")
        entries = tl.get("entries") if isinstance(tl, dict) else None
        rows.append({"page": "chat", "check": "GET /api/sessions/{id}/timeline",
                     "ok": status == 200 and isinstance(entries, list) and len(entries) >= 1
                     and all("row_id" in e for e in entries), "status": status,
                     "entries": len(entries or [])})
        row_id = entries[0]["row_id"] if entries else 0
        status, ar = await rest(http, "GET", f"{base}/api/sessions/{sid}/messages/around?row_id={row_id}&limit=20")
        msgs = ar.get("messages") if isinstance(ar, dict) else None
        rows.append({"page": "chat", "check": "GET /api/sessions/{id}/messages/around",
                     "ok": status == 200 and isinstance(msgs, list) and any(m.get("row_id") == row_id for m in msgs),
                     "status": status, "returned": len(msgs or [])})

        # Logs page: the gateway really writes agent.log; level is a floor.
        status, lg = await rest(http, "GET", f"{base}/api/logs?level=INFO&lines=500")
        lines = lg.get("lines") if isinstance(lg, dict) else None
        rows.append({"page": "logs", "check": "GET /api/logs?level=INFO has turn lines",
                     "ok": status == 200 and isinstance(lines, list) and len(lines) > 0,
                     "status": status, "lines": len(lines or [])})
        for level in ("WARNING", "ERROR"):
            status, lg = await rest(http, "GET", f"{base}/api/logs?level={level}&lines=500")
            lines = lg.get("lines") if isinstance(lg, dict) else None
            floor = LEVELS.index(level)
            ok = status == 200 and isinstance(lines, list) and all(
                len(ln.split(" ", 3)) > 2 and ln.split(" ", 3)[2] in LEVELS
                and LEVELS.index(ln.split(" ", 3)[2]) >= floor for ln in lines)
            rows.append({"page": "logs", "check": f"GET /api/logs?level={level} filters", "ok": ok,
                         "status": status, "lines": len(lines or [])})

        # Skills page: toggle off/on, and the learning node edit.
        status, tg = await rest(http, "PUT", f"{base}/api/skills/toggle", {"name": SMOKE_SKILL, "enabled": False})
        status2, sk = await rest(http, "GET", f"{base}/api/skills")
        listed = next((x for x in (sk if isinstance(sk, list) else []) if x.get("name") == SMOKE_SKILL), {})
        rows.append({"page": "skill", "check": "PUT /api/skills/toggle (off)",
                     "ok": status == 200 and tg.get("ok") is True and listed.get("enabled") is False,
                     "status": status, "listed_enabled": listed.get("enabled")})
        status, tg = await rest(http, "PUT", f"{base}/api/skills/toggle", {"name": SMOKE_SKILL, "enabled": True})
        rows.append({"page": "skill", "check": "PUT /api/skills/toggle (on)",
                     "ok": status == 200 and tg.get("ok") is True, "status": status})
        status, tg = await rest(http, "PUT", f"{base}/api/skills/toggle", {"name": "no-such-skill", "enabled": False})
        rows.append({"page": "skill", "check": "PUT /api/skills/toggle unknown skill -> ok:false",
                     "ok": status == 200 and tg.get("ok") is False, "status": status})
        status, nd = await rest(http, "GET", f"{base}/api/learning/node?id={SMOKE_SKILL}")
        rows.append({"page": "skill", "check": "GET /api/learning/node",
                     "ok": status == 200 and nd.get("ok") is True and "Route smoke" in str(nd.get("content")),
                     "status": status})
        edited = "---\nname: route-smoke-skill\ndescription: edited\n---\nEdited by the route smoke.\n"
        status, ed = await rest(http, "PUT", f"{base}/api/learning/node", {"id": SMOKE_SKILL, "content": edited})
        _, nd = await rest(http, "GET", f"{base}/api/learning/node?id={SMOKE_SKILL}")
        rows.append({"page": "skill", "check": "PUT /api/learning/node (edit persists)",
                     "ok": status == 200 and ed.get("ok") is True and nd.get("content") == edited,
                     "status": status})

        # Memory panel and the GitHub account page.
        status, mem = await rest(http, "GET", f"{base}/api/memory")
        rows.append({"page": "memory", "check": "GET /api/memory (real status)",
                     "ok": status == 200 and isinstance(mem, dict) and "active" in mem,
                     "status": status, "active": (mem or {}).get("active") if isinstance(mem, dict) else None})
        status, acct = await rest(http, "GET", f"{base}/api/account/github")
        rows.append({"page": "settings:account", "check": "GET /api/account/github",
                     "ok": status == 200 and acct.get("provider") == "github"
                     and isinstance(acct.get("connected"), bool),
                     "status": status, "connected": acct.get("connected")})
        status, acct = await rest(http, "POST", f"{base}/api/account/github", {"token": ""})
        rows.append({"page": "settings:account", "check": "POST /api/account/github empty token -> ok:false",
                     "ok": status == 200 and acct.get("ok") is False and bool(acct.get("error")),
                     "status": status})

        # Kantor → Perusahaan: every company.* route the desktop tabs call (heartbeat paused: no LLM turns).
        rows += await company_checks(http, base)

    from neovarch.agent import persona_prompt
    persona = persona_prompt(sid, snap)
    rows.append({"page": "chat", "check": "persona names the desk", "ok": bool(desk.get("name"))
                 and f"**{desk.get('name')}**" in persona, "name": desk.get("name")})
    return rows


async def company_checks(http, base: str) -> list[dict]:
    rows: list[dict] = []

    async def co(method: str, body: dict | None = None, want: int = 200, check=None, label: str = ""):
        status, res = await rest(http, "POST", f"{base}/api/company/{method}", body or {})
        ok = status == want and (check(res) if check else True)
        rows.append({"page": "kantor:perusahaan", "check": f"company.{method}{label}", "ok": bool(ok), "status": status,
                     **({} if ok else {"body": str(res)[:300]})})
        return res if isinstance(res, dict) else {}

    status, snap = await rest(http, "GET", f"{base}/api/company")
    rows.append({"page": "kantor:perusahaan", "check": "GET /api/company (no company yet)",
                 "ok": status == 200 and snap == {"exists": False}, "status": status})
    await co("ticket.save", {"title": "x"}, 400, label=" without company -> 400")
    await co("setup", {"name": "Smoke Studio", "mission": "Uji rute"},
             check=lambda r: r.get("autorun") is True, label=" (heartbeat on by default)")
    # pause the heartbeat right away so the smoke makes no LLM turns (also covers the pause switch)
    await co("heartbeat", {"on": False}, check=lambda r: r.get("autorun") is False, label=" (pause)")
    snap = await co("seed_demo", check=lambda r: r.get("exists") is True and len(r.get("agents") or []) == 4)
    agents = {a["name"]: a for a in snap.get("agents") or []}
    dimas, hana = agents.get("Dimas", {}).get("id"), agents.get("Hana", {}).get("id")
    goal = await co("goal.save", {"title": "Rilis stabil"}, check=lambda r: bool(r.get("id")))
    sub = await co("goal.save", {"title": "Windows", "parent_id": goal.get("id")}, check=lambda r: bool(r.get("id")))
    await co("goal.save", {"id": goal.get("id"), "parent_id": sub.get("id")}, 400, label=" cycle -> 400")
    await co("goal.save", {"id": sub.get("id"), "title": "Windows & Linux"},
             check=lambda r: r.get("title") == "Windows & Linux", label=" (edit)")
    proj = await co("project.save", {"name": "Desktop", "goal_id": goal.get("id"), "budget_monthly_cents": 300},
                    check=lambda r: r.get("budget_monthly_cents") == 300)
    await co("project.save", {"id": proj.get("id"), "budget_monthly_cents": -1}, 400, label=" negative budget -> 400")
    await co("agent.save", {"id": hana, "budget_monthly_cents": 150, "budget_monthly_tokens": 20000,
                            "model": "mock-model", "provider": "custom"},
             check=lambda r: r.get("budget_monthly_cents") == 150 and r.get("model") == "mock-model",
             label=" (budget + model)")
    await co("agent.save", {"id": hana, "reports_to": hana}, 400, label=" self-report -> 400")
    t1 = await co("ticket.save", {"title": "Rancang sinkronisasi", "assignee_id": hana, "project_id": proj.get("id")},
                  check=lambda r: str(r.get("key", "")).startswith("NV-"))
    t2 = await co("ticket.save", {"title": "Siapkan API"}, check=lambda r: bool(r.get("id")))
    await co("ticket.block", {"id": t1.get("id"), "blocker_id": t2.get("id")})
    await co("ticket.get", {"id": t1.get("id")}, check=lambda r: [b["id"] for b in r.get("blockers") or []]
             == [t2.get("id")], label=" (blocker listed)")
    await co("ticket.block", {"id": t2.get("id"), "blocker_id": t1.get("id")}, 400, label=" cycle -> 400")
    await co("ticket.unblock", {"id": t1.get("id"), "blocker_id": t2.get("id")})
    await co("ticket.list", check=lambda r: isinstance(r.get("tickets"), list) and len(r["tickets"]) >= 3)
    await co("ticket.move", {"id": t2.get("id"), "status": "backlog"}, check=lambda r: r.get("status") == "backlog")
    await co("ticket.move", {"id": t2.get("id"), "status": "done"}, 409, label=" illegal transition -> 409")
    await co("ticket.comment", {"id": t1.get("id"), "body": "Halo dari smoke"}, check=lambda r: bool(r.get("id")))
    rt = await co("routine.save", {"name": "Ringkasan mingguan", "schedule": "every 7d", "agent_id": dimas},
                  check=lambda r: bool(r.get("next_run_at")))
    await co("routine.save", {"id": rt.get("id"), "schedule": "kapan-kapan"}, 400, label=" bad schedule -> 400")
    await co("routine.save", {"id": rt.get("id"), "enabled": False}, check=lambda r: r.get("enabled") == 0,
             label=" (disable)")
    await co("routine.trigger", {"id": rt.get("id")}, check=lambda r: r.get("assignee_id") == dimas)
    await co("routine.delete", {"id": rt.get("id")}, check=lambda r: r.get("ok") is True)
    await co("approval.list", {"status": None}, check=lambda r: isinstance(r.get("approvals"), list))
    await co("costs", check=lambda r: isinstance(r.get("by_agent"), list) and "total" in r)
    await co("activity", {"limit": 50}, check=lambda r: isinstance(r.get("items"), list) and len(r["items"]) > 5)
    await co("agent.pause", {"id": hana}, check=lambda r: r.get("status") == "paused")
    await co("agent.resume", {"id": hana}, check=lambda r: r.get("status") == "idle")
    await co("no.such", {}, 404, label=" unknown method -> 404")
    await co("project.delete", {"id": proj.get("id")}, check=lambda r: r.get("ok") is True)
    await co("goal.delete", {"id": sub.get("id")}, check=lambda r: r.get("ok") is True)
    status, snap = await rest(http, "GET", f"{base}/api/company")
    rows.append({"page": "kantor:perusahaan", "check": "GET /api/company snapshot after edits",
                 "ok": status == 200 and snap.get("exists") is True and len(snap.get("goals") or []) == 2
                 and snap["company"]["autorun"] is False, "status": status})

    # Kantor desk model popover on a company desk: that agent only, never the PC default.
    _, info_before = await rest(http, "GET", f"{base}/api/model/info")
    status, res = await rest(http, "PUT", f"{base}/api/agents/company:{dimas}/model", {"model": "mock-model"})
    _, info_after = await rest(http, "GET", f"{base}/api/model/info")
    rows.append({"page": "kantor:perusahaan", "check": "PUT /api/agents/company:<id>/model (agent scope)",
                 "ok": status == 200 and res.get("scope") == "agent" and info_before == info_after, "status": status})
    status, _ = await rest(http, "PUT", f"{base}/api/agents/company:99999/model", {"model": "mock-model"})
    rows.append({"page": "kantor:perusahaan", "check": "PUT /api/agents/company:<unknown>/model -> 404",
                 "ok": status == 404, "status": status})
    status, office = await rest(http, "GET", f"{base}/api/office")
    desks = [a for a in (office.get("agents") or []) if a.get("kind") == "company"] if isinstance(office, dict) else []
    rows.append({"page": "kantor:perusahaan", "check": "GET /api/office has the company desks",
                 "ok": status == 200 and len(desks) == 4, "status": status, "desks": len(desks)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9329)
    ap.add_argument("--llm-port", type=int, default=18090)
    ap.add_argument("--out", help="also write the JSON report to this file")
    args = ap.parse_args()
    home = Path(tempfile.mkdtemp(prefix="neovarch-routes-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERM" + "ES_", "NEOVARCH_"))}
    token = "route-smoke"
    env.update(NEOVARCH_HOME=str(home), NEOVARCH_SESSION_TOKEN=token, PYTHONPATH=str(CORE))
    (home / "config.yaml").write_text(
        "model:\n  provider: custom\n  default: mock-model\n  vision: true\n"
        f"  base_url: http://127.0.0.1:{args.llm_port}/v1\n", encoding="utf-8")
    skill = home / "skills" / SMOKE_SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: route-smoke-skill\ndescription: Route smoke\n---\nRoute smoke skill.\n",
                                   encoding="utf-8")
    os.environ["NEOVARCH_HOME"] = str(home)
    llm = subprocess.Popen([sys.executable, str(CORE / "tests" / "mock_llm.py"), "--port", str(args.llm_port),
                            "--delay", "0.3"],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv = subprocess.Popen([sys.executable, "-m", "neovarch", "serve", "--port", str(args.port)],
                           env=env, cwd=str(home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_port(args.llm_port)
        srv.stdout.readline()
        wait_port(args.port)
        rows = asyncio.run(drive(args.port, token))
        failed = [r for r in rows if not r["ok"]]
        report = json.dumps({"checks": len(rows), "failed": len(failed), "rows": rows}, indent=2, ensure_ascii=False)
        print(report)
        if args.out:
            Path(args.out).write_text(report + "\n", encoding="utf-8")
        return 1 if failed else 0
    finally:
        for p in (srv, llm):
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
