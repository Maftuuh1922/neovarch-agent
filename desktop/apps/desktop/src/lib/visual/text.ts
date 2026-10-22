// Text helpers for the ```visual renderer: XML escaping and a width estimate
// good enough to size boxes and wrap labels without a DOM (the renderer also
// runs in the Android WebView bundle and in node tests).

export function esc(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function isWide(code: number): boolean {
  return (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xff00 && code <= 0xff60) ||
    code >= 0x1f300
  )
}

// Average advance widths (in em) for a UI sans at weight 500. Wide glyphs
// (CJK, emoji) take a full em; narrow ones less.
function charWidth(ch: string): number {
  const code = ch.codePointAt(0) ?? 0

  if (isWide(code)) {
    return 1
  }

  if ('il.,:;|!\'`'.includes(ch)) {
    return 0.28
  }

  if ('frtjI() []{}'.includes(ch)) {
    return 0.38
  }

  if ('mwMW@%'.includes(ch)) {
    return 0.86
  }

  if (ch >= 'A' && ch <= 'Z') {
    return 0.66
  }

  if (ch >= '0' && ch <= '9') {
    return 0.58
  }

  return 0.55
}

export function textWidth(text: string, fontSize: number, bold = false): number {
  let em = 0

  for (const ch of String(text)) {
    em += charWidth(ch)
  }

  return em * fontSize * (bold ? 1.06 : 1)
}

/** Greedy word wrap to `maxWidth` px; long words are hard-split. */
export function wrapText(text: string, fontSize: number, maxWidth: number, maxLines = 4, bold = false): string[] {
  const words = String(text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)

  const lines: string[] = []
  let line = ''

  for (let word of words) {
    while (textWidth(word, fontSize, bold) > maxWidth && word.length > 1) {
      // Hard split a word that cannot fit on any line.
      let cut = word.length - 1

      while (cut > 1 && textWidth(word.slice(0, cut), fontSize, bold) > maxWidth) {
        cut -= 1
      }

      if (line) {
        lines.push(line)
        line = ''
      }

      lines.push(word.slice(0, cut))
      word = word.slice(cut)
    }

    const candidate = line ? `${line} ${word}` : word

    if (textWidth(candidate, fontSize, bold) <= maxWidth || !line) {
      line = candidate
    } else {
      lines.push(line)
      line = word
    }
  }

  if (line) {
    lines.push(line)
  }

  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    let last = kept[maxLines - 1]

    while (last.length > 1 && textWidth(`${last}…`, fontSize, bold) > maxWidth) {
      last = last.slice(0, -1)
    }

    kept[maxLines - 1] = `${last.trimEnd()}…`

    return kept
  }

  return lines.length ? lines : ['']
}

export function r(value: number): string {
  return String(Math.round(value * 10) / 10)
}

/** `<text>` with one `<tspan>` per line, vertically centred on `y` (or starting at `y`). */
export function textBlock(
  lines: string[],
  x: number,
  y: number,
  opts: {
    anchor?: 'start' | 'middle' | 'end'
    baseline?: 'center' | 'top'
    className?: string
    lineHeight?: number
    size?: number
  } = {}
): string {
  const size = opts.size ?? 13
  const lh = opts.lineHeight ?? Math.round(size * 1.3)
  const anchor = opts.anchor ?? 'middle'
  const total = (lines.length - 1) * lh
  // A fixed cap-height offset instead of dominant-baseline (not honoured by
  // every rasteriser used for export): ≈0.35em centres the x-height.
  const first = opts.baseline === 'top' ? y + size * 0.8 : y - total / 2 + size * 0.35
  const tspans = lines.map((line, i) => `<tspan x="${r(x)}" y="${r(first + i * lh)}">${esc(line)}</tspan>`).join('')

  return `<text class="${opts.className ?? 'nv-t'}" font-size="${size}" text-anchor="${anchor}">${tspans}</text>`
}
