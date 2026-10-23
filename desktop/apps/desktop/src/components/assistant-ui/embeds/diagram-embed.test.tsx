import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

const { renderMermaid } = vi.hoisted(() => ({
  renderMermaid: vi.fn(async () => ({ svg: '<svg viewBox="0 0 10 10"><title>Classic</title></svg>' }))
}))

vi.mock('mermaid', () => ({ default: { initialize: vi.fn(), render: renderMermaid } }))
vi.mock('./use-is-dark', () => ({ useIsDark: () => true }))

import DiagramRenderer from './diagram-embed'
import { RICH_FENCE_LANGUAGES } from './registry'

const FLOW = '---\ntitle: Alur login\n---\nflowchart TD\n  A([Mulai]) --> B{Benar?}\n  B -->|Ya| C[Masuk]\n  B -->|Tidak| A'
const SEQ = 'sequenceDiagram\n  title Login\n  A->>S: POST /login\n  S-->>A: token'

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 600 })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DiagramRenderer (old ```mermaid / ```diagram blocks)', () => {
  it('handles mermaid, mmd and diagram fences', () => {
    for (const lang of ['mermaid', 'mmd', 'diagram', 'visual']) {
      expect(RICH_FENCE_LANGUAGES.has(lang)).toBe(true)
    }
  })

  it('draws a convertible flowchart as a visual card (no mermaid runtime)', () => {
    render(<DiagramRenderer code={FLOW} />)
    const card = screen.getByTestId('visual-card')
    expect(card.getAttribute('data-source')).toBe('mermaid')
    expect(screen.getByTestId('visual-title').textContent).toBe('Alur login')
    const frame = screen.getByTestId('visual-frame') as HTMLIFrameElement
    expect(frame.getAttribute('sandbox')).toBe('')
    expect(frame.getAttribute('srcdoc')).toContain('Mulai')
    expect(renderMermaid).not.toHaveBeenCalled()
  })

  it('draws a sequence diagram as a visual card', () => {
    render(<DiagramRenderer code={SEQ} />)
    expect(screen.getByTestId('visual-title').textContent).toBe('Login')
    expect((screen.getByTestId('visual-frame') as HTMLIFrameElement).getAttribute('srcdoc')).toContain('POST /login')
  })

  it('shows the drawing placeholder while streaming, with the mermaid title', () => {
    render(<DiagramRenderer code={'---\ntitle: Alur login\n---\nflowchart TD\n  A-->'} streaming />)
    expect(screen.getByTestId('visual-drawing')).toBeTruthy()
    expect(screen.getByTestId('visual-title').textContent).toBe('Alur login')
  })

  it('uses the "Diagram" heading when the mermaid has no title', () => {
    render(<DiagramRenderer code={'flowchart LR\n A --> B'} />)
    expect(screen.getByTestId('visual-title').textContent).toBe('Diagram')
  })

  it('keeps the classic mermaid renderer for unsupported diagrams', async () => {
    const { container } = render(<DiagramRenderer code={'classDiagram\n  Animal <|-- Duck'} />)
    expect(screen.getByTestId('diagram-fallback')).toBeTruthy()
    expect(screen.queryByTestId('visual-card')).toBeNull()
    await waitFor(() => expect(container.querySelector('img')).toBeTruthy())
    expect(renderMermaid).toHaveBeenCalledTimes(1)
  })

  it('keeps the classic renderer for flowchart syntax the converter rejects (subgraph)', () => {
    render(<DiagramRenderer code={'flowchart TD\n subgraph API\n A-->B\n end'} />)
    expect(screen.getByTestId('diagram-fallback')).toBeTruthy()
  })

  it('a ```diagram fence holding a visual JSON spec renders as a visual', () => {
    render(<DiagramRenderer code={'{"type":"bar","title":"Ukuran","data":[{"label":"a","value":1}]}'} />)
    expect(screen.getByTestId('visual-card').getAttribute('data-source')).toBe('visual')
    expect(screen.getByTestId('visual-title').textContent).toBe('Ukuran')
  })

  it('the menu switches to the original mermaid style and back', async () => {
    render(<DiagramRenderer code={FLOW} />)
    const trigger = screen.getByTestId('visual-menu')
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' })
    fireEvent.click(await screen.findByTestId('visual-classic'))
    expect(await screen.findByTestId('diagram-classic')).toBeTruthy()
    await waitFor(() => expect(renderMermaid).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('diagram-new-style'))
    expect(screen.getByTestId('visual-card')).toBeTruthy()
  })
})
