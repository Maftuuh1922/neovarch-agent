import { describe, expect, it } from 'vitest'

import { looksLikeVisualBody, mermaidFamily, mermaidPartialTitle, mermaidToVisual } from './mermaid'
import { renderSpec } from './render'

const LOGIN = `---
title: Alur login
---
flowchart TD
  A([Mulai]) --> B[Isi form login]
  B --> C{Password benar?}
  C -->|Ya| D[Buat sesi]
  C -- Tidak --> E[Tampilkan error]
  E -.-> B
  D ==> F([Selesai])
  class D hot`

const SEQ = `sequenceDiagram
  title Login dengan token
  autonumber
  actor U as Pengguna
  participant A as Aplikasi
  participant S as Server
  U->>A: Ketuk Login
  A->>+S: POST /login
  alt kredensial benar
    S-->>-A: 200 + token
  else salah
    S--xA: 401
  end
  Note over A,S: Token disimpan di keychain
  A->>A: simpan token
  loop tiap 5 menit
    A-)S: ping
  end
  A-->>U: Beranda`

const TIMELINE = `timeline
  title Rilis Neovarch
  section 2026
  Agustus : v1.4.6
  September : v1.4.7 : Relay
           : Wi-Fi lokal
  Oktober : v1.4.8`

type Json = Record<string, unknown>

describe('mermaidToVisual', () => {
  it('turns a flowchart into a flow spec (shapes, labels, dashed/thick links, title, class highlight)', () => {
    const conv = mermaidToVisual(LOGIN)!
    expect(conv.family).toBe('flowchart')
    const spec = conv.spec
    expect(spec).toMatchObject({ direction: 'down', title: 'Alur login', type: 'flow' })
    const steps = spec.steps as Json[]
    expect(steps.map(s => s.id)).toEqual(['A', 'B', 'C', 'D', 'E', 'F'])
    expect(steps.find(s => s.id === 'A')).toMatchObject({ label: 'Mulai', shape: 'start' })
    expect(steps.find(s => s.id === 'C')).toMatchObject({ label: 'Password benar?', shape: 'decision' })
    expect(steps.find(s => s.id === 'F')).toMatchObject({ shape: 'end' })
    expect(steps.find(s => s.id === 'D')?.highlight).toBe(true)
    const edges = spec.edges as Json[]
    expect(edges).toContainEqual(expect.objectContaining({ from: 'C', label: 'Ya', to: 'D' }))
    expect(edges).toContainEqual(expect.objectContaining({ from: 'C', label: 'Tidak', to: 'E' }))
    expect(edges.find(e => e.from === 'E')).toMatchObject({ dashed: true, to: 'B' })
    expect(edges.find(e => e.from === 'D')).toMatchObject({ highlight: true, to: 'F' })
  })

  it('reads one-liners, chains, & groups, LR direction and links without spaces', () => {
    const spec = mermaidToVisual('graph LR; A-->B-->C; A & B --- D[Gudang "utama"]')!.spec
    expect(spec.direction).toBe('right')
    const edges = (spec.edges as Json[]).map(e => `${e.from}>${e.to}${e.arrow === false ? '-' : ''}`)
    expect(edges).toEqual(['A>B', 'B>C', 'A>D-', 'B>D-'])
    expect((spec.steps as Json[]).find(s => s.id === 'D')?.label).toBe('Gudang "utama"')
  })

  it('draws an undirected letter graph as a graph spec', () => {
    const conv = mermaidToVisual('graph TD\n A --- B\n A --- C\n B --- C')!
    expect(conv.family).toBe('graph')
    expect(conv.spec).toMatchObject({ directed: false, type: 'graph' })
  })

  it('turns a sequenceDiagram into a sequence spec', () => {
    const conv = mermaidToVisual(SEQ)!
    expect(conv.family).toBe('sequence')
    const spec = conv.spec
    expect(spec).toMatchObject({ autonumber: true, title: 'Login dengan token', type: 'sequence' })
    expect((spec.participants as Json[]).map(p => [p.id, p.label, p.actor ?? false])).toEqual([
      ['U', 'Pengguna', true],
      ['A', 'Aplikasi', false],
      ['S', 'Server', false]
    ])
    const msgs = spec.messages as Json[]
    expect(msgs[0]).toMatchObject({ from: 'U', label: 'Ketuk Login', to: 'A' })
    expect(msgs.find(m => m.label === '200 + token')).toMatchObject({ dashed: true, from: 'S', to: 'A' })
    expect(msgs.find(m => m.label === '401')).toMatchObject({ cross: true })
    expect(msgs.filter(m => m.group).map(m => m.group)).toEqual(['alt', 'loop'])
    expect(msgs.filter(m => m.end)).toHaveLength(2)
    expect(msgs.find(m => m.else !== undefined)?.else).toBe('salah')
    expect(msgs.find(m => m.note)).toMatchObject({ note: 'Token disimpan di keychain', over: ['A', 'S'] })
    expect(msgs.find(m => m.label === 'simpan token')).toMatchObject({ from: 'A', to: 'A' })
  })

  it('turns a timeline into a timeline spec (extra events of a period become the note)', () => {
    const spec = mermaidToVisual(TIMELINE)!.spec
    expect(spec.title).toBe('Rilis Neovarch')
    const events = spec.events as Json[]
    expect(events.map(e => [e.date, e.label])).toEqual([
      ['Agustus', 'v1.4.6'],
      ['September', 'v1.4.7'],
      ['Oktober', 'v1.4.8']
    ])
    expect(events[0].note).toBe('2026')
    expect(events[1].note).toBe('Relay · Wi-Fi lokal')
  })

  it('turns a pie into a bar spec with percentages', () => {
    const spec = mermaidToVisual('pie title Bahasa\n "TS" : 60\n "Dart" : 30\n "Python" : 10')!.spec
    expect(spec).toMatchObject({ sort: 'desc', title: 'Bahasa', type: 'bar' })
    expect((spec.data as Json[])[0]).toMatchObject({ display: '60%', highlight: true, label: 'TS', value: 60 })
  })

  it('turns a simple stateDiagram into a flow', () => {
    const conv = mermaidToVisual('stateDiagram-v2\n [*] --> Idle\n Idle --> Running : start\n Running --> Idle : stop\n Running --> [*]')!
    expect(conv.family).toBe('state')
    expect((conv.spec.steps as Json[]).map(s => s.shape)).toEqual(['start', 'box', 'box', 'end'])
    expect(conv.spec.edges).toContainEqual(expect.objectContaining({ from: 'Idle', label: 'start', to: 'Running' }))
  })

  it('returns null (classic mermaid) for unsupported types and syntax', () => {
    expect(mermaidToVisual('classDiagram\n A <|-- B')).toBeNull()
    expect(mermaidToVisual('erDiagram\n A ||--o{ B : has')).toBeNull()
    expect(mermaidToVisual('gantt\n title x')).toBeNull()
    expect(mermaidToVisual('flowchart TD\n subgraph X\n A-->B\n end')).toBeNull()
    expect(mermaidToVisual('stateDiagram-v2\n state X {\n A --> B\n }')).toBeNull()
    expect(mermaidToVisual('sequenceDiagram\n A->>B: hi\n end')).toBeNull()
    expect(mermaidToVisual('flowchart TD\n A-->B\n this is not mermaid ))')).toBeNull()
    const big = 'flowchart TD\n' + Array.from({ length: 40 }, (_, i) => `N${i} --> N${i + 1}`).join('\n')
    expect(mermaidToVisual(big)).toBeNull()
    expect(mermaidToVisual('{"type": "flow"}')).toBeNull()
    expect(mermaidToVisual('')).toBeNull()
  })

  it('every converted spec renders to an svg that fits a phone column', () => {
    for (const code of [LOGIN, SEQ, TIMELINE, 'pie\n "a" : 1\n "b" : 2', 'graph TD\n A---B']) {
      const conv = mermaidToVisual(code)!
      const out = renderSpec(conv.spec, code, { width: 360 })
      expect(out.svg.startsWith('<svg')).toBe(true)
      expect(out.width).toBeLessThanOrEqual(400)
    }
  })

  it('helpers: family, partial title, visual body detection', () => {
    expect(mermaidFamily('%%{init: {"theme": "dark"}}%%\n%% c\nsequenceDiagram\n A->>B: x')).toBe('sequencediagram')
    expect(mermaidPartialTitle('---\ntitle: Alur login\n---\nflowchart TD\n A-->')).toBe('Alur login')
    expect(mermaidPartialTitle('timeline\n  title Rilis\n  2026 : a')).toBe('Rilis')
    expect(mermaidPartialTitle('pie title Bahasa\n "a": 1')).toBe('Bahasa')
    expect(looksLikeVisualBody('{"type":"flow"}')).toBe(true)
    expect(looksLikeVisualBody('title: x\n---\n<svg viewBox="0 0 1 1"/>')).toBe(true)
    expect(looksLikeVisualBody('flowchart TD\n A-->B')).toBe(false)
  })
})

describe('sequence spec renderer', () => {
  it('lays columns out for the available width and draws messages, groups and notes', () => {
    const spec = mermaidToVisual(SEQ)!.spec
    const wide = renderSpec(spec, SEQ, { width: 720 })
    const narrow = renderSpec(spec, SEQ, { width: 340 })
    expect(narrow.width).toBeLessThan(wide.width)
    expect(wide.svg).toContain('Pengguna')
    expect(wide.svg).toContain('1. Ketuk Login')
    expect(wide.svg).toContain('[kredensial benar]')
    expect(wide.svg).toContain('Token disimpan di keychain')
    expect(wide.svg).toContain('stroke-dasharray:5 4')
    expect(wide.svg).toContain('marker-end')
  })

  it('rejects empty and oversized sequences', () => {
    expect(() => renderSpec({ messages: [], type: 'sequence' })).toThrow(/participants/)
    const many = { messages: Array.from({ length: 11 }, (_, i) => ({ from: `P${i}`, to: `P${i + 1}` })), type: 'sequence' }
    expect(() => renderSpec(many)).toThrow(/10/)
  })

  it('flow edges with arrow:false have no arrowhead', () => {
    const out = renderSpec({ edges: [{ arrow: false, from: 'a', to: 'b' }], steps: [{ id: 'a' }, { id: 'b' }], type: 'flow' })
    expect(out.svg).not.toContain('marker-end')
  })
})
