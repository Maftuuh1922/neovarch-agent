import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import type { HermesGateway } from '@/hermes'

import { $coreQueueBySession, coreQueueCopy, EMPTY_CORE_QUEUE, setCoreQueue, wireCoreQueueEvents } from './core-queue-store'

/** "Antre (n)" above the composer: messages waiting in the PC core's queue for
 *  this chat (sent from the phone or from here while the agent worked). Edit,
 *  remove, or send now (stops the running turn; this one goes next). */
export function CoreQueuePanel({ gateway, sessionId }: { gateway?: HermesGateway | null; sessionId?: null | string }) {
  const all = useStore($coreQueueBySession)
  const q = (sessionId && all[sessionId]) || EMPTY_CORE_QUEUE
  const [editing, setEditing] = useState<null | { id: string; text: string }>(null)
  const copy = coreQueueCopy()

  useEffect(() => {
    wireCoreQueueEvents()

    if (!gateway || !sessionId || typeof gateway.request !== 'function') {
      return
    }

    try {
      Promise.resolve(gateway.request<unknown>('queue.list', { session_id: sessionId }))
        .then(res => setCoreQueue(sessionId, res))
        .catch(() => undefined) // older core: no queue
    } catch {
      // a test double without RPC: nothing to show
    }
  }, [gateway, sessionId])

  if (!sessionId || q.items.length === 0) {
    return null
  }

  const act = (action: string, params: Record<string, unknown> = {}) =>
    gateway
      ?.request<unknown>(`queue.${action}`, { session_id: sessionId, ...params })
      .then(res => setCoreQueue(sessionId, res))
      .catch(() => undefined)

  return (
    <div
      className="mb-1.5 flex flex-col gap-1 rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) px-3 py-2 text-[0.75rem]"
      data-testid="core-queue-panel"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-foreground" title={copy.subtitle}>
          {copy.label(q.items.length)}
        </span>
        {q.paused && (
          <button className="text-muted-foreground hover:text-foreground" data-testid="core-queue-resume" onClick={() => void act('resume')} type="button">
            {copy.resume}
          </button>
        )}
      </div>

      {q.paused && (
        <p className="text-[0.6875rem] text-muted-foreground" data-testid="core-queue-paused">
          {q.pausedReason === 'error' ? copy.pausedError : copy.pausedStopped}
        </p>
      )}

      <ul className="flex max-h-36 flex-col gap-1 overflow-y-auto">
        {q.items.map(item => (
          <li className="flex items-center gap-2" data-testid={`core-queue-item-${item.id}`} key={item.id}>
            {editing?.id === item.id ? (
              <input
                autoFocus
                className="min-w-0 flex-1 rounded border border-(--ui-stroke-secondary) bg-transparent px-1.5 py-0.5"
                data-testid="core-queue-edit-input"
                onChange={e => setEditing({ id: item.id, text: e.target.value })}
                onKeyDown={e => {
                  if (e.key === 'Enter' && editing.text.trim()) {
                    void act('edit', { id: item.id, text: editing.text })
                    setEditing(null)
                  } else if (e.key === 'Escape') {
                    setEditing(null)
                  }
                }}
                value={editing.text}
              />
            ) : (
              <span className="min-w-0 flex-1 truncate text-foreground">{item.text || copy.attachments(item.attachments)}</span>
            )}
            <button
              className="shrink-0 text-muted-foreground hover:text-foreground"
              data-testid={`core-queue-send-${item.id}`}
              onClick={() => void act('send_now', { id: item.id })}
              type="button"
            >
              {copy.sendNow}
            </button>
            <button
              className="shrink-0 text-muted-foreground hover:text-foreground"
              onClick={() => setEditing(editing?.id === item.id ? null : { id: item.id, text: item.text })}
              type="button"
            >
              {copy.edit}
            </button>
            <button
              aria-label={copy.remove}
              className="shrink-0 text-muted-foreground hover:text-foreground"
              data-testid={`core-queue-remove-${item.id}`}
              onClick={() => void act('remove', { id: item.id })}
              type="button"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
