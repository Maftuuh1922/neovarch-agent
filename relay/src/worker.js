// Cloudflare Worker + Durable Object (free plan, SQLite-backed class).
// One Durable Object instance per room (pcId). Uses the WebSocket Hibernation
// API so idle rooms cost nothing; "ping" → "pong" is answered by Cloudflare
// without waking the object. Nothing is written to storage: the only state is
// the live sockets and their attachments.
import { CLOSE, DEFAULT_LIMITS, HEALTH, RelayRoom, parseRelayPath, verifyRoomKey } from './room.js'

function limitsFromEnv(env) {
  const n = (k, d) => {
    const v = Number(env?.[k])
    return Number.isFinite(v) && v > 0 ? v : d
  }
  return {
    maxMessageBytes: n('MAX_MESSAGE_BYTES', DEFAULT_LIMITS.maxMessageBytes),
    maxPhonesPerRoom: n('MAX_PHONES_PER_ROOM', DEFAULT_LIMITS.maxPhonesPerRoom),
    idleMs: n('IDLE_SECONDS', DEFAULT_LIMITS.idleMs / 1000) * 1000
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    if (url.pathname === '/' || url.pathname === '/health') {
      return Response.json(HEALTH, { headers: { 'cache-control': 'no-store' } })
    }
    const route = parseRelayPath(url.pathname)
    if (!route) return new Response('not found', { status: 404 })
    if (request.headers.get('Upgrade')?.toLowerCase() !== 'websocket') {
      return new Response('expected websocket', { status: 426 })
    }
    if (route.role === 'pc' && !(await verifyRoomKey(route.pcId, url.searchParams.get('k') ?? ''))) {
      return new Response('bad room key', { status: 403 })
    }
    const stub = env.ROOMS.get(env.ROOMS.idFromName(route.pcId))
    const fwd = new URL(request.url)
    fwd.search = '' // the room key never reaches the object
    fwd.searchParams.set('role', route.role)
    return stub.fetch(new Request(fwd, request))
  }
}

export class RelayRoomDO {
  constructor(state, env) {
    this.state = state
    this.limits = limitsFromEnv(env)
    // Answered at the edge without waking a hibernated object.
    state.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'))
    const s = state
    this.room = new RelayRoom(
      {
        list: () =>
          s
            .getWebSockets()
            .map(sock => ({ sock, meta: sock.deserializeAttachment() }))
            .filter(e => e.meta && !e.meta.gone),
        attach: (sock, meta) => {
          s.acceptWebSocket(sock, [meta.role])
          sock.serializeAttachment(meta)
        },
        save: (sock, meta) => sock.serializeAttachment(meta),
        detach: sock => {
          // getWebSockets() still lists a socket until it is fully closed.
          const meta = sock.deserializeAttachment() ?? {}
          sock.serializeAttachment({ ...meta, gone: true })
        }
      },
      this.limits
    )
  }

  async fetch(request) {
    const role = new URL(request.url).searchParams.get('role')
    const pair = new WebSocketPair()
    const [client, server] = Object.values(pair)
    const meta = role === 'pc' ? this.room.joinPc(server) : this.room.joinPhone(server)
    if (!meta) {
      // room full: accept, then close with the reason so the phone can show it
      this.state.acceptWebSocket(server, ['rejected'])
      server.serializeAttachment({ role: 'rejected', gone: true })
      server.close(CLOSE.ROOM_FULL, 'room_full')
    }
    await this.ensureAlarm()
    return new Response(null, { status: 101, webSocket: client })
  }

  async webSocketMessage(ws, message) {
    const meta = ws.deserializeAttachment()
    if (!meta || meta.gone) return
    this.room.message(ws, meta, message)
  }

  async webSocketClose(ws) {
    const meta = ws.deserializeAttachment()
    if (meta && !meta.gone) this.room.leave(ws, meta)
  }

  async webSocketError(ws) {
    await this.webSocketClose(ws)
  }

  async ensureAlarm() {
    if ((await this.state.storage.getAlarm()) == null) {
      await this.state.storage.setAlarm(Date.now() + this.limits.idleMs / 2)
    }
  }

  async alarm() {
    const open = this.room.sweepIdle(e => {
      const auto = this.state.getWebSocketAutoResponseTimestamp(e.sock)
      return Math.max(e.meta.last ?? 0, auto ? auto.getTime() : 0)
    })
    if (open > 0) await this.state.storage.setAlarm(Date.now() + this.limits.idleMs / 2)
  }
}
