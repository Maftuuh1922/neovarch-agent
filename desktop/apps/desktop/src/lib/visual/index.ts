// ```visual blocks: parse → render/sanitise → one prepared card that both the
// desktop (iframe sandbox="") and the Android WebView (bundled copy of this
// module, see scripts/build-visual-bundle.mjs) display the same way.

import { parseVisualSource, VisualError } from './parse'
import { renderSpec, SVG_STYLE } from './render'
import { sanitizeHtml, sanitizeSvg } from './sanitize'
import { esc, wrapText } from './text'
import { themeCss, themeVars, type VisualTheme } from './theme'

export { partialTitle, VisualError } from './parse'
export { renderSpec, SPEC_TYPES } from './render'
export { DEFAULT_THEME_DARK, DEFAULT_THEME_LIGHT, themeCss, type VisualTheme } from './theme'

export interface PreparedVisual {
  caption?: string
  /** Intrinsic height in px for svg cards (from the viewBox). */
  height?: number
  /** svg = one <svg> element; html = an HTML+CSS fragment. */
  kind: 'svg' | 'html'
  markup: string
  /** Where the block came from: a declarative spec, or raw svg/html. */
  source: 'spec' | 'svg' | 'html'
  title?: string
  width?: number
}

export const MAX_VISUAL_CHARS = 200_000

function svgSizeOf(markup: string): { height: number; width: number } | null {
  const tag = /<svg\b[^>]*>/i.exec(markup)?.[0] ?? ''

  const attr = (name: string) =>
    new RegExp(`\\s${name}\\s*=\\s*"([^"]*)"`, 'i').exec(tag)?.[1] ?? new RegExp(`\\s${name}\\s*=\\s*'([^']*)'`, 'i').exec(tag)?.[1]

  const vb = (attr('viewBox') ?? '').trim().split(/[\s,]+/).map(Number)

  if (vb.length === 4 && vb[2] > 0 && vb[3] > 0) {
    return { height: vb[3], width: vb[2] }
  }

  const rawW = attr('width') ?? ''
  const w = Number.parseFloat(rawW)
  const h = Number.parseFloat(attr('height') ?? '')

  return w > 0 && h > 0 && !rawW.includes('%') ? { height: h, width: w } : null
}

/**
 * Give a raw <svg> a viewBox (from width/height) so it scales crisply, and a
 * pixel width/height (from the viewBox) so it never scales up past its
 * intended size: small diagrams stay small, wide ones shrink to fit.
 */
function ensureViewBox(markup: string, size: { height: number; width: number }): string {
  return markup.replace(/<svg\b([^>]*)>/i, (_whole, attrs: string) => {
    let next = attrs.replace(/\s(width|height)\s*=\s*("[^"]*"|'[^']*')/gi, '')
    next += ` width="${size.width}" height="${size.height}"`

    if (!/\sviewBox\s*=/i.test(next)) {
      next += ` viewBox="0 0 ${size.width} ${size.height}"`
    }

    return `<svg${next}>`
  })
}

/**
 * `width` = the space the card body has (px, without the card padding). Specs use
 * it to pick a layout that stays readable (timeline vertical on a phone, compare
 * panels stacked when side by side would be too small, bars that fit).
 */
export function prepareVisual(code: string, opts: { width?: number } = {}): PreparedVisual {
  if (code.length > MAX_VISUAL_CHARS) {
    throw new VisualError('too large')
  }

  const parsed = parseVisualSource(code)

  if (parsed.kind === 'spec') {
    let out

    try {
      out = renderSpec(parsed.spec!, code, { width: opts.width })
    } catch (error) {
      throw new VisualError((error as Error).message)
    }

    const markup = sanitizeSvg(out.svg).trim()

    if (!markup.startsWith('<svg')) {
      throw new VisualError('render produced nothing')
    }

    return { caption: parsed.caption, height: out.height, kind: 'svg', markup, source: 'spec', title: parsed.title, width: out.width }
  }

  if (parsed.kind === 'svg') {
    const clean = sanitizeSvg(parsed.body).trim()

    if (!clean.startsWith('<svg')) {
      throw new VisualError('invalid svg')
    }

    const size = svgSizeOf(clean)

    if (!size) {
      throw new VisualError('svg needs a viewBox or width/height')
    }

    return {
      caption: parsed.caption,
      height: size.height,
      kind: 'svg',
      markup: ensureViewBox(clean, size),
      source: 'svg',
      title: parsed.title,
      width: size.width
    }
  }

  const clean = sanitizeHtml(parsed.body).trim()

  if (!clean) {
    throw new VisualError('empty html')
  }

  return { caption: parsed.caption, kind: 'html', markup: clean, source: 'html', title: parsed.title }
}

/** Base CSS every card gets (inside the frame / shadow root). */
export function cardCss(theme: VisualTheme, selector = ':root'): string {
  return (
    themeCss(theme, selector) +
    'html,body{margin:0;padding:0;background:var(--nv-bg);color:var(--nv-fg);font-family:var(--nv-font);font-size:14px;line-height:1.45;-webkit-font-smoothing:antialiased;overflow:hidden}' +
    '.nv-root{padding:12px 14px;box-sizing:border-box;color:var(--nv-fg);font-family:var(--nv-font);font-size:14px;line-height:1.45}' +
    '.nv-root.nv-svg{display:flex;justify-content:center}' +
    '.nv-root.nv-svg>svg{display:block;max-width:100%;height:auto}' +
    '.nv-root *{box-sizing:border-box}' +
    // Raw svg/html may use the same helper classes as generated specs.
    SVG_STYLE
  )
}

const FRAME_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"

/** Full srcdoc for `<iframe sandbox="">`: no scripts, no network. */
export function frameDocument(v: PreparedVisual, theme: VisualTheme): string {
  return (
    `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${FRAME_CSP}">` +
    `<style>${cardCss(theme)}</style></head><body><div class="nv-root nv-${v.kind}">${v.markup}</div></body></html>`
  )
}

/** Height an svg card needs at `width` px, from its viewBox (+ the card padding). */
export function svgCardHeight(v: PreparedVisual, width: number, maxHeight = Number.POSITIVE_INFINITY): number {
  if (!v.width || !v.height) {
    return 160
  }

  const inner = Math.min(v.width, Math.max(40, width - 28))

  return Math.ceil(Math.min((inner * v.height) / v.width + 24, maxHeight))
}

/** Serialise sanitised HTML as XHTML (needed inside foreignObject). */
function toXhtml(html: string): string {
  if (typeof document === 'undefined') {
    return html
  }

  const holder = document.createElement('div')
  holder.innerHTML = html

  return Array.from(holder.childNodes)
    .map(n => new XMLSerializer().serializeToString(n))
    .join('')
}

/**
 * A standalone SVG for "Simpan SVG/PNG": concrete theme colours, background,
 * title on top and caption below. HTML cards are wrapped in a foreignObject.
 */
export function exportSvg(
  v: PreparedVisual,
  theme: VisualTheme,
  opts: { htmlHeight?: number; htmlWidth?: number } = {}
): { height: number; svg: string; width: number } {
  const vars = themeVars(theme)
  const pad = 20
  const bodyW = v.kind === 'svg' ? (v.width ?? 600) : (opts.htmlWidth ?? 640)
  const bodyH = v.kind === 'svg' ? (v.height ?? 400) : (opts.htmlHeight ?? 400)
  const width = Math.ceil(Math.max(bodyW + pad * 2, 280))
  const titleLines = v.title ? wrapText(v.title, 16, width - pad * 2, 2, true) : []
  const capLines = v.caption ? wrapText(v.caption, 13, width - pad * 2, 4) : []
  const titleH = titleLines.length ? titleLines.length * 21 + 10 : 0
  const capH = capLines.length ? capLines.length * 18 + 8 : 0
  const height = Math.ceil(pad + titleH + bodyH + capH + pad)
  const varCss = `svg{${Object.entries(vars)
    .map(([k, val]) => `${k}:${val}`)
    .join(';')}}`
  const bx = Math.round((width - bodyW) / 2)
  const by = pad + titleH
  let body: string

  if (v.kind === 'svg') {
    const open = /<svg\b[^>]*>/i.exec(v.markup)?.[0] ?? '<svg>'
    const cleaned = open.replace(/\s(width|height|x|y)\s*=\s*("[^"]*"|'[^']*')/gi, '')
    body = v.markup.replace(open, cleaned.replace(/<svg\b/i, `<svg x="${bx}" y="${by}" width="${bodyW}" height="${bodyH}"`))
  } else {
    body =
      `<foreignObject x="${bx}" y="${by}" width="${bodyW}" height="${bodyH}">` +
      `<div xmlns="http://www.w3.org/1999/xhtml" class="nv-root nv-html" style="width:${bodyW}px">` +
      `<style>${cardCss(theme, '.nv-root').replace(/html,body\{[^}]*\}/, '')}</style>${toXhtml(v.markup)}</div></foreignObject>`
  }

  const title = titleLines
    .map((line, i) => `<text x="${pad}" y="${pad + 15 + i * 21}" class="nv-t nv-b" font-size="16">${esc(line)}</text>`)
    .join('')

  const caption = capLines
    .map((line, i) => `<text x="${pad}" y="${by + bodyH + 18 + i * 18}" class="nv-m" font-size="13">${esc(line)}</text>`)
    .join('')

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<style>${varCss}${SVG_STYLE}</style><rect width="${width}" height="${height}" rx="14" style="fill:var(--nv-bg)"/>${title}${body}${caption}</svg>`

  return { height, svg, width }
}

/** Measure an HTML card at `width` inside a throwaway shadow root (markup is sanitised; nothing runs). */
export function measureHtml(v: PreparedVisual, theme: VisualTheme, width: number): number {
  if (typeof document === 'undefined') {
    return 240
  }

  const host = document.createElement('div')
  host.style.cssText = `position:absolute;left:-100000px;top:0;width:${Math.max(120, width)}px;visibility:hidden;pointer-events:none`
  document.body.appendChild(host)

  try {
    const root = host.attachShadow({ mode: 'open' })
    root.innerHTML = `<style>${cardCss(theme, ':host')}</style><div class="nv-root nv-html">${v.markup}</div>`
    const h = (root.querySelector('.nv-root') as HTMLElement).getBoundingClientRect().height

    return Math.ceil(h > 0 ? h : 200)
  } finally {
    host.remove()
  }
}
