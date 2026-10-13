import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  adjacency,
  buildSimulation,
  DEFAULT_FILTERS,
  filterGraph,
  fitView,
  type GraphIn,
  graphProjects,
  graphTags,
  kindOf,
  labelAlpha,
  localGraph,
  VaultForceGraph,
  zoomAt
} from './vault-graph'

const G: GraphIn = {
  edges: [
    { source: 'Neovarch/Neovarch.md', target: 'Neovarch/Proyek/toko.md' },
    { source: 'Neovarch/Proyek/toko.md', target: 'Neovarch/Sesi/a.md' },
    { source: 'Neovarch/Sesi/a.md', target: 'Neovarch/Proyek/toko.md' },
    { source: 'Neovarch/Sesi/a.md', target: 'Neovarch/Proyek/toko/Berkas/src/app.py.md' },
    { source: 'Neovarch/Sesi/a.md', target: 'Keputusan.md' },
    { source: 'Keputusan.md', target: '?Belum Ada' }
  ],
  nodes: [
    { degree: 1, exists: true, id: 'Neovarch/Neovarch.md', kind: 'hub', tags: ['neovarch'], title: 'Neovarch' },
    { degree: 3, exists: true, id: 'Neovarch/Proyek/toko.md', kind: 'project', project: 'toko', tags: ['neovarch/proyek'], title: 'toko' },
    { degree: 4, exists: true, id: 'Neovarch/Sesi/a.md', kind: 'session', project: 'toko', tags: ['neovarch/sesi'], title: 'a' },
    {
      degree: 1,
      exists: true,
      id: 'Neovarch/Proyek/toko/Berkas/src/app.py.md',
      kind: 'file',
      project: 'toko',
      tags: ['neovarch/berkas'],
      title: 'app.py'
    },
    { degree: 2, exists: true, id: 'Keputusan.md', kind: 'note', tags: ['keputusan'], title: 'Keputusan' },
    { degree: 1, exists: false, id: '?Belum Ada', kind: 'unresolved', title: 'Belum Ada' },
    { degree: 0, exists: true, id: 'Yatim.md', kind: 'note', title: 'Yatim' }
  ]
}

describe('vault graph model', () => {
  afterEach(() => cleanup())

  it('kinds, tags, projects and neighbours', () => {
    expect(G.nodes.map(kindOf)).toEqual(['hub', 'project', 'session', 'file', 'note', 'unresolved', 'note'])
    expect(kindOf({ degree: 0, exists: true, id: 'x', kind: 'weird', title: 'x' })).toBe('note')
    expect(graphTags(G)).toEqual(['keputusan', 'neovarch', 'neovarch/berkas', 'neovarch/proyek', 'neovarch/sesi'])
    expect(graphProjects(G)).toEqual(['toko'])
    expect([...adjacency(G).get('Neovarch/Sesi/a.md')!].sort()).toEqual([
      'Keputusan.md',
      'Neovarch/Proyek/toko.md',
      'Neovarch/Proyek/toko/Berkas/src/app.py.md'
    ])
  })

  it('filters: orphans, unresolved, tag (with nesting), project, search and hidden kinds', () => {
    const ids = (g: GraphIn) => g.nodes.map(n => n.id)
    expect(ids(filterGraph(G, DEFAULT_FILTERS))).toHaveLength(7)
    expect(ids(filterGraph(G, { ...DEFAULT_FILTERS, orphans: false }))).not.toContain('Yatim.md')
    expect(ids(filterGraph(G, { ...DEFAULT_FILTERS, unresolved: false }))).not.toContain('?Belum Ada')
    expect(ids(filterGraph(G, { ...DEFAULT_FILTERS, tag: 'neovarch' })).sort()).toEqual([
      'Neovarch/Neovarch.md',
      'Neovarch/Proyek/toko.md',
      'Neovarch/Proyek/toko/Berkas/src/app.py.md',
      'Neovarch/Sesi/a.md'
    ])
    expect(ids(filterGraph(G, { ...DEFAULT_FILTERS, project: 'toko' }))).toHaveLength(3)
    expect(ids(filterGraph(G, { ...DEFAULT_FILTERS, query: 'app' }))).toEqual(['Neovarch/Proyek/toko/Berkas/src/app.py.md'])
    const noSessions = filterGraph(G, { ...DEFAULT_FILTERS, hiddenKinds: ['session'] })
    expect(ids(noSessions)).not.toContain('Neovarch/Sesi/a.md')
    expect(noSessions.edges.every(e => e.source !== 'Neovarch/Sesi/a.md' && e.target !== 'Neovarch/Sesi/a.md')).toBe(true)
  })

  it('local graph follows links both ways up to the depth', () => {
    expect(localGraph(G, 'Neovarch/Proyek/toko/Berkas/src/app.py.md', 1).nodes.map(n => n.id).sort()).toEqual([
      'Neovarch/Proyek/toko/Berkas/src/app.py.md',
      'Neovarch/Sesi/a.md'
    ])
    expect(localGraph(G, 'Neovarch/Proyek/toko/Berkas/src/app.py.md', 2).nodes).toHaveLength(4)
    expect(localGraph(G, 'nope', 2).nodes).toEqual([])
  })

  it('labels fade in with zoom; hubs earlier; highlighted always', () => {
    expect(labelAlpha(0.3, 0, false)).toBe(0)
    expect(labelAlpha(2, 0, false)).toBe(1)
    expect(labelAlpha(0.8, 20, false)).toBeGreaterThan(labelAlpha(0.8, 0, false))
    expect(labelAlpha(0.1, 0, true)).toBe(1)
  })

  it('zoom keeps the point under the cursor; fit centres the bounds', () => {
    const v = zoomAt({ k: 1, x: 0, y: 0 }, 100, 50, 2)
    expect(v.k).toBe(2)
    // world point under (100,50) before = (100,50); after = ((100 - v.x)/k, (50 - v.y)/k)
    expect((100 - v.x) / v.k).toBeCloseTo(100)
    expect((50 - v.y) / v.k).toBeCloseTo(50)
    expect(zoomAt({ k: 5, x: 0, y: 0 }, 0, 0, 10).k).toBe(6)
    const f = fitView(
      [
        { x: -100, y: -50 },
        { x: 100, y: 50 }
      ],
      400,
      200,
      0
    )
    expect(f.x).toBeCloseTo(200)
    expect(f.y).toBeCloseTo(100)
    expect(f.k).toBeCloseTo(2)
  })

  it('force layout: no node is pinned to an edge, linked notes end up closer than unlinked ones', () => {
    const { links, nodes, sim } = buildSimulation(G)
    expect(links).toHaveLength(6)

    for (let i = 0; i < 300; i++) {
      sim.tick()
    }

    const at = (id: string) => nodes.find(n => n.id === id)!
    const d = (a: string, b: string) => Math.hypot(at(a).x! - at(b).x!, at(a).y! - at(b).y!)
    expect(d('Neovarch/Proyek/toko.md', 'Neovarch/Sesi/a.md')).toBeLessThan(d('Neovarch/Neovarch.md', 'Yatim.md'))
    // no clamping to a box: positions are free floats around the centre, all finite and distinct
    const xs = nodes.map(n => n.x!)
    expect(xs.every(Number.isFinite)).toBe(true)
    expect(new Set(nodes.map(n => `${Math.round(n.x!)}:${Math.round(n.y!)}`)).size).toBe(nodes.length)
    // keeps old positions when rebuilt (filter change does not jump)
    const prev = new Map(nodes.map(n => [n.id, { x: n.x!, y: n.y! }]))
    const again = buildSimulation(G, prev)
    expect(again.nodes[0]!.x).toBe(prev.get(again.nodes[0]!.id)!.x)
    sim.stop()
  })

  it('renders a canvas with node/edge counts (jsdom: no 2d context, no crash)', () => {
    const { container } = render(<VaultForceGraph graph={G} onOpen={() => {}} />)
    const el = container.querySelector('[data-nv-vault-graph]')!
    expect(el.getAttribute('data-nv-vault-graph')).toBe('7')
    expect(el.getAttribute('data-nv-vault-edges')).toBe('6')
    expect(container.querySelector('canvas')!.getAttribute('aria-label')).toContain('7 catatan')
  })
})
