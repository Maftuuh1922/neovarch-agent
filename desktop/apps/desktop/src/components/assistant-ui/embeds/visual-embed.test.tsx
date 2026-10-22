import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./use-is-dark', () => ({ useIsDark: () => true }))

import VisualRenderer from './visual-embed'

const STAR = JSON.stringify({
  caption: 'Satu pusat ke semua',
  edges: [['A', 'B'], ['A', 'C'], ['A', 'D']],
  nodes: [{ highlight: true, id: 'A' }, 'B', 'C', 'D'],
  title: 'Star',
  type: 'graph'
})

afterEach(() => cleanup())

describe('VisualRenderer', () => {
  it('shows a drawing placeholder with the title while the fence streams', () => {
    render(<VisualRenderer code={'{"type":"graph","title":"Star", "nodes": ['} streaming />)
    expect(screen.getByTestId('visual-drawing')).toBeTruthy()
    expect(screen.getByTestId('visual-title').textContent).toBe('Star')
    expect(screen.queryByTestId('visual-frame')).toBeNull()
  })

  it('renders a sandboxed frame with title and caption once complete', () => {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 600 })
    render(<VisualRenderer code={STAR} />)
    const frame = screen.getByTestId('visual-frame') as HTMLIFrameElement
    expect(frame.getAttribute('sandbox')).toBe('')
    expect(frame.getAttribute('srcdoc')).toContain("default-src 'none'")
    expect(frame.getAttribute('srcdoc')).toContain('<svg')
    expect(screen.getByTestId('visual-title').textContent).toBe('Star')
    expect(screen.getByTestId('visual-caption').textContent).toBe('Satu pusat ke semua')
    expect(Number.parseFloat(frame.style.height)).toBeGreaterThan(100)
  })

  it('falls back to the code when the block cannot be drawn', () => {
    render(<VisualRenderer code={'{"type":"pie"}'} />)
    expect(screen.getByTestId('visual-failed')).toBeTruthy()
    expect(screen.getByText('{"type":"pie"}')).toBeTruthy()
  })
})
