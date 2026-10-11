import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { hermesApi } from '@/api/client'
import { OBSIDIAN_VAULT_CHANGED_EVENT } from '@/app/settings/obsidian-vault-settings'
import { cn } from '@/lib/utils'

/** Neovarch's Obsidian vault viewer: file tree, rendered note with clickable
 *  wikilinks + backlinks, "Buka di Obsidian", and a node graph. Read-only —
 *  the agent writes notes through its tools; people edit them in Obsidian. */
export const VAULT_ROUTE = '/vault'

interface TreeNode {
  children?: TreeNode[]
  name: string
  path: string
  type: 'folder' | 'note'
}

interface TreeResponse {
  configured: boolean
  detail?: string
  path?: string
  tree: null | TreeNode
  vault?: string
}

interface NoteResponse {
  backlinks: { path: string; snippet: string; title: string }[]
  content: string
  open_uri: string
  outgoing: { path: null | string; target: string }[]
  path: string
  tags: string[]
  title: string
}

interface GraphResponse {
  configured: boolean
  edges: { source: string; target: string }[]
  nodes: { degree: number; exists: boolean; id: string; title: string }[]
}

const api = <T,>(path: string) => hermesApi<T>({ path })

/** Deep link to Settings ▸ Memori & Skill ▸ Vault Obsidian (the folder picker). */
export const VAULT_SETTINGS_ROUTE = '/settings?tab=obsidian'

function openExternal(uri: string) {
  void window.hermesDesktop?.openExternal?.(uri)
}

// ---- tiny Markdown renderer (no HTML injection; wikilinks become buttons) ----
function inline(text: string, onLink: (target: string) => void, key: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|([^\]]*))?\]\])|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[([^\]]+)\]\((https?:[^)\s]+)\))/g
  let last = 0
  let m: null | RegExpExecArray
  let i = 0

  while ((m = re.exec(text))) {
    if (m.index > last) {
      out.push(text.slice(last, m.index))
    }

    const k = `${key}-${i++}`

    if (m[1]) {
      const target = m[2]!.trim()
      out.push(
        <button className="nv-vault-wikilink" key={k} onClick={() => onLink(target)} type="button">
          {(m[3] || target).trim()}
        </button>
      )
    } else if (m[4]) {
      out.push(<code key={k}>{m[4].slice(1, -1)}</code>)
    } else if (m[5]) {
      out.push(<strong key={k}>{m[5].slice(2, -2)}</strong>)
    } else if (m[6]) {
      out.push(<em key={k}>{m[6].slice(1, -1)}</em>)
    } else if (m[7]) {
      const href = m[9]!
      out.push(
        <a href={href} key={k} onClick={e => (e.preventDefault(), openExternal(href))}>
          {m[8]}
        </a>
      )
    }

    last = m.index + m[0].length
  }

  if (last < text.length) {
    out.push(text.slice(last))
  }

  return out
}

export function VaultMarkdown({ source, onLink }: { onLink: (target: string) => void; source: string }) {
  const body = source.replace(/^---\n[\s\S]*?\n---\n?/, '')
  const lines = body.split('\n')
  const blocks: ReactNode[] = []
  let para: string[] = []
  let list: string[] = []
  let code: null | string[] = null

  const flush = () => {
    if (para.length) {
      blocks.push(<p key={`p${blocks.length}`}>{inline(para.join(' '), onLink, `p${blocks.length}`)}</p>)
      para = []
    }

    if (list.length) {
      blocks.push(
        <ul key={`l${blocks.length}`}>
          {list.map((item, j) => (
            <li key={j}>{inline(item, onLink, `l${blocks.length}-${j}`)}</li>
          ))}
        </ul>
      )
      list = []
    }
  }

  for (const line of lines) {
    if (code) {
      if (line.startsWith('```')) {
        blocks.push(<pre key={`c${blocks.length}`}>{code.join('\n')}</pre>)
        code = null
      } else {
        code.push(line)
      }

      continue
    }

    if (line.startsWith('```')) {
      flush()
      code = []

      continue
    }

    const h = /^(#{1,6})\s+(.*)$/.exec(line)

    if (h) {
      flush()
      const level = Math.min(h[1]!.length + 1, 6)
      const Tag = `h${level}` as 'h2'
      blocks.push(<Tag key={`h${blocks.length}`}>{inline(h[2]!, onLink, `h${blocks.length}`)}</Tag>)

      continue
    }

    const li = /^\s*(?:[-*+]|\d+\.)\s+(.*)$/.exec(line)

    if (li) {
      if (para.length) {
        flush()
      }

      list.push(li[1]!)

      continue
    }

    if (!line.trim()) {
      flush()

      continue
    }

    if (list.length) {
      flush()
    }

    para.push(line.trim())
  }

  if (code) {
    blocks.push(<pre key={`c${blocks.length}`}>{code.join('\n')}</pre>)
  }

  flush()

  return <div className="nv-vault-md">{blocks}</div>
}

// ---- graph: a small force layout computed once per graph ------------------
function layout(g: GraphResponse, w: number, h: number) {
  const n = g.nodes.length
  const pos = g.nodes.map((_, i) => ({
    x: w / 2 + Math.cos((i / Math.max(n, 1)) * Math.PI * 2) * w * 0.3,
    y: h / 2 + Math.sin((i / Math.max(n, 1)) * Math.PI * 2) * h * 0.3,
    vx: 0,
    vy: 0
  }))
  const idx = new Map(g.nodes.map((node, i) => [node.id, i]))
  const edges = g.edges.map(e => [idx.get(e.source)!, idx.get(e.target)!] as const).filter(([a, b]) => a != null && b != null)
  const k = Math.sqrt((w * h) / Math.max(n, 1)) * 0.6

  for (let it = 0; it < 220; it++) {
    for (let a = 0; a < n; a++) {
      for (let b = a + 1; b < n; b++) {
        const dx = pos[a]!.x - pos[b]!.x
        const dy = pos[a]!.y - pos[b]!.y
        const d2 = Math.max(dx * dx + dy * dy, 0.01)
        const f = (k * k) / d2
        pos[a]!.vx += dx * f * 0.02
        pos[a]!.vy += dy * f * 0.02
        pos[b]!.vx -= dx * f * 0.02
        pos[b]!.vy -= dy * f * 0.02
      }
    }

    for (const [a, b] of edges) {
      const dx = pos[a]!.x - pos[b]!.x
      const dy = pos[a]!.y - pos[b]!.y
      const d = Math.sqrt(dx * dx + dy * dy) || 1
      const f = (d - k) * 0.02
      pos[a]!.vx -= (dx / d) * f * 10
      pos[a]!.vy -= (dy / d) * f * 10
      pos[b]!.vx += (dx / d) * f * 10
      pos[b]!.vy += (dy / d) * f * 10
    }

    for (const p of pos) {
      p.vx += (w / 2 - p.x) * 0.005
      p.vy += (h / 2 - p.y) * 0.005
      p.x = Math.min(w - 20, Math.max(20, p.x + Math.max(-12, Math.min(12, p.vx))))
      p.y = Math.min(h - 20, Math.max(20, p.y + Math.max(-12, Math.min(12, p.vy))))
      p.vx *= 0.6
      p.vy *= 0.6
    }
  }

  return { edges, pos }
}

export function VaultGraph({
  graph,
  onOpen,
  selected
}: {
  graph: GraphResponse
  onOpen: (path: string) => void
  selected?: null | string
}) {
  const W = 760
  const H = 480
  const { edges, pos } = useMemo(() => layout(graph, W, H), [graph])

  if (!graph.nodes.length) {
    return <p className="nv-vault-empty">Belum ada catatan untuk digambar.</p>
  }

  return (
    <svg className="nv-vault-graph" data-nv-vault-graph={graph.nodes.length} viewBox={`0 0 ${W} ${H}`}>
      {edges.map(([a, b], i) => (
        <line className="nv-vault-edge" key={i} x1={pos[a]!.x} x2={pos[b]!.x} y1={pos[a]!.y} y2={pos[b]!.y} />
      ))}
      {graph.nodes.map((node, i) => (
        <g
          className={cn('nv-vault-node', !node.exists && 'nv-vault-node-ghost', selected === node.id && 'nv-vault-node-on')}
          key={node.id}
          onClick={() => node.exists && onOpen(node.id)}
          transform={`translate(${pos[i]!.x},${pos[i]!.y})`}
        >
          <circle r={4 + Math.min(node.degree, 10) * 1.2} />
          <text dy={-10} textAnchor="middle">
            {node.title}
          </text>
        </g>
      ))}
    </svg>
  )
}

function TreeItem({ node, onOpen, selected }: { node: TreeNode; onOpen: (p: string) => void; selected: null | string }) {
  const [open, setOpen] = useState(true)

  if (node.type === 'note') {
    return (
      <li>
        <button
          className={cn('nv-vault-tree-note', selected === node.path && 'nv-vault-tree-on')}
          data-nv-vault-note={node.path}
          onClick={() => onOpen(node.path)}
          type="button"
        >
          {node.name}
        </button>
      </li>
    )
  }

  return (
    <li>
      <button className="nv-vault-tree-folder" onClick={() => setOpen(v => !v)} type="button">
        {open ? '▾' : '▸'} {node.name}
      </button>
      {open && (
        <ul>
          {node.children?.map(c => <TreeItem key={c.path} node={c} onOpen={onOpen} selected={selected} />)}
        </ul>
      )}
    </li>
  )
}

export function NeovarchVaultPage() {
  const navigate = useNavigate()
  const [tree, setTree] = useState<null | TreeResponse>(null)
  const [graph, setGraph] = useState<GraphResponse | null>(null)
  const [note, setNote] = useState<NoteResponse | null>(null)
  const [selected, setSelected] = useState<null | string>(null)
  const [view, setView] = useState<'graph' | 'note'>('note')
  const [error, setError] = useState<null | string>(null)

  const load = useCallback(async () => {
    try {
      const [t, g] = await Promise.all([api<TreeResponse>('/api/obsidian/tree'), api<GraphResponse>('/api/obsidian/graph')])
      setTree(t)
      setGraph(g)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
    // Reload as soon as Settings ▸ Vault Obsidian saves (the page may stay
    // mounted behind the Settings overlay) and whenever the window regains focus.
    const reload = () => void load()
    window.addEventListener(OBSIDIAN_VAULT_CHANGED_EVENT, reload)
    window.addEventListener('focus', reload)

    return () => {
      window.removeEventListener(OBSIDIAN_VAULT_CHANGED_EVENT, reload)
      window.removeEventListener('focus', reload)
    }
  }, [load])

  const open = useCallback(async (path: string) => {
    setSelected(path)
    setView('note')

    try {
      setNote(await api<NoteResponse>(`/api/obsidian/note?path=${encodeURIComponent(path)}`))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const openLink = useCallback(
    (target: string) => {
      const hit = note?.outgoing.find(o => o.target === target)?.path
      void open(hit ?? target)
    },
    [note, open]
  )

  if (tree && !tree.configured) {
    return (
      <div className="nv-vault nv-vault-unset">
        <h1 className="nv-vault-title">Vault Obsidian</h1>
        <p className="nv-vault-empty">Belum ada vault. Pilih folder vault di Pengaturan ▸ Memori & Skill ▸ Vault Obsidian.</p>
        <button className="nv-vault-btn" onClick={() => navigate(VAULT_SETTINGS_ROUTE)} type="button">
          Buka Pengaturan
        </button>
      </div>
    )
  }

  return (
    <div className="nv-vault" data-nv-page="vault">
      <aside className="nv-vault-side">
        <div className="nv-vault-side-head">
          <span className="nv-vault-kicker">Vault</span>
          <strong>{tree?.vault ?? '…'}</strong>
        </div>
        <div className="nv-vault-tabs">
          <button className={cn(view === 'note' && 'nv-vault-tab-on')} onClick={() => setView('note')} type="button">
            Catatan
          </button>
          <button
            className={cn(view === 'graph' && 'nv-vault-tab-on')}
            data-nv-vault-tab="graph"
            onClick={() => setView('graph')}
            type="button"
          >
            Graf
          </button>
        </div>
        <ul className="nv-vault-tree">
          {tree?.tree?.children?.map(c => <TreeItem key={c.path} node={c} onOpen={p => void open(p)} selected={selected} />)}
        </ul>
      </aside>
      <section className="nv-vault-main">
        {error && (
          <div className="nv-vault-empty" role="alert">
            <p>Vault belum bisa dimuat: {error}</p>
            <button className="nv-vault-retry" onClick={() => void load()} type="button">
              Coba lagi
            </button>
          </div>
        )}
        {view === 'graph' && graph && <VaultGraph graph={graph} onOpen={p => void open(p)} selected={selected} />}
        {view === 'note' && !note && <p className="nv-vault-empty">Pilih catatan di kiri, atau buka tab Graf.</p>}
        {view === 'note' && note && (
          <article className="nv-vault-note" data-nv-vault-open={note.path}>
            <header className="nv-vault-note-head">
              <div>
                <p className="nv-vault-kicker">{note.path}</p>
                <h1 className="nv-vault-title">{note.title}</h1>
                {note.tags.length > 0 && (
                  <p className="nv-vault-tags">
                    {note.tags.map(t => (
                      <span key={t}>#{t}</span>
                    ))}
                  </p>
                )}
              </div>
              <button className="nv-vault-btn" onClick={() => openExternal(note.open_uri)} type="button">
                Buka di Obsidian
              </button>
            </header>
            <VaultMarkdown onLink={openLink} source={note.content} />
            <footer className="nv-vault-backlinks">
              <h2>Backlink ({note.backlinks.length})</h2>
              {note.backlinks.length === 0 && <p className="nv-vault-empty">Belum ada catatan yang menautkan ke sini.</p>}
              {note.backlinks.map(b => (
                <button className="nv-vault-backlink" key={b.path} onClick={() => void open(b.path)} type="button">
                  <strong>{b.title}</strong>
                  <span>{b.snippet}</span>
                </button>
              ))}
            </footer>
          </article>
        )}
      </section>
    </div>
  )
}
