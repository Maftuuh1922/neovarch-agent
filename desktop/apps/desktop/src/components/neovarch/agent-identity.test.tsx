// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  AgentAvatar,
  agentForSession,
  AgentSenderPill,
  initialOf,
  opensAgentTurn,
} from './agent-identity'
import { coatFor } from './office3d-model'
import { $office, type OfficeAgent, type OfficeSnapshot } from './office-store'

const AGENT: OfficeAgent = {
  current_task: null,
  current_tool: null,
  id: 'session:s1',
  kind: 'session',
  last_activity: 0,
  last_activity_text: null,
  message_count: 0,
  model: 'gpt-mini',
  name: 'Raka',
  pending_approval: null,
  role: 'Agen utama',
  session_id: 's1',
  source: 'desktop',
  status: 'working',
  title: null,
}

function snapshot(agents: OfficeAgent[]): OfficeSnapshot {
  return {
    agents,
    counts: {
      idle: 0,
      total: agents.length,
      'waiting-approval': 0,
      working: agents.length,
    },
    feed: [],
    generated_at: 0,
    host: 'pc-rumah',
    kanban: {},
    seq: 1,
    vault: { configured: false, connected: false, note_count: 0, path: '' },
  }
}

afterEach(() => {
  cleanup()
  $office.set(null)
})

describe('agent identity (agent-identity-spec.md)', () => {
  it('uses the same coat hash as the phone (reference values)', () => {
    expect(coatFor('session:s1').toUpperCase()).toBe('#3A4A6E')
    expect(coatFor('session:s2').toUpperCase()).toBe('#7A2E2E')
    expect(coatFor('kanban:writer').toUpperCase()).toBe('#8A6A3A')
  })

  it('initial is the first grapheme, upper-cased, ? when empty', () => {
    expect(initialOf('raka')).toBe('R')
    expect(initialOf('  ')).toBe('?')
    expect(initialOf('élan')).toBe('É')
  })

  it('finds the office agent for a session by session_id or id', () => {
    const office = snapshot([AGENT])
    expect(agentForSession(office, null, 's1')?.name).toBe('Raka')
    expect(agentForSession(office, 'nope')).toBeNull()
    expect(agentForSession(null, 's1')).toBeNull()
  })

  it('avatar: coat fill, white initial, size-scaled glyph, optional status dot', () => {
    const { container } = render(
      <AgentAvatar id='session:s2' name='sari' size={40} status='working' />,
    )

    const el = container.querySelector('.nv-agent-avatar') as HTMLElement
    expect(el.textContent).toBe('S')
    expect(el.style.background).toBe('rgb(122, 46, 46)')
    expect(el.style.width).toBe('40px')
    expect(el.style.fontSize).toBe(`${40 * 0.46}px`)
    expect(container.querySelector('.nv-agent-avatar-dot')).not.toBeNull()
  })

  it('sender pill: agent name + host, Neovarch mark without an agent', () => {
    $office.set(snapshot([AGENT]))
    const { rerender } = render(<AgentSenderPill live sessionIds={['s1']} />)
    expect(screen.getByText('Raka · pc-rumah')).toBeTruthy()
    expect(document.querySelector('.nv-sender-live')).not.toBeNull()
    expect(document.querySelector('.nv-agent-avatar-dot')).toBeNull()
    rerender(<AgentSenderPill sessionIds={['other']} />)
    expect(screen.getByText('Neovarch · pc-rumah')).toBeTruthy()
    expect(document.querySelector('.nv-sender-live')).toBeNull()
    // No office agent: the mascot (static when idle), never the old "N" mark.
    const still = document.querySelector('img.nv-sender-mascot') as HTMLImageElement
    expect(still).not.toBeNull()
    expect(still.getAttribute('src')).toMatch(/neovarch-avatar-128-static\.png/)
    expect(still.dataset.animated).toBeUndefined()
    rerender(<AgentSenderPill live sessionIds={['other']} />)
    const running = document.querySelector('img.nv-sender-mascot') as HTMLImageElement
    expect(running.getAttribute('src')).toMatch(/neovarch-avatar-128\.webp/)
    expect(running.dataset.animated).toBe('true')
  })

  it('pill shows once per turn: only on the assistant message that opens it', () => {
    const messages = [
      { id: 'u1', role: 'user' },
      { id: 'a1', role: 'assistant' },
      { id: 'a2', role: 'assistant' },
      { id: 'u2', role: 'user' },
      { id: 'a3', role: 'assistant' },
    ]

    expect(opensAgentTurn(messages, 'a1')).toBe(true)
    expect(opensAgentTurn(messages, 'a2')).toBe(false)
    expect(opensAgentTurn(messages, 'a3')).toBe(true)
    expect(opensAgentTurn(messages, 'u1')).toBe(false)
    expect(opensAgentTurn(messages, 'missing')).toBe(false)
    expect(opensAgentTurn([{ id: 'a0', role: 'assistant' }], 'a0')).toBe(true)
  })
})
