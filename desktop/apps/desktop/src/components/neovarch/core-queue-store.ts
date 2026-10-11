import { map } from 'nanostores'

import { onGatewayEvent } from '@/contrib/events'
import { nvPick } from '@/i18n/neovarch-lang'

/** One message waiting in the PC core's per-session queue (core ≥ 1.4.7, `msg_queue.py`). */
export interface CoreQueuedMessage {
  attachments: number
  id: string
  text: string
  ts?: number
}

export interface CoreQueueState {
  items: CoreQueuedMessage[]
  paused: boolean
  pausedReason?: string
}

export const EMPTY_CORE_QUEUE: CoreQueueState = { items: [], paused: false }

/** Per session: the PC's queue — the same list the phone shows ("Antre (n)"). */
export const $coreQueueBySession = map<Record<string, CoreQueueState>>({})

export function parseCoreQueue(raw: unknown): CoreQueueState {
  if (!raw || typeof raw !== 'object') {
    return EMPTY_CORE_QUEUE
  }

  const r = raw as Record<string, unknown>

  const items = (Array.isArray(r.items) ? r.items : [])
    .filter((i): i is Record<string, unknown> => !!i && typeof i === 'object' && typeof i.id === 'string' && !!i.id)
    .map(i => ({
      attachments: Array.isArray(i.attachments) ? i.attachments.length : 0,
      id: String(i.id),
      text: typeof i.text === 'string' ? i.text : '',
      ...(typeof i.ts === 'number' ? { ts: i.ts } : {})
    }))

  return {
    items,
    paused: r.paused === true && items.length > 0,
    ...(typeof r.paused_reason === 'string' ? { pausedReason: r.paused_reason } : {})
  }
}

export function setCoreQueue(sessionId: string, raw: unknown): void {
  $coreQueueBySession.setKey(sessionId, parseCoreQueue(raw))
}

let wired = false

/** Follow `queue.update` / `queue.sent` for every session (idempotent). */
export function wireCoreQueueEvents(): void {
  if (wired) {
    return
  }

  wired = true
  onGatewayEvent('queue.update', event => {
    if (event.session_id) {
      setCoreQueue(event.session_id, event.payload)
    }
  })
  onGatewayEvent('queue.sent', event => {
    const sid = event.session_id
    const id = (event.payload as unknown as { id?: string } | undefined)?.id

    if (!sid || !id) {
      return
    }

    const cur = $coreQueueBySession.get()[sid] ?? EMPTY_CORE_QUEUE
    $coreQueueBySession.setKey(sid, { ...cur, items: cur.items.filter(i => i.id !== id), paused: false })
  })
}

export const CORE_QUEUE_COPY = {
  en: {
    attachments: (n: number) => `${n} attachments`,
    edit: 'Edit',
    label: (n: number) => `Queued (${n})`,
    pausedError: 'Queue paused because the turn failed. Send now or resume.',
    pausedStopped: 'Queue paused because the agent was stopped. Send now or resume.',
    remove: 'Remove from queue',
    resume: 'Resume queue',
    save: 'Save',
    sendNow: 'Send now',
    subtitle: 'Held by the PC — the phone sees the same list'
  },
  id: {
    attachments: (n: number) => `${n} lampiran`,
    edit: 'Edit',
    label: (n: number) => `Antre (${n})`,
    pausedError: 'Antrean dijeda karena giliran gagal. Kirim sekarang atau lanjutkan.',
    pausedStopped: 'Antrean dijeda karena agen dihentikan. Kirim sekarang atau lanjutkan.',
    remove: 'Hapus dari antrean',
    resume: 'Lanjutkan antrean',
    save: 'Simpan',
    sendNow: 'Kirim sekarang',
    subtitle: 'Dipegang PC — HP melihat daftar yang sama'
  }
}

export const coreQueueCopy = () => nvPick(CORE_QUEUE_COPY)

/** Raw core refusals never reach the person in English. */
export function friendlyCoreQueueError(message: string): null | string {
  const m = message.toLowerCase()

  if (m.includes('turn is already running')) {
    return nvPick({
      en: 'The agent is still working. Your message was not sent — wait for it to finish or press Stop.',
      id: 'Agen masih bekerja. Pesan belum terkirim — tunggu sampai selesai atau tekan Stop.'
    })
  }

  if (m.includes('antrean penuh')) {
    return nvPick({ en: 'Queue is full (max 20 messages).', id: 'Antrean penuh (maks 20 pesan).' })
  }

  return null
}
