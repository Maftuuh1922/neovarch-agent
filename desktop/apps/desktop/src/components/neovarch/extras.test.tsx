import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.fn()

vi.mock('@/api/client', () => ({ hermesApi: (req: { body?: unknown; method?: string; path: string }) => api(req) }))

import { extrasPhaseText, ObsidianExtraPanel, useOpenInObsidian } from './extras'

function OpenButton({ uri }: { uri: string }) {
  const ob = useOpenInObsidian()

  return (
    <div>
      <button onClick={() => void ob.open(uri)} type="button">
        Buka di Obsidian
      </button>
      {ob.offer && (
        <button onClick={() => void ob.accept()} type="button">
          Pasang & buka
        </button>
      )}
      <span data-testid="phase">{extrasPhaseText(ob.job)}</span>
    </div>
  )
}

describe('optional extras (Obsidian)', () => {
  let installed = false
  let job: null | Record<string, unknown> = null
  const openExternal = vi.fn()

  beforeEach(() => {
    installed = false
    job = null
    openExternal.mockReset()
    ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { openExternal }
    api.mockReset()
    api.mockImplementation(async (req: { body?: { name?: string }; method?: string; path: string }) => {
      if (req.path === '/api/extras/install') {
        job = { name: 'obsidian', percent: 40, phase: 'download', state: 'running' }

        return { job }
      }

      if (req.path === '/api/extras') {
        if (job && job.state === 'running') {
          // the next poll after the install started sees it finished
          installed = true
          job = { name: 'obsidian', state: 'done', status: 'installed' }
        }

        return {
          extras: [{ auto: true, installed, label: 'Obsidian', name: 'obsidian', path: installed ? '/home/u/.local/bin/obsidian' : null }],
          job
        }
      }

      return { ok: true }
    })
  })

  afterEach(() => cleanup())

  it('phase text', () => {
    expect(extrasPhaseText({ percent: 42.4, phase: 'download', state: 'running' })).toBe('Mengunduh dari rilis resmi… 42%')
    expect(extrasPhaseText({ detail: 'offline', state: 'failed' })).toBe('Gagal memasang: offline')
    expect(extrasPhaseText({ state: 'done', status: 'installed' })).toBe('Obsidian terpasang.')
    expect(extrasPhaseText(null)).toBe('')
  })

  it('settings panel: missing → "Pasang Obsidian" installs with progress; auto toggle saves config', async () => {
    render(<ObsidianExtraPanel />)
    expect(await screen.findByText(/Belum terpasang/)).toBeTruthy()
    await act(async () => {
      fireEvent.click(screen.getByText('Pasang Obsidian'))
    })
    expect(api).toHaveBeenCalledWith({ body: { name: 'obsidian' }, method: 'POST', path: '/api/extras/install' })
    expect(await screen.findByText(/Terpasang/, {}, { timeout: 6000 })).toBeTruthy()

    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'))
    })
    expect(api).toHaveBeenCalledWith({ body: { extras: { auto_install: false } }, method: 'PUT', path: '/api/config' })
  })

  it('"Buka di Obsidian": installed → opens the link; missing → offer, install, then open', async () => {
    installed = true
    const { unmount } = render(<OpenButton uri="obsidian://open?path=%2Fv" />)
    await act(async () => {
      fireEvent.click(screen.getByText('Buka di Obsidian'))
    })
    expect(openExternal).toHaveBeenCalledWith('obsidian://open?path=%2Fv')
    unmount()

    installed = false
    openExternal.mockReset()
    render(<OpenButton uri="obsidian://open?path=%2Fv" />)
    await act(async () => {
      fireEvent.click(screen.getByText('Buka di Obsidian'))
    })
    expect(openExternal).not.toHaveBeenCalled()
    await act(async () => {
      fireEvent.click(await screen.findByText('Pasang & buka'))
    })
    await vi.waitFor(() => expect(openExternal).toHaveBeenCalledWith('obsidian://open?path=%2Fv'), { timeout: 6000 })
  })
})
