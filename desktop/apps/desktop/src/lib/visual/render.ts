// Declarative ```visual specs → crisp, self-contained SVG.
//
// Pure string building (no DOM), so the same code runs in the desktop
// renderer, the Android WebView bundle and node tests. Colours are CSS
// variables (`--nv-*`, see theme.ts) so one SVG follows light/dark themes; an
// export prepends concrete values to make it standalone.

import { esc, r, textBlock, textWidth, wrapText } from './text'

export interface RenderedSvg {
  height: number
  svg: string
  width: number
}

interface Box {
  body: string
  h: number
  w: number
}

interface Ctx {
  /** Width (px) the box should fit in, when the host knows it (phone column, chat pane). */
  avail?: number
  depth: number
  id: string
  markers: Map<string, string>
}

type Json = Record<string, unknown>

const PALETTE = new Set(['blue', 'green', 'red', 'amber', 'purple', 'teal', 'pink', 'accent'])

/** CSS colour for a palette name or a literal hex; undefined for anything else. */
export function colorOf(name: unknown): string | undefined {
  if (typeof name !== 'string') {
    return undefined
  }

  const key = name.trim().toLowerCase()

  if (key === 'good' || key === 'ok') {
    return 'var(--nv-green)'
  }

  if (key === 'bad' || key === 'error') {
    return 'var(--nv-red)'
  }

  if (key === 'gray' || key === 'grey' || key === 'muted') {
    return 'var(--nv-muted)'
  }

  if (PALETTE.has(key)) {
    return `var(--nv-${key})`
  }

  return /^#[0-9a-f]{3,8}$/i.test(key) ? key : undefined
}

function str(value: unknown, fallback = ''): string {
  if (typeof value === 'string') {
    return value
  }

  return typeof value === 'number' && Number.isFinite(value) ? String(value) : fallback
}

function num(value: unknown): number | undefined {
  const n = typeof value === 'string' ? Number.parseFloat(value) : typeof value === 'number' ? value : Number.NaN

  return Number.isFinite(n) ? n : undefined
}

function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function obj(value: unknown): Json {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
}

function truthy(value: unknown): boolean {
  return value === true || value === 'true' || value === 1
}

function marker(ctx: Ctx, color: string): string {
  const existing = ctx.markers.get(color)

  if (existing) {
    return existing
  }

  const id = `${ctx.id}-m${ctx.markers.size}`
  ctx.markers.set(color, id)

  return id
}

function markerDefs(ctx: Ctx): string {
  return [...ctx.markers.entries()]
    .map(
      ([color, id]) =>
        `<marker id="${id}" viewBox="0 0 10 10" refX="8.6" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0.6,0.8 L9.2,5 L0.6,9.2 z" style="fill:${color}"/></marker>`
    )
    .join('')
}

function edgeLabel(x: number, y: number, label: string): string {
  const lines = wrapText(label, 11.5, 120, 2)
  const w = Math.max(...lines.map(l => textWidth(l, 11.5))) + 10
  const h = lines.length * 14 + 6

  return `<rect x="${r(x - w / 2)}" y="${r(y - h / 2)}" width="${r(w)}" height="${r(h)}" rx="4" class="nv-lbg"/>${textBlock(lines, x, y, { className: 'nv-m', lineHeight: 14, size: 11.5 })}`
}

// ------------------------------------------------------------------ graph ---

interface GNode {
  color?: string
  fx?: number
  fy?: number
  h: number
  highlight: boolean
  id: string
  lines: string[]
  round: boolean
  sub?: string
  w: number
  x: number
  y: number
}

interface GEdge {
  /** false = a plain line without an arrowhead (flow only). */
  arrow?: boolean
  color?: string
  dashed: boolean
  from: string
  highlight: boolean
  label?: string
  to: string
}

function readNodes(raw: unknown[], size: number): GNode[] {
  const seen = new Set<string>()
  const out: GNode[] = []

  for (const item of raw) {
    const o = typeof item === 'string' || typeof item === 'number' ? { id: String(item) } : obj(item)
    const id = str(o.id ?? o.name ?? o.label)

    if (!id || seen.has(id)) {
      continue
    }

    seen.add(id)
    const label = str(o.label, id)
    const round = (o.shape === 'circle' || [...label].length <= 3) && o.shape !== 'box'
    const lines = round ? [label] : wrapText(label, 13, 130, 3)
    const w = round ? size * 2 : Math.max(56, Math.max(...lines.map(l => textWidth(l, 13, true))) + 24)
    const h = round ? size * 2 : lines.length * 16 + 14

    out.push({
      color: colorOf(o.color),
      fx: num(o.x),
      fy: num(o.y),
      h,
      highlight: truthy(o.highlight) || truthy(o.important),
      id,
      lines,
      round,
      sub: str(o.sub ?? o.note) || undefined,
      w,
      x: 0,
      y: 0
    })
  }

  return out
}

export function readEdges(raw: unknown[], ids: Set<string>): GEdge[] {
  const out: GEdge[] = []

  for (const item of raw) {
    let e: GEdge | null = null

    if (Array.isArray(item)) {
      e = { dashed: false, from: str(item[0]), highlight: false, label: str(item[2]) || undefined, to: str(item[1]) }
    } else if (typeof item === 'string') {
      const m = /^\s*(.+?)\s*(?:->|--|→)\s*(.+?)\s*$/.exec(item)

      if (m) {
        e = { dashed: false, from: m[1], highlight: false, to: m[2] }
      }
    } else {
      const o = obj(item)
      e = {
        arrow: o.arrow === false || o.arrow === 'false' ? false : undefined,
        color: colorOf(o.color),
        dashed: truthy(o.dashed),
        from: str(o.from ?? o.source),
        highlight: truthy(o.highlight),
        label: str(o.label) || undefined,
        to: str(o.to ?? o.target)
      }
    }

    if (e && ids.has(e.from) && ids.has(e.to)) {
      out.push(e)
    }
  }

  return out
}

function neighbours(nodes: GNode[], edges: GEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>(nodes.map(n => [n.id, new Set<string>()]))

  for (const e of edges) {
    if (e.from !== e.to) {
      adj.get(e.from)?.add(e.to)
      adj.get(e.to)?.add(e.from)
    }
  }

  return adj
}

function findHub(nodes: GNode[], edges: GEdge[], explicit?: string): GNode | undefined {
  if (explicit) {
    return nodes.find(n => n.id === explicit)
  }

  if (nodes.length < 4) {
    return undefined
  }

  const adj = neighbours(nodes, edges)
  const hub = nodes.find(n => (adj.get(n.id)?.size ?? 0) === nodes.length - 1)

  if (!hub) {
    return undefined
  }

  // A real star: no edges between leaves.
  return edges.some(e => e.from !== hub.id && e.to !== hub.id && e.from !== e.to) ? undefined : hub
}

function isTree(nodes: GNode[], edges: GEdge[]): boolean {
  const unique = new Set(edges.filter(e => e.from !== e.to).map(e => [e.from, e.to].sort().join('\u0000')))

  if (unique.size !== nodes.length - 1 || nodes.length < 2) {
    return false
  }

  const adj = neighbours(nodes, edges)
  const seen = new Set<string>([nodes[0].id])
  const queue = [nodes[0].id]

  while (queue.length) {
    for (const next of adj.get(queue.shift()!) ?? []) {
      if (!seen.has(next)) {
        seen.add(next)
        queue.push(next)
      }
    }
  }

  return seen.size === nodes.length
}

function layoutCircle(nodes: GNode[], L: number, startAngle = -Math.PI / 2) {
  const n = nodes.length
  const R = n <= 1 ? 0 : Math.max(L * 0.75, (n * L) / (2 * Math.PI))

  nodes.forEach((node, i) => {
    const a = startAngle + (2 * Math.PI * i) / n
    node.x = R * Math.cos(a)
    node.y = R * Math.sin(a)
  })
}

function layoutLayered(nodes: GNode[], edges: GEdge[], directed: boolean, L: number, root?: string) {
  const byId = new Map(nodes.map(n => [n.id, n]))
  const rank = new Map<string, number>()
  const children = new Map<string, string[]>(nodes.map(n => [n.id, []]))
  const indeg = new Map(nodes.map(n => [n.id, 0]))

  if (directed) {
    for (const e of edges) {
      if (e.from !== e.to) {
        children.get(e.from)?.push(e.to)
        indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1)
      }
    }
  } else {
    for (const [k, v] of neighbours(nodes, edges)) {
      children.set(k, [...v])
    }
  }

  const starts = root && byId.has(root) ? [root] : directed ? nodes.filter(n => !indeg.get(n.id)).map(n => n.id) : [nodes[0].id]

  for (const start of [...starts, ...nodes.map(n => n.id)]) {
    if (rank.has(start)) {
      continue
    }

    rank.set(start, 0)
    const queue = [start]

    while (queue.length) {
      const cur = queue.shift()!

      for (const next of children.get(cur) ?? []) {
        if (!rank.has(next)) {
          rank.set(next, (rank.get(cur) ?? 0) + 1)
          queue.push(next)
        }
      }
    }
  }

  const levels: GNode[][] = []

  for (const n of nodes) {
    ;(levels[rank.get(n.id) ?? 0] ||= []).push(n)
  }

  const colW = Math.max(...nodes.map(n => n.w)) + 26
  const rowH = Math.max(L * 0.95, Math.max(...nodes.map(n => n.h)) + 34)

  levels.forEach((level, k) => {
    if (!level) {
      return
    }

    if (k > 0) {
      // Barycentre ordering under the parents keeps edges from crossing.
      const center = (n: GNode) => {
        const xs = edges
          .filter(e => e.from !== e.to && (e.to === n.id || (!directed && e.from === n.id)))
          .map(e => byId.get(e.to === n.id ? e.from : e.to)!)
          .filter(p => (rank.get(p.id) ?? 0) < k)
          .map(p => p.x)

        return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
      }

      level.sort((a, b) => center(a) - center(b))
    }

    const width = (level.length - 1) * colW
    level.forEach((n, i) => {
      n.x = i * colW - width / 2
      n.y = k * rowH
    })
  })
}

function layoutForce(nodes: GNode[], edges: GEdge[], L: number) {
  layoutCircle(nodes, L)
  const index = new Map(nodes.map((n, i) => [n.id, i]))
  let temp = L * 1.2

  for (let iter = 0; iter < 320; iter++) {
    const disp = nodes.map(() => ({ x: 0, y: 0 }))

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[i].x - nodes[j].x
        let dy = nodes[i].y - nodes[j].y
        let d = Math.hypot(dx, dy)

        if (d < 0.01) {
          dx = 0.01 * (i + 1)
          dy = 0.01
          d = Math.hypot(dx, dy)
        }

        const f = (L * L) / d
        disp[i].x += (dx / d) * f
        disp[i].y += (dy / d) * f
        disp[j].x -= (dx / d) * f
        disp[j].y -= (dy / d) * f
      }
    }

    for (const e of edges) {
      const a = index.get(e.from)!
      const b = index.get(e.to)!

      if (a === b) {
        continue
      }

      const dx = nodes[a].x - nodes[b].x
      const dy = nodes[a].y - nodes[b].y
      const d = Math.max(0.01, Math.hypot(dx, dy))
      const f = (d * d) / L
      disp[a].x -= (dx / d) * f
      disp[a].y -= (dy / d) * f
      disp[b].x += (dx / d) * f
      disp[b].y += (dy / d) * f
    }

    nodes.forEach((n, i) => {
      // Weak gravity keeps disconnected parts together.
      disp[i].x -= n.x * 0.04
      disp[i].y -= n.y * 0.04
      const d = Math.max(0.01, Math.hypot(disp[i].x, disp[i].y))
      n.x += (disp[i].x / d) * Math.min(d, temp)
      n.y += (disp[i].y / d) * Math.min(d, temp)
    })

    temp = Math.max(0.5, temp * 0.975)
  }
}

/** Point on the node's outline in the direction of (tx, ty). */
function anchor(n: GNode, tx: number, ty: number, pad = 0): { x: number; y: number } {
  const dx = tx - n.x
  const dy = ty - n.y
  const d = Math.hypot(dx, dy) || 1

  if (n.round) {
    const rad = n.w / 2 + pad

    return { x: n.x + (dx / d) * rad, y: n.y + (dy / d) * rad }
  }

  const hw = n.w / 2 + pad
  const hh = n.h / 2 + pad
  const s = Math.min(dx ? hw / Math.abs(dx) : Number.POSITIVE_INFINITY, dy ? hh / Math.abs(dy) : Number.POSITIVE_INFINITY)

  return { x: n.x + dx * s, y: n.y + dy * s }
}

function fillStyle(color: string | undefined, strong: boolean): string {
  if (!color) {
    return ''
  }

  return strong ? `fill:${color};stroke:${color}` : `fill:${color};fill-opacity:.16;stroke:${color}`
}

function nodeSvg(n: GNode): string {
  const strong = n.highlight
  const color = n.color ?? (strong ? 'var(--nv-blue)' : undefined)

  const shape = (cls: string, style: string) =>
    n.round
      ? `<circle cx="${r(n.x)}" cy="${r(n.y)}" r="${r(n.w / 2)}" class="${cls}"${style ? ` style="${style}"` : ''}/>`
      : `<rect x="${r(n.x - n.w / 2)}" y="${r(n.y - n.h / 2)}" width="${r(n.w)}" height="${r(n.h)}" rx="9" class="${cls}"${style ? ` style="${style}"` : ''}/>`

  // Solid base first so edges never show through a tinted fill.
  const parts = [shape('nv-node', '')]

  if (color) {
    parts.push(shape('nv-fillnode', fillStyle(color, strong)))
  }

  parts.push(textBlock(n.lines, n.x, n.y, { className: color && strong ? 'nv-on nv-b' : 'nv-t nv-b', lineHeight: 16, size: n.round ? 14 : 13 }))

  if (n.sub) {
    parts.push(
      textBlock(wrapText(n.sub, 11.5, 120, 2), n.x, n.y + n.h / 2 + 6, { baseline: 'top', className: 'nv-m', lineHeight: 14, size: 11.5 })
    )
  }

  return `<g class="nv-n${strong ? ' nv-hl' : ''}">${parts.join('')}</g>`
}

function renderGraph(spec: Json, ctx: Ctx): Box {
  const small = ctx.depth > 0
  const size = num(spec.nodeSize) ?? (small ? 17 : 19)
  const nodes = readNodes(arr(spec.nodes), size)

  if (!nodes.length) {
    throw new Error('graph: nodes is empty')
  }

  const ids = new Set(nodes.map(n => n.id))
  const directed = truthy(spec.directed)
  const hl = new Set(nodes.filter(n => n.highlight).map(n => n.id))
  // highlightEdges: light every edge whose two ends are highlighted.
  const edges = readEdges(arr(spec.edges ?? spec.links), ids).map(e => ({
    ...e,
    highlight: e.highlight || (truthy(spec.highlightEdges) && hl.has(e.from) && hl.has(e.to))
  }))
  const maxDim = Math.max(...nodes.map(n => Math.max(n.w, n.h)))
  const L = num(spec.spacing) ?? Math.max(small ? 60 : 74, maxDim + (small ? 28 : 38))
  const layout = str(spec.layout, 'auto').toLowerCase()

  if (nodes.every(n => n.fx !== undefined && n.fy !== undefined)) {
    const maxCoord = Math.max(...nodes.map(n => Math.max(Math.abs(n.fx!), Math.abs(n.fy!))))
    const scale = maxCoord <= 1.0001 ? L * Math.max(2, Math.sqrt(nodes.length) * 1.4) : 1

    for (const n of nodes) {
      n.x = n.fx! * scale
      n.y = n.fy! * scale
    }
  } else if (layout === 'circle' || layout === 'ring') {
    layoutCircle(nodes, L)
  } else if (layout === 'grid') {
    const cols = Math.ceil(Math.sqrt(nodes.length))
    nodes.forEach((n, i) => {
      n.x = (i % cols) * L
      n.y = Math.floor(i / cols) * L
    })
  } else if (layout === 'line' || layout === 'path' || layout === 'row') {
    nodes.forEach((n, i) => {
      n.x = i * L
      n.y = 0
    })
  } else if (layout === 'tree' || layout === 'layered' || layout === 'hierarchy') {
    layoutLayered(nodes, edges, directed, L, str(spec.root) || undefined)
  } else if (layout === 'force') {
    layoutForce(nodes, edges, L)
  } else {
    const hub = layout === 'star' || layout === 'auto' ? findHub(nodes, edges, str(spec.hub ?? spec.center) || undefined) : undefined

    if (hub) {
      const rest = nodes.filter(n => n !== hub)
      const R = Math.max(L, (rest.length * (maxDim + 22)) / (2 * Math.PI))
      rest.forEach((n, i) => {
        const a = -Math.PI / 2 + (2 * Math.PI * i) / rest.length
        n.x = R * Math.cos(a)
        n.y = R * Math.sin(a)
      })
      hub.x = 0
      hub.y = 0
    } else if (layout === 'star' || (nodes.length <= 6 && !isTree(nodes, edges))) {
      layoutCircle(nodes, L)
    } else if (isTree(nodes, edges)) {
      layoutLayered(nodes, edges, directed, L, str(spec.root) || undefined)
    } else {
      layoutForce(nodes, edges, L)
    }
  }

  // Bounds (with sub-labels and self loops) → translate to a padded origin.
  const pad = 6
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY

  for (const n of nodes) {
    const subLines = n.sub ? wrapText(n.sub, 11.5, 120, 2) : []
    const subW = subLines.length ? Math.max(...subLines.map(l => textWidth(l, 11.5))) / 2 : 0
    minX = Math.min(minX, n.x - Math.max(n.w / 2, subW))
    maxX = Math.max(maxX, n.x + Math.max(n.w / 2, subW))
    minY = Math.min(minY, n.y - n.h / 2)
    maxY = Math.max(maxY, n.y + n.h / 2 + (subLines.length ? subLines.length * 14 + 8 : 0))
  }

  for (const e of edges) {
    if (e.from === e.to) {
      const n = nodes.find(x => x.id === e.from)!
      minY = Math.min(minY, n.y - n.h / 2 - (e.label ? 40 : 30))
    }
  }

  for (const n of nodes) {
    n.x += pad - minX
    n.y += pad - minY
  }

  const byId = new Map(nodes.map(n => [n.id, n]))
  const pairCount = new Map<string, number>()
  const pairKey = (e: GEdge) => [e.from, e.to].sort().join('\u0000')

  for (const e of edges) {
    pairCount.set(pairKey(e), (pairCount.get(pairKey(e)) ?? 0) + 1)
  }

  const plain: string[] = []
  const lit: string[] = []
  const labels: string[] = []

  for (const e of edges) {
    const a = byId.get(e.from)!
    const b = byId.get(e.to)!
    const color = e.color ?? (e.highlight ? 'var(--nv-blue)' : 'var(--nv-line)')
    const style = `stroke:${color};stroke-width:${e.highlight ? 2.4 : 1.6}${e.dashed ? ';stroke-dasharray:5 4' : ''}`
    const arrow = directed ? ` marker-end="url(#${marker(ctx, color)})"` : ''
    const into = e.highlight || e.color ? lit : plain

    if (a === b) {
      const top = a.y - a.h / 2
      into.push(
        `<path class="nv-edge" style="${style}" d="M${r(a.x - 7)},${r(top + 1)} C${r(a.x - 24)},${r(top - 32)} ${r(a.x + 24)},${r(top - 32)} ${r(a.x + 7)},${r(top + 1)}"${arrow}/>`
      )

      if (e.label) {
        labels.push(edgeLabel(a.x, top - 30, e.label))
      }

      continue
    }

    const start = anchor(a, b.x, b.y)
    const end = anchor(b, a.x, a.y, directed ? 1.5 : 0)

    if (directed && (pairCount.get(pairKey(e)) ?? 0) > 1) {
      const mx = (start.x + end.x) / 2
      const my = (start.y + end.y) / 2
      const d = Math.hypot(end.x - start.x, end.y - start.y) || 1
      const cx = mx + (-(end.y - start.y) / d) * 18
      const cy = my + ((end.x - start.x) / d) * 18
      into.push(`<path class="nv-edge" style="${style}" d="M${r(start.x)},${r(start.y)} Q${r(cx)},${r(cy)} ${r(end.x)},${r(end.y)}"${arrow}/>`)

      if (e.label) {
        labels.push(edgeLabel((mx + cx) / 2, (my + cy) / 2, e.label))
      }
    } else {
      into.push(`<line class="nv-edge" style="${style}" x1="${r(start.x)}" y1="${r(start.y)}" x2="${r(end.x)}" y2="${r(end.y)}"${arrow}/>`)

      if (e.label) {
        labels.push(edgeLabel((start.x + end.x) / 2, (start.y + end.y) / 2, e.label))
      }
    }
  }

  return {
    body: `<g class="nv-edges">${plain.join('')}${lit.join('')}</g>${labels.join('')}<g class="nv-nodes">${nodes.map(nodeSvg).join('')}</g>`,
    h: maxY - minY + pad * 2,
    w: maxX - minX + pad * 2
  }
}

// ------------------------------------------------------------------- flow ---

interface FNode {
  color?: string
  h: number
  highlight: boolean
  id: string
  lines: string[]
  note?: string
  shape: string
  w: number
  x: number
  y: number
}

function renderFlow(spec: Json, ctx: Ctx): Box {
  const right = /^(right|lr|horizontal|kanan)$/i.test(str(spec.direction))
  const nodes: FNode[] = []
  const seen = new Set<string>()

  arr(spec.steps ?? spec.nodes).forEach((item, i) => {
    const o = typeof item === 'string' ? { label: item } : obj(item)
    const id = str(o.id, `s${i + 1}`)

    if (seen.has(id)) {
      return
    }

    seen.add(id)
    const shape = str(o.shape, 'box').toLowerCase()
    const decision = shape === 'decision' || shape === 'diamond'
    const strong = truthy(o.highlight)
    const lines = wrapText(str(o.label ?? o.title, id), 13, decision ? 112 : right ? 130 : 190, 3, strong)
    const tw = Math.max(...lines.map(l => textWidth(l, 13, strong)))
    let w = Math.max(right ? 96 : 120, tw + 32)
    let h = lines.length * 17 + 20

    if (decision) {
      w = Math.max(128, tw * 1.55 + 34)
      h = Math.max(64, lines.length * 17 * 1.7 + 30)
    }

    nodes.push({ color: colorOf(o.color), h, highlight: strong, id, lines, note: str(o.note) || undefined, shape: decision ? 'decision' : shape, w, x: 0, y: 0 })
  })

  if (!nodes.length) {
    throw new Error('flow: steps is empty')
  }

  const ids = new Set(nodes.map(n => n.id))
  let edges = readEdges(arr(spec.edges ?? spec.links), ids)

  if (!edges.length) {
    edges = nodes.slice(1).map((n, i) => ({ dashed: false, from: nodes[i].id, highlight: false, to: n.id }))
  }

  // Ranks: longest path over the DAG left after dropping back edges.
  const order = new Map(nodes.map((n, i) => [n.id, i]))
  const back = new Set<GEdge>()
  const state = new Map<string, number>()
  const out = new Map<string, GEdge[]>(nodes.map(n => [n.id, []]))

  for (const e of edges) {
    out.get(e.from)!.push(e)
  }

  const visit = (id: string) => {
    state.set(id, 1)

    for (const e of out.get(id)!) {
      const s = state.get(e.to) ?? 0

      if (s === 1) {
        back.add(e)
      } else if (s === 0) {
        visit(e.to)
      }
    }

    state.set(id, 2)
  }

  for (const n of nodes) {
    if (!state.get(n.id)) {
      visit(n.id)
    }
  }

  const rank = new Map<string, number>(nodes.map(n => [n.id, 0]))

  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false

    for (const e of edges) {
      if (!back.has(e) && rank.get(e.to)! < rank.get(e.from)! + 1) {
        rank.set(e.to, rank.get(e.from)! + 1)
        changed = true
      }
    }

    if (!changed) {
      break
    }
  }

  const levels: FNode[][] = []

  for (const n of nodes) {
    ;(levels[rank.get(n.id)!] ||= []).push(n)
  }

  const gapMain = 44
  const gapCross = 30
  const mainOf = (n: FNode) => (right ? n.w : n.h)
  const crossOf = (n: FNode) => (right ? n.h : n.w)
  const levelCross = levels.map(l => (l ? l.reduce((s, n) => s + crossOf(n), 0) + gapCross * (l.length - 1) : 0))
  const maxCross = Math.max(...levelCross)
  const byId = new Map(nodes.map(n => [n.id, n]))
  let cursor = 0

  levels.forEach((level, k) => {
    if (!level) {
      return
    }

    level.sort((a, b) => order.get(a.id)! - order.get(b.id)!)
    const thick = Math.max(...level.map(mainOf))
    let c = (maxCross - levelCross[k]) / 2

    for (const n of level) {
      const main = cursor + thick / 2
      const cross = c + crossOf(n) / 2
      n.x = right ? main : cross
      n.y = right ? cross : main
      c += crossOf(n) + gapCross
    }

    cursor += thick + gapMain
  })

  const totalMain = cursor - gapMain
  let loop = 0
  const edgeSvg: string[] = []
  const labels: string[] = []

  for (const e of edges) {
    const a = byId.get(e.from)!
    const b = byId.get(e.to)!
    const color = e.color ?? (e.highlight ? 'var(--nv-blue)' : 'var(--nv-line)')
    const style = `stroke:${color};stroke-width:${e.highlight ? 2.2 : 1.6}${e.dashed ? ';stroke-dasharray:5 4' : ''}`
    const arrow = e.arrow === false ? '' : ` marker-end="url(#${marker(ctx, color)})"`

    if (back.has(e)) {
      // Loop back around the outside: right side of a vertical flow, below a horizontal one.
      const lane = maxCross + 22 + loop
      loop += 12

      if (right) {
        const sx = a.x
        const sy = a.y + a.h / 2
        const tx = b.x
        const ty = b.y + b.h / 2 + 2
        edgeSvg.push(
          `<path class="nv-edge" style="${style}" d="M${r(sx)},${r(sy)} V${r(lane - 8)} Q${r(sx)},${r(lane)} ${r(sx - 8)},${r(lane)} H${r(tx + 8)} Q${r(tx)},${r(lane)} ${r(tx)},${r(lane - 8)} V${r(ty)}"${arrow}/>`
        )

        if (e.label) {
          labels.push(edgeLabel((sx + tx) / 2, lane, e.label))
        }
      } else {
        const sx = a.x + a.w / 2
        const sy = a.y
        const tx = b.x + b.w / 2 + 2
        const ty = b.y
        edgeSvg.push(
          `<path class="nv-edge" style="${style}" d="M${r(sx)},${r(sy)} H${r(lane - 8)} Q${r(lane)},${r(sy)} ${r(lane)},${r(sy - 8)} V${r(ty + 8)} Q${r(lane)},${r(ty)} ${r(lane - 8)},${r(ty)} H${r(tx)}"${arrow}/>`
        )

        if (e.label) {
          labels.push(edgeLabel(lane, (sy + ty) / 2, e.label))
        }
      }

      continue
    }

    const sx = right ? a.x + a.w / 2 : a.x
    const sy = right ? a.y : a.y + a.h / 2
    const tx = right ? b.x - b.w / 2 - 2 : b.x
    const ty = right ? b.y : b.y - b.h / 2 - 2
    const straight = right ? Math.abs(sy - ty) < 1 : Math.abs(sx - tx) < 1

    const d = straight
      ? `M${r(sx)},${r(sy)} L${r(tx)},${r(ty)}`
      : right
        ? `M${r(sx)},${r(sy)} C${r((sx + tx) / 2)},${r(sy)} ${r((sx + tx) / 2)},${r(ty)} ${r(tx)},${r(ty)}`
        : `M${r(sx)},${r(sy)} C${r(sx)},${r((sy + ty) / 2)} ${r(tx)},${r((sy + ty) / 2)} ${r(tx)},${r(ty)}`

    edgeSvg.push(`<path class="nv-edge" style="${style}" d="${d}"${arrow}/>`)

    if (e.label) {
      labels.push(edgeLabel((sx + tx) / 2, (sy + ty) / 2, e.label))
    }
  }

  let noteExtra = 0

  const nodeParts = nodes.map(n => {
    const color = n.color ?? (n.highlight ? 'var(--nv-blue)' : undefined)
    const st = color ? ` style="${fillStyle(color, n.highlight)}"` : ''
    let base: string
    let tint = ''

    if (n.shape === 'decision') {
      const pts = `${r(n.x)},${r(n.y - n.h / 2)} ${r(n.x + n.w / 2)},${r(n.y)} ${r(n.x)},${r(n.y + n.h / 2)} ${r(n.x - n.w / 2)},${r(n.y)}`
      base = `<polygon points="${pts}" class="nv-node"/>`
      tint = color ? `<polygon points="${pts}" class="nv-fillnode"${st}/>` : ''
    } else {
      const pill = ['start', 'end', 'pill', 'terminal'].includes(n.shape)
      const attrs = `x="${r(n.x - n.w / 2)}" y="${r(n.y - n.h / 2)}" width="${r(n.w)}" height="${r(n.h)}" rx="${r(pill ? n.h / 2 : 9)}"`
      base = `<rect ${attrs} class="nv-node"/>`
      tint = color ? `<rect ${attrs} class="nv-fillnode"${st}/>` : ''
    }

    const text = textBlock(n.lines, n.x, n.y, { className: color && n.highlight ? 'nv-on nv-b' : 'nv-t', lineHeight: 17, size: 13 })
    let note = ''

    if (n.note) {
      const lines = wrapText(n.note, 11.5, right ? 130 : 150, 2)

      if (right) {
        note = textBlock(lines, n.x, n.y + n.h / 2 + 6, { baseline: 'top', className: 'nv-m', lineHeight: 14, size: 11.5 })
      } else {
        note = textBlock(lines, n.x + n.w / 2 + 10, n.y, { anchor: 'start', className: 'nv-m', lineHeight: 14, size: 11.5 })
        noteExtra = Math.max(noteExtra, n.x + n.w / 2 + 10 + Math.max(...lines.map(l => textWidth(l, 11.5))) - maxCross)
      }
    }

    return `<g class="nv-n${n.highlight ? ' nv-hl' : ''}">${base}${tint}${text}${note}</g>`
  })

  const pad = 6
  const loopRoom = loop ? 22 + loop + 4 : 0
  const w = (right ? totalMain : maxCross + Math.max(loopRoom, noteExtra + 4)) + pad * 2
  const h = (right ? maxCross + Math.max(loopRoom, nodes.some(n => n.note) ? 36 : 0) : totalMain) + pad * 2

  return {
    body: `<g transform="translate(${pad},${pad})"><g class="nv-edges">${edgeSvg.join('')}</g>${nodeParts.join('')}${labels.join('')}</g>`,
    h,
    w
  }
}

// -------------------------------------------------------------------- bar ---

function formatValue(value: number, spec: Json): string {
  const digits = Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : Math.abs(value) >= 10 ? 1 : 2
  const sep = str(spec.thousands, ',')
  const dec = sep === '.' ? ',' : '.'
  const [int, frac] = Math.abs(value).toFixed(digits).split('.')
  const fracTrim = frac ? frac.replace(/0+$/, '') : ''

  return `${value < 0 ? '−' : ''}${str(spec.prefix)}${int.replace(/\B(?=(\d{3})+(?!\d))/g, sep)}${fracTrim ? dec + fracTrim : ''}${str(spec.unit)}`
}

function renderBar(spec: Json, ctx: Ctx): Box {
  const items = arr(spec.data ?? spec.bars ?? spec.items).map((item, i) => {
    const o = obj(item)

    return {
      color: colorOf(o.color),
      display: str(o.display) || undefined,
      highlight: truthy(o.highlight),
      label: str(o.label ?? o.name, `#${i + 1}`),
      note: str(o.note) || undefined,
      value: num(o.value) ?? 0
    }
  })

  if (!items.length) {
    throw new Error('bar: data is empty')
  }

  if (spec.sort === 'desc') {
    items.sort((a, b) => b.value - a.value)
  } else if (spec.sort === 'asc') {
    items.sort((a, b) => a.value - b.value)
  }

  const vertical = /^(vertical|column|columns)$/i.test(str(spec.orientation ?? spec.direction))
  const maxV = Math.max(0, num(spec.max) ?? 0, ...items.map(i => i.value))
  const minV = Math.min(0, ...items.map(i => i.value))
  const span = maxV - minV || 1
  const valueText = items.map(i => i.display ?? formatValue(i.value, spec))

  const fill = (i: (typeof items)[number]) =>
    i.color ? `fill:${i.color}${i.highlight ? '' : ';fill-opacity:.7'}` : i.highlight ? 'fill:var(--nv-blue)' : 'fill:var(--nv-bar)'

  if (vertical) {
    const colW = Math.max(30, Math.min(52, 320 / items.length))
    const slot = colW + Math.max(22, colW * 0.7)
    const plotH = 170
    const labelLines = items.map(i => wrapText(i.label, 11.5, slot - 6, 2, i.highlight))
    const top = 22
    const zeroY = top + (maxV / span) * plotH
    const parts: string[] = []

    items.forEach((it, k) => {
      const cx = slot / 2 + k * slot
      const y1 = top + ((maxV - Math.max(it.value, 0)) / span) * plotH
      const y2 = top + ((maxV - Math.min(it.value, 0)) / span) * plotH
      parts.push(`<rect x="${r(cx - colW / 2)}" y="${r(y1)}" width="${r(colW)}" height="${r(Math.max(1.5, y2 - y1))}" rx="4" style="${fill(it)}"/>`)
      parts.push(textBlock([valueText[k]], cx, it.value >= 0 ? y1 - 9 : y2 + 11, { className: it.highlight ? 'nv-t nv-b' : 'nv-m', size: 11.5 }))
      parts.push(textBlock(labelLines[k], cx, top + plotH + 8, { baseline: 'top', className: it.highlight ? 'nv-t nv-b' : 'nv-t', lineHeight: 14, size: 11.5 }))
    })

    const w = items.length * slot
    const labelH = Math.max(...labelLines.map(l => l.length)) * 14 + 10

    return { body: `<line x1="0" x2="${r(w)}" y1="${r(zeroY)}" y2="${r(zeroY)}" class="nv-axis"/>${parts.join('')}`, h: top + plotH + labelH + 6, w }
  }

  const narrow = ctx.avail !== undefined && ctx.avail < 460
  const labelMax = narrow ? 104 : 150
  const labelLines = items.map(i => wrapText(i.label, 12.5, labelMax, 2, i.highlight))
  const labelW = Math.min(labelMax, Math.max(...labelLines.flat().map(l => textWidth(l, 12.5, true)))) + 4
  const valueW = Math.max(...valueText.map(v => textWidth(v, 12, true))) + 10
  const fitW = ctx.avail !== undefined ? ctx.avail - (labelW + 12) - valueW - 4 : 300
  const plotW = num(spec.width) ?? Math.max(110, Math.min(300, fitW))
  const negRoom = minV < 0 ? Math.max(...valueText.map(v => textWidth(v, 12))) + 8 : 0
  const x0 = labelW + 12 + negRoom
  const zeroX = x0 + (-minV / span) * plotW
  const parts: string[] = []
  let y = 4

  items.forEach((it, k) => {
    const rowH = Math.max(30, labelLines[k].length * 15 + 14) + (it.note ? 14 : 0)
    const barH = 16
    const cy = y + (it.note ? (rowH - 14) / 2 : rowH / 2)
    const xa = x0 + ((Math.min(it.value, 0) - minV) / span) * plotW
    const xb = x0 + ((Math.max(it.value, 0) - minV) / span) * plotW
    parts.push(textBlock(labelLines[k], labelW + negRoom, cy, { anchor: 'end', className: it.highlight ? 'nv-t nv-b' : 'nv-t', lineHeight: 15, size: 12.5 }))
    parts.push(`<rect x="${r(xa)}" y="${r(cy - barH / 2)}" width="${r(Math.max(1.5, xb - xa))}" height="${barH}" rx="4" style="${fill(it)}"/>`)
    parts.push(
      textBlock([valueText[k]], it.value < 0 ? xa - 6 : xb + 6, cy, {
        anchor: it.value < 0 ? 'end' : 'start',
        className: it.highlight ? 'nv-t nv-b' : 'nv-m',
        size: 12
      })
    )

    if (it.note) {
      parts.push(textBlock([it.note], x0, cy + barH / 2 + 3, { anchor: 'start', baseline: 'top', className: 'nv-m', size: 11 }))
    }

    y += rowH
  })

  return {
    body: `<line x1="${r(zeroX)}" x2="${r(zeroX)}" y1="0" y2="${r(y + 4)}" class="nv-axis"/>${parts.join('')}`,
    h: y + 8,
    w: x0 + plotW + valueW + 4
  }
}

// --------------------------------------------------------------- timeline ---

function renderTimeline(spec: Json, ctx: Ctx): Box {
  const events = arr(spec.events ?? spec.items ?? spec.steps).map(item => {
    const o = typeof item === 'string' ? { label: item } : obj(item)

    return {
      color: colorOf(o.color),
      date: str(o.date ?? o.time ?? o.when ?? o.year),
      highlight: truthy(o.highlight),
      label: str(o.label ?? o.title ?? o.event),
      note: str(o.note ?? o.detail) || undefined
    }
  })

  if (!events.length) {
    throw new Error('timeline: events is empty')
  }

  const forced = str(spec.direction ?? spec.orientation).toLowerCase()
  // Mendatar only when every event gets a readable slot in the space we have.
  const fits = ctx.avail === undefined || events.length * 132 <= ctx.avail
  const horizontal = forced ? /^(horizontal|right|row)$/.test(forced) : events.length <= 5 && fits
  const parts: string[] = []

  const dot = (x: number, y: number, e: (typeof events)[number]) => {
    const color = e.color ?? (e.highlight ? 'var(--nv-blue)' : undefined)

    if (!color) {
      return `<circle cx="${r(x)}" cy="${r(y)}" r="6" class="nv-node" style="stroke:var(--nv-line);stroke-width:2"/>`
    }

    const halo = e.highlight ? `<circle cx="${r(x)}" cy="${r(y)}" r="12" style="fill:none;stroke:${color};stroke-opacity:.35;stroke-width:2"/>` : ''

    return `${halo}<circle cx="${r(x)}" cy="${r(y)}" r="${e.highlight ? 7 : 6}" class="nv-node" style="fill:${color};stroke:${color}"/>`
  }

  if (horizontal) {
    const slot = Math.max(132, Math.min(176, 680 / events.length))
    const axisY = 40
    let bottom = axisY

    events.forEach((e, i) => {
      const x = slot / 2 + i * slot
      parts.push(textBlock([e.date], x, 14, { className: e.highlight ? 'nv-t nv-b' : 'nv-m nv-b', size: 12 }))
      const lines = wrapText(e.label, 13, slot - 18, 3, e.highlight)
      parts.push(textBlock(lines, x, axisY + 20, { baseline: 'top', className: e.highlight ? 'nv-t nv-b' : 'nv-t', lineHeight: 16, size: 13 }))
      let b = axisY + 20 + lines.length * 16 + 4

      if (e.note) {
        const nl = wrapText(e.note, 11.5, slot - 18, 3)
        parts.push(textBlock(nl, x, b, { baseline: 'top', className: 'nv-m', lineHeight: 14, size: 11.5 }))
        b += nl.length * 14
      }

      bottom = Math.max(bottom, b)
    })

    const w = slot * events.length
    const axis = `<line x1="${r(slot / 2 - 18)}" x2="${r(w - slot / 2 + 18)}" y1="${axisY}" y2="${axisY}" class="nv-axis" style="stroke-width:2"/>`

    return { body: axis + events.map((e, i) => dot(slot / 2 + i * slot, axisY, e)).join('') + parts.join(''), h: bottom + 6, w }
  }

  const dateW = Math.min(120, Math.max(...events.map(e => textWidth(e.date, 12, true)))) + 4
  const axisX = dateW + 18
  const textX = axisX + 18
  const textW = ctx.avail !== undefined ? Math.max(140, Math.min(320, ctx.avail - textX - 4)) : 320
  const dots: string[] = []
  let y = 8

  for (const e of events) {
    const lines = wrapText(e.label, 13, textW, 3, e.highlight)
    const nl = e.note ? wrapText(e.note, 11.5, textW, 3) : []
    const blockH = lines.length * 17 + (nl.length ? nl.length * 14 + 4 : 0)
    const cy = y + 9
    parts.push(textBlock(wrapText(e.date, 12, dateW, 2, true), dateW, cy, { anchor: 'end', className: e.highlight ? 'nv-t nv-b' : 'nv-m nv-b', lineHeight: 14, size: 12 }))
    parts.push(textBlock(lines, textX, y, { anchor: 'start', baseline: 'top', className: e.highlight ? 'nv-t nv-b' : 'nv-t', lineHeight: 17, size: 13 }))

    if (nl.length) {
      parts.push(textBlock(nl, textX, y + lines.length * 17 + 2, { anchor: 'start', baseline: 'top', className: 'nv-m', lineHeight: 14, size: 11.5 }))
    }

    dots.push(dot(axisX, cy, e))
    y += Math.max(26, blockH) + 16
  }

  const axis = `<line x1="${axisX}" x2="${axisX}" y1="4" y2="${r(y - 22)}" class="nv-axis" style="stroke-width:2"/>`

  return { body: axis + dots.join('') + parts.join(''), h: y - 6, w: textX + textW }
}

// --------------------------------------------------------------- sequence ---

interface SeqPart {
  actor: boolean
  color?: string
  highlight: boolean
  id: string
  lines: string[]
}

interface SeqGroup {
  depth: number
  elses: { label: string; y: number }[]
  kind: string
  label: string
  y0: number
}

function renderSequence(spec: Json, ctx: Ctx): Box {
  const parts: SeqPart[] = []
  const byId = new Map<string, number>()
  const msgs = arr(spec.messages ?? spec.steps ?? spec.items).map(obj)

  const add = (raw: unknown) => {
    const o = typeof raw === 'string' ? { id: raw } : obj(raw)
    const id = str(o.id ?? o.name ?? o.label)

    if (!id || byId.has(id)) {
      return
    }

    byId.set(id, parts.length)
    parts.push({ actor: truthy(o.actor), color: colorOf(o.color), highlight: truthy(o.highlight), id, lines: [str(o.label, id)] })
  }

  arr(spec.participants ?? spec.actors).forEach(add)

  for (const m of msgs) {
    if (m.from !== undefined) {
      add(str(m.from))
      add(str(m.to ?? m.from))
    }

    arr(m.over).forEach(add)
  }

  if (!parts.length) {
    throw new Error('sequence: participants is empty')
  }

  if (parts.length > 10) {
    throw new Error('sequence: at most 10 participants')
  }

  const n = parts.length
  const avail = ctx.avail ?? 680
  // Column per participant: as wide as the space allows, never so narrow a label can't sit between two lifelines.
  const col = Math.max(92, Math.min(180, Math.floor(avail / n)))
  const w0 = col * n
  const cx = (i: number) => col / 2 + i * col
  const headW = col - 14

  for (const p of parts) {
    p.lines = wrapText(p.lines[0], 12.5, headW - 14, 2, true)
  }

  const headH = Math.max(...parts.map(p => p.lines.length)) * 16 + 16
  const out: string[] = []
  // Group frames: panel + divider lines go under the lifelines, their labels on top (on a background chip).
  const frames: string[] = []
  const frameLabels: string[] = []
  const groups: SeqGroup[] = []
  let y = headH + 20
  let maxX = w0
  let num = 0
  const auto = truthy(spec.autonumber)
  const idx = (id: unknown) => byId.get(str(id)) ?? 0

  // Background behind a label so lifelines don't run through it; inside group frames
  // it repeats the frames' tint so it blends with the panel.
  const chip = (lines: string[], x: number, y: number, size: number, anchor: 'start' | 'middle', depth: number) => {
    const w = Math.max(...lines.map(l => textWidth(l, size))) + 8
    const h = lines.length * 15 + 2
    const x0 = anchor === 'start' ? x - 4 : x - w / 2
    const box = `x="${r(x0)}" y="${r(y - 1)}" width="${r(w)}" height="${r(h)}" rx="3"`

    return `<rect ${box} class="nv-lbg"/>` + `<rect ${box} style="fill:var(--nv-panel)"/>`.repeat(depth)
  }

  const frame = (g: SeqGroup, y1: number) => {
    const inset = 3 + g.depth * 6
    const x0 = inset
    const x1 = w0 - inset
    const tagW = textWidth(g.kind, 11, true) + 14
    frames.push(
      `<rect x="${r(x0)}" y="${r(g.y0)}" width="${r(x1 - x0)}" height="${r(y1 - g.y0)}" rx="8" class="nv-panel"/>` +
        g.elses
          .map(e => `<line x1="${r(x0)}" x2="${r(x1)}" y1="${r(e.y + 4)}" y2="${r(e.y + 4)}" class="nv-axis" style="stroke-dasharray:5 4"/>`)
          .join('')
    )
    const tagLines = [g.kind]
    const label = g.label ? wrapText(`[${g.label}]`, 11.5, x1 - x0 - tagW - 24, 1) : []
    const elseParts = g.elses.map(e => {
      const lines = e.label ? wrapText(`[${e.label}]`, 11.5, x1 - x0 - 20, 1) : []

      return lines.length ? chip(lines, x0 + 10, e.y + 8, 11.5, 'start', g.depth + 1) + textBlock(lines, x0 + 10, e.y + 15, { anchor: 'start', className: 'nv-m', size: 11.5 }) : ''
    })
    frameLabels.push(
      `<path d="M${r(x0 + 1)},${r(g.y0 + 8)} V${r(g.y0 + 20)} H${r(x0 + tagW)} L${r(x0 + tagW + 6)},${r(g.y0 + 14)} V${r(g.y0 + 1)} H${r(x0 + 8)} Z" class="nv-lbg"/>` +
        `<path d="M${r(x0 + 1)},${r(g.y0 + 8)} V${r(g.y0 + 20)} H${r(x0 + tagW)} L${r(x0 + tagW + 6)},${r(g.y0 + 14)} V${r(g.y0 + 1)} H${r(x0 + 8)} Z" style="fill:var(--nv-panel)"/>`.repeat(g.depth + 1) +
        `<path d="M${r(x0)},${r(g.y0 + 20)} H${r(x0 + tagW)} L${r(x0 + tagW + 6)},${r(g.y0 + 14)} V${r(g.y0)}" class="nv-edge" style="stroke:var(--nv-stroke);stroke-width:1"/>` +
        textBlock(tagLines, x0 + 7, g.y0 + 10, { anchor: 'start', className: 'nv-t nv-b', size: 11 }) +
        (label.length ? chip(label, x0 + tagW + 14, g.y0 + 3, 11.5, 'start', g.depth + 1) + textBlock(label, x0 + tagW + 14, g.y0 + 10, { anchor: 'start', className: 'nv-m', size: 11.5 }) : '') +
        elseParts.join('')
    )
  }

  for (const m of msgs) {
    if (m.group !== undefined) {
      groups.push({ depth: groups.length, elses: [], kind: str(m.group, 'loop'), label: str(m.label), y0: y })
      y += 30
      continue
    }

    if (m.else !== undefined) {
      const g = groups[groups.length - 1]

      if (g) {
        g.elses.push({ label: str(m.else).trim(), y })
        y += 26
      }

      continue
    }

    if (m.end !== undefined) {
      const g = groups.pop()

      if (g) {
        frame(g, y + 2)
        y += 14
      }

      continue
    }

    if (m.note !== undefined) {
      const over = arr(m.over).map(idx)
      const a = over.length ? Math.min(...over) : 0
      const b = over.length ? Math.max(...over) : a
      const side = str(m.side)
      let x0: number
      let x1: number

      if (side === 'left' || side === 'right') {
        const nw = Math.min(col - 10, 150)
        x0 = side === 'left' ? cx(a) - nw - 6 : cx(a) + 6
        x1 = x0 + nw

        if (x0 < 2) {
          x1 += 2 - x0
          x0 = 2
        }
      } else {
        x0 = cx(a) - Math.min(col / 2 - 6, 70)
        x1 = cx(b) + Math.min(col / 2 - 6, 70)
        // A note over one lifeline grows toward its text (up to ~two columns) so it isn't
        // squeezed into a few clipped lines; it stays inside the diagram.
        const want = Math.min(textWidth(str(m.note), 11.5) + 28, Math.max(col * 2 - 12, 240), w0 - 4)

        if (x1 - x0 < want) {
          const mid = (x0 + x1) / 2
          x0 = Math.max(2, Math.min(mid - want / 2, w0 - 2 - want))
          x1 = x0 + want
        }
      }

      const lines = wrapText(str(m.note), 11.5, x1 - x0 - 16, 4)
      const h = lines.length * 15 + 12
      out.push(
        `<rect x="${r(x0)}" y="${r(y)}" width="${r(x1 - x0)}" height="${r(h)}" rx="6" class="nv-lbg"/>` +
          `<rect x="${r(x0)}" y="${r(y)}" width="${r(x1 - x0)}" height="${r(h)}" rx="6" style="fill:var(--nv-panel)"/>`.repeat(groups.length) +
          `<rect x="${r(x0)}" y="${r(y)}" width="${r(x1 - x0)}" height="${r(h)}" rx="6" style="fill:var(--nv-amber);fill-opacity:.12;stroke:var(--nv-amber);stroke-opacity:.55;stroke-width:1"/>` +
          textBlock(lines, (x0 + x1) / 2, y + h / 2, { className: 'nv-t', lineHeight: 15, size: 11.5 })
      )
      maxX = Math.max(maxX, x1 + 2)
      y += h + 14
      continue
    }

    if (m.from === undefined) {
      continue
    }

    const fi = idx(m.from)
    const ti = idx(m.to ?? m.from)
    const hl = truthy(m.highlight)
    const color = colorOf(m.color) ?? (hl ? 'var(--nv-blue)' : 'var(--nv-line)')
    const style = `stroke:${color};stroke-width:${hl ? 2.1 : 1.5}${truthy(m.dashed) ? ';stroke-dasharray:5 4' : ''}`
    const head = truthy(m.open) ? '' : ` marker-end="url(#${marker(ctx, color)})"`
    const tail = truthy(m.two) ? ` marker-start="url(#${marker(ctx, color)})"` : ''
    num += 1
    const label = (auto ? `${num}. ` : '') + str(m.label)
    const cls = hl ? 'nv-t nv-b' : 'nv-t'

    if (fi === ti) {
      // Message to self: a small loop right of the lifeline, label beside it.
      const x = cx(fi)
      const loopW = 30
      const lw = Math.max(70, Math.min(170, col - 16))
      const lines = label ? wrapText(label, 12, lw, 3, hl) : []
      const textX = x + loopW + 14
      out.push(
        `<path class="nv-edge" style="${style}" d="M${r(x)},${r(y)} H${r(x + loopW)} Q${r(x + loopW + 6)},${r(y)} ${r(x + loopW + 6)},${r(y + 6)} V${r(y + 18)} Q${r(x + loopW + 6)},${r(y + 24)} ${r(x + loopW)},${r(y + 24)} H${r(x + 3)}"${head}/>`
      )

      if (lines.length) {
        const top = y + 12 - ((lines.length - 1) * 15) / 2 - 8
        out.push(chip(lines, textX, top, 12, 'start', groups.length) + textBlock(lines, textX, y + 12, { anchor: 'start', className: cls, lineHeight: 15, size: 12 }))
        maxX = Math.max(maxX, textX + Math.max(...lines.map(l => textWidth(l, 12, hl))) + 4)
      }

      y += Math.max(24, lines.length * 15) + 22
      continue
    }

    const x1 = cx(fi)
    const x2 = cx(ti)
    const lines = label ? wrapText(label, 12, Math.max(70, Math.abs(x2 - x1) - 14), 3, hl) : []
    const ly = y + lines.length * 15 + 6
    const dir = x2 > x1 ? 1 : -1

    if (lines.length) {
      out.push(chip(lines, (x1 + x2) / 2, y + 1, 12, 'middle', groups.length) + textBlock(lines, (x1 + x2) / 2, y, { baseline: 'top', className: cls, lineHeight: 15, size: 12 }))
    }

    out.push(`<path class="nv-edge" style="${style}" d="M${r(x1 + (tail ? dir * 3 : 0))},${r(ly)} L${r(x2 - dir * 3)},${r(ly)}"${head}${tail}/>`)

    if (truthy(m.cross)) {
      const xx = x2 - dir * 9
      out.push(
        `<path class="nv-edge" style="stroke:${color};stroke-width:1.8" d="M${r(xx - 4)},${r(ly - 4)} L${r(xx + 4)},${r(ly + 4)} M${r(xx - 4)},${r(ly + 4)} L${r(xx + 4)},${r(ly - 4)}"/>`
      )
    }

    y = ly + 20
  }

  // Unclosed groups (truncated source): close them at the bottom.
  while (groups.length) {
    frame(groups.pop()!, y)
    y += 8
  }

  const bottom = y - 4
  const heads: string[] = []
  const lifelines: string[] = []

  parts.forEach((p, i) => {
    const x = cx(i)
    const color = p.color ?? (p.highlight ? 'var(--nv-blue)' : undefined)
    const st = color ? ` style="${fillStyle(color, p.highlight)}"` : ''
    const tw = Math.max(...p.lines.map(l => textWidth(l, 12.5, true)))
    const bw = Math.min(headW, Math.max(64, tw + 22))
    const attrs = `x="${r(x - bw / 2)}" y="2" width="${r(bw)}" height="${r(headH - 4)}" rx="${p.actor ? r((headH - 4) / 2) : 9}"`
    lifelines.push(`<line x1="${r(x)}" x2="${r(x)}" y1="${headH - 2}" y2="${r(bottom)}" class="nv-axis" style="stroke-dasharray:4 4"/>`)
    heads.push(
      `<g class="nv-n${p.highlight ? ' nv-hl' : ''}"><rect ${attrs} class="nv-node"/>${color ? `<rect ${attrs} class="nv-fillnode"${st}/>` : ''}` +
        textBlock(p.lines, x, headH / 2, { className: color && p.highlight ? 'nv-on nv-b' : 'nv-t nv-b', lineHeight: 16, size: 12.5 }) +
        '</g>'
    )
  })

  return {
    body: frames.join('') + lifelines.join('') + heads.join('') + out.join('') + frameLabels.join(''),
    h: bottom + 2,
    w: Math.max(w0, maxX)
  }
}

// ---------------------------------------------------------------- compare ---

const GOOD = new Set(['good', 'ok', 'yes', 'true', 'benar', 'ya', 'pass', '✓'])
const BAD = new Set(['bad', 'no', 'false', 'salah', 'tidak', 'fail', '✗'])

function renderCompare(spec: Json, ctx: Ctx): Box {
  const panels = arr(spec.panels ?? spec.items)

  if (!panels.length) {
    throw new Error('compare: panels is empty')
  }

  const count = Math.min(4, panels.length)
  const gap = ctx.avail !== undefined && ctx.avail < 520 ? 10 : 16
  const inset = ctx.avail !== undefined && ctx.avail < 520 ? 12 : 18
  const innerAvail = ctx.avail !== undefined ? Math.max(140, (ctx.avail - gap * (Math.min(count, 2) - 1)) / Math.min(count, 2) - inset * 2) : undefined

  const rendered = panels.slice(0, 4).map(p => {
    const o = obj(p)
    const box = renderBox(obj(o.visual ?? o.spec), { ...ctx, avail: innerAvail, depth: ctx.depth + 1 })
    const verdict = str(o.verdict).toLowerCase()
    const s = Math.min(1, 230 / box.h, 300 / box.w)

    return {
      box,
      caption: str(o.caption),
      good: GOOD.has(verdict) ? true : BAD.has(verdict) ? false : undefined,
      h: box.h * s,
      s,
      title: str(o.title),
      w: box.w * s
    }
  })

  const minPanel = ctx.avail !== undefined && ctx.avail < 520 ? 150 : 200
  const rowWidth = (n: number) => rendered.slice(0, n).reduce((sum, p) => sum + Math.max(minPanel, p.w + inset * 2), 0) + gap * (n - 1)
  const limit = ctx.avail ?? 940
  let perRow = rendered.length === 4 || rowWidth(rendered.length) > limit ? 2 : rendered.length

  // On a narrow column, stack the panels when side by side would shrink them below ~85% (text under ~10px).
  if (ctx.avail !== undefined && perRow > 1 && ctx.avail / rowWidth(perRow) < 0.85) {
    perRow = 1
  }
  const parts: string[] = []
  let y = 0
  let maxW = 0

  for (let start = 0; start < rendered.length; start += perRow) {
    const row = rendered.slice(start, start + perRow)
    const panelW = Math.max(minPanel, ...row.map(p => p.w + inset * 2))
    const innerH = Math.max(...row.map(p => p.h))
    const titleH = row.some(p => p.title) ? 26 : 0
    // Wrap with the glyph included so the first line's width is right.
    const capLines = row.map(p => (p.caption ? wrapText(`${p.good === undefined ? '' : '✓ '}${p.caption}`, 13, panelW - inset * 2, 4) : []))
    const capH = Math.max(0, ...capLines.map(l => (l.length ? l.length * 17 + 12 : 0)))
    const panelH = inset + titleH + innerH + capH + inset
    let x = 0

    row.forEach((p, i) => {
      parts.push(`<rect x="${r(x + 0.5)}" y="${r(y + 0.5)}" width="${r(panelW - 1)}" height="${r(panelH - 1)}" rx="12" class="nv-panel"/>`)

      if (p.title) {
        parts.push(textBlock([p.title], x + panelW / 2, y + inset + 6, { className: 'nv-t nv-b', size: 13 }))
      }

      const gx = x + (panelW - p.w) / 2
      const gy = y + inset + titleH + (innerH - p.h) / 2
      parts.push(`<g transform="translate(${r(gx)},${r(gy)}) scale(${Math.round(p.s * 1000) / 1000})">${p.box.body}</g>`)

      if (p.caption) {
        const top = y + inset + titleH + innerH + 12
        const tx = x + panelW / 2

        const tspans = capLines[i]
          .map((line, k) => {
            let content = esc(line)

            if (k === 0 && p.good !== undefined) {
              const tone = p.good ? 'green' : 'red'
              content = `<tspan class="nv-b" style="fill:var(--nv-${tone})">${p.good ? '✓' : '✗'}</tspan>${esc(line.slice(1))}`
            }

            return `<tspan x="${r(tx)}" y="${r(top + 13 + k * 17)}">${content}</tspan>`
          })
          .join('')

        parts.push(`<text class="nv-t" font-size="13" text-anchor="middle">${tspans}</text>`)
      }

      x += panelW + gap
    })

    maxW = Math.max(maxW, x - gap)
    y += panelH + gap
  }

  return { body: parts.join(''), h: y - gap, w: maxW }
}

// --------------------------------------------------------------- dispatch ---

const ALIASES: Record<string, string> = {
  bars: 'bar',
  chart: 'bar',
  comparison: 'compare',
  flowchart: 'flow',
  network: 'graph',
  seq: 'sequence',
  sequencediagram: 'sequence',
  'side-by-side': 'compare',
  steps: 'flow',
  tree: 'graph',
  versus: 'compare',
  vs: 'compare'
}

export const SPEC_TYPES = ['graph', 'flow', 'bar', 'timeline', 'sequence', 'compare'] as const

function renderBox(spec: Json, ctx: Ctx): Box {
  const raw = str(spec.type).toLowerCase()
  const type = ALIASES[raw] ?? raw

  if (ctx.depth > 3) {
    throw new Error('compare: nested too deep')
  }

  switch (type) {
    case 'graph':
      return renderGraph(raw === 'tree' && !spec.layout ? { ...spec, layout: 'tree' } : spec, ctx)
    case 'flow':
      return renderFlow(spec, ctx)
    case 'bar':
      return renderBar(spec, ctx)
    case 'timeline':
      return renderTimeline(spec, ctx)
    case 'sequence':
      return renderSequence(spec, ctx)
    case 'compare':
      return renderCompare(spec, ctx)
    default:
      throw new Error(`unknown type "${raw || '?'}" (use ${SPEC_TYPES.join(' | ')})`)
  }
}

/** Stable short id so marker ids differ between visuals on one page. */
export function hashId(text: string): string {
  let h = 0x811c9dc5

  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }

  return `nv${(h >>> 0).toString(36)}`
}

export const SVG_STYLE =
  '.nv-t{fill:var(--nv-fg);font-family:var(--nv-font);font-weight:500}' +
  '.nv-m{fill:var(--nv-muted);font-family:var(--nv-font);font-weight:500}' +
  '.nv-b{font-weight:650}' +
  '.nv-on{fill:var(--nv-on);font-family:var(--nv-font)}' +
  '.nv-edge{fill:none;stroke:var(--nv-line);stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}' +
  '.nv-node{fill:var(--nv-surface);stroke:var(--nv-stroke);stroke-width:1.5}' +
  '.nv-fillnode{stroke-width:1.5}' +
  '.nv-axis{stroke:var(--nv-stroke);stroke-width:1.2}' +
  '.nv-lbg{fill:var(--nv-bg)}' +
  '.nv-panel{fill:var(--nv-panel);stroke:var(--nv-stroke);stroke-width:1}'

export function renderSpec(spec: Json, seed = '', opts: { width?: number } = {}): RenderedSvg {
  const pad = 8
  const avail = opts.width && opts.width > 0 ? Math.max(200, opts.width - pad * 2) : undefined
  const ctx: Ctx = { avail, depth: 0, id: hashId(seed || JSON.stringify(spec)), markers: new Map() }
  const box = renderBox(spec, ctx)
  const w = Math.ceil(box.w + pad * 2)
  const h = Math.ceil(box.h + pad * 2)
  const label = str(spec.title) || str(spec.type)

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}" class="nv-visual">` +
    `<style>${SVG_STYLE}</style><defs>${markerDefs(ctx)}</defs>` +
    `<g transform="translate(${pad},${pad})">${box.body}</g></svg>`

  return { height: h, svg, width: w }
}
