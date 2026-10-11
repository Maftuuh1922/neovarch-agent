import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.fn()

vi.mock('@/api/client', () => ({ hermesApi: (req: { body?: unknown; method?: string; path: string }) => api(req) }))
vi.mock('@/contrib/events', () => ({ onGatewayEvent: () => () => undefined }))

const status = {
  client_id_configured: true,
  gist_id: 'g1',
  gist_url: 'https://gist.github.com/g1',
  last_error: null,
  last_published_at: new Date(Date.now() - 120_000).toISOString(),
  login: 'aku',
  login_flow: { state: 'idle' },
  settings: {
    github_client_id: 'Iv1.x',
    include_github_contributions: true,
    paused: false,
    publish_heatmap: true,
    publish_stack: true,
    publish_status: true,
    share_project: false
  },
  signed_in: true,
  token_storage: 'keychain'
}

const counts = Array.from({ length: 365 }, (_, i) => (i % 7 === 0 ? 4 : i % 3 === 0 ? 1 : 0))

const profile = {
  avatar_url: null,
  bio: 'ngoding tiap hari',
  heatmap: { active_days: 150, counts, days: 365, end: '2026-10-09', max: 4, start: '2025-10-10', streak: 1, total: 300 },
  html_url: 'https://github.com/aku',
  login: 'aku',
  name: 'Aku Dev',
  publish: { paused: false },
  stack: {
    languages: [
      { name: 'Python', share: 0.6, source: 'both' },
      { name: 'TypeScript', share: 0.4, source: 'agent' }
    ],
    tools: [{ count: 9, name: 'shell', share: 1 }]
  },
  status: { coding: true, last_active_at: new Date().toISOString(), project: null }
}

const friends = {
  counts: { coding: 1, followers: 3, following: 3, friends: 3 },
  friends: [
    { avatar_url: null, bio: '', coding: false, has_neovarch: false, html_url: '', last_active_at: null, login: 'zed', name: 'Zed', project: null, top_stack: [] },
    { avatar_url: null, bio: '', coding: true, has_neovarch: true, html_url: '', last_active_at: new Date().toISOString(), login: 'budi', name: 'Budi', project: 'toko', top_stack: ['Dart'] },
    { avatar_url: null, bio: '', coding: false, has_neovarch: true, html_url: '', last_active_at: new Date(Date.now() - 3_600_000).toISOString(), login: 'sari', name: 'Sari', project: null, top_stack: ['Go'] }
  ],
  pending: [{ avatar_url: null, login: 'tono' }],
  signed_in: true
}

function routes(overrides: Record<string, unknown> = {}) {
  api.mockImplementation(async ({ method = 'GET', path }: { method?: string; path: string }) => {
    const key = `${method} ${path.split('?')[0]}`

    if (key in overrides) {
      const v = overrides[key]

      return typeof v === 'function' ? (v as () => unknown)() : v
    }

    switch (key) {
      case 'GET /api/social/status':
        return status
      case 'GET /api/social/profile':
        return profile
      case 'GET /api/social/friends':
        return friends
      case 'GET /api/social/friends/budi':
        return { ...friends.friends[1], follows_you: true, following: true, mutual: true, profile: { ...profile, login: 'budi', name: 'Budi' } }
      case 'GET /api/social/search':
        return { items: [{ avatar_url: null, follows_you: true, following: false, login: 'rina' }] }
      case 'POST /api/social/follow':
        return { mutual: true }
      case 'DELETE /api/social/follow/budi':
        return { ok: true }
      case 'PUT /api/social/settings':
        return { ...status.settings, paused: true }
      default:
        return {}
    }
  })
}

async function renderPage() {
  const mod = await import('./social')
  const store = await import('./social-store')
  store.$socialStatus.set(null)
  store.$socialProfile.set(null)
  store.$socialFriends.set(null)
  await store.refreshSocial()
  render(<mod.NeovarchSocialPage />)

  return store
}

describe('Profil & Teman', () => {
  beforeEach(() => {
    api.mockReset()
    window.hermesDesktop = { ...(window.hermesDesktop ?? {}), openExternal: vi.fn() } as never
  })
  afterEach(() => cleanup())

  it('sorts friends with "lagi ngoding" first, then Neovarch users by recency', async () => {
    const { sortFriends } = await import('./social-store')
    expect(sortFriends(friends.friends as never).map(f => f.login)).toEqual(['budi', 'sari', 'zed'])
  })

  it('buckets heatmap levels and lays days out in Sunday-first weeks', async () => {
    const { heatLevel, heatmapWeeks } = await import('./social-store')
    expect([0, 1, 2, 3, 4].map(c => heatLevel(c, 4))).toEqual([0, 1, 2, 3, 4])
    expect(heatLevel(5, 0)).toBe(0)
    const weeks = heatmapWeeks({ counts: [1, 2, 3], start: '2026-10-07' }) // a Wednesday
    expect(weeks).toHaveLength(1)
    expect(weeks[0]!.slice(0, 3).every(c => c.count === -1)).toBe(true)
    expect(weeks[0]![3]).toEqual({ count: 1, date: '2026-10-07' })
  })

  it('renders the profile card: heatmap in 365 cells, stack chips, coding status and friends', async () => {
    routes()
    await renderPage()
    expect(await screen.findByText('Aku Dev')).toBeTruthy()
    expect(screen.getByText('ngoding tiap hari')).toBeTruthy()
    const cells = document.querySelectorAll('[data-slot="nv-heatmap"] .nv-social-heatmap-grid .nv-social-cell:not([data-level="pad"])')
    expect(cells).toHaveLength(365)
    expect(document.querySelectorAll('.nv-social-heatmap-grid [data-level="4"]').length).toBeGreaterThan(40)
    expect(screen.getByText('Python')).toBeTruthy()
    expect(screen.getAllByText('Lagi ngoding').length).toBeGreaterThan(0)
    await waitFor(() => expect(document.querySelectorAll('[data-nv-friend]')).toHaveLength(3))
    expect([...document.querySelectorAll('[data-nv-friend]')].map(e => e.getAttribute('data-nv-friend'))).toEqual(['budi', 'sari', 'zed'])
    expect(screen.getByText('Lagi ngoding · toko')).toBeTruthy()
    expect(screen.getByText('Belum pakai Neovarch')).toBeTruthy()
    expect(screen.getByText('Menunggu follow balik')).toBeTruthy()
  })

  it('opens a friend, and unfriending asks for confirmation before unfollowing', async () => {
    routes()
    await renderPage()
    fireEvent.click(await screen.findByText('Budi', { selector: '.nv-social-friend-name' }))
    expect(await screen.findByText('Hapus teman')).toBeTruthy()
    fireEvent.click(screen.getByText('Hapus teman'))
    expect(screen.getByText(/Hapus budi dari teman\?/)).toBeTruthy()
    expect(api.mock.calls.some(([r]) => r.method === 'DELETE')).toBe(false)
    await act(async () => {
      fireEvent.click(screen.getByText('Ya, unfollow'))
    })
    await waitFor(() =>
      expect(api.mock.calls.some(([r]) => r.method === 'DELETE' && r.path === '/api/social/follow/budi')).toBe(true)
    )
  })

  it('adds a friend by searching a GitHub username and following', async () => {
    routes()
    await renderPage()
    const input = await screen.findByPlaceholderText('Cari username GitHub…')
    fireEvent.change(input, { target: { value: 'rina' } })
    await act(async () => {
      fireEvent.submit(input.closest('form')!)
    })
    fireEvent.click(await screen.findByText('Follow'))
    await waitFor(() =>
      expect(api.mock.calls.some(([r]) => r.method === 'POST' && r.path === '/api/social/follow' && (r.body as { login: string }).login === 'rina')).toBe(true)
    )
    expect(await screen.findByText('Di-follow')).toBeTruthy()
  })

  it('privacy toggles save settings', async () => {
    routes()
    await renderPage()
    const pause = await screen.findByLabelText('Jeda publikasi')
    await act(async () => {
      fireEvent.click(pause)
    })
    await waitFor(() =>
      expect(api.mock.calls.some(([r]) => r.method === 'PUT' && (r.body as { paused?: boolean }).paused === true)).toBe(true)
    )
  })

  it('signed out: asks for the OAuth client id, then shows the device code', async () => {
    let configured = false
    routes({
      'GET /api/social/status': () => ({ ...status, client_id_configured: configured, signed_in: false }),
      'POST /api/social/login': { state: 'pending', user_code: 'ABCD-1234', verification_uri: 'https://github.com/login/device' },
      'PUT /api/social/settings': () => {
        configured = true

        return { ...status.settings, github_client_id: 'Ov23liabcdef' }
      }
    })
    await renderPage()
    expect(await screen.findByText('Client ID OAuth App GitHub belum diatur.')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('Ov23li…'), { target: { value: 'Ov23liabcdef' } })
    await act(async () => {
      fireEvent.click(screen.getByText('Simpan'))
    })
    // Saving the client id goes straight on to the GitHub device flow.
    expect(await screen.findByText('ABCD-1234')).toBeTruthy()
    expect(window.hermesDesktop.openExternal).toHaveBeenCalledWith('https://github.com/login/device')
  })

  it('signed out: Simpan is never silently disabled — a bad client id gets a message', async () => {
    routes({
      'GET /api/social/status': () => ({ ...status, client_id_configured: false, signed_in: false })
    })
    await renderPage()
    await screen.findByText('Client ID OAuth App GitHub belum diatur.')
    const save = screen.getByText('Simpan').closest('button') as HTMLButtonElement
    expect(save.disabled).toBe(false)
    await act(async () => {
      fireEvent.click(save)
    })
    expect(await screen.findByText('Tempel Client ID dulu.')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('Ov23li…'), { target: { value: 'abc def ghi' } })
    await act(async () => {
      fireEvent.click(save)
    })
    expect(await screen.findByText('Client ID tidak boleh berisi spasi.')).toBeTruthy()
    expect(api.mock.calls.some(([r]) => r.method === 'PUT')).toBe(false)
  })

  it('signed out with a built-in client id: one-click sign in, manual id is an advanced override', async () => {
    routes({
      'GET /api/social/status': () => ({
        ...status,
        client_id_configured: true,
        client_id_source: 'default',
        settings: { ...status.settings, github_client_id: '', github_client_id_source: 'default' },
        signed_in: false
      }),
      'POST /api/social/login': { state: 'pending', user_code: 'WXYZ-0000', verification_uri: 'https://github.com/login/device' }
    })
    await renderPage()
    expect(await screen.findByText('Masuk dengan GitHub')).toBeTruthy()
    expect(screen.queryByText('Client ID OAuth App GitHub belum diatur.')).toBeNull()
    expect(screen.queryByPlaceholderText('Ov23li…')).toBeNull()
    fireEvent.click(screen.getByText('Pakai Client ID sendiri (lanjutan)'))
    expect(screen.getByPlaceholderText('Ov23li…')).toBeTruthy()
  })
})
