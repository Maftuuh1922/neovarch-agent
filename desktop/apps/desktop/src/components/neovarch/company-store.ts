import { atom, onMount } from 'nanostores'

import { onGatewayEvent } from '@/contrib/events'
import { $gateway } from '@/store/gateway'

/** Perusahaan (company) data from the core's `company.*` RPCs. See docs/company-flow-design.md. */

export type TicketStatus = 'backlog' | 'blocked' | 'cancelled' | 'done' | 'in_progress' | 'review' | 'todo'
export type CompanyAgentStatus = 'error' | 'idle' | 'paused' | 'pending_approval' | 'running' | 'terminated'

export interface CompanyInfo {
  autorun: boolean
  budget_monthly_cents: number
  budget_monthly_tokens: number
  max_parallel: number
  mission: string
  name: string
  price_in_per_mtok: number
  price_out_per_mtok: number
  require_hire_approval: boolean
  require_review: boolean
  ticket_prefix: string
  warn_pct: number
}

export interface BudgetState {
  cents: number
  level: 'exceeded' | 'ok' | 'warning'
  pct: null | number
  tokens: number
}

export interface CompanyAgent {
  budget: BudgetState
  budget_monthly_cents: number
  budget_monthly_tokens: number
  current_ticket: null | {
    id: number
    key: string
    status: TicketStatus
    title: string
  }
  heartbeat_s: number
  id: number
  job_description: string
  model: string
  name: string
  pause_reason: null | string
  pending_approvals: number
  /** Persona / working style the main agent set for this employee. */
  persona?: string
  /** Provider of the agent's own model pick ('' = the PC default). */
  provider?: string
  /** Skill names this employee knows. */
  skills?: string[]
  /** Built-in tools this employee may use (empty = all). */
  tools?: string[]
  /** Organisasi/agency this employee sits in. */
  unit_id?: null | number
  unit_name?: null | string
  reports_to: null | number
  reports_to_name: null | string
  role: string
  session_id: null | string
  status: CompanyAgentStatus
  ticket_counts: Partial<Record<TicketStatus, number>>
  title: string
}

/** Organisasi → Agency → Orang: units nest without limit. */
export interface CompanyUnit {
  description?: string
  id: number
  kind: 'agency' | 'organisasi'
  name: string
  parent_id: null | number
}

export interface CompanyGoal {
  description: string
  id: number
  parent_id: null | number
  status: string
  title: string
}

export interface CompanyProject {
  budget_monthly_cents: number
  description: string
  goal_id: null | number
  id: number
  name: string
  status?: string
}

export interface CompanyRoutine {
  agent_id: null | number
  description?: string
  enabled: boolean | number
  id: number
  last_run_at?: null | number
  name: string
  next_run_at: null | number
  project_id?: null | number
  schedule: string
  title?: string
}

export interface CompanySnapshot {
  active_agents?: number[]
  agents: CompanyAgent[]
  budget: BudgetState
  company: CompanyInfo
  exists: true
  goals: CompanyGoal[]
  pending_approvals: number
  projects: CompanyProject[]
  routines: CompanyRoutine[]
  ticket_counts: Record<TicketStatus, number>
  units?: CompanyUnit[]
}

export interface CompanyTicket {
  assignee_id: null | number
  assignee_name: null | string
  blocked_by: number
  description: string
  id: number
  key: string
  locked: boolean
  parent_id: null | number
  priority: number
  project_id: null | number
  status: TicketStatus
  status_label: string
  title: string
  updated_at: number
}

export interface TicketComment {
  author_name: null | string
  author_type: 'agent' | 'system' | 'user'
  body: string
  created_at: number
  id: number
}

export interface TicketDetail extends CompanyTicket {
  ancestry: {
    id: number
    key?: string
    title: string
    type: 'goal' | 'mission' | 'project' | 'ticket'
  }[]
  blockers: { id: number; key: string; status: TicketStatus; title: string }[]
  children: { id: number; key: string; status: TicketStatus; title: string }[]
  comments: TicketComment[]
  work_products: { id: number; kind: string; ref: string; title: string }[]
}

export interface CompanyApproval {
  agent_name: null | string
  created_at: number
  id: number
  kind: 'budget' | 'hire' | 'plan' | 'review'
  note: string
  payload: Record<string, unknown>
  status: 'approved' | 'cancelled' | 'pending' | 'rejected'
  ticket_key: null | string
  title: string
}

export interface CompanyActivity {
  action: string
  actor_name: string
  actor_type: string
  id: number
  summary: string
  ts: number
}

export interface CostRow {
  budget_monthly_cents: number
  cents: number
  id: number
  name: string
  pct: null | number
  tokens: number
}

export interface CompanyCosts {
  budget_monthly_cents: number
  budget_monthly_tokens: number
  by_agent: CostRow[]
  by_project: CostRow[]
  month: string
  price_in_per_mtok: number
  price_out_per_mtok: number
  total: BudgetState
  warn_pct: number
}

export const TICKET_COLUMNS: { label: string; status: TicketStatus }[] = [
  { label: 'Backlog', status: 'backlog' },
  { label: 'Akan dikerjakan', status: 'todo' },
  { label: 'Dikerjakan', status: 'in_progress' },
  { label: 'Ditinjau', status: 'review' },
  { label: 'Terhambat', status: 'blocked' },
  { label: 'Selesai', status: 'done' }
]

export const TICKET_LABEL: Record<TicketStatus, string> = {
  backlog: 'Backlog',
  blocked: 'Terhambat',
  cancelled: 'Dibatalkan',
  done: 'Selesai',
  in_progress: 'Dikerjakan',
  review: 'Ditinjau',
  todo: 'Akan dikerjakan'
}

/** Mirrors core/neovarch/company.py TRANSITIONS (the core re-checks every move). */
export const TICKET_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  backlog: ['todo', 'cancelled'],
  blocked: ['todo', 'in_progress', 'cancelled'],
  cancelled: ['todo'],
  done: ['todo'],
  in_progress: ['review', 'blocked', 'done', 'todo', 'cancelled'],
  review: ['in_progress', 'done', 'cancelled'],
  todo: ['in_progress', 'blocked', 'backlog', 'cancelled']
}

export const AGENT_STATUS_LABEL: Record<CompanyAgentStatus, string> = {
  error: 'Galat',
  idle: 'Siaga',
  paused: 'Dijeda',
  pending_approval: 'Menunggu persetujuan',
  running: 'Bekerja',
  terminated: 'Diberhentikan'
}

export const GOAL_STATUS_LABEL: Record<string, string> = {
  active: 'Aktif',
  done: 'Tercapai',
  paused: 'Ditunda'
}

export const APPROVAL_KIND_LABEL: Record<CompanyApproval['kind'], string> = {
  budget: 'Anggaran',
  hire: 'Rekrut',
  plan: 'Rencana',
  review: 'Tinjau hasil'
}

/** null = not loaded yet. `{exists: false}` = no company created on this PC. */
export const $company = atom<CompanySnapshot | null | { exists: false }>(null)
export const $companyError = atom<null | string>(null)
/** Bumped on every `company.changed` push so views that fetch their own data reload. */
export const $companyRev = atom(0)

export async function companyCall<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const gateway = $gateway.get()

  if (!gateway) {
    throw new Error('Belum terhubung ke core')
  }

  return gateway.request<T>(`company.${method}`, params)
}

export async function refreshCompany(): Promise<void> {
  if (!$gateway.get()) {
    return
  }

  try {
    $company.set(await companyCall<CompanySnapshot | { exists: false }>('snapshot'))
    $companyError.set(null)
  } catch (error) {
    $companyError.set(error instanceof Error ? error.message : String(error))
  }
}

let pending: null | ReturnType<typeof setTimeout> = null

function scheduleRefresh(): void {
  if (pending) {
    return
  }

  pending = setTimeout(() => {
    pending = null
    $companyRev.set($companyRev.get() + 1)
    void refreshCompany()
  }, 150)
}

onMount($company, () => {
  void refreshCompany()
  const offChanged = onGatewayEvent('company.changed', () => scheduleRefresh())
  const offReady = onGatewayEvent('gateway.ready', () => void refreshCompany())
  const offGateway = $gateway.listen(() => void refreshCompany())

  return () => {
    offChanged()
    offReady()
    offGateway()
  }
})

export function hasCompany(value: ReturnType<typeof $company.get>): value is CompanySnapshot {
  return Boolean(value && value.exists)
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(cents > 0 && cents < 1 ? 4 : 2)}`
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)} jt token`
  }

  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)} rb token`
  }

  return `${tokens} token`
}

/** Agents arranged as a tree (roots = report to the board). Cycles are impossible in the core. */
/** Units in tree order (parents before children), with their depth. */
export function unitTree(units: CompanyUnit[] | undefined): { depth: number; unit: CompanyUnit }[] {
  const list = Array.isArray(units) ? units : []
  const ids = new Set(list.map(u => u.id))
  const byParent = new Map<null | number, CompanyUnit[]>()

  for (const u of list) {
    const key = u.parent_id !== null && ids.has(u.parent_id) ? u.parent_id : null
    byParent.set(key, [...(byParent.get(key) ?? []), u])
  }

  const out: { depth: number; unit: CompanyUnit }[] = []
  const seen = new Set<number>()

  const walk = (parent: null | number, depth: number) => {
    for (const u of byParent.get(parent) ?? []) {
      if (seen.has(u.id)) {
        continue
      }

      seen.add(u.id)
      out.push({ depth, unit: u })
      walk(u.id, depth + 1)
    }
  }

  walk(null, 0)

  return out
}

export function orgTree(agents: CompanyAgent[]): { agent: CompanyAgent; depth: number }[] {
  const byManager = new Map<null | number, CompanyAgent[]>()
  const ids = new Set(agents.map(a => a.id))

  for (const a of agents) {
    const key = a.reports_to !== null && ids.has(a.reports_to) ? a.reports_to : null
    byManager.set(key, [...(byManager.get(key) ?? []), a])
  }

  const out: { agent: CompanyAgent; depth: number }[] = []
  const seen = new Set<number>()

  const walk = (manager: null | number, depth: number) => {
    for (const a of byManager.get(manager) ?? []) {
      if (seen.has(a.id)) {
        continue
      }

      seen.add(a.id)
      out.push({ agent: a, depth })
      walk(a.id, depth + 1)
    }
  }

  walk(null, 0)

  return out
}
