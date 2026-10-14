// Pamerkan chart blocks for the Kartu Neovarch canvas: radar (spider), bar,
// donut and trend (daily / weekly), plus the usage totals tiles. Every block is
// a pure list of draw ops (same DrawOp list kartu-card.ts paints), so the
// geometry is tested without a real canvas. Values are only ever the ones the
// core counted (`GET /api/pamerkan`); with no data a block shows its empty
// state instead of a made-up shape.
import type { CardColors, DrawOp } from './kartu-card'
import type { PamerkanActivity, PamerkanAxis, PamerkanSlice, PamerkanStats } from './pamerkan-store'
import { PAMERKAN_ACTIVITY } from './pamerkan-store'

export interface Box {
  h: number
  w: number
  x: number
  y: number
}

export interface PamerkanCardLabels {
  activeDays: string
  axes: Record<PamerkanAxis, string>
  barsTitle: string
  calls: string
  donutTitle: string
  empty: string
  lainnya: string
  radarTitle: string
  streak: string
  tokens: string
  toolCalls: string
  trendDaily: string
  trendWeekly: string
  /** "{days} hari terakhir" */
  window: string
}

export const PAMERKAN_LABELS_ID: PamerkanCardLabels = {
  activeDays: 'hari aktif',
  axes: { browser: 'Browser', coding: 'Coding', otomasi: 'Otomasi', ppt: 'PPT', riset: 'Riset', token: 'Token' },
  barsTitle: 'AKTIVITAS',
  calls: 'aksi',
  donutTitle: 'PORSI',
  empty: 'Belum ada data pemakaian',
  lainnya: 'Lainnya',
  radarTitle: 'RADAR',
  streak: 'hari beruntun',
  tokens: 'token',
  toolCalls: 'panggilan alat',
  trendDaily: 'TREN HARIAN',
  trendWeekly: 'TREN MINGGUAN',
  window: '{days} hari terakhir'
}

const SANS = 'Inter, "Segoe UI", system-ui, sans-serif'
const MONO = '"JetBrains Mono", ui-monospace, monospace'

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.replace(/(.)/g, '$1$1') : h.padEnd(6, '0').slice(0, 6)
  const n = parseInt(full, 16)

  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** `#rrggbb` + alpha → rgba(); non-hex colours pass through unchanged. */
export function withAlpha(color: string, a: number): string {
  if (!/^#[0-9a-f]{3,8}$/i.test(color)) {
    return color
  }

  const [r, g, b] = hexToRgb(color)

  return `rgba(${r}, ${g}, ${b}, ${a})`
}

export function formatCount(n: number, locale = 'id'): string {
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 1, notation: 'compact' }).format(n)
  } catch {
    return String(Math.round(n))
  }
}

const ANGLE0 = -Math.PI / 2

/** Corner of axis `i` of `n` at `fraction` of radius `r` (axis 0 points up, clockwise). */
export function radarPoint(i: number, n: number, fraction: number, cx: number, cy: number, r: number): [number, number] {
  const a = ANGLE0 + (i * 2 * Math.PI) / n

  return [cx + Math.cos(a) * r * fraction, cy + Math.sin(a) * r * fraction]
}

function title(text: string, box: Box, c: CardColors, size: number): DrawOp {
  return { color: c.muted, font: `600 ${size}px ${MONO}`, kind: 'text', maxWidth: box.w, text, x: box.x, y: box.y + size }
}

export interface BlockOpts {
  colors: CardColors
  labels: PamerkanCardLabels
  locale: string
  scale: number
}

/** Spider chart of the six axes (score 0-100); grid + empty note when nothing was counted. */
export function radarOps(stats: PamerkanStats, box: Box, o: BlockOpts): DrawOp[] {
  const { colors: c, labels, scale: s } = o
  const ops: DrawOp[] = [title(`${labels.radarTitle} · ${labels.window.replace('{days}', String(stats.days))}`, box, c, Math.round(24 * s))]
  const top = box.y + 44 * s
  const labelPad = 64 * s
  const cx = box.x + box.w / 2
  const cy = top + (box.y + box.h - top) / 2
  const r = Math.max(20, Math.min(box.w / 2 - labelPad * 1.9, (box.y + box.h - top) / 2 - labelPad * 0.7))
  const n = stats.axes.length

  for (const ring of [0.25, 0.5, 0.75, 1]) {
    ops.push({
      closed: true,
      kind: 'path',
      points: stats.axes.map((_, i) => radarPoint(i, n, ring, cx, cy, r)),
      stroke: c.line,
      width: ring === 1 ? 3 : 1.5
    })
  }

  stats.axes.forEach((_, i) => ops.push({ closed: false, kind: 'path', points: [[cx, cy], radarPoint(i, n, 1, cx, cy, r)], stroke: c.line, width: 1.5 }))

  if (!stats.empty) {
    const pts = stats.axes.map((a, i) => radarPoint(i, n, Math.max(0.04, a.score / 100), cx, cy, r))
    ops.push({ closed: true, fill: withAlpha(c.accent, 0.32), kind: 'path', points: pts, stroke: c.accent, width: 4 })
    pts.forEach(([x, y]) => ops.push({ fill: c.accent, kind: 'circle', r: 7 * s, x, y }))
  }

  stats.axes.forEach((a, i) => {
    const [x, y] = radarPoint(i, n, 1, cx, cy, r + 22 * s)
    const dx = x - cx
    const align: 'center' | 'left' | 'right' = Math.abs(dx) < 4 ? 'center' : dx > 0 ? 'left' : 'right'
    const up = y < cy - 4
    const ly = up ? y - 26 * s : y + 22 * s
    ops.push({ align, color: c.text, font: `600 ${Math.round(24 * s)}px ${SANS}`, kind: 'text', text: labels.axes[a.id], x, y: ly })
    ops.push({
      align,
      color: c.muted,
      font: `500 ${Math.round(20 * s)}px ${MONO}`,
      kind: 'text',
      text: a.id === 'token' ? `${formatCount(a.value, o.locale)} ${labels.tokens}` : `${formatCount(a.value, o.locale)}`,
      x,
      y: ly + 24 * s
    })
  })

  if (stats.empty) {
    ops.push({ align: 'center', color: c.muted, font: `500 ${Math.round(24 * s)}px ${SANS}`, kind: 'text', maxWidth: r * 1.8, text: labels.empty, x: cx, y: cy + 8 * s })
  }

  return ops
}

/** Horizontal bars, one per activity axis, real counts (no scores). */
export function barsOps(stats: PamerkanStats, box: Box, o: BlockOpts): DrawOp[] {
  const { colors: c, labels, scale: s } = o
  const ops: DrawOp[] = [title(labels.barsTitle, box, c, Math.round(22 * s))]
  const top = box.y + 40 * s
  const rows = PAMERKAN_ACTIVITY.map(id => ({ id, value: stats.bars.find(b => b.id === id)?.value ?? 0 }))
  const max = Math.max(0, ...rows.map(r => r.value))
  const rh = (box.y + box.h - top) / rows.length
  const barH = Math.max(8, Math.min(18 * s, rh * 0.32))

  rows.forEach((row, i) => {
    const y = top + i * rh
    ops.push({ color: c.text, font: `500 ${Math.round(20 * s)}px ${SANS}`, kind: 'text', text: labels.axes[row.id], x: box.x, y: y + 22 * s })
    ops.push({ align: 'right', color: c.muted, font: `500 ${Math.round(19 * s)}px ${MONO}`, kind: 'text', text: formatCount(row.value, o.locale), x: box.x + box.w, y: y + 22 * s })
    const by = y + 32 * s
    ops.push({ fill: c.cell, h: barH, kind: 'rect', r: barH / 2, w: box.w, x: box.x, y: by })

    if (row.value > 0 && max > 0) {
      ops.push({ fill: c.accent, h: barH, kind: 'rect', r: barH / 2, w: Math.max(barH, (box.w * row.value) / max), x: box.x, y: by })
    }
  })

  return ops
}

export function sliceColor(id: PamerkanSlice, c: CardColors, style: string): string {
  const order: PamerkanSlice[] = ['coding', 'riset', 'ppt', 'browser', 'otomasi', 'lainnya']
  const i = order.indexOf(id)

  if (style === 'warna') {
    return withAlpha(c.text.startsWith('#') ? c.text : '#111111', [0.92, 0.7, 0.52, 0.38, 0.26, 0.14][i] ?? 0.2)
  }

  const fixed = ['', '#38bdf8', '#facc15', '#a78bfa', '#34d399', '#a8a29e']

  return i === 0 ? c.accent : fixed[i]
}

/** Share of activity per axis (+ "lainnya"); legend with percentages. */
export function donutOps(stats: PamerkanStats, box: Box, o: BlockOpts & { style: string }): DrawOp[] {
  const { colors: c, labels, scale: s } = o
  const ops: DrawOp[] = [title(labels.donutTitle, box, c, Math.round(22 * s))]
  const top = box.y + 40 * s
  const h = box.y + box.h - top
  const legendW = Math.min(box.w * 0.5, 240 * s)
  const r = Math.max(24, Math.min((box.w - legendW - 20 * s) / 2, h / 2) - 4)
  const cx = box.x + r
  const cy = top + h / 2
  const total = stats.donut.reduce((a, d) => a + d.value, 0)

  if (!total) {
    ops.push({ fill: c.cell, kind: 'circle', r, stroke: c.line, x: cx, y: cy })
    ops.push({ fill: 'rgba(0, 0, 0, 0)', kind: 'circle', r: r * 0.58, stroke: c.line, x: cx, y: cy })
    ops.push({ color: c.muted, font: `500 ${Math.round(20 * s)}px ${SANS}`, kind: 'text', maxWidth: legendW, text: labels.empty, x: cx + r + 20 * s, y: cy + 6 })

    return ops
  }

  let a = ANGLE0

  for (const d of stats.donut) {
    const sweep = (d.value / total) * Math.PI * 2
    ops.push({ end: a + sweep, fill: sliceColor(d.id, c, o.style), inner: r * 0.58, kind: 'arc', r, start: a, x: cx, y: cy })
    a += sweep
  }

  ops.push({ align: 'center', color: c.text, font: `700 ${Math.round(30 * s)}px ${SANS}`, kind: 'text', maxWidth: r * 1.1, text: formatCount(total, o.locale), x: cx, y: cy + 8 * s })
  ops.push({ align: 'center', color: c.muted, font: `500 ${Math.round(16 * s)}px ${MONO}`, kind: 'text', maxWidth: r * 1.1, text: labels.calls, x: cx, y: cy + 30 * s })

  const lx = box.x + box.w - legendW
  const shown = stats.donut.slice(0, 6)
  const lh = Math.min(34 * s, h / shown.length)
  const ly0 = cy - (lh * shown.length) / 2

  shown.forEach((d, i) => {
    const y = ly0 + i * lh
    const name = d.id === 'lainnya' ? labels.lainnya : labels.axes[d.id as PamerkanActivity]
    const pct = Math.round((100 * d.value) / total)
    ops.push({ fill: sliceColor(d.id, c, o.style), h: 16 * s, kind: 'rect', r: 4 * s, w: 16 * s, x: lx, y: y + 6 * s })
    ops.push({ color: c.text, font: `500 ${Math.round(19 * s)}px ${SANS}`, kind: 'text', maxWidth: legendW - 26 * s, text: `${name} ${pct}%`, x: lx + 26 * s, y: y + 21 * s })
  })

  return ops
}

/** Column per day / week = tool calls; line = tokens (own scale). */
export function trendOps(stats: PamerkanStats, box: Box, o: BlockOpts & { mode: 'daily' | 'weekly' }): DrawOp[] {
  const { colors: c, labels, scale: s } = o
  const pts = o.mode === 'weekly' ? stats.trend.weekly.map(w => ({ calls: w.calls, key: w.week.replace(/^\d{4}-/, ''), tokens: w.tokens })) : stats.trend.daily.map(d => ({ calls: d.calls, key: d.date.slice(5), tokens: d.tokens }))
  const ops: DrawOp[] = [title(o.mode === 'weekly' ? labels.trendWeekly : labels.trendDaily, box, c, Math.round(22 * s))]
  const top = box.y + 40 * s
  const bottom = box.y + box.h - 28 * s
  const ch = bottom - top
  const maxCalls = Math.max(0, ...pts.map(p => p.calls))
  const maxTok = Math.max(0, ...pts.map(p => p.tokens))

  ops.push({ fill: c.line, h: 2, kind: 'rect', r: 0, w: box.w, x: box.x, y: bottom })

  if (!pts.length || (!maxCalls && !maxTok)) {
    ops.push({ align: 'center', color: c.muted, font: `500 ${Math.round(20 * s)}px ${SANS}`, kind: 'text', maxWidth: box.w, text: labels.empty, x: box.x + box.w / 2, y: top + ch / 2 })

    return ops
  }

  const slot = box.w / pts.length
  const bw = Math.max(4, slot * 0.56)

  pts.forEach((p, i) => {
    if (p.calls > 0 && maxCalls > 0) {
      const bh = Math.max(4, (ch - 8) * (p.calls / maxCalls))
      ops.push({ fill: c.accent, h: bh, kind: 'rect', r: Math.min(6, bw / 2), w: bw, x: box.x + i * slot + (slot - bw) / 2, y: bottom - bh })
    }
  })

  if (maxTok > 0) {
    const line = pts.map((p, i): [number, number] => [box.x + i * slot + slot / 2, bottom - 4 - (ch - 12) * (p.tokens / maxTok)])
    ops.push({ closed: false, kind: 'path', points: line, stroke: c.text, width: 3 })
  }

  ops.push({ color: c.muted, font: `500 ${Math.round(17 * s)}px ${MONO}`, kind: 'text', text: pts[0].key, x: box.x, y: box.y + box.h - 4 })
  ops.push({ align: 'right', color: c.muted, font: `500 ${Math.round(17 * s)}px ${MONO}`, kind: 'text', text: pts[pts.length - 1].key, x: box.x + box.w, y: box.y + box.h - 4 })
  ops.push({
    align: 'right',
    color: c.muted,
    font: `500 ${Math.round(17 * s)}px ${MONO}`,
    kind: 'text',
    text: `▮ ${formatCount(maxCalls, o.locale)} ${labels.calls} · ─ ${formatCount(maxTok, o.locale)} ${labels.tokens}`,
    x: box.x + box.w,
    y: box.y + 22 * s
  })

  return ops
}

/** Usage tiles: tool calls, tokens, active days, streak (from the same window). */
export function totalsTiles(stats: PamerkanStats, labels: PamerkanCardLabels, locale: string): [string, string][] {
  const t = stats.totals

  return [
    [formatCount(t.toolCalls, locale), labels.toolCalls],
    [formatCount(t.tokens, locale), labels.tokens],
    [String(t.activeDays), labels.activeDays],
    [String(t.streak), labels.streak]
  ]
}

export type ChartBlock = 'bars' | 'donut' | 'radar' | 'row' | 'totals' | 'trend'

export interface BlockPlan {
  dropped: ChartBlock[]
  heights: Partial<Record<ChartBlock, number>>
}

export const BLOCK_MIN: Record<'feed' | 'story', Record<ChartBlock, number>> = {
  feed: { bars: 190, donut: 190, radar: 230, row: 190, totals: 104, trend: 150 },
  story: { bars: 250, donut: 250, radar: 360, row: 270, totals: 128, trend: 200 }
}

export const RADAR_MAX = { feed: 330, story: 640 }

/**
 * Fit the enabled blocks (in priority order) into `free` px with `gap` between them:
 * drop from the lowest priority until the minimums fit, then let the radar grow.
 */
export function planBlocks(blocks: ChartBlock[], free: number, gap: number, format: 'feed' | 'story'): BlockPlan {
  const keep = [...blocks]
  const dropped: ChartBlock[] = []
  const need = (list: ChartBlock[]) => list.reduce((a, b) => a + BLOCK_MIN[format][b], 0) + gap * Math.max(0, list.length)

  while (keep.length && need(keep) > free) {
    dropped.unshift(keep.pop()!)
  }

  const heights: Partial<Record<ChartBlock, number>> = {}
  keep.forEach(b => (heights[b] = BLOCK_MIN[format][b]))
  let extra = free - need(keep)

  if (heights.radar !== undefined && extra > 0) {
    const grow = Math.min(extra, RADAR_MAX[format] - heights.radar)
    heights.radar += grow
    extra -= grow
  }

  for (const b of ['row', 'trend', 'bars', 'donut'] as const) {
    if (heights[b] !== undefined && extra > 0) {
      const grow = Math.min(extra, 120)
      heights[b]! += grow
      extra -= grow
    }
  }

  return { dropped, heights }
}
