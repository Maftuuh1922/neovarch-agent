// Pamerkan stats (radar / bar / donut / trend) from the core's `GET /api/pamerkan`
// (core/neovarch/pamerkan.py). Every number comes from this PC's own sessions and
// usage.json; when the core is older or unreachable the card simply has no charts.
import { atom } from 'nanostores'

import { hermesApi } from '@/api/client'

export const PAMERKAN_AXES = ['coding', 'riset', 'ppt', 'browser', 'otomasi', 'token'] as const
export type PamerkanAxis = (typeof PAMERKAN_AXES)[number]
export type PamerkanActivity = Exclude<PamerkanAxis, 'token'>
export const PAMERKAN_ACTIVITY: PamerkanActivity[] = ['coding', 'riset', 'ppt', 'browser', 'otomasi']
export type PamerkanSlice = 'lainnya' | PamerkanActivity

export interface PamerkanAxisValue {
  id: PamerkanAxis
  reference: number
  /** 0-100, log scale against `reference` (see pamerkan.py). */
  score: number
  value: number
}

export interface PamerkanDay {
  calls: number
  date: string
  tokens: number
  turns: number
}

export interface PamerkanWeek {
  calls: number
  start: string
  tokens: number
  turns: number
  week: string
}

export interface PamerkanStats {
  axes: PamerkanAxisValue[]
  bars: { id: PamerkanActivity; value: number }[]
  days: number
  donut: { id: PamerkanSlice; value: number }[]
  empty: boolean
  from: string
  to: string
  toolsTop: { axis: PamerkanSlice; name: string; value: number }[]
  totals: {
    activeDays: number
    automatedSessions: number
    sessions: number
    streak: number
    tokens: number
    toolCalls: number
    turns: number
  }
  trend: { daily: PamerkanDay[]; weekly: PamerkanWeek[] }
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, v) : 0)

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.filter(isObj) : [])

const SLICES = new Set<string>([...PAMERKAN_ACTIVITY, 'lainnya'])

/** Defensive parse of `/api/pamerkan`; anything that is not the expected shape → null. */
export function parsePamerkan(raw: unknown): null | PamerkanStats {
  if (!isObj(raw) || !Array.isArray(raw.axes)) {
    return null
  }

  const byId = new Map(list(raw.axes).map(a => [String(a.id), a]))

  const axes = PAMERKAN_AXES.map(id => {
    const a = byId.get(id) ?? {}

    return { id, reference: num(a.reference), score: Math.min(100, num(a.score)), value: num(a.value) }
  })

  const bars = PAMERKAN_ACTIVITY.map(id => ({ id, value: num(list(raw.bars).find(b => b.id === id)?.value) }))

  const donut = list(raw.donut)
    .filter(d => SLICES.has(String(d.id)) && num(d.value) > 0)
    .map(d => ({ id: String(d.id) as PamerkanSlice, value: num(d.value) }))

  const trend = isObj(raw.trend) ? raw.trend : {}
  const totals = isObj(raw.totals) ? raw.totals : {}

  return {
    axes,
    bars,
    days: num(raw.days) || 30,
    donut,
    empty: raw.empty === true || axes.every(a => a.value === 0),
    from: String(raw.from ?? ''),
    to: String(raw.to ?? ''),
    toolsTop: list(raw.tools_top).map(t => ({
      axis: (SLICES.has(String(t.axis)) ? String(t.axis) : 'lainnya') as PamerkanSlice,
      name: String(t.name ?? ''),
      value: num(t.value)
    })),
    totals: {
      activeDays: num(totals.active_days),
      automatedSessions: num(totals.automated_sessions),
      sessions: num(totals.sessions),
      streak: num(totals.streak),
      tokens: num(totals.tokens),
      toolCalls: num(totals.tool_calls),
      turns: num(totals.turns)
    },
    trend: {
      daily: list(trend.daily).map(d => ({ calls: num(d.calls), date: String(d.date ?? ''), tokens: num(d.tokens), turns: num(d.turns) })),
      weekly: list(trend.weekly).map(w => ({
        calls: num(w.calls),
        start: String(w.start ?? ''),
        tokens: num(w.tokens),
        turns: num(w.turns),
        week: String(w.week ?? '')
      }))
    }
  }
}

export const $pamerkan = atom<null | PamerkanStats>(null)
export const $pamerkanState = atom<'error' | 'idle' | 'loading' | 'ready'>('idle')

/** Fetch the last `days` days. Keeps the previous value when the core does not answer. */
export async function refreshPamerkan(days = 30): Promise<null | PamerkanStats> {
  $pamerkanState.set('loading')

  try {
    const next = parsePamerkan(await hermesApi<unknown>({ path: `/api/pamerkan?days=${encodeURIComponent(String(days))}` }))

    if (next) {
      $pamerkan.set(next)
      $pamerkanState.set('ready')

      return next
    }

    $pamerkanState.set('error')
  } catch {
    // older core without /api/pamerkan, or core still starting: the card works without charts
    $pamerkanState.set('error')
  }

  return $pamerkan.get()
}
