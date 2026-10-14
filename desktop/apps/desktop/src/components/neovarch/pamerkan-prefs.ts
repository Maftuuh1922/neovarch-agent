// Pamerkan card preferences: which widgets show, theme, layout, background,
// window and trend granularity. Persisted in localStorage (one JSON blob);
// unknown / broken values fall back to the defaults one field at a time.
export const PAMERKAN_WIDGETS = ['stats', 'totals', 'office', 'radar', 'bars', 'donut', 'trend', 'model'] as const
export type PamerkanWidget = (typeof PAMERKAN_WIDGETS)[number]

export const PAMERKAN_THEMES = ['kaca', 'gelap', 'warna', 'neon', 'kertas', 'terminal'] as const
export type PamerkanTheme = (typeof PAMERKAN_THEMES)[number]

export const PAMERKAN_LAYOUTS = ['grafik', 'kartu', 'ringkas'] as const
export type PamerkanLayout = (typeof PAMERKAN_LAYOUTS)[number]

export const PAMERKAN_BACKGROUNDS = ['gaya', 'polos', 'grid', 'titik', 'aurora', 'simbol', 'garis'] as const
export type PamerkanBackground = (typeof PAMERKAN_BACKGROUNDS)[number]

export const PAMERKAN_WINDOWS = [7, 30, 90] as const
export type PamerkanWindow = (typeof PAMERKAN_WINDOWS)[number]

export type PamerkanTrendMode = 'daily' | 'weekly'

export interface PamerkanPrefs {
  background: PamerkanBackground
  days: PamerkanWindow
  layout: PamerkanLayout
  theme: PamerkanTheme
  trend: PamerkanTrendMode
  widgets: Record<PamerkanWidget, boolean>
}

export const PAMERKAN_PREFS_KEY = 'nv.pamerkan.prefs'

export const DEFAULT_PAMERKAN_PREFS: PamerkanPrefs = {
  background: 'gaya',
  days: 30,
  layout: 'grafik',
  theme: 'kaca',
  trend: 'daily',
  widgets: { bars: true, donut: true, model: true, office: true, radar: true, stats: true, totals: true, trend: true }
}

function pick<T extends number | string>(allowed: readonly T[], value: unknown, fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

export function sanitizePrefs(raw: unknown): PamerkanPrefs {
  const r = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const w = r.widgets && typeof r.widgets === 'object' ? (r.widgets as Record<string, unknown>) : {}
  const d = DEFAULT_PAMERKAN_PREFS
  const widgets = { ...d.widgets }

  for (const id of PAMERKAN_WIDGETS) {
    if (typeof w[id] === 'boolean') {
      widgets[id] = w[id] as boolean
    }
  }

  return {
    background: pick(PAMERKAN_BACKGROUNDS, r.background, d.background),
    days: pick(PAMERKAN_WINDOWS, r.days, d.days),
    layout: pick(PAMERKAN_LAYOUTS, r.layout, d.layout),
    theme: pick(PAMERKAN_THEMES, r.theme, d.theme),
    trend: pick(['daily', 'weekly'] as const, r.trend, d.trend),
    widgets
  }
}

export function loadPamerkanPrefs(storage: null | Pick<Storage, 'getItem'> = safeStorage()): PamerkanPrefs {
  try {
    const raw = storage?.getItem(PAMERKAN_PREFS_KEY)

    return sanitizePrefs(raw ? JSON.parse(raw) : null)
  } catch {
    return sanitizePrefs(null)
  }
}

export function savePamerkanPrefs(prefs: PamerkanPrefs, storage: null | Pick<Storage, 'setItem'> = safeStorage()): void {
  try {
    storage?.setItem(PAMERKAN_PREFS_KEY, JSON.stringify(sanitizePrefs(prefs)))
  } catch {
    // private mode / storage off: the choice lasts for this dialog only
  }
}

function safeStorage(): null | Storage {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}
