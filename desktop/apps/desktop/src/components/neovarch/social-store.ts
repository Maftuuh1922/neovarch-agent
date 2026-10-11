import { atom, onMount } from 'nanostores'

import { hermesApi } from '@/api/client'
import { onGatewayEvent } from '@/contrib/events'

/** Friends & profile via GitHub — data from the core's /api/social/* routes. */
export const SOCIAL_ROUTE = '/teman'

export interface SocialSettings {
  github_client_id: string
  /** Where the active client ID comes from: the user's override, env, or the built-in default. */
  github_client_id_source?: 'config' | 'default' | 'env' | 'none'
  include_github_contributions: boolean
  paused: boolean
  publish_heatmap: boolean
  publish_stack: boolean
  publish_status: boolean
  share_project: boolean
}

export interface LoginFlow {
  error?: string
  expires_at?: number
  login?: string
  state: 'done' | 'error' | 'idle' | 'pending'
  user_code?: string
  verification_uri?: string
}

export interface SocialStatus {
  client_id_configured: boolean
  client_id_source?: 'config' | 'default' | 'env' | 'none'
  gist_id: null | string
  gist_url: null | string
  last_error: null | string
  last_published_at: null | string
  login: null | string
  login_flow: LoginFlow
  settings: SocialSettings
  signed_in: boolean
  token_storage: string
}

export interface Heatmap {
  active_days: number
  agent?: number[]
  counts: number[]
  days: number
  end: string
  github?: null | number[]
  max: number
  start: string
  streak: number
  total: number
}

export interface StackItem {
  count?: number
  name: string
  share: number
  source?: 'agent' | 'both' | 'github'
}

export interface CodingStatus {
  coding: boolean
  last_active_at: null | string
  project?: null | string
}

export interface SocialProfile {
  avatar_url: null | string
  bio: string
  heatmap?: Heatmap
  html_url: null | string
  login: null | string
  name: null | string
  publish?: { error?: null | string; gist_url?: null | string; last_published_at?: null | string; paused: boolean }
  stack?: { languages: StackItem[]; tools: StackItem[] }
  status?: CodingStatus
}

export interface FriendCard {
  avatar_url: null | string
  bio: string
  coding: boolean
  has_neovarch: boolean
  html_url: string
  last_active_at: null | string
  login: string
  name: string
  project: null | string
  top_stack: string[]
}

export interface FriendDetail extends FriendCard {
  follows_you: boolean
  following: boolean
  mutual: boolean
  profile: (SocialProfile & { gist_url?: string }) | null
}

export interface FriendsResponse {
  counts?: { coding: number; followers: number; following: number; friends: number }
  friends: FriendCard[]
  pending: { avatar_url: null | string; login: string }[]
  signed_in: boolean
}

export interface SearchItem {
  avatar_url: null | string
  follows_you: boolean
  following: boolean
  login: string
}

export const $socialStatus = atom<null | SocialStatus>(null)
export const $socialProfile = atom<null | SocialProfile>(null)
export const $socialFriends = atom<FriendsResponse | null>(null)
export const $socialError = atom<null | string>(null)

const AVATAR_KEY = 'nv.social.avatar'

function storedAvatar(): null | string {
  try {
    return window.localStorage?.getItem(AVATAR_KEY) || null
  } catch {
    return null
  }
}

/** The signed-in GitHub avatar for the rail (remembered across launches, cleared on sign-out). */
export const $socialAvatar = atom<null | string>(storedAvatar())

function rememberAvatar(url: null | string) {
  $socialAvatar.set(url)

  try {
    if (url) {
      window.localStorage?.setItem(AVATAR_KEY, url)
    } else {
      window.localStorage?.removeItem(AVATAR_KEY)
    }
  } catch {
    // storage unavailable: keep the in-memory value
  }
}

const api = <T>(path: string, method = 'GET', body?: unknown) =>
  hermesApi<T>({ path, method, ...(body === undefined ? {} : { body }) })

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Friends first by "lagi ngoding", then Neovarch users, then most recently active. */
export function sortFriends(friends: FriendCard[]): FriendCard[] {
  return [...friends].sort((a, b) => {
    if (a.coding !== b.coding) {
      return a.coding ? -1 : 1
    }

    if (a.has_neovarch !== b.has_neovarch) {
      return a.has_neovarch ? -1 : 1
    }

    const ta = a.last_active_at ? Date.parse(a.last_active_at) : 0
    const tb = b.last_active_at ? Date.parse(b.last_active_at) : 0

    return tb - ta || a.login.localeCompare(b.login)
  })
}

export async function refreshSocial(): Promise<void> {
  try {
    const status = await api<SocialStatus>('/api/social/status')
    $socialStatus.set(status)
    $socialError.set(null)

    if (!status.signed_in) {
      $socialProfile.set(null)
      $socialFriends.set(null)
      rememberAvatar(null)

      return
    }

    const [profile, friends] = await Promise.all([
      api<SocialProfile>('/api/social/profile'),
      api<FriendsResponse>('/api/social/friends')
    ])

    $socialProfile.set(profile)
    rememberAvatar(profile.avatar_url)
    $socialFriends.set({ ...friends, friends: sortFriends(friends.friends) })
  } catch (error) {
    $socialError.set(message(error))
  }
}

export async function startGithubLogin(): Promise<LoginFlow> {
  const flow = await api<LoginFlow>('/api/social/login', 'POST', {})
  const status = $socialStatus.get()

  if (status) {
    $socialStatus.set({ ...status, login_flow: flow })
  }

  return flow
}

export async function pollLogin(): Promise<LoginFlow> {
  const flow = await api<LoginFlow>('/api/social/login')
  const status = $socialStatus.get()

  if (status) {
    $socialStatus.set({ ...status, login_flow: flow })
  }

  if (flow.state === 'done') {
    await refreshSocial()
  }

  return flow
}

export async function logoutGithub(): Promise<void> {
  await api('/api/social/logout', 'POST', {})
  await refreshSocial()
}

export async function saveSocialSettings(patch: Partial<SocialSettings>): Promise<void> {
  const settings = await api<SocialSettings>('/api/social/settings', 'PUT', patch)
  const status = $socialStatus.get()

  if (status) {
    const source = settings.github_client_id_source

    $socialStatus.set({
      ...status,
      client_id_configured: source ? source !== 'none' : Boolean(settings.github_client_id),
      client_id_source: source ?? status.client_id_source,
      settings
    })
  }
}

/** GitHub OAuth App client IDs: "Ov23li…" (new), "Iv1.…" (legacy) or 20 hex chars. */
export const GITHUB_CLIENT_ID_RE = /^[A-Za-z0-9._-]{8,64}$/

export function clientIdProblem(raw: string): null | string {
  const value = raw.trim()

  if (!value) {
    return 'Tempel Client ID dulu.'
  }

  if (/\s/.test(value)) {
    return 'Client ID tidak boleh berisi spasi.'
  }

  if (!GITHUB_CLIENT_ID_RE.test(value)) {
    return 'Format Client ID tidak valid (contoh: Ov23li…). Jangan tempel client secret.'
  }

  return null
}

export async function publishNow(): Promise<void> {
  await api('/api/social/publish', 'POST', {})
  await refreshSocial()
}

export function searchGithubUsers(q: string): Promise<{ items: SearchItem[] }> {
  return api(`/api/social/search?q=${encodeURIComponent(q)}`)
}

export async function followUser(login: string): Promise<{ mutual: boolean }> {
  const res = await api<{ mutual: boolean }>('/api/social/follow', 'POST', { login })
  void refreshSocial()

  return res
}

export async function unfollowUser(login: string): Promise<void> {
  await api(`/api/social/follow/${encodeURIComponent(login)}`, 'DELETE')
  await refreshSocial()
}

export function friendDetail(login: string): Promise<FriendDetail> {
  return api(`/api/social/friends/${encodeURIComponent(login)}`)
}

let lastBeat = 0

/** "Coding now" also counts typing in the desktop (composer, editor panes):
 *  one throttled heartbeat at most every 2 minutes. */
function editorHeartbeat() {
  const now = Date.now()

  if (now - lastBeat < 120_000 || !$socialStatus.get()?.signed_in) {
    return
  }

  lastBeat = now
  void api('/api/social/activity', 'POST', {}).catch(() => undefined)
}

onMount($socialStatus, () => {
  void refreshSocial()
  const offChanged = onGatewayEvent('social.changed', event => {
    const what = (event.payload as { what?: string } | undefined)?.what

    if (what === 'login') {
      void pollLogin().catch(() => undefined)
    }

    void refreshSocial()
  })
  const offReady = onGatewayEvent('gateway.ready', () => void refreshSocial())
  window.addEventListener('keydown', editorHeartbeat, { passive: true })

  return () => {
    offChanged()
    offReady()
    window.removeEventListener('keydown', editorHeartbeat)
  }
})

export function relativeIso(iso: null | string | undefined, now = Date.now()): string {
  if (!iso) {
    return '—'
  }

  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))

  if (s < 60) {
    return 'baru saja'
  }

  if (s < 3600) {
    return `${Math.round(s / 60)} mnt lalu`
  }

  if (s < 86400) {
    return `${Math.round(s / 3600)} jam lalu`
  }

  return `${Math.round(s / 86400)} hari lalu`
}

/** 0..4 intensity buckets relative to the busiest day (GitHub-style quartiles). */
export function heatLevel(count: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || max <= 0) {
    return 0
  }

  const r = count / max

  return r > 0.75 ? 4 : r > 0.5 ? 3 : r > 0.25 ? 2 : 1
}

/** Columns of 7 days (Sunday-first weeks) like GitHub's contribution graph. */
export function heatmapWeeks(hm: Pick<Heatmap, 'counts' | 'start'>): { count: number; date: string }[][] {
  const start = new Date(`${hm.start}T00:00:00`)
  const lead = start.getDay()
  const cells: ({ count: number; date: string } | null)[] = Array.from({ length: lead }, () => null)

  hm.counts.forEach((count, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    cells.push({ count, date })
  })

  const weeks: { count: number; date: string }[][] = []

  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7).map(c => c ?? { count: -1, date: '' }))
  }

  return weeks
}
