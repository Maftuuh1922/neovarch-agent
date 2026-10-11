import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CLOSE,
  RelayRoom,
  byteLength,
  isValidPcId,
  parseRelayPath,
  pcIdForKey,
  takeTokens,
  verifyRoomKey
} from '../src/room.js'

class FakeSock {
  constructor(name) {
    this.name = name
    this.sent = []
    this.closed = null
  }
  send(t) {
    if (this.closed) throw new Error('closed')
    this.sent.push(t)
  }
  close(code, reason) {
    this.closed = { code, reason }
  }
  json() {
    return this.sent.filter(s => s.startsWith('{')).map(s => JSON.parse(s))
  }
}

function makeRoom(limits = {}, clock = { t: 1000 }) {
  const sockets = new Map()
  const room = new RelayRoom(
    {
      list: () => [...sockets].map(([sock, meta]) => ({ sock, meta })),
      attach: (sock, meta) => sockets.set(sock, meta),
      save: () => {},
      detach: sock => sockets.delete(sock)
    },
    limits,
    () => clock.t
  )
  return { room, sockets, clock }
}

// Shared vector with core/tests/test_remote_link.py (pc id derivation).
const KEY = 'neovarch-test-room-key-0123456789'

test('pcId derivation is a 22-char base64url sha256 prefix', async () => {
  const id = await pcIdForKey(KEY)
  assert.equal(id.length, 22)
  assert.ok(isValidPcId(id))
  assert.equal(id, 'hkPbq-MaVpvc2ZsNQZYXL6')
  assert.equal(await verifyRoomKey(id, KEY), true)
  assert.equal(await verifyRoomKey(id, KEY + 'x'), false)
  assert.equal(await verifyRoomKey(id, 'short'), false)
  assert.equal(await verifyRoomKey('bad', KEY), false)
})

test('paths', () => {
  assert.deepEqual(parseRelayPath('/v1/pc/hkPbq-MaVpvc2ZsNQZYXL6'), { role: 'pc', pcId: 'hkPbq-MaVpvc2ZsNQZYXL6' })
  assert.deepEqual(parseRelayPath('/v1/phone/hkPbq-MaVpvc2ZsNQZYXL6/'), { role: 'phone', pcId: 'hkPbq-MaVpvc2ZsNQZYXL6' })
  assert.equal(parseRelayPath('/v1/pc/../x'), null)
  assert.equal(parseRelayPath('/v1/admin/hkPbq-MaVpvc2ZsNQZYXL6'), null)
})

test('phone ↔ PC routing with connection ids', () => {
  const { room } = makeRoom()
  const pc = new FakeSock('pc')
  const p1 = new FakeSock('p1')
  const p2 = new FakeSock('p2')
  const m1 = room.joinPhone(p1) // before the PC
  assert.deepEqual(p1.json(), [{ relay: 'pc_offline' }])
  const mpc = room.joinPc(pc)
  assert.deepEqual(pc.json(), [{ type: 'join', cid: m1.cid }])
  assert.deepEqual(p1.json().at(-1), { relay: 'pc_online' })
  const m2 = room.joinPhone(p2)
  assert.deepEqual(pc.json().at(-1), { type: 'join', cid: m2.cid })

  room.message(p1, m1, 'cipher-1')
  assert.deepEqual(pc.json().at(-1), { type: 'msg', cid: m1.cid, data: 'cipher-1' })

  room.message(pc, mpc, JSON.stringify({ type: 'msg', cid: m2.cid, data: 'cipher-2' }))
  assert.equal(p2.sent.at(-1), 'cipher-2')
  assert.ok(!p1.sent.includes('cipher-2'), 'only the addressed phone gets it')

  room.message(pc, mpc, JSON.stringify({ type: 'close', cid: m1.cid }))
  assert.equal(p1.closed.code, CLOSE.BY_PC)

  room.leave(p2, m2)
  assert.deepEqual(pc.json().at(-1), { type: 'leave', cid: m2.cid })
})

test('rooms are isolated', () => {
  const a = makeRoom()
  const b = makeRoom()
  const pcA = new FakeSock('pcA')
  const pcB = new FakeSock('pcB')
  a.room.joinPc(pcA)
  b.room.joinPc(pcB)
  const ph = new FakeSock('ph')
  const m = a.room.joinPhone(ph)
  a.room.message(ph, m, 'hello')
  assert.equal(pcA.json().filter(f => f.type === 'msg').length, 1)
  assert.equal(pcB.sent.length, 0)
  // A PC cannot address a phone of another room even with its cid.
  const mpcB = b.sockets.get(pcB)
  b.room.message(pcB, mpcB, JSON.stringify({ type: 'msg', cid: m.cid, data: 'x' }))
  assert.ok(!ph.sent.includes('x'))
})

test('PC replaced by a new connection; phones told when PC leaves', () => {
  const { room } = makeRoom()
  const pc1 = new FakeSock('pc1')
  const pc2 = new FakeSock('pc2')
  const ph = new FakeSock('ph')
  room.joinPc(pc1)
  const m = room.joinPhone(ph)
  const m2 = room.joinPc(pc2)
  assert.equal(pc1.closed.code, CLOSE.REPLACED)
  assert.deepEqual(pc2.json()[0], { type: 'join', cid: m.cid })
  room.leave(pc2, m2)
  assert.deepEqual(ph.json().at(-1), { relay: 'pc_offline' })
  room.message(ph, m, 'lost')
  assert.deepEqual(ph.json().at(-1), { relay: 'pc_offline' })
})

test('limits: size, binary, room full', () => {
  const { room } = makeRoom({ maxMessageBytes: 10, maxPhonesPerRoom: 2 })
  const pc = new FakeSock('pc')
  room.joinPc(pc)
  const a = new FakeSock('a')
  const ma = room.joinPhone(a)
  const b = new FakeSock('b')
  room.joinPhone(b)
  const c = new FakeSock('c')
  assert.equal(room.joinPhone(c), null)
  assert.equal(c.closed.code, CLOSE.ROOM_FULL)
  room.message(a, ma, 'x'.repeat(11))
  assert.equal(a.closed.code, CLOSE.TOO_BIG)
  const d = new FakeSock('d')
  const md = room.joinPhone(d)
  room.message(d, md, new Uint8Array([1, 2]))
  assert.equal(d.closed.code, CLOSE.BINARY)
})

test('rate limit closes a flooding connection', () => {
  const clock = { t: 0 }
  const { room } = makeRoom({ msgBurst: 5, msgPerSec: 1 }, clock)
  const pc = new FakeSock('pc')
  room.joinPc(pc)
  const ph = new FakeSock('ph')
  const m = room.joinPhone(ph)
  for (let i = 0; i < 5; i++) room.message(ph, m, 'm' + i)
  assert.equal(ph.closed, null)
  room.message(ph, m, 'flood')
  assert.equal(ph.closed.code, CLOSE.RATE_LIMITED)
})

test('token bucket refills over time', () => {
  const lim = { msgBurst: 2, msgPerSec: 1, byteBurst: 100, bytePerSec: 10 }
  const s = {}
  assert.ok(takeTokens(s, 10, lim, 0))
  assert.ok(takeTokens(s, 10, lim, 0))
  assert.ok(!takeTokens(s, 10, lim, 0))
  assert.ok(takeTokens(s, 10, lim, 1000))
  assert.ok(!takeTokens({}, 101, lim, 0), 'byte budget')
})

test('ping is answered by the relay, idle connections are swept', () => {
  const clock = { t: 0 }
  const { room } = makeRoom({ idleMs: 1000 }, clock)
  const pc = new FakeSock('pc')
  const mpc = room.joinPc(pc)
  const ph = new FakeSock('ph')
  room.joinPhone(ph)
  clock.t = 900
  room.message(pc, mpc, 'ping')
  assert.equal(pc.sent.at(-1), 'pong')
  clock.t = 1500
  assert.equal(room.sweepIdle(), 1)
  assert.equal(ph.closed.code, CLOSE.IDLE)
  assert.equal(pc.closed, null)
})

test('byteLength counts UTF-8', () => {
  assert.equal(byteLength('abc'), 3)
  assert.equal(byteLength('é'), 2)
  assert.equal(byteLength('😀'), 4)
})
