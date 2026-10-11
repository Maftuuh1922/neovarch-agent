"""Remote dari mana saja: reach this PC from the phone without the same Wi-Fi.

Transports after the LAN: an end-to-end encrypted relay (``relay/`` in the
repo; free Cloudflare Worker or self-hosted Node) and Bluetooth. See
docs/relay.md.
"""

# The public relay run by NeovarchLabs. Single source for the core; the desktop
# app carries the same value in electron/relay-defaults.ts and passes it via
# NEOVARCH_RELAY_URL. Placeholder until the Worker is deployed once.
DEFAULT_RELAY_URL = "wss://relay.neovarchlabs.web.id"
