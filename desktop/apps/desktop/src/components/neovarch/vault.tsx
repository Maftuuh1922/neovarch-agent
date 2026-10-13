import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { hermesApi } from '@/api/client'
import { OBSIDIAN_VAULT_CHANGED_EVENT } from '@/app/settings/obsidian-vault-settings'
import { cn } from '@/lib/utils'

import {
  DEFAULT_FILTERS,
  filterGraph,
  type GraphFilters,
  type GraphNodeIn,
  graphProjects,
  graphTags,
  KIND_COLORS,
  KIND_LABELS,
  kindOf,
  localGraph,
  NODE_KINDS,
  type NodeKind,
  VaultForceGraph
} from './vault-graph'

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
  open_uri?: string
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
  nodes: GraphNodeIn[]
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

// ---- graph: see vault-graph.tsx (force layout, filters, local graph) -------

function GraphPanel({
  graph,
  onOpen,
  selected
}: {
  graph: GraphResponse
  onOpen: (path: string) => void
  selected: null | string
}) {
  const [filters, setFilters] = useState<GraphFilters>(DEFAULT_FILTERS)
  const [mode, setMode] = useState<'global' | 'local'>('global')
  const [depth, setDepth] = useState(1)
  const tags = useMemo(() => graphTags(graph), [graph])
  const projects = useMemo(() => graphProjects(graph), [graph])
  const shown = useMemo(() => {
    const base = mode === 'local' && selected ? localGraph(graph, selected, depth) : graph

    return filterGraph(base, filters)
  }, [depth, filters, graph, mode, selected])
  const set = (patch: Partial<GraphFilters>) => setFilters(f => ({ ...f, ...patch }))

  const toggleKind = (k: NodeKind) =>
    set({ hiddenKinds: filters.hiddenKinds.includes(k) ? filters.hiddenKinds.filter(x => x !== k) : [...filters.hiddenKinds, k] })

  const present = useMemo(() => new Set(graph.nodes.map(n => kindOf(n))), [graph])

  return (
    <div className="nv-vault-graph-panel">
      <div className="nv-vault-graph-tools" data-nv-vault-graph-tools>
        <input
          aria-label="Cari di graf"
          className="nv-vault-graph-search"
          onChange={e => set({ query: e.target.value })}
          placeholder="Cari catatan…"
          value={filters.query}
        />
        <select aria-label="Filter tag" onChange={e => set({ tag: e.target.value || null })} value={filters.tag ?? ''}>
          <option value="">Semua tag</option>
          {tags.map(t => (
            <option key={t} value={t}>
              #{t}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter proyek"
          onChange={e => set({ project: e.target.value || null })}
          value={filters.project ?? ''}
        >
          <option value="">Semua proyek</option>
          {projects.map(p => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label className="nv-vault-graph-check">
          <input checked={filters.orphans} onChange={e => set({ orphans: e.target.checked })} type="checkbox" /> Yatim
        </label>
        <label className="nv-vault-graph-check">
          <input checked={filters.unresolved} onChange={e => set({ unresolved: e.target.checked })} type="checkbox" />{' '}
          Belum ada
        </label>
        <div className="nv-vault-graph-mode">
          <button
            className={cn(mode === 'global' && 'nv-vault-tab-on')}
            onClick={() => setMode('global')}
            type="button"
          >
            Global
          </button>
          <button
            className={cn(mode === 'local' && 'nv-vault-tab-on')}
            data-nv-vault-local
            disabled={!selected}
            onClick={() => setMode('local')}
            title={selected ? 'Graf lokal catatan yang dipilih' : 'Pilih catatan dulu'}
            type="button"
          >
            Lokal
          </button>
          {mode === 'local' && (
            <select aria-label="Kedalaman" onChange={e => setDepth(Number(e.target.value))} value={depth}>
              <option value={1}>1 lompatan</option>
              <option value={2}>2 lompatan</option>
              <option value={3}>3 lompatan</option>
            </select>
          )}
        </div>
      </div>
      <div className="nv-vault-graph-legend" data-nv-vault-legend>
        {NODE_KINDS.filter(k => present.has(k)).map(k => (
          <button
            aria-pressed={!filters.hiddenKinds.includes(k)}
            className={cn('nv-vault-legend-chip', filters.hiddenKinds.includes(k) && 'nv-vault-legend-off')}
            key={k}
            onClick={() => toggleKind(k)}
            type="button"
          >
            <span style={{ background: KIND_COLORS[k] ?? 'var(--nv-text-2)' }} />
            {KIND_LABELS[k]}
          </button>
        ))}
        <span className="nv-vault-graph-count">
          {shown.nodes.length} catatan · {shown.edges.length} tautan
        </span>
      </div>
      {shown.nodes.length ? (
        <VaultForceGraph graph={shown} onOpen={onOpen} selected={selected} />
      ) : (
        <p className="nv-vault-empty">Tidak ada catatan yang cocok dengan filter.</p>
      )}
    </div>
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
  const [busy, setBusy] = useState<null | string>(null)

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

  const post = useCallback(
    async (path: string, label: string) => {
      setBusy(label)

      try {
        await hermesApi({ body: {}, method: 'POST', path })
        setError(null)
        window.dispatchEvent(new CustomEvent(OBSIDIAN_VAULT_CHANGED_EVENT))
        await load()
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(null)
      }
    },
    [load]
  )

  const localOf = useMemo(
    () => (graph && note ? localGraph(graph, note.path, 1) : null),
    [graph, note]
  )

  if (tree && !tree.configured) {
    return (
      <div className="nv-vault nv-vault-unset">
        <h1 className="nv-vault-title">Vault Obsidian</h1>
        <p className="nv-vault-empty">
          Belum ada vault. Buat vault Neovarch (folder Obsidian asli: catatan Markdown, [[wikilink]], .obsidian) — proyek,
          sesi, dan berkas yang diubah agen langsung jadi catatan yang saling tertaut. Atau pilih folder vault yang sudah ada
          di Pengaturan ▸ Memori & Skill ▸ Vault Obsidian.
        </p>
        {error && (
          <p className="nv-vault-empty" role="alert">
            {error}
          </p>
        )}
        <div className="nv-vault-actions">
          <button
            className="nv-vault-btn nv-vault-btn-primary"
            data-nv-vault-init
            disabled={busy !== null}
            onClick={() => void post('/api/obsidian/init', 'init')}
            type="button"
          >
            {busy === 'init' ? 'Menyiapkan…' : 'Buat vault Neovarch'}
          </button>
          <button className="nv-vault-btn" onClick={() => navigate(VAULT_SETTINGS_ROUTE)} type="button">
            Buka Pengaturan
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="nv-vault" data-nv-page="vault">
      <aside className="nv-vault-side">
        <div className="nv-vault-side-head">
          <span className="nv-vault-kicker">Vault</span>
          <strong>{tree?.vault ?? '…'}</strong>
          <div className="nv-vault-side-actions">
            {tree?.open_uri && (
              <button
                className="nv-vault-btn nv-vault-btn-sm"
                data-nv-vault-open-app
                onClick={() => openExternal(tree.open_uri!)}
                title="Buka seluruh vault di aplikasi Obsidian"
                type="button"
              >
                Buka di Obsidian
              </button>
            )}
            <button
              className="nv-vault-btn nv-vault-btn-sm"
              data-nv-vault-sync
              disabled={busy !== null}
              onClick={() => void post('/api/obsidian/sync', 'sync')}
              title="Tulis ulang catatan proyek & sesi dari riwayat obrolan"
              type="button"
            >
              {busy === 'sync' ? 'Menyinkronkan…' : 'Sinkronkan'}
            </button>
          </div>
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
        {view === 'graph' && graph && !graph.nodes.length && (
          <p className="nv-vault-empty">Belum ada catatan untuk digambar.</p>
        )}
        {view === 'graph' && graph && graph.nodes.length > 0 && (
          <GraphPanel graph={graph} onOpen={p => void open(p)} selected={selected} />
        )}
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
            {localOf && localOf.nodes.length > 1 && (
              <section className="nv-vault-local" data-nv-vault-localgraph>
                <h2>Graf lokal</h2>
                <VaultForceGraph compact graph={localOf} onOpen={p => void open(p)} selected={note.path} />
              </section>
            )}
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
