import { describe, expect, it } from 'vitest'

import { agentAttachmentPaths, withAgentAttachments } from './agent-attachments'
import { toChatMessages } from './hydration'
import { renderMediaTags } from './parts'

const shot = {
  id: 'aa11bb22cc33',
  kind: 'image',
  mime: 'image/png',
  name: 'screenshot.png',
  origin: 'agent',
  path: '/home/me/.neovarch/uploads/s1/aa11bb22cc33-screenshot.png',
  size: 10,
  url: '/api/uploads/aa11bb22cc33'
}

describe('agent attachments (send_file)', () => {
  it('turns stored attachments into quoted MEDIA lines', () => {
    expect(agentAttachmentPaths([shot, { path: 'bad"quote' }, null, 3])).toEqual([shot.path])
    expect(withAgentAttachments('Ini screenshot-nya.', [shot])).toBe(`Ini screenshot-nya.\n\nMEDIA:"${shot.path}"`)
    expect(withAgentAttachments('', [shot])).toBe(`MEDIA:"${shot.path}"`)
    expect(withAgentAttachments('teks', undefined)).toBe('teks')
  })

  it('does not repeat a file already named', () => {
    const once = withAgentAttachments('a', [shot])

    expect(withAgentAttachments(once, [shot])).toBe(once)
  })

  it('renders as a media link', () => {
    expect(renderMediaTags(withAgentAttachments('x', [shot]))).toContain('screenshot.png')
  })

  it('history: an assistant row with attachments shows them', () => {
    const messages = toChatMessages([
      { content: 'kirim ke sini', role: 'user', row_id: 1, timestamp: 1 },
      { attachments: [shot], content: 'Ini dia', role: 'assistant', row_id: 2, timestamp: 2 }
    ] as never)

    const assistant = messages.find(m => m.role === 'assistant')
    const text = assistant?.parts.map(p => ('text' in p ? String(p.text) : '')).join('\n') ?? ''

    expect(text).toContain(`MEDIA:"${shot.path}"`)
  })
})
