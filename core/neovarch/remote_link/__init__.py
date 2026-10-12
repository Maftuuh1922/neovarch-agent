"""Remote dari mana saja: reach this PC from the phone without the same Wi-Fi.

Transports after the LAN and Tailscale: an end-to-end encrypted relay
(``relay/`` in the repo; free Cloudflare Worker or self-hosted Node) and
Bluetooth. See docs/relay.md.

v1.4.7: Tailscale is the primary remote path. The NeovarchLabs relay was never
deployed, so there is no built-in relay: it only runs when a relay URL is
configured (``NEOVARCH_RELAY_URL`` or ``POST /api/remote/link/config``).
"""

# No built-in relay. The desktop app carries the same value in
# electron/relay-defaults.ts (DEFAULT_RELAY_URL_BUILTIN; a test checks they match).
DEFAULT_RELAY_URL = ""

# Shipped as the default before v1.4.7 but never deployed (the host does not
# resolve). A setting that still carries it means "no relay configured".
UNDEPLOYED_RELAY_URLS = frozenset({"wss://relay.neovarchlabs.web.id"})


def usable_relay_url(url: str | None) -> str:
    """``url`` normalised, or ``""`` when empty, invalid or a known undeployed default."""
    from .relay_client import normalize_relay_url

    n = normalize_relay_url(url or "")
    return n if n and n not in UNDEPLOYED_RELAY_URLS else ""
