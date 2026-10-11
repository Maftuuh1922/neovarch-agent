"""The main agent as orchestrator: one place that routes "manage everything" requests.

Tools registered here (main agent only; Kantor employees never get them):

* ``manage`` — domain + action router: kantor, settings, models, skills, memory,
  schedule, devices, self_repair, status;
* ``skill_manage`` / ``memory_update`` — the agent's own skills and notes,
  versioned and undoable (:mod:`neovarch.selfedit`);
* ``settings_update`` — its own settings, persona and tool toggles, with a change log;
* ``self_diagnose`` — ``/perbaiki``: logs, failed tools, config → report + fixes;
  code patches on a local branch, applied only after approval;
* ``self_undo`` — revert the newest change; ``core_reload`` — reload after a change;
* ``plan_update`` — the checklist of the current multi-step task.

Risky actions always ask the user (desktop and phone get the same approval card),
even when approvals are switched off: code changes, deleting data, turning
approvals off, restarting the core. Secrets are never returned.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from neovarch import config as cfgmod
from neovarch import selfedit
from neovarch.selfedit import SelfEditError

# (domain, action) pairs that always need the user's yes, with the reason shown on the card.
RISKY: dict[tuple[str, str], str] = {
    ("kantor", "fire"): "memberhentikan pegawai Kantor (data pegawai dihapus)",
    ("kantor", "delete_unit"): "menghapus organisasi/agency",
    ("skills", "delete"): "menghapus skill",
    ("memory", "delete"): "menghapus catatan memori",
    ("schedule", "delete"): "menghapus jadwal",
    ("devices", "revoke"): "memutus perangkat yang dipasangkan",
    ("self_repair", "apply_patch"): "menerapkan perubahan kode aplikasi",
    ("self_repair", "restart"): "memulai ulang core Neovarch",
}
DOMAINS = ["status", "kantor", "settings", "models", "skills", "memory", "schedule", "devices", "self_repair"]


async def ask(ctx, what: str, why: str, tool: str) -> bool:
    """Always ask (ignores approvals.mode=off). Any answer but deny counts as one-time consent."""
    try:
        choice = await ctx.approve(what, why, tool)
    except Exception:
        return False
    return choice not in ("deny", "", None)


def _sid(ctx) -> str:
    return str(getattr(ctx, "session_id", "") or "")


def _gw(ctx):
    return getattr(ctx, "gateway", None)


def _fmt(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)[:8000]


# ----------------------------------------------------------------- domains --

async def _kantor(ctx, action: str, a: dict) -> str:
    if getattr(ctx, "company", None) is not None:
        return "refused: hanya agen utama Neovarch yang mengatur Kantor"
    gw = _gw(ctx)
    if action in ("pause", "resume"):
        company = getattr(gw, "company", None) if gw is not None else None
        if company is None:
            return "Kantor hanya tersedia saat core berjalan sebagai gateway desktop (neovarch serve)."
        store = company.store
        name = str(a.get("name") or a.get("employee") or "").strip()
        row = store.q1("SELECT * FROM agents WHERE lower(name)=lower(?) AND status!='terminated'", (name,))
        if not row:
            return f"error: pegawai '{name}' tidak ditemukan"
        status = "paused" if action == "pause" else "idle"
        res = store.set_agent_status(row["id"], status, reason=str(a.get("reason") or "diminta pengguna"),
                                     actor="neovarch")
        return f"{res['name']} sekarang {'dijeda' if status == 'paused' else 'aktif lagi'}."
    mapping = {"create": "hire", "assign": "assign_task", "list": "overview"}
    kact = mapping.get(action, action)
    if ctx.kantor is None:
        return "Kantor hanya tersedia saat core berjalan sebagai gateway desktop (neovarch serve)."
    return ctx.kantor({**a, "action": kact})


async def _settings(ctx, action: str, a: dict) -> str:
    if action in ("get", "list", "view"):
        return _fmt(selfedit.settings_view())
    if action in ("log", "history"):
        return selfedit.change_log(int(a.get("limit") or 20))
    if action == "persona":
        return selfedit.persona_update(str(a.get("value") or a.get("content") or ""), session_id=_sid(ctx))["message"]
    if action == "set":
        key, value = str(a.get("key") or ""), a.get("value")
        if selfedit.is_risky_setting(key, value) and not await ask(
                ctx, f"settings {key}={value}", "Mematikan semua persetujuan: perintah berbahaya akan jalan tanpa ditanya.",
                "settings_update"):
            return "denied: pengguna tidak menyetujui perubahan ini."
        res = selfedit.settings_update(key, value, session_id=_sid(ctx))
        gw = _gw(ctx)
        if gw is not None and key.startswith("model.") and hasattr(gw, "_default_changed"):
            ep = cfgmod.resolve_endpoint(cfgmod.load_config())
            gw._default_changed({"model": ep["model"], "provider": ep["provider"]})
        return f"{res['message']} ({key}: {res['before']!r} → {res['value']!r}). Pulihkan dengan /undo."
    return "error: action settings harus get, set, persona atau log"


async def _models(ctx, action: str, a: dict) -> str:
    gw = _gw(ctx)
    if action in ("list", "options"):
        from neovarch import providers
        res = providers.model_options(cfgmod.load_config(), False, None)
        rows = [f"- {p['slug']}: {', '.join((p.get('models') or [])[:15])}" for p in res.get("providers", [])]
        return "Model yang tersedia:\n" + ("\n".join(rows) or "(belum ada penyedia)")
    if action in ("set_default", "set"):
        model, provider = str(a.get("model") or a.get("value") or ""), a.get("provider")
        if not model:
            return "error: model wajib diisi"
        cfg = cfgmod.load_config()
        before = {"model": cfgmod.get_path(cfg, "model.default"), "provider": cfgmod.get_path(cfg, "model.provider")}
        if gw is not None and hasattr(gw, "set_default_model"):
            selfedit.record("config", "set", "model", None, summary=f"model bawaan → {model}", before=before,
                            after={"model": model, "provider": provider}, session_id=_sid(ctx),
                            extra={"raw_before": cfg.get("model")})
            res = gw.set_default_model(model, provider)
            return f"Model bawaan sekarang {res.get('model')} ({res.get('provider')}). Pulihkan dengan /undo."
        selfedit.settings_update("model.default", model, session_id=_sid(ctx))
        if provider:
            selfedit.settings_update("model.provider", provider, session_id=_sid(ctx))
        return f"Model bawaan sekarang {model}. Pulihkan dengan /undo."
    return "error: action models harus list atau set_default"


async def _skills(ctx, action: str, a: dict) -> str:
    if action == "delete" and not await ask(ctx, f"hapus skill {a.get('name')}", RISKY[("skills", "delete")]
                                            + " (bisa dipulihkan dengan /undo)", "skill_manage"):
        return "denied: pengguna tidak menyetujui penghapusan."
    if action in ("enable", "disable"):
        from neovarch import skills_admin
        cur = sorted(skills_admin.disabled() - {str(a.get("name"))} if action == "enable"
                     else skills_admin.disabled() | {str(a.get("name"))})
        return selfedit.settings_update("skills.disabled", cur, session_id=_sid(ctx))["message"]
    res = selfedit.skill_manage(action, str(a.get("name") or ""), content=str(a.get("content") or ""),
                                description=str(a.get("description") or ""), old_text=str(a.get("old_text") or ""),
                                new_text=str(a.get("new_text") or ""), session_id=_sid(ctx))
    return _fmt(res.get("message") or res)


async def _memory(ctx, action: str, a: dict) -> str:
    if action == "delete" and not await ask(ctx, f"hapus memori {a.get('name')}", RISKY[("memory", "delete")]
                                            + " (bisa dipulihkan dengan /undo)", "memory_update"):
        return "denied: pengguna tidak menyetujui penghapusan."
    res = selfedit.memory_update(action, str(a.get("name") or "notes"), content=str(a.get("content") or ""),
                                 old_text=str(a.get("old_text") or ""), new_text=str(a.get("new_text") or ""),
                                 session_id=_sid(ctx))
    if action == "read":
        return res.get("content") or "(kosong)"
    if action == "list":
        return "\n".join(res.get("notes") or []) or "(belum ada catatan memori)"
    return res["message"]


def _cron(ctx):
    gw = _gw(ctx)
    if gw is not None and getattr(gw, "cron", None) is not None:
        return gw.cron, gw
    from neovarch.cron import CronStore
    return CronStore(), None


async def _schedule(ctx, action: str, a: dict) -> str:
    from neovarch.cron import CronStore, ScheduleError
    store, gw = _cron(ctx)
    jid = str(a.get("id") or a.get("name") or "")

    def find() -> dict | None:
        return store.get(jid) or next((j for j in store.list() if (j.get("name") or "").lower() == jid.lower()), None)

    def changed() -> None:
        if gw is not None:
            gw.broadcast_event("cron.changed", None, {})
    try:
        if action == "list":
            jobs = [CronStore.public(j) for j in store.list()]
            return "\n".join(f"- {j['id']} {j['name']}: {j['schedule_display']} ({j['state']})" for j in jobs) \
                or "(belum ada jadwal)"
        if action == "create":
            job = store.create({"name": a.get("name"), "prompt": a.get("prompt") or a.get("content"),
                                "schedule": a.get("schedule"), "model": a.get("model")})
            changed()
            return f"Jadwal {job['id']} dibuat: {job['schedule']['display']}."
        job = find()
        if not job:
            return f"error: jadwal '{jid}' tidak ditemukan"
        if action in ("pause", "resume"):
            store.update(job["id"], {"enabled": action == "resume"})
            changed()
            return f"Jadwal {job['id']} {'dijeda' if action == 'pause' else 'dilanjutkan'}."
        if action == "delete":
            if not await ask(ctx, f"hapus jadwal {job['id']} ({job.get('name')})", RISKY[("schedule", "delete")],
                             "manage"):
                return "denied: pengguna tidak menyetujui penghapusan."
            store.delete(job["id"])
            changed()
            return f"Jadwal {job['id']} dihapus."
    except ScheduleError as exc:
        return f"error: {exc}"
    return "error: action schedule harus list, create, pause, resume atau delete"


async def _devices(ctx, action: str, a: dict) -> str:
    gw = _gw(ctx)
    lister = getattr(gw, "paired_devices", None) if gw is not None else None
    if action == "list":
        if callable(lister):
            rows = lister()
            return "\n".join(f"- {d.get('name') or d.get('id')}: {d.get('status', '')}" for d in rows) or "(tidak ada)"
        n = len(getattr(gw, "conns", []) or []) if gw is not None else 0
        return (f"{n} koneksi aktif ke core ini (desktop/HP). Daftar perangkat yang dipasangkan dan tombol putuskan "
                "ada di halaman Pasangkan HP di desktop.")
    if action == "revoke":
        revoker = getattr(gw, "revoke_device", None) if gw is not None else None
        if not callable(revoker):
            return "Memutus perangkat dilakukan dari halaman Pasangkan HP di desktop."
        if not await ask(ctx, f"putuskan perangkat {a.get('id') or a.get('name')}", RISKY[("devices", "revoke")],
                         "manage"):
            return "denied: pengguna tidak menyetujui."
        return _fmt(revoker(str(a.get("id") or a.get("name") or "")))
    return "error: action devices harus list atau revoke"


async def _status(ctx, action: str, a: dict) -> str:
    cfg = cfgmod.load_config()
    ep = cfgmod.resolve_endpoint(cfg)
    lines = [f"Model bawaan: {ep['model'] or '-'} ({ep['provider']})",
             f"Persetujuan: {cfgmod.get_path(cfg, 'approvals.mode', 'ask')}",
             f"Naik ke model kuat saat buntu: {'aktif' if cfgmod.get_path(cfg, 'agent.escalate_on_stuck') else 'mati'}"]
    if ctx.office is not None:
        from neovarch.tools import office_summary
        try:
            lines.append(office_summary(ctx.office()))
        except Exception:
            pass
    lines.append("Perubahan terakhir oleh agen:\n" + selfedit.change_log(5))
    return "\n".join(lines)


async def _self_repair(ctx, action: str, a: dict) -> str:
    return await tool_self_diagnose({**a, "action": action}, ctx)


ROUTES: dict[str, Callable[[Any, str, dict], Awaitable[str]]] = {
    "status": _status, "kantor": _kantor, "settings": _settings, "models": _models, "skills": _skills,
    "memory": _memory, "schedule": _schedule, "devices": _devices, "self_repair": _self_repair,
}


async def tool_manage(args: dict, ctx) -> str:
    domain = str(args.get("domain") or "status").strip().lower()
    action = str(args.get("action") or ("overview" if domain == "kantor" else "list" if domain != "status" else "get"))
    route = ROUTES.get(domain)
    if route is None:
        return f"error: domain harus salah satu dari {', '.join(DOMAINS)}"
    reason = RISKY.get((domain, action))
    if reason and domain == "kantor":
        if not await ask(ctx, f"kantor {action} {args.get('name') or args.get('unit') or ''}".strip(), reason, "manage"):
            return "denied: pengguna tidak menyetujui."
    try:
        return await route(ctx, action.lower(), {k: v for k, v in args.items() if k not in ("domain", "action")})
    except SelfEditError as exc:
        return f"error: {exc}"


# ------------------------------------------------------------ single tools --

async def tool_skill_manage(args: dict, ctx) -> str:
    try:
        return await _skills(ctx, str(args.get("action") or "list"), args)
    except SelfEditError as exc:
        return f"error: {exc}"


async def tool_memory_update(args: dict, ctx) -> str:
    try:
        return await _memory(ctx, str(args.get("action") or "list"), args)
    except SelfEditError as exc:
        return f"error: {exc}"


async def tool_settings_update(args: dict, ctx) -> str:
    try:
        return await _settings(ctx, str(args.get("action") or ("set" if args.get("key") else "get")), args)
    except SelfEditError as exc:
        return f"error: {exc}"


async def tool_self_undo(args: dict, ctx) -> str:
    if args.get("action") == "log":
        return selfedit.change_log(int(args.get("limit") or 20))
    entry = next((e for e in reversed(selfedit.entries(500, include_undone=False))
                  if not args.get("change_id") or e["id"] == args.get("change_id")), None)
    if entry and entry.get("kind") == "code" and not await ask(
            ctx, f"git revert {str(entry.get('commit'))[:10]}", "membatalkan patch kode aplikasi", "self_undo"):
        return "denied: pengguna tidak menyetujui."
    res = selfedit.undo(args.get("change_id") or None, session_id=_sid(ctx))
    return res["message"]


async def tool_self_diagnose(args: dict, ctx) -> str:
    from neovarch import diagnose, selfpatch
    action = str(args.get("action") or "diagnose")
    gw = _gw(ctx)
    if action in ("diagnose", "report"):
        res = diagnose.run(getattr(gw, "store", None), _sid(ctx), apply=args.get("apply", True) is not False)
        return res["report"]
    if action == "collect":
        return _fmt(diagnose.collect(getattr(gw, "store", None)))
    if action == "prepare_patch":
        if selfpatch.source_checkout() is None:
            return ("Instalasi ini terpaket (bukan git checkout), jadi kode aplikasi tidak diubah. "
                    "Perbaikan kode datang lewat Pembaruan aplikasi.")
        try:
            meta = selfpatch.prepare(str(args.get("diff") or ""), str(args.get("title") or "perbaikan"),
                                     test_cmd=str(args.get("test_cmd") or ""))
        except selfpatch.PatchError as exc:
            return f"error: {exc}"
        return (selfpatch.summary(meta) + "\nBelum diterapkan. Panggil self_diagnose action=apply_patch "
                f"patch_id={meta['id']} — pengguna akan diminta menekan Setujui.")
    if action == "apply_patch":
        pid = str(args.get("patch_id") or "")
        try:
            meta = selfpatch.load(pid)
        except selfpatch.PatchError as exc:
            return f"error: {exc}"
        why = (f"Menerapkan patch kode '{meta['title']}' ke {meta['repo']} (file: {', '.join(meta.get('files') or [])}; "
               f"tes: {'lulus' if meta.get('tests_ok') else 'GAGAL' if meta.get('tests_ok') is False else 'tidak ada'}). "
               "Bisa dibatalkan dengan /undo.")
        if not await ask(ctx, f"git cherry-pick {str(meta.get('commit'))[:10]} ({meta['branch']})", why, "self_diagnose"):
            return "denied: pengguna tidak menyetujui patch ini; tidak ada yang diubah."
        try:
            res = selfpatch.apply(pid, session_id=_sid(ctx))
        except selfpatch.PatchError as exc:
            return f"error: {exc}"
        return (f"Patch diterapkan di {res['applied_on']} (commit {res['applied_commit'][:10]}). "
                "Muat ulang core dengan core_reload action=restart agar kode baru dipakai.")
    if action == "undo":
        return await tool_self_undo(args, ctx)
    if action in ("reload", "restart"):
        return await tool_core_reload({"action": action}, ctx)
    return "error: action harus diagnose, collect, prepare_patch, apply_patch, undo, reload atau restart"


async def tool_core_reload(args: dict, ctx) -> str:
    """soft: re-read skills/config/model catalog in place. restart: re-exec the core after this turn."""
    action = str(args.get("action") or "soft")
    gw = _gw(ctx)
    if action in ("soft", "reload"):
        from neovarch.tools import ensure_builtin_skills, list_skills
        ensure_builtin_skills()
        n = len(list_skills())
        if gw is not None:
            if getattr(gw, "catalog", None) is not None:
                gw.catalog.fetched_at = 0.0
            gw.broadcast_event("skills.changed", None, {"count": n})
            gw.broadcast_event("config.changed", None, {"reloaded": True})
            for live in list(getattr(gw, "live", {}).values()):
                gw.broadcast_event("session.info", live.id, live.info())
        return f"Core dimuat ulang tanpa memutus sesi: {n} skill aktif, pengaturan dan daftar model dibaca ulang."
    if action == "restart":
        if gw is None or not hasattr(gw, "request_restart"):
            return "Restart penuh hanya tersedia saat core berjalan sebagai gateway (neovarch serve)."
        if not await ask(ctx, "restart core Neovarch", RISKY[("self_repair", "restart")]
                         + "; obrolan tetap tersimpan dan hasilnya dilaporkan di sini.", "core_reload"):
            return "denied: pengguna tidak menyetujui restart."
        gw.request_restart(_sid(ctx))
        return "Core akan dimulai ulang setelah giliran ini selesai; hasilnya akan muncul di obrolan ini."
    return "error: action harus soft atau restart"


async def tool_plan_update(args: dict, ctx) -> str:
    """Keep the current task's checklist on the session (shown to the user as a plan)."""
    steps = args.get("steps") or []
    if isinstance(steps, str):
        steps = [s.strip("-• ").strip() for s in steps.splitlines() if s.strip()]
    clean = []
    for s in steps[:12]:
        if isinstance(s, dict):
            title = str(s.get("title") or s.get("step") or "").strip()
            status = str(s.get("status") or "todo").lower()
        else:
            title, status = str(s).strip(), "todo"
        if title:
            clean.append({"title": title[:160], "status": status if status in ("todo", "doing", "done", "blocked")
                          else "todo"})
    if not clean:
        return "error: steps wajib berisi 1-12 langkah"
    setter = getattr(ctx, "set_plan", None)
    if callable(setter):
        setter(clean)
    mark = {"todo": "[ ]", "doing": "[~]", "done": "[x]", "blocked": "[!]"}
    return "Rencana:\n" + "\n".join(f"{mark[s['status']]} {s['title']}" for s in clean)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, **({"required": required} if required else {})}


S = {"type": "string"}
SCHEMAS: dict[str, dict] = {
    "manage": {
        "description": "Manage everything in this Neovarch install as the main agent. domain: status | kantor "
                       "(overview, create=hire, assign, pause, resume, set_employee, fire, create_org, create_agency, "
                       "move, delete_unit) | settings (get, set key/value, persona, log) | models (list, set_default) | "
                       "skills (list, view, create, edit, patch, delete, enable, disable) | memory (list, read, write, "
                       "append, replace, delete) | schedule (list, create name/prompt/schedule, pause, resume, delete) | "
                       "devices (list, revoke) | self_repair (diagnose, prepare_patch, apply_patch, undo, reload, "
                       "restart). Risky actions ask the user first.",
        "parameters": _obj({"domain": {"type": "string", "enum": DOMAINS}, "action": S, "name": S, "key": S,
                            "value": {}, "model": S, "provider": S, "content": S, "description": S,
                            "old_text": S, "new_text": S, "prompt": S, "schedule": S, "id": S, "title": S,
                            "employee": S, "unit": S, "reason": S, "diff": S, "patch_id": S},
                           ["domain"])},
    "skill_manage": {
        "description": "Create or improve your own skills (SKILL.md under the user's data folder). action: list | "
                       "view | create (name, description, content) | edit (name, content) | patch (name, old_text, "
                       "new_text) | delete (asks the user). Every change is backed up; /undo restores it. Save "
                       "procedures, pitfalls and the user's preferences for a kind of task here.",
        "parameters": _obj({"action": {"type": "string", "enum": ["list", "view", "create", "edit", "patch", "delete",
                                                                  "enable", "disable"]},
                            "name": S, "description": S, "content": S, "old_text": S, "new_text": S}, ["action"])},
    "memory_update": {
        "description": "Your long-term memory notes (facts true in every session, written as facts, not orders). "
                       "action: list | read | write | append | replace (old_text→new_text) | delete (asks the user). "
                       "Backed up and undoable with /undo.",
        "parameters": _obj({"action": {"type": "string", "enum": ["list", "read", "write", "append", "replace",
                                                                  "delete"]},
                            "name": S, "content": S, "old_text": S, "new_text": S}, ["action"])},
    "settings_update": {
        "description": "Read or change your own settings through the settings API, with a change log. action: get | "
                       "set (key, value) | persona (value = new persona text) | log. Allowed keys: "
                       + ", ".join(selfedit.SETTINGS) + ". Secrets/API keys are not editable here.",
        "parameters": _obj({"action": {"type": "string", "enum": ["get", "set", "persona", "log"]}, "key": S,
                            "value": {}}, ["action"])},
    "self_diagnose": {
        "description": "Diagnose and repair yourself (same as /perbaiki). action: diagnose (logs, failed tools, config "
                       "→ Indonesian report; safe config/skill fixes applied, undoable) | collect (raw redacted data) | "
                       "prepare_patch (diff, title, test_cmd?: builds the fix on a NEW local git branch and runs tests; "
                       "source installs only) | apply_patch (patch_id; asks the user to tap Setujui) | undo | reload | "
                       "restart.",
        "parameters": _obj({"action": {"type": "string", "enum": ["diagnose", "collect", "prepare_patch", "apply_patch",
                                                                  "undo", "reload", "restart"]},
                            "diff": S, "title": S, "test_cmd": S, "patch_id": S, "apply": {"type": "boolean"}},
                           ["action"])},
    "self_undo": {
        "description": "Restore the previous version: undo your newest change to a skill, memory note, setting, "
                       "persona or code patch (or change_id). action=log lists the change log.",
        "parameters": _obj({"action": {"type": "string", "enum": ["undo", "log"]}, "change_id": S})},
    "core_reload": {
        "description": "Apply a change without killing the chat. action: soft (re-read skills, settings and models "
                       "now) | restart (restart the core process after this turn; asks the user; result is reported "
                       "back in this chat).",
        "parameters": _obj({"action": {"type": "string", "enum": ["soft", "restart"]}})},
    "plan_update": {
        "description": "Write or update the checklist for the current multi-step task (2-12 short steps, status todo | "
                       "doing | done | blocked). Call it at the start of multi-step work and as steps finish.",
        "parameters": _obj({"steps": {"type": "array", "items": _obj({"title": S, "status": {
            "type": "string", "enum": ["todo", "doing", "done", "blocked"]}}, ["title"])}}, ["steps"])},
}

TOOLS: dict[str, tuple[Callable[[dict, Any], Awaitable[str]], dict]] = {
    "manage": (tool_manage, SCHEMAS["manage"]),
    "skill_manage": (tool_skill_manage, SCHEMAS["skill_manage"]),
    "memory_update": (tool_memory_update, SCHEMAS["memory_update"]),
    "settings_update": (tool_settings_update, SCHEMAS["settings_update"]),
    "self_diagnose": (tool_self_diagnose, SCHEMAS["self_diagnose"]),
    "self_undo": (tool_self_undo, SCHEMAS["self_undo"]),
    "core_reload": (tool_core_reload, SCHEMAS["core_reload"]),
    "plan_update": (tool_plan_update, SCHEMAS["plan_update"]),
}
# Employees get only the checklist; everything that changes the install is the main agent's.
EMPLOYEE_ALLOWED = {"plan_update"}
