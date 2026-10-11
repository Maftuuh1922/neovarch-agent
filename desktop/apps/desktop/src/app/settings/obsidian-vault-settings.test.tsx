import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { groupSettingsNav } from './neovarch-nav'
import { OBSIDIAN_VAULT_CHANGED_EVENT, ObsidianVaultSettings } from './obsidian-vault-settings'

const api = vi.fn()

vi.mock('@/api/client', () => ({ hermesApi: (req: { body?: unknown; method?: string; path: string }) => api(req) }))

const unset = { configured: false, connected: false, enabled: true, note_count: 0, path: '' }

describe('Settings ▸ Vault Obsidian', () => {
  beforeEach(() => {
    api.mockReset()
    ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = {
      selectPaths: vi.fn(async () => ['/home/aku/Obsidian/Kuliah'])
    }
  })

  afterEach(() => cleanup())

  it('picks a folder with the native dialog, saves it, and tells the vault page to reload', async () => {
    api.mockImplementation(async (req: { body?: { enabled: boolean; path: string }; method?: string }) =>
      req.method === 'POST'
        ? { configured: true, connected: true, enabled: req.body!.enabled, note_count: 12, ok: true, path: req.body!.path }
        : unset
    )
    const changed = vi.fn()
    window.addEventListener(OBSIDIAN_VAULT_CHANGED_EVENT, changed)
    render(<ObsidianVaultSettings />)
    expect(await screen.findByText('Belum ada vault')).toBeTruthy()

    const save = screen.getByText('Simpan').closest('button') as HTMLButtonElement
    expect(save.disabled).toBe(true) // nothing changed yet

    await act(async () => {
      fireEvent.click(screen.getByText('Pilih folder…'))
    })
    expect(window.hermesDesktop.selectPaths).toHaveBeenCalledWith(expect.objectContaining({ directories: true }))
    expect((screen.getByLabelText('Folder vault') as HTMLInputElement).value).toBe('/home/aku/Obsidian/Kuliah')
    expect(save.disabled).toBe(false)

    await act(async () => {
      fireEvent.click(save)
    })
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith({
        body: { enabled: true, path: '/home/aku/Obsidian/Kuliah' },
        method: 'POST',
        path: '/api/memory/obsidian'
      })
    )
    expect(await screen.findByText('Tersambung · 12 catatan')).toBeTruthy()
    expect(changed).toHaveBeenCalledTimes(1)
    window.removeEventListener(OBSIDIAN_VAULT_CHANGED_EVENT, changed)
  })

  it('shows the core error when the folder is refused', async () => {
    api.mockImplementation(async (req: { method?: string }) => {
      if (req.method === 'POST') {
        throw new Error('400: {"ok": false, "error": "the folder does not exist: /nope"}')
      }

      return unset
    })
    render(<ObsidianVaultSettings />)
    await screen.findByText('Belum ada vault')
    fireEvent.change(screen.getByLabelText('Folder vault'), { target: { value: '/nope' } })
    await act(async () => {
      fireEvent.click(screen.getByText('Simpan'))
    })
    expect((await screen.findByRole('alert')).textContent).toBe('the folder does not exist: /nope')
  })

  it('is listed under Memori & Skill, before the (empty) generic Memori page', () => {
    const noop = () => undefined
    const groups = groupSettingsNav([
      { active: false, id: 'obsidian', label: 'x', onSelect: noop },
      { active: false, id: 'sessions', label: 'Sessions', onSelect: noop }
    ] as never)
    const memory = groups.find(g => g.id === 'nv:memory')!
    expect(memory.children?.map(c => c.label)).toEqual(['Vault Obsidian', 'Arsip sesi'])
  })
})
