import { isSttUnavailable } from '@/api/system'
import { notify, notifyError } from '@/store/notifications'

interface TranscriptionCopy {
  transcriptionFailed: string
  transcriptionUnavailable: string
  unavailable: string
}

/** One id, so a voice conversation that keeps hitting it shows one notice, not a stack. */
export const STT_UNAVAILABLE_NOTICE_ID = 'voice-stt-unavailable'

/**
 * A failed transcription never takes the composer down. A backend with no
 * speech engine gets a plain "voice typing is not available" notice in the
 * app's language; any other failure keeps the error toast.
 */
export function notifyTranscriptionError(error: unknown, copy: TranscriptionCopy): void {
  if (isSttUnavailable(error)) {
    notify({
      id: STT_UNAVAILABLE_NOTICE_ID,
      kind: 'warning',
      message: copy.transcriptionUnavailable,
      title: copy.unavailable
    })

    return
  }

  notifyError(error, copy.transcriptionFailed)
}
