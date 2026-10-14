# Neovarch Kantor — "Perusahaan" worker flow (design)

Branch `feature-office-company` (from `fix-core-parity`). Concepts adapted from
Paperclip (MIT, github.com/paperclipai/paperclip: doc/SPEC-implementation.md §7–§11) —
no code copied; rewritten for Neovarch's Python core, Electron/React desktop and Flutter remote.

## 1. Principles
- **Never surprising, never idle.** The company exists only after the user creates it
  (or taps "Coba contoh"). No agent spends tokens until the company exists; from then on its
  heartbeat ("autorun") is on by default so employees pick up assigned tickets by themselves, and
  the user can pause it ("Jeda heartbeat") at any time. Budgets hard-stop an agent mid-run.
- **Single source of truth = core.** Desktop and phone are views/controllers over the same RPCs.
- **Isolated files.** Everything lives in `~/.neovarch/company.db` (SQLite, WAL). Never `~/.hermes`.
- **Minimal hooks into existing code** (server.py / tools.py / agent.py / office.py get a few lines each),
  so rebases on the fast-moving `fix-core-parity` stay cheap.

## 2. Data model (`core/neovarch/company.py`, SQLite)
| table | key fields |
|---|---|
| `company` (1 row) | name, mission (top goal text), autorun, max_parallel (2), require_hire_approval, require_review, budget_monthly_cents, budget_monthly_tokens, warn_pct (80), price_in/out_per_mtok (cents), ticket_prefix (`NV`), ticket_counter |
| `goals` | id, parent_id (tree under the company mission), title, description, status |
| `projects` | id, goal_id, name, description, status, budget_monthly_cents |
| `agents` | id, name, title, role, reports_to (strict tree, no cycles), job_description, model, status, pause_reason, heartbeat_s (0 = only on events), budget_monthly_cents/tokens, session_id (persona chat), last_heartbeat_at |
| `tickets` | id, key `NV-12`, project_id, goal_id, parent_id, title, description, status, priority (0–3), assignee_id, **checkout_agent_id, checkout_run_id, checkout_at**, created_by, started_at, completed_at |
| `ticket_blockers` | ticket_id, blocker_id |
| `comments` | ticket_id, author_type (user/agent/system), author_id, body |
| `work_products` | ticket_id, kind (file/link/text), title, ref |
| `approvals` | kind (hire/plan/review/budget), status, ticket_id, agent_id, payload, note, decided_at |
| `runs` | heartbeat runs: agent_id, ticket_id, reason (assignment/comment/schedule/manual/routine/approval), status, session_id, error, tokens, cost_cents |
| `cost_events` | agent_id, project_id, ticket_id, run_id, prompt/completion tokens, cost_cents, month `YYYY-MM` |
| `wakeups` | queued wake requests (agent_id, reason, ticket_id) — coalesced per agent |
| `routines` | name, schedule (same parser as Jadwal/cron.py), agent_id, project_id, title, description, enabled, next_run_at |
| `activity` | ts, actor_type/actor_id, action (`ticket.moved`…), entity, summary (Indonesian), data |

Goal ancestry for a ticket = ticket → parent tickets → project → project goal → parent goals → company mission.
It is rendered into every heartbeat prompt and the persona, so each agent knows the "why".

## 3. State machines
**Ticket**: `backlog→todo|cancelled`; `todo→in_progress(checkout only)|blocked|backlog|cancelled`;
`in_progress→review|blocked|done|todo(release)|cancelled`; `review→in_progress|done|cancelled`;
`blocked→todo|in_progress|cancelled`; `done/cancelled` terminal except user "Buka lagi" → `todo`.
`done` by an agent when `require_review` → status `review` + a `review` approval; approve → `done`, reject → `in_progress` + comment.
A ticket with unresolved blockers cannot be checked out.

**Checkout lock** (atomic, one SQL statement under `BEGIN IMMEDIATE`):
`UPDATE tickets SET status='in_progress', assignee_id=:a, checkout_agent_id=:a, checkout_run_id=:r … WHERE id=:t
AND status IN ('todo','backlog','blocked','review','in_progress') AND (assignee_id IS NULL OR assignee_id=:a)
AND (checkout_run_id IS NULL OR checkout_agent_id=:a)` → 0 rows ⇒ `409 conflict` with current owner.
The lock is per run: released when the run ends (status kept), or by `ticket.release` / user force-release.

**Agent**: `pending_approval→idle` (hire approved) · `idle↔running` · `running→error→idle` · `*→paused→idle`
(resume) · `*→terminated` (irreversible). Stop = interrupt the live run + release its lock + pause.

**Approval**: `pending→approved|rejected|cancelled`.

## 4. Heartbeats & delegation
`CompanyScheduler` (asyncio, tick `NEOVARCH_COMPANY_TICK`, default 10 s) — runs only when `autorun` is on,
except manual wakes which always run.
- Wake sources: ticket assigned/moved to todo (assignment), user comment on an agent's ticket (comment),
  approval decided (approval), `heartbeat_s` elapsed (schedule), routine due (routine → creates a ticket), "Bangunkan" (manual).
- One run per agent at a time; at most `max_parallel` runs overall. Skips paused/terminated/over-budget agents.
- Run = pick ticket (own `in_progress` first, then highest-priority unblocked `todo`) → checkout → submit a turn in the
  agent's own session (`source: "company"`) with the heartbeat prompt (persona + ancestry + ticket + last comments) →
  record usage as a cost event → release lock. Final text becomes a ticket comment if the agent didn't comment itself.
- Agent tools (only inside company sessions): `company_my_work`, `company_ticket_update` (status + comment),
  `company_comment`, `company_delegate` (create sub-ticket for a **report** in its subtree → wakes them),
  `company_escalate` (blocked + reassign to manager), `company_request_approval` (plan), `company_work_product`.

## 5. Governance, budgets, activity
- Approvals: hire (when `require_hire_approval`), plan (agent request), review (task completion), budget override.
- Budgets: monthly UTC window; per agent, per project, company; cents (from token prices) and/or tokens.
  ≥ `warn_pct` → activity `budget.warning` (once per month/scope); ≥ 100 % → agent auto-paused (`pause_reason=budget`),
  activity `budget.hard_stop`, no further runs until resumed / budget raised.
- Activity log: every mutation writes one row (actor, action, entity, Indonesian summary).

## 6. API (all also REST: `GET /api/company`, `POST /api/company/{method}`; JSON-RPC over `/api/ws`)
`company.snapshot` · `company.setup` · `company.update` · `company.seed_demo` · `company.goal.save|delete` ·
`company.project.save|delete` · `company.agent.save|pause|resume|stop|terminate|wake|runs` ·
`company.ticket.list|get|save|move|assign|checkout|release|comment|block|unblock|work_product` ·
`company.approval.list|decide` · `company.costs` · `company.activity` · `company.routine.save|delete|trigger`.
Errors: JSON-RPC `-32602` invalid, `-32004` not found, `-32009` conflict (checkout/transition) — REST 400/404/409.
Event: `company.changed` `{entity, id, action}` (coalesced) and `office.update` is re-pushed.

## 7. Mapping onto existing Kantor
- `Office.snapshot()` adds company agents as desks `kind:"company"`, id `company:<id>`, name/title as role,
  `status`: running→`working`, has pending approval/ticket in review→`waiting-approval`, else `idle`;
  extra `company: {agent_id, title, ticket_key, ticket_title, ticket_status, paused, reports_to}`. The 3D view keeps
  working unchanged and shows the ticket status badge from `company.ticket_status`.
- `office_status` tool summary gets a "Perusahaan" section (goal, agents, tickets by status, pending approvals, spend).
- Persona: a session with `company_agent_id` gets a persona block (name, title, manager, job, current ticket, ancestry,
  last activity) and the company tools; "lagi apa kamu" is answered in character from real data.

## 8. UI
- **Desktop** Kantor tabs: `Ruang` (existing 3D/list) · `Organisasi` · `Tiket` (kanban) · `Tujuan` · `Rutinitas` ·
  `Persetujuan` · `Biaya` · `Aktivitas`. Hidden behind an empty state ("Buat perusahaan") until a company exists;
  The heartbeat (autorun) is on by default once a company exists (since 1.4.8; an older idle company is switched on once on upgrade). "Jeda heartbeat" pauses it; a budget hard stop pauses one agent and files a budget approval.
  - Organisasi: each agent has "Ubah" → profile, manager (own reports excluded), heartbeat, monthly budget
    (cents/tokens), model (from `model.options`, empty = PC default; stored as `model`+`provider` on the agent and
    applied to its persona session at once), "Berhentikan" (terminate, two-click confirm).
  - Tiket detail: blockers list with "Lepas" and "Tambah hambatan" (open tickets only; cycles rejected by core).
  - Tujuan: mission editor, goal tree (create/edit/status/delete), projects with goal + monthly budget.
  - Rutinitas: list/create/edit/enable/delete, "Jalankan sekarang" (creates the ticket now).
  - The Kantor desk model popover on a company desk (`PUT /api/agents/company:<id>/model`) changes that agent only.
- **Android remote**: "Perusahaan" screen with tabs Organisasi / Tiket / Persetujuan / Biaya; approve/reject, pause/resume,
  wake, assign, move — all through the same RPCs over the paired gateway.


## 10. Paperclip gap-closing pass (feat/kantor-paperclip, 2026-10-14)
- Heartbeat on by default (`company.heartbeat {on, stop_running?}` is the pause switch).
- CEO: each active goal without work gets a `kind=strategy` ticket for the CEO (role `ceo`, else the
  top of the chart with a team). Tool `company_propose_strategy` files a `strategy` approval; approve
  → tickets created under the strategy ticket and assignees woken; revise → back to todo + CEO woken;
  reject → backlog. `require_strategy_approval` (default on) can skip the board.
- Agents may ask to hire (`company_hire`); that always needs a hire approval.
- Costs are captured per model call (`usage.update`); a hard stop interrupts the running heartbeat and
  files one `budget` approval (approve adds one more month of the agent's budget and resumes).
- Live feed: every activity row is pushed as `company.activity`; `company.activity {after, agent_id}`.
- Ticket thread: `ticket.get` returns `timeline` (comments + audit events + heartbeat runs).
