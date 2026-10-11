// The Cloudflare entry points against a small in-memory imitation of the
// Workers runtime (WebSocketPair, hibernation state). Exercises routing, the
// room-key check and the Durable Object glue without wrangler.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pcIdForKey } from '../src/room.js'

class FakeWS {
  constructor() {
    this.sent = []
    this.att = null
    this.closed = null
  }
  send(t) {
    this.sent.push(t)
  }
  close(code, reason) {
    this.closed = { code, reason }
  }
  serializeAttachment(v) {
    this.att = structuredClone(v)
  }
  deserializeAttachment() {
    return this.att ? structuredClone(this.att) : null
  }
}

globalThis.WebSocketPair = class {
  constructor() {
    this[0] = new FakeWS()
    this[1] = new FakeWS()
  }
}
globalThis.WebSocketRequestResponsePair = class {
  constructor(req, res) {
    Object.assign(this, { req, res })
  }
}
const RealResponse = globalThis.Response
globalThis.Response = class extends RealResponse {
  constructor(body, init = {}) {
    super(body, init.status === 101 ? { ...init, status: 200 } : init)
    if (init.status === 101) Object.defineProperty(this, 'status', { value: 101 })
    this.webSocket = init.webSocket
  }
  static json(v, init) {
    return RealResponse.json(v, init)
  }
}

const { default: worker, RelayRoomDO } = await import('../src/worker.js')

function fakeState() {
  const sockets = []
  let alarm = null
  return {
    sockets,
    setWebSocketAutoResponse() {},
    acceptWebSocket(ws) {
      sockets.push(ws)
    },
    getWebSockets() {
      return sockets.filter(s => !s.closed)
    },
    getWebSocketAutoResponseTimestamp() {
      return null
    },
    storage: {
      getAlarm: async () => alarm,
      setAlarm: async t => {
        alarm = t
      }
    }
  }
}

test('worker routes, checks the room key and strips it before the object', async () => {
  const key = 'room-key-'.repeat(4)
  const pcId = await pcIdForKey(key)
  const seen = []
  const env = {
    ROOMS: {
      idFromName: n => n,
      get: () => ({ fetch: req => (seen.push(req.url), new Response('ok')) })
    }
  }
  const up = { headers: { Upgrade: 'websocket' } }
  assert.equal((await worker.fetch(new Request('https://r/health'), env)).status, 200)
  assert.equal((await worker.fetch(new Request('https://r/nope'), env)).status, 404)
  assert.equal((await worker.fetch(new Request(`https://r/v1/pc/${pcId}?k=${key}`), env)).status, 426)
  assert.equal((await worker.fetch(new Request(`https://r/v1/pc/${pcId}?k=wrongwrongwrongwrong`, up), env)).status, 403)
  assert.equal((await worker.fetch(new Request(`https://r/v1/pc/${pcId}?k=${key}`, up), env)).status, 200)
  assert.equal((await worker.fetch(new Request(`https://r/v1/phone/${pcId}`, up), env)).status, 200)
  assert.ok(seen.every(u => !u.includes('k=')), 'room key never forwarded')
  assert.deepEqual(seen.map(u => new URL(u).searchParams.get('role')), ['pc', 'phone'])
})

test('durable object forwards between PC and phone', async () => {
  const state = fakeState()
  const dobj = new RelayRoomDO(state, {})
  const r1 = await dobj.fetch(new Request('https://r/v1/pc/x?role=pc'))
  assert.equal(r1.status, 101)
  const pcServer = state.sockets[0]
  await dobj.fetch(new Request('https://r/v1/phone/x?role=phone'))
  const phServer = state.sockets[1]
  assert.deepEqual(JSON.parse(phServer.sent[0]), { relay: 'pc_online' })
  const join = JSON.parse(pcServer.sent[0])
  assert.equal(join.type, 'join')

  await dobj.webSocketMessage(phServer, 'ct-1')
  assert.deepEqual(JSON.parse(pcServer.sent.at(-1)), { type: 'msg', cid: join.cid, data: 'ct-1' })
  await dobj.webSocketMessage(pcServer, JSON.stringify({ type: 'msg', cid: join.cid, data: 'ct-2' }))
  assert.equal(phServer.sent.at(-1), 'ct-2')

  await dobj.webSocketClose(phServer)
  assert.deepEqual(JSON.parse(pcServer.sent.at(-1)), { type: 'leave', cid: join.cid })
})
