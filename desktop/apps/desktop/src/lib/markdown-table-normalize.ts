/**
 * Repair GFM tables that a model streamed onto a single line.
 *
 * Some models (seen with MiMo via 9Router) drop the newlines inside a table:
 *
 *   Rute ada 3: | Rute | Error | |---|---| | `a` | 401 | | `b` | 402 |
 *
 * GFM only recognises a table when the header, the delimiter row and every
 * body row sit on their own lines, so that arrives as a paragraph full of
 * pipes. This pass finds an inline delimiter row (`|---|:--:|`), takes the
 * header cells right before it and the body rows after it (rows are split
 * every N cells, N = delimiter columns), and rewrites them onto separate lines
 * with blank lines around the table. Prose before/after the table stays as its
 * own paragraph.
 *
 * Also handles a header line that starts with prose ("…hulunya: | a | b |")
 * followed by a proper delimiter line.
 *
 * Safe while streaming: nothing changes until a complete delimiter row with at
 * least two columns has arrived; a half-received last row is kept as a row
 * (padded at render time). Pipes inside `inline code` or escaped (`\|`) are
 * not cell separators. Callers pass prose only (fenced code is skipped by
 * `normalizeMarkdownTables` itself as well).
 *
 * The Flutter app ships the same algorithm in
 * lib/ui/widgets/markdown_table_normalize.dart — keep the two in step.
 */

const INLINE_DELIM_RE = /\|[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|/
const DELIM_LINE_RE = /^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$/
const FENCE_RE = /^[ \t]*(```|~~~)/

/** Indices of the `|` characters that separate cells (outside code spans, not escaped). */
function pipePositions(s: string): number[] {
  const out: number[] = []
  let inCode = false
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '\\') {
      i++
      continue
    }
    if (ch === '`') {
      inCode = !inCode
      continue
    }
    if (ch === '|' && !inCode) out.push(i)
  }
  return out
}

function splitCells(s: string): string[] {
  const pos = pipePositions(s)
  const out: string[] = []
  let last = 0
  for (const p of pos) {
    out.push(s.slice(last, p))
    last = p + 1
  }
  out.push(s.slice(last))
  return out
}

function row(cells: string[]): string {
  return `| ${cells.map(c => c.trim()).join(' | ')} |`
}

function delimCells(delim: string): string[] {
  return delim
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(c => c.trim())
}

/**
 * Split `pre` (text before the delimiter) into prose + header cells: the
 * header is the last `n` cells, i.e. everything after the (n+1)-th pipe from
 * the end. Returns null when there are not enough pipes.
 */
function splitHeader(pre: string, n: number): { prose: string; header: string[] } | null {
  const trimmed = pre.replace(/[ \t]+$/, '')
  const pos = pipePositions(trimmed)
  if (pos.length < n + 1) return null
  // A header ends with a pipe right before the delimiter.
  if (pos[pos.length - 1] !== trimmed.length - 1) return null
  const start = pos[pos.length - 1 - n]
  const header = splitCells(trimmed.slice(start + 1, trimmed.length - 1))
  if (header.length !== n) return null
  return { prose: trimmed.slice(0, start).trim(), header }
}

/** Body rows from the text after the delimiter: n cells, a gap token, n cells… */
function splitBody(post: string, n: number): { rows: string[][]; tail: string } {
  const tokens = splitCells(post)
  const rows: string[][] = []
  // tokens[0] is the gap between the delimiter's closing pipe and the first row's opening pipe.
  let i: number
  if (tokens.length && tokens[0].trim() !== '') {
    // Text right after the delimiter with no row: not a body, keep as prose.
    return { rows, tail: post.trim() }
  }
  i = 1
  while (i < tokens.length) {
    const remaining = tokens.length - i
    if (remaining === 1) {
      // Only reached right after a row gap ("| |"): the start of the next row
      // that is still streaming in. (Prose after a closing pipe is caught by
      // the gap check below.)
      if (tokens[i].trim() !== '') rows.push([tokens[i]])
      return { rows, tail: '' }
    }
    const cells = tokens.slice(i, i + n)
    i += n
    rows.push(cells)
    if (i >= tokens.length) break
    // Expect the gap between "|" and "|" of the next row.
    if (tokens[i].trim() !== '') {
      return { rows, tail: tokens.slice(i).join('|').trim() }
    }
    i++
  }
  return { rows, tail: '' }
}

function normalizeLine(line: string, next: string | undefined): { lines: string[]; consumedNext: boolean } | null {
  const m = INLINE_DELIM_RE.exec(line)
  if (m && !DELIM_LINE_RE.test(line)) {
    const delim = m[0]
    const n = delimCells(delim).length
    const head = splitHeader(line.slice(0, m.index), n)
    if (!head) return null
    const { rows, tail } = splitBody(line.slice(m.index + delim.length), n)
    const out: string[] = []
    if (head.prose) out.push(head.prose, '')
    out.push(row(head.header), row(delimCells(delim)))
    for (const r of rows) {
      while (r.length < n) r.push('')
      out.push(row(r))
    }
    if (tail) out.push('', tail)
    else out.push('')
    return { lines: out, consumedNext: false }
  }
  // "prose: | a | b |" on one line, delimiter on the next.
  if (next !== undefined && DELIM_LINE_RE.test(next) && !line.trimStart().startsWith('|')) {
    const n = delimCells(next).length
    const head = splitHeader(line, n)
    if (!head || !head.prose) return null
    return { lines: [head.prose, '', row(head.header)], consumedNext: false }
  }
  return null
}

export function normalizeMarkdownTables(text: string): string {
  if (!text.includes('|')) return text
  const lines = text.split('\n')
  const out: string[] = []
  let fence: string | null = null
  let changed = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const f = FENCE_RE.exec(line)
    if (f) {
      if (fence === null) fence = f[1]
      else if (f[1] === fence) fence = null
      out.push(line)
      continue
    }
    if (fence !== null || !line.includes('|')) {
      out.push(line)
      continue
    }
    const r = normalizeLine(line, lines[i + 1])
    if (!r) {
      out.push(line)
      continue
    }
    changed = true
    // Keep a blank line before the table when the previous line is prose.
    if (out.length && out[out.length - 1].trim() !== '' && r.lines[0] !== '' && r.lines[0].startsWith('|')) out.push('')
    out.push(...r.lines)
  }
  if (!changed) return text
  // A trailing '' we added at the very end is harmless for markdown but would
  // change streamed text length checks; drop one.
  if (out.length && out[out.length - 1] === '' && lines[lines.length - 1] !== '') out.pop()
  return out.join('\n')
}
