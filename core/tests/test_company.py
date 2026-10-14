"""Perusahaan store: data model, state machine, checkout locks, approvals, budgets, routines, activity."""

import threading

import pytest

from neovarch.company import CompanyError, CompanyStore


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store(home):
    s = CompanyStore(clock=Clock())
    yield s
    s.close()


def org(s, *, approval=False):
    s.setup("Neovarch Studio", "Bikin aplikasi yang membantu orang", require_hire_approval=approval)
    dimas = s.save_agent({"name": "Dimas", "title": "CEO", "skip_approval": True})
    hana = s.save_agent({"name": "Hana", "title": "CTO", "reports_to": dimas["id"], "skip_approval": True})
    raka = s.save_agent({"name": "Raka", "title": "Engineer", "reports_to": hana["id"], "skip_approval": True})
    return dimas, hana, raka


def test_db_lives_under_neovarch_home(store, home):
    assert store.path == home / "company.db"
    assert store.snapshot() == {"exists": False}
    with pytest.raises(CompanyError) as e:
        store.create_ticket({"title": "x"})
    assert e.value.code == "invalid"


def test_setup_once_and_settings(store):
    c = store.setup("Studio", "Misi", autorun=True, warn_pct=70)
    assert c["autorun"] is True and c["warn_pct"] == 70 and c["require_review"] is True
    with pytest.raises(CompanyError) as e:
        store.setup("Lagi")
    assert e.value.code == "conflict"
    with pytest.raises(CompanyError):
        store.update_company({"max_parallel": 99})


def test_org_chart_tree_rules(store):
    dimas, hana, raka = org(store)
    assert store.subtree(dimas["id"]) == {hana["id"], raka["id"]}
    with pytest.raises(CompanyError, match="melingkar"):
        store.save_agent({"id": dimas["id"], "reports_to": raka["id"]})
    with pytest.raises(CompanyError) as e:
        store.save_agent({"name": "hana"})
    assert e.value.code == "conflict"
    snap = store.snapshot()
    by = {a["name"]: a for a in snap["agents"]}
    assert by["Raka"]["reports_to_name"] == "Hana"


def test_hire_needs_approval(store):
    org(store, approval=True)
    sari = store.save_agent({"name": "Sari", "title": "Marketing"})
    assert sari["status"] == "pending_approval"
    [ap] = store.list_approvals()
    assert ap["kind"] == "hire" and ap["agent_id"] == sari["id"]
    store.decide(ap["id"], "approved")
    assert store.agent(sari["id"])["status"] == "idle"
    with pytest.raises(CompanyError):
        store.decide(ap["id"], "rejected")
    budi = store.save_agent({"name": "Budi"})
    store.decide(store.list_approvals()[0]["id"], "rejected")
    assert store.agent(budi["id"])["status"] == "terminated"


def test_ticket_keys_ancestry_and_state_machine(store):
    dimas, hana, raka = org(store)
    g0 = store.save_goal({"title": "Jadi aplikasi nomor satu"})
    g1 = store.save_goal({"title": "Rilis 1.5 stabil", "parent_id": g0["id"]})
    p = store.save_project({"name": "Desktop", "goal_id": g1["id"]})
    parent = store.create_ticket({"title": "Rencana rilis", "project_id": p["id"], "assignee_id": dimas["id"]})
    child = store.create_ticket({"title": "Perbaiki crash", "parent_id": parent["id"], "assignee_id": raka["id"]})
    assert parent["key"] == "NV-1" and child["key"] == "NV-2"
    assert child["project_id"] == p["id"] and child["status"] == "todo"
    chain = [(x["type"], x["title"]) for x in store.ancestry(child["id"])]
    assert chain == [("ticket", "Rencana rilis"), ("project", "Desktop"), ("goal", "Rilis 1.5 stabil"),
                     ("goal", "Jadi aplikasi nomor satu"), ("mission", "Bikin aplikasi yang membantu orang")]
    # no assignee -> backlog; backlog cannot jump to done
    b = store.create_ticket({"title": "Ide"})
    assert b["status"] == "backlog"
    with pytest.raises(CompanyError) as e:
        store.move_ticket(b["id"], "done")
    assert e.value.code == "conflict"
    store.move_ticket(b["id"], "todo")
    with pytest.raises(CompanyError, match="penanggung jawab"):
        store.move_ticket(b["id"], "in_progress")
    store.move_ticket(b["id"], "cancelled")
    # user can reopen a terminal ticket
    assert store.move_ticket(b["id"], "todo")["status"] == "todo"
    assert store.ticket("nv-2")["id"] == child["id"]


def test_checkout_is_atomic_and_exclusive(store):
    dimas, hana, raka = org(store)
    t = store.create_ticket({"title": "Tugas"})
    winners, losers = [], []

    def grab(aid, rid):
        try:
            store.checkout(t["id"], aid, rid)
            winners.append(aid)
        except CompanyError as exc:
            assert exc.code == "conflict"
            losers.append(aid)

    threads = [threading.Thread(target=grab, args=(a, i)) for i, a in enumerate([hana["id"], raka["id"]] * 5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(set(winners)) == 1
    owner = winners[0]
    cur = store.ticket(t["id"])
    assert cur["status"] == "in_progress" and cur["assignee_id"] == owner and cur["checkout_agent_id"] == owner
    other = raka["id"] if owner == hana["id"] else hana["id"]
    with pytest.raises(CompanyError) as e:
        store.checkout(t["id"], other, 99)
    assert e.value.data["owner"] == owner
    with pytest.raises(CompanyError):
        store.assign_ticket(t["id"], other)       # locked: cannot reassign mid-run
    store.release(t["id"])
    assert store.ticket(t["id"])["checkout_run_id"] is None


def test_blockers_prevent_checkout(store):
    dimas, hana, raka = org(store)
    a = store.create_ticket({"title": "Desain API", "assignee_id": hana["id"]})
    b = store.create_ticket({"title": "Implementasi", "assignee_id": raka["id"]})
    store.add_blocker(b["id"], a["id"])
    with pytest.raises(CompanyError, match="melingkar"):
        store.add_blocker(a["id"], b["id"])
    with pytest.raises(CompanyError, match="terhambat"):
        store.checkout(b["id"], raka["id"], 1)
    assert store.next_ticket_for(raka["id"]) is None
    store.checkout(a["id"], hana["id"], 1)
    store.move_ticket(a["id"], "done")
    assert store.next_ticket_for(raka["id"])["id"] == b["id"]


def test_review_approval_flow(store):
    dimas, hana, raka = org(store)
    t = store.create_ticket({"title": "Fitur", "assignee_id": raka["id"]})
    store.checkout(t["id"], raka["id"], 1)
    store.move_ticket(t["id"], "review", actor="agent", actor_id=raka["id"])
    ap = store.create_approval("review", ticket_id=t["id"], agent_id=raka["id"], title="Tinjau", requested_by="agent",
                               actor_id=raka["id"])
    assert store.create_approval("review", ticket_id=t["id"], agent_id=raka["id"])["id"] == ap["id"]  # deduped
    store.decide(ap["id"], "rejected", "kurang tes")
    cur = store.ticket_detail(t["id"])
    assert cur["status"] == "in_progress" and "kurang tes" in cur["comments"][-1]["body"]
    store.move_ticket(t["id"], "review")
    ap2 = store.create_approval("review", ticket_id=t["id"], agent_id=raka["id"])
    store.decide(ap2["id"], "approved")
    assert store.ticket(t["id"])["status"] == "done" and store.ticket(t["id"])["completed_at"]


def test_costs_budget_warning_and_hard_stop(store):
    dimas, hana, raka = org(store)
    store.update_company({"price_in_per_mtok": 100, "price_out_per_mtok": 400, "warn_pct": 80})
    store.save_agent({"id": raka["id"], "budget_monthly_cents": 10})
    t = store.create_ticket({"title": "x", "assignee_id": raka["id"]})
    # 20k in + 2k out = 2 + 0.8 = 2.8 cents
    r = store.record_cost(agent_id=raka["id"], prompt_tokens=20_000, completion_tokens=2_000, ticket_id=t["id"])
    assert r["cost_cents"] == pytest.approx(2.8)
    assert store.check_budgets(raka["id"]) == []
    store.record_cost(agent_id=raka["id"], prompt_tokens=60_000, completion_tokens=0)   # 8.8 -> 88 %
    assert store.check_budgets(raka["id"]) == ["warning:agent:%d" % raka["id"]]
    assert store.check_budgets(raka["id"]) == []          # warned once per month
    store.record_cost(agent_id=raka["id"], prompt_tokens=20_000, completion_tokens=0)   # 10.8 -> 108 %
    assert "exceeded:agent:%d" % raka["id"] in store.check_budgets(raka["id"])
    a = store.agent(raka["id"])
    assert a["status"] == "paused" and a["pause_reason"] == "budget"
    costs = store.costs()
    row = next(x for x in costs["by_agent"] if x["id"] == raka["id"])
    assert row["pct"] == pytest.approx(108.0) and row["tokens"] == 102_000
    actions = [x["action"] for x in store.activity()]
    assert "budget.warning" in actions and "budget.hard_stop" in actions


def test_token_budget_on_company(store):
    org(store)
    store.update_company({"budget_monthly_tokens": 1000})
    store.record_cost(agent_id=None, prompt_tokens=900, completion_tokens=200)
    assert store.budget_state()["level"] == "exceeded"


def test_routines_create_tickets(store):
    dimas, hana, raka = org(store)
    with pytest.raises(CompanyError, match="Jadwal"):
        store.save_routine({"name": "Laporan", "schedule": "bukan jadwal"})
    r = store.save_routine({"name": "Laporan harian", "schedule": "every 1h", "agent_id": hana["id"],
                            "title": "Laporan harian"})
    assert r["next_run_at"] > store.clock()
    assert store.due_routines() == []
    store.clock.t += 3601
    [due] = store.due_routines()
    t = store.fire_routine(due["id"])
    assert t["assignee_id"] == hana["id"] and t["status"] == "todo" and t["title"].startswith("Laporan harian (")
    assert store.due_routines() == []


def test_activity_records_every_mutation(store):
    dimas, hana, raka = org(store)
    t = store.create_ticket({"title": "Catat", "assignee_id": raka["id"]})
    store.comment(t["id"], "semangat")
    store.add_work_product(t["id"], "Laporan", "/tmp/a.md", "file")
    acts = store.activity(limit=50)
    kinds = [a["action"] for a in acts]
    for k in ("company.created", "agent.hired", "ticket.created", "ticket.commented", "ticket.work_product"):
        assert k in kinds
    assert acts[0]["id"] > acts[-1]["id"]
    assert store.activity(entity="ticket", entity_id=t["id"])
    assert all(a["summary"] for a in acts)


def test_change_listener_never_breaks_writes(store):
    def boom(*_):
        raise RuntimeError("listener down")
    store.on_change = boom
    store.setup("Studio")
    assert store.company()["name"] == "Studio"


def test_goal_project_edit_and_validation(store):
    store.setup("Studio", "Misi")
    assert store.company()["autorun"] is True  # heartbeat on by default once a company exists
    g = store.save_goal({"title": "Rilis 1.4.5"})
    sub = store.save_goal({"title": "Stabil di Windows", "parent_id": g["id"]})
    store.save_goal({"id": sub["id"], "title": "Stabil di Windows & Linux", "description": "tanpa crash"})
    assert store.q1("SELECT title FROM goals WHERE id=?", (sub["id"],))["title"] == "Stabil di Windows & Linux"
    with pytest.raises(CompanyError, match="induk"):
        store.save_goal({"id": g["id"], "parent_id": sub["id"]})
    p = store.save_project({"name": "Desktop", "goal_id": g["id"], "budget_monthly_cents": 500})
    store.save_project({"id": p["id"], "goal_id": None, "budget_monthly_cents": 0})
    assert store.q1("SELECT goal_id FROM projects WHERE id=?", (p["id"],))["goal_id"] is None
    with pytest.raises(CompanyError) as e:
        store.save_project({"id": p["id"], "budget_monthly_cents": -5})
    assert e.value.code == "invalid"
    store.delete_goal(g["id"])
    assert store.q1("SELECT parent_id FROM goals WHERE id=?", (sub["id"],))["parent_id"] is None


def test_agent_model_provider_and_budget_fields(store):
    dimas, _hana, _raka = org(store)
    a = store.save_agent({"id": dimas["id"], "model": "gpt-x", "provider": "custom:lab",
                          "budget_monthly_cents": 250, "budget_monthly_tokens": 10000, "heartbeat_s": 600})
    assert (a["model"], a["provider"], a["budget_monthly_cents"], a["budget_monthly_tokens"], a["heartbeat_s"]) == \
        ("gpt-x", "custom:lab", 250, 10000, 600)
    with pytest.raises(CompanyError) as e:
        store.save_agent({"id": dimas["id"], "budget_monthly_tokens": -1})
    assert e.value.code == "invalid"
    store.save_agent({"id": dimas["id"], "model": "", "provider": ""})
    assert store.agent(dimas["id"])["model"] == ""


def test_old_company_db_gets_provider_column(home):
    import sqlite3
    path = home / "company.db"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, title TEXT NOT NULL "
               "DEFAULT '', role TEXT NOT NULL DEFAULT 'pegawai', reports_to INTEGER, job_description TEXT NOT NULL "
               "DEFAULT '', model TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'idle', pause_reason TEXT, "
               "heartbeat_s INTEGER NOT NULL DEFAULT 0, budget_monthly_cents INTEGER NOT NULL DEFAULT 0, "
               "budget_monthly_tokens INTEGER NOT NULL DEFAULT 0, session_id TEXT, last_heartbeat_at REAL, "
               "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    db.commit()
    db.close()
    s = CompanyStore(clock=Clock())
    try:
        s.setup("Studio")
        a = s.save_agent({"name": "Dimas", "provider": "openai", "skip_approval": True})
        assert a["provider"] == "openai"
    finally:
        s.close()


def test_blocker_add_remove_and_cycle(store):
    dimas, _h, _r = org(store)
    a = store.create_ticket({"title": "A", "assignee_id": dimas["id"]})
    b = store.create_ticket({"title": "B"})
    store.add_blocker(a["id"], b["id"])
    assert [x["key"] for x in store.ticket_detail(a["id"])["blockers"]] == [b["key"]]
    with pytest.raises(CompanyError, match="melingkar"):
        store.add_blocker(b["id"], a["id"])
    with pytest.raises(CompanyError):
        store.add_blocker(a["id"], a["id"])
    store.remove_blocker(a["id"], b["id"])
    assert store.ticket_detail(a["id"])["blockers"] == []


def test_routine_edit_disable_and_bad_schedule(store):
    dimas, _h, _r = org(store)
    r = store.save_routine({"name": "Ringkasan", "schedule": "every 1d", "agent_id": dimas["id"]})
    store.save_routine({"id": r["id"], "enabled": False, "agent_id": None, "schedule": "every 7d"})
    row = store.q1("SELECT * FROM routines WHERE id=?", (r["id"],))
    assert row["enabled"] == 0 and row["agent_id"] is None and row["schedule"] == "every 7d"
    assert store.due_routines() == []
    with pytest.raises(CompanyError, match="Jadwal"):
        store.save_routine({"id": r["id"], "schedule": "kapan-kapan"})
    store.delete_routine(r["id"])
    assert store.q1("SELECT id FROM routines WHERE id=?", (r["id"],)) is None


def test_old_idle_company_gets_heartbeat_once_and_user_choice_sticks(home):
    import sqlite3
    s = CompanyStore(clock=Clock())
    s.setup("Lama")
    s.x("UPDATE company SET autorun=0")
    s.close()
    # simulate a company.db from before the heartbeat-on default (no autorun_user_set column)
    db = sqlite3.connect(str(home / "company.db"))
    db.execute("ALTER TABLE company DROP COLUMN autorun_user_set")
    db.commit()
    db.close()
    s = CompanyStore(clock=Clock())
    assert s.company()["autorun"] is True
    assert s.activity(5)[0]["action"] == "company.heartbeat_on"
    s.update_company({"autorun": False})           # the user pauses it: that sticks
    assert s.company()["autorun_user_set"] is True
    s.close()
    s = CompanyStore(clock=Clock())
    assert s.company()["autorun"] is False
    s.close()


def test_ceo_and_goal_planning_ticket(store):
    dimas, hana, raka = org(store)
    assert store.ceo()["id"] == dimas["id"]           # top of the chart with a team
    store.save_agent({"id": hana["id"], "role": "ceo"})
    assert store.ceo()["id"] == hana["id"]            # explicit role wins
    store.save_agent({"id": hana["id"], "role": "cto"})
    g = store.save_goal({"title": "Capai 1000 pengguna"})
    made = store.ensure_goal_planning()
    assert len(made) == 1 and made[0]["kind"] == "strategy" and made[0]["assignee_id"] == dimas["id"]
    assert made[0]["goal_id"] == g["id"] and made[0]["status"] == "todo"
    assert store.ensure_goal_planning() == []          # once per goal
    g2 = store.save_goal({"title": "Selesai"})
    store.save_goal({"id": g2["id"], "status": "done"})
    assert store.ensure_goal_planning() == []          # only active goals


def test_ticket_timeline_merges_comments_and_audit(store):
    dimas, hana, raka = org(store)
    t = store.create_ticket({"title": "Bangun", "assignee_id": raka["id"]})
    store.comment(t["id"], "mulai ya")
    store.checkout(t["id"], raka["id"])
    store.comment(t["id"], "beres", actor="agent", actor_id=raka["id"])
    tl = store.ticket_detail(t["id"])["timeline"]
    assert [x["type"] for x in tl][:2] == ["event", "comment"]
    assert [x["body"] for x in tl if x["type"] == "comment"] == ["mulai ya", "beres"]
    assert tl[-1]["actor_name"] == "Raka"
    assert not any(x.get("action") == "ticket.commented" for x in tl)   # no duplicate of the comment


def test_budget_hard_stop_files_one_board_request(store):
    dimas, hana, raka = org(store)
    store.save_agent({"id": raka["id"], "budget_monthly_tokens": 50})
    store.record_cost(agent_id=raka["id"], prompt_tokens=60, completion_tokens=0)
    store.check_budgets(raka["id"])
    store.check_budgets(raka["id"])
    aps = [a for a in store.list_approvals() if a["kind"] == "budget"]
    assert len(aps) == 1 and aps[0]["agent_id"] == raka["id"]
    store.decide(aps[0]["id"], "approved")
    a = store.agent(raka["id"])
    assert a["budget_monthly_tokens"] == 100 and a["status"] == "idle"
