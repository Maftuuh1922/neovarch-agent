/**
 * One look for an agent on desktop and phone (agent-identity-spec.md):
 * a circle in the agent's coat colour (hash of the agent id), the initial of
 * its display name in white, and an optional status dot bottom-right.
 * Names always come from the core's office snapshot, never invented here.
 */
import { useStore } from '@nanostores/react'

import mascotAnimated from '@/assets/neovarch/neovarch-avatar-128.webp'
import mascotStatic from '@/assets/neovarch/neovarch-avatar-128-static.png'
import { cn } from '@/lib/utils'

import { coatFor, OFFICE3D_STATUS, type SceneStatus, sceneStatusOf } from './office3d-model'
import { $office, type OfficeAgent, type OfficeSnapshot } from './office-store'

/** First user-perceived character of the name, upper-cased; '?' when empty. */
export function initialOf(name: string): string {
  const trimmed = name.trim()

  if (!trimmed) {
    return '?'
  }

  let first = Array.from(trimmed)[0]!

  if (typeof Intl !== 'undefined' && 'Segmenter' in Intl) {
    const segments = new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(trimmed)
    const head = segments[Symbol.iterator]().next().value

    first = head?.segment ?? first
  }

  return first.toLocaleUpperCase()
}

/** The office agent whose session is `sessionId` (`id == "session:" + sessionId`). */
export function agentForSession(office: null | OfficeSnapshot, ...sessionIds: (null | string | undefined)[]) {
  if (!office) {
    return null
  }

  for (const sid of sessionIds) {
    if (!sid) {
      continue
    }

    const hit = office.agents.find(agent => agent.session_id === sid || agent.id === `session:${sid}`)

    if (hit) {
      return hit
    }
  }

  return null
}

/** True when `messageId` is the first assistant message after the latest user
 *  message before it, i.e. the one that opens an agent turn. A turn can span
 *  several assistant messages (tool rounds); the sender pill shows once. */
export function opensAgentTurn(messages: readonly { id: string; role: string }[], messageId: string): boolean {
  const index = messages.findIndex(message => message.id === messageId)

  if (index < 0 || messages[index]!.role !== 'assistant') {
    return false
  }

  const prev = messages[index - 1]

  return !prev || prev.role !== 'assistant'
}

export const STATUS_WORD: Record<SceneStatus, string> = {
  error: 'galat',
  idle: 'santai',
  waiting: 'menunggu persetujuan',
  working: 'bekerja'
}

export function AgentAvatar({
  className,
  id,
  name,
  size = 32,
  status
}: {
  className?: string
  id: string
  name: string
  size?: number
  /** Omit for no status dot (e.g. the chat sender pill). */
  status?: SceneStatus
}) {
  const dot = Math.max(7, Math.round(size * 0.34))

  return (
    <span
      aria-hidden="true"
      className={cn('nv-agent-avatar', className)}
      data-nv-agent-avatar={id}
      style={{ background: coatFor(id), fontSize: size * 0.46, height: size, width: size }}
    >
      {initialOf(name)}
      {status && (
        <i
          className="nv-agent-avatar-dot"
          data-status={status}
          style={{
            background: OFFICE3D_STATUS[status].color,
            height: dot,
            left: size * 0.85 - dot / 2,
            top: size * 0.85 - dot / 2,
            width: dot
          }}
        />
      )}
    </span>
  )
}

/** Avatar for an office agent, status dot included. */
export function OfficeAgentAvatar({
  agent,
  className,
  feed,
  size = 32
}: {
  agent: OfficeAgent
  className?: string
  feed?: OfficeSnapshot['feed']
  size?: number
}) {
  return (
    <AgentAvatar className={className} id={agent.id} name={agent.name} size={size} status={sceneStatusOf(agent, feed)} />
  )
}

/** Glass pill above an agent turn: avatar 18 + "NAME · PC" + a pulse while it streams.
 *  Without an office agent for the session: the Neovarch mascot + "NEOVARCH · PC". */
export function AgentSenderPill({ live = false, sessionIds }: { live?: boolean; sessionIds: (null | string)[] }) {
  const office = useStore($office)
  const agent = agentForSession(office, ...sessionIds)
  const pc = office?.host ? ` · ${office.host}` : ''

  return (
    <div className="nv-sender-pill" data-live={live || undefined} data-slot="nv-sender-pill">
      {agent ? (
        <AgentAvatar id={agent.id} name={agent.name} size={18} />
      ) : (
        <NeovarchMascot live={live} size={18} />
      )}
      <span className="nv-sender-label">{`${agent?.name ?? 'Neovarch'}${pc}`}</span>
      {live && <i aria-hidden="true" className="nv-sender-live" />}
    </div>
  )
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false
}

/** The Neovarch mascot (v1.4.7, replaces the orange "N"): the animated
 *  thinking loop only while the agent's turn runs, the still frame when idle,
 *  done or failed — and always still under prefers-reduced-motion. Same assets
 *  as the phone (assets/brand/neovarch_avatar_128*.{webp,png}). */
export function NeovarchMascot({ live = false, size = 18 }: { live?: boolean; size?: number }) {
  const animate = live && !prefersReducedMotion()

  return (
    <img
      alt=""
      aria-hidden="true"
      className="nv-sender-mark nv-sender-mascot"
      data-animated={animate || undefined}
      draggable={false}
      height={size}
      src={animate ? mascotAnimated : mascotStatic}
      style={{ height: size, width: size }}
      width={size}
    />
  )
}
