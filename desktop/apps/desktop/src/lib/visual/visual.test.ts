import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { DEFAULT_THEME_DARK, exportSvg, frameDocument, partialTitle, prepareVisual, renderSpec, svgCardHeight } from './index'
import { lenientJson, parseVisualSource } from './parse'
import { textWidth, wrapText } from './text'

const EXAMPLES = resolve(__dirname, '../../../../../../core/neovarch/skillpack/visual-inline/examples')

const examples = readdirSync(EXAMPLES)
  .filter(f => f.endsWith('.visual'))
  .sort()
  .map(f => [f, readFileSync(resolve(EXAMPLES, f), 'utf8')] as const)

describe('parse', () => {
  it('reads lenient JSON with comments and trailing commas', () => {
    expect(lenientJson('{"a": [1, 2,], // x\n "b": "//not a comment", /* c */}')).toEqual({ a: [1, 2], b: '//not a comment' })
  })

  it('splits title/caption headers from raw svg', () => {
    const p = parseVisualSource('title: Judul\ncaption: Keterangan\n---\n<svg viewBox="0 0 10 10"></svg>')
    expect(p).toMatchObject({ caption: 'Keterangan', kind: 'svg', title: 'Judul' })
  })

  it('finds a title while streaming', () => {
    expect(partialTitle('{"type":"graph","title":"Star vs graf')).toBeUndefined()
    expect(partialTitle('{"type":"graph","title":"Star vs graf kamu", "nodes": [')).toBe('Star vs graf kamu')
    expect(partialTitle('judul: Alur\n<svg')).toBe('Alur')
  })
})

describe('text', () => {
  it('wraps to the width and ellipsises past maxLines', () => {
    const lines = wrapText('satu dua tiga empat lima enam tujuh delapan sembilan sepuluh', 13, 80, 2)
    expect(lines).toHaveLength(2)
    expect(lines[1].endsWith('…')).toBe(true)
    lines.forEach(l => expect(textWidth(l, 13)).toBeLessThanOrEqual(80 + 13))
  })
})

describe('renderSpec', () => {
  it('draws a star with the hub in the middle and leaves around it', () => {
    const { svg } = renderSpec({ edges: [['A', 'B'], ['A', 'C'], ['A', 'D'], ['A', 'E']], nodes: [{ highlight: true, id: 'A' }, 'B', 'C', 'D', 'E'], type: 'graph' })
    const circles = [...svg.matchAll(/<circle cx="([\d.]+)" cy="([\d.]+)" r="19" class="nv-node"/g)].map(m => [Number(m[1]), Number(m[2])])
    expect(circles).toHaveLength(5)
    const [hub, ...leaves] = circles
    const cx = leaves.reduce((s, c) => s + c[0], 0) / 4
    const cy = leaves.reduce((s, c) => s + c[1], 0) / 4
    expect(Math.abs(hub[0] - cx)).toBeLessThan(1)
    expect(Math.abs(hub[1] - cy)).toBeLessThan(1)
    expect(svg).toContain('fill:var(--nv-blue)')
  })

  it('marks compare captions with ✓ and ✗', () => {
    const { svg } = renderSpec({
      panels: [
        { caption: 'Star', verdict: 'good', visual: { nodes: ['A'], type: 'graph' } },
        { caption: 'Bukan star', verdict: 'bad', visual: { nodes: ['A'], type: 'graph' } }
      ],
      type: 'compare'
    })
    expect(svg).toMatch(/var\(--nv-green\)">✓/)
    expect(svg).toMatch(/var\(--nv-red\)">✗/)
  })

  it('rejects unknown types and empty specs with a clear message', () => {
    expect(() => renderSpec({ type: 'pie' })).toThrow(/unknown type/)
    expect(() => renderSpec({ nodes: [], type: 'graph' })).toThrow(/nodes is empty/)
  })

  it('keeps marker ids unique per visual', () => {
    const a = renderSpec({ directed: true, edges: [['a', 'b']], nodes: ['a', 'b'], type: 'graph' }, 'one').svg
    const b = renderSpec({ directed: true, edges: [['a', 'b']], nodes: ['a', 'b'], type: 'graph' }, 'two').svg
    expect(/marker id="([^"]+)"/.exec(a)![1]).not.toBe(/marker id="([^"]+)"/.exec(b)![1])
  })
})

describe('prepareVisual', () => {
  it.each(examples)('renders example %s', (_name, code) => {
    const v = prepareVisual(code)
    expect(v.title).toBeTruthy()
    expect(v.caption).toBeTruthy()

    if (v.kind === 'svg') {
      expect(v.markup.startsWith('<svg')).toBe(true)
      expect(v.width).toBeGreaterThan(50)
      expect(v.height).toBeGreaterThan(50)
      // Every generated label survives sanitising.
      expect(v.markup).toContain('<text')
    }
  })

  it('strips scripts, handlers, foreignObject, external links and css urls', () => {
    const v = prepareVisual(
      '<svg viewBox="0 0 10 10" onload="alert(1)"><script>alert(1)</script><foreignObject><div>x</div></foreignObject>' +
        '<a href="https://evil.example"><text>t</text></a><image href="http://x/y.png"/><style>@import url(http://x); .a{fill:url(http://x/p)}</style>' +
        '<rect style="fill:url(https://x/p)" width="1" height="1"/></svg>'
    )
    expect(v.markup).not.toMatch(/onload|<script|foreignObject|evil\.example|http:\/\/x|https:\/\/x|@import/i)
    expect(v.markup).toContain('<text>t</text>')
  })

  it('cleans html fragments the same way', () => {
    const v = prepareVisual('<div onclick="x()">a<img src="https://t.example/p.gif"><iframe src="x"></iframe><form><input></form></div><style>.a{background:url(https://t.example)}</style>')
    expect(v.kind).toBe('html')
    expect(v.markup).not.toMatch(/onclick|t\.example|<iframe|<form|<input/)
  })

  it('pins raw svg to its viewBox size so it never scales up', () => {
    const v = prepareVisual('<svg viewBox="0 0 200 100"><rect width="10" height="10"/></svg>')
    expect(v.markup).toMatch(/width="200" height="100"/)
    expect(svgCardHeight(v, 1000)).toBe(124)
    expect(svgCardHeight(v, 128)).toBe(74)
  })

  it('rejects svg without a size', () => {
    expect(() => prepareVisual('<svg><rect/></svg>')).toThrow(/viewBox/)
  })
})

describe('frame and export', () => {
  const v = prepareVisual(examples[0][1])

  it('builds a sandbox document with a no-network CSP', () => {
    const doc = frameDocument(v, DEFAULT_THEME_DARK)
    expect(doc).toContain("default-src 'none'")
    expect(doc).not.toMatch(/<script/i)
    expect(doc).toContain('--nv-blue:')
  })

  it('exports a standalone svg with concrete colours, title and caption', () => {
    const out = exportSvg(v, DEFAULT_THEME_DARK)
    expect(out.svg).toContain('--nv-bg:#141010')
    expect(out.svg).toContain('Star vs graf kamu')
    expect(out.svg).toContain('Graf bintang')
    expect(out.height).toBeGreaterThan(v.height!)
  })
})
