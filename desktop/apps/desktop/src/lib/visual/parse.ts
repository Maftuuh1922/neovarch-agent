// Parsing for ```visual fences. A block is one of:
//   1. a declarative spec (JSON; comments and trailing commas tolerated)
//      {"type": "graph" | "flow" | "bar" | "timeline" | "compare", "title", "caption", ...}
//   2. raw SVG markup (<svg ...>...</svg>)
//   3. an HTML+CSS fragment (<div>...</div><style>...</style>)
// Raw SVG/HTML may start with `title:` / `caption:` header lines (also
// `judul:` / `keterangan:`), optionally closed by a `---` line.

export type VisualSourceKind = 'spec' | 'svg' | 'html'

export interface ParsedVisual {
  body: string
  caption?: string
  kind: VisualSourceKind
  spec?: Record<string, unknown>
  title?: string
}

export class VisualError extends Error {}

const HEADER = /^\s*(title|judul|caption|keterangan)\s*:\s*(.*)$/i

function stripHeader(code: string): { body: string; caption?: string; title?: string } {
  const lines = code.replace(/\r\n?/g, '\n').split('\n')
  let title: string | undefined
  let caption: string | undefined
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (!line.trim()) {
      i += 1
      continue
    }

    const m = HEADER.exec(line)

    if (!m) {
      break
    }

    const key = m[1].toLowerCase()

    if (key === 'title' || key === 'judul') {
      title = m[2].trim()
    } else {
      caption = m[2].trim()
    }

    i += 1
  }

  if (i < lines.length && /^\s*---\s*$/.test(lines[i])) {
    i += 1
  }

  return { body: lines.slice(i).join('\n').trim(), caption, title }
}

/** JSON with // and block comments and trailing commas removed (outside strings). */
export function lenientJson(text: string): unknown {
  let out = ''
  let i = 0
  let inString = false

  while (i < text.length) {
    const ch = text[i]

    if (inString) {
      out += ch

      if (ch === '\\') {
        out += text[i + 1] ?? ''
        i += 2
        continue
      }

      if (ch === '"') {
        inString = false
      }

      i += 1
      continue
    }

    if (ch === '"') {
      inString = true
      out += ch
      i += 1
      continue
    }

    if (ch === '/' && text[i + 1] === '/') {
      while (i < text.length && text[i] !== '\n') {
        i += 1
      }

      continue
    }

    if (ch === '/' && text[i + 1] === '*') {
      const end = text.indexOf('*/', i + 2)
      i = end < 0 ? text.length : end + 2
      continue
    }

    out += ch
    i += 1
  }

  return JSON.parse(out.replace(/,(\s*[}\]])/g, '$1'))
}

export function parseVisualSource(code: string): ParsedVisual {
  const { body, caption, title } = stripHeader(String(code ?? ''))

  if (!body) {
    throw new VisualError('empty')
  }

  if (body.startsWith('{')) {
    let spec: unknown

    try {
      spec = lenientJson(body)
    } catch (error) {
      throw new VisualError(`json: ${(error as Error).message}`)
    }

    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
      throw new VisualError('spec must be an object')
    }

    const obj = spec as Record<string, unknown>

    return {
      body,
      caption: typeof obj.caption === 'string' ? obj.caption : caption,
      kind: 'spec',
      spec: obj,
      title: typeof obj.title === 'string' ? obj.title : title
    }
  }

  const head = body
    .replace(/^<\?xml[^>]*\?>\s*/, '')
    .replace(/^(<!--[\s\S]*?-->\s*)+/, '')
    .replace(/^<!DOCTYPE[^>]*>\s*/i, '')

  if (head.startsWith('<svg')) {
    return { body: head, caption, kind: 'svg', title }
  }

  if (head.startsWith('<')) {
    return { body: head, caption, kind: 'html', title }
  }

  throw new VisualError('unknown format')
}

/** Best-effort title while the fence is still streaming (no full parse). */
export function partialTitle(code: string): string | undefined {
  const json = /"title"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(code)

  if (json) {
    try {
      return JSON.parse(`"${json[1]}"`) as string
    } catch {
      return json[1]
    }
  }

  const line = /^\s*(?:title|judul)\s*:\s*(.+)$/im.exec(code)

  return line ? line[1].trim() : undefined
}
