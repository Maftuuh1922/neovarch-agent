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
})
