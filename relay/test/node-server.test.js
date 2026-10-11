// End-to-end over real sockets: Node relay + Node's built-in WebSocket client.
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { test } from 'node:test'
import { createRelayServer } from '../src/node-server.js'
import { pcIdForKey } from '../src/room.js'

function open(url) {
  const ws = new WebSocket(url)
  const inbox = []
  const waiters = []
  ws.addEventListener('message', e => {
    const w = waiters.shift()
    if (w) w(e.data)
    else inbox.push(e.data)
  })
  ws.next = () => (inbox.length ? Promise.resolve(inbox.shift()) : new Promise(r => waiters.push(r)))
  ws.closedWith = new Promise(r => ws.addEventListener('close', e => r(e.code)))
  return new Promise((resolve, reject) => {
    ws.addEventListener('open', () => resolve(ws))
    ws.addEventListener('error', reject)
  })
}

async function start(limits) {
  const { server } = createRelayServer({ limits })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const base = `ws://127.0.0.1:${server.address().port}`
  return { server, base }
}

test('relay forwards between PC and phone and rejects a wrong room key', async () => {
  const { server, base } = await start()
  try {
    const key = 'k'.repeat(32)
    const pcId = await pcIdForKey(key)

    await assert.rejects(open(`${base}/v1/pc/${pcId}?k=${'x'.repeat(32)}`))

    const pc = await open(`${base}/v1/pc/${pcId}?k=${key}`)
    const phone = await open(`${base}/v1/phone/${pcId}`)
    assert.deepEqual(JSON.parse(await phone.next()), { relay: 'pc_online' })
    const join = JSON.parse(await pc.next())
    assert.equal(join.type, 'join')

    phone.send('hello-ciphertext')
    assert.deepEqual(JSON.parse(await pc.next()), { type: 'msg', cid: join.cid, data: 'hello-ciphertext' })

    const big = 'z'.repeat(70_000) // > 64 KiB: exercises 64-bit length frames
    pc.send(JSON.stringify({ type: 'msg', cid: join.cid, data: big }))
    assert.equal(await phone.next(), big)

    phone.send('ping')
    assert.equal(await phone.next(), 'pong')

    phone.close()
    assert.deepEqual(JSON.parse(await pc.next()), { type: 'leave', cid: join.cid })
    pc.close()
  } finally {
    server.close()
  }
})

test('oversized message closes with 1009', async () => {
  const { server, base } = await start({ maxMessageBytes: 1000 })
  try {
    const key = 'q'.repeat(40)
    const pcId = await pcIdForKey(key)
    const pc = await open(`${base}/v1/pc/${pcId}?k=${key}`)
    const phone = await open(`${base}/v1/phone/${pcId}`)
    await phone.next()
    await pc.next()
    phone.send('y'.repeat(1001))
    assert.equal(await phone.closedWith, 1009)
    pc.close()
  } finally {
    server.close()
  }
})

test('health endpoint', async () => {
  const { server, base } = await start()
  try {
    const res = await fetch(base.replace('ws:', 'http:') + '/health')
    const j = await res.json()
    assert.equal(j.service, 'neovarch-relay')
    assert.equal(j.protocol, 1)
  } finally {
    server.close()
  }
})
