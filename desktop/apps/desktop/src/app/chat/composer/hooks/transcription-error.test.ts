import { beforeEach, describe, expect, it, vi } from 'vitest'

import { checkedTranscription, isSttUnavailable, SttUnavailableError } from '@/api/system'

import { notifyTranscriptionError, STT_UNAVAILABLE_NOTICE_ID } from './transcription-error'

const notify = vi.fn()
const notifyError = vi.fn()

vi.mock('@/store/notifications', () => ({
  notify: (...args: unknown[]) => notify(...args),
  notifyError: (...args: unknown[]) => notifyError(...args)
}))

const copy = {
  transcriptionFailed: 'Voice transcription failed',
  transcriptionUnavailable: 'Voice typing on the PC is not available yet.',
  unavailable: 'Voice unavailable'
}

describe('PC voice typing never crashes the composer', () => {
  beforeEach(() => {
    notify.mockReset()
    notifyError.mockReset()
  })

  it('passes a real transcript through', () => {
    expect(checkedTranscription({ ok: true, transcript: 'halo' }).transcript).toBe('halo')
  })

  it("turns the core's refusal into SttUnavailableError (it used to crash on undefined.trim())", () => {
    const refusal = { ok: false, available: false, transcript: '', code: 'stt_unavailable', error: 'Dikte suara di PC belum tersedia' }

    expect(() => checkedTranscription(refusal)).toThrow(SttUnavailableError)
    expect(() => checkedTranscription(refusal)).toThrow('Dikte suara di PC belum tersedia')
  })

  it('keeps a failed local STT run a plain error with the core message (not "unavailable")', () => {
    let caught: unknown

    try {
      checkedTranscription({ ok: false, available: true, transcript: '', code: 'stt_failed', error: 'Transkripsi gagal (faster-whisper): oom' })
    } catch (error) {
      caught = error
    }

    expect(isSttUnavailable(caught)).toBe(false)
    expect((caught as Error).message).toContain('faster-whisper')
  })

  it("treats an older core's quiet fallback (no transcript at all) the same way", () => {
    let caught: unknown

    try {
      checkedTranscription({ ok: false, available: false, message: 'Not available in the Neovarch core.' })
    } catch (error) {
      caught = error
    }

    expect(isSttUnavailable(caught)).toBe(true)
    expect(() => checkedTranscription(undefined)).toThrow(SttUnavailableError)
  })

  it('shows one localized "not available" notice for a backend without STT', () => {
    notifyTranscriptionError(new SttUnavailableError('x'), copy)
    notifyTranscriptionError(new SttUnavailableError('x'), copy)

    expect(notifyError).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledTimes(2)
    expect(notify).toHaveBeenLastCalledWith({
      id: STT_UNAVAILABLE_NOTICE_ID,
      kind: 'warning',
      message: copy.transcriptionUnavailable,
      title: copy.unavailable
    })
  })

  it('keeps the error toast for real failures', () => {
    const boom = new Error('network down')
    notifyTranscriptionError(boom, copy)
    expect(notifyError).toHaveBeenCalledWith(boom, copy.transcriptionFailed)
    expect(notify).not.toHaveBeenCalled()
  })
})
