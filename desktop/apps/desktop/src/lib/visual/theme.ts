// Theme tokens for ```visual cards. The host (desktop renderer or Android
// WebView) passes the app's resolved colours; the palette below stays fixed so
// "blue = important" means the same thing on every theme.

export interface VisualTheme {
  /** Brand accent (Neovarch red by default). */
  accent?: string
  /** Card / frame background. */
  bg: string
  dark: boolean
  /** Text colour. */
  fg: string
  font?: string
  /** Edge colour. */
  line?: string
  /** Secondary text. */
  muted: string
  /** Hairlines (node outlines, panel borders, axes). */
  stroke: string
  /** Node fill. */
  surface: string
}

const LIGHT = {
  amber: '#B45309',
  bar: '#A8B1BD',
  blue: '#2563EB',
  green: '#15803D',
  pink: '#DB2777',
  purple: '#7C3AED',
  red: '#DC2626',
  teal: '#0F766E'
}

const DARK = {
  amber: '#F5B544',
  bar: '#5B6470',
  blue: '#4C8DFF',
  green: '#3FB97A',
  pink: '#F472B6',
  purple: '#A78BFA',
  red: '#F25F5C',
  teal: '#2DD4BF'
}

export const DEFAULT_THEME_DARK: VisualTheme = {
  accent: '#EE1C1C',
  bg: '#141010',
  dark: true,
  fg: '#F4F2ED',
  muted: '#A49B95',
  stroke: '#3A3030',
  surface: '#1E1818'
}

export const DEFAULT_THEME_LIGHT: VisualTheme = {
  accent: '#D7141A',
  bg: '#FFFFFF',
  dark: false,
  fg: '#1A1616',
  muted: '#6B625D',
  stroke: '#D9D2CC',
  surface: '#FFFFFF'
}

const SAFE_VALUE = /^[#(),.%\w\s/-]+$/

function safe(value: string | undefined, fallback: string): string {
  const v = String(value ?? '').trim()

  return v && SAFE_VALUE.test(v) && v.length < 80 ? v : fallback
}

const DEFAULT_FONT = "Inter, 'Segoe UI', system-ui, -apple-system, Roboto, sans-serif"

export function themeVars(theme: VisualTheme): Record<string, string> {
  const base = theme.dark ? DEFAULT_THEME_DARK : DEFAULT_THEME_LIGHT
  const pal = theme.dark ? DARK : LIGHT

  return {
    '--nv-accent': safe(theme.accent, base.accent!),
    '--nv-amber': pal.amber,
    '--nv-bar': pal.bar,
    '--nv-bg': safe(theme.bg, base.bg),
    '--nv-blue': pal.blue,
    '--nv-fg': safe(theme.fg, base.fg),
    '--nv-font': theme.font && /^[\w\s,'"-]+$/.test(theme.font) ? theme.font : DEFAULT_FONT,
    '--nv-green': pal.green,
    '--nv-line': safe(theme.line, theme.dark ? '#8C8580' : '#8A817B'),
    '--nv-muted': safe(theme.muted, base.muted),
    '--nv-on': '#FFFFFF',
    '--nv-panel': theme.dark ? 'rgba(255,255,255,0.025)' : 'rgba(0,0,0,0.018)',
    '--nv-pink': pal.pink,
    '--nv-purple': pal.purple,
    '--nv-red': pal.red,
    '--nv-stroke': safe(theme.stroke, base.stroke),
    '--nv-surface': safe(theme.surface, base.surface),
    '--nv-teal': pal.teal
  }
}

export function themeCss(theme: VisualTheme, selector = ':root'): string {
  const vars = Object.entries(themeVars(theme))
    .map(([k, v]) => `${k}:${v}`)
    .join(';')

  return `${selector}{${vars};color-scheme:${theme.dark ? 'dark' : 'light'}}`
}
