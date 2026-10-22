import { atom, onMount } from 'nanostores'

import { onGatewayEvent } from '@/contrib/events'
import { $gateway } from '@/store/gateway'

import type { CrewMemberStatus } from './crew-pixel'

/** The Crew page (rail "Crew"). The old Kantor page stays at /office, reachable from Lanjutan. */
export const CREW_ROUTE = '/crew'

export type CrewToolGroup = 'files' | 'shell' | 'web' | 'write'
export type CrewProcess = 'hierarchical' | 'sequential'
export type CrewStatus = 'cancelled' | 'done' | 'failed' | 'proposed' | 'running'
export type CrewTemplateId = 'coding' | 'konten' | 'riset' | 'riset_laporan'

export interface CrewMember {
  activity?: string
  approval?: { command: string; request_id: string; session_id: string } | null
  avatar: number
  goal: string
  id: string
  model: string
  name: string
  role: string
  session_id?: string
  status: CrewMemberStatus
  tools: CrewToolGroup[]
}

export interface CrewTask {
  description: string
  expected_output: string
  finished_at?: number
  id: string
  member_id: string
  output: string
  started_at?: number
  status: 'cancelled' | 'done' | 'running' | 'skipped' | 'todo'
  title: string
}

export interface Crew {
  allow_side_effects: boolean
  created_at: number
  designed_by: 'agent' | 'template'
  error: string
  final_output: string
  goal: string
  id: string
  log: Array<{ member: null | string; text: string; ts: number }>
  manager: null | string
  members: CrewMember[]
  note?: string
  process: CrewProcess
  side_effects: CrewToolGroup[]
  status: CrewStatus
  tasks: CrewTask[]
  template: CrewTemplateId
  title: string
  updated_at: number
}

export interface CrewSummary {
  created_at: number
  done: number
  goal: string
  id: string
  members: number
  process: CrewProcess
  status: CrewStatus
  tasks: number
  template: CrewTemplateId
  title: string
}

export const CREW_TEMPLATES: CrewTemplateId[] = ['riset', 'konten', 'coding', 'riset_laporan']
export const CREW_TOOL_GROUPS: CrewToolGroup[] = ['web', 'files', 'write', 'shell']
export const CREW_SIDE_EFFECT_TOOLS: CrewToolGroup[] = ['write', 'shell']
export const CREW_INTRO_KEY = 'nv.crew.intro.seen'

export const $crews = atom<CrewSummary[]>([])
/** The crew shown on the Crew tab (full record), or null for the goal form. */
export const $crew = atom<Crew | null>(null)
export const $crewError = atom<null | string>(null)
export const $crewBusy = atom(false)

function gw() {
  const gateway = $gateway.get()

  if (!gateway) {
    throw new Error('Core belum tersambung')
  }

  return gateway
}

async function call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return gw().request<T>(method, params)
}

function remember(c: Crew): Crew {
  $crew.set(c)
  const rest = $crews.get().filter(x => x.id !== c.id)
  $crews.set([summarize(c), ...rest].sort((a, b) => b.created_at - a.created_at))

  return c
}

export function summarize(c: Crew): CrewSummary {
  return {
    created_at: c.created_at,
    done: c.tasks.filter(t => t.status === 'done').length,
    goal: c.goal,
    id: c.id,
    members: c.members.length,
    process: c.process,
    status: c.status,
    tasks: c.tasks.length,
    template: c.template,
    title: c.title
  }
}

export async function refreshCrews(): Promise<void> {
  try {
    const res = await call<{ crews: CrewSummary[] }>('crew.list')
    $crews.set(Array.isArray(res?.crews) ? res.crews : [])
    $crewError.set(null)
    const current = $crew.get()

    if (!current) {
      // reopen a crew that is still working (e.g. after a reload)
      const running = $crews.get().find(c => c.status === 'running')

      if (running) {
        await openCrew(running.id)
      }
    }
  } catch (error) {
    $crewError.set(error instanceof Error ? error.message : String(error))
  }
}

async function guarded<T>(fn: () => Promise<T>): Promise<T | null> {
  $crewBusy.set(true)
  $crewError.set(null)

  try {
    return await fn()
  } catch (error) {
    $crewError.set(error instanceof Error ? error.message : String(error))

    return null
  } finally {
    $crewBusy.set(false)
  }
}

export const openCrew = (id: string) => guarded(async () => remember(await call<Crew>('crew.get', { id })))

export const proposeCrew = (goal: string, template?: CrewTemplateId) =>
  guarded(async () => remember(await call<Crew>('crew.propose', template ? { goal, template } : { goal })))

export const approveCrew = (id: string, allowSideEffects: boolean) =>
  guarded(async () => remember(await call<Crew>('crew.approve', { allow_side_effects: allowSideEffects, id })))

export const updateCrew = (id: string, patch: Partial<Pick<Crew, 'manager' | 'members' | 'process' | 'tasks' | 'title'>>) =>
  guarded(async () => remember(await call<Crew>('crew.update', { id, patch })))

export const cancelCrew = (id: string) => guarded(async () => remember(await call<Crew>('crew.cancel', { id })))

export const deleteCrew = (id: string) =>
  guarded(async () => {
    await call('crew.delete', { id })
    $crews.set($crews.get().filter(c => c.id !== id))

    if ($crew.get()?.id === id) {
      $crew.set(null)
    }

    return true
  })

export function answerCrewApproval(m: CrewMember, choice: 'deny' | 'once') {
  if (!m.approval) {
    return Promise.resolve(null)
  }

  return guarded(() =>
    call('approval.respond', { choice, request_id: m.approval!.request_id, session_id: m.approval!.session_id })
  )
}

export function closeCrew() {
  $crew.set(null)
}

/** Apply a `crew.update` push: the open crew follows live, the list stays in sync. */
export function applyCrewPush(payload: unknown) {
  const p = payload as (Crew & { deleted?: boolean }) | undefined

  if (!p || typeof p !== 'object' || !p.id) {
    return
  }

  if (p.deleted) {
    $crews.set($crews.get().filter(c => c.id !== p.id))

    if ($crew.get()?.id === p.id) {
      $crew.set(null)
    }

    return
  }

  if (!Array.isArray(p.members) || !Array.isArray(p.tasks)) {
    return
  }

  const open = $crew.get()

  if (open?.id === p.id) {
    $crew.set(p)
  }

  const others = $crews.get().filter(c => c.id !== p.id)
  $crews.set([summarize(p), ...others].sort((a, b) => b.created_at - a.created_at))
}

onMount($crews, () => {
  void refreshCrews()
  const offUpdate = onGatewayEvent('crew.update', event => applyCrewPush(event.payload))
  const offReady = onGatewayEvent('gateway.ready', () => void refreshCrews())

  return () => {
    offUpdate()
    offReady()
  }
})

export function introSeen(): boolean {
  try {
    return window.localStorage.getItem(CREW_INTRO_KEY) === '1'
  } catch {
    return true
  }
}

export function markIntroSeen() {
  try {
    window.localStorage.setItem(CREW_INTRO_KEY, '1')
  } catch {
    // private mode: the intro simply shows again next time
  }
}

export function fmt(template: string, args: Record<string, number | string>): string {
  return template.replace(/\{(\w+)\}/g, (_, k: string) => String(args[k] ?? ''))
}
