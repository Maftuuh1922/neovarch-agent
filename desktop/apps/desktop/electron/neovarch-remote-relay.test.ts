// Remote dari mana saja: the pairing QR carries the relay identity, the
// default relay URL is a single constant, and the remote gateway is started
// with the link env.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { buildPairingUri, createRemoteController } from './neovarch-remote'
import { DEFAULT_RELAY_URL, DEFAULT_RELAY_URL_BUILTIN, effectiveRelayUrl, isUsableRelayUrl, normalizeRelayUrl } from './relay-defaults'

const LINK = {
  pc_id: 'hkPbq-MaVpvc2ZsNQZYXL6',
  pc_pk: 'A'.repeat(43),
  relay: { enabled: true, url: 'wss://relay.example.test', state: 'online', error: null, phones: 1 },
  bluetooth: { enabled: false, state: 'off', error: null, address: null, channel: null, phones: 0 },
  devices: [{ id: 'dev1', name: 'HP Andi', added: 1, last_seen: 2, via: 'relay' }],
  pair_code: 'code-123',
  pair_expires: 9999999999
}

describe('relay defaults', () => {
  it('has one built-in default (mirrored by the core) and normalizes URLs', () => {
    expect(DEFAULT_RELAY_URL).toBe(DEFAULT_RELAY_URL_BUILTIN)
    const core = fs.readFileSync(path.resolve(__dirname, '../../../../core/neovarch/remote_link/__init__.py'), 'utf8')
    expect(core).toContain(`DEFAULT_RELAY_URL = "${DEFAULT_RELAY_URL_BUILTIN}"`)
    expect(normalizeRelayUrl('https://r.example.com/')).toBe('wss://r.example.com')
    expect(normalizeRelayUrl('r.example.com')).toBe('wss://r.example.com')
    expect(normalizeRelayUrl('ftp://x')).toBeNull()
    expect(normalizeRelayUrl('')).toBeNull()
  })

  it('v1.4.7: no built-in relay; the never-deployed default counts as "not configured"', () => {
    expect(DEFAULT_RELAY_URL_BUILTIN).toBe('')
    expect(isUsableRelayUrl('wss://relay.neovarchlabs.web.id')).toBe(false)
    expect(isUsableRelayUrl('https://relay.neovarchlabs.web.id/')).toBe(false)
    expect(effectiveRelayUrl('wss://relay.neovarchlabs.web.id')).toBeNull()
    expect(effectiveRelayUrl(null)).toBeNull()
    expect(effectiveRelayUrl('https://relay.mine.test')).toBe('wss://relay.mine.test')
  })
})

describe('pairing URI with the relay identity', () => {
  it('adds pc, pk, relay and pair; old fields unchanged', () => {
    const uri = buildPairingUri({
      url: 'http://192.168.1.5:9319',
      token: 't',
      name: 'PC',
      profile: null,
      alt: ['http://pc.tail1.ts.net:9319'],
      link: { pcId: LINK.pc_id, pcPk: LINK.pc_pk, relayUrl: 'wss://relay.example.test', pairCode: 'code-123' }
    })

    const q = new URL(uri.replace('neovarch://', 'http://')).searchParams
    expect(q.get('url')).toBe('http://192.168.1.5:9319')
    expect(q.getAll('alt')).toEqual(['http://pc.tail1.ts.net:9319'])
    expect(q.get('pc')).toBe(LINK.pc_id)
    expect(q.get('pk')).toBe(LINK.pc_pk)
    expect(q.get('relay')).toBe('wss://relay.example.test')
    expect(q.get('pair')).toBe('code-123')
    expect(q.get('bt')).toBeNull()
  })
})

describe('remote controller relay settings', () => {
  function makeController(fetchImpl: typeof fetch) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nv-relay-'))
    const ctl = createRemoteController({
      settingsPath: path.join(dir, 'remote.json'),
      resolveSpawn: async () => ({ command: process.execPath, args: ['-e', 'setInterval(()=>{},1000)'], env: {} }),
      currentProfile: () => null,
      log: () => {},
      portInUse: async () => false,
      listProcesses: async () => [],
      fetch: fetchImpl
    })

    return { ctl, dir }
  }

  it('defaults: no relay configured (stays off), Bluetooth off, no devices yet', () => {
    const { ctl } = makeController((async () => new Response('{}', { status: 404 })) as typeof fetch)
    const s = ctl.status()
    expect(s.relay.configured).toBe(false)
    expect(s.relay.url).toBe('')
    expect(s.relay.state).toBe('off')
    expect(s.bluetooth.enabled).toBe(false)
    expect(s.devices).toEqual([])
  })

  it('a saved setting with the old built-in URL is treated as no relay', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nv-relay-old-'))
    fs.writeFileSync(path.join(dir, 'remote.json'), JSON.stringify({ relayEnabled: true, relayUrl: 'wss://relay.neovarchlabs.web.id' }))
    const ctl = createRemoteController({
      settingsPath: path.join(dir, 'remote.json'),
      resolveSpawn: async () => ({ command: process.execPath, args: ['-e', ''], env: {} }),
      currentProfile: () => null,
      log: () => {},
      portInUse: async () => false,
      listProcesses: async () => []
    })
    expect(ctl.status().relay.configured).toBe(false)
  })

  it('persists a custom relay URL, rejects a bad one, empty turns the relay off', async () => {
    const { ctl, dir } = makeController((async () => new Response('{}', { status: 404 })) as typeof fetch)
    let s = await ctl.setRelay({ url: 'https://relay.mine.test' })
    expect(s.relay.url).toBe('wss://relay.mine.test')
    expect(s.relay.configured).toBe(true)
    expect(JSON.parse(fs.readFileSync(path.join(dir, 'remote.json'), 'utf8')).relayUrl).toBe('wss://relay.mine.test')
    s = await ctl.setRelay({ url: 'ftp://nope' })
    expect(s.error).toMatch(/wss:\/\//)
    expect(s.relay.url).toBe('wss://relay.mine.test')
    s = await ctl.setRelay({ url: '' })
    expect(s.relay.url).toBe(DEFAULT_RELAY_URL)
    expect(s.relay.configured).toBe(false)
    s = await ctl.setRelay({ enabled: false })
    expect(s.relay.enabled).toBe(false)
    s = await ctl.setBluetooth(true)
    expect(s.bluetooth.enabled).toBe(true)
  })
})
