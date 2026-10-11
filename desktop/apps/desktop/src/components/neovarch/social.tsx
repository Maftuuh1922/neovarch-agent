import { useStore } from '@nanostores/react'
import { type FormEvent, useEffect, useState } from 'react'

import { socialT as t } from '@/i18n/neovarch-social'
import { cn } from '@/lib/utils'

import { ShareProfileDialog } from './share-dialog'

import {
  $socialError,
  $socialFriends,
  $socialProfile,
  $socialStatus,
  type CodingStatus,
  type FriendCard,
  type FriendDetail,
  clientIdProblem,
  followUser,
  friendDetail,
  type Heatmap,
  heatLevel,
  heatmapWeeks,
  logoutGithub,
  pollLogin,
  publishNow,
  refreshSocial,
  relativeIso,
  saveSocialSettings,
  searchGithubUsers,
  type SearchItem,
  type SocialProfile,
  type SocialSettings,
  type StackItem,
  startGithubLogin,
  unfollowUser
} from './social-store'
import { TechLogo, TechStackChips } from './tech-logo'

function openExternal(url: string) {
  void window.hermesDesktop?.openExternal?.(url)
}

function Avatar({ name, size = 'md', url }: { name: string; size?: 'lg' | 'md' | 'sm'; url?: null | string }) {
  return url ? (
    <img alt="" className={cn('nv-social-avatar', `nv-social-avatar-${size}`)} src={url} />
  ) : (
    <span className={cn('nv-social-avatar', `nv-social-avatar-${size}`)}>{(name[0] || '?').toUpperCase()}</span>
  )
}

export function CodingBadge({ status }: { status?: CodingStatus | null }) {
  const coding = Boolean(status?.coding)

  return (
    <span className="nv-social-status" data-coding={coding ? 'true' : 'false'}>
      <span aria-hidden="true" className="nv-social-dot" data-coding={coding ? 'true' : 'false'} />
      {coding
        ? status?.project
          ? t('codingIn', { project: status.project })
          : t('codingNow')
        : status?.last_active_at
          ? t('lastActive', { when: relativeIso(status.last_active_at) })
          : t('idle')}
    </span>
  )
}

/** GitHub-style contribution grid in the accent colour (flat cells, 5 levels). */
export function HeatmapGrid({ heatmap }: { heatmap: Heatmap }) {
  const weeks = heatmapWeeks(heatmap)

  return (
    <figure className="nv-social-heatmap" data-slot="nv-heatmap">
      <div aria-label={t('heatmapTitle')} className="nv-social-heatmap-grid" role="img">
        {weeks.map((week, wi) => (
          <div className="nv-social-heatmap-col" key={wi}>
            {week.map((cell, di) => (
              <span
                className="nv-social-cell"
                data-level={cell.count < 0 ? 'pad' : heatLevel(cell.count, heatmap.max)}
                key={di}
                title={cell.count < 0 ? undefined : t('heatmapCell', { count: cell.count, date: cell.date })}
              />
            ))}
          </div>
        ))}
      </div>
      <figcaption className="nv-social-heatmap-foot">
        <span>
          {t('heatmapSummary', { days: heatmap.active_days, streak: heatmap.streak, total: heatmap.total })}
        </span>
        <span className="nv-social-legend">
          {t('heatmapLegendLess')}
          {[0, 1, 2, 3, 4].map(l => (
            <span className="nv-social-cell" data-level={l} key={l} />
          ))}
          {t('heatmapLegendMore')}
        </span>
      </figcaption>
    </figure>
  )
}

export function StackChips({ items }: { items: StackItem[] }) {
  if (!items.length) {
    return <p className="nv-social-muted">{t('stackEmpty')}</p>
  }

  return (
    <ul className="nv-social-chips">
      {items.map(item => (
        <li className="nv-social-chip" data-source={item.source} key={item.name}>
          {item.name}
          <span className="nv-social-chip-share">{Math.round(item.share * 100)}%</span>
        </li>
      ))}
    </ul>
  )
}

function LoginCard() {
  const status = useStore($socialStatus)
  const [clientId, setClientId] = useState('')
  const [error, setError] = useState<null | string>(null)
  const [saving, setSaving] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const flow = status?.login_flow
  const pending = flow?.state === 'pending'

  useEffect(() => {
    if (!pending) {
      return
    }

    const timer = window.setInterval(() => void pollLogin().catch(() => undefined), 3000)

    return () => window.clearInterval(timer)
  }, [pending])

  async function begin() {
    setError(null)

    try {
      const res = await startGithubLogin()

      if (res.verification_uri) {
        openExternal(res.verification_uri)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function saveClientId(event: FormEvent) {
    event.preventDefault()
    const problem = clientIdProblem(clientId)

    if (problem) {
      setError(problem)

      return
    }

    setError(null)
    setSaving(true)

    try {
      await saveSocialSettings({ github_client_id: clientId.trim() })
      setClientId('')
      setAdvanced(false)
      // Saving the ID is only half of it — go straight on to "Masuk dengan GitHub".
      await begin()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const clientIdForm = (
    <form className="nv-social-clientid" data-slot="nv-social-clientid" onSubmit={saveClientId}>
      <label className="nv-social-field">
        <span>{t('clientIdLabel')}</span>
        <input
          autoComplete="off"
          onChange={e => {
            setClientId(e.target.value)
            setError(null)
          }}
          placeholder="Ov23li…"
          spellCheck={false}
          value={clientId}
        />
      </label>
      <button className="nv-social-btn nv-social-btn-primary" disabled={saving} type="submit">
        {saving ? 'Menyimpan…' : t('clientIdSave')}
      </button>
    </form>
  )

  return (
    <section className="nv-social-card nv-social-login" data-slot="nv-social-login">
      <h2 className="nv-social-h2">{t('signedOutTitle')}</h2>
      <p className="nv-social-muted">{t('signedOutBody')}</p>
      {status && !status.client_id_configured ? (
        <>
          <p className="nv-social-warn">{t('noClientId')}</p>
          <p className="nv-social-muted">{t('noClientIdHelp')}</p>
          {clientIdForm}
        </>
      ) : pending ? (
        <div className="nv-social-device">
          <p>{t('deviceStep1', { url: flow?.verification_uri || 'github.com/login/device' })}</p>
          <code className="nv-social-code" data-slot="nv-device-code">
            {flow?.user_code}
          </code>
          <div className="nv-social-row">
            <button
              className="nv-social-btn"
              onClick={() => void navigator.clipboard?.writeText(flow?.user_code || '')}
              type="button"
            >
              {t('copyCode')}
            </button>
            <button
              className="nv-social-btn"
              onClick={() => openExternal(flow?.verification_uri || 'https://github.com/login/device')}
              type="button"
            >
              {t('openGithub')}
            </button>
          </div>
          <p className="nv-social-muted">{t('signingIn')}</p>
        </div>
      ) : (
        <>
          <button className="nv-social-btn nv-social-btn-primary" onClick={() => void begin()} type="button">
            {t('signIn')}
          </button>
          <button
            className="nv-social-btn nv-social-btn-ghost nv-social-btn-sm"
            data-slot="nv-social-clientid-toggle"
            onClick={() => setAdvanced(v => !v)}
            type="button"
          >
            {advanced ? 'Tutup' : status?.client_id_source === 'config' ? 'Ganti Client ID (lanjutan)' : 'Pakai Client ID sendiri (lanjutan)'}
          </button>
          {advanced && clientIdForm}
        </>
      )}
      {(error || flow?.error) && (
        <p className="nv-social-warn" role="alert">
          {error || flow?.error}
        </p>
      )}
    </section>
  )
}

function Toggle({
  checked,
  label,
  onChange
}: {
  checked: boolean
  label: string
  onChange: (value: boolean) => void
}) {
  return (
    <label className="nv-social-toggle">
      <input checked={checked} onChange={e => onChange(e.target.checked)} role="switch" type="checkbox" />
      <span>{label}</span>
    </label>
  )
}

function PrivacyCard() {
  const status = useStore($socialStatus)
  const profile = useStore($socialProfile)
  const [busy, setBusy] = useState(false)

  if (!status) {
    return null
  }

  const s = status.settings
  const set = (key: keyof SocialSettings) => (value: boolean) => void saveSocialSettings({ [key]: value })

  return (
    <section className="nv-social-card" data-slot="nv-social-privacy">
      <h2 className="nv-social-h2">{t('privacyTitle')}</h2>
      <Toggle checked={s.publish_heatmap} label={t('publishHeatmap')} onChange={set('publish_heatmap')} />
      <Toggle checked={s.publish_stack} label={t('publishStack')} onChange={set('publish_stack')} />
      <Toggle checked={s.publish_status} label={t('publishStatus')} onChange={set('publish_status')} />
      <Toggle checked={s.share_project} label={t('shareProject')} onChange={set('share_project')} />
      <Toggle
        checked={s.include_github_contributions}
        label={t('includeContrib')}
        onChange={set('include_github_contributions')}
      />
      <Toggle checked={s.paused} label={t('paused')} onChange={set('paused')} />
      <p className="nv-social-muted">
        {status.last_published_at
          ? t('publishedAt', { when: relativeIso(status.last_published_at) })
          : t('neverPublished')}
        {status.gist_url && (
          <>
            {' · '}
            <button className="nv-social-link" onClick={() => openExternal(status.gist_url!)} type="button">
              {t('gistLink')}
            </button>
          </>
        )}
      </p>
      {(profile?.publish?.error || status.last_error) && (
        <p className="nv-social-warn">{profile?.publish?.error || status.last_error}</p>
      )}
      <div className="nv-social-row">
        <button
          className="nv-social-btn"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            void publishNow().finally(() => setBusy(false))
          }}
          type="button"
        >
          {t('publishNow')}
        </button>
        <button className="nv-social-btn nv-social-btn-ghost" onClick={() => void logoutGithub()} type="button">
          {t('signOut')}
        </button>
      </div>
    </section>
  )
}

export function ProfileCard({ onShare, profile }: { onShare?: () => void; profile: null | SocialProfile }) {
  if (!profile) {
    return null
  }

  return (
    <section className="nv-social-card nv-social-profile" data-slot="nv-social-profile">
      <header className="nv-social-profile-head">
        <Avatar name={profile.name || profile.login || '?'} size="lg" url={profile.avatar_url} />
        <div className="min-w-0">
          <h2 className="nv-social-name">{profile.name || profile.login}</h2>
          {profile.login && <p className="nv-social-login-name">@{profile.login}</p>}
          {profile.bio && <p className="nv-social-bio">{profile.bio}</p>}
          <CodingBadge status={profile.status} />
        </div>
        {onShare && (
          <button className="nv-social-btn nv-social-share-btn" data-slot="nv-share-open" onClick={onShare} type="button">
            {t('share')}
          </button>
        )}
      </header>
      {profile.heatmap && (
        <>
          <h3 className="nv-social-h3">{t('heatmapTitle')}</h3>
          <HeatmapGrid heatmap={profile.heatmap} />
        </>
      )}
      {profile.stack && (
        <>
          <h3 className="nv-social-h3">{t('stackTitle')}</h3>
          <TechStackChips items={profile.stack.languages} />
          {profile.stack.tools?.length > 0 && (
            <>
              <h3 className="nv-social-h3">{t('toolsTitle')}</h3>
              <StackChips items={profile.stack.tools.slice(0, 6)} />
            </>
          )}
        </>
      )}
    </section>
  )
}

export function FriendRow({ friend, onOpen }: { friend: FriendCard; onOpen: (login: string) => void }) {
  return (
    <li>
      <button
        className="nv-social-friend"
        data-coding={friend.coding ? 'true' : 'false'}
        data-nv-friend={friend.login}
        onClick={() => onOpen(friend.login)}
        type="button"
      >
        <span className="nv-social-avatar-wrap">
          <Avatar name={friend.name} url={friend.avatar_url} />
          <span aria-hidden="true" className="nv-social-dot nv-social-dot-badge" data-coding={String(friend.coding)} />
        </span>
        <span className="nv-social-friend-text">
          <span className="nv-social-friend-name">{friend.name}</span>
          <span className="nv-social-friend-sub">
            {friend.coding
              ? friend.project
                ? t('codingIn', { project: friend.project })
                : t('codingNow')
              : friend.has_neovarch
                ? friend.last_active_at
                  ? t('lastActive', { when: relativeIso(friend.last_active_at) })
                  : t('idle')
                : t('noNeovarch')}
          </span>
        </span>
        {friend.top_stack.length > 0 && (
          <span className="nv-social-friend-stack" title={friend.top_stack.join(' · ')}>
            {friend.top_stack.slice(0, 4).map(n => (
              <TechLogo key={n} name={n} size={14} />
            ))}
          </span>
        )}
      </button>
    </li>
  )
}

function AddFriend() {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<SearchItem[]>([])
  const [error, setError] = useState<null | string>(null)

  async function search(event: FormEvent) {
    event.preventDefault()
    setError(null)

    try {
      setItems((await searchGithubUsers(q)).items)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function follow(login: string) {
    try {
      await followUser(login)
      setItems(list => list.map(i => (i.login === login ? { ...i, following: true } : i)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="nv-social-add" data-slot="nv-social-add">
      <form className="nv-social-search" onSubmit={search}>
        <input
          aria-label={t('addFriend')}
          onChange={e => setQ(e.target.value)}
          placeholder={t('searchPlaceholder')}
          value={q}
        />
        <button className="nv-social-btn" disabled={!q.trim()} type="submit">
          {t('addFriend')}
        </button>
      </form>
      {items.length > 0 && (
        <ul className="nv-social-results">
          {items.map(item => (
            <li className="nv-social-result" key={item.login}>
              <Avatar name={item.login} size="sm" url={item.avatar_url} />
              <span className="nv-social-friend-name">{item.login}</span>
              {item.follows_you && <span className="nv-social-tag">{t('followsYou')}</span>}
              <button
                className="nv-social-btn nv-social-btn-sm"
                disabled={item.following}
                onClick={() => void follow(item.login)}
                type="button"
              >
                {item.following ? t('following') : t('follow')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="nv-social-warn">{error}</p>}
    </div>
  )
}

function FriendDetailView({ login, onBack }: { login: string; onBack: () => void }) {
  const [detail, setDetail] = useState<FriendDetail | null>(null)
  const [error, setError] = useState<null | string>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let alive = true
    setDetail(null)
    friendDetail(login)
      .then(d => alive && setDetail(d))
      .catch(e => alive && setError(e instanceof Error ? e.message : String(e)))

    return () => {
      alive = false
    }
  }, [login])

  const profile = detail
    ? {
        ...(detail.profile ?? {}),
        avatar_url: detail.profile?.avatar_url ?? detail.avatar_url,
        bio: detail.bio,
        html_url: detail.html_url,
        login: detail.login,
        name: detail.name,
        status: detail.profile?.status ?? { coding: detail.coding, last_active_at: detail.last_active_at }
      }
    : null

  return (
    <div className="nv-social-detail" data-slot="nv-social-detail">
      <div className="nv-social-row">
        <button className="nv-social-btn nv-social-btn-ghost" onClick={onBack} type="button">
          ← {t('back')}
        </button>
        {detail && (
          <button className="nv-social-btn" onClick={() => openExternal(detail.html_url)} type="button">
            {t('openProfile')}
          </button>
        )}
      </div>
      {error && <p className="nv-social-warn">{t('error', { message: error })}</p>}
      {!detail && !error && <p className="nv-social-muted">{t('loading')}</p>}
      {profile && <ProfileCard profile={profile as SocialProfile} />}
      {detail && !detail.has_neovarch && <p className="nv-social-muted">{t('noNeovarch')}</p>}
      {detail?.following && (
        <div className="nv-social-danger">
          {confirming ? (
            <>
              <p>{t('unfriendConfirm', { login: detail.login })}</p>
              <div className="nv-social-row">
                <button
                  className="nv-social-btn nv-social-btn-danger"
                  onClick={() => void unfollowUser(detail.login).then(onBack)}
                  type="button"
                >
                  {t('unfriendYes')}
                </button>
                <button className="nv-social-btn nv-social-btn-ghost" onClick={() => setConfirming(false)} type="button">
                  {t('cancel')}
                </button>
              </div>
            </>
          ) : (
            <button className="nv-social-btn nv-social-btn-ghost" onClick={() => setConfirming(true)} type="button">
              {t('unfriend')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** "Profil & Teman": your GitHub-backed profile card + friends (mutual follows). */
export function NeovarchSocialPage() {
  const status = useStore($socialStatus)
  const profile = useStore($socialProfile)
  const friends = useStore($socialFriends)
  const error = useStore($socialError)
  const [open, setOpen] = useState<null | string>(null)
  const [sharing, setSharing] = useState(false)

  return (
    <div className="nv-social" data-slot="nv-social">
      <header className="nv-social-header">
        <p className="nv-social-kicker">{t('kicker')}</p>
        <h1 className="nv-social-title">{t('title')}</h1>
        <p className="nv-social-sub">{t('sub')}</p>
      </header>
      {error && (
        <p className="nv-social-warn">
          {t('error', { message: error })}{' '}
          <button className="nv-social-link" onClick={() => void refreshSocial()} type="button">
            {t('retry')}
          </button>
        </p>
      )}
      {!status && !error && <p className="nv-social-muted">{t('loading')}</p>}
      {status && !status.signed_in && <LoginCard />}
      {sharing && profile && (
        <ShareProfileDialog gistUrl={status?.gist_url} onClose={() => setSharing(false)} profile={profile} />
      )}
      {status?.signed_in && (
        <div className="nv-social-body">
          <div className="nv-social-main">
            {open ? (
              <FriendDetailView login={open} onBack={() => setOpen(null)} />
            ) : (
              <>
                {profile ? (
                  <ProfileCard onShare={() => setSharing(true)} profile={profile} />
                ) : (
                  <p className="nv-social-muted">{t('loading')}</p>
                )}
                <PrivacyCard />
              </>
            )}
          </div>
          <aside className="nv-social-card nv-social-friends" data-slot="nv-social-friends">
            <h2 className="nv-social-h2">{t('friendsTitle')}</h2>
            {friends?.counts && (
              <p className="nv-social-muted">
                {t('friendsCount', { coding: friends.counts.coding, n: friends.counts.friends })}
              </p>
            )}
            <AddFriend />
            {friends && friends.friends.length === 0 && <p className="nv-social-muted">{t('friendsEmpty')}</p>}
            <ul className="nv-social-friend-list">
              {friends?.friends.map(f => <FriendRow friend={f} key={f.login} onOpen={setOpen} />)}
            </ul>
            {friends && friends.pending.length > 0 && (
              <>
                <h3 className="nv-social-h3">{t('pendingTitle')}</h3>
                <ul className="nv-social-pending">
                  {friends.pending.map(p => (
                    <li key={p.login}>
                      <Avatar name={p.login} size="sm" url={p.avatar_url} /> {p.login}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
