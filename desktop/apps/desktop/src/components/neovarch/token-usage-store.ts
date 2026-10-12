import { atom, onMount } from 'nanostores'

import { hermesApi } from '@/api/client'
import { onGatewayEvent } from '@/contrib/events'

/** One bucket of the core's `GET /api/usage` (core ≥ 1.4.7, `usage_stats.py`). */
export interface TokenBucket {
  cached: number
  calls: number
  input: number
  output: number
  total: number
}

export interface TokenModelRow extends TokenBucket {
  model: string
  provider?: string
}

/** What `GET /api/usage[?session=]` answers. Same numbers the phone's
 *  Profil › Pemakaian token panel and the Pamerkan tiles read. */
export interface TokenUsageSummary {
  date: string
  lifetime: TokenBucket
  models: TokenModelRow[]
  session?: TokenBucket
  today: TokenBucket
  today_models?: TokenModelRow[]
  trend?: { date: string; total: number }[]
}

export const $tokenUsage = atom<TokenUsageSummary | null>(null)
export const $tokenUsageSession = atom<null | string>(null)

const EMPTY: TokenBucket = { cached: 0, calls: 0, input: 0, output: 0, total: 0 }

function bucket(value: unknown): TokenBucket {
  if (!value || typeof value !== 'object') {
    return EMPTY
  }

  const v = value as Record<string, unknown>
  const n = (k: string) => (typeof v[k] === 'number' && Number.isFinite(v[k]) ? Math.max(0, v[k] as number) : 0)
  const input = n('input')
  const output = n('output')

  return { cached: n('cached'), calls: n('calls'), input, output, total: n('total') || input + output }
}

/** Defensive parse: an older core (no route) or a junk answer gives null. */
export function parseTokenUsage(raw: unknown): TokenUsageSummary | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const r = raw as Record<string, unknown>

  if (!r.today || !r.lifetime) {
    return null
  }

  const rows = (list: unknown): TokenModelRow[] =>
    Array.isArray(list)
      ? list
          .filter((m): m is Record<string, unknown> => !!m && typeof m === 'object')
          .map(m => ({
            ...bucket(m),
            model: String(m.model ?? '?'),
            ...(typeof m.provider === 'string' ? { provider: m.provider } : {})
          }))
      : []

  return {
    date: String(r.date ?? ''),
    lifetime: bucket(r.lifetime),
    models: rows(r.models),
    ...(r.session ? { session: bucket(r.session) } : {}),
    today: bucket(r.today),
    today_models: rows(r.today_models),
    trend: Array.isArray(r.trend) ? (r.trend as { date: string; total: number }[]) : []
  }
}

let inflight: Promise<void> | null = null
let lastFetch = 0
let pending: number | undefined

export async function refreshTokenUsage(sessionId?: null | string): Promise<void> {
  if (sessionId !== undefined) {
    $tokenUsageSession.set(sessionId || null)
  }

  if (inflight) {
    return inflight
  }

  const sid = $tokenUsageSession.get()
  const path = sid ? `/api/usage?session=${encodeURIComponent(sid)}` : '/api/usage'
  inflight = (async () => {
    try {
      const next = parseTokenUsage(await hermesApi<unknown>({ path }))

      if (next) {
        $tokenUsage.set(next)
      }
    } catch {
      // core still starting / older core without /api/usage: keep what we have
    } finally {
      lastFetch = Date.now()
      inflight = null
    }
  })()

  return inflight
}

/** Live ticks arrive after every model call; refetch at most every 3 s. */
function scheduleRefresh(): void {
  if (pending !== undefined) {
    return
  }

  const wait = Math.max(0, 3000 - (Date.now() - lastFetch))
  pending = window.setTimeout(() => {
    pending = undefined
    void refreshTokenUsage()
  }, wait)
}

onMount($tokenUsage, () => {
  void refreshTokenUsage()
  const offs = ['session.usage', 'message.complete', 'gateway.ready'].map(type => onGatewayEvent(type, scheduleRefresh))

  return () => {
    offs.forEach(off => off())

    if (pending !== undefined) {
      window.clearTimeout(pending)
      pending = undefined
    }
  }
})

/** 950 → "950", 12 400 → "12,4rb", 3 400 000 → "3,4jt", 2 100 000 000 → "2,1M" (same as the phone). */
export function compactTokens(n: number): string {
  const f = (v: number) => v.toFixed(1).replace('.', ',').replace(/,0$/, '')

  if (n >= 1_000_000_000) {
    return `${f(n / 1_000_000_000)}M`
  }

  if (n >= 1_000_000) {
    return `${f(n / 1_000_000)}jt`
  }

  if (n >= 10_000) {
    return `${Math.round(n / 1000)}rb`
  }

  if (n >= 1000) {
    return `${f(n / 1000)}rb`
  }

  return `${Math.round(n)}`
}
