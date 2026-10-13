import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { OBSIDIAN_VAULT_CHANGED_EVENT } from '@/app/settings/obsidian-vault-settings'

const api = vi.fn()
const navigate = vi.fn()

vi.mock('@/api/client', () => ({ hermesApi: (req: { path: string }) => api(req) }))
vi.mock('react-router', async importOriginal => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useNavigate: () => navigate
}))

import { NeovarchVaultPage, VAULT_SETTINGS_ROUTE } from './vault'

describe('Vault Obsidian page', () => {
  afterEach(() => cleanup())

  it('"Buka Pengaturan" deep-links to Settings ▸ Vault Obsidian and the page loads the vault after a save', async () => {
    let configured = false
    api.mockImplementation(async ({ path }: { path: string }) => {
      if (path.startsWith('/api/obsidian/tree')) {
        return configured
          ? {
              configured: true,
              path: '/v/Kuliah',
              tree: { children: [{ name: 'Skripsi', path: 'Skripsi.md', type: 'note' }], name: 'Kuliah', path: '', type: 'folder' },
              vault: 'Kuliah'
            }
          : { configured: false }
      }

      return configured ? { configured: true, edges: [], nodes: [] } : { configured: false, edges: [], nodes: [] }
    })

    render(<NeovarchVaultPage />)
    fireEvent.click(await screen.findByText('Buka Pengaturan'))
    expect(VAULT_SETTINGS_ROUTE).toBe('/settings?tab=obsidian')
    expect(navigate).toHaveBeenCalledWith('/settings?tab=obsidian')

    configured = true
    await act(async () => {
      window.dispatchEvent(new CustomEvent(OBSIDIAN_VAULT_CHANGED_EVENT))
    })
    expect(await screen.findByText('Kuliah')).toBeTruthy()
    expect(screen.queryByText('Buka Pengaturan')).toBeNull()
  })
  it('no vault yet: "Buat vault Neovarch" creates one, then the graph tab shows filters, legend and local mode', async () => {
    let configured = false
    const calls: { method?: string; path: string }[] = []
    api.mockReset()
    api.mockImplementation(async (req: { method?: string; path: string }) => {
      calls.push(req)
      const { path } = req

      if (path === '/api/obsidian/init') {
        configured = true

        return { vault: '/home/u/Neovarch Vault' }
      }

      if (path.startsWith('/api/obsidian/tree')) {
        return configured
          ? {
              configured: true,
              open_uri: 'obsidian://open?path=%2Fhome%2Fu%2FNeovarch%20Vault',
              path: '/home/u/Neovarch Vault',
              tree: { children: [{ name: 'Neovarch', path: 'Neovarch/Neovarch.md', type: 'note' }], name: 'Neovarch Vault', path: '', type: 'folder' },
              vault: 'Neovarch Vault'
            }
          : { configured: false }
      }

      if (path.startsWith('/api/obsidian/graph')) {
        return {
          configured,
          edges: [{ source: 'Neovarch/Neovarch.md', target: 'Neovarch/Proyek/toko.md' }],
          nodes: [
            { degree: 1, exists: true, id: 'Neovarch/Neovarch.md', kind: 'hub', tags: ['neovarch'], title: 'Neovarch' },
            { degree: 1, exists: true, id: 'Neovarch/Proyek/toko.md', kind: 'project', project: 'toko', tags: ['neovarch/proyek'], title: 'toko' }
          ]
        }
      }

      return {}
    })

    render(<NeovarchVaultPage />)
    fireEvent.click(await screen.findByText('Buat vault Neovarch'))
    expect(await screen.findByText('Neovarch Vault')).toBeTruthy()
    expect(calls.some(c => c.path === '/api/obsidian/init' && c.method === 'POST')).toBe(true)
    expect(document.querySelector('[data-nv-vault-open-app]')).toBeTruthy()

    fireEvent.click(document.querySelector('[data-nv-vault-tab="graph"]')!)
    expect(await screen.findByText('Semua tag')).toBeTruthy()
    expect(screen.getByText('Proyek')).toBeTruthy() // legend chip (colour group)
    expect(screen.getByText('Hub')).toBeTruthy()
    expect(document.querySelector('[data-nv-vault-graph]')!.getAttribute('data-nv-vault-graph')).toBe('2')
    expect((document.querySelector('[data-nv-vault-local]') as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getByText('Proyek')) // hide projects
    expect(document.querySelector('[data-nv-vault-graph]')!.getAttribute('data-nv-vault-graph')).toBe('1')
  })
})
