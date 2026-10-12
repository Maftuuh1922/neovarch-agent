import { describe, expect, it } from 'vitest'

import { $coreQueueBySession, friendlyCoreQueueError, parseCoreQueue, setCoreQueue } from './core-queue-store'

describe('core queue (Antre)', () => {
  it('parses the core queue.update payload', () => {
    const q = parseCoreQueue({
      count: 2,
      items: [
        { attachments: [{ id: 'u1' }], id: 'q-1', text: 'cek log', ts: 1 },
        { id: 'q-2', text: 'deploy' },
        { text: 'no id' }
      ],
      paused: true,
      paused_reason: 'stopped'
    })

    expect(q.items.map(i => i.id)).toEqual(['q-1', 'q-2'])
    expect(q.items[0].attachments).toBe(1)
    expect(q.paused).toBe(true)
    expect(q.pausedReason).toBe('stopped')
  })

  it('an empty queue is never paused; junk is empty', () => {
    expect(parseCoreQueue({ items: [], paused: true }).paused).toBe(false)
    expect(parseCoreQueue(null).items).toEqual([])
  })

  it('stores per session', () => {
    setCoreQueue('s1', { items: [{ id: 'q-1', text: 'a' }] })
    setCoreQueue('s2', { items: [] })
    expect($coreQueueBySession.get().s1.items).toHaveLength(1)
    expect($coreQueueBySession.get().s2.items).toHaveLength(0)
  })

  it('maps the raw English refusal to friendly copy', () => {
    expect(friendlyCoreQueueError('a turn is already running in this session')).toBeTruthy()
    expect(friendlyCoreQueueError('a turn is already running in this session')).not.toContain('turn is already running')
    expect(friendlyCoreQueueError('other')).toBeNull()
  })
})
