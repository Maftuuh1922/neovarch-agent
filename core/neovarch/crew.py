"""Crew: a small team of agents the main agent puts together for one goal.

The user only states the goal. The main agent designs the crew - members (role, goal,
tools, model), tasks and the flow (``sequential``: each task in order, every member sees
the earlier results; ``hierarchical``: a manager member delegates, reviews each result
once and writes the final answer). The design is shown as a *proposal*; nothing runs
until the user approves it, and tools with side effects (writing files, running
commands) need an explicit extra consent on top of that. Every change made through the
"Lanjutan" (advanced) editor goes through the same validation.

Free models only: a member's model must be a free model (``router9.is_free_model``);
anything else is replaced by the free default when the crew runs.

This module is independent of the Kantor/Perusahaan (``company.py``) store; the
``office.*`` and ``company.*`` RPCs are untouched. The engine takes two injected
callables so it can be tested without a model:

* ``ask(prompt) -> str``: one plain completion by the main agent (the designer, and the
  manager's review/synthesis in hierarchical crews);
* ``run_member(crew, member, prompt) -> str``: one turn by a crew member with only its
  allowed tools.

RPCs (``Gateway.dispatch``): ``crew.templates``, ``crew.list``, ``crew.get``,
``crew.propose``, ``crew.update``, ``crew.approve``, ``crew.cancel``, ``crew.delete``.
REST: ``GET /api/crew``, ``POST /api/crew/{method}``. Push: ``crew.update`` events.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable

MAX_MEMBERS = 5
MAX_TASKS = 8
OUTPUT_CLIP = 6000
CONTEXT_CLIP = 2500
LOG_MAX = 80
KEEP_CREWS = 30

PROCESSES = ("sequential", "hierarchical")

# Tool groups a member can get. ``side_effect`` groups change the PC and need consent.
TOOL_GROUPS: dict[str, dict[str, Any]] = {
    "web": {"tools": ["web_search", "web_fetch"], "side_effect": False},
    "files": {"tools": ["read_file", "grep", "glob", "repo_map"], "side_effect": False},
    "write": {"tools": ["write_file", "edit_file", "apply_patch"], "side_effect": True},
    "shell": {"tools": ["shell", "shell_job"], "side_effect": True},
}

STATUSES = ("proposed", "running", "done", "failed", "cancelled")
MEMBER_STATUSES = ("idle", "working", "reviewing", "waiting", "done", "error")


class CrewError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _m(mid, name, role, goal, tools, avatar):
    return {"id": mid, "name": name, "role": role, "goal": goal, "tools": tools, "model": "", "avatar": avatar}


def _t(tid, title, description, expected, member_id):
    return {"id": tid, "title": title, "description": description, "expected_output": expected, "member_id": member_id}


TEMPLATES: dict[str, dict[str, Any]] = {
    "riset": {
        "label": "Riset", "process": "sequential",
        "summary": "Cari sumber, cek fakta, rangkum temuan.",
        "members": [
            _m("m1", "Rani", "Peneliti", "Menemukan sumber terpercaya tentang tujuan", ["web", "files"], 1),
            _m("m2", "Bayu", "Analis", "Memeriksa fakta dan menyusun ringkasan yang jujur", ["web"], 4),
        ],
        "tasks": [
            _t("t1", "Kumpulkan sumber", "Cari 5-8 sumber terpercaya tentang: {goal}. Catat poin penting tiap sumber "
               "dengan tautannya.", "Daftar sumber + poin penting", "m1"),
            _t("t2", "Analisis & ringkas", "Bandingkan temuan, tandai yang bertentangan atau belum pasti, lalu tulis "
               "ringkasan untuk: {goal}.", "Ringkasan 5-10 poin dengan sumber", "m2"),
        ],
    },
    "konten": {
        "label": "Konten", "process": "sequential",
        "summary": "Rencana, tulis, lalu sunting satu konten.",
        "members": [
            _m("m1", "Sekar", "Perencana konten", "Menentukan audiens, sudut pandang dan kerangka", ["web"], 2),
            _m("m2", "Dimas", "Penulis", "Menulis draf yang jelas dan enak dibaca", [], 5),
            _m("m3", "Laras", "Editor", "Merapikan bahasa, fakta dan panjang tulisan", [], 7),
        ],
        "tasks": [
            _t("t1", "Kerangka", "Tentukan audiens, pesan utama dan kerangka untuk: {goal}.", "Kerangka bernomor", "m1"),
            _t("t2", "Draf", "Tulis draf lengkap mengikuti kerangka.", "Draf siap sunting", "m2"),
            _t("t3", "Sunting", "Sunting draf: perjelas, potong yang bertele-tele, cek fakta. Kembalikan versi final.",
               "Konten final", "m3"),
        ],
    },
    "coding": {
        "label": "Coding", "process": "hierarchical", "manager": "m1",
        "summary": "Manajer membagi kerja ke perancang, programmer, penguji.",
        "members": [
            _m("m1", "Arga", "Manajer teknis", "Membagi kerja, memeriksa hasil, menulis ringkasan akhir", ["files"], 3),
            _m("m2", "Nadia", "Perancang", "Membaca kode dan menyusun rencana perubahan", ["files"], 6),
            _m("m3", "Fajar", "Programmer", "Menerapkan perubahan sesuai rencana", ["files", "write", "shell"], 0),
            _m("m4", "Wulan", "Penguji", "Menjalankan tes dan melaporkan yang gagal", ["files", "shell"], 8),
        ],
        "tasks": [
            _t("t1", "Rencana", "Baca kode yang relevan dan tulis rencana perubahan untuk: {goal}.",
               "Rencana: file yang diubah + langkah", "m2"),
            _t("t2", "Implementasi", "Terapkan rencana. Ubah sesedikit mungkin.", "Daftar perubahan", "m3"),
            _t("t3", "Uji", "Jalankan tes yang relevan, laporkan hasil dan perbaiki kegagalan kecil.",
               "Hasil tes", "m4"),
        ],
    },
    "riset_laporan": {
        "label": "Riset + Laporan", "process": "sequential",
        "summary": "Riset, analisis, lalu laporan rapi dalam file Markdown.",
        "members": [
            _m("m1", "Rani", "Peneliti", "Menemukan sumber terpercaya", ["web", "files"], 1),
            _m("m2", "Bayu", "Analis", "Menarik kesimpulan dari data dan sumber", ["web"], 4),
            _m("m3", "Citra", "Penulis laporan", "Menulis laporan terstruktur", ["files", "write"], 9),
        ],
        "tasks": [
            _t("t1", "Riset", "Kumpulkan sumber dan data tentang: {goal}.", "Catatan riset + tautan", "m1"),
            _t("t2", "Analisis", "Analisis catatan riset: pola, angka penting, keterbatasan.", "Analisis poin-poin", "m2"),
            _t("t3", "Laporan", "Tulis laporan Markdown (ringkasan, temuan, analisis, sumber) ke file laporan-crew.md "
               "di folder kerja, lalu tampilkan isinya.", "laporan-crew.md", "m3"),
        ],
    },
}

TEMPLATE_KEYWORDS = {
    "coding": ("kode", "code", "coding", "bug", "fitur", "feature", "refactor", "tes ", "test", "repo", "api",
               "aplikasi", "app", "script", "fungsi", "function", "error", "build"),
    "konten": ("konten", "content", "artikel", "article", "postingan", "post", "caption", "blog", "thread",
               "newsletter", "naskah", "script video", "copy", "tulisan"),
    "riset_laporan": ("laporan", "report", "makalah", "paper", "skripsi", "dokumen", "whitepaper"),
    "riset": ("riset", "research", "cari", "bandingkan", "compare", "analisis", "analyze", "tren", "trend", "pasar"),
}

AVATARS = 10  # pixel avatar palettes known to the desktop and phone renderers


def pick_template(goal: str) -> str:
    g = f" {str(goal or '').lower()} "
    for key in ("riset_laporan", "coding", "konten", "riset"):
        if any(k in g for k in TEMPLATE_KEYWORDS[key]):
            return key
    return "riset"


def templates_payload() -> list[dict]:
    return [{"id": k, "label": v["label"], "summary": v["summary"], "process": v["process"],
             "members": [{"role": m["role"], "tools": m["tools"], "avatar": m["avatar"]} for m in v["members"]]}
            for k, v in TEMPLATES.items()]


def side_effect_groups(tools: list[str]) -> list[str]:
    return [g for g in tools if TOOL_GROUPS.get(g, {}).get("side_effect")]


def allowed_tool_names(groups: list[str]) -> set[str]:
    out: set[str] = set()
    for g in groups or []:
        out.update(TOOL_GROUPS.get(g, {}).get("tools", []))
    return out


def is_free_model(model: str) -> bool:
    from neovarch import router9
    return router9.is_free_model(model)


def _clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n] + f"\n…[dipotong {len(s) - n} karakter]"


def _now() -> float:
    return time.time()


# --------------------------------------------------------------- normalise --
def normalize(raw: dict, goal: str = "") -> dict:
    """Validate a crew design (from the designer, a template or the Lanjutan editor).

    Raises CrewError("invalid", ...) with an Indonesian message on anything unusable."""
    if not isinstance(raw, dict):
        raise CrewError("invalid", "rancangan crew harus berupa objek")
    process = str(raw.get("process") or "sequential").strip().lower()
    if process in ("manager", "hierarki", "hierarkis"):
        process = "hierarchical"
    if process not in PROCESSES:
        raise CrewError("invalid", f"alur tidak dikenal: {process} (pakai sequential atau hierarchical)")
    members_in = raw.get("members") or []
    if not isinstance(members_in, list) or not members_in:
        raise CrewError("invalid", "crew butuh minimal satu anggota")
    if len(members_in) > MAX_MEMBERS:
        raise CrewError("invalid", f"maksimal {MAX_MEMBERS} anggota")
    members: list[dict] = []
    seen: set[str] = set()
    for i, m in enumerate(members_in):
        if not isinstance(m, dict):
            raise CrewError("invalid", "anggota harus berupa objek")
        mid = str(m.get("id") or f"m{i + 1}").strip()[:16] or f"m{i + 1}"
        if mid in seen:
            mid = f"m{i + 1}x"
        seen.add(mid)
        role = str(m.get("role") or "").strip()[:60]
        if not role:
            raise CrewError("invalid", f"anggota {i + 1} belum punya peran")
        tools = [str(t).strip().lower() for t in (m.get("tools") or []) if str(t).strip()]
        bad = [t for t in tools if t not in TOOL_GROUPS]
        if bad:
            raise CrewError("invalid", f"alat tidak dikenal: {', '.join(bad)} (pilihan: {', '.join(TOOL_GROUPS)})")
        model = str(m.get("model") or "").strip()
        if model and not is_free_model(model):
            raise CrewError("paid_model", f"model {model} tidak gratis; Crew hanya memakai model gratis")
        try:
            avatar = int(m.get("avatar")) % AVATARS
        except (TypeError, ValueError):
            avatar = i % AVATARS
        members.append({"id": mid, "name": str(m.get("name") or role).strip()[:30], "role": role,
                        "goal": str(m.get("goal") or "").strip()[:300], "tools": list(dict.fromkeys(tools)),
                        "model": model, "avatar": avatar, "status": "idle", "activity": ""})
    ids = [m["id"] for m in members]
    manager = raw.get("manager")
    if process == "hierarchical":
        manager = str(manager or ids[0])
        if manager not in ids:
            raise CrewError("invalid", "manajer harus salah satu anggota")
    else:
        manager = None
    tasks_in = raw.get("tasks") or []
    if not isinstance(tasks_in, list) or not tasks_in:
        raise CrewError("invalid", "crew butuh minimal satu tugas")
    if len(tasks_in) > MAX_TASKS:
        raise CrewError("invalid", f"maksimal {MAX_TASKS} tugas")
    workers = [i for i in ids if i != manager] or ids
    tasks: list[dict] = []
    for i, t in enumerate(tasks_in):
        if not isinstance(t, dict):
            raise CrewError("invalid", "tugas harus berupa objek")
        title = str(t.get("title") or "").strip()[:80]
        desc = str(t.get("description") or "").strip()
        if not title and not desc:
            raise CrewError("invalid", f"tugas {i + 1} kosong")
        member_id = str(t.get("member_id") or t.get("agent") or "").strip()
        if member_id not in ids:
            member_id = workers[i % len(workers)]
        g = str(goal or raw.get("goal") or "")
        tasks.append({"id": str(t.get("id") or f"t{i + 1}")[:16], "title": title or desc[:60],
                      "description": desc.replace("{goal}", g)[:2000],
                      "expected_output": str(t.get("expected_output") or "").strip()[:300],
                      "member_id": member_id, "status": "todo", "output": "", "started_at": 0, "finished_at": 0})
    tool_groups = sorted({g for m in members for g in m["tools"]})
    return {"process": process, "manager": manager, "members": members, "tasks": tasks,
            "side_effects": side_effect_groups(tool_groups)}


def from_template(key: str, goal: str) -> dict:
    tpl = TEMPLATES.get(key)
    if not tpl:
        raise CrewError("invalid", f"template tidak dikenal: {key}")
    return normalize({"process": tpl["process"], "manager": tpl.get("manager"),
                      "members": json.loads(json.dumps(tpl["members"])),
                      "tasks": json.loads(json.dumps(tpl["tasks"]))}, goal)


DESIGN_PROMPT = """Kamu agen utama Neovarch. Susun sebuah crew (tim kecil agen) untuk tujuan pengguna di bawah.
Balas HANYA dengan satu objek JSON, tanpa teks lain:
{{"title": "judul pendek", "process": "sequential" atau "hierarchical",
  "manager": "id anggota manajer (hanya untuk hierarchical)",
  "members": [{{"id": "m1", "name": "nama Indonesia pendek", "role": "peran", "goal": "tujuan anggota",
               "tools": ["web" | "files" | "write" | "shell"]}}],
  "tasks": [{{"id": "t1", "title": "judul", "description": "apa yang dikerjakan", "expected_output": "hasil",
             "member_id": "m1"}}]}}
Aturan: 2-{max_members} anggota, 1-{max_tasks} tugas berurutan, beri alat seperlunya saja ("write"/"shell" hanya bila
tujuan memang butuh mengubah file atau menjalankan perintah). Pakai "hierarchical" bila pekerjaan perlu dibagi dan
diperiksa manajer (mis. coding), selain itu "sequential". Bahasa Indonesia.
Template yang mirip: {template}.
Tujuan: {goal}"""


def parse_design(text: str) -> dict | None:
    s = str(text or "")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    cand = m.group(1) if m else s[s.find("{"): s.rfind("}") + 1] if "{" in s else ""
    if not cand:
        return None
    try:
        data = json.loads(cand)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ store --
class CrewStore:
    """Crews as one JSON file (``<home>/crew/crews.json``); small, so a rewrite per change is fine."""

    def __init__(self, path: Path | None = None):
        if path is None:
            from neovarch.paths import neovarch_home
            path = neovarch_home() / "crew" / "crews.json"
        self.path = path
        self._lock = threading.Lock()
        self.crews: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for c in (data.get("crews") or []) if isinstance(data, dict) else []:
            if isinstance(c, dict) and c.get("id"):
                if c.get("status") == "running":  # the core restarted mid-run
                    c["status"] = "failed"
                    c["error"] = "dihentikan karena core dimulai ulang"
                    for m in c.get("members") or []:
                        m["status"] = "idle"
                        m["activity"] = ""
                self.crews[c["id"]] = c

    def save(self) -> None:
        with self._lock:
            items = sorted(self.crews.values(), key=lambda c: c.get("created_at", 0), reverse=True)
            keep = items[:KEEP_CREWS]
            self.crews = {c["id"]: c for c in keep}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "crews": keep}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, cid: str) -> dict:
        c = self.crews.get(str(cid or ""))
        if not c:
            raise CrewError("not_found", "crew tidak ditemukan")
        return c


Ask = Callable[[str], Awaitable[str]]
RunMember = Callable[[dict, dict, str], Awaitable[str]]


# ----------------------------------------------------------------- engine --
class CrewEngine:
    def __init__(self, store: CrewStore, ask: Ask | None = None, run_member: RunMember | None = None,
                 on_change: Callable[[dict], None] | None = None):
        self.store = store
        self.ask = ask
        self.run_member = run_member
        self.on_change = on_change
        self.tasks: dict[str, asyncio.Task] = {}

    # -- helpers --
    def _changed(self, c: dict, save: bool = True) -> None:
        c["updated_at"] = _now()
        if save:
            self.store.save()
        if self.on_change:
            try:
                self.on_change(public(c))
            except Exception:  # a broken listener never stops a crew
                traceback.print_exc()

    def _log(self, c: dict, text: str, member: str | None = None) -> None:
        c.setdefault("log", []).append({"ts": _now(), "text": str(text)[:300], "member": member})
        del c["log"][:-LOG_MAX]

    @staticmethod
    def _member(c: dict, mid: str | None) -> dict | None:
        return next((m for m in c["members"] if m["id"] == mid), None)

    def _set_member(self, c: dict, mid: str | None, status: str, activity: str = "") -> None:
        m = self._member(c, mid)
        if m:
            m["status"], m["activity"] = status, activity[:140]
        self._changed(c, save=False)

    # -- API --
    async def propose(self, goal: str, template: str | None = None) -> dict:
        goal = str(goal or "").strip()
        if not goal:
            raise CrewError("invalid", "tulis dulu tujuannya")
        if template and template not in TEMPLATES:
            raise CrewError("invalid", f"template tidak dikenal: {template}")
        key = template or pick_template(goal)
        design, designed_by, title, note = None, "template", "", ""
        if self.ask is not None and not template:
            try:
                text = await asyncio.wait_for(self.ask(DESIGN_PROMPT.format(
                    goal=goal, template=TEMPLATES[key]["label"], max_members=MAX_MEMBERS, max_tasks=MAX_TASKS)), 120)
                raw = parse_design(text)
                if raw:
                    design = normalize(raw, goal)
                    designed_by = "agent"
                    title = str(raw.get("title") or "").strip()[:80]
                else:
                    note = "rancangan agen tidak terbaca; memakai template"
            except CrewError as exc:
                note = f"rancangan agen ditolak ({exc}); memakai template"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the model is down or slow: the template still gives a crew
                note = f"agen utama tidak menjawab ({type(exc).__name__}); memakai template"
        if design is None:
            design = from_template(key, goal)
        cid = "c" + secrets.token_hex(4)
        c = {"id": cid, "title": title or goal[:60], "goal": goal, "template": key, "designed_by": designed_by,
             "status": "proposed", "allow_side_effects": False, "final_output": "", "error": "", "note": note,
             "created_at": _now(), "updated_at": _now(), "log": [], **design}
        self._log(c, "rancangan crew dibuat oleh agen utama" if designed_by == "agent"
                  else f"rancangan crew dari template {TEMPLATES[key]['label']}")
        self.store.crews[cid] = c
        self._changed(c)
        return public(c)

    def update(self, cid: str, patch: dict) -> dict:
        """Lanjutan: edit members/tasks/process/manager/title of a proposal (not while it runs)."""
        c = self.store.get(cid)
        if c["status"] == "running":
            raise CrewError("busy", "crew sedang bekerja; hentikan dulu untuk mengubahnya")
        patch = patch if isinstance(patch, dict) else {}
        merged = {"process": patch.get("process", c["process"]), "manager": patch.get("manager", c.get("manager")),
                  "members": patch.get("members", c["members"]), "tasks": patch.get("tasks", c["tasks"])}
        design = normalize(merged, c["goal"])
        c.update(design)
        if "title" in patch:
            c["title"] = str(patch.get("title") or c["goal"])[:80]
        if c["status"] != "proposed":  # editing a finished crew turns it into a new proposal to run again
            c["status"], c["final_output"], c["error"] = "proposed", "", ""
        c["allow_side_effects"] = False  # consent is for the design the user saw
        self._log(c, "rancangan diubah di Lanjutan")
        self._changed(c)
        return public(c)

    def approve(self, cid: str, allow_side_effects: bool = False) -> dict:
        c = self.store.get(cid)
        if c["status"] == "running":
            raise CrewError("busy", "crew sudah bekerja")
        if self.run_member is None:
            raise CrewError("unavailable", "Crew belum bisa dijalankan di core ini")
        if c.get("side_effects") and not allow_side_effects:
            raise CrewError("needs_consent", "crew ini bisa mengubah file atau menjalankan perintah; "
                                             "centang izin efek samping dulu")
        c["allow_side_effects"] = bool(allow_side_effects and c.get("side_effects"))
        c["status"], c["error"], c["final_output"] = "running", "", ""
        c["started_at"], c["finished_at"] = _now(), 0
        for t in c["tasks"]:
            t.update(status="todo", output="", started_at=0, finished_at=0)
        for m in c["members"]:
            m["status"], m["activity"] = "idle", ""
        self._log(c, "disetujui pengguna, crew mulai bekerja")
        self._changed(c)
        self.tasks[cid] = asyncio.get_event_loop().create_task(self._run(cid))
        return public(c)

    def cancel(self, cid: str) -> dict:
        c = self.store.get(cid)
        t = self.tasks.get(cid)
        if t and not t.done():
            t.cancel()
        if c["status"] == "running":
            self._finish(c, "cancelled", "dihentikan pengguna")
        return public(c)

    def delete(self, cid: str) -> dict:
        c = self.store.get(cid)
        if c["status"] == "running":
            raise CrewError("busy", "hentikan crew dulu sebelum dihapus")
        self.store.crews.pop(cid, None)
        self.store.save()
        if self.on_change:
            self.on_change({"id": cid, "deleted": True})
        return {"ok": True, "id": cid}

    def list(self) -> list[dict]:
        items = sorted(self.store.crews.values(), key=lambda c: c.get("created_at", 0), reverse=True)
        return [summary(c) for c in items]

    async def wait(self, cid: str) -> dict:
        t = self.tasks.get(cid)
        if t:
            try:
                await t
            except asyncio.CancelledError:
                pass
        return public(self.store.get(cid))

    # -- execution --
    def _finish(self, c: dict, status: str, error: str = "") -> None:
        c["status"], c["error"], c["finished_at"] = status, error, _now()
        for m in c["members"]:
            if m["status"] not in ("done", "error"):
                m["status"], m["activity"] = ("idle", "") if status != "done" else ("done", "")
        for t in c["tasks"]:
            if t["status"] in ("todo", "running") and status != "done":
                t["status"] = "skipped" if t["status"] == "todo" else "cancelled"
        self._log(c, {"done": "crew selesai", "failed": f"crew gagal: {error}",
                      "cancelled": "crew dihentikan"}.get(status, status))
        self._changed(c)

    def task_prompt(self, c: dict, t: dict, m: dict, extra: str = "") -> str:
        done = [x for x in c["tasks"] if x["status"] == "done" and x["output"]]
        ctx = "\n\n".join(f"### {x['title']} (oleh {self._member(c, x['member_id'])['role']})\n"
                          f"{_clip(x['output'], CONTEXT_CLIP)}" for x in done)
        team = ", ".join(f"{x['name']} ({x['role']})" for x in c["members"])
        tools = ", ".join(m["tools"]) or "tanpa alat (cukup berpikir dan menulis)"
        lines = [f"Kamu {m['name']}, {m['role']} dalam crew Neovarch. Tujuanmu: {m['goal'] or m['role']}.",
                 f"Tujuan crew: {c['goal']}", f"Tim: {team}.", f"Alatmu: {tools}.",
                 "", f"## Tugasmu: {t['title']}", t["description"]]
        if t.get("expected_output"):
            lines.append(f"Hasil yang diharapkan: {t['expected_output']}")
        if ctx:
            lines += ["", "## Hasil anggota sebelumnya", ctx]
        if extra:
            lines += ["", extra]
        lines += ["", "Kerjakan hanya tugasmu, lalu tulis hasilnya langsung (tanpa basa-basi), Bahasa Indonesia."]
        return "\n".join(lines)

    async def _run(self, cid: str) -> None:
        c = self.store.get(cid)
        try:
            if c["process"] == "hierarchical":
                await self._run_hierarchical(c)
            else:
                await self._run_sequential(c)
            self._finish(c, "done")
        except asyncio.CancelledError:
            if c["status"] == "running":
                self._finish(c, "cancelled", "dihentikan pengguna")
            raise
        except Exception as exc:
            traceback.print_exc()
            self._finish(c, "failed", f"{type(exc).__name__}: {exc}")
        finally:
            self.tasks.pop(cid, None)

    async def _work(self, c: dict, t: dict, extra: str = "") -> str:
        m = self._member(c, t["member_id"]) or c["members"][0]
        t["status"], t["started_at"] = "running", t["started_at"] or _now()
        self._log(c, f"{m['name']} mulai: {t['title']}", m["id"])
        self._set_member(c, m["id"], "working", t["title"])
        out = await self.run_member(c, m, self.task_prompt(c, t, m, extra))
        t["output"] = _clip((out or "").strip() or "(tanpa hasil)", OUTPUT_CLIP)
        t["status"], t["finished_at"] = "done", _now()
        self._log(c, f"{m['name']} selesai: {t['title']}", m["id"])
        self._set_member(c, m["id"], "done" if self._all_done_for(c, m["id"]) else "idle", "")
        self.store.save()
        return t["output"]

    @staticmethod
    def _all_done_for(c: dict, mid: str) -> bool:
        return all(t["status"] == "done" for t in c["tasks"] if t["member_id"] == mid)

    async def _run_sequential(self, c: dict) -> None:
        for t in c["tasks"]:
            await self._work(c, t)
        c["final_output"] = c["tasks"][-1]["output"]

    async def _manager_say(self, c: dict, prompt: str, activity: str) -> str:
        mgr = self._member(c, c.get("manager"))
        self._set_member(c, mgr["id"] if mgr else None, "reviewing", activity)
        persona = (f"Kamu {mgr['name']}, {mgr['role']} (manajer) crew Neovarch untuk tujuan: {c['goal']}.\n"
                   if mgr else "")
        if self.ask is not None:
            out = await self.ask(persona + prompt)
        else:  # no designer model: the manager answers through its own member turn
            out = await self.run_member(c, mgr, persona + prompt)
        self._set_member(c, mgr["id"] if mgr else None, "idle", "")
        return (out or "").strip()

    async def _run_hierarchical(self, c: dict) -> None:
        mgr = self._member(c, c.get("manager"))
        for t in c["tasks"]:
            if t["member_id"] == c.get("manager"):
                await self._work(c, t)
                continue
            out = await self._work(c, t)
            verdict = await self._manager_say(
                c, f"Periksa hasil tugas \"{t['title']}\" (harapan: {t.get('expected_output') or '-'}):\n\n"
                   f"{_clip(out, CONTEXT_CLIP)}\n\nBalas satu baris: OK, atau REVISI: <apa yang harus diperbaiki>.",
                f"memeriksa {t['title']}")
            if verdict.upper().startswith("REVISI"):
                note = verdict.split(":", 1)[1].strip() if ":" in verdict else verdict
                self._log(c, f"{mgr['name'] if mgr else 'Manajer'} minta revisi: {note[:120]}", c.get("manager"))
                await self._work(c, t, extra=f"## Catatan revisi dari manajer\n{note}\n\nHasilmu sebelumnya:\n"
                                             f"{_clip(out, CONTEXT_CLIP)}")
        results = "\n\n".join(f"### {t['title']}\n{_clip(t['output'], CONTEXT_CLIP)}" for t in c["tasks"])
        c["final_output"] = _clip(await self._manager_say(
            c, f"Semua tugas selesai. Tulis jawaban akhir untuk pengguna dari hasil tim berikut:\n\n{results}",
            "menulis ringkasan akhir") or c["tasks"][-1]["output"], OUTPUT_CLIP)
        if mgr:
            mgr["status"] = "done"


def summary(c: dict) -> dict:
    return {"id": c["id"], "title": c.get("title") or c.get("goal", "")[:60], "goal": c.get("goal", ""),
            "status": c.get("status"), "process": c.get("process"), "template": c.get("template"),
            "members": len(c.get("members") or []), "tasks": len(c.get("tasks") or []),
            "done": sum(1 for t in c.get("tasks") or [] if t.get("status") == "done"),
            "created_at": c.get("created_at", 0), "updated_at": c.get("updated_at", 0)}


def public(c: dict) -> dict:
    return json.loads(json.dumps(c))


# ------------------------------------------------------------- gateway ----
class CrewBinding:
    """Attached to a crew member's LiveSession as ``ctx.company`` so the existing tool gate
    (``tools._allowed_builtin``) limits the member to its tool groups. Members get no
    Kantor tools, no vault notes and no install changes, like Perusahaan employees."""

    def __init__(self, member: dict, allow_side_effects: bool):
        groups = [g for g in member.get("tools") or [] if allow_side_effects or not TOOL_GROUPS[g]["side_effect"]]
        self._allowed = allowed_tool_names(groups) or {"__crew_no_tools__"}
        self._persona = (f"Kamu {member.get('name')}, {member.get('role')} dalam sebuah Crew Neovarch. "
                         f"Tujuanmu: {member.get('goal') or member.get('role')}. Kerjakan tugas yang diberikan saja.")

    def tool_schemas(self) -> list[dict]:
        return []

    def tool_names(self) -> set[str]:
        return set()

    async def run_tool(self, name: str, args: dict) -> str:
        return f"error: unknown tool {name}"

    def persona(self) -> str:
        return self._persona

    def allowed_tools(self) -> set[str]:
        return set(self._allowed)


def member_model(member: dict, cfg: dict) -> dict | None:
    """The model override a member runs with: its own free model, else the PC default when that is
    free, else the free default. Never a paid model."""
    from neovarch import models as modelsmod
    from neovarch import router9
    if member.get("model") and is_free_model(member["model"]):
        return {"model": member["model"], "provider": router9.PROVIDER}
    ref = modelsmod.default_ref(cfg)
    if is_free_model(ref.get("model", "")):
        return None
    return {"model": router9.DEFAULT_MODEL, "provider": router9.PROVIDER}


class CrewRuntime:
    """Wires the engine into the Gateway: member turns as hidden sessions, designer calls
    as a throwaway session of the main agent, ``crew.update`` pushes."""

    def __init__(self, gw):
        self.gw = gw
        self.store = CrewStore()
        self.engine = CrewEngine(self.store, ask=self._ask, run_member=self._run_member, on_change=self._push)
        self.sessions: dict[str, Any] = {}

    def _push(self, payload: dict) -> None:
        try:
            self.gw.broadcast_event("crew.update", None, payload)
        except Exception:
            pass

    def _open(self, title: str, model: dict | None, binding: CrewBinding | None):
        gw = self.gw
        rec = gw.store.create(source="crew", title=title, model=gw.model_info()["model"])
        if model:
            rec["model_override"] = model
        gw.store.save(rec)
        live = gw.open(rec)
        if binding is not None:
            live.ctx.company = binding  # type: ignore[attr-defined]
            live.ctx.persona = binding.persona  # type: ignore[attr-defined]
        return live

    async def _turn(self, live, prompt: str) -> str:
        live.submit(prompt)
        if live.task:
            await live.task
        return live.last_text or ""

    async def _ask(self, prompt: str) -> str:
        from neovarch import config as cfgmod
        none = CrewBinding({"name": "Neovarch", "role": "agen utama", "tools": []}, False)
        none._persona = "Kamu agen utama Neovarch yang menyusun dan memimpin Crew."
        live = self._open("Crew · agen utama", member_model({}, cfgmod.load_config()), none)
        try:
            return await self._turn(live, prompt)
        finally:
            self.gw.live.pop(live.id, None)

    async def _run_member(self, c: dict, m: dict, prompt: str) -> str:
        from neovarch import config as cfgmod
        live = self._open(f"Crew · {m.get('name')} ({m.get('role')})", member_model(m, cfgmod.load_config()),
                          CrewBinding(m, bool(c.get("allow_side_effects"))))
        self.sessions[f"{c['id']}:{m['id']}"] = live.id
        m["session_id"] = live.id
        try:
            return await self._turn(live, prompt)
        except asyncio.CancelledError:
            try:
                live.stop()
            except Exception:
                pass
            raise
        finally:
            self.gw.live.pop(live.id, None)

    def observe(self, kind: str, sid: str | None, payload: dict | None) -> None:
        """Member sessions' live events → the member's status in the pixel room (not saved)."""
        if not sid or kind not in ("approval.request", "approval.cancelled", "tool.start"):
            return
        for c in self.store.crews.values():
            if c.get("status") != "running":
                continue
            m = next((x for x in c["members"] if x.get("session_id") == sid), None)
            if not m:
                continue
            p = payload if isinstance(payload, dict) else {}
            if kind == "approval.request":
                m["status"] = "waiting"
                m["activity"] = f"minta izin: {str(p.get('command') or p.get('tool_name') or '')[:100]}"
                m["approval"] = {"session_id": sid, "request_id": p.get("request_id"),
                                 "command": str(p.get("command") or "")[:300]}
            elif kind == "approval.cancelled":
                m.pop("approval", None)
                if m["status"] == "waiting":
                    m["status"], m["activity"] = "working", ""
            elif kind == "tool.start" and m["status"] == "working":
                m["activity"] = str(p.get("name") or p.get("tool_name") or "")[:60]
            self.engine._changed(c, save=False)
            return

    async def call(self, method: str, p: dict) -> Any:
        e = self.engine
        p = p if isinstance(p, dict) else {}
        if method == "crew.templates":
            return {"templates": templates_payload(), "tool_groups": {k: {"side_effect": v["side_effect"]}
                                                                     for k, v in TOOL_GROUPS.items()}}
        if method == "crew.list":
            return {"crews": e.list()}
        if method == "crew.get":
            return public(self.store.get(str(p.get("id") or "")))
        if method == "crew.propose":
            return await e.propose(str(p.get("goal") or ""), p.get("template") or None)
        if method == "crew.update":
            return e.update(str(p.get("id") or ""), p.get("patch") if isinstance(p.get("patch"), dict) else p)
        if method in ("crew.approve", "crew.start"):
            return e.approve(str(p.get("id") or ""), bool(p.get("allow_side_effects")))
        if method == "crew.cancel":
            return e.cancel(str(p.get("id") or ""))
        if method == "crew.delete":
            return e.delete(str(p.get("id") or ""))
        raise CrewError("unknown", f"metode tidak dikenal: {method}")

    async def stop(self) -> None:
        for t in list(self.engine.tasks.values()):
            t.cancel()


CREW_RPC_CODES = {"invalid": -32602, "paid_model": -32602, "not_found": -32004, "busy": -32009,
                  "needs_consent": -32011, "unavailable": -32010, "unknown": -32601}
CREW_HTTP = {"invalid": 400, "paid_model": 400, "not_found": 404, "busy": 409, "needs_consent": 409,
             "unavailable": 503, "unknown": 404}


# --------------------------------------------------------- main agent tool --
TOOL_SCHEMA = {
    "description": ("Crew: susun tim kecil agen untuk satu tujuan. action=propose membuat RANCANGAN (anggota, tugas, "
                    "alur) yang ditampilkan ke pengguna di menu Crew untuk disetujui; crew TIDAK berjalan sebelum "
                    "pengguna menyetujuinya di sana. Beri `design` (JSON: process, manager, members[{name, role, goal, "
                    "tools: web|files|write|shell}], tasks[{title, description, expected_output, member_id}]) bila kamu "
                    "sudah tahu susunannya, atau `template` (riset, konten, coding, riset_laporan). action=list/status "
                    "untuk melihat crew yang ada."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["propose", "list", "status"]},
        "goal": {"type": "string"}, "template": {"type": "string"},
        "design": {"type": "object"}, "id": {"type": "string"}}, "required": ["action"]},
}


async def tool_crew(args: dict, ctx) -> str:
    gw = getattr(ctx, "gateway", None)
    rt = getattr(gw, "crew", None)
    if rt is None:
        return "error: Crew tidak tersedia di sesi ini"
    action = str(args.get("action") or "list")
    try:
        if action == "list":
            return json.dumps(rt.engine.list()[:10], ensure_ascii=False)
        if action == "status":
            c = rt.store.get(str(args.get("id") or ""))
            return json.dumps({k: c.get(k) for k in ("id", "title", "status", "final_output", "error")}
                              | {"tasks": [{"title": t["title"], "status": t["status"]} for t in c["tasks"]]},
                              ensure_ascii=False)
        goal = str(args.get("goal") or "").strip()
        design = args.get("design")
        if isinstance(design, dict) and design:
            norm = normalize(design, goal)
            c = await rt.engine.propose(goal, args.get("template") or pick_template(goal))
            c = rt.engine.update(c["id"], {**norm, "title": design.get("title") or c["title"]})
            rt.store.get(c["id"])["designed_by"] = "agent"
            rt.store.save()
        else:
            c = await rt.engine.propose(goal, args.get("template") or pick_template(goal))
        return (f"Rancangan crew {c['id']} dibuat ({len(c['members'])} anggota, {len(c['tasks'])} tugas, alur "
                f"{c['process']}). Minta pengguna membuka menu Crew untuk meninjau dan menyetujuinya; jangan "
                f"anggap crew sudah berjalan.")
    except CrewError as exc:
        return f"error: {exc}"
