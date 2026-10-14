import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.fn()

vi.mock('@/api/client', () => ({ hermesApi: (req: { path: string }) => api(req) }))

const renderPng = vi.fn(async () => new Blob(['png'], { type: 'image/png' }))

vi.mock('./kartu-card', async importOriginal => ({
  ...(await importOriginal<typeof import('./kartu-card')>()),
  renderShareCardPng: (...args: unknown[]) => renderPng(...(args as []))
}))

import { en } from '@/i18n/en'
import {
  nvPamerkanAr,
  nvPamerkanDe,
  nvPamerkanEn,
  nvPamerkanEs,
  nvPamerkanFr,
  nvPamerkanId,
  nvPamerkanJa,
  nvPamerkanRu,
  nvPamerkanZh,
  nvPamerkanZhHant
} from '@/i18n/nv-pamerkan'

import { type DrawOp, layoutShareCard, NEOVARCH_LANDING_URL, planShareCard, SHARE_CARD_SIZE, SHARE_CARD_STYLES, type ShareCardData } from './kartu-card'
import { KartuCardDialog } from './kartu-card-dialog'
import { barsOps, donutOps, PAMERKAN_LABELS_ID, planBlocks, radarOps, radarPoint, trendOps } from './pamerkan-card'
import { DEFAULT_PAMERKAN_PREFS, loadPamerkanPrefs, PAMERKAN_PREFS_KEY, PAMERKAN_THEMES, sanitizePrefs, savePamerkanPrefs } from './pamerkan-prefs'
import { $pamerkan, $pamerkanState, parsePamerkan, type PamerkanStats, refreshPamerkan } from './pamerkan-store'

const RAW = {
  axes: [
    { id: 'coding', reference: 1500, score: 62, value: 312 },
    { id: 'riset', reference: 300, score: 48, value: 40 },
    { id: 'ppt', reference: 40, score: 30, value: 2 },
    { id: 'browser', reference: 200, score: 41, value: 18 },
    { id: 'otomasi', reference: 150, score: 35, value: 7 },
    { id: 'token', reference: 20000000, score: 77, value: 1234567 }
  ],
  bars: [
    { id: 'coding', value: 312 },
    { id: 'riset', value: 40 },
    { id: 'ppt', value: 2 },
    { id: 'browser', value: 18 },
    { id: 'otomasi', value: 7 }
  ],
  days: 30,
  donut: [
    { id: 'coding', value: 312 },
    { id: 'riset', value: 40 },
    { id: 'ppt', value: 2 },
    { id: 'browser', value: 18 },
    { id: 'otomasi', value: 7 },
    { id: 'lainnya', value: 11 }
  ],
  empty: false,
  from: '2026-09-15',
  to: '2026-10-14',
  tools_top: [{ axis: 'coding', name: 'edit_file', value: 120 }],
  totals: { active_days: 12, automated_sessions: 1, sessions: 9, streak: 3, tokens: 1234567, tool_calls: 390, turns: 55 },
  trend: {
    daily: Array.from({ length: 14 }, (_, i) => ({ calls: i % 3 ? i * 4 : 0, date: `2026-10-${String(i + 1).padStart(2, '0')}`, tokens: i * 1000, turns: i })),
    weekly: Array.from({ length: 8 }, (_, i) => ({ calls: i * 10, start: `2026-08-${10 + i}`, tokens: i * 5000, turns: i, week: `2026-W${33 + i}` }))
  },
  version: 1
}

const EMPTY_RAW = {
  ...RAW,
  axes: RAW.axes.map(a => ({ ...a, score: 0, value: 0 })),
  bars: RAW.bars.map(b => ({ ...b, value: 0 })),
  donut: [],
  empty: true,
  tools_top: [],
  totals: { active_days: 0, automated_sessions: 0, sessions: 0, streak: 0, tokens: 0, tool_calls: 0, turns: 0 },
  trend: { daily: RAW.trend.daily.map(d => ({ ...d, calls: 0, tokens: 0, turns: 0 })), weekly: RAW.trend.weekly.map(w => ({ ...w, calls: 0, tokens: 0, turns: 0 })) }
}

const stats = parsePamerkan(RAW) as PamerkanStats
const empty = parsePamerkan(EMPTY_RAW) as PamerkanStats

const card = (over: Partial<ShareCardData> = {}): ShareCardData => ({
  handle: 'Maftuuh1922',
  link: NEOVARCH_LANDING_URL,
  name: 'Maftuh',
  officeShot: 'data:image/jpeg;base64,AAAA',
  stats: { agentsActive: 1, agentsTotal: 2, messages: 200, model: 'claude-sonnet-4.5', tasksDone: 7 },
  ...over
})

const texts = (ops: DrawOp[]) => ops.flatMap(op => (op.kind === 'text' ? [op.text] : []))
const colors = { accent: '#EE1C1C', cell: '#1c1c21', ground: '#09090b', line: '#2a2a30', muted: '#a8a29e', panel: '#141417', text: '#f4f2ed' }
const bo = { colors, labels: PAMERKAN_LABELS_ID, locale: 'id', scale: 1 }

function inside(ops: DrawOp[], W: number, H: number) {
  for (const op of ops) {
    if (op.kind === 'rect' || op.kind === 'image') {
      expect(op.x).toBeGreaterThanOrEqual(-1)
      expect(op.y).toBeGreaterThanOrEqual(-1)
      expect(op.x + op.w).toBeLessThanOrEqual(W + 1)
      expect(op.y + op.h).toBeLessThanOrEqual(H + 1)
    }

    if (op.kind === 'path') {
      for (const [x, y] of op.points) {
        expect(x).toBeGreaterThanOrEqual(0)
        expect(x).toBeLessThanOrEqual(W)
        expect(y).toBeGreaterThanOrEqual(0)
        expect(y).toBeLessThanOrEqual(H)
      }
    }

    if (op.kind === 'arc') {
      expect(op.x - op.r).toBeGreaterThanOrEqual(0)
      expect(op.x + op.r).toBeLessThanOrEqual(W)
    }
  }
}

describe('Pamerkan data + prefs', () => {
  it('parses /api/pamerkan defensively', () => {
    expect(parsePamerkan(null)).toBeNull()
    expect(parsePamerkan({ axes: 'x' })).toBeNull()
    expect(stats.axes.map(a => a.id)).toEqual(['coding', 'riset', 'ppt', 'browser', 'otomasi', 'token'])
    expect(stats.totals.toolCalls).toBe(390)
    expect(stats.donut.find(d => d.id === 'lainnya')?.value).toBe(11)

    const junk = parsePamerkan({ axes: [{ id: 'coding', score: 900, value: -5 }], donut: [{ id: 'hack', value: 3 }] })!
    expect(junk.axes[0]).toMatchObject({ score: 100, value: 0 })
    expect(junk.empty).toBe(true)
    expect(junk.donut).toEqual([])
  })

  it('refreshPamerkan asks the core for the window and keeps the last value on errors', async () => {
    api.mockResolvedValueOnce(RAW)
    await refreshPamerkan(7)
    expect(api).toHaveBeenLastCalledWith({ path: '/api/pamerkan?days=7' })
    expect($pamerkan.get()?.totals.sessions).toBe(9)
    expect($pamerkanState.get()).toBe('ready')
    api.mockRejectedValueOnce(new Error('404'))
    await refreshPamerkan(7)
    expect($pamerkanState.get()).toBe('error')
    expect($pamerkan.get()?.totals.sessions).toBe(9)
  })

  it('prefs sanitize, persist and survive junk', () => {
    expect(sanitizePrefs({ background: 'x', days: 5, layout: 'ringkas', theme: 'neon', widgets: { radar: false, zzz: true } })).toEqual({
      ...DEFAULT_PAMERKAN_PREFS,
      layout: 'ringkas',
      theme: 'neon',
      widgets: { ...DEFAULT_PAMERKAN_PREFS.widgets, radar: false }
    })
    const store = new Map<string, string>()
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) }
    savePamerkanPrefs({ ...DEFAULT_PAMERKAN_PREFS, days: 90, trend: 'weekly' }, storage)
    expect(JSON.parse(store.get(PAMERKAN_PREFS_KEY)!).days).toBe(90)
    expect(loadPamerkanPrefs(storage).trend).toBe('weekly')
    store.set(PAMERKAN_PREFS_KEY, '{broken')
    expect(loadPamerkanPrefs(storage)).toEqual(DEFAULT_PAMERKAN_PREFS)
  })
})

describe('Pamerkan charts', () => {
  it('radar axis 0 points up and runs clockwise', () => {
    const [x0, y0] = radarPoint(0, 6, 1, 100, 100, 50)
    expect(x0).toBeCloseTo(100)
    expect(y0).toBeCloseTo(50)
    const [x1] = radarPoint(1, 6, 1, 100, 100, 50)
    expect(x1).toBeGreaterThan(100)
  })

  it('radar draws the real scores and values, empty state draws no shape', () => {
    const box = { h: 560, w: 900, x: 90, y: 600 }
    const ops = radarOps(stats, box, bo)
    const shape = ops.filter(o => o.kind === 'path' && o.fill)
    expect(shape).toHaveLength(1)
    const t = texts(ops)
    expect(t).toEqual(expect.arrayContaining(['Coding', 'Riset', 'PPT', 'Browser', 'Otomasi', 'Token']))
    expect(t.some(x => x.startsWith('312'))).toBe(true)
    inside(ops, 1080, 1920)

    const e = radarOps(empty, box, bo)
    expect(e.some(o => o.kind === 'path' && o.fill)).toBe(false)
    expect(texts(e)).toContain(PAMERKAN_LABELS_ID.empty)
  })

  it('bars use real counts, donut sums to 360°, trend handles daily + weekly', () => {
    const box = { h: 300, w: 420, x: 100, y: 100 }
    const bars = barsOps(stats, box, bo).filter(o => o.kind === 'rect')
    // 5 tracks + 5 fills (every axis has a value)
    expect(bars).toHaveLength(10)
    const fills = bars.filter((_, i) => i % 2 === 1) as Extract<DrawOp, { kind: 'rect' }>[]
    expect(fills[0].w).toBeCloseTo(box.w) // coding is the max

    const arcs = donutOps(stats, box, { ...bo, style: 'kaca' }).filter(o => o.kind === 'arc') as Extract<DrawOp, { kind: 'arc' }>[]
    expect(arcs).toHaveLength(6)
    expect(arcs.reduce((a, s) => a + (s.end - s.start), 0)).toBeCloseTo(Math.PI * 2)
    expect(texts(donutOps(empty, box, { ...bo, style: 'kaca' }))).toContain(PAMERKAN_LABELS_ID.empty)

    const daily = trendOps(stats, { ...box, w: 900 }, { ...bo, mode: 'daily' })
    expect(daily.filter(o => o.kind === 'rect').length).toBeGreaterThan(5)
    expect(texts(daily)).toContain('10-01')
    expect(texts(trendOps(stats, { ...box, w: 900 }, { ...bo, mode: 'weekly' }))).toContain('W33')
    expect(texts(trendOps(empty, box, { ...bo, mode: 'daily' }))).toContain(PAMERKAN_LABELS_ID.empty)
  })

  it('planBlocks drops lowest priority first and grows the radar', () => {
    const p = planBlocks(['radar', 'totals', 'row', 'trend'], 900, 28, 'story')
    expect(p.dropped).toEqual(['trend'])
    expect(p.heights.radar).toBeGreaterThan(360)
    expect(planBlocks(['radar'], 100, 20, 'feed').dropped).toEqual(['radar'])
  })
})

describe('Kartu with Pamerkan', () => {
  for (const format of ['story', 'feed'] as const) {
    for (const style of PAMERKAN_THEMES) {
      it(`${style} ${format}: charts above the QR, inside the canvas`, () => {
        const { h, w } = SHARE_CARD_SIZE[format]
        const plan = planShareCard(card(), {
          accent: '#EE1C1C',
          format,
          layout: 'grafik',
          pamerkan: stats,
          showOffice: true,
          showStats: true,
          style
        })
        inside(plan.ops, w, h)
        const t = texts(plan.ops)
        expect(t.some(x => x.startsWith('RADAR'))).toBe(true)
        expect(t).toContain('Dibuat dengan Neovarch')
        const qr = plan.ops.find(o => o.kind === 'qr')!
        const radarTitle = plan.ops.find(o => o.kind === 'text' && o.text.startsWith('RADAR'))!
        expect(radarTitle.y).toBeLessThan(qr.y)

        for (const op of plan.ops) {
          if (op.kind === 'path') {
            expect(Math.max(...op.points.map(p => p[1]))).toBeLessThan(qr.y)
          }
        }
      })
    }
  }

  it('widgets can be hidden; layouts change what fits', () => {
    const base = { accent: '#7C3AED', format: 'story' as const, pamerkan: stats, showOffice: true, showStats: true, style: 'gelap' as const }
    const off = layoutShareCard(card(), { ...base, layout: 'grafik', widgets: { model: false, radar: false, stats: false, trend: false } })
    const t = texts(off)
    expect(t.some(x => x.startsWith('RADAR'))).toBe(false)
    expect(t).not.toContain('agen aktif')
    expect(t.some(x => x.startsWith('model ·'))).toBe(false)
    expect(t).toContain('AKTIVITAS')

    // classic layout with the big office shot leaves no room in Feed
    const feed = planShareCard(card(), { ...base, format: 'feed', layout: 'kartu' })
    expect(feed.dropped).toContain('radar')

    const ringkas = planShareCard(card(), { ...base, layout: 'ringkas' })
    expect(ringkas.ops.some(o => o.kind === 'image')).toBe(false)
    expect(ringkas.ops.some(o => o.kind === 'arc')).toBe(true)
    expect(texts(ringkas.ops)).not.toContain('AKTIVITAS')
  })

  it('without pamerkan data the classic card is unchanged (no charts)', () => {
    const ops = layoutShareCard(card(), { accent: '#EE1C1C', format: 'story', showOffice: true, showStats: true, style: 'kaca' })
    expect(ops.some(o => o.kind === 'path' || o.kind === 'arc')).toBe(false)
  })

  it('draws the locale texts and every background', () => {
    const ops = layoutShareCard(card(), {
      accent: '#EE1C1C',
      background: 'titik',
      format: 'story',
      labels: nvPamerkanEn.card,
      layout: 'grafik',
      locale: 'en',
      pamerkan: stats,
      showOffice: false,
      showStats: true,
      style: 'kertas',
      text: nvPamerkanEn.card
    })
    expect(texts(ops)).toEqual(expect.arrayContaining(['Made with Neovarch', 'agents active', 'Research', 'Try Neovarch']))

    for (const background of ['gaya', 'polos', 'grid', 'titik', 'aurora', 'simbol', 'garis'] as const) {
      const o = layoutShareCard(card(), { accent: '#EE1C1C', background, format: 'feed', pamerkan: stats, showOffice: false, showStats: true, style: 'neon' })
      inside(o, 1080, 1080)
    }

    expect(SHARE_CARD_STYLES).toHaveLength(6)
  })
})

describe('Pamerkan i18n', () => {
  const flat = (o: unknown, p = ''): string[] =>
    o && typeof o === 'object' ? Object.entries(o).flatMap(([k, v]) => flat(v, p ? `${p}.${k}` : k)) : [p]

  const locales = { ar: nvPamerkanAr, de: nvPamerkanDe, es: nvPamerkanEs, fr: nvPamerkanFr, id: nvPamerkanId, ja: nvPamerkanJa, ru: nvPamerkanRu, zh: nvPamerkanZh, zhHant: nvPamerkanZhHant }

  it('all 10 locales have every key, non-empty, same placeholders', () => {
    const keys = flat(nvPamerkanEn).sort()
    expect(en.nvPamerkan).toBe(nvPamerkanEn)

    const get = (o: unknown, path: string) => path.split('.').reduce((a: unknown, k) => (a as Record<string, unknown>)[k], o) as string

    for (const [name, loc] of Object.entries(locales)) {
      expect(flat(loc).sort(), name).toEqual(keys)

      for (const k of keys) {
        const v = get(loc, k)
        expect(typeof v === 'string' && v.trim().length > 0, `${name}.${k}`).toBe(true)
        const ph = (s: string) => (s.match(/\{[a-z]+\}/g) ?? []).sort().join()
        expect(ph(v), `${name}.${k}`).toBe(ph(get(nvPamerkanEn, k)))
      }
    }
  })
})

describe('KartuCardDialog', () => {
  beforeEach(() => {
    window.localStorage.clear()
    api.mockReset()
    renderPng.mockClear()
    $pamerkan.set(null)
    $pamerkanState.set('idle')
    URL.createObjectURL = vi.fn(() => 'blob:card')
    URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => cleanup())

  it('loads local stats, toggles widgets and persists choices', async () => {
    api.mockResolvedValue(RAW)
    render(<KartuCardDialog officeShot={null} onOpenChange={() => {}} open />)
    await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/pamerkan?days=30' }))
    await waitFor(() => expect(screen.getByAltText(en.nvPamerkan.previewAlt)).toBeTruthy())

    const lastOpts = () => (renderPng.mock.calls.at(-1) as unknown as [unknown, { pamerkan: null | PamerkanStats; style: string; widgets: Record<string, boolean> }])[1]
    await waitFor(() => expect(lastOpts().pamerkan?.totals.toolCalls).toBe(390))

    const radar = document.querySelector<HTMLInputElement>('input[data-widget="radar"]')!
    expect(radar.checked).toBe(true)
    await act(async () => fireEvent.click(radar))
    await waitFor(() => expect(lastOpts().widgets.radar).toBe(false))
    expect(JSON.parse(window.localStorage.getItem(PAMERKAN_PREFS_KEY)!).widgets.radar).toBe(false)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: en.nvPamerkan.themes.neon })))
    await waitFor(() => expect(lastOpts().style).toBe('neon'))

    await act(async () => fireEvent.click(screen.getByRole('button', { name: en.nvPamerkan.windowDays.replace('{days}', '7') })))
    await waitFor(() => expect(api).toHaveBeenCalledWith({ path: '/api/pamerkan?days=7' }))
    expect(JSON.parse(window.localStorage.getItem(PAMERKAN_PREFS_KEY)!).days).toBe(7)
  })

  it('shows the empty state and the old-core note', async () => {
    api.mockResolvedValueOnce(EMPTY_RAW)
    render(<KartuCardDialog officeShot={null} onOpenChange={() => {}} open />)
    await waitFor(() => expect(screen.getByText(en.nvPamerkan.empty)).toBeTruthy())
    cleanup()
    $pamerkan.set(null)
    api.mockRejectedValueOnce(new Error('404'))
    render(<KartuCardDialog officeShot={null} onOpenChange={() => {}} open />)
    await waitFor(() => expect(screen.getByText(en.nvPamerkan.unavailable)).toBeTruthy())
  })
})
