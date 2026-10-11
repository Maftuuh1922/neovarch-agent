// Neovarch relay: one room per PC. Platform-neutral core shared by the
// Cloudflare Worker (Durable Object) and the standalone Node server.
//
// The relay is a dumb forwarder. It never sees plaintext: every payload the
// phone and the PC exchange is end-to-end encrypted (see docs/relay.md). It
// stores nothing except the live sockets of a room.
//
// Wire protocol (text frames only, UTF-8):
//
//   PC     connects  /v1/pc/<pcId>?k=<roomKey>     pcId = b64url(sha256(roomKey))[:22]
//   phone  connects  /v1/phone/<pcId>
//
//   relay → PC     {"type":"join","cid":"…"}         a phone entered the room
//                  {"type":"msg","cid":"…","data":"…"} a phone sent `data`
//                  {"type":"leave","cid":"…"}         a phone left
//                  "pong"                             answer to "ping"
//   PC → relay     {"type":"msg","cid":"…","data":"…"} deliver `data` to one phone
//                  {"type":"close","cid":"…"}         disconnect one phone
//                  "ping"                             keepalive
//
//   relay → phone  <data from the PC, verbatim>
//                  {"relay":"pc_online"} | {"relay":"pc_offline"}  room status
//                  "pong"
//   phone → relay  <any text: forwarded to the PC as a `msg`>
//                  "ping"                             keepalive
//
// Close codes: 1003 binary frame, 1009 too big, 4000 replaced by a new PC
// connection, 4001 closed by the PC, 4004 bad room / key, 4008 room full,
// 4029 rate limited, 4040 idle.

export const DEFAULT_LIMITS = Object.freeze({
  maxMessageBytes: 256 * 1024,
  maxPhonesPerRoom: 5,
  idleMs: 120_000,
  // token buckets per connection
  msgBurst: 400,
  msgPerSec: 100,
  byteBurst: 4 * 1024 * 1024,
  bytePerSec: 1024 * 1024
})

export const CLOSE = Object.freeze({
  BINARY: 1003,
  TOO_BIG: 1009,
  REPLACED: 4000,
  BY_PC: 4001,
  BAD_ROOM: 4004,
  ROOM_FULL: 4008,
  RATE_LIMITED: 4029,
  IDLE: 4040
})

const PC_ID = /^[A-Za-z0-9_-]{22}$/

export function isValidPcId(id) {
  return typeof id === 'string' && PC_ID.test(id)
}

function b64url(bytes) {
  let s = ''
  for (const b of bytes) s += String.fromCharCode(b)
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** pcId for a room key: base64url(sha256(utf8(key)))[:22]. WebCrypto (Workers + Node ≥ 20). */
export async function pcIdForKey(key) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(key)))
  return b64url(new Uint8Array(digest)).slice(0, 22)
}

/** True when `key` owns room `pcId` (constant-time compare of the derived id). */
export async function verifyRoomKey(pcId, key) {
  if (!isValidPcId(pcId) || typeof key !== 'string' || key.length < 16 || key.length > 256) return false
  const want = await pcIdForKey(key)
  let diff = 0
  for (let i = 0; i < 22; i++) diff |= want.charCodeAt(i) ^ pcId.charCodeAt(i)
  return diff === 0
}

export function randomCid() {
  const b = new Uint8Array(8)
  crypto.getRandomValues(b)
  return Array.from(b, x => x.toString(16).padStart(2, '0')).join('')
}

export function byteLength(s) {
  // UTF-8 length without allocating for ASCII-only strings (ciphertext is base64).
  let n = 0
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    if (c < 0x80) n += 1
    else if (c < 0x800) n += 2
    else if (c >= 0xd800 && c <= 0xdbff) {
      n += 4
      i++
    } else n += 3
  }
  return n
}

/** Token bucket for messages and bytes. State is a plain object (serializable). */
export function takeTokens(state, bytes, limits, now) {
  const dt = Math.max(0, (now - (state.t ?? now)) / 1000)
  state.t = now
  state.m = Math.min(limits.msgBurst, (state.m ?? limits.msgBurst) + dt * limits.msgPerSec)
  state.b = Math.min(limits.byteBurst, (state.b ?? limits.byteBurst) + dt * limits.bytePerSec)
  if (state.m < 1 || state.b < bytes) return false
  state.m -= 1
  state.b -= bytes
  return true
}

/**
 * One room. `store` abstracts where sockets live:
 *   store.list()            → [{ sock, meta }]   meta = { role:'pc'|'phone', cid?, last }
 *   store.attach(sock,meta) remember the socket (meta is mutable and persisted via store.save)
 *   store.save(sock, meta)  persist a mutated meta (DO: serializeAttachment; Node: no-op)
 *   store.detach(sock)
 * Sockets need `send(text)` and `close(code, reason)`.
 */
export class RelayRoom {
  constructor(store, limits = DEFAULT_LIMITS, now = () => Date.now()) {
    this.store = store
    this.limits = { ...DEFAULT_LIMITS, ...limits }
    this.now = now
  }

  pc() {
    return this.store.list().find(e => e.meta.role === 'pc') ?? null
  }

  phones() {
    return this.store.list().filter(e => e.meta.role === 'phone')
  }

  phone(cid) {
    return this.phones().find(e => e.meta.cid === cid) ?? null
  }

  static safeSend(sock, text) {
    try {
      sock.send(text)
      return true
    } catch {
      return false
    }
  }

  static safeClose(sock, code, reason) {
    try {
      sock.close(code, reason)
    } catch {
      // already gone
    }
  }

  joinPc(sock) {
    const old = this.pc()
    if (old) {
      this.store.detach(old.sock)
      RelayRoom.safeClose(old.sock, CLOSE.REPLACED, 'replaced')
    }
    const meta = { role: 'pc', last: this.now() }
    this.store.attach(sock, meta)
    for (const p of this.phones()) {
      RelayRoom.safeSend(sock, JSON.stringify({ type: 'join', cid: p.meta.cid }))
      RelayRoom.safeSend(p.sock, '{"relay":"pc_online"}')
    }
    return meta
  }

  joinPhone(sock) {
    if (this.phones().length >= this.limits.maxPhonesPerRoom) {
      RelayRoom.safeClose(sock, CLOSE.ROOM_FULL, 'room_full')
      return null
    }
    const meta = { role: 'phone', cid: randomCid(), last: this.now() }
    this.store.attach(sock, meta)
    const pc = this.pc()
    if (pc) {
      RelayRoom.safeSend(pc.sock, JSON.stringify({ type: 'join', cid: meta.cid }))
      RelayRoom.safeSend(sock, '{"relay":"pc_online"}')
    } else {
      RelayRoom.safeSend(sock, '{"relay":"pc_offline"}')
    }
    return meta
  }

  /** A frame arrived on `sock`. `data` is a string, or anything else for a binary frame. */
  message(sock, meta, data) {
    if (typeof data !== 'string') {
      this.drop(sock, meta, CLOSE.BINARY, 'text_only')
      return
    }
    const size = byteLength(data)
    if (size > this.limits.maxMessageBytes) {
      this.drop(sock, meta, CLOSE.TOO_BIG, 'too_big')
      return
    }
    const now = this.now()
    meta.rl ??= {}
    if (!takeTokens(meta.rl, size, this.limits, now)) {
      this.drop(sock, meta, CLOSE.RATE_LIMITED, 'rate_limited')
      return
    }
    meta.last = now
    this.store.save(sock, meta)
    if (data === 'ping') {
      RelayRoom.safeSend(sock, 'pong')
      return
    }
    if (meta.role === 'phone') {
      const pc = this.pc()
      if (!pc) {
        RelayRoom.safeSend(sock, '{"relay":"pc_offline"}')
        return
      }
      RelayRoom.safeSend(pc.sock, JSON.stringify({ type: 'msg', cid: meta.cid, data }))
      return
    }
    // from the PC
    let f
    try {
      f = JSON.parse(data)
    } catch {
      return
    }
    if (!f || typeof f !== 'object' || typeof f.cid !== 'string') return
    const target = this.phone(f.cid)
    if (!target) {
      if (f.type === 'msg') RelayRoom.safeSend(sock, JSON.stringify({ type: 'leave', cid: f.cid }))
      return
    }
    if (f.type === 'msg' && typeof f.data === 'string') {
      RelayRoom.safeSend(target.sock, f.data)
    } else if (f.type === 'close') {
      this.store.detach(target.sock)
      RelayRoom.safeClose(target.sock, CLOSE.BY_PC, 'closed_by_pc')
    }
  }

  drop(sock, meta, code, reason) {
    this.leave(sock, meta)
    RelayRoom.safeClose(sock, code, reason)
  }

  /** The socket closed (or is being dropped). Idempotent. */
  leave(sock, meta) {
    const known = this.store.list().some(e => e.sock === sock)
    if (!known) return
    this.store.detach(sock)
    if (meta?.role === 'phone') {
      const pc = this.pc()
      if (pc) RelayRoom.safeSend(pc.sock, JSON.stringify({ type: 'leave', cid: meta.cid }))
    } else if (meta?.role === 'pc') {
      for (const p of this.phones()) RelayRoom.safeSend(p.sock, '{"relay":"pc_offline"}')
    }
  }

  /** Close connections silent for longer than idleMs. `lastSeen(entry)` may add platform keepalive times. */
  sweepIdle(lastSeen = e => e.meta.last ?? 0) {
    const cutoff = this.now() - this.limits.idleMs
    let open = 0
    for (const e of this.store.list()) {
      if (lastSeen(e) < cutoff) this.drop(e.sock, e.meta, CLOSE.IDLE, 'idle')
      else open++
    }
    return open
  }
}

/** Parse `/v1/pc/<id>` and `/v1/phone/<id>`; null for anything else. */
export function parseRelayPath(pathname) {
  const m = /^\/v1\/(pc|phone)\/([^/]+)\/?$/.exec(pathname)
  if (!m || !isValidPcId(m[2])) return null
  return { role: m[1], pcId: m[2] }
}

export const HEALTH = Object.freeze({ ok: true, service: 'neovarch-relay', protocol: 1 })
