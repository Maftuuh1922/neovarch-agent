"""Perusahaan: the Kantor run as a small company of agents.

Concepts (company goal → projects → tickets with goal ancestry, an org chart, atomic
ticket checkout, heartbeats, approvals, budgets, an activity log, routines) follow the
public design of Paperclip (MIT); the code is Neovarch's own. See
docs/company-flow-design.md.

Everything is stored in ``~/.neovarch/company.db`` (SQLite). Nothing runs on its own
until the user turns ``autorun`` on, except an explicit "Bangunkan" (manual wake).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from neovarch.paths import neovarch_home

TICKET_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked", "done", "cancelled")
TRANSITIONS: dict[str, set[str]] = {
    "backlog": {"todo", "cancelled"},
    "todo": {"in_progress", "blocked", "backlog", "cancelled"},
    "in_progress": {"review", "blocked", "done", "todo", "cancelled"},
    "review": {"in_progress", "done", "cancelled"},
    "blocked": {"todo", "in_progress", "cancelled"},
    "done": set(),
    "cancelled": set(),
}
AGENT_STATUSES = ("pending_approval", "idle", "running", "paused", "error", "terminated")
APPROVAL_KINDS = ("hire", "plan", "review", "budget")
STATUS_LABEL = {"backlog": "Backlog", "todo": "Akan dikerjakan", "in_progress": "Dikerjakan",
                "review": "Ditinjau", "blocked": "Terhambat", "done": "Selesai", "cancelled": "Dibatalkan"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT NOT NULL, mission TEXT NOT NULL DEFAULT '',
  autorun INTEGER NOT NULL DEFAULT 0, max_parallel INTEGER NOT NULL DEFAULT 2,
  require_hire_approval INTEGER NOT NULL DEFAULT 1, require_review INTEGER NOT NULL DEFAULT 1,
  budget_monthly_cents INTEGER NOT NULL DEFAULT 0, budget_monthly_tokens INTEGER NOT NULL DEFAULT 0,
  warn_pct INTEGER NOT NULL DEFAULT 80, price_in_per_mtok REAL NOT NULL DEFAULT 0,
  price_out_per_mtok REAL NOT NULL DEFAULT 0, ticket_prefix TEXT NOT NULL DEFAULT 'NV',
  ticket_counter INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
  budget_monthly_cents INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'pegawai', reports_to INTEGER REFERENCES agents(id) ON DELETE SET NULL,
  job_description TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'idle',
  pause_reason TEXT, heartbeat_s INTEGER NOT NULL DEFAULT 0, budget_monthly_cents INTEGER NOT NULL DEFAULT 0,
  budget_monthly_tokens INTEGER NOT NULL DEFAULT 0, session_id TEXT, last_heartbeat_at REAL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL, goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  parent_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo', priority INTEGER NOT NULL DEFAULT 1,
  assignee_id INTEGER REFERENCES agents(id) ON DELETE SET NULL, checkout_agent_id INTEGER, checkout_run_id INTEGER,
  checkout_at REAL, created_by TEXT NOT NULL DEFAULT 'user', started_at REAL, completed_at REAL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ticket_blockers (
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  blocker_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, PRIMARY KEY (ticket_id, blocker_id));
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  author_type TEXT NOT NULL, author_id INTEGER, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS work_products (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'text', title TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '', agent_id INTEGER,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE, agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}', requested_by TEXT NOT NULL DEFAULT 'user',
  note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, decided_at REAL);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  ticket_id INTEGER, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running', session_id TEXT, error TEXT,
  prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents REAL NOT NULL DEFAULT 0, started_at REAL NOT NULL, finished_at REAL);
CREATE TABLE IF NOT EXISTS cost_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, project_id INTEGER, ticket_id INTEGER, run_id INTEGER,
  model TEXT NOT NULL DEFAULT '', prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents REAL NOT NULL DEFAULT 0, month TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wakeups (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  reason TEXT NOT NULL, ticket_id INTEGER, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS routines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, schedule TEXT NOT NULL,
  agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL, project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at REAL, next_run_at REAL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS budget_alerts (scope TEXT NOT NULL, month TEXT NOT NULL, level TEXT NOT NULL,
  PRIMARY KEY (scope, month, level));
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor_type TEXT NOT NULL, actor_id INTEGER,
  actor_name TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER,
  summary TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS units (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'agency',
  parent_id INTEGER REFERENCES units(id) ON DELETE SET NULL, description TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
CREATE INDEX IF NOT EXISTS idx_cost_month ON cost_events(month);
"""


class CompanyError(Exception):
    """code: invalid | not_found | conflict"""

    def __init__(self, code: str, message: str, **data):
        super().__init__(message)
        self.code = code
        self.data = data


def month_of(ts: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts))


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


class CompanyStore:
    """All persistence + invariants. Thread-safe (one connection, one lock)."""

    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else neovarch_home() / "company.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        try:
            self.db.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        self.db.executescript(SCHEMA)
        self._migrate()
        self.on_change: Callable[[str, int | None, str], None] | None = None

    def _migrate(self) -> None:
        """Columns added after the first release of company.db (old files keep working)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(agents)").fetchall()}
        if "provider" not in cols:
            self.db.execute("ALTER TABLE agents ADD COLUMN provider TEXT NOT NULL DEFAULT ''")
        # Organisasi → Agency → Orang: an employee sits in a unit; persona/skills/tools are theirs.
        for col, ddl in (("unit_id", "INTEGER"), ("persona", "TEXT NOT NULL DEFAULT ''"),
                         ("skills", "TEXT NOT NULL DEFAULT '[]'"), ("tools", "TEXT NOT NULL DEFAULT '[]'")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE agents ADD COLUMN {col} {ddl}")

    # ------------------------------------------------------------ plumbing --
    def close(self) -> None:
        with self.lock:
            self.db.close()

    def q(self, sql: str, args: tuple | list = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def q1(self, sql: str, args: tuple | list = ()) -> dict | None:
        with self.lock:
            return _row(self.db.execute(sql, args).fetchone())

    def x(self, sql: str, args: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.db.execute(sql, args)

    def tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store.lock.acquire()
                store.db.execute("BEGIN IMMEDIATE")
                return store

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    store.db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store.lock.release()
                return False
        return _Tx()

    def changed(self, entity: str, eid: int | None, action: str) -> None:
        if self.on_change:
            try:
                self.on_change(entity, eid, action)
            except Exception:  # never break a write because a listener failed
                pass

    def log(self, action: str, entity: str, eid: int | None, summary: str, *, actor: str = "user",
            actor_id: int | None = None, data: dict | None = None) -> None:
        name = "Kamu" if actor == "user" else ("Sistem" if actor == "system" else "")
        if actor == "agent" and actor_id:
            a = self.q1("SELECT name FROM agents WHERE id=?", (actor_id,))
            name = a["name"] if a else "Agen"
        self.x("INSERT INTO activity (ts, actor_type, actor_id, actor_name, action, entity, entity_id, summary, data) "
               "VALUES (?,?,?,?,?,?,?,?,?)", (self.clock(), actor, actor_id, name, action, entity, eid,
                                               summary[:400], json.dumps(data or {}, ensure_ascii=False)))

    # ------------------------------------------------------------- company --
    def company(self) -> dict | None:
        c = self.q1("SELECT * FROM company WHERE id=1")
        if c:
            for k in ("autorun", "require_hire_approval", "require_review"):
                c[k] = bool(c[k])
        return c

    def require_company(self) -> dict:
        c = self.company()
        if not c:
            raise CompanyError("invalid", "Perusahaan belum dibuat")
        return c

    def ensure_company(self, name: str = "Kantor Neovarch") -> dict:
        """The Kantor itself: created on the first command that needs it (no demo staff)."""
        c = self.company()
        if c:
            return c
        c = self.setup(name)
        # The user commands every hire through the main agent, so no extra approval step.
        return self.update_company({"require_hire_approval": False}, actor="system")

    def setup(self, name: str, mission: str = "", **settings) -> dict:
        name = (name or "").strip()
        if not name:
            raise CompanyError("invalid", "Nama perusahaan wajib diisi")
        now = self.clock()
        with self.tx():
            if self.company():
                raise CompanyError("conflict", "Perusahaan sudah ada")
            self.db.execute("INSERT INTO company (id, name, mission, created_at, updated_at) VALUES (1,?,?,?,?)",
                            (name, mission.strip(), now, now))
            self.log("company.created", "company", 1, f"membuat perusahaan “{name}”")
        if settings:
            self.update_company(settings)
        self.changed("company", 1, "created")
        return self.require_company()

    COMPANY_FIELDS = {"name": str, "mission": str, "autorun": bool, "max_parallel": int,
                      "require_hire_approval": bool, "require_review": bool, "budget_monthly_cents": int,
                      "budget_monthly_tokens": int, "warn_pct": int, "price_in_per_mtok": float,
                      "price_out_per_mtok": float, "ticket_prefix": str}

    def update_company(self, fields: dict, actor: str = "user") -> dict:
        self.require_company()
        sets, args = self._fields(fields, self.COMPANY_FIELDS)
        if "max_parallel" in fields and not 1 <= int(fields["max_parallel"]) <= 8:
            raise CompanyError("invalid", "max_parallel harus 1–8")
        if "warn_pct" in fields and not 1 <= int(fields["warn_pct"]) <= 100:
            raise CompanyError("invalid", "warn_pct harus 1–100")
        if sets:
            self.x(f"UPDATE company SET {', '.join(sets)}, updated_at=? WHERE id=1", [*args, self.clock()])
            self.log("company.updated", "company", 1, "mengubah pengaturan perusahaan: " + ", ".join(
                k for k in fields if k in self.COMPANY_FIELDS), actor=actor)
            self.changed("company", 1, "updated")
        return self.require_company()

    @staticmethod
    def _fields(fields: dict, allowed: dict) -> tuple[list[str], list]:
        sets, args = [], []
        for k, typ in allowed.items():
            if k in fields:
                v = fields[k]
                if v is None and typ is not str:
                    args.append(None)
                elif typ is bool:
                    args.append(1 if v in (True, 1, "1", "true", "on") else 0)
                else:
                    try:
                        args.append(typ(v) if v is not None else "")
                    except (TypeError, ValueError):
                        raise CompanyError("invalid", f"nilai {k} tidak valid") from None
                sets.append(f"{k}=?")
        return sets, args

    # --------------------------------------------------------------- goals --
    def save_goal(self, body: dict, actor: str = "user") -> dict:
        self.require_company()
        now = self.clock()
        gid = body.get("id")
        if body.get("parent_id") is not None and body.get("parent_id") != "":
            if not self.q1("SELECT id FROM goals WHERE id=?", (int(body["parent_id"]),)):
                raise CompanyError("not_found", "Tujuan induk tidak ditemukan")
            if gid and self._goal_cycle(int(gid), int(body["parent_id"])):
                raise CompanyError("invalid", "Tujuan tidak boleh menjadi induk dirinya sendiri")
        if gid:
            if not self.q1("SELECT id FROM goals WHERE id=?", (gid,)):
                raise CompanyError("not_found", "Tujuan tidak ditemukan")
            sets, args = self._fields(body, {"title": str, "description": str, "status": str, "parent_id": int})
            if sets:
                self.x(f"UPDATE goals SET {', '.join(sets)}, updated_at=? WHERE id=?", [*args, now, gid])
            self.log("goal.updated", "goal", gid, f"memperbarui tujuan “{body.get('title') or gid}”", actor=actor)
        else:
            title = str(body.get("title") or "").strip()
            if not title:
                raise CompanyError("invalid", "Judul tujuan wajib diisi")
            gid = self.x("INSERT INTO goals (parent_id, title, description, created_at, updated_at) VALUES (?,?,?,?,?)",
                         (body.get("parent_id") or None, title, str(body.get("description") or ""), now, now)).lastrowid
            self.log("goal.created", "goal", gid, f"menambah tujuan “{title}”", actor=actor)
        self.changed("goal", gid, "saved")
        return self.q1("SELECT * FROM goals WHERE id=?", (gid,))

    def _goal_cycle(self, gid: int, parent: int) -> bool:
        cur: int | None = parent
        for _ in range(100):
            if cur is None:
                return False
            if cur == gid:
                return True
            r = self.q1("SELECT parent_id FROM goals WHERE id=?", (cur,))
            cur = r["parent_id"] if r else None
        return True

    def delete_goal(self, gid: int) -> None:
        g = self.q1("SELECT * FROM goals WHERE id=?", (gid,))
        if not g:
            raise CompanyError("not_found", "Tujuan tidak ditemukan")
        self.x("DELETE FROM goals WHERE id=?", (gid,))
        self.log("goal.deleted", "goal", gid, f"menghapus tujuan “{g['title']}”")
        self.changed("goal", gid, "deleted")

    # ------------------------------------------------------------ projects --
    def save_project(self, body: dict, actor: str = "user") -> dict:
        self.require_company()
        self._non_negative(body, ("budget_monthly_cents",))
        now = self.clock()
        pid = body.get("id")
        if body.get("goal_id") and not self.q1("SELECT id FROM goals WHERE id=?", (int(body["goal_id"]),)):
            raise CompanyError("not_found", "Tujuan tidak ditemukan")
        if pid:
            if not self.q1("SELECT id FROM projects WHERE id=?", (pid,)):
                raise CompanyError("not_found", "Proyek tidak ditemukan")
            sets, args = self._fields(body, {"name": str, "description": str, "status": str, "goal_id": int,
                                             "budget_monthly_cents": int})
            if sets:
                self.x(f"UPDATE projects SET {', '.join(sets)}, updated_at=? WHERE id=?", [*args, now, pid])
            self.log("project.updated", "project", pid, f"memperbarui proyek “{body.get('name') or pid}”", actor=actor)
        else:
            name = str(body.get("name") or "").strip()
            if not name:
                raise CompanyError("invalid", "Nama proyek wajib diisi")
            pid = self.x("INSERT INTO projects (goal_id, name, description, budget_monthly_cents, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?)", (body.get("goal_id") or None, name, str(body.get("description") or ""),
                                                  int(body.get("budget_monthly_cents") or 0), now, now)).lastrowid
            self.log("project.created", "project", pid, f"membuat proyek “{name}”", actor=actor)
        self.changed("project", pid, "saved")
        return self.q1("SELECT * FROM projects WHERE id=?", (pid,))

    def delete_project(self, pid: int) -> None:
        p = self.q1("SELECT * FROM projects WHERE id=?", (pid,))
        if not p:
            raise CompanyError("not_found", "Proyek tidak ditemukan")
        self.x("DELETE FROM projects WHERE id=?", (pid,))
        self.log("project.deleted", "project", pid, f"menghapus proyek “{p['name']}”")
        self.changed("project", pid, "deleted")

    # --------------------------------------------------------------- units --
    UNIT_KINDS = ("organisasi", "agency")

    def unit(self, uid) -> dict | None:
        try:
            return self.q1("SELECT * FROM units WHERE id=?", (int(uid),)) if uid not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            return None

    def require_unit(self, uid) -> dict:
        u = self.unit(uid)
        if not u:
            raise CompanyError("not_found", "Organisasi/agency tidak ditemukan")
        return u

    def unit_by_name(self, name: str) -> dict | None:
        return self.q1("SELECT * FROM units WHERE lower(name)=lower(?) ORDER BY id LIMIT 1", ((name or "").strip(),))

    def units(self) -> list[dict]:
        return self.q("SELECT * FROM units ORDER BY COALESCE(parent_id,0), id")

    def unit_subtree(self, uid: int) -> set[int]:
        out: set[int] = set()
        stack = [uid]
        while stack:
            cur = stack.pop()
            for r in self.q("SELECT id FROM units WHERE parent_id=?", (cur,)):
                if r["id"] not in out:
                    out.add(r["id"])
                    stack.append(r["id"])
        return out

    def save_unit(self, body: dict, actor: str = "user") -> dict:
        self.require_company()
        now = self.clock()
        uid = body.get("id")
        kind = str(body.get("kind") or "").strip().lower() or None
        if kind is not None and kind not in self.UNIT_KINDS:
            raise CompanyError("invalid", "jenis harus organisasi atau agency")
        parent = body.get("parent_id")
        parent = int(parent) if parent not in (None, "", 0, "0") else None
        if parent is not None:
            self.require_unit(parent)
            if uid and (parent == int(uid) or parent in self.unit_subtree(int(uid))):
                raise CompanyError("invalid", "Struktur organisasi tidak boleh melingkar")
        if uid:
            u = self.require_unit(uid)
            sets, args = self._fields(body, {"name": str, "description": str})
            if kind:
                sets.append("kind=?")
                args.append(kind)
            if "parent_id" in body:
                sets.append("parent_id=?")
                args.append(parent)
            if "name" in body and not str(body.get("name") or "").strip():
                raise CompanyError("invalid", "Nama wajib diisi")
            if sets:
                self.x(f"UPDATE units SET {', '.join(sets)}, updated_at=? WHERE id=?", [*args, now, u["id"]])
            self.log("unit.updated", "unit", u["id"], f"memperbarui {u['kind']} {u['name']}", actor=actor)
            self.changed("unit", u["id"], "updated")
            return self.require_unit(u["id"])
        name = str(body.get("name") or "").strip()
        if not name:
            raise CompanyError("invalid", "Nama wajib diisi")
        kind = kind or ("agency" if parent else "organisasi")
        uid = self.x("INSERT INTO units (name, kind, parent_id, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (name, kind, parent, str(body.get("description") or ""), now, now)).lastrowid
        self.log("unit.created", "unit", uid, f"membuat {kind} {name}", actor=actor)
        self.changed("unit", uid, "created")
        return self.require_unit(uid)

    def delete_unit(self, uid, actor: str = "user") -> None:
        """Child units and the people inside move up to the parent (nobody is lost)."""
        u = self.require_unit(uid)
        with self.tx():
            self.db.execute("UPDATE units SET parent_id=? WHERE parent_id=?", (u["parent_id"], u["id"]))
            self.db.execute("UPDATE agents SET unit_id=? WHERE unit_id=?", (u["parent_id"], u["id"]))
            self.db.execute("DELETE FROM units WHERE id=?", (u["id"],))
        self.log("unit.deleted", "unit", u["id"], f"menghapus {u['kind']} {u['name']}", actor=actor)
        self.changed("unit", u["id"], "deleted")

    # -------------------------------------------------------------- agents --
    def agent(self, aid: int | None) -> dict | None:
        return self.q1("SELECT * FROM agents WHERE id=?", (aid,)) if aid else None

    def require_agent(self, aid) -> dict:
        try:
            a = self.agent(int(aid))
        except (TypeError, ValueError):
            a = None
        if not a:
            raise CompanyError("not_found", "Pegawai tidak ditemukan")
        return a

    def agent_by_session(self, sid: str) -> dict | None:
        return self.q1("SELECT * FROM agents WHERE session_id=?", (sid,)) if sid else None

    def reports(self, aid: int) -> list[dict]:
        return self.q("SELECT * FROM agents WHERE reports_to=? AND status!='terminated' ORDER BY id", (aid,))

    def subtree(self, aid: int) -> set[int]:
        out: set[int] = set()
        stack = [aid]
        while stack:
            cur = stack.pop()
            for r in self.q("SELECT id FROM agents WHERE reports_to=?", (cur,)):
                if r["id"] not in out:
                    out.add(r["id"])
                    stack.append(r["id"])
        return out

    AGENT_FIELDS = {"name": str, "title": str, "role": str, "job_description": str, "model": str, "provider": str,
                    "heartbeat_s": int, "budget_monthly_cents": int, "budget_monthly_tokens": int, "persona": str}

    @staticmethod
    def _name_list(v) -> str:
        """skills/tools arrive as a list or a comma string; stored as a JSON list of names."""
        if isinstance(v, str):
            v = [x for x in (p.strip() for p in v.split(",")) if x]
        if not isinstance(v, (list, tuple)):
            v = []
        out: list[str] = []
        for x in v:
            x = str(x).strip()
            if x and x not in out:
                out.append(x[:80])
        return json.dumps(out[:50], ensure_ascii=False)

    @staticmethod
    def parse_names(raw) -> list[str]:
        try:
            v = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        return [str(x) for x in v] if isinstance(v, list) else []

    @staticmethod
    def _non_negative(body: dict, keys: tuple[str, ...]) -> None:
        for k in keys:
            if body.get(k) in (None, ""):
                continue
            try:
                ok = float(body[k]) >= 0
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise CompanyError("invalid", f"nilai {k} harus angka 0 atau lebih")

    def save_agent(self, body: dict, actor: str = "user", actor_id: int | None = None) -> dict:
        c = self.require_company()
        self._non_negative(body, ("heartbeat_s", "budget_monthly_cents", "budget_monthly_tokens"))
        now = self.clock()
        aid = body.get("id")
        reports_to = body.get("reports_to")
        reports_to = int(reports_to) if reports_to not in (None, "", 0, "0") else None
        if reports_to is not None:
            mgr = self.agent(reports_to)
            if not mgr or mgr["status"] == "terminated":
                raise CompanyError("not_found", "Atasan tidak ditemukan")
            if aid and (reports_to == int(aid) or reports_to in self.subtree(int(aid))):
                raise CompanyError("invalid", "Struktur organisasi tidak boleh melingkar")
        if aid:
            a = self.require_agent(aid)
            if a["status"] == "terminated":
                raise CompanyError("conflict", "Pegawai sudah diberhentikan")
            sets, args = self._fields(body, self.AGENT_FIELDS)
            if "reports_to" in body:
                sets.append("reports_to=?")
                args.append(reports_to)
            if "unit_id" in body:
                unit = body.get("unit_id")
                unit = self.require_unit(unit)["id"] if unit not in (None, "", 0, "0") else None
                sets.append("unit_id=?")
                args.append(unit)
            for k in ("skills", "tools"):
                if k in body:
                    sets.append(f"{k}=?")
                    args.append(self._name_list(body[k]))
            if sets:
                self.x(f"UPDATE agents SET {', '.join(sets)}, updated_at=? WHERE id=?", [*args, now, a["id"]])
            self.log("agent.updated", "agent", a["id"], f"memperbarui profil {a['name']}", actor=actor, actor_id=actor_id)
            self.changed("agent", a["id"], "updated")
            return self.require_agent(a["id"])
        name = str(body.get("name") or "").strip()
        if not name:
            raise CompanyError("invalid", "Nama pegawai wajib diisi")
        if self.q1("SELECT id FROM agents WHERE lower(name)=lower(?) AND status!='terminated'", (name,)):
            raise CompanyError("conflict", f"Sudah ada pegawai bernama {name}")
        needs_ok = bool(c["require_hire_approval"]) and not body.get("skip_approval")
        status = "pending_approval" if needs_ok else "idle"
        unit = body.get("unit_id")
        unit = self.require_unit(unit)["id"] if unit not in (None, "", 0, "0") else None
        # Empty model = the PC's default model (MiMo V2.6 via 9Router on a fresh install,
        # router9.DEFAULT_MODEL), so a new employee follows whatever the main agent uses.
        model, provider = str(body.get("model") or ""), str(body.get("provider") or "")
        aid = self.x("INSERT INTO agents (name, title, role, reports_to, job_description, model, provider, status, heartbeat_s, "
                     "budget_monthly_cents, budget_monthly_tokens, unit_id, persona, skills, tools, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (name, str(body.get("title") or ""), str(body.get("role") or "pegawai"), reports_to,
                      str(body.get("job_description") or ""), model, provider, status,
                      int(body.get("heartbeat_s") or 0), int(body.get("budget_monthly_cents") or 0),
                      int(body.get("budget_monthly_tokens") or 0), unit, str(body.get("persona") or ""),
                      self._name_list(body.get("skills")), self._name_list(body.get("tools")), now, now)).lastrowid
        if needs_ok:
            self.create_approval("hire", agent_id=aid, title=f"Rekrut {name} sebagai {body.get('title') or 'pegawai'}",
                                 payload={"name": name, "title": body.get("title") or ""},
                                 requested_by=actor, actor_id=actor_id)
            self.log("agent.hire_requested", "agent", aid, f"mengajukan rekrut {name}", actor=actor, actor_id=actor_id)
        else:
            self.log("agent.hired", "agent", aid, f"merekrut {name} ({body.get('title') or 'pegawai'})",
                     actor=actor, actor_id=actor_id)
        self.changed("agent", aid, "created")
        return self.require_agent(aid)

    def set_agent_status(self, aid, status: str, *, reason: str | None = None, actor: str = "user",
                         log: bool = True) -> dict:
        a = self.require_agent(aid)
        if a["status"] == "terminated" and status != "terminated":
            raise CompanyError("conflict", f"{a['name']} sudah diberhentikan")
        if status not in AGENT_STATUSES:
            raise CompanyError("invalid", f"status tidak dikenal: {status}")
        self.x("UPDATE agents SET status=?, pause_reason=?, updated_at=? WHERE id=?",
               (status, reason if status == "paused" else None, self.clock(), a["id"]))
        if log:
            verbs = {"paused": "menjeda", "idle": "melanjutkan", "terminated": "memberhentikan", "error": "menandai galat"}
            if status in verbs:
                self.log(f"agent.{status}", "agent", a["id"], f"{verbs[status]} {a['name']}"
                         + (f" ({reason})" if reason and status == "paused" else ""), actor=actor)
        self.changed("agent", a["id"], status)
        return self.require_agent(a["id"])

    def delete_agent(self, aid, actor: str = "user") -> dict:
        """Remove an employee for good: open tickets lose their assignee, reports move up."""
        a = self.require_agent(aid)
        with self.tx():
            self.db.execute("UPDATE tickets SET assignee_id=NULL, checkout_agent_id=NULL, checkout_run_id=NULL, "
                            "checkout_at=NULL WHERE assignee_id=? OR checkout_agent_id=?", (a["id"], a["id"]))
            self.db.execute("UPDATE agents SET reports_to=? WHERE reports_to=?", (a["reports_to"], a["id"]))
            self.db.execute("UPDATE routines SET agent_id=NULL WHERE agent_id=?", (a["id"],))
            self.db.execute("DELETE FROM agents WHERE id=?", (a["id"],))
        self.log("agent.deleted", "agent", a["id"], f"menghapus {a['name']} dari Kantor", actor=actor)
        self.changed("agent", a["id"], "deleted")
        return a

    # ------------------------------------------------------------- tickets --
    def ticket(self, tid) -> dict | None:
        if isinstance(tid, str) and not tid.isdigit():
            return self.q1("SELECT * FROM tickets WHERE key=?", (tid.upper(),))
        try:
            return self.q1("SELECT * FROM tickets WHERE id=?", (int(tid),))
        except (TypeError, ValueError):
            return None

    def require_ticket(self, tid) -> dict:
        t = self.ticket(tid)
        if not t:
            raise CompanyError("not_found", "Tiket tidak ditemukan")
        return t

    def open_blockers(self, tid: int) -> list[dict]:
        return self.q("SELECT t.id, t.key, t.title, t.status FROM ticket_blockers b JOIN tickets t ON t.id=b.blocker_id "
                      "WHERE b.ticket_id=? AND t.status NOT IN ('done','cancelled')", (tid,))

    def create_ticket(self, body: dict, actor: str = "user", actor_id: int | None = None) -> dict:
        c = self.require_company()
        title = str(body.get("title") or "").strip()
        if not title:
            raise CompanyError("invalid", "Judul tiket wajib diisi")
        status = str(body.get("status") or ("todo" if body.get("assignee_id") else "backlog"))
        if status not in ("backlog", "todo", "blocked"):
            raise CompanyError("invalid", "Tiket baru hanya boleh backlog, todo, atau blocked")
        assignee = body.get("assignee_id")
        if assignee:
            a = self.require_agent(assignee)
            if a["status"] in ("terminated",):
                raise CompanyError("conflict", f"{a['name']} sudah diberhentikan")
        project_id = body.get("project_id") or None
        goal_id = body.get("goal_id") or None
        parent_id = body.get("parent_id") or None
        if parent_id:
            parent = self.require_ticket(parent_id)
            parent_id = parent["id"]
            project_id = project_id or parent["project_id"]
            goal_id = goal_id or parent["goal_id"]
        if project_id and not self.q1("SELECT id FROM projects WHERE id=?", (project_id,)):
            raise CompanyError("not_found", "Proyek tidak ditemukan")
        if goal_id and not self.q1("SELECT id FROM goals WHERE id=?", (goal_id,)):
            raise CompanyError("not_found", "Tujuan tidak ditemukan")
        now = self.clock()
        with self.tx():
            n = c["ticket_counter"] + 1
            self.db.execute("UPDATE company SET ticket_counter=? WHERE id=1", (n,))
            key = f"{c['ticket_prefix']}-{n}"
            tid = self.db.execute(
                "INSERT INTO tickets (key, project_id, goal_id, parent_id, title, description, status, priority, "
                "assignee_id, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, project_id, goal_id, parent_id, title, str(body.get("description") or ""), status,
                 max(0, min(3, int(body.get("priority") if body.get("priority") is not None else 1))),
                 int(assignee) if assignee else None, f"{actor}:{actor_id}" if actor_id else actor, now, now)).lastrowid
        who = self.agent(int(assignee))["name"] if assignee else None
        self.log("ticket.created", "ticket", tid, f"membuat {key} “{title}”" + (f" untuk {who}" if who else ""),
                 actor=actor, actor_id=actor_id)
        self.changed("ticket", tid, "created")
        return self.require_ticket(tid)

    TICKET_FIELDS = {"title": str, "description": str, "priority": int, "project_id": int, "goal_id": int}

    def update_ticket(self, tid, fields: dict, actor: str = "user", actor_id: int | None = None) -> dict:
        t = self.require_ticket(tid)
        sets, args = self._fields(fields, self.TICKET_FIELDS)
        if sets:
            self.x(f"UPDATE tickets SET {', '.join(sets)}, updated_at=? WHERE id=?", [*args, self.clock(), t["id"]])
            self.log("ticket.updated", "ticket", t["id"], f"memperbarui {t['key']}", actor=actor, actor_id=actor_id)
            self.changed("ticket", t["id"], "updated")
        return self.require_ticket(t["id"])

    def move_ticket(self, tid, to: str, *, actor: str = "user", actor_id: int | None = None,
                    force: bool = False) -> dict:
        """Status transition (not checkout: entering in_progress from todo goes through checkout)."""
        t = self.require_ticket(tid)
        frm = t["status"]
        if to not in TICKET_STATUSES:
            raise CompanyError("invalid", f"status tidak dikenal: {to}")
        if frm == to:
            return t
        reopen = frm in ("done", "cancelled") and to == "todo" and actor == "user"
        if not reopen and to not in TRANSITIONS[frm] and not force:
            raise CompanyError("conflict", f"{t['key']}: tidak bisa dari {STATUS_LABEL[frm]} ke {STATUS_LABEL[to]}",
                               status=frm)
        if to == "in_progress" and frm != "in_progress" and not force:
            if not t["assignee_id"]:
                raise CompanyError("conflict", f"{t['key']} belum punya penanggung jawab")
            if self.open_blockers(t["id"]):
                raise CompanyError("conflict", f"{t['key']} masih terhambat tiket lain")
        now = self.clock()
        extra = ""
        if to == "in_progress" and not t["started_at"]:
            extra = ", started_at=%f" % now
        if to in ("done", "cancelled"):
            extra = ", completed_at=%f, checkout_agent_id=NULL, checkout_run_id=NULL, checkout_at=NULL" % now
        if to in ("todo", "backlog") and frm in ("in_progress", "done", "cancelled"):
            extra = ", checkout_agent_id=NULL, checkout_run_id=NULL, checkout_at=NULL, completed_at=NULL"
        self.x(f"UPDATE tickets SET status=?, updated_at=?{extra} WHERE id=?", (to, now, t["id"]))
        self.log("ticket.moved", "ticket", t["id"], f"memindahkan {t['key']}: {STATUS_LABEL[frm]} → {STATUS_LABEL[to]}",
                 actor=actor, actor_id=actor_id, data={"from": frm, "to": to})
        self.changed("ticket", t["id"], "moved")
        return self.require_ticket(t["id"])

    def assign_ticket(self, tid, agent_id, *, actor: str = "user", actor_id: int | None = None) -> dict:
        t = self.require_ticket(tid)
        if t["checkout_run_id"] and t["checkout_agent_id"] != (int(agent_id) if agent_id else None):
            raise CompanyError("conflict", f"{t['key']} sedang dikerjakan; hentikan dulu sebelum dialihkan",
                               owner=t["checkout_agent_id"])
        name = None
        if agent_id:
            a = self.require_agent(agent_id)
            if a["status"] == "terminated":
                raise CompanyError("conflict", f"{a['name']} sudah diberhentikan")
            name = a["name"]
        status = t["status"]
        if agent_id and status == "backlog":
            status = "todo"
        if not agent_id and status == "in_progress":
            status = "todo"
        self.x("UPDATE tickets SET assignee_id=?, status=?, updated_at=? WHERE id=?",
               (int(agent_id) if agent_id else None, status, self.clock(), t["id"]))
        self.log("ticket.assigned", "ticket", t["id"], f"menugaskan {t['key']} ke {name}" if name
                 else f"melepas penanggung jawab {t['key']}", actor=actor, actor_id=actor_id)
        self.changed("ticket", t["id"], "assigned")
        return self.require_ticket(t["id"])

    def checkout(self, tid, agent_id: int, run_id: int | None = None) -> dict:
        """Atomic: one UPDATE decides who owns the ticket. Raises conflict (409) otherwise."""
        t = self.require_ticket(tid)
        a = self.require_agent(agent_id)
        if self.open_blockers(t["id"]):
            raise CompanyError("conflict", f"{t['key']} masih terhambat tiket lain", status=t["status"])
        now = self.clock()
        with self.tx():
            cur = self.db.execute(
                "UPDATE tickets SET status='in_progress', assignee_id=:a, checkout_agent_id=:a, checkout_run_id=:r, "
                "checkout_at=:now, started_at=COALESCE(started_at, :now), updated_at=:now "
                "WHERE id=:t AND status IN ('todo','backlog','blocked','review','in_progress') "
                "AND (assignee_id IS NULL OR assignee_id=:a) "
                "AND (checkout_run_id IS NULL OR checkout_agent_id=:a)",
                {"a": a["id"], "r": run_id, "now": now, "t": t["id"]})
            ok = cur.rowcount == 1
        if not ok:
            cur_t = self.require_ticket(t["id"])
            owner = self.agent(cur_t["checkout_agent_id"] or cur_t["assignee_id"])
            raise CompanyError("conflict", f"{t['key']} sedang dipegang {owner['name'] if owner else 'pihak lain'}"
                               if owner else f"{t['key']} tidak bisa diambil (status {cur_t['status']})",
                               owner=owner["id"] if owner else None, status=cur_t["status"])
        if t["status"] != "in_progress":
            self.log("ticket.checkout", "ticket", t["id"], f"mulai mengerjakan {t['key']}", actor="agent",
                     actor_id=a["id"])
        self.changed("ticket", t["id"], "checkout")
        return self.require_ticket(t["id"])

    def release(self, tid, agent_id: int | None = None, *, actor: str = "user") -> dict:
        t = self.require_ticket(tid)
        if agent_id is not None and t["checkout_agent_id"] not in (None, agent_id):
            raise CompanyError("conflict", f"{t['key']} dipegang pegawai lain", owner=t["checkout_agent_id"])
        self.x("UPDATE tickets SET checkout_agent_id=NULL, checkout_run_id=NULL, checkout_at=NULL, updated_at=? WHERE id=?",
               (self.clock(), t["id"]))
        if actor == "user":
            self.log("ticket.released", "ticket", t["id"], f"melepas kunci {t['key']}")
        self.changed("ticket", t["id"], "released")
        return self.require_ticket(t["id"])

    def comment(self, tid, body: str, *, actor: str = "user", actor_id: int | None = None) -> dict:
        t = self.require_ticket(tid)
        body = (body or "").strip()
        if not body:
            raise CompanyError("invalid", "Komentar kosong")
        cid = self.x("INSERT INTO comments (ticket_id, author_type, author_id, body, created_at) VALUES (?,?,?,?,?)",
                     (t["id"], actor, actor_id, body[:8000], self.clock())).lastrowid
        self.x("UPDATE tickets SET updated_at=? WHERE id=?", (self.clock(), t["id"]))
        self.log("ticket.commented", "ticket", t["id"], f"berkomentar di {t['key']}: {body[:120]}",
                 actor=actor, actor_id=actor_id)
        self.changed("ticket", t["id"], "commented")
        return self.q1("SELECT * FROM comments WHERE id=?", (cid,))

    def add_blocker(self, tid, blocker) -> dict:
        t, b = self.require_ticket(tid), self.require_ticket(blocker)
        if t["id"] == b["id"]:
            raise CompanyError("invalid", "Tiket tidak bisa menghambat dirinya sendiri")
        if self._blocks_path(b["id"], t["id"]):
            raise CompanyError("invalid", "Hambatan melingkar")
        self.x("INSERT OR IGNORE INTO ticket_blockers (ticket_id, blocker_id) VALUES (?,?)", (t["id"], b["id"]))
        self.log("ticket.blocked_by", "ticket", t["id"], f"{t['key']} terhambat oleh {b['key']}")
        self.changed("ticket", t["id"], "blocker")
        return self.require_ticket(t["id"])

    def _blocks_path(self, start: int, target: int) -> bool:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack += [r["blocker_id"] for r in self.q("SELECT blocker_id FROM ticket_blockers WHERE ticket_id=?", (cur,))]
        return False

    def remove_blocker(self, tid, blocker) -> dict:
        t, b = self.require_ticket(tid), self.require_ticket(blocker)
        self.x("DELETE FROM ticket_blockers WHERE ticket_id=? AND blocker_id=?", (t["id"], b["id"]))
        self.log("ticket.unblocked", "ticket", t["id"], f"{b['key']} tidak lagi menghambat {t['key']}")
        self.changed("ticket", t["id"], "blocker")
        return self.require_ticket(t["id"])

    def add_work_product(self, tid, title: str, ref: str = "", kind: str = "text", *, actor: str = "user",
                         actor_id: int | None = None) -> dict:
        t = self.require_ticket(tid)
        if not (title or "").strip():
            raise CompanyError("invalid", "Judul hasil kerja wajib diisi")
        if kind not in ("file", "link", "text"):
            kind = "text"
        wid = self.x("INSERT INTO work_products (ticket_id, kind, title, ref, agent_id, created_at) VALUES (?,?,?,?,?,?)",
                     (t["id"], kind, title.strip()[:200], (ref or "")[:8000], actor_id, self.clock())).lastrowid
        self.log("ticket.work_product", "ticket", t["id"], f"menambah hasil kerja di {t['key']}: {title[:80]}",
                 actor=actor, actor_id=actor_id)
        self.changed("ticket", t["id"], "work_product")
        return self.q1("SELECT * FROM work_products WHERE id=?", (wid,))

    def ancestry(self, tid) -> list[dict]:
        """Ticket → parent tickets → project → goal chain → company mission (closest first)."""
        out: list[dict] = []
        t = self.require_ticket(tid)
        seen: set[int] = set()
        cur = t
        project_id, goal_id = t["project_id"], t["goal_id"]
        while cur["parent_id"] and cur["parent_id"] not in seen:
            seen.add(cur["parent_id"])
            cur = self.ticket(cur["parent_id"])
            if not cur:
                break
            out.append({"type": "ticket", "id": cur["id"], "key": cur["key"], "title": cur["title"]})
            project_id = project_id or cur["project_id"]
            goal_id = goal_id or cur["goal_id"]
        if project_id:
            p = self.q1("SELECT * FROM projects WHERE id=?", (project_id,))
            if p:
                out.append({"type": "project", "id": p["id"], "title": p["name"], "description": p["description"]})
                goal_id = goal_id or p["goal_id"]
        gseen: set[int] = set()
        while goal_id and goal_id not in gseen:
            gseen.add(goal_id)
            g = self.q1("SELECT * FROM goals WHERE id=?", (goal_id,))
            if not g:
                break
            out.append({"type": "goal", "id": g["id"], "title": g["title"], "description": g["description"]})
            goal_id = g["parent_id"]
        c = self.company()
        if c and c["mission"]:
            out.append({"type": "mission", "id": 1, "title": c["mission"]})
        return out

    def ticket_detail(self, tid) -> dict:
        t = self.require_ticket(tid)
        return {
            **self._ticket_public(t),
            "comments": self.q("SELECT c.*, a.name AS author_name FROM comments c LEFT JOIN agents a "
                               "ON c.author_type='agent' AND a.id=c.author_id WHERE ticket_id=? ORDER BY c.id", (t["id"],)),
            "work_products": self.q("SELECT * FROM work_products WHERE ticket_id=? ORDER BY id", (t["id"],)),
            "blockers": self.q("SELECT t.id, t.key, t.title, t.status FROM ticket_blockers b JOIN tickets t "
                               "ON t.id=b.blocker_id WHERE b.ticket_id=?", (t["id"],)),
            "children": self.q("SELECT id, key, title, status, assignee_id FROM tickets WHERE parent_id=? ORDER BY id",
                               (t["id"],)),
            "ancestry": self.ancestry(t["id"]),
            "runs": self.q("SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 20", (t["id"],)),
            "approvals": self.q("SELECT * FROM approvals WHERE ticket_id=? ORDER BY id DESC", (t["id"],)),
        }

    def _ticket_public(self, t: dict) -> dict:
        a = self.agent(t["assignee_id"])
        return {**t, "assignee_name": a["name"] if a else None, "status_label": STATUS_LABEL.get(t["status"], t["status"]),
                "blocked_by": len(self.open_blockers(t["id"])), "locked": bool(t["checkout_run_id"])}

    def list_tickets(self, *, status: str | None = None, assignee_id=None, project_id=None, limit: int = 500) -> list[dict]:
        where, args = [], []
        if status:
            where.append("status=?")
            args.append(status)
        if assignee_id:
            where.append("assignee_id=?")
            args.append(int(assignee_id))
        if project_id:
            where.append("project_id=?")
            args.append(int(project_id))
        sql = "SELECT * FROM tickets" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'review' THEN 1 WHEN 'todo' THEN 2 " \
               "WHEN 'blocked' THEN 3 WHEN 'backlog' THEN 4 ELSE 5 END, priority DESC, id DESC LIMIT ?"
        return [self._ticket_public(t) for t in self.q(sql, [*args, max(1, min(int(limit), 2000))])]

    def next_ticket_for(self, aid: int) -> dict | None:
        mine = self.q1("SELECT * FROM tickets WHERE assignee_id=? AND status='in_progress' "
                       "AND (checkout_run_id IS NULL OR checkout_agent_id=?) ORDER BY priority DESC, id LIMIT 1", (aid, aid))
        if mine and not self.open_blockers(mine["id"]):
            return mine
        for t in self.q("SELECT * FROM tickets WHERE assignee_id=? AND status='todo' ORDER BY priority DESC, id", (aid,)):
            if not self.open_blockers(t["id"]):
                return t
        return None

    # ----------------------------------------------------------- approvals --
    def create_approval(self, kind: str, *, ticket_id=None, agent_id=None, title: str = "", payload: dict | None = None,
                        requested_by: str = "user", actor_id: int | None = None) -> dict:
        if kind not in APPROVAL_KINDS:
            raise CompanyError("invalid", f"jenis persetujuan tidak dikenal: {kind}")
        dup = self.q1("SELECT * FROM approvals WHERE kind=? AND status='pending' AND IFNULL(ticket_id,0)=IFNULL(?,0) "
                      "AND IFNULL(agent_id,0)=IFNULL(?,0)", (kind, ticket_id, agent_id))
        if dup:
            return dup
        apid = self.x("INSERT INTO approvals (kind, ticket_id, agent_id, title, payload, requested_by, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (kind, ticket_id, agent_id, title[:300],
                                                 json.dumps(payload or {}, ensure_ascii=False),
                                                 f"agent:{actor_id}" if requested_by == "agent" else requested_by,
                                                 self.clock())).lastrowid
        self.log("approval.requested", "approval", apid, f"meminta persetujuan: {title}", actor=requested_by,
                 actor_id=actor_id)
        self.changed("approval", apid, "created")
        return self.approval(apid)

    def approval(self, apid) -> dict:
        r = self.q1("SELECT * FROM approvals WHERE id=?", (int(apid),))
        if not r:
            raise CompanyError("not_found", "Persetujuan tidak ditemukan")
        r["payload"] = json.loads(r["payload"] or "{}")
        return r

    def list_approvals(self, status: str | None = "pending") -> list[dict]:
        rows = self.q("SELECT ap.*, a.name AS agent_name, t.key AS ticket_key, t.title AS ticket_title FROM approvals ap "
                      "LEFT JOIN agents a ON a.id=ap.agent_id LEFT JOIN tickets t ON t.id=ap.ticket_id"
                      + (" WHERE ap.status=?" if status else "") + " ORDER BY ap.id DESC LIMIT 200",
                      (status,) if status else ())
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def decide(self, apid, decision: str, note: str = "") -> dict:
        ap = self.approval(apid)
        if ap["status"] != "pending":
            raise CompanyError("conflict", "Persetujuan ini sudah diputuskan", status=ap["status"])
        if decision not in ("approved", "rejected", "cancelled"):
            raise CompanyError("invalid", "keputusan harus approved / rejected / cancelled")
        self.x("UPDATE approvals SET status=?, note=?, decided_at=? WHERE id=?", (decision, note or "", self.clock(), ap["id"]))
        verb = {"approved": "menyetujui", "rejected": "menolak", "cancelled": "membatalkan"}[decision]
        self.log(f"approval.{decision}", "approval", ap["id"], f"{verb}: {ap['title']}" + (f" — {note}" if note else ""))
        # Side effects of the decision.
        if ap["kind"] == "hire" and ap["agent_id"]:
            a = self.agent(ap["agent_id"])
            if a and a["status"] == "pending_approval":
                self.set_agent_status(a["id"], "idle" if decision == "approved" else "terminated", log=False)
        elif ap["kind"] == "review" and ap["ticket_id"]:
            t = self.ticket(ap["ticket_id"])
            if t and t["status"] == "review":
                if decision == "approved":
                    self.move_ticket(t["id"], "done", actor="user")
                elif decision == "rejected":
                    self.move_ticket(t["id"], "in_progress", actor="user", force=True)
                    self.comment(t["id"], "Ditolak saat ditinjau" + (f": {note}" if note else "."), actor="user")
        elif ap["kind"] == "budget" and ap["agent_id"] and decision == "approved":
            a = self.agent(ap["agent_id"])
            if a and a["status"] == "paused" and a["pause_reason"] == "budget":
                extra = int(ap["payload"].get("extra_cents") or 0)
                if extra:
                    self.x("UPDATE agents SET budget_monthly_cents=budget_monthly_cents+? WHERE id=?", (extra, a["id"]))
                self.set_agent_status(a["id"], "idle", log=False)
        self.changed("approval", ap["id"], decision)
        return self.approval(ap["id"])

    # --------------------------------------------------------------- costs --
    def record_cost(self, *, agent_id: int | None, prompt_tokens: int, completion_tokens: int, model: str = "",
                    ticket_id: int | None = None, run_id: int | None = None) -> dict:
        c = self.company() or {}
        cents = (prompt_tokens * float(c.get("price_in_per_mtok") or 0)
                 + completion_tokens * float(c.get("price_out_per_mtok") or 0)) / 1_000_000
        project_id = None
        if ticket_id:
            t = self.ticket(ticket_id)
            project_id = t["project_id"] if t else None
        now = self.clock()
        self.x("INSERT INTO cost_events (agent_id, project_id, ticket_id, run_id, model, prompt_tokens, completion_tokens, "
               "cost_cents, month, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (agent_id, project_id, ticket_id, run_id, model, int(prompt_tokens), int(completion_tokens), cents,
                month_of(now), now))
        if run_id:
            self.x("UPDATE runs SET prompt_tokens=prompt_tokens+?, completion_tokens=completion_tokens+?, "
                   "cost_cents=cost_cents+? WHERE id=?", (int(prompt_tokens), int(completion_tokens), cents, run_id))
        self.changed("cost", agent_id, "recorded")
        return {"cost_cents": cents, "project_id": project_id}

    def spend(self, *, agent_id=None, project_id=None, month: str | None = None) -> dict:
        month = month or month_of(self.clock())
        where, args = ["month=?"], [month]
        if agent_id:
            where.append("agent_id=?")
            args.append(agent_id)
        if project_id:
            where.append("project_id=?")
            args.append(project_id)
        r = self.q1("SELECT COALESCE(SUM(cost_cents),0) AS cents, COALESCE(SUM(prompt_tokens+completion_tokens),0) AS tokens, "
                    "COUNT(*) AS events FROM cost_events WHERE " + " AND ".join(where), args) or {}
        return {"cents": round(float(r.get("cents") or 0), 4), "tokens": int(r.get("tokens") or 0),
                "events": int(r.get("events") or 0)}

    @staticmethod
    def _pct(used: float, limit: float) -> float | None:
        return round(100.0 * used / limit, 1) if limit and limit > 0 else None

    def budget_state(self, *, agent: dict | None = None, project: dict | None = None) -> dict:
        """{'pct': max % used of any limit, 'level': ok|warning|exceeded, ...}."""
        c = self.company() or {}
        warn = int(c.get("warn_pct") or 80)
        if agent is not None:
            s = self.spend(agent_id=agent["id"])
            lims = [(s["cents"], agent["budget_monthly_cents"]), (s["tokens"], agent["budget_monthly_tokens"])]
        elif project is not None:
            s = self.spend(project_id=project["id"])
            lims = [(s["cents"], project["budget_monthly_cents"])]
        else:
            s = self.spend()
            lims = [(s["cents"], c.get("budget_monthly_cents") or 0), (s["tokens"], c.get("budget_monthly_tokens") or 0)]
        pcts = [p for p in (self._pct(u, lim) for u, lim in lims) if p is not None]
        pct = max(pcts) if pcts else None
        level = "ok" if pct is None or pct < warn else ("warning" if pct < 100 else "exceeded")
        return {**s, "pct": pct, "level": level}

    def check_budgets(self, agent_id: int | None) -> list[str]:
        """Warn once per month per scope; hard-stop (pause) the agent at 100 %. Returns actions taken."""
        out: list[str] = []
        month = month_of(self.clock())
        scopes: list[tuple[str, dict, str]] = [("company", self.budget_state(), "perusahaan")]
        a = self.agent(agent_id) if agent_id else None
        if a:
            scopes.append((f"agent:{a['id']}", self.budget_state(agent=a), a["name"]))
        for scope, st, label in scopes:
            if st["level"] == "ok":
                continue
            fresh = self.x("INSERT OR IGNORE INTO budget_alerts (scope, month, level) VALUES (?,?,?)",
                           (scope, month, st["level"])).rowcount == 1
            if fresh and st["level"] == "warning":
                self.log("budget.warning", "budget", a["id"] if scope.startswith("agent") and a else None,
                         f"anggaran {label} sudah terpakai {st['pct']}%", actor="system")
                out.append(f"warning:{scope}")
            if st["level"] == "exceeded":
                if fresh:
                    self.log("budget.hard_stop", "budget", a["id"] if scope.startswith("agent") and a else None,
                             f"anggaran {label} habis ({st['pct']}%) — pekerjaan dihentikan", actor="system")
                out.append(f"exceeded:{scope}")
        if a and any(x.startswith("exceeded") for x in out) and a["status"] not in ("paused", "terminated"):
            self.set_agent_status(a["id"], "paused", reason="budget", actor="system", log=False)
        return out

    def costs(self, month: str | None = None) -> dict:
        month = month or month_of(self.clock())
        by_agent = self.q("SELECT a.id, a.name, a.title, a.budget_monthly_cents, a.budget_monthly_tokens, "
                          "COALESCE(SUM(e.cost_cents),0) AS cents, COALESCE(SUM(e.prompt_tokens+e.completion_tokens),0) AS tokens "
                          "FROM agents a LEFT JOIN cost_events e ON e.agent_id=a.id AND e.month=? "
                          "WHERE a.status!='terminated' GROUP BY a.id ORDER BY cents DESC, tokens DESC", (month,))
        by_project = self.q("SELECT p.id, p.name, p.budget_monthly_cents, COALESCE(SUM(e.cost_cents),0) AS cents, "
                            "COALESCE(SUM(e.prompt_tokens+e.completion_tokens),0) AS tokens FROM projects p "
                            "LEFT JOIN cost_events e ON e.project_id=p.id AND e.month=? GROUP BY p.id ORDER BY cents DESC",
                            (month,))
        for r in by_agent:
            r["pct"] = max([p for p in (self._pct(r["cents"], r["budget_monthly_cents"]),
                                        self._pct(r["tokens"], r["budget_monthly_tokens"])) if p is not None], default=None)
        for r in by_project:
            r["pct"] = self._pct(r["cents"], r["budget_monthly_cents"])
        c = self.company() or {}
        return {"month": month, "total": self.budget_state(), "by_agent": by_agent, "by_project": by_project,
                "budget_monthly_cents": c.get("budget_monthly_cents") or 0,
                "budget_monthly_tokens": c.get("budget_monthly_tokens") or 0, "warn_pct": c.get("warn_pct") or 80,
                "price_in_per_mtok": c.get("price_in_per_mtok") or 0, "price_out_per_mtok": c.get("price_out_per_mtok") or 0}

    # ---------------------------------------------------------------- runs --
    def start_run(self, agent_id: int, reason: str, ticket_id: int | None = None) -> int:
        return self.x("INSERT INTO runs (agent_id, ticket_id, reason, started_at) VALUES (?,?,?,?)",
                      (agent_id, ticket_id, reason, self.clock())).lastrowid

    def finish_run(self, run_id: int, status: str, error: str | None = None, session_id: str | None = None) -> None:
        self.x("UPDATE runs SET status=?, error=?, finished_at=?, session_id=COALESCE(?, session_id) WHERE id=?",
               (status, error, self.clock(), session_id, run_id))

    def wake(self, agent_id: int, reason: str, ticket_id: int | None = None) -> None:
        if not self.q1("SELECT id FROM wakeups WHERE agent_id=? AND reason=? AND IFNULL(ticket_id,0)=IFNULL(?,0)",
                       (agent_id, reason, ticket_id)):
            self.x("INSERT INTO wakeups (agent_id, reason, ticket_id, created_at) VALUES (?,?,?,?)",
                   (agent_id, reason, ticket_id, self.clock()))

    def take_wakeups(self) -> dict[int, list[dict]]:
        with self.tx():
            rows = [dict(r) for r in self.db.execute("SELECT * FROM wakeups ORDER BY id").fetchall()]
            self.db.execute("DELETE FROM wakeups")
        out: dict[int, list[dict]] = {}
        for r in rows:
            out.setdefault(r["agent_id"], []).append(r)
        return out

    # ------------------------------------------------------------ routines --
    def save_routine(self, body: dict) -> dict:
        from neovarch import cron as cronmod
        self.require_company()
        rid = body.get("id")
        now = self.clock()
        if "schedule" in body or not rid:
            try:
                sched = cronmod.parse_schedule(str(body.get("schedule") or ""))
            except cronmod.ScheduleError as exc:
                raise CompanyError("invalid", f"Jadwal tidak valid: {exc}") from None
            nxt = cronmod.next_run(sched, after=now, last_run=None)
        if body.get("agent_id"):
            self.require_agent(body["agent_id"])
        if rid:
            r = self.q1("SELECT * FROM routines WHERE id=?", (rid,))
            if not r:
                raise CompanyError("not_found", "Rutinitas tidak ditemukan")
            sets, args = self._fields(body, {"name": str, "schedule": str, "agent_id": int, "project_id": int,
                                             "title": str, "description": str, "enabled": bool})
            if "schedule" in body:
                sets.append("next_run_at=?")
                args.append(nxt)
            if sets:
                self.x(f"UPDATE routines SET {', '.join(sets)} WHERE id=?", [*args, rid])
            self.log("routine.updated", "routine", rid, f"memperbarui rutinitas “{body.get('name') or r['name']}”")
        else:
            name = str(body.get("name") or body.get("title") or "").strip()
            title = str(body.get("title") or name).strip()
            if not name:
                raise CompanyError("invalid", "Nama rutinitas wajib diisi")
            rid = self.x("INSERT INTO routines (name, schedule, agent_id, project_id, title, description, enabled, "
                         "next_run_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (name, str(body["schedule"]), body.get("agent_id") or None, body.get("project_id") or None,
                          title, str(body.get("description") or ""), 0 if body.get("enabled") is False else 1, nxt,
                          now)).lastrowid
            self.log("routine.created", "routine", rid, f"membuat rutinitas “{name}” ({body['schedule']})")
        self.changed("routine", rid, "saved")
        return self.q1("SELECT * FROM routines WHERE id=?", (rid,))

    def delete_routine(self, rid) -> None:
        r = self.q1("SELECT * FROM routines WHERE id=?", (int(rid),))
        if not r:
            raise CompanyError("not_found", "Rutinitas tidak ditemukan")
        self.x("DELETE FROM routines WHERE id=?", (r["id"],))
        self.log("routine.deleted", "routine", r["id"], f"menghapus rutinitas “{r['name']}”")
        self.changed("routine", r["id"], "deleted")

    def fire_routine(self, rid, *, actor: str = "system") -> dict:
        from neovarch import cron as cronmod
        r = self.q1("SELECT * FROM routines WHERE id=?", (int(rid),))
        if not r:
            raise CompanyError("not_found", "Rutinitas tidak ditemukan")
        now = self.clock()
        stamp = time.strftime("%Y-%m-%d", time.localtime(now))
        t = self.create_ticket({"title": f"{r['title']} ({stamp})", "description": r["description"],
                                "assignee_id": r["agent_id"], "project_id": r["project_id"]}, actor=actor)
        try:
            nxt = cronmod.next_run(cronmod.parse_schedule(r["schedule"]), after=now, last_run=now)
        except cronmod.ScheduleError:
            nxt = None
        self.x("UPDATE routines SET last_run_at=?, next_run_at=? WHERE id=?", (now, nxt, r["id"]))
        return t

    def due_routines(self) -> list[dict]:
        return self.q("SELECT * FROM routines WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=?",
                      (self.clock(),))

    # ------------------------------------------------------------ activity --
    def activity(self, limit: int = 100, before: int | None = None, entity: str | None = None,
                 entity_id: int | None = None) -> list[dict]:
        where, args = [], []
        if before:
            where.append("id<?")
            args.append(int(before))
        if entity:
            where.append("entity=?")
            args.append(entity)
        if entity_id:
            where.append("entity_id=?")
            args.append(int(entity_id))
        rows = self.q("SELECT * FROM activity" + (" WHERE " + " AND ".join(where) if where else "")
                      + " ORDER BY id DESC LIMIT ?", [*args, max(1, min(int(limit), 500))])
        for r in rows:
            r["data"] = json.loads(r["data"] or "{}")
        return rows

    # ------------------------------------------------------------ snapshot --
    def agents_public(self) -> list[dict]:
        out = []
        for a in self.q("SELECT * FROM agents WHERE status!='terminated' ORDER BY COALESCE(reports_to,0), id"):
            cur = self.q1("SELECT id, key, title, status FROM tickets WHERE assignee_id=? AND status IN "
                          "('in_progress','review') ORDER BY CASE status WHEN 'in_progress' THEN 0 ELSE 1 END, "
                          "updated_at DESC LIMIT 1", (a["id"],))
            counts = {r["status"]: r["n"] for r in self.q(
                "SELECT status, COUNT(*) AS n FROM tickets WHERE assignee_id=? GROUP BY status", (a["id"],))}
            mgr = self.agent(a["reports_to"])
            unit = self.unit(a.get("unit_id"))
            a = {**a, "skills": self.parse_names(a.get("skills")), "tools": self.parse_names(a.get("tools")),
                 "persona": a.get("persona") or "", "unit_name": unit["name"] if unit else None}
            out.append({**a, "reports_to_name": mgr["name"] if mgr else None, "current_ticket": cur,
                        "ticket_counts": counts, "budget": self.budget_state(agent=a),
                        "pending_approvals": self.q1("SELECT COUNT(*) AS n FROM approvals WHERE agent_id=? AND "
                                                     "status='pending'", (a["id"],))["n"]})
        return out

    def snapshot(self) -> dict:
        c = self.company()
        if not c:
            return {"exists": False}
        counts = {s: 0 for s in TICKET_STATUSES}
        for r in self.q("SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"):
            counts[r["status"]] = r["n"]
        return {
            "exists": True, "company": c,
            "goals": self.q("SELECT * FROM goals ORDER BY COALESCE(parent_id,0), id"),
            "units": self.units(),
            "projects": self.q("SELECT * FROM projects ORDER BY id"),
            "agents": self.agents_public(),
            "ticket_counts": counts,
            "pending_approvals": len(self.q("SELECT id FROM approvals WHERE status='pending'")),
            "budget": self.budget_state(),
            "routines": self.q("SELECT * FROM routines ORDER BY id"),
            "running_runs": self.q("SELECT * FROM runs WHERE status='running' ORDER BY id"),
            "generated_at": self.clock(),
        }
