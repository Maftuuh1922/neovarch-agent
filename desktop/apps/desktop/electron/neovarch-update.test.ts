import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  buildLinuxInstallCommand,
  cleanLogChunk,
  compareSemver,
  createNeovarchUpdater,
  detectInstallKind,
  INSTALL_SH_URL,
  isNewerRelease,
  LATEST_RELEASE_API,
  parseLatestRelease,
  parseSemver,
  pickWindowsSetupAsset,
  shouldRunStartupCheck,
  STARTUP_CHECK_INTERVAL_MS,
  summarizeReleaseNotes,
  updateActionFor,
  WINDOWS_SETUP_ASSET
} from './neovarch-update'

describe('semver', () => {
  it('parses tags with and without the v prefix', () => {
    expect(parseSemver('v1.4.7')).toEqual({ major: 1, minor: 4, patch: 7, pre: [] })
    expect(parseSemver('1.4.7')).toEqual({ major: 1, minor: 4, patch: 7, pre: [] })
    expect(parseSemver('v2.0.0-rc.1+build.5')).toEqual({ major: 2, minor: 0, patch: 0, pre: ['rc', '1'] })
    expect(parseSemver('1.4')).toBeNull()
    expect(parseSemver('latest')).toBeNull()
    expect(parseSemver(undefined)).toBeNull()
  })

  it('compares numerically, not as strings', () => {
    expect(compareSemver('v1.4.10', '1.4.9')).toBeGreaterThan(0)
    expect(compareSemver('1.10.0', '1.9.9')).toBeGreaterThan(0)
    expect(compareSemver('v1.4.7', '1.4.7')).toBe(0)
    expect(compareSemver('1.4.6', '1.4.7')).toBeLessThan(0)
    expect(compareSemver('2.0.0', '1.99.99')).toBeGreaterThan(0)
  })

  it('ranks a release above its prereleases', () => {
    expect(compareSemver('1.5.0', '1.5.0-rc.1')).toBeGreaterThan(0)
    expect(compareSemver('1.5.0-rc.2', '1.5.0-rc.1')).toBeGreaterThan(0)
    expect(compareSemver('1.5.0-rc.10', '1.5.0-rc.9')).toBeGreaterThan(0)
    expect(compareSemver('1.5.0-alpha', '1.5.0-beta')).toBeLessThan(0)
    expect(compareSemver('1.5.0-1', '1.5.0-alpha')).toBeLessThan(0)
  })

  it('only reports a newer release when both versions parse', () => {
    expect(isNewerRelease('v1.4.8', '1.4.7')).toBe(true)
    expect(isNewerRelease('v1.4.7', '1.4.7')).toBe(false)
    expect(isNewerRelease('v1.4.6', '1.4.7')).toBe(false)
    expect(isNewerRelease('nightly', '1.4.7')).toBe(false)
    expect(isNewerRelease('v1.4.8', '0.0.0-dev+abc')).toBe(true)
    expect(isNewerRelease('v1.4.8', '')).toBe(false)
  })
})

describe('release parsing', () => {
  const assets = [
    { name: 'neovarch-agent-linux-x64.tar.gz', url: 'https://x/linux.tgz', size: 1 },
    { name: 'neovarch-agent-windows-x64.zip', url: 'https://x/win.zip', size: 2 },
    { name: WINDOWS_SETUP_ASSET, url: 'https://x/setup.exe', size: 3 }
  ]

  it('picks the Windows setup asset by exact name', () => {
    expect(pickWindowsSetupAsset(assets)?.url).toBe('https://x/setup.exe')
  })

  it('falls back to a loose Windows x64 setup match, never the zip', () => {
    expect(pickWindowsSetupAsset([assets[1], { name: 'Neovarch-Windows-x64-Setup-1.5.0.exe', url: 'u', size: 4 }])?.url).toBe('u')
    expect(pickWindowsSetupAsset(assets.slice(0, 2))).toBeNull()
    expect(pickWindowsSetupAsset([])).toBeNull()
  })

  it('reads the GitHub latest-release payload', () => {
    const release = parseLatestRelease({
      tag_name: 'v1.4.8',
      name: 'Neovarch Agent 1.4.8',
      html_url: 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8',
      body: '## Neovarch Agent 1.4.8\n\nPerbaikan.',
      published_at: '2026-10-14T00:00:00Z',
      assets: [{ name: WINDOWS_SETUP_ASSET, browser_download_url: 'https://dl/setup.exe', size: 10 }, { bogus: true }]
    })
    expect(release?.tag).toBe('v1.4.8')
    expect(release?.assets).toEqual([{ name: WINDOWS_SETUP_ASSET, url: 'https://dl/setup.exe', size: 10 }])
    expect(parseLatestRelease({ tag_name: 'nightly' })).toBeNull()
    expect(parseLatestRelease({ tag_name: 'v1.0.0', draft: true })).toBeNull()
    expect(parseLatestRelease(null)).toBeNull()
  })

  it('never trusts a non-GitHub release url', () => {
    expect(parseLatestRelease({ tag_name: 'v1.4.8', html_url: 'https://evil.example/x' })?.htmlUrl).toBe(
      'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8'
    )
  })

  it('summarizes notes without the version heading and caps the length', () => {
    expect(summarizeReleaseNotes('## Neovarch Agent 1.4.7\r\n\r\nRilis **ini** pakai `Tailscale`.\n\n\n\n### Penting')).toBe(
      'Rilis ini pakai Tailscale.\n\n### Penting'
    )
    const long = summarizeReleaseNotes(Array.from({ length: 50 }, (_, i) => `baris ${i} ${'x'.repeat(30)}`).join('\n'), 200)
    expect(long.length).toBeLessThanOrEqual(201)
    expect(long.endsWith('…')).toBe(true)
  })
})

describe('startup throttle', () => {
  const now = 1_800_000_000_000

  it('runs when never checked', () => {
    expect(shouldRunStartupCheck(undefined, now)).toBe(true)
    expect(shouldRunStartupCheck(null, now)).toBe(true)
    expect(shouldRunStartupCheck(Number.NaN, now)).toBe(true)
  })

  it('waits 24 hours between checks', () => {
    expect(shouldRunStartupCheck(now - 60_000, now)).toBe(false)
    expect(shouldRunStartupCheck(now - STARTUP_CHECK_INTERVAL_MS + 1, now)).toBe(false)
    expect(shouldRunStartupCheck(now - STARTUP_CHECK_INTERVAL_MS, now)).toBe(true)
  })

  it('runs again when the clock went backwards', () => {
    expect(shouldRunStartupCheck(now + 60_000, now)).toBe(true)
  })
})

describe('install kind', () => {
  const base = { env: {}, homeDir: '/home/u', isPackaged: true }

  it('tells install.sh, AppImage and system packages apart on Linux', () => {
    expect(
      detectInstallKind({ ...base, platform: 'linux', execPath: '/home/u/.local/share/neovarch-agent/neovarch-agent' })
    ).toBe('installer')
    expect(
      detectInstallKind({
        ...base,
        platform: 'linux',
        env: { XDG_DATA_HOME: '/data' },
        execPath: '/data/neovarch-agent/neovarch-agent'
      })
    ).toBe('installer')
    expect(
      detectInstallKind({ ...base, platform: 'linux', env: { APPIMAGE: '/x.AppImage' }, execPath: '/tmp/.mount/neovarch' })
    ).toBe('appimage')
    expect(detectInstallKind({ ...base, platform: 'linux', execPath: '/opt/Neovarch Agent/neovarch-agent' })).toBe('deb')
    expect(
      detectInstallKind({ ...base, platform: 'linux', execPath: '/home/u/.local/share/neovarch-agent-old/neovarch-agent' })
    ).toBe('deb')
  })

  it('maps platforms and dev builds to their action', () => {
    expect(detectInstallKind({ ...base, platform: 'win32', execPath: 'C:\\x.exe' })).toBe('windows')
    expect(detectInstallKind({ ...base, platform: 'darwin', execPath: '/Applications/x' })).toBe('unsupported')
    expect(detectInstallKind({ ...base, isPackaged: false, platform: 'linux', execPath: '/usr/bin/electron' })).toBe(
      'unsupported'
    )
    expect(updateActionFor('installer')).toBe('install-script')
    expect(updateActionFor('windows')).toBe('windows-setup')
    expect(updateActionFor('appimage')).toBe('release-page')
    expect(updateActionFor('deb')).toBe('release-page')
    expect(updateActionFor('unsupported')).toBe('release-page')
  })
})

describe('linux installer command', () => {
  it('runs the official install.sh for the tag without killing the app', () => {
    const cmd = buildLinuxInstallCommand('v1.4.8')
    expect(cmd.command).toBe('/bin/sh')
    expect(cmd.env).toMatchObject({ NEOVARCH_VERSION: 'v1.4.8', NEOVARCH_KEEP_RUNNING: '1', NV_INSTALL_URL: INSTALL_SH_URL })
    expect(cmd.args[1]).toContain('sh "$f"')
    expect(buildLinuxInstallCommand('1.4.8').env.NEOVARCH_VERSION).toBe('v1.4.8')
  })

  it('refuses anything that is not a version tag', () => {
    expect(() => buildLinuxInstallCommand('v1.4.8; rm -rf ~')).toThrow()
  })

  it('cleans ANSI colours and carriage returns from the log', () => {
    expect(cleanLogChunk('\u001b[31m==>\u001b[0m Mengunduh\r\n50%\r100%\n\n')).toEqual(['==> Mengunduh', '50%', '100%'])
  })
})

describe('createNeovarchUpdater', () => {
  let dir: string

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nv-update-'))
  })

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true })
  })

  const release = {
    tag_name: 'v1.4.8',
    name: 'Neovarch Agent 1.4.8',
    html_url: 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.8',
    body: '## Neovarch Agent 1.4.8\n\nPerbaikan updater.',
    assets: [{ name: WINDOWS_SETUP_ASSET, browser_download_url: 'https://dl/setup.exe', size: 3 }]
  }

  function make(overrides: Record<string, unknown> = {}) {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(release), { status: 200 }))
    const deps = {
      currentVersion: '1.4.7',
      statePath: path.join(dir, 'state.json'),
      tmpDir: path.join(dir, 'tmp'),
      installKind: 'installer' as const,
      baseEnv: {},
      fetch: fetchMock as unknown as typeof fetch,
      now: () => 1_800_000_000_000,
      spawn: vi.fn(),
      openExternal: vi.fn(),
      send: vi.fn(),
      quitApp: vi.fn(),
      ...overrides
    }

    return { deps, fetchMock, updater: createNeovarchUpdater(deps as never) }
  }

  it('reports a newer release with its notes and the install-script action', async () => {
    const { fetchMock, updater } = make()
    const status = await updater.check()
    expect(fetchMock).toHaveBeenCalledWith(LATEST_RELEASE_API, expect.anything())
    expect(status).toMatchObject({
      ok: true,
      updateAvailable: true,
      latestVersion: 'v1.4.8',
      currentVersion: '1.4.7',
      action: 'install-script',
      notes: 'Perbaikan updater.'
    })
  })

  it('makes at most one quiet network check per 24h, answering from the cache', async () => {
    let clock = 1_800_000_000_000
    const { fetchMock, updater } = make({ now: () => clock })
    await updater.check({ quiet: true })
    clock += 60 * 60 * 1000
    const cached = await updater.check({ quiet: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(cached).toMatchObject({ skipped: true, updateAvailable: true, latestVersion: 'v1.4.8' })

    // A manual check always goes to the network.
    await updater.check()
    expect(fetchMock).toHaveBeenCalledTimes(2)

    clock += STARTUP_CHECK_INTERVAL_MS
    await updater.check({ quiet: true })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('stamps failed quiet checks so a broken network is not retried every launch', async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error('offline')
    })
    const { updater } = make({ fetch: fetchMock })
    const first = await updater.check({ quiet: true })
    expect(first).toMatchObject({ ok: false, error: 'offline', updateAvailable: false })
    await updater.check({ quiet: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('opens the release page for AppImage/deb installs instead of installing', async () => {
    const { deps, updater } = make({ installKind: 'appimage' })
    await updater.check()
    const result = await updater.apply()
    expect(result).toMatchObject({ ok: true, openedReleasePage: true, action: 'release-page' })
    expect(deps.openExternal).toHaveBeenCalledWith(release.html_url)
    expect(deps.spawn).not.toHaveBeenCalled()
  })

  it('starts the installer detached for install.sh installs and reports done on exit 0', async () => {
    const listeners: Record<string, (...args: unknown[]) => void> = {}
    const child = {
      pid: 42,
      on: (event: string, cb: (...args: unknown[]) => void) => {
        listeners[event] = cb
      },
      unref: vi.fn()
    }
    const spawn = vi.fn(() => child)
    const { deps, updater } = make({ spawn })
    await updater.check()
    const result = await updater.apply()
    expect(result).toMatchObject({ ok: true, started: true, action: 'install-script' })
    const [command, args, options] = spawn.mock.calls[0] as unknown as [string, string[], Record<string, unknown>]
    expect(command).toBe('/bin/sh')
    expect(args[0]).toBe('-c')
    expect(options).toMatchObject({ detached: true })
    expect((options.env as Record<string, string>).NEOVARCH_VERSION).toBe('v1.4.8')
    expect(child.unref).toHaveBeenCalled()
    listeners.exit(0, null)
    expect(deps.send).toHaveBeenLastCalledWith({ stage: 'done' })
  })

  it('does not install when already on the latest version', async () => {
    const { deps, updater } = make({ currentVersion: '1.4.8' })
    const status = await updater.check()
    expect(status.updateAvailable).toBe(false)
    await updater.apply()
    expect(deps.spawn).not.toHaveBeenCalled()
  })
})
