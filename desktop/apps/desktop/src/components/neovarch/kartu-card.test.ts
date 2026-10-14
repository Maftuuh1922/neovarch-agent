import { describe, expect, it, vi } from 'vitest'

import {
  cardColors,
  contrast,
  type DrawOp,
  layoutShareCard,
  NEOVARCH_LANDING_URL,
  paintShareCard,
  qrModules,
  renderShareCardPng,
  safeHandle,
  safeLabel,
  safeModelName,
  SHARE_CARD_SIZE,
  type ShareCardData,
  shareLinks,
  statsFromOffice
} from './kartu-card'
import type { OfficeSnapshot } from './office-store'

const office = {
  agents: [
    { id: 'a', message_count: 120, model: 'openrouter/anthropic/claude-sonnet-4.5', name: 'Raka', status: 'working' },
    { id: 'b', message_count: 80, model: '', name: 'Ayu', status: 'idle' }
  ],
  counts: { idle: 1, total: 2, 'waiting-approval': 0, working: 1 },
  feed: [],
  generated_at: 0,
  host: 'my-secret-pc.local',
  kanban: { done: 7 },
  seq: 1,
  vault: { configured: true, connected: true, note_count: 3, path: '/home/aku/vault' }
} as unknown as OfficeSnapshot

const data = (over: Partial<ShareCardData> = {}): ShareCardData => ({
  handle: 'Maftuuh1922',
  link: NEOVARCH_LANDING_URL,
  name: 'Maftuh',
  officeShot: 'data:image/jpeg;base64,AAAA',
  stats: statsFromOffice(office),
  ...over
})

const texts = (ops: DrawOp[]) => ops.flatMap(op => (op.kind === 'text' ? [op.text] : []))

describe('Kartu Neovarch (desktop)', () => {
  it('stats come from the Office snapshot without host, vault path or provider', () => {
    expect(statsFromOffice(office)).toEqual({ agentsActive: 1, agentsTotal: 2, messages: 200, model: 'claude-sonnet-4.5', tasksDone: 7 })
    expect(statsFromOffice(null, 'C:\\models\\x.gguf')).toEqual({ model: undefined })
  })

  it('scrubs secrets, paths and addresses', () => {
    expect(safeLabel('sk-or-v1-0123456789abcdef0123456789abcdef')).toBe('')
    expect(safeLabel('/home/aku/.neovarch')).toBe('')
    expect(safeLabel('http://192.168.1.4:9319')).toBe('')
    expect(safeLabel('  Maftuh   Dev ')).toBe('Maftuh Dev')
    expect(safeHandle('@Maftuuh1922')).toBe('Maftuuh1922')
    expect(safeHandle('../etc/passwd')).toBe('')
    expect(safeModelName('http://localhost:11434/qwen')).toBe('')
    expect(safeModelName('deepseek/deepseek-r1:free')).toBe('deepseek-r1')

    const ops = layoutShareCard(data({ handle: 'ghp_x/../', name: 'ghp_abcdefghijklmnopqrstuvwxyz0123' }), {
      accent: '#EE1C1C',
      format: 'story',
      showOffice: true,
      showStats: true,
      style: 'kaca'
    })

    const all = texts(ops).join(' ')
    expect(all).not.toMatch(/ghp_|my-secret-pc|\/home\/aku|Hermes/)
    expect(all).toContain('Kantor AI-ku')
  })

  for (const format of ['story', 'feed'] as const) {
    for (const style of ['kaca', 'gelap', 'warna'] as const) {
      it(`lays out ${style} ${format} inside the canvas with QR, stats, office and footer`, () => {
        const { h, w } = SHARE_CARD_SIZE[format]
        const ops = layoutShareCard(data(), { accent: '#EE1C1C', format, showOffice: true, showStats: true, style })
        const t = texts(ops)
        expect(t).toContain('Dibuat dengan Neovarch')
        expect(t).toContain('Maftuh')
        expect(t).toContain('@Maftuuh1922')
        expect(t).toContain('agen aktif')
        expect(t.some(x => x.startsWith('model · claude-sonnet-4.5'))).toBe(true)
        expect(ops.some(op => op.kind === 'qr')).toBe(true)
        expect(ops.some(op => op.kind === 'image')).toBe(true)

        for (const op of ops) {
          if (op.kind === 'rect' || op.kind === 'image') {
            expect(op.x).toBeGreaterThanOrEqual(0)
            expect(op.y).toBeGreaterThanOrEqual(0)
            expect(op.x + op.w).toBeLessThanOrEqual(w + 1)
            expect(op.y + op.h).toBeLessThanOrEqual(h + 1)
          }
        }

        // content above the QR block never runs into it
        const qr = ops.find(op => op.kind === 'qr')!
        const model = ops.find((op): op is Extract<DrawOp, { kind: 'text' }> => op.kind === 'text' && op.text.startsWith('model ·'))!
        expect(model.y).toBeLessThan(qr.y)
      })
    }
  }

  it('hides stats and the office snapshot on request', () => {
    const ops = layoutShareCard(data(), { accent: '#7C3AED', format: 'feed', showOffice: false, showStats: false, style: 'gelap' })
    const t = texts(ops)
    expect(t).not.toContain('agen aktif')
    expect(t.some(x => x.startsWith('model ·'))).toBe(false)
    expect(ops.some(op => op.kind === 'image')).toBe(false)
  })

  it('QR encodes the landing page', () => {
    const m = qrModules(NEOVARCH_LANDING_URL)
    expect(m.length).toBeGreaterThanOrEqual(25)
    expect(m.every(row => row.length === m.length)).toBe(true)
    // finder pattern corners
    expect(m[0][0] && m[0][6] && m[6][0]).toBe(true)
  })

  it('Warna-warni text keeps 4.5:1 on any accent', () => {
    for (const a of ['#EE1C1C', '#FACC15', '#84CC16', '#1E3A8A', '#FFFFFF', '#0D9488']) {
      const c = cardColors('warna', a)
      expect(contrast(c.ground, c.text)).toBeGreaterThan(4.5)
    }
  })

  it('share links carry the landing URL', () => {
    const links = shareLinks(NEOVARCH_LANDING_URL, 'Kantor AI-ku di Neovarch.')
    expect(links.map(l => l.label)).toEqual(['X', 'Facebook', 'WhatsApp'])

    for (const l of links) {
      expect(decodeURIComponent(l.url)).toContain(NEOVARCH_LANDING_URL)
    }
  })

  it('paints every op and exports a PNG of the format size', async () => {
    const calls: string[] = []

    const ctx = new Proxy(
      {},
      {
        get: (_t, prop: string) => (typeof prop === 'string' ? (...args: unknown[]) => calls.push(`${prop}:${args.length}`) : undefined),
        set: () => true
      }
    ) as unknown as CanvasRenderingContext2D

    const sizes: [number, number][] = []

    const fakeDoc = {
      createElement: () => {
        const canvas = {
          getContext: () => ctx,
          height: 0,
          toBlob: (cb: (b: Blob) => void) => {
            sizes.push([canvas.width, canvas.height])
            cb(new Blob(['png'], { type: 'image/png' }))
          },
          width: 0
        }

        return canvas
      }
    } as unknown as Document

    const load = vi.fn(async () => null)
    await paintShareCard(ctx, layoutShareCard(data(), { accent: '#EE1C1C', format: 'story', showOffice: true, showStats: true, style: 'kaca' }), load)
    expect(load).toHaveBeenCalledWith('data:image/jpeg;base64,AAAA')
    expect(calls.some(c => c.startsWith('fillText'))).toBe(true)
    expect(calls.some(c => c.startsWith('fillRect'))).toBe(true)

    const blob = await renderShareCardPng(data({ officeShot: null }), { accent: '#EE1C1C', format: 'feed', showOffice: true, showStats: true, style: 'warna' }, fakeDoc)
    expect(blob.type).toBe('image/png')
    expect(sizes).toEqual([[1080, 1080]])
  })
})
