// "Jalankan di latar belakang": settings, merge with the phone's copy, close /
// quit decisions, autostart entries, and a gateway that outlives the app.
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import {
  HIDDEN_ARG,
  applyStartAtLogin,
  closeAction,
  launchCommand,
  launchedHidden,
  linuxAutostartEntry,
  linuxAutostartPath,
  mergeWithCore,
  parseBackgroundSettings,
  quitGatewayAction,
  readBackgroundSettings,
  serviceLabel,
  writeBackgroundSettings
} from './neovarch-background'
import { createRemoteController, readRemotePid } from './neovarch-remote'

const dirs: string[] = []

function tempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neovarch-bg-'))
  dirs.push(dir)

  return dir
}

afterEach(() => {
  for (const dir of dirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

describe('background settings', () => {
  it('defaults off and survives a round trip; junk falls back to defaults', () => {
    const dir = tempDir()
    const file = path.join(dir, 'bg.json')
    expect(readBackgroundSettings(file)).toEqual({ runInBackground: false, startAtLogin: false, updatedAt: 0 })
    writeBackgroundSettings(file, { runInBackground: true, startAtLogin: true, updatedAt: 10 })
    expect(readBackgroundSettings(file)).toEqual({ runInBackground: true, startAtLogin: true, updatedAt: 10 })
    expect(parseBackgroundSettings({ runInBackground: 'yes', updatedAt: -1 })).toEqual({
      runInBackground: false,
      startAtLogin: false,
      updatedAt: 0
    })
  })

  it('the newer side wins when the phone and the desktop disagree', () => {
    const local = { runInBackground: false, startAtLogin: false, updatedAt: 100 }
    // phone turned it on later
    expect(mergeWithCore(local, { run_in_background: true, start_at_login: false, updated_at: 200 })).toEqual({
      settings: { runInBackground: true, startAtLogin: false, updatedAt: 200 },
      pushToCore: false,
      changed: true
    })
    // gateway holds an older copy (e.g. fresh core): push ours
    expect(mergeWithCore(local, { run_in_background: true, start_at_login: true, updated_at: 0 })).toEqual({
      settings: local,
      pushToCore: true,
      changed: false
    })
    expect(mergeWithCore(local, { run_in_background: false, start_at_login: false, updated_at: 999 }).changed).toBe(false)
    expect(mergeWithCore(local, null).changed).toBe(false)
  })

  it('close hides only with a tray; quit detaches only when remote is on', () => {
    expect(closeAction({ runInBackground: true }, true)).toBe('hide')
    expect(closeAction({ runInBackground: true }, false)).toBe('close')
    expect(closeAction({ runInBackground: false }, true)).toBe('close')
    expect(quitGatewayAction({ runInBackground: true }, true)).toBe('detach')
    expect(quitGatewayAction({ runInBackground: true }, true, true)).toBe('stop') // "Hentikan semua & keluar"
    expect(quitGatewayAction({ runInBackground: true }, false)).toBe('stop')
    expect(quitGatewayAction({ runInBackground: false }, true)).toBe('stop')
  })

  it('Indonesian service labels', () => {
    expect(serviceLabel({ runInBackground: false, service: null })).toBe('Mati')
    expect(serviceLabel({ runInBackground: true, service: null })).toBe('Aktif — gateway belum berjalan')
    const svc = { state: 'running', mode: 'app', desktop_attached: true, pid: 1, port: 9319, uptime_s: 1 }
    expect(serviceLabel({ runInBackground: true, service: svc })).toBe('Berjalan di latar belakang')
    expect(serviceLabel({ runInBackground: true, service: { ...svc, state: 'restarting' } })).toBe('Sedang dimulai ulang')
  })
})

describe('mulai saat login', () => {
  it('Linux: writes an XDG autostart entry that launches hidden, and removes it', () => {
    const home = tempDir()
    const env = { XDG_CONFIG_HOME: path.join(home, 'cfg') }
    const file = linuxAutostartPath(env, home)
    expect(file).toBe(path.join(home, 'cfg', 'autostart', 'neovarch-agent.desktop'))

    expect(applyStartAtLogin({ enabled: true, platform: 'linux', execPath: '/opt/Neovarch Agent/neovarch', env, home })).toBeNull()
    const entry = fs.readFileSync(file, 'utf8')
    expect(entry).toContain('[Desktop Entry]')
    expect(entry).toContain(`Exec="/opt/Neovarch Agent/neovarch" ${HIDDEN_ARG}`)

    expect(applyStartAtLogin({ enabled: false, platform: 'linux', execPath: '/x', env, home })).toBeNull()
    expect(fs.existsSync(file)).toBe(false)
  })

  it('AppImage installs autostart the AppImage, not the mounted binary', () => {
    expect(launchCommand('/tmp/.mount_x/neovarch', { APPIMAGE: '/home/u/Neovarch.AppImage' })).toBe('/home/u/Neovarch.AppImage')
    expect(linuxAutostartEntry('/usr/bin/neovarch')).toContain('Exec=/usr/bin/neovarch --hidden')
  })

  it('Windows: uses the OS login item with --hidden', () => {
    const calls: unknown[] = []
    const app = { setLoginItemSettings: (s: unknown) => void calls.push(s) }
    expect(applyStartAtLogin({ enabled: true, platform: 'win32', execPath: 'C:\\Neovarch\\Neovarch.exe', app })).toBeNull()
    expect(applyStartAtLogin({ enabled: false, platform: 'win32', execPath: 'C:\\Neovarch\\Neovarch.exe', app })).toBeNull()
    expect(calls).toEqual([
      { openAtLogin: true, openAsHidden: true, path: 'C:\\Neovarch\\Neovarch.exe', args: [HIDDEN_ARG] },
      { openAtLogin: false, openAsHidden: false, path: 'C:\\Neovarch\\Neovarch.exe', args: [] }
    ])
    expect(applyStartAtLogin({ enabled: true, platform: 'aix' as NodeJS.Platform, execPath: '/x' })).toMatch(/belum didukung/)
  })

  it('detects a hidden launch', () => {
    expect(launchedHidden(['/opt/neovarch', HIDDEN_ARG])).toBe(true)
    expect(launchedHidden(['/opt/neovarch'])).toBe(false)
  })
})

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => resolve(port))
    })
  })
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0)

    return true
  } catch {
    return false
  }
}

describe.skipIf(process.platform !== 'linux')('background gateway process', () => {
  it('is spawned with a log file, survives detach (quit), and the next session adopts it', async () => {
    const dir = tempDir()
    const port = await freePort()
    const settingsPath = path.join(dir, 'neovarch-remote.json')
    fs.writeFileSync(
      settingsPath,
      JSON.stringify({ enabled: true, port, secret: Buffer.alloc(32, 1).toString('base64'), issuedAt: 1760000000 })
    )
    const pidFilePath = path.join(dir, 'neovarch-remote.pid')
    const gatewayLogPath = path.join(dir, 'gateway.log')
    const script = `console.log('gateway up');require('http').createServer((q,r)=>r.end('{}')).listen(${port},'127.0.0.1')`
    let spawns = 0

    const make = () =>
      createRemoteController({
        settingsPath,
        pidFilePath,
        gatewayLogPath,
        backgroundMode: () => true,
        currentProfile: () => null,
        log: () => {},
        resolveSpawn: async args => {
          spawns++

          return { command: process.execPath, args: ['-e', script, ...args], env: process.env }
        }
      })

    const first = make()
    first.autostart()

    for (let i = 0; i < 100 && !first.status().running; i++) {
      await new Promise(r => setTimeout(r, 100))
    }

    expect(first.status().running).toBe(true)
    const pid = readRemotePid(pidFilePath) as number
    expect(pid).toBeGreaterThan(0)

    // quit with "Jalankan di latar belakang": the gateway keeps running
    await first.detach()
    expect(first.hasProcess()).toBe(false)
    await new Promise(r => setTimeout(r, 300))
    expect(alive(pid)).toBe(true)
    expect(readRemotePid(pidFilePath)).toBe(pid)
    expect(fs.readFileSync(gatewayLogPath, 'utf8')).toContain('gateway up')

    // next launch: adopt instead of reaping + respawning
    const second = make()
    second.autostart()

    for (let i = 0; i < 50 && !second.isRunning(); i++) {
      await new Promise(r => setTimeout(r, 100))
    }

    expect(second.isRunning()).toBe(true)
    expect(spawns).toBe(1)

    // turning remote off stops the adopted gateway
    await second.shutdown()

    for (let i = 0; i < 40 && alive(pid); i++) {
      await new Promise(r => setTimeout(r, 50))
    }

    expect(alive(pid)).toBe(false)
    expect(readRemotePid(pidFilePath)).toBeNull()
  }, 30_000)
})
