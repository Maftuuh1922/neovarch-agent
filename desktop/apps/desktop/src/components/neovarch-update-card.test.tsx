import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { en } from '@/i18n/en'
import {
  $nvUpdateApply,
  $nvUpdateStatus,
  NEOVARCH_APPLY_IDLE,
  reduceNeovarchProgress
} from '@/store/neovarch-update'

import type { NeovarchUpdateStatus } from '../../electron/neovarch-update'

import { NeovarchUpdateCard } from './neovarch-update-card'

const n = en.nvUpdate

function status(overrides: Partial<NeovarchUpdateStatus> = {}): NeovarchUpdateStatus {
  return {
    ok: true,
    currentVersion: '1.4.7',
    latestVersion: 'v1.4.8',
    updateAvailable: true,
    notes: 'Perbaikan updater.',
    releaseUrl: 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8',
    installKind: 'installer',
    action: 'install-script',
    ...overrides
  }
}

describe('NeovarchUpdateCard', () => {
  let api: {
    check: ReturnType<typeof vi.fn>
    apply: ReturnType<typeof vi.fn>
    openReleasePage: ReturnType<typeof vi.fn>
    relaunch: ReturnType<typeof vi.fn>
    onProgress: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    $nvUpdateStatus.set(null)
    $nvUpdateApply.set(NEOVARCH_APPLY_IDLE)
    api = {
      check: vi.fn().mockResolvedValue(status()),
      apply: vi.fn().mockResolvedValue({ ok: true, action: 'install-script', started: true }),
      openReleasePage: vi.fn().mockResolvedValue(undefined),
      relaunch: vi.fn().mockResolvedValue(undefined),
      onProgress: vi.fn(() => () => undefined)
    }
    ;(window as unknown as { neovarchUpdate?: unknown }).neovarchUpdate = api
  })

  afterEach(() => {
    cleanup()
    delete (window as unknown as { neovarchUpdate?: unknown }).neovarchUpdate
  })

  it('checks on open and offers "Update now" for an install.sh install', async () => {
    render(<NeovarchUpdateCard autoCheck />)
    await waitFor(() => expect(screen.getByText(n.available.replace('{version}', 'v1.4.8'))).toBeTruthy())
    expect(api.check).toHaveBeenCalledWith({ quiet: false })
    expect(screen.getByText('Perbaikan updater.')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: n.updateNow }))
    await waitFor(() => expect(api.apply).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText(n.installing)).toBeTruthy())
  })

  it('shows the installer log and asks to restart when it finishes', () => {
    $nvUpdateStatus.set(status())
    render(<NeovarchUpdateCard />)

    act(() => {
      let next = reduceNeovarchProgress($nvUpdateApply.get(), { stage: 'running', lines: ['==> Mengunduh'] })
      next = reduceNeovarchProgress(next, { stage: 'done' })
      $nvUpdateApply.set(next)
    })

    expect(screen.getByText(n.installedRestart)).toBeTruthy()
    expect(screen.getByText('==> Mengunduh')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: n.restartNow }))
    expect(api.relaunch).toHaveBeenCalledTimes(1)
  })

  it('sends AppImage/deb installs to the release page', () => {
    $nvUpdateStatus.set(status({ installKind: 'appimage', action: 'release-page' }))
    render(<NeovarchUpdateCard />)
    expect(screen.getByText(n.manualHint)).toBeTruthy()
    expect(screen.getByRole('button', { name: n.openRelease })).toBeTruthy()
    expect(screen.queryByRole('button', { name: n.updateNow })).toBeNull()
  })

  it('offers download & install on Windows', () => {
    $nvUpdateStatus.set(status({ installKind: 'windows', action: 'windows-setup' }))
    render(<NeovarchUpdateCard />)
    expect(screen.getByRole('button', { name: n.downloadInstall })).toBeTruthy()
  })

  it('says up to date when there is nothing newer', () => {
    $nvUpdateStatus.set(status({ updateAvailable: false, latestVersion: 'v1.4.7' }))
    render(<NeovarchUpdateCard />)
    expect(screen.getByText(n.upToDate)).toBeTruthy()
    expect(screen.queryByRole('button', { name: n.updateNow })).toBeNull()
  })
})

describe('reduceNeovarchProgress', () => {
  it('keeps the log bounded and records errors', () => {
    let state = NEOVARCH_APPLY_IDLE

    for (let i = 0; i < 50; i += 1) {
      state = reduceNeovarchProgress(state, { stage: 'running', lines: Array.from({ length: 10 }, (_, j) => `${i}-${j}`) })
    }

    expect(state.lines).toHaveLength(400)
    expect(state.lines.at(-1)).toBe('49-9')
    state = reduceNeovarchProgress(state, { stage: 'error', message: 'boom', fellBackToReleasePage: true })
    expect(state).toMatchObject({ stage: 'error', message: 'boom', fellBackToReleasePage: true })
    expect(reduceNeovarchProgress(NEOVARCH_APPLY_IDLE, { stage: 'downloading', percent: 42 }).percent).toBe(42)
  })
})
