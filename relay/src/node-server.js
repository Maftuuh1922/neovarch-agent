// Standalone Neovarch relay for a VPS or home server (Node ≥ 20, no npm deps).
//
//   node src/node-server.js            # listens on $PORT (default 8787)
//
// Put it behind a TLS reverse proxy (Caddy, nginx, Cloudflare Tunnel) so phones
// connect with wss://. Same protocol and limits as the Cloudflare Worker.
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import { DEFAULT_LIMITS, HEALTH, RelayRoom, parseRelayPath, verifyRoomKey } from './room.js'
import { upgrade } from './ws-node.js'

function envLimits(env = process.env) {
  const n = (k, d) => {
    const v = Number(env[k])
    return Number.isFinite(v) && v > 0 ? v : d
  }
  return {
    ...DEFAULT_LIMITS,
    maxMessageBytes: n('MAX_MESSAGE_BYTES', DEFAULT_LIMITS.maxMessageBytes),
    maxPhonesPerRoom: n('MAX_PHONES_PER_ROOM', DEFAULT_LIMITS.maxPhonesPerRoom),
    idleMs: n('IDLE_SECONDS', DEFAULT_LIMITS.idleMs / 1000) * 1000
  }
}

/** Create (not start) a relay server. `opts.limits` overrides; `opts.maxRooms` caps rooms per process. */
export function createRelayServer(opts = {}) {
  const limits = { ...envLimits(), ...(opts.limits ?? {}) }
  const maxRooms = opts.maxRooms ?? Number(process.env.MAX_ROOMS ?? 10000)
  const now = opts.now ?? (() => Date.now())
  /** pcId → { room, sockets: Map<sock, meta> } */
  const rooms = new Map()

  function roomFor(pcId, create) {
    let r = rooms.get(pcId)
    if (!r && create) {
      if (rooms.size >= maxRooms) return null
      const sockets = new Map()
      r = {
        sockets,
        room: new RelayRoom(
          {
            list: () => [...sockets].map(([sock, meta]) => ({ sock, meta })),
            attach: (sock, meta) => sockets.set(sock, meta),
            save: () => {},
            detach: sock => sockets.delete(sock)
          },
          limits,
          now
        )
      }
      rooms.set(pcId, r)
    }
    return r ?? null
  }

  function gc(pcId) {
    const r = rooms.get(pcId)
    if (r && r.sockets.size === 0) rooms.delete(pcId)
  }

  const server = http.createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://relay')
    if (pathname === '/' || pathname === '/health') {
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' })
      res.end(JSON.stringify({ ...HEALTH, rooms: rooms.size }))
      return
    }
    res.writeHead(parseRelayPath(pathname) ? 426 : 404, { 'content-type': 'text/plain' })
    res.end(parseRelayPath(pathname) ? 'expected websocket' : 'not found')
  })

  server.on('upgrade', async (req, socket, head) => {
    socket.on('error', () => {})
    const url = new URL(req.url, 'http://relay')
    const route = parseRelayPath(url.pathname)
    const reject = (status, text) => socket.end(`HTTP/1.1 ${status} ${text}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`)
    if (!route) return reject(404, 'Not Found')
    if (route.role === 'pc' && !(await verifyRoomKey(route.pcId, url.searchParams.get('k') ?? ''))) {
      return reject(403, 'Forbidden')
    }
    const r = roomFor(route.pcId, true)
    if (!r) return reject(503, 'Service Unavailable')
    const ws = upgrade(req, socket, null, { maxPayload: limits.maxMessageBytes + 1024 })
    if (!ws) return gc(route.pcId)
    const meta = route.role === 'pc' ? r.room.joinPc(ws) : r.room.joinPhone(ws)
    if (!meta) return gc(route.pcId)
    ws.on('message', data => r.room.message(ws, meta, data))
    ws.on('close', () => {
      r.room.leave(ws, meta)
      gc(route.pcId)
    })
    if (head?.length) ws._onData(head)
  })

  const sweep = setInterval(() => {
    for (const [pcId, r] of rooms) {
      r.room.sweepIdle()
      gc(pcId)
    }
  }, Math.max(1000, Math.floor(limits.idleMs / 4)))
  sweep.unref?.()
  server.on('close', () => clearInterval(sweep))

  return { server, rooms, limits }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const port = Number(process.env.PORT ?? 8787)
  const host = process.env.HOST ?? '0.0.0.0'
  const { server } = createRelayServer()
  server.listen(port, host, () => {
    console.log(`neovarch-relay listening on ${host}:${port}`)
  })
  const stop = () => server.close(() => process.exit(0))
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
}
