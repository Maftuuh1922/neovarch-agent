// Old ```mermaid / ```diagram blocks → the declarative ```visual specs, so they
// draw in the same visual-inline style (render.ts) instead of mermaid's own
// look. Pure string parsing (no DOM, no mermaid runtime): it runs in the
// desktop renderer, the Android WebView bundle and node tests.
//
// Supported: flowchart / graph (→ flow, or graph for undirected letter graphs),
// sequenceDiagram (→ sequence), timeline (→ timeline), pie (→ bar) and simple
// stateDiagram(-v2) (→ flow). Anything else, or syntax this parser does not
// understand (subgraphs, composite states, very large diagrams), returns null
// so the caller keeps the classic mermaid renderer.

type Json = Record<string, unknown>

export interface MermaidConversion {
  /** Diagram family, for labels and tests: flowchart | graph | sequence | timeline | pie | state. */
  family: string
  spec: Json
}

const MAX_NODES = 30
const MAX_MESSAGES = 60
const MAX_EVENTS = 16

class Unsupported extends Error {}

/** Strip YAML front matter (`---\ntitle: …\n---`), `%%` comments and `%%{init}%%` directives. */
function preprocess(code: string): { lines: string[]; title?: string } {
  let text = String(code ?? '').replace(/\r\n?/g, '\n')
  let title: string | undefined
  const fm = /^\s*---\n([\s\S]*?)\n---\s*\n/.exec(text)

  if (fm) {
    const t = /^\s*title\s*:\s*(.+)$/m.exec(fm[1])

    if (t) {
      title = unquote(t[1].trim())
    }

    text = text.slice(fm[0].length)
  }

  const lines = text
    .replace(/%%\{[\s\S]*?\}%%/g, '')
    .split('\n')
    .map(l => l.replace(/^\s*%%.*$/, '').trimEnd())
    .filter(l => l.trim())

  return { lines, title }
}

function unquote(s: string): string {
  const t = s.trim()

  if (t.length >= 2 && ((t[0] === '"' && t.endsWith('"')) || (t[0] === "'" && t.endsWith("'")))) {
    return t.slice(1, -1)
  }

  return t
}

/** Mermaid label text → plain text: quotes, markdown backticks, <br>, entities, fa: icons. */
export function cleanLabel(raw: string): string {
  let s = unquote(raw)

  if (s.startsWith('`') && s.endsWith('`') && s.length >= 2) {
    s = s.slice(1, -1)
  }

  return s
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/<\/?(b|i|em|strong|u|small|sub|sup|span)[^>]*>/gi, '')
    .replace(/\bfa:fa-[\w-]+\s*/g, '')
    .replace(/#quot;/g, '"')
    .replace(/#(\d+);/g, (_m, d: string) => String.fromCodePoint(Number(d)))
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Header keyword of a mermaid source (first meaningful line), lower-case. */
export function mermaidFamily(code: string): string {
  const { lines } = preprocess(code)
  const first = (lines[0] ?? '').trim()

  return (/^([A-Za-z][\w-]*)/.exec(first)?.[1] ?? '').toLowerCase()
}

/** A block whose content is a ```visual body (JSON spec, raw SVG/HTML), not mermaid. */
export function looksLikeVisualBody(code: string): boolean {
  const t = String(code ?? '')
    .replace(/^\s*((title|judul|caption|keterangan)\s*:.*\n)*(\s*---\s*\n)?/i, '')
    .trimStart()

  return t.startsWith('{') || t.startsWith('<')
}

// ---------------------------------------------------------------- flowchart --

interface FlowNode {
  id: string
  label: string
  shape: 'box' | 'decision' | 'round' | 'circle'
}

interface FlowLink {
  arrow: boolean
  dashed: boolean
  from: string
  label?: string
  thick: boolean
  to: string
}

const SHAPES: [string, string, FlowNode['shape']][] = [
  ['(((', ')))', 'circle'],
  ['((', '))', 'circle'],
  ['([', '])', 'round'],
  ['[[', ']]', 'box'],
  ['[(', ')]', 'box'],
  ['{{', '}}', 'box'],
  ['[/', '/]', 'box'],
  ['[\\', '\\]', 'box'],
  ['[/', '\\]', 'box'],
  ['[\\', '/]', 'box'],
  ['>', ']', 'box'],
  ['[', ']', 'box'],
  ['(', ')', 'round'],
  ['{', '}', 'decision']
]

function skipClass(s: string, i: number): number {
  const m = /^:::[\w-]+/.exec(s.slice(i))

  return m ? i + m[0].length : i
}

/** Reads `id`, `id[label]`, `id{label}`, `id(["label"])`, … at `pos`; returns null when none. */
function readNode(s: string, pos: number): { end: number; node: Partial<FlowNode> & { id: string } } | null {
  // Single "-" / "." only between word characters, so "A-->B" reads as A, -->, B.
  const idm = /^[\p{L}\p{N}_]+(?:[-.][\p{L}\p{N}_]+)*/u.exec(s.slice(pos))

  if (!idm) {
    return null
  }

  const id = idm[0]
  let i = pos + id.length

  for (const [open, close, shape] of SHAPES) {
    if (!s.startsWith(open, i)) {
      continue
    }

    const start = i + open.length
    let j = start
    let quote = false

    while (j < s.length) {
      if (s[j] === '"') {
        quote = !quote
      } else if (!quote && s.startsWith(close, j)) {
        break
      }

      j += 1
    }

    if (j >= s.length) {
      return null
    }

    i = skipClass(s, j + close.length)

    return { end: i, node: { id, label: cleanLabel(s.slice(start, j)), shape } }
  }

  // Mermaid v11 shape syntax: A@{ shape: diamond, label: "x" }
  if (s.startsWith('@{', i)) {
    const close = s.indexOf('}', i)

    if (close < 0) {
      return null
    }

    const body = s.slice(i + 2, close)
    const shape = /shape\s*:\s*([\w-]+)/.exec(body)?.[1] ?? ''
    const label = /label\s*:\s*("[^"]*"|[^,}]+)/.exec(body)?.[1]

    return {
      end: skipClass(s, close + 1),
      node: {
        id,
        label: label ? cleanLabel(label) : undefined,
        shape: /diam|decision|question/.test(shape) ? 'decision' : /stadium|pill|terminal|circle|start|stop/.test(shape) ? 'round' : 'box'
      }
    }
  }

  return { end: skipClass(s, i), node: { id } }
}

/** Reads a link (`-->`, `-.->`, `==>`, `---`, `-- text -->`, `-->|text|`, `<-->`, `--o`, `--x`) at `pos`. */
function readLink(s: string, pos: number): { end: number; link: Omit<FlowLink, 'from' | 'to'> } | null {
  const rest = s.slice(pos)

  // Text in the middle: A -- text --> B / A -. text .-> B / A == text ==> B
  const mid = /^(<)?(--|==|-\.)\s+([^|]+?)\s+(-{2,}>|-{3,}|={2,}>|={3,}|\.-+>|\.-+|-{2,}[ox]|={2,}[ox])/.exec(rest)

  if (mid) {
    return {
      end: pos + mid[0].length,
      link: { arrow: mid[4].endsWith('>'), dashed: mid[2] === '-.', label: cleanLabel(mid[3]), thick: mid[2] === '==' }
    }
  }

  const plain = /^(<|o|x)?(-{2,}|={2,}|-\.+-)(>|o|x)?(?:\s*\|([^|]*)\|)?/.exec(rest)

  if (!plain) {
    return null
  }

  return {
    end: pos + plain[0].length,
    link: {
      arrow: plain[3] === '>' || plain[3] === 'o' || plain[3] === 'x' || plain[1] === '<',
      dashed: plain[2].includes('.'),
      label: plain[4] !== undefined ? cleanLabel(plain[4]) || undefined : undefined,
      thick: plain[2].startsWith('=')
    }
  }
}

function skipWs(s: string, i: number): number {
  while (i < s.length && /\s/.test(s[i])) {
    i += 1
  }

  return i
}

/** `A & B` at pos; registers / updates the nodes it names. */
function readGroup(s: string, pos: number, nodes: Map<string, FlowNode>): { end: number; ids: string[] } | null {
  const ids: string[] = []
  let i = pos

  for (;;) {
    i = skipWs(s, i)
    const n = readNode(s, i)

    if (!n) {
      return ids.length ? { end: i, ids } : null
    }

    const prev = nodes.get(n.node.id)

    if (!prev) {
      nodes.set(n.node.id, { id: n.node.id, label: n.node.label || n.node.id, shape: n.node.shape ?? 'box' })
    } else if (n.node.label !== undefined || n.node.shape) {
      nodes.set(n.node.id, { id: n.node.id, label: n.node.label ?? prev.label, shape: n.node.shape ?? prev.shape })
    }

    ids.push(n.node.id)
    i = skipWs(s, n.end)

    if (s[i] === '&') {
      i += 1

      continue
    }

    return { end: i, ids }
  }
}

const FLOW_IGNORED = /^(classDef|class|style|linkStyle|click|direction|accTitle|accDescr)\b/

function parseFlowchart(lines: string[], title?: string): MermaidConversion {
  const head = lines[0].trim()
  const dir = (/^(?:flowchart|graph)(?:\s+(TB|TD|BT|RL|LR))?/i.exec(head)?.[1] ?? 'TD').toUpperCase()
  const nodes = new Map<string, FlowNode>()
  const links: FlowLink[] = []
  const highlighted = new Set<string>()
  let caption: string | undefined

  // The header may carry a first statement after ";" (graph TD;A-->B).
  const statements = [head.replace(/^(?:flowchart(?:-elk)?|graph)(?:\s+(TB|TD|BT|RL|LR))?\s*;?/i, ''), ...lines.slice(1)]
    .flatMap(l => l.split(/;(?=(?:[^"]*"[^"]*")*[^"]*$)/))
    .map(l => l.trim())
    .filter(Boolean)

  for (const st of statements) {
    if (/^(subgraph|end)\b/.test(st)) {
      throw new Unsupported('subgraph')
    }

    const at = /^accTitle\s*:\s*(.+)$/.exec(st)

    if (at) {
      title = title ?? cleanLabel(at[1])

      continue
    }

    const ad = /^accDescr\s*:\s*(.+)$/.exec(st)

    if (ad) {
      caption = cleanLabel(ad[1])

      continue
    }

    // `class A,B hot` / `style A fill:…`: a styled node is one the author wanted to stand out.
    const cls = /^class\s+([\w,\s]+?)\s+[\w-]+\s*$/.exec(st)

    if (cls) {
      cls[1].split(',').forEach(id => highlighted.add(id.trim()))

      continue
    }

    const sty = /^style\s+([\w-]+)\s+(.+)$/.exec(st)

    if (sty) {
      if (/fill\s*:/.test(sty[2])) {
        highlighted.add(sty[1])
      }

      continue
    }

    if (FLOW_IGNORED.test(st)) {
      continue
    }

    let g = readGroup(st, 0, nodes)

    if (!g) {
      throw new Unsupported(`statement: ${st}`)
    }

    let i = g.end

    while (i < st.length) {
      const l = readLink(st, i)

      if (!l) {
        throw new Unsupported(`link: ${st.slice(i)}`)
      }

      const next = readGroup(st, l.end, nodes)

      if (!next) {
        throw new Unsupported(`target: ${st}`)
      }

      for (const from of g.ids) {
        for (const to of next.ids) {
          links.push({ ...l.link, from, to })
        }
      }

      g = next
      i = skipWs(st, next.end)
    }

    if (nodes.size > MAX_NODES) {
      throw new Unsupported('too many nodes')
    }
  }

  if (!nodes.size) {
    throw new Unsupported('empty')
  }

  // Inline `A:::hot` classes.
  for (const st of statements) {
    for (const m of st.matchAll(/([\p{L}\p{N}_][\p{L}\p{N}_.-]*)(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\})?:::[\w-]+/gu)) {
      highlighted.add(m[1])
    }
  }

  const list = [...nodes.values()]
  // Highlight only when the author singled out a few nodes; "style everything" means nothing stands out.
  const hl = (id: string) => highlighted.has(id) && highlighted.size <= 4

  // Undirected links between short (letter-like) nodes = a graph-theory picture.
  const undirected = links.length > 0 && links.every(l => !l.arrow)

  if (undirected && list.every(n => n.label.length <= 3 && n.shape !== 'decision')) {
    return {
      family: 'graph',
      spec: {
        caption,
        directed: false,
        edges: links.map(l => ({ dashed: l.dashed, from: l.from, label: l.label, to: l.to })),
        nodes: list.map(n => ({ highlight: hl(n.id) || undefined, id: n.id, label: n.label })),
        title,
        type: 'graph'
      }
    }
  }

  const incoming = new Set(links.map(l => l.to))
  const outgoing = new Set(links.map(l => l.from))

  const steps = list.map(n => {
    let shape = 'box'

    if (n.shape === 'decision') {
      shape = 'decision'
    } else if (n.shape === 'round' || n.shape === 'circle') {
      shape = !incoming.has(n.id) ? 'start' : !outgoing.has(n.id) ? 'end' : n.shape === 'circle' ? 'pill' : 'box'
    }

    return { highlight: hl(n.id) || undefined, id: n.id, label: n.label, shape }
  })

  return {
    family: 'flowchart',
    spec: {
      caption,
      direction: dir === 'LR' || dir === 'RL' ? 'right' : 'down',
      edges: links.map(l => ({
        arrow: l.arrow ? undefined : false,
        dashed: l.dashed || undefined,
        from: l.from,
        highlight: l.thick || undefined,
        label: l.label,
        to: l.to
      })),
      steps,
      title,
      type: 'flow'
    }
  }
}

// ----------------------------------------------------------------- sequence --

const SEQ_ARROW = /^(.+?)\s*(<<-->>|<<->>|-->>|->>|--x|-x|--\)|-\)|-->|->)\s*([+-])?\s*(.+?)\s*(?::\s*(.*))?$/

function parseSequence(lines: string[], title?: string): MermaidConversion {
  const participants: Json[] = []
  const known = new Map<string, Json>()
  const messages: Json[] = []
  let autonumber = false
  let depth = 0
  let caption: string | undefined

  const ensure = (id: string, label?: string, actor = false) => {
    const key = unquote(id.trim())
    const prev = known.get(key)

    if (prev) {
      if (label) {
        prev.label = label
      }

      return key
    }

    const p: Json = { actor: actor || undefined, id: key, label: label ?? key }
    known.set(key, p)
    participants.push(p)

    return key
  }

  for (const raw of lines.slice(1)) {
    const st = raw.trim()
    let m: RegExpExecArray | null

    if ((m = /^title\s*:?\s*(.+)$/i.exec(st))) {
      title = cleanLabel(m[1])
    } else if ((m = /^accTitle\s*:\s*(.+)$/.exec(st))) {
      title = title ?? cleanLabel(m[1])
    } else if ((m = /^accDescr\s*:\s*(.+)$/.exec(st))) {
      caption = cleanLabel(m[1])
    } else if (/^autonumber\b/.test(st)) {
      autonumber = true
    } else if ((m = /^(?:create\s+)?(participant|actor)\s+(.+?)(?:\s+as\s+(.+))?$/.exec(st))) {
      ensure(m[2], m[3] ? cleanLabel(m[3]) : undefined, m[1] === 'actor')
    } else if (/^(box|rect)\b/.test(st)) {
      // Coloured lanes / backgrounds: no visual equivalent, only their `end` matters.
      depth += 1
      messages.push({ ignore: true })
    } else if (/^(destroy|activate|deactivate|links?|properties|details)\b/.test(st)) {
      continue
    } else if ((m = /^note\s+(left of|right of|over)\s+([^:]+):\s*(.*)$/i.exec(st))) {
      const where = m[1].toLowerCase()
      const over = m[2].split(',').map(x => ensure(x))
      messages.push({ note: cleanLabel(m[3]), over, side: where.startsWith('left') ? 'left' : where.startsWith('right') ? 'right' : undefined })
    } else if ((m = /^(loop|alt|opt|par|critical|break)\b\s*(.*)$/.exec(st))) {
      depth += 1
      messages.push({ group: m[1], label: cleanLabel(m[2]) })
    } else if ((m = /^(else|and|option)\b\s*(.*)$/.exec(st))) {
      messages.push({ else: cleanLabel(m[2]) || ' ' })
    } else if (/^end\b/.test(st)) {
      if (depth <= 0) {
        throw new Unsupported('end without block')
      }

      depth -= 1
      messages.push({ end: true })
    } else if ((m = SEQ_ARROW.exec(st))) {
      const op = m[2]
      const from = ensure(m[1])
      const to = ensure(m[4])
      messages.push({
        cross: op.includes('x') || undefined,
        dashed: op.startsWith('--') || op.startsWith('<<--') || undefined,
        from,
        label: cleanLabel(m[5] ?? ''),
        open: op === '->' || op === '-->' || undefined,
        to,
        two: op.startsWith('<<') || undefined
      })
    } else {
      throw new Unsupported(`sequence: ${st}`)
    }

    if (messages.length > MAX_MESSAGES || participants.length > 10) {
      throw new Unsupported('too large')
    }
  }

  // Drop box/rect markers and their matching ends.
  const cleaned: Json[] = []
  const stack: boolean[] = []

  for (const msg of messages) {
    if (msg.ignore) {
      stack.push(true)
    } else if (msg.group) {
      stack.push(false)
      cleaned.push(msg)
    } else if (msg.end) {
      if (!stack.pop()) {
        cleaned.push(msg)
      }
    } else {
      cleaned.push(msg)
    }
  }

  if (!participants.length) {
    throw new Unsupported('no participants')
  }

  return { family: 'sequence', spec: { autonumber: autonumber || undefined, caption, messages: cleaned, participants, title, type: 'sequence' } }
}

// ----------------------------------------------------------------- timeline --

function parseTimeline(lines: string[], title?: string): MermaidConversion {
  const events: Json[] = []
  let section: string | undefined
  let sectionUsed = false

  for (const raw of lines.slice(1)) {
    const st = raw.trim()
    let m: RegExpExecArray | null

    if ((m = /^title\s+(.+)$/i.exec(st))) {
      title = cleanLabel(m[1])

      continue
    }

    if ((m = /^section\s+(.+)$/i.exec(st))) {
      section = cleanLabel(m[1])
      sectionUsed = false

      continue
    }

    if (/^(accTitle|accDescr)\b/.test(st)) {
      continue
    }

    const parts = st.split(/\s*:\s*/)

    if (st.startsWith(':')) {
      const last = events[events.length - 1]

      if (!last) {
        throw new Unsupported('timeline continuation')
      }

      last.note = [last.note, ...parts.slice(1).map(cleanLabel).filter(Boolean)].filter(Boolean).join(' · ')

      continue
    }

    const date = cleanLabel(parts[0])
    const items = parts.slice(1).map(cleanLabel).filter(Boolean)
    const notes = items.slice(1)

    // The first period of a mermaid section carries the section name as its note.
    if (section && !sectionUsed) {
      notes.unshift(section)
    }

    sectionUsed = true
    events.push(
      items.length ? { date, label: items[0], note: notes.join(' · ') || undefined } : { date: '', label: date, note: notes.join(' · ') || undefined }
    )
  }

  if (!events.length || events.length > MAX_EVENTS) {
    throw new Unsupported('timeline size')
  }

  return { family: 'timeline', spec: { events, title, type: 'timeline' } }
}

// ---------------------------------------------------------------------- pie --

function parsePie(lines: string[], title?: string): MermaidConversion {
  const ht = /^pie(?:\s+showData)?(?:\s+title\s+(.+))?$/i.exec(lines[0].trim())

  if (!ht) {
    throw new Unsupported('pie header')
  }

  if (ht[1]) {
    title = cleanLabel(ht[1])
  }

  const data: { label: string; value: number }[] = []

  for (const raw of lines.slice(1)) {
    const st = raw.trim()
    let m: RegExpExecArray | null

    if ((m = /^title\s+(.+)$/i.exec(st))) {
      title = cleanLabel(m[1])
    } else if ((m = /^("[^"]*"|'[^']*'|[^:]+?)\s*:\s*(-?[\d.]+)\s*$/.exec(st))) {
      data.push({ label: cleanLabel(m[1]), value: Number.parseFloat(m[2]) })
    } else if (!/^(showData|accTitle|accDescr)\b/.test(st)) {
      throw new Unsupported(`pie: ${st}`)
    }
  }

  const total = data.reduce((s, d) => s + Math.max(0, d.value), 0)

  if (!data.length || !(total > 0)) {
    throw new Unsupported('pie empty')
  }

  const top = Math.max(...data.map(d => d.value))

  return {
    family: 'pie',
    spec: {
      data: data.map(d => {
        const pct = (d.value / total) * 100
        const shown = pct >= 10 || Number.isInteger(pct) ? Math.round(pct) : Math.round(pct * 10) / 10

        return { display: `${shown}%`, highlight: d.value === top || undefined, label: d.label, note: String(d.value), value: d.value }
      }),
      sort: 'desc',
      title,
      type: 'bar'
    }
  }
}

// -------------------------------------------------------------------- state --

function parseState(lines: string[], title?: string): MermaidConversion {
  const nodes = new Map<string, { id: string; label: string; shape: string }>()
  const edges: Json[] = []
  let starts = 0
  let ends = 0
  let caption: string | undefined

  const node = (raw: string, role: 'from' | 'to') => {
    const id = raw.trim()

    if (id === '[*]') {
      const key = role === 'from' ? `__start${++starts}` : `__end${++ends}`
      nodes.set(key, { id: key, label: role === 'from' ? '●' : '◉', shape: role === 'from' ? 'start' : 'end' })

      return key
    }

    if (!nodes.has(id)) {
      nodes.set(id, { id, label: id, shape: 'box' })
    }

    return id
  }

  for (const raw of lines.slice(1)) {
    const st = raw.trim()
    let m: RegExpExecArray | null

    if (/[{}]/.test(st) || /^(--|note|end note)\b/.test(st)) {
      throw new Unsupported('composite state / notes')
    }

    if ((m = /^title\s*:?\s*(.+)$/i.exec(st))) {
      title = cleanLabel(m[1])
    } else if ((m = /^accDescr\s*:\s*(.+)$/.exec(st))) {
      caption = cleanLabel(m[1])
    } else if (/^(direction|classDef|class|accTitle|hide)\b/.test(st)) {
      continue
    } else if ((m = /^state\s+"([^"]+)"\s+as\s+(\S+)$/.exec(st))) {
      nodes.set(m[2], { id: m[2], label: cleanLabel(m[1]), shape: nodes.get(m[2])?.shape ?? 'box' })
    } else if ((m = /^state\s+(\S+)\s+<<(choice|fork|join)>>$/.exec(st))) {
      nodes.set(m[1], { id: m[1], label: m[2] === 'choice' ? '?' : m[1], shape: m[2] === 'choice' ? 'decision' : 'box' })
    } else if ((m = /^(\S+)\s*-->\s*(\S+?)(?:\s*:\s*(.+))?$/.exec(st))) {
      const from = node(m[1].replace(/:::[\w-]+$/, ''), 'from')
      const to = node(m[2].replace(/:::[\w-]+$/, ''), 'to')
      edges.push({ from, label: m[3] ? cleanLabel(m[3]) : undefined, to })
    } else if ((m = /^(\S+)\s*:\s*(.+)$/.exec(st))) {
      nodes.set(m[1], { id: m[1], label: cleanLabel(m[2]), shape: nodes.get(m[1])?.shape ?? 'box' })
    } else if ((m = /^state\s+(\S+)$/.exec(st)) || (m = /^([\p{L}\p{N}_]+)$/u.exec(st))) {
      node(m[1], 'to')
    } else {
      throw new Unsupported(`state: ${st}`)
    }

    if (nodes.size > MAX_NODES) {
      throw new Unsupported('too many states')
    }
  }

  if (!nodes.size) {
    throw new Unsupported('empty')
  }

  return { family: 'state', spec: { caption, direction: 'down', edges, steps: [...nodes.values()], title, type: 'flow' } }
}

// ----------------------------------------------------------------- dispatch --

/**
 * Convert mermaid source to a ```visual spec, or null when the diagram type or
 * some of its syntax is not supported (the caller then keeps the classic
 * mermaid rendering, so nothing is ever lost).
 */
export function mermaidToVisual(code: string): MermaidConversion | null {
  if (!code || code.length > 40_000 || looksLikeVisualBody(code)) {
    return null
  }

  const { lines, title } = preprocess(code)

  if (!lines.length) {
    return null
  }

  const family = (/^([A-Za-z][\w-]*)/.exec(lines[0].trim())?.[1] ?? '').toLowerCase()

  try {
    switch (family) {
      case 'flowchart':

      case 'flowchart-elk':

      case 'graph':
        return parseFlowchart(lines, title)

      case 'sequencediagram':
        return parseSequence(lines, title)

      case 'timeline':
        return parseTimeline(lines, title)

      case 'pie':
        return parsePie(lines, title)

      case 'statediagram':

      case 'statediagram-v2':
        return parseState(lines, title)

      default:
        return null
    }
  } catch (error) {
    if (error instanceof Unsupported) {
      return null
    }

    throw error
  }
}

/** Best-effort title of a mermaid block that is still streaming. */
export function mermaidPartialTitle(code: string): string | undefined {
  const text = String(code ?? '').replace(/\r\n?/g, '\n')
  const fm = /^\s*---\n[\s\S]*?^\s*title\s*:\s*(.+)$/m.exec(text)

  if (fm) {
    return unquote(fm[1].trim())
  }

  const line = /^\s*(?:title|accTitle\s*:)\s*:?\s*(.+)$/m.exec(text)

  if (line) {
    return cleanLabel(line[1])
  }

  const pie = /^\s*pie\b.*\btitle\s+(.+)$/m.exec(text)

  return pie ? cleanLabel(pie[1]) : undefined
}
