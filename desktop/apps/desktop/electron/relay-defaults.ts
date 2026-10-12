// Remote dari mana saja — the optional relay (docs/relay.md).
//
// v1.4.7: Tailscale is the primary way to reach this PC from anywhere. The
// NeovarchLabs Cloudflare Worker relay was never deployed (its host does not
// resolve), so there is NO built-in default any more: the relay only runs when
// a relay URL is actually configured — by a self-hoster in Settings → Remote,
// or by a build through NEOVARCH_DEFAULT_RELAY_URL. The relay code and setting
// stay for self-hosters.
// The core keeps the same default in core/neovarch/remote_link/__init__.py for
// headless `neovarch serve` (a test checks they match).
export const DEFAULT_RELAY_URL_BUILTIN = ''

/**
 * Relay URLs that were shipped as defaults but never deployed. A setting or a
 * saved QR that still carries one is treated as "no relay configured", so the
 * phone and the PC never try (and never show an error for) a dead host.
 */
export const UNDEPLOYED_RELAY_URLS: readonly string[] = ['wss://relay.neovarchlabs.web.id']

export const DEFAULT_RELAY_URL: string = normalizeRelayUrl(process.env.NEOVARCH_DEFAULT_RELAY_URL || DEFAULT_RELAY_URL_BUILTIN) ?? ''

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

/** True for a usable relay URL (normalised, and not a known undeployed default). */
export function isUsableRelayUrl(url: string | null | undefined): boolean {
  const n = normalizeRelayUrl(url)

  return Boolean(n && !UNDEPLOYED_RELAY_URLS.includes(n))
}

/** The relay to use: the user's own URL, else the build default; null = relay not configured. */
export function effectiveRelayUrl(userUrl: string | null | undefined): string | null {
  const own = normalizeRelayUrl(userUrl)

  if (own && isUsableRelayUrl(own)) {
    return own
  }

  return isUsableRelayUrl(DEFAULT_RELAY_URL) ? DEFAULT_RELAY_URL : null
}
