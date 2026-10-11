// Single-instance / backend lifecycle contract, pinned at main.ts's seams.
//
// main.ts cannot boot under vitest (it is Electron's entry), so this reads its
// source and asserts the ordering the behaviour depends on:
//   * `--version` exits before the lock, a window, or a backend;
//   * a lock-losing (second) launch hard-exits before `ready`, so it never
//     reaps/spawns a backend, and the running app focuses its window instead;
//   * only the lock holder may start the core backend (exactly one backend);
//   * quit stops the core backend AND the opt-in LAN gateway, and a late
//     autostart cannot respawn the gateway during quit.
// The behaviour behind each seam has its own unit tests (singleton-lock,
// main-window-lifecycle, host-backend-singleton, backend-exit-recovery,
// neovarch-remote-lifecycle).
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const MAIN = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

function at(needle: string): number {
  const index = MAIN.indexOf(needle)
  expect(index, `main.ts no longer contains: ${needle}`).toBeGreaterThan(-1)

  return index
}

function block(startNeedle: string, length = 4000): string {
  const start = at(startNeedle)

  return MAIN.slice(start, start + length)
}

describe('single instance', () => {
  it('--version answers before the single-instance lock is taken', () => {
    expect(at("includes('--version')")).toBeLessThan(at('const isPrimaryInstance: boolean = acquireSingleInstanceLock()'))
  })

  it('stale SingletonLock recovery retries the lock once after removing a provably-dead owner', () => {
    const fn = block('function acquireSingleInstanceLock(): boolean {', 800)
    expect(fn).toContain('removeStaleSingletonLock(app.getPath(')
    expect(fn.match(/app\.requestSingleInstanceLock\(\)/g)?.length).toBe(2)
  })

  it('a second launch exits immediately (before ready) instead of booting a second app', () => {
    const lock = at('const isPrimaryInstance: boolean = acquireSingleInstanceLock()')
    const gate = block('const isPrimaryInstance: boolean = acquireSingleInstanceLock()', 300)
    expect(gate).toMatch(/if \(!isPrimaryInstance\) \{[\s\S]*?app\.exit\(0\)/)
    expect(lock).toBeLessThan(at('app.whenReady().then(() => {'))
  })

  it('the running app focuses (or recreates) its window on a second launch', () => {
    const handler = block("app.on('second-instance', (_event, argv) => {", 2000)
    expect(handler).toContain('ensureMainWindow(mainWindow')
    expect(handler).toContain('focusWindow: activateWindow')
  })
})

describe('exactly one core backend', () => {
  it('only the lock holder may reap or spawn the backend', () => {
    const start = block('async function runHermesStart(', 1500)
    const guard = start.indexOf('if (!isPrimaryInstance)')
    expect(guard).toBeGreaterThan(-1)
    expect(guard).toBeLessThan(start.indexOf('await reapOrphanedBackendsOnce()'))
    expect(start).toContain('localBackendLifecycle.assertCanStart()')
  })

  it('the LAN gateway (the only other core process) starts only from autostart/explicit enable', () => {
    // Two call sites, no more: the boot autostart after `ready` (so only the lock holder
    // reaches it), and the restart when "Jalankan di latar belakang" is switched on (#6),
    // which stops the running gateway first, so it replaces it instead of adding a second.
    const calls = [...MAIN.matchAll(/neovarchRemote\.autostart\(\)/g)].map(m => m.index ?? -1)
    expect(calls.length).toBe(2)

    const boot = at('setTimeout(() => neovarchRemote.autostart(),')
    expect(calls).toContain(boot + 'setTimeout(() => '.length)
    expect(boot).toBeGreaterThan(at('app.whenReady().then(() => {'))

    const restart = calls.find(index => index !== boot + 'setTimeout(() => '.length) ?? -1
    const before = MAIN.slice(Math.max(0, restart - 400), restart)
    expect(before).toMatch(
      /if \(next\.runInBackground && neovarchRemote\.status\(\)\.enabled && neovarchRemote\.hasProcess\(\)\) \{[\s\S]*await neovarchRemote\.stop\(\)\s*$/
    )
  })
})

describe('quit', () => {
  it('stops the core backend and waits for it', () => {
    const quit = block("app.on('before-quit', event => {", 6000)
    expect(quit).toContain('backendShutdown.run()')
    expect(quit).toContain('waitForCompletion: backendNeedsWait')
  })

  it('stops the LAN gateway once, before any early return, and waits for it', () => {
    const quit = block("app.on('before-quit', event => {", 6000)
    const shutdown = quit.indexOf('neovarchRemote.shutdown()')
    expect(shutdown).toBeGreaterThan(-1)
    expect(shutdown).toBeLessThan(quit.indexOf('if (\n    !managedUpdateQuitWaitDone'))
    expect(quit).toContain('remoteQuitStop ??=')
    expect(quit).toContain('waitForCompletion: Boolean(remoteQuitStop?.wait)')
    // The fire-and-forget stop that let the gateway outlive the app is gone.
    expect(MAIN).not.toContain('void neovarchRemote.stop()')
  })
})
