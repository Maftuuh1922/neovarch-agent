// Remote dari mana saja — the default relay every install uses unless the user
// points Settings → Remote at their own (docs/relay.md).
//
// This is the ONE place to change it before a release: set it to the URL the
// NeovarchLabs Cloudflare Worker was deployed to (wss://…). A build can also
// override it without a code change through NEOVARCH_DEFAULT_RELAY_URL.
// The core keeps the same value in core/neovarch/remote_link/__init__.py for
// headless `neovarch serve` (a test checks they match).
//
// Placeholder until the Worker is deployed once (relay/README.md).
export const DEFAULT_RELAY_URL_BUILTIN = 'wss://relay.neovarchlabs.web.id'

export const DEFAULT_RELAY_URL: string = (process.env.NEOVARCH_DEFAULT_RELAY_URL || DEFAULT_RELAY_URL_BUILTIN).trim()

/** https://x → wss://x, bare host → wss://host; null when unusable. Mirrors the core. */
export function normalizeRelayUrl(input: string | null | undefined): string | null {
  let u = String(input ?? '')
    .trim()
    .replace(/\/+$/, '')

  if (!u) {
    return null
  }

  if (u.startsWith('https://')) {
    u = `wss://${u.slice(8)}`
  } else if (u.startsWith('http://')) {
    u = `ws://${u.slice(7)}`
  } else if (!u.includes('://')) {
    u = `wss://${u}`
  }

  if (!/^wss?:\/\/[^/\s]+/.test(u) || u.length > 300) {
    return null
  }

  return u
}
