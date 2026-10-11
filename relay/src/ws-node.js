// Minimal RFC 6455 WebSocket server endpoint for Node (no dependencies).
// Text and binary frames, fragmentation, ping/pong, close. Enough for the relay;
// permessage-deflate is not negotiated.
import { createHash } from 'node:crypto'
import { EventEmitter } from 'node:events'

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

export function acceptKey(key) {
  return createHash('sha1').update(key + GUID).digest('base64')
}

/** Complete the HTTP upgrade on `socket`; returns a NodeWebSocket or null (already answered 400). */
export function upgrade(req, socket, head, { maxPayload = 1024 * 1024 } = {}) {
  const key = req.headers['sec-websocket-key']
  if (!key || req.headers['sec-websocket-version'] !== '13') {
    socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n')
    return null
  }
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${acceptKey(key)}\r\n\r\n`
  )
  const ws = new NodeWebSocket(socket, maxPayload)
  if (head && head.length) ws._onData(head)
  return ws
}

export class NodeWebSocket extends EventEmitter {
  constructor(socket, maxPayload) {
    super()
    this.socket = socket
    this.maxPayload = maxPayload
    this.buf = Buffer.alloc(0)
    this.frag = null // { opcode, parts: [] }
    this.closed = false
    socket.setNoDelay?.(true)
    socket.on('data', d => this._onData(d))
    socket.on('close', () => this._finish(1006, ''))
    socket.on('error', () => this._finish(1006, ''))
  }

  _onData(chunk) {
    this.buf = this.buf.length ? Buffer.concat([this.buf, chunk]) : chunk
    while (!this.closed) {
      const f = this._parse()
      if (!f) break
      this._frame(f)
    }
  }

  _parse() {
    const b = this.buf
    if (b.length < 2) return null
    const fin = (b[0] & 0x80) !== 0
    const opcode = b[0] & 0x0f
    const masked = (b[1] & 0x80) !== 0
    let len = b[1] & 0x7f
    let off = 2
    if (len === 126) {
      if (b.length < 4) return null
      len = b.readUInt16BE(2)
      off = 4
    } else if (len === 127) {
      if (b.length < 10) return null
      const big = b.readBigUInt64BE(2)
      if (big > BigInt(this.maxPayload)) {
        this.close(1009, 'too_big')
        return null
      }
      len = Number(big)
      off = 10
    }
    if (len > this.maxPayload) {
      this.close(1009, 'too_big')
      return null
    }
    if (!masked) {
      // clients must mask (RFC 6455 §5.1)
      this.close(1002, 'unmasked')
      return null
    }
    if (b.length < off + 4 + len) return null
    const mask = b.subarray(off, off + 4)
    const payload = Buffer.from(b.subarray(off + 4, off + 4 + len))
    for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3]
    this.buf = b.subarray(off + 4 + len)
    return { fin, opcode, payload }
  }

  _frame({ fin, opcode, payload }) {
    if (opcode === 0x8) {
      const code = payload.length >= 2 ? payload.readUInt16BE(0) : 1005
      this.close(code === 1005 ? 1000 : code, '')
      return
    }
    if (opcode === 0x9) {
      this._send(0xa, payload)
      return
    }
    if (opcode === 0xa) return
    if (opcode === 0x1 || opcode === 0x2) {
      if (fin) {
        this._deliver(opcode, payload)
      } else {
        this.frag = { opcode, parts: [payload], size: payload.length }
      }
      return
    }
    if (opcode === 0x0 && this.frag) {
      this.frag.parts.push(payload)
      this.frag.size += payload.length
      if (this.frag.size > this.maxPayload) {
        this.close(1009, 'too_big')
        return
      }
      if (fin) {
        const { opcode: op, parts } = this.frag
        this.frag = null
        this._deliver(op, Buffer.concat(parts))
      }
      return
    }
    this.close(1002, 'protocol')
  }

  _deliver(opcode, payload) {
    this.emit('message', opcode === 0x1 ? payload.toString('utf8') : payload)
  }

  _send(opcode, payload) {
    if (this.closed || this.socket.destroyed) return
    const len = payload.length
    let header
    if (len < 126) {
      header = Buffer.from([0x80 | opcode, len])
    } else if (len < 65536) {
      header = Buffer.alloc(4)
      header[0] = 0x80 | opcode
      header[1] = 126
      header.writeUInt16BE(len, 2)
    } else {
      header = Buffer.alloc(10)
      header[0] = 0x80 | opcode
      header[1] = 127
      header.writeBigUInt64BE(BigInt(len), 2)
    }
    this.socket.write(Buffer.concat([header, payload]))
  }

  send(text) {
    if (this.closed) throw new Error('closed')
    this._send(0x1, Buffer.from(String(text), 'utf8'))
  }

  close(code = 1000, reason = '') {
    if (this.closed) return
    const r = Buffer.from(String(reason).slice(0, 120), 'utf8')
    const p = Buffer.alloc(2 + r.length)
    p.writeUInt16BE(code, 0)
    r.copy(p, 2)
    this._send(0x8, p)
    this.socket.end()
    this._finish(code, reason)
  }

  _finish(code, reason) {
    if (this.closed) return
    this.closed = true
    this.emit('close', code, reason)
  }
}
