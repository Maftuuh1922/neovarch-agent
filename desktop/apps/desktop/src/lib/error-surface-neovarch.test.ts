import { describe, expect, it } from 'vitest'

import { errorRecoveryPlan, neovarchStopSurface } from './error-surface'
import { errorCardText } from './error-surface-copy'

const thread = {} as Parameters<typeof errorCardText>[0]

describe('Neovarch core stop codes (v1.4.7)', () => {
  const stop = neovarchStopSurface({
    action: 'continue',
    action_label: 'Lanjutkan',
    code: 'step_limit',
    message: 'Agen sudah bekerja 150 langkah di giliran ini tanpa kemajuan baru.',
    title: 'Batas langkah tercapai'
  })

  it('uses the core words verbatim, never the raw internal string', () => {
    expect(stop).not.toBeNull()
    const text = errorCardText(thread, stop)

    expect(text.title).toBe('Batas langkah tercapai')
    expect(text.body).toContain('150 langkah')
  })

  it('offers exactly the one action the core named', () => {
    const plan = errorRecoveryPlan(stop)

    expect(plan.continueTurn).toBe(true)
    expect(plan.retry).toBe(false)
    expect(plan.chooseModel).toBe(false)
    expect(errorRecoveryPlan(neovarchStopSurface({ action: 'switch_model', code: 'no_progress', title: 'Agen buntu' })).chooseModel).toBe(
      true
    )
    expect(errorRecoveryPlan(neovarchStopSurface({ action: 'settings', code: 'auth', title: 'Kunci API ditolak' })).openSettings).toBe(
      true
    )
  })

  it('ignores payloads without a title (older cores)', () => {
    expect(neovarchStopSurface({ message: 'stopped after 30 model calls' })).toBeNull()
  })
})
