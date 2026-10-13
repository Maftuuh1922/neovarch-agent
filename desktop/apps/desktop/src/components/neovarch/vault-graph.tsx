import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum
} from 'd3-force'
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'

/** Obsidian-style graph view for the Neovarch vault: a live force-directed layout
 *  (d3-force, ISC licence, already a desktop dependency) drawn on a canvas, with link
 *  lines, drag / zoom / pan, hover highlighting of a note's neighbours, labels that fade
 *  in as you zoom, a local graph around one note, filters (search, tag, project,
 *  orphans, unresolved links, node kinds) and colour groups. Works without the
 *  Obsidian app; the same colour groups are written to .obsidian/graph.json. */

export type NodeKind = 'file' | 'hub' | 'memory' | 'note' | 'project' | 'session' | 'unresolved'

export interface GraphNodeIn {
  degree: number
  exists: boolean
  folder?: string
  id: string
  kind?: string
  project?: null | string
  tags?: string[]
  title: string
}

export interface GraphIn {
  edges: { source: string; target: string }[]
  nodes: GraphNodeIn[]
}

export const NODE_KINDS: NodeKind[] = ['project', 'session', 'file', 'memory', 'hub', 'note', 'unresolved']

export const KIND_LABELS: Record<NodeKind, string> = {
  file: 'Berkas',
  hub: 'Hub',
  memory: 'Memori',
  note: 'Catatan',
  project: 'Proyek',
  session: 'Sesi',
  unresolved: 'Belum ada'
}

/** Colour groups — the same colours Neovarch writes to .obsidian/graph.json. `null` =
 *  the theme's text colour (plain notes) or faint (unresolved links). */
export const KIND_COLORS: Record<NodeKind, null | string> = {
  file: '#46a758',
  hub: '#a78bfa',
  memory: '#f5a524',
  note: null,
  project: '#e5484d',
  session: '#3e9bf7',
  unresolved: null
}

export function kindOf(n: GraphNodeIn): NodeKind {
  if (!n.exists) {
    return 'unresolved'
  }

  return (NODE_KINDS as string[]).includes(n.kind ?? '') ? (n.kind as NodeKind) : 'note'
}

export interface GraphFilters {
  hiddenKinds: NodeKind[]
  orphans: boolean
  project: null | string
  query: string
  tag: null | string
  unresolved: boolean
}

export const DEFAULT_FILTERS: GraphFilters = {
  hiddenKinds: [],
  orphans: true,
  project: null,
  query: '',
  tag: null,
  unresolved: true
}

export function graphTags(g: GraphIn): string[] {
  const s = new Set<string>()

  for (const n of g.nodes) {
    for (const t of n.tags ?? []) {
      s.add(t)
    }
  }

  return [...s].sort((a, b) => a.localeCompare(b))
}

export function graphProjects(g: GraphIn): string[] {
  const s = new Set<string>()

  for (const n of g.nodes) {
    if (n.project) {
      s.add(n.project)
    }
  }

  return [...s].sort((a, b) => a.localeCompare(b))
}

/** Undirected neighbour sets. */
export function adjacency(g: GraphIn): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>()

  for (const n of g.nodes) {
    adj.set(n.id, new Set())
  }

  for (const e of g.edges) {
    if (e.source === e.target) {
      continue
    }

    adj.get(e.source)?.add(e.target)
    adj.get(e.target)?.add(e.source)
  }

  return adj
}

function hasTag(n: GraphNodeIn, tag: string) {
  return (n.tags ?? []).some(t => t === tag || t.startsWith(tag + '/'))
}

/** Apply the filter panel. Edges are kept only between visible nodes. A node is an orphan
 *  when it has no links at all in the full graph (Obsidian's definition). */
export function filterGraph(g: GraphIn, f: GraphFilters): GraphIn {
  const adj = adjacency(g)
  const q = f.query.trim().toLowerCase()
  const hidden = new Set(f.hiddenKinds)

  const keep = g.nodes.filter(n => {
    const kind = kindOf(n)

    if (hidden.has(kind)) {
      return false
    }

    if (!f.unresolved && kind === 'unresolved') {
      return false
    }

    if (!f.orphans && (adj.get(n.id)?.size ?? 0) === 0) {
      return false
    }

    if (f.tag && !hasTag(n, f.tag)) {
      return false
    }

    if (f.project && n.project !== f.project && !(kind === 'project' && n.title === f.project)) {
      return false
    }

    if (q && !n.title.toLowerCase().includes(q) && !n.id.toLowerCase().includes(q)) {
      return false
    }

    return true
  })

  const ids = new Set(keep.map(n => n.id))

  return { edges: g.edges.filter(e => ids.has(e.source) && ids.has(e.target)), nodes: keep }
}

/** Obsidian's local graph: the note plus everything within `depth` links (both directions). */
export function localGraph(g: GraphIn, center: string, depth = 1): GraphIn {
  const adj = adjacency(g)

  if (!adj.has(center)) {
    return { edges: [], nodes: [] }
  }

  const seen = new Set([center])
  let frontier = [center]

  for (let d = 0; d < depth; d++) {
    const next: string[] = []

    for (const id of frontier) {
      for (const nb of adj.get(id) ?? []) {
        if (!seen.has(nb)) {
          seen.add(nb)
          next.push(nb)
        }
      }
    }

    frontier = next
  }

  return {
    edges: g.edges.filter(e => seen.has(e.source) && seen.has(e.target)),
    nodes: g.nodes.filter(n => seen.has(n.id))
  }
}

export function nodeRadius(degree: number) {
  return 3.2 + Math.sqrt(Math.max(degree, 0)) * 1.7
}

/** Label opacity like Obsidian: labels fade in as you zoom in; well-linked notes show
 *  their label earlier; the hovered note and its neighbours always show theirs. */
export function labelAlpha(scale: number, degree: number, highlighted: boolean) {
  if (highlighted) {
    return 1
  }

  const start = 1.05 - Math.min(degree, 24) * 0.025 // 1.05 (leaf) … 0.45 (hub)

  return Math.max(0, Math.min(1, (scale - start) / 0.35))
}

export interface View {
  k: number
  x: number
  y: number
}

/** Zoom by `factor` keeping the world point under (px, py) fixed on screen. */
export function zoomAt(v: View, px: number, py: number, factor: number, min = 0.08, max = 6): View {
  const k = Math.max(min, Math.min(max, v.k * factor))
  const f = k / v.k

  return { k, x: px - (px - v.x) * f, y: py - (py - v.y) * f }
}

/** A view that fits all points (world coords) into a w×h viewport with padding. */
export function fitView(points: { x: number; y: number }[], w: number, h: number, pad = 40): View {
  if (!points.length || w <= 0 || h <= 0) {
    return { k: 1, x: w / 2, y: h / 2 }
  }

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity

  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }

  const bw = Math.max(maxX - minX, 1)
  const bh = Math.max(maxY - minY, 1)
  const k = Math.max(0.08, Math.min(2.2, Math.min((w - pad * 2) / bw, (h - pad * 2) / bh)))

  return { k, x: w / 2 - ((minX + maxX) / 2) * k, y: h / 2 - ((minY + maxY) / 2) * k }
}

interface SimNode extends SimulationNodeDatum {
  color: null | string
  degree: number
  exists: boolean
  id: string
  kind: NodeKind
  r: number
  title: string
}

type SimLink = SimulationLinkDatum<SimNode> & { source: SimNode | string; target: SimNode | string }

function endpoint(v: SimNode | string | number | undefined): SimNode | null {
  return v && typeof v === 'object' ? v : null
}

/** Build (or rebuild) the simulation. Nodes that were already on screen keep their spot. */
export function buildSimulation(g: GraphIn, prev?: Map<string, { x: number; y: number }>) {
  const degree = new Map<string, number>()

  for (const e of g.edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }

  const n = g.nodes.length
  const spread = Math.sqrt(Math.max(n, 1)) * 18

  const nodes: SimNode[] = g.nodes.map((node, i) => {
    const kind = kindOf(node)
    const d = degree.get(node.id) ?? 0
    const old = prev?.get(node.id)
    // phyllotaxis seed: deterministic, round, no corner pile-up
    const a = i * 2.399963
    const rr = spread * Math.sqrt((i + 0.5) / Math.max(n, 1))

    return {
      color: KIND_COLORS[kind],
      degree: d,
      exists: node.exists,
      id: node.id,
      kind,
      r: nodeRadius(d),
      title: node.title,
      x: old?.x ?? Math.cos(a) * rr,
      y: old?.y ?? Math.sin(a) * rr
    }
  })

  const ids = new Set(nodes.map(x => x.id))
  const links: SimLink[] = g.edges.filter(e => ids.has(e.source) && ids.has(e.target)).map(e => ({ ...e }))

  const sim: Simulation<SimNode, SimLink> = forceSimulation<SimNode, SimLink>(nodes)
    .force(
      'link',
      forceLink<SimNode, SimLink>(links)
        .id(d => d.id)
        .distance(46)
        .strength(0.55)
    )
    .force('charge', forceManyBody<SimNode>().strength(-90).distanceMax(520))
    // Obsidian's "centre force": a gentle pull keeps unlinked notes near the cluster
    .force('x', forceX<SimNode>(0).strength(0.045))
    .force('y', forceY<SimNode>(0).strength(0.045))
    .force(
      'collide',
      forceCollide<SimNode>(d => d.r + 3)
    )
    .alphaDecay(0.028)
    .velocityDecay(0.38)

  sim.stop() // the component ticks it from requestAnimationFrame

  return { links, nodes, sim }
}

interface Palette {
  accent: string
  bg: string
  faint: string
  line: string
  text: string
}

function readPalette(el: HTMLElement | null): Palette {
  const css = el ? getComputedStyle(el) : null
  const v = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback

  return {
    accent: v('--nv-red', '#e5484d'),
    bg: v('--nv-ink-2', '#111'),
    faint: v('--nv-text-3', '#777'),
    line: v('--nv-line', 'rgba(127,127,127,0.35)'),
    text: v('--nv-text-2', '#ccc')
  }
}

export interface VaultForceGraphProps {
  compact?: boolean
  graph: GraphIn
  onOpen: (path: string) => void
  selected?: null | string
}

export function VaultForceGraph({ compact = false, graph, onOpen, selected }: VaultForceGraphProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [size, setSize] = useState({ h: compact ? 220 : 520, w: 760 })
  const viewRef = useRef<View>({ k: 1, x: 380, y: 260 })
  const fittedRef = useRef(false)
  const hoverRef = useRef<null | string>(null)
  const [hover, setHover] = useState<null | string>(null)
  const dragRef = useRef<null | { moved: boolean; node: null | SimNode; sx: number; sy: number; vx: number; vy: number }>(
    null
  )
  const posRef = useRef(new Map<string, { x: number; y: number }>())
  const frameRef = useRef(0)
  const dirtyRef = useRef(true)

  const built = useMemo(() => buildSimulation(graph, posRef.current), [graph])
  const adj = useMemo(() => adjacency(graph), [graph])

  useEffect(() => {
    fittedRef.current = false
    built.sim.alpha(1)
    dirtyRef.current = true

    return () => {
      for (const n of built.nodes) {
        if (n.x != null && n.y != null) {
          posRef.current.set(n.id, { x: n.x, y: n.y })
        }
      }

      built.sim.stop()
    }
  }, [built])

  // follow the container size
  useEffect(() => {
    const el = wrapRef.current

    if (!el || typeof ResizeObserver === 'undefined') {
      return
    }

    const ro = new ResizeObserver(entries => {
      const r = entries[0]?.contentRect

      if (r && r.width > 0 && r.height > 0) {
        setSize({ h: Math.round(r.height), w: Math.round(r.width) })
        dirtyRef.current = true
      }
    })

    ro.observe(el)

    return () => ro.disconnect()
  }, [])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext?.('2d')

    if (!canvas || !ctx) {
      return
    }

    const dpr = window.devicePixelRatio || 1
    const { h, w } = size

    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
    }

    const pal = readPalette(wrapRef.current)
    const v = viewRef.current
    const focus = hoverRef.current ?? selected ?? null
    const near = focus ? (adj.get(focus) ?? new Set<string>()) : null
    const lit = (id: string) => !focus || id === focus || near!.has(id)

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.setTransform(dpr * v.k, 0, 0, dpr * v.k, dpr * v.x, dpr * v.y)

    // links
    ctx.lineWidth = Math.max(0.6, 1 / v.k)

    for (const l of built.links) {
      const a = endpoint(l.source)
      const b = endpoint(l.target)

      if (!a || !b || a.x == null || b.x == null) {
        continue
      }

      const hot = !!focus && (a.id === focus || b.id === focus)
      ctx.globalAlpha = focus ? (hot ? 0.95 : 0.08) : 0.55
      ctx.strokeStyle = hot ? pal.accent : pal.line
      ctx.beginPath()
      ctx.moveTo(a.x, a.y!)
      ctx.lineTo(b.x, b.y!)
      ctx.stroke()
    }

    // nodes
    for (const n of built.nodes) {
      if (n.x == null || n.y == null) {
        continue
      }

      const on = lit(n.id)
      ctx.globalAlpha = on ? 1 : 0.18
      ctx.fillStyle = n.id === focus ? pal.accent : (n.color ?? (n.exists ? pal.text : pal.faint))
      ctx.beginPath()
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
      ctx.fill()

      if (!n.exists) {
        ctx.strokeStyle = pal.faint
        ctx.lineWidth = 1 / v.k
        ctx.stroke()
      }

      if (n.id === selected) {
        ctx.strokeStyle = pal.text
        ctx.lineWidth = 2 / v.k
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.r + 3 / v.k, 0, Math.PI * 2)
        ctx.stroke()
      }
    }

    // labels (screen-size text, fade with zoom)
    const fontPx = 11.5 / v.k
    ctx.font = `${fontPx}px Inter, system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'

    for (const n of built.nodes) {
      if (n.x == null || n.y == null) {
        continue
      }

      const highlighted = !!focus && lit(n.id)
      const alpha = labelAlpha(v.k * (compact ? 1.35 : 1), n.degree, highlighted) * (lit(n.id) ? 1 : 0.15)

      if (alpha <= 0.02) {
        continue
      }

      ctx.globalAlpha = alpha
      ctx.fillStyle = pal.text
      const label = n.title.length > 42 ? n.title.slice(0, 41) + '…' : n.title
      ctx.fillText(label, n.x, n.y + n.r + 3 / v.k)
    }

    ctx.globalAlpha = 1
  }, [adj, built, compact, selected, size])

  // animation loop: tick the simulation while it is warm, redraw when something changed
  useEffect(() => {
    let alive = true

    const loop = () => {
      if (!alive) {
        return
      }

      const sim = built.sim

      if (sim.alpha() > sim.alphaMin()) {
        sim.tick()
        dirtyRef.current = true

        if (!fittedRef.current && (sim.alpha() < 0.25 || built.nodes.length < 3)) {
          viewRef.current = fitView(built.nodes as { x: number; y: number }[], size.w, size.h, compact ? 18 : 48)
          fittedRef.current = true
        }
      }

      if (dirtyRef.current) {
        dirtyRef.current = false
        draw()
      }

      frameRef.current = requestAnimationFrame(loop)
    }

    if (typeof requestAnimationFrame === 'function') {
      frameRef.current = requestAnimationFrame(loop)
    }

    return () => {
      alive = false

      if (typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(frameRef.current)
      }
    }
  }, [built, compact, draw, size])

  useEffect(() => {
    dirtyRef.current = true
  }, [hover, selected])

  const toWorld = (px: number, py: number) => {
    const v = viewRef.current

    return { x: (px - v.x) / v.k, y: (py - v.y) / v.k }
  }

  const hit = (px: number, py: number): null | SimNode => {
    const p = toWorld(px, py)
    let best: null | SimNode = null
    let bestD = Infinity

    for (const n of built.nodes) {
      if (n.x == null || n.y == null) {
        continue
      }

      const d = Math.hypot(n.x - p.x, n.y - p.y)
      const reach = n.r + 6 / viewRef.current.k

      if (d < reach && d < bestD) {
        best = n
        bestD = d
      }
    }

    return best
  }

  const local = (e: { clientX: number; clientY: number }) => {
    const r = canvasRef.current!.getBoundingClientRect()

    return { px: e.clientX - r.left, py: e.clientY - r.top }
  }

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const { px, py } = local(e)
    const node = hit(px, py)
    e.currentTarget.setPointerCapture?.(e.pointerId)
    dragRef.current = { moved: false, node, sx: px, sy: py, vx: viewRef.current.x, vy: viewRef.current.y }

    if (node) {
      node.fx = node.x
      node.fy = node.y
      built.sim.alphaTarget(0.25).alpha(Math.max(built.sim.alpha(), 0.3))
    }
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const { px, py } = local(e)
    const d = dragRef.current

    if (d) {
      if (Math.hypot(px - d.sx, py - d.sy) > 3) {
        d.moved = true
      }

      if (d.node) {
        const p = toWorld(px, py)
        d.node.fx = p.x
        d.node.fy = p.y
      } else {
        viewRef.current = { ...viewRef.current, x: d.vx + (px - d.sx), y: d.vy + (py - d.sy) }
      }

      dirtyRef.current = true

      return
    }

    const id = hit(px, py)?.id ?? null

    if (id !== hoverRef.current) {
      hoverRef.current = id
      setHover(id)
    }
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current
    dragRef.current = null
    e.currentTarget.releasePointerCapture?.(e.pointerId)

    if (d?.node) {
      d.node.fx = null
      d.node.fy = null
      built.sim.alphaTarget(0)

      if (!d.moved && d.node.exists) {
        onOpen(d.node.id)
      }
    }
  }

  // wheel = zoom around the cursor; a native non-passive listener so the page does not scroll
  useEffect(() => {
    const canvas = canvasRef.current

    if (!canvas) {
      return
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = canvas.getBoundingClientRect()
      viewRef.current = zoomAt(viewRef.current, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015))
      dirtyRef.current = true
    }

    canvas.addEventListener('wheel', onWheel, { passive: false })

    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  const onLeave = () => {
    if (hoverRef.current) {
      hoverRef.current = null
      setHover(null)
    }
  }

  const recenter = () => {
    viewRef.current = fitView(built.nodes as { x: number; y: number }[], size.w, size.h, compact ? 18 : 48)
    dirtyRef.current = true
  }

  const hovered = hover ? built.nodes.find(n => n.id === hover) : null

  return (
    <div
      className={compact ? 'nv-vault-graph nv-vault-graph-compact' : 'nv-vault-graph'}
      data-nv-vault-graph={graph.nodes.length}
      data-nv-vault-edges={graph.edges.length}
      ref={wrapRef}
    >
      <canvas
        aria-label={`Graf vault: ${graph.nodes.length} catatan, ${graph.edges.length} tautan`}
        onPointerDown={onPointerDown}
        onPointerLeave={onLeave}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        ref={canvasRef}
        role="img"
        style={{ cursor: hovered ? 'pointer' : 'grab', height: size.h, width: size.w }}
      />
      <div className="nv-vault-graph-hud">
        {hovered && (
          <span className="nv-vault-graph-hover">
            {hovered.title} · {KIND_LABELS[hovered.kind]} · {adj.get(hovered.id)?.size ?? 0} tautan
          </span>
        )}
        <button className="nv-vault-graph-fit" onClick={recenter} title="Pusatkan graf" type="button">
          ⤢
        </button>
      </div>
    </div>
  )
}
