/**
 * Renderer side of Neovarch's GitHub-Releases updater (window.neovarchUpdate,
 * electron/neovarch-update-ipc.ts): the status the update card shows, the
 * install progress, and the quiet startup check with its small notice.
 */
import { atom } from 'nanostores'

import { translateNow } from '@/i18n'
import { notify } from '@/store/notifications'

import type { NeovarchUpdateProgress, NeovarchUpdateStatus } from '../../electron/neovarch-update'

export type NeovarchApplyStage = 'idle' | 'running' | 'downloading' | 'done' | 'launched' | 'error'

export interface NeovarchApplyState {
  stage: NeovarchApplyStage
  lines: string[]
  percent: number | null
  message: string | null
  fellBackToReleasePage: boolean
}

const MAX_LINES = 400

export const NEOVARCH_APPLY_IDLE: NeovarchApplyState = {
  stage: 'idle',
  lines: [],
  percent: null,
  message: null,
  fellBackToReleasePage: false
}

export const $nvUpdateStatus = atom<NeovarchUpdateStatus | null>(null)
export const $nvUpdateChecking = atom<boolean>(false)
export const $nvUpdateApply = atom<NeovarchApplyState>(NEOVARCH_APPLY_IDLE)

function bridge() {
  return typeof window === 'undefined' ? undefined : window.neovarchUpdate
}

/** Pure reducer for one progress event from main (exported for tests). */
export function reduceNeovarchProgress(state: NeovarchApplyState, progress: NeovarchUpdateProgress): NeovarchApplyState {
  switch (progress.stage) {
    case 'running':
      return { ...state, stage: 'running', lines: [...state.lines, ...progress.lines].slice(-MAX_LINES) }
    case 'downloading':
      return { ...state, stage: 'downloading', percent: progress.percent }
    case 'done':
      return { ...state, stage: 'done', message: null }
    case 'launched':
      return { ...state, stage: 'launched', percent: 100 }
    case 'error':
      return {
        ...state,
        stage: 'error',
        message: progress.message,
        fellBackToReleasePage: Boolean(progress.fellBackToReleasePage)
      }
    default:
      return state
  }
}

export async function checkNeovarchUpdate(opts: { quiet?: boolean } = {}): Promise<NeovarchUpdateStatus | null> {
  const api = bridge()

  if (!api) {
    return null
  }

  if (!opts.quiet) {
    $nvUpdateChecking.set(true)
  }

  try {
    const status = await api.check({ quiet: Boolean(opts.quiet) })

    // A quiet failure stays silent: keep whatever the card already showed.
    if (!(opts.quiet && !status.ok)) {
      $nvUpdateStatus.set(status)
    }

    return status
  } catch (error) {
    if (!opts.quiet) {
      $nvUpdateStatus.set({
        ok: false,
        currentVersion: $nvUpdateStatus.get()?.currentVersion ?? '',
        updateAvailable: false,
        releaseUrl: 'https://github.com/Maftuuh1922/neovrach_Agent/releases',
        installKind: 'unsupported',
        action: 'release-page',
        error: error instanceof Error ? error.message : String(error)
      })
    }

    return null
  } finally {
    if (!opts.quiet) {
      $nvUpdateChecking.set(false)
    }
  }
}

export async function applyNeovarchUpdate(): Promise<void> {
  const api = bridge()

  if (!api) {
    return
  }

  $nvUpdateApply.set({ ...NEOVARCH_APPLY_IDLE })
  const result = await api.apply().catch((error: Error) => ({ ok: false, error: error.message, started: false }))

  if (!result.ok) {
    $nvUpdateApply.set({ ...NEOVARCH_APPLY_IDLE, stage: 'error', message: result.error ?? 'update failed' })
  } else if (result.started) {
    const current = $nvUpdateApply.get()

    if (current.stage === 'idle') {
      $nvUpdateApply.set({ ...current, stage: $nvUpdateStatus.get()?.action === 'windows-setup' ? 'downloading' : 'running' })
    }
  }
}

export function openNeovarchReleasePage(url?: string): void {
  void bridge()?.openReleasePage(url)
}

export function relaunchNeovarch(): void {
  void bridge()?.relaunch()
}

export function resetNeovarchApply(): void {
  $nvUpdateApply.set(NEOVARCH_APPLY_IDLE)
}

let unsubscribeProgress: (() => void) | null = null

/**
 * Subscribe to install progress and run the quiet startup check. Main
 * throttles the network request to once per 24h and answers from its cache
 * otherwise; the notice only shows after a real check found a newer release.
 */
export function startNeovarchUpdateWatch(opts: { onOpen: () => void }): void {
  const api = bridge()

  if (!api || unsubscribeProgress) {
    return
  }

  unsubscribeProgress = api.onProgress(progress => $nvUpdateApply.set(reduceNeovarchProgress($nvUpdateApply.get(), progress)))

  void checkNeovarchUpdate({ quiet: true }).then(status => {
    if (!status?.ok || status.skipped || !status.updateAvailable || !status.latestVersion) {
      return
    }

    notify({
      id: `neovarch-update-${status.latestVersion}`,
      kind: 'info',
      placement: 'bottom-right',
      title: translateNow('nvUpdate.noticeTitle'),
      message: translateNow('nvUpdate.noticeBody').replace('{version}', status.latestVersion),
      action: { label: translateNow('nvUpdate.noticeAction'), onClick: opts.onOpen },
      durationMs: 20_000
    })
  })
}

export function stopNeovarchUpdateWatch(): void {
  unsubscribeProgress?.()
  unsubscribeProgress = null
}
