// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OfficeSnapshot } from './office-store'

const scene = vi.hoisted(() => ({
  options: [] as { framing?: string; thumbnail?: { fps?: number; pixelRatio?: number } }[],
  dispose: vi.fn(),
  setAgents: vi.fn(),
  setPaused: vi.fn()
}))

vi.mock('./office3d-scene', () => ({
  createOfficeScene: (options: { thumbnail?: { fps?: number; pixelRatio?: number } }) => {
    scene.options.push(options)

    return {
      dispose: scene.dispose,
      resetCamera: vi.fn(),
      setAgents: scene.setAgents,
      setPaused: scene.setPaused,
      setSelected: vi.fn()
    }
  }
}))

vi.mock('@/store/gateway', async () => {
  const { atom } = await import('nanostores')

  return { $gateway: atom(null) }
})

const { $office } = await import('./office-store')
const { NeovarchOfficeMini } = await import('./office')
const { MINI_OFFICE_FPS } = await import('./office-mini-3d')

const SNAP: OfficeSnapshot = {
  agents: [
    {
      current_task: 'Tulis laporan',
      current_tool: null,
      id: 'session:a',
      kind: 'session',
      last_activity: 0,
      last_activity_text: null,
      message_count: 2,
      model: 'm',
      name: 'Sari',
      pending_approval: null,
      role: 'Agen utama',
      session_id: 'a',
      source: 'desktop',
      status: 'working',
      title: null
    }
  ],
  counts: { idle: 0, total: 1, 'waiting-approval': 0, working: 1 },
  feed: [],
  generated_at: 0,
  host: 'pc',
  kanban: {},
  seq: 1,
  vault: { configured: false, connected: false, note_count: 0, path: '' }
}

let intersect: ((entries: { isIntersecting: boolean }[]) => void) | null = null

beforeEach(() => {
  scene.options.length = 0
  vi.clearAllMocks()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) =>
    kind.startsWith('webgl') ? ({} as WebGLRenderingContext) : null) as never)
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        intersect = cb
      }

      disconnect() {}

      observe() {}
    }
  )
  $office.set(SNAP)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  $office.set(null)
})

function renderMini() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<NeovarchOfficeMini />} path="/" />
        <Route element={<p>HALAMAN CREW</p>} path="/crew" />
      </Routes>
    </MemoryRouter>
  )
}

describe('mini Kantor 3D in the right sidebar', () => {
  it('reuses the office scene as a low-res, low-fps thumbnail with live agents', async () => {
    const { container } = renderMini()

    expect(container.querySelector('[data-slot="nv-office-mini3d"]')).not.toBeNull()
    await waitFor(() => expect(scene.options.length).toBe(1))
    expect(scene.options[0]!.thumbnail).toEqual({ fps: MINI_OFFICE_FPS, pixelRatio: 0.75 })
    // Cropped to the room + engawa: the garden is left to the full Kantor.
    expect(scene.options[0]!.framing).toBe('room')
    await waitFor(() => expect(scene.setAgents).toHaveBeenCalled())
    expect(scene.setAgents.mock.lastCall![0]).toMatchObject([{ id: 'session:a', name: 'Sari' }])
  })

  it('pauses rendering when offscreen and resumes when back in view', async () => {
    renderMini()
    await waitFor(() => expect(scene.setPaused).toHaveBeenCalledWith(false))

    act(() => intersect?.([{ isIntersecting: false }]))
    expect(scene.setPaused).toHaveBeenLastCalledWith(true)

    act(() => intersect?.([{ isIntersecting: true }]))
    expect(scene.setPaused).toHaveBeenLastCalledWith(false)
  })

  it('disposes the scene when the sidebar unmounts and opens Crew on click', async () => {
    const first = renderMini()

    await waitFor(() => expect(scene.options.length).toBe(1))
    first.unmount()
    expect(scene.dispose).toHaveBeenCalled()

    renderMini()
    // Rendered without the locale provider, so the English catalog shows.
    expect(screen.getByText('Crew')).toBeTruthy()
    expect(screen.queryByText('Kantor')).toBeNull()
    fireEvent.click(screen.getByTitle('Open Crew'))
    expect(screen.getByText('HALAMAN CREW')).toBeTruthy()
  })
})
