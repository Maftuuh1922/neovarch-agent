/**
 * Files the agent sent into the chat with its `send_file` tool.
 *
 * The core stores them on the assistant row as `attachments` (same schema as
 * the phone's uploads: `{id, name, mime, size, kind, url, path, origin}`) and
 * repeats them in `message.complete.attachments`. The desktop runs on the same
 * PC, so it shows them through the existing `MEDIA:` path rendering (inline
 * image / file chip) using the stored copy's local `path`; the phone fetches
 * the same files from `GET /api/uploads/<id>`.
 */

interface AgentAttachmentLike {
  path?: unknown
}

export function agentAttachmentPaths(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const out: string[] = []

  for (const item of raw) {
    const path = item && typeof item === 'object' ? (item as AgentAttachmentLike).path : undefined

    if (typeof path === 'string' && path.trim() && !path.includes('\n') && !path.includes('"')) {
      out.push(path.trim())
    }
  }

  return out
}

/** `text` plus one quoted `MEDIA:"<path>"` line per sent file not already named in it. */
export function withAgentAttachments(text: string, raw: unknown): string {
  const media = agentAttachmentPaths(raw)
    .filter(path => !text.includes(`MEDIA:"${path}"`))
    .map(path => `MEDIA:"${path}"`)

  if (!media.length) {
    return text
  }

  return text.trim() ? `${text}\n\n${media.join('\n')}` : media.join('\n')
}
