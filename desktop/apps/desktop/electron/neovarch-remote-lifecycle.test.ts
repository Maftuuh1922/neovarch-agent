// LAN gateway lifecycle: the remote gateway is the only second core process the
// desktop may run, it must die with the app, and a gateway left behind by a
// crashed desktop must be recovered instead of blocking the port forever.
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { createRemoteController, isOwnRemoteGatewayCommand, ownGatewayPids, readRemotePid } from './neovarch-remote'

const dirs: string[] = []

function tempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neovarch-remote-'))
  dirs.push(dir)

  return dir
}

afterEach(() => {
  for (const dir of dirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true })
  }
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

function writeSettings(dir: string, port: number, enabled = true): string {
  const settingsPath = path.join(dir, 'neovarch-remote.json')
  fs.writeFileSync(
    settingsPath,
    JSON.stringify({ enabled, port, secret: Buffer.alloc(32, 1).toString('base64'), issuedAt: 1760000000 })
  )

  return settingsPath
}

describe('isOwnRemoteGatewayCommand', () => {
  it('matches only our serve --port <port> --isolated LAN gateway', () => {
    const cmd = '/home/u/.neovarch/venv/bin/python -m neovarch serve --host 0.0.0.0 --port 9319 --isolated'
    expect(isOwnRemoteGatewayCommand(cmd, 9319)).toBe(true)
    expect(isOwnRemoteGatewayCommand(cmd, 9320)).toBe(false)
    // The desktop's own loopback backend is not the LAN gateway.
    expect(isOwnRemoteGatewayCommand('python -m neovarch serve --port 9319', 9319)).toBe(false)
    expect(isOwnRemoteGatewayCommand('/usr/bin/bash', 9319)).toBe(false)
    expect(isOwnRemoteGatewayCommand(null, 9319)).toBe(false)
  })
})

describe('stale LAN gateway recovery', () => {
  it('stops a recorded gateway still running from a crashed desktop, then forgets it', async () => {
    const dir = tempDir()
    const settingsPath = writeSettings(dir, 9319)
    const pidFilePath = path.join(dir, 'neovarch-remote.pid')
    fs.writeFileSync(pidFilePath, '4711\n')
    let alive = true
    const signals: string[] = []

    const remote = createRemoteController({
      settingsPath,
      pidFilePath,
      currentProfile: () => null,
      log: () => {},
      resolveSpawn: async () => {
        throw new Error('not spawned in this test')
      },
      processCommandLine: pid =>
        pid === 4711 && alive ? 'python -m neovarch serve --host 0.0.0.0 --port 9319 --isolated' : null,
      killProcessGroup: (pid, signal) => {
        signals.push(`${pid}:${signal}`)
        alive = false
      }
    })

    expect(await remote.reapStaleGateway()).toBe(4711)
    expect(signals).toEqual(['4711:SIGTERM'])
    expect(readRemotePid(pidFilePath)).toBeNull()
  })

  it('stops an orphan gateway an older desktop left on the port without a PID file', async () => {
    const dir = tempDir()
    const settingsPath = writeSettings(dir, 9319)
    let busy = true
    const signals: string[] = []

    const remote = createRemoteController({
      settingsPath,
      pidFilePath: path.join(dir, 'neovarch-remote.pid'),
      currentProfile: () => null,
      log: () => {},
      resolveSpawn: async () => {
        throw new Error('not spawned')
      },
      portInUse: async () => busy,
      listProcesses: async () => [
        { command: '/usr/bin/firefox', pid: 10 },
        { command: '/home/u/.neovarch/neovarch-agent/venv/bin/neovarch serve --host 0.0.0.0 --port 9319 --isolated', pid: 4242 },
        { command: 'python -m neovarch serve --port 9319', pid: 11 }
      ],
      killProcessGroup: (pid, signal) => {
        signals.push(`${pid}:${signal}`)
        busy = false
      }
    })

    expect(await remote.reapStaleGateway()).toBe(4242)
    expect(signals).toEqual(['4242:SIGTERM'])
  })

  it('leaves a port alone when what holds it is not our gateway', async () => {
    const dir = tempDir()
    const signals: string[] = []

    const remote = createRemoteController({
      settingsPath: writeSettings(dir, 9319),
      pidFilePath: path.join(dir, 'neovarch-remote.pid'),
      currentProfile: () => null,
      log: () => {},
      resolveSpawn: async () => {
        throw new Error('not spawned')
      },
      portInUse: async () => true,
      listProcesses: async () => [{ command: 'node server.js --port 9319', pid: 77 }],
      killProcessGroup: (pid, signal) => signals.push(`${pid}:${signal}`)
    })

    expect(await remote.reapStaleGateway()).toBeNull()
    expect(signals).toEqual([])
    expect(ownGatewayPids([{ command: 'x serve --host 0.0.0.0 --port 9319 --isolated', pid: 5 }], 9319, [5])).toEqual([])
  })

  it('never signals a reused PID that is not our gateway', async () => {
    const dir = tempDir()
    const settingsPath = writeSettings(dir, 9319)
    const pidFilePath = path.join(dir, 'neovarch-remote.pid')
    fs.writeFileSync(pidFilePath, '4711\n')
    const signals: string[] = []

    const remote = createRemoteController({
      settingsPath,
      pidFilePath,
      currentProfile: () => null,
      log: () => {},
      resolveSpawn: async () => {
        throw new Error('not spawned')
      },
      processCommandLine: () => '/usr/bin/firefox',
      killProcessGroup: (pid, signal) => signals.push(`${pid}:${signal}`)
    })

    expect(await remote.reapStaleGateway()).toBeNull()
    expect(signals).toEqual([])
    expect(readRemotePid(pidFilePath)).toBeNull()
  })

  it('after shutdown (quit) a late autostart spawns nothing', async () => {
    const dir = tempDir()
    let spawns = 0

    const remote = createRemoteController({
      settingsPath: writeSettings(dir, 9319),
      currentProfile: () => null,
      log: () => {},
      portInUse: async () => false,
      resolveSpawn: async () => {
        spawns += 1
        throw new Error('should not spawn')
      }
    })

    await remote.shutdown()
    remote.autostart()
    await new Promise(r => setTimeout(r, 50))
    expect(spawns).toBe(0)
    expect(remote.hasProcess()).toBe(false)
  })
})

describe.skipIf(process.platform !== 'linux')('real gateway process', () => {
  it('records its PID while running and is killed + forgotten on shutdown', async () => {
    const dir = tempDir()
    const port = await freePort()
    const settingsPath = writeSettings(dir, port)
    const pidFilePath = path.join(dir, 'neovarch-remote.pid')
    // Stand-in core: answers /api/status on the port and carries the gateway argv.
    const script = `require('http').createServer((q,r)=>r.end('{}')).listen(${port},'127.0.0.1')`

    const remote = createRemoteController({
      settingsPath,
      pidFilePath,
      currentProfile: () => null,
      log: () => {},
      resolveSpawn: async args => ({ command: process.execPath, args: ['-e', script, ...args], env: process.env })
    })

    remote.autostart()

    for (let i = 0; i < 100 && !remote.status().running; i++) {
      await new Promise(r => setTimeout(r, 100))
    }

    expect(remote.status().running).toBe(true)
    expect(remote.hasProcess()).toBe(true)
    const pid = readRemotePid(pidFilePath)
    expect(pid).not.toBeNull()

    await remote.shutdown()
    expect(remote.hasProcess()).toBe(false)

    let gone = false

    for (let i = 0; i < 40 && !gone; i++) {
      try {
        process.kill(pid as number, 0)
        await new Promise(r => setTimeout(r, 50))
      } catch {
        gone = true
      }
    }

    expect(gone).toBe(true)
    expect(readRemotePid(pidFilePath)).toBeNull()
  }, 20_000)
})
