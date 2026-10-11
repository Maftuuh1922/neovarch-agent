# Neovarch relay

Stateless WebSocket forwarder for **Remote dari mana saja**: the PC and the phone both connect *outbound*,
the relay pairs them by room and forwards end-to-end-encrypted frames. It stores nothing but live sockets and
cannot read content. Protocol: [docs/remote-protocol.md §7](../docs/remote-protocol.md); user guide:
[docs/relay.md](../docs/relay.md).

```
src/room.js         shared room logic + limits (platform neutral)
src/worker.js       Cloudflare Worker + Durable Object (SQLite-backed, WebSocket hibernation)
src/node-server.js  standalone Node ≥ 20 server, zero npm dependencies (Dockerfile)
src/ws-node.js      minimal RFC 6455 server endpoint used by node-server.js
test/               node --test (routing, limits, room isolation, Worker glue)
```

## Test

```bash
cd relay && node --test test/*.test.js
```

## Deploy on Cloudflare (free plan)

```bash
cd relay
npx wrangler login      # free Cloudflare account
npx wrangler deploy     # prints https://neovarch-relay.<account>.workers.dev
```

Use `wss://neovarch-relay.<account>.workers.dev` as the Relay URL in Neovarch PC ▸ Settings ▸ Remote.

### Launching the default public relay (NeovarchLabs, one time)

1. Cloudflare account for NeovarchLabs (free plan is enough to start), `npx wrangler login`.
2. `npx wrangler deploy` from `relay/`.
3. Custom domain (optional, recommended): add the zone (e.g. `neovarchlabs.web.id`) to Cloudflare, then uncomment
   `routes = [{ pattern = "relay.neovarchlabs.web.id", custom_domain = true }]` in `wrangler.toml` and deploy again.
4. Make the URL the app default: set `DEFAULT_RELAY_URL_BUILTIN` in
   `desktop/apps/desktop/electron/relay-defaults.ts` **and** `DEFAULT_RELAY_URL` in
   `core/neovarch/remote_link/__init__.py` (a test keeps them equal), or override at build time with
   `NEOVARCH_DEFAULT_RELAY_URL`. Phones never need a rebuild: they read the relay URL from the QR / the PC.
5. Check: `curl https://relay.neovarchlabs.web.id/health` → `{"ok":true,"service":"neovarch-relay","protocol":1}`.

Free-plan quotas (requests/day, Durable Object duration) apply; watch the Workers dashboard as usage grows and move
to Workers Paid if needed — the code does not change.

## Self-host with Docker

```bash
docker build -t neovarch-relay relay/
docker run -d --restart unless-stopped -p 8787:8787 neovarch-relay
```

Terminate TLS in front of it (Caddy/nginx/Cloudflare Tunnel) so phones connect with `wss://`.
Env: `PORT`, `HOST`, `MAX_MESSAGE_BYTES` (262144), `MAX_PHONES_PER_ROOM` (5), `IDLE_SECONDS` (120), `MAX_ROOMS` (10000).
