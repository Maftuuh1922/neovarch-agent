"""Self-repair: versioned skills/memory with undo, settings change log, approval gating,
log redaction, orchestrator routing, /undo and /perbaiki, code patches on a local branch."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from neovarch import config as cfgmod
from neovarch import diagnose, orchestrator, selfedit, selfpatch
from neovarch.agent import Agent
from neovarch.paths import neovarch_home
from neovarch.store import SessionStore
from neovarch.tools import ToolContext, run_tool, tool_schemas


class Approver:
    def __init__(self, answer="once"):
        self.answer = answer
        self.asked = []

    async def __call__(self, command, description, tool):
        self.asked.append((command, description, tool))
        return self.answer


def ctx_for(tmp_path, answer="once", **kw):
    appr = Approver(answer)
    return ToolContext(cwd=tmp_path, approve=appr, **kw), appr


# ------------------------------------------------------ skills + backups --

def test_skill_create_edit_patch_and_undo_chain(home):
    r = selfedit.skill_manage("create", "deploy notes", description="Cara deploy", content="# Deploy\n- langkah 1")
    doc = Path(r["path"])
    assert doc.parent.name == "deploy-notes" and "description: Cara deploy" in doc.read_text()
    selfedit.skill_manage("patch", "deploy-notes", old_text="langkah 1", new_text="langkah 1 (cek tes)")
    assert "cek tes" in doc.read_text()
    selfedit.skill_manage("edit", "deploy-notes", content="# Deploy v3")
    assert "Deploy v3" in doc.read_text()
    assert selfedit.undo()["ok"] and "cek tes" in doc.read_text()          # back to the patched version
    assert selfedit.undo()["ok"] and "cek tes" not in doc.read_text()      # back to the original
    assert selfedit.undo()["ok"] and not doc.exists()                      # creation undone (moved aside)
    assert not selfedit.undo()["ok"]                                        # nothing left to undo
    assert any((neovarch_home() / "self" / "backups").rglob("SKILL.md"))  # nothing was destroyed


def test_skill_delete_is_recoverable(home):
    selfedit.skill_manage("create", "tmp-skill", content="isi")
    selfedit.skill_manage("delete", "tmp-skill")
    assert not (neovarch_home() / "skills" / "tmp-skill").exists()
    selfedit.undo()
    assert (neovarch_home() / "skills" / "tmp-skill" / "SKILL.md").read_text().strip().endswith("isi")


def test_memory_versioned(home):
    selfedit.memory_update("write", "USER", content="Pengguna suka jawaban singkat.")
    selfedit.memory_update("append", "USER", content="Zona waktu WIB.")
    note = neovarch_home() / "memory" / "USER.md"
    assert note.read_text().count("\n") == 2
    selfedit.undo()
    assert note.read_text() == "Pengguna suka jawaban singkat."
    with pytest.raises(selfedit.SelfEditError):
        selfedit.memory_update("replace", "USER", old_text="tidak ada", new_text="x")


# ----------------------------------------------------------- settings --

def test_settings_change_log_and_undo(home):
    res = selfedit.settings_update("agent.max_turns", "12")
    assert res["value"] == 12 and cfgmod.get_path(cfgmod.load_config(), "agent.max_turns") == 12
    selfedit.settings_update("agent.escalate_on_stuck", "ya")
    assert cfgmod.get_path(cfgmod.load_config(), "agent.escalate_on_stuck") is True
    log = selfedit.change_log()
    assert "agent.max_turns" in log and "Naik ke model lebih kuat" in log
    selfedit.undo()
    selfedit.undo()
    cfg = cfgmod.load_config()
    assert cfgmod.get_path(cfg, "agent.max_turns") == 150 and not cfgmod.get_path(cfg, "agent.escalate_on_stuck")


def test_settings_whitelist_and_protected_tools(home):
    with pytest.raises(selfedit.SelfEditError):
        selfedit.settings_update("router9.api_key", "sk-secret-123456")
    with pytest.raises(selfedit.SelfEditError):
        selfedit.settings_update("tools.disabled", ["self_diagnose"])
    with pytest.raises(selfedit.SelfEditError):
        selfedit.settings_update("agent.max_turns", 0)
    selfedit.settings_update("tools.disabled", ["web_fetch"])
    names = {s["function"]["name"] for s in tool_schemas(ToolContext(cwd=Path("."), approve=None))}
    assert "web_fetch" not in names and "self_diagnose" in names and "manage" in names


def test_persona_update_and_undo(home):
    before = cfgmod.soul_text()
    selfedit.persona_update("Kamu Neovarch, santai dan singkat.")
    assert "santai" in cfgmod.soul_text()
    selfedit.undo()
    assert cfgmod.soul_text() == before


# ------------------------------------------------------- approval gating --

async def test_turning_approvals_off_needs_approval(home, tmp_path):
    ctx, appr = ctx_for(tmp_path, "deny")
    out = await run_tool("settings_update", {"action": "set", "key": "approvals.mode", "value": "off"}, ctx)
    assert out.startswith("denied") and cfgmod.get_path(cfgmod.load_config(), "approvals.mode") == "ask"
    assert appr.asked and appr.asked[0][2] == "settings_update"


async def test_delete_asks_even_with_approvals_off(home, tmp_path):
    selfedit.skill_manage("create", "keep-me", content="isi")
    ctx, appr = ctx_for(tmp_path, "deny")
    ctx.approvals_mode = "off"
    out = await run_tool("skill_manage", {"action": "delete", "name": "keep-me"}, ctx)
    assert out.startswith("denied") and (neovarch_home() / "skills" / "keep-me").exists()
    appr.answer = "once"
    out = await run_tool("manage", {"domain": "memory", "action": "write", "name": "x", "content": "y"}, ctx)
    assert "disimpan" in out
    out = await run_tool("manage", {"domain": "memory", "action": "delete", "name": "x"}, ctx)
    assert "dihapus" in out and len(appr.asked) == 2


async def test_shell_outside_workspace_needs_approval(home, tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    ctx, appr = ctx_for(work, "deny")
    ctx.approvals_mode = "off"
    out = await run_tool("shell", {"command": "echo hi", "workdir": str(outside)}, ctx)
    assert out.startswith("denied") and "luar folder kerja" in appr.asked[0][1]
    out = await run_tool("shell", {"command": "echo hi"}, ctx)
    assert "hi" in out and len(appr.asked) == 1


async def test_code_patch_apply_needs_approval(home, tmp_path, monkeypatch):
    ctx, appr = ctx_for(tmp_path, "deny")
    applied = []
    monkeypatch.setattr(selfpatch, "load", lambda pid: {"id": pid, "title": "fix", "repo": "/r", "files": ["a.py"],
                                                        "tests_ok": True, "commit": "abc123", "branch": "perbaikan/x",
                                                        "status": "ready"})
    monkeypatch.setattr(selfpatch, "apply", lambda pid, session_id="": applied.append(pid))
    out = await run_tool("self_diagnose", {"action": "apply_patch", "patch_id": "p1"}, ctx)
    assert out.startswith("denied") and not applied and appr.asked[0][2] == "self_diagnose"


async def test_employees_cannot_touch_the_install(home, tmp_path):
    class Emp:
        def allowed_tools(self):
            return None

        def tool_schemas(self):
            return []

        def tool_names(self):
            return set()

    ctx = ToolContext(cwd=tmp_path, approve=Approver(), company=Emp())
    names = {s["function"]["name"] for s in tool_schemas(ctx)}
    assert "plan_update" in names
    assert not names & {"manage", "skill_manage", "settings_update", "self_diagnose", "core_reload", "self_undo"}
    out = await run_tool("manage", {"domain": "status"}, ctx)
    assert out.startswith("refused")


# ------------------------------------------------------------ redaction --

def test_log_collection_redacts_secrets(home):
    cfgmod.write_env_value("OPENROUTER_API_KEY", "or-very-secret-value-42")
    cfg = cfgmod.load_config()
    cfg["custom_providers"] = [{"name": "X", "base_url": "https://u:pw123456@api.example.com/v1",
                                "api_key": "plain-key-in-config", "key_env": "OPENROUTER_API_KEY"}]
    cfgmod.save_config(cfg)
    logs = neovarch_home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "errors.log").write_text(
        "2026-10-11 10:00:00 WARNING neovarch: HTTP 401 Authorization: Bearer abcdefghijklmnop1234\n"
        "2026-10-11 10:00:01 ERROR neovarch: token=ghp_ABCDEFGHIJKLMNOPQRSTUV key or-very-secret-value-42\n"
        "2026-10-11 10:00:02 ERROR neovarch: url https://x.test/?api_key=zzzzzzzz sk-ant-REDACTME0123456789\n")
    data = diagnose.collect()
    blob = repr(data)
    for secret in ("abcdefghijklmnop1234", "ghp_ABCDEFGHIJKLMNOPQRSTUV", "or-very-secret-value-42", "zzzzzzzz",
                   "sk-ant-REDACTME0123456789", "plain-key-in-config", "pw123456"):
        assert secret not in blob, secret
    assert data["config"]["custom_providers"][0]["key_env"] == "OPENROUTER_API_KEY"
    res = diagnose.run(apply=False)
    assert "Kunci API ditolak" in res["report"] and "or-very-secret" not in res["report"]


def test_failed_tool_calls_are_collected(home):
    store = SessionStore()
    rec = store.create()
    rec["messages"] = [{"role": "user", "content": "x"},
                       {"role": "assistant", "content": None, "tool_calls": [
                           {"id": "1", "function": {"name": "read_file", "arguments": '{"path": "/nope"}'}}]},
                       {"role": "tool", "tool_call_id": "1", "name": "read_file", "content": "error: not found: /nope"},
                       {"role": "assistant", "content": None, "tool_calls": [
                           {"id": "2", "function": {"name": "read_file", "arguments": '{"path": "/nope2"}'}}]},
                       {"role": "tool", "tool_call_id": "2", "name": "read_file", "content": "error: not found: /nope2"}]
    store.save(rec)
    res = diagnose.run(store)
    assert any(f["id"] == "tool-read_file" for f in res["findings"])
    assert "tool-read_file" in res["applied"]  # learned into a skill, undoable
    assert (neovarch_home() / "skills" / "catatan-perbaikan" / "SKILL.md").exists()


# ------------------------------------------------------ orchestrator routing --

async def test_manage_routes_kantor_with_mapped_actions(home, tmp_path):
    seen = []
    ctx, _ = ctx_for(tmp_path, kantor=lambda a: seen.append(a) or "ok")
    assert await run_tool("manage", {"domain": "kantor", "action": "create", "name": "Raka", "title": "Dev"}, ctx) == "ok"
    await run_tool("manage", {"domain": "kantor", "action": "assign", "employee": "Raka", "title": "Tes"}, ctx)
    await run_tool("manage", {"domain": "kantor"}, ctx)
    assert [a["action"] for a in seen] == ["hire", "assign_task", "overview"]
    assert seen[0]["name"] == "Raka" and "domain" not in seen[0]


async def test_manage_kantor_fire_asks_first(home, tmp_path):
    seen = []
    ctx, appr = ctx_for(tmp_path, "deny", kantor=lambda a: seen.append(a) or "ok")
    out = await run_tool("manage", {"domain": "kantor", "action": "fire", "name": "Raka"}, ctx)
    assert out.startswith("denied") and not seen and appr.asked


async def test_manage_kantor_pause_resume(home, tmp_path):
    class Store:
        def __init__(self):
            self.status = "idle"

        def q1(self, sql, args):
            return {"id": 7, "name": "Raka"} if args[0].lower() == "raka" else None

        def set_agent_status(self, aid, status, reason=None, actor="user"):
            self.status = status
            return {"name": "Raka", "status": status}

    class Company:
        store = Store()

    class GW:
        company = Company()

    ctx, _ = ctx_for(tmp_path, gateway=GW(), kantor=lambda a: "x")
    assert "dijeda" in await run_tool("manage", {"domain": "kantor", "action": "pause", "name": "raka"}, ctx)
    assert GW.company.store.status == "paused"
    assert "aktif" in await run_tool("manage", {"domain": "kantor", "action": "resume", "name": "Raka"}, ctx)
    assert "tidak ditemukan" in await run_tool("manage", {"domain": "kantor", "action": "pause", "name": "Budi"}, ctx)


async def test_manage_schedule_lifecycle(home, tmp_path):
    ctx, appr = ctx_for(tmp_path)
    out = await run_tool("manage", {"domain": "schedule", "action": "create", "name": "pagi",
                                    "prompt": "ringkas berita", "schedule": "daily 08:00"}, ctx)
    assert "dibuat" in out
    assert "dijeda" in await run_tool("manage", {"domain": "schedule", "action": "pause", "name": "pagi"}, ctx)
    assert "paused" in await run_tool("manage", {"domain": "schedule", "action": "list"}, ctx)
    assert "dilanjutkan" in await run_tool("manage", {"domain": "schedule", "action": "resume", "name": "pagi"}, ctx)
    assert "dihapus" in await run_tool("manage", {"domain": "schedule", "action": "delete", "name": "pagi"}, ctx)
    assert appr.asked  # delete asked
    assert "error" in await run_tool("manage", {"domain": "schedule", "action": "create", "prompt": "x",
                                                "schedule": "kapan-kapan"}, ctx)


async def test_manage_settings_skills_status_and_unknown(home, tmp_path):
    ctx, _ = ctx_for(tmp_path)
    out = await run_tool("manage", {"domain": "settings", "action": "set", "key": "agent.max_turns", "value": 9}, ctx)
    assert "/undo" in out and cfgmod.get_path(cfgmod.load_config(), "agent.max_turns") == 9
    out = await run_tool("manage", {"domain": "skills", "action": "create", "name": "s1", "content": "x"}, ctx)
    assert "dibuat" in out
    assert "Model bawaan" in await run_tool("manage", {"domain": "status"}, ctx)
    assert "Pasangkan HP" in await run_tool("manage", {"domain": "devices", "action": "list"}, ctx)
    assert "domain harus" in await run_tool("manage", {"domain": "teleport"}, ctx)
    assert "error" in await run_tool("manage", {"domain": "settings", "action": "set", "key": "x.y", "value": 1}, ctx)


async def test_plan_update_reaches_the_session(home, tmp_path):
    got = []
    ctx, _ = ctx_for(tmp_path, set_plan=got.append)
    out = await run_tool("plan_update", {"steps": [{"title": "Baca kode", "status": "done"},
                                                   {"title": "Ubah", "status": "doing"}, "Tes"]}, ctx)
    assert "[x] Baca kode" in out and "[~] Ubah" in out and "[ ] Tes" in out
    assert got and got[0][2] == {"title": "Tes", "status": "todo"}


# ---------------------------------------------------------- chat commands --

async def _no_model(*_a, **_k):
    raise AssertionError("the model must not be called")


async def test_undo_command_without_model(home, tmp_path, monkeypatch):
    monkeypatch.setattr(Agent, "_stream", _no_model)
    selfedit.memory_update("write", "fakta", content="v1")
    selfedit.memory_update("write", "fakta", content="v2")
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    events = []
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=Approver()), lambda k, p: events.append((k, p)))
    out = await agent.run_turn("Pulihkan versi sebelumnya")
    assert "Dipulihkan" in out and (neovarch_home() / "memory" / "fakta.md").read_text() == "v1"
    assert events[-1][0] == "message.complete" and events[-1][1]["command"] == "undo"
    assert "Dipulihkan" in await agent.run_turn("/undo") and not (neovarch_home() / "memory" / "fakta.md").exists()


async def test_perbaiki_command_reports_without_model(home, tmp_path, monkeypatch):
    monkeypatch.setattr(Agent, "_stream", _no_model)
    store = SessionStore()
    rec = store.create(cwd=str(tmp_path))
    agent = Agent(rec, store, ToolContext(cwd=tmp_path, approve=Approver()), lambda k, p: None)
    out = await agent.run_turn("/fix")
    assert out.startswith("**Diagnosis Neovarch**") and "**Bukti**" in out and "**Batasan**" in out


# --------------------------------------------------------------- code patch --

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_code_patch_on_local_branch_then_apply_and_undo(home, tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "mod.py").write_text("def answer():\n    return 41\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    diff = ("diff --git a/mod.py b/mod.py\n--- a/mod.py\n+++ b/mod.py\n@@ -1,2 +1,2 @@\n def answer():\n"
            "-    return 41\n+    return 42\n")
    meta = selfpatch.prepare(diff, "jawaban benar", repo=repo,
                             test_cmd=f"{sys.executable} -c \"import mod; assert mod.answer()==42\"")
    assert meta["status"] == "ready" and meta["tests_ok"] is True and meta["branch"].startswith("perbaikan/")
    assert "return 41" in (repo / "mod.py").read_text()          # user's checkout untouched until approval
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    res = selfpatch.apply(meta["id"])
    assert "return 42" in (repo / "mod.py").read_text() and res["applied_on"] == "main"
    assert selfedit.undo()["ok"]
    assert "return 41" in (repo / "mod.py").read_text()          # reverted with git revert


def test_packaged_install_is_never_patched(tmp_path):
    assert selfpatch.source_checkout(tmp_path / "x" / "app.asar" / "core" / "selfpatch.py") is None
    assert selfpatch.source_checkout(tmp_path / "lib" / "site-packages" / "neovarch" / "selfpatch.py") is None


# ---- composer catalog, per-chat reasoning and the "Agen" settings -----------
async def test_composer_catalog_and_per_chat_reasoning(mock_provider, monkeypatch):
    from neovarch import session_settings as ss
    from neovarch.server import config_schema_payload
    from test_server import WS, _client

    schema = config_schema_payload()
    assert "agent" in schema["category_order"]
    assert schema["fields"]["agent.escalate_on_stuck"]["category"] == "agent"
    gw, c = await _client(monkeypatch, NEOVARCH_SESSION_TOKEN="tok")
    try:
        ws = WS(await c.ws_connect("/api/ws?token=tok"))
        await ws.pump()
        sid = (await ws.call("session.create", {"source": "phone"}))["result"]["session_id"]
        cat = await (await c.get(f"/api/composer/catalog?session_id={sid}&token=tok")).json()
        assert cat["reasoning"]["supported"] and "ultra" in cat["reasoning"]["levels"]
        assert {"perbaiki", "undo"} <= {x["name"] for x in cat["commands"]}
        r = await c.patch(f"/api/sessions/{sid}?token=tok", json={"reasoning_effort": "high"})
        assert r.status == 200 and (await r.json())["reasoning_effort"] == "high"
        cat = await (await c.get(f"/api/composer/catalog?session_id={sid}&token=tok")).json()
        assert cat["reasoning"]["current"] == "high"
        assert (await c.patch(f"/api/sessions/{sid}?token=tok", json={"reasoning_effort": "banana"})).status == 422
        # A model that rejected the parameter hides the levels, even after a restart (on disk).
        ss.mark_no_reasoning(cat["models"]["model"])
        ss._NO_REASONING.clear()
        cat = await (await c.get(f"/api/composer/catalog?session_id={sid}&token=tok")).json()
        assert cat["reasoning"]["supported"] is False and cat["reasoning"]["levels"] == []
    finally:
        await c.close()
