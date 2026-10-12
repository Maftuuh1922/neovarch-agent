# Neovarch Remote — phone ↔ desktop protocol

**Product split:** the agent runs in the **Neovarch desktop app** (a fork of Hermes Desktop: Electron + React
driving the **Neovarch core** — the Python agent in `core/`, vendored from Hermes Agent and run as the
`neovarch` CLI with its own home `~/.neovarch`). The **phone app (Android/iOS, this Flutter project) is a
remote only**: no local agent runtime, no provider/API-key settings, no local tools. It talks to the gateway
the desktop already runs — the core's `tui_gateway` JSON-RPC API on `/api/ws` plus a few dashboard REST
routes (wire-compatible with a stock `hermes serve` / `hermes dashboard`).

**Port:** Neovarch's remote gateway listens on **9319** by default. 9119 is Hermes Agent's dashboard port;
Neovarch never binds it, so both can run on one PC. Desktops that were set to 9119 by v1.2.x move to 9319
on upgrade, and phones paired to `:9119` must scan the new QR once. If the port is taken by another
program the desktop reports it and does not start (it never stops or replaces the other process).

Code: `lib/remote/` (`pairing.dart`, `remote_gateway.dart`, `remote_transcript.dart`, `remote_controller.dart`,
`saved_desktops.dart`, `ui/`). Transport reuses `lib/data/gateway_client.dart`. Tests:
`test/remote_gateway_test.dart` (in-process mock gateway).

---

## 1. Pairing payload (what the desktop must show)

The desktop's **Remote / Perangkat** screen shows a QR and the same data as text. The phone accepts any of:

| Form | Example |
|---|---|
| **Pairing URI (preferred)** | `neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.5%3A9319&token=<token>&name=PC%20Kantor&profile=default` |
| JSON | `{"url":"http://192.168.1.5:9319","token":"<token>","name":"PC Kantor","profile":"default","headers":{"CF-Access-Client-Id":"…"}}` |
| Dashboard URL with token | `http://192.168.1.5:9319/?token=<token>` |
| WebSocket URL | `ws://192.168.1.5:9319/api/ws?token=<token>` |
| Manual | address `192.168.1.5:9319` (port defaults to **9319**, scheme to `http`) + token typed separately |

Fields: `url` = gateway HTTP origin (optionally with a base path behind a reverse proxy; `ws(s)` and a trailing
`/api/ws` are normalized away), `token` = gateway auth token, `name` = label, `profile` = Hermes profile to pass
on every RPC (optional), `headers` = extra headers for access proxies (optional, JSON form only).

The phone stores `url/name/profile/headers` in shared_preferences and the **token in
flutter_secure_storage** (`remote.token.<desktopId>`). "Lupakan" deletes both.

### What the desktop does (Neovarch Desktop, `desktop/apps/desktop/electron/neovarch-remote.ts`)
Settings ▸ **Remote / Perangkat** ("Aktifkan akses remote"):
1. The desktop's own backend stays on `127.0.0.1` (loopback peers only). The Hermes core refuses any
   non-loopback bind without a dashboard auth provider (`--insecure` is a no-op since the June 2026
   hardening), so the desktop spawns a **second** process
   `neovarch serve --host 0.0.0.0 --port 9319 --isolated` with the core's bundled password provider
   enabled through env: `HERMES_DASHBOARD_BASIC_AUTH_USERNAME=neovarch-remote`, a random never-shown
   `…_PASSWORD`, and `…_SECRET=<base64 32-byte secret>` stored in the desktop's userData
   (`neovarch-remote.json`, mode 0600).
2. The phone token is minted by the desktop in the exact format of the provider's `verify_session`:
   `urlsafe_b64encode(json.dumps({"sub":"neovarch-remote","kind":"access","exp":…}, separators=(",",":")) + HMAC_SHA256(secret, json))`
   (padding kept, signature appended without separator). It is accepted as `Authorization: Bearer` on REST
   and as `?token=` on `/api/ws` (gated mode). `X-Hermes-Session-Token` is ignored in gated mode (harmless).
3. The screen shows the QR (`neovarch://pair?v=1&url=http://<LAN-IP>:9319&token=…&name=<PC>&profile=<profile>`),
   address + token with copy buttons, a LAN-IP picker when the PC has several addresses, a connection check
   (`GET /api/plugins/kanban/board` with the phone token via the LAN address) and **Buat token baru**
   (new secret → gateway restart → every paired phone must re-scan). The process stops on quit and
   auto-starts on launch when left enabled.
   **Since 1.4.6 the QR carries a one-time pair token instead** (`{"kind":"pair","iat","exp","jti"}`, same
   signature, valid 10 minutes) whenever the gateway reports `pair_epoch` on `/api/remote/link`. A pair token
   opens only `POST /api/remote/devices` (`{pk, name, session:true}`), which answers with this phone's own
   `session_token` (`nvd_…`; the core stores only its SHA-256). Every successful pairing (pair token or relay
   pairing code) moves `pair_epoch` past the token's `iat`, so the same QR cannot pair a second phone; the
   desktop then shows a fresh QR. Pairing again rotates the device token (the old one stops working). Phones
   still holding the old long-lived access token trade it for a session token on their next LAN connect.
   Paired devices carry `created_at`/`last_seen` (updated on every authenticated request and relay/Bluetooth
   frame, throttled to once a minute); one not seen for `remote.pairing_idle_days` days (config.yaml, default
   30, `0` = never) is unpaired: its token gets `401 {"code":"session_expired","detail":"Sesi kedaluwarsa,
   pasangkan ulang"}` and its relay auth `{"t":"denied","reason":"expired"}`. Desktop Settings ▸ Remote lists
   each device with "Terakhir aktif" and its expiry, and **Cabut** revokes it at once.
4. Kanban is a bundled plugin and answers by default; status changes follow the board's own rules
   (e.g. `running` only via the dispatcher, some transitions answer 400/409 — the phone shows the error).

---

## 2. Transport & auth

* WebSocket: `ws(s)://<host>:<port>/api/ws?token=<token>` (native builds also send
  `Authorization: Bearer <token>` + any extra headers). JSON-RPC 2.0, one JSON object per frame.
* REST: same origin, headers `X-Hermes-Session-Token: <token>` **and** `Authorization: Bearer <token>`.
* First frame from the server: event `gateway.ready`.
* Right after connecting the phone calls **`client.capabilities {server_requests: true}`** —
  without it the gateway never sends approval requests to this connection (it fails them fast instead).
* Heartbeat: `ping` every 15 s; a missed pong closes the socket and starts reconnect.
* Reconnect: backoff 1 → 2 → 4 → 8 → 15 → 30 s; on reconnect the open chat is re-attached with
  `session.resume` (which also returns still-open server requests, i.e. approvals that were waiting).
* Frames: request `{jsonrpc, id, method, params}` → `{id, result}` | `{id, error:{code,message}}`;
  notification `{method:"event", params:{type, session_id, payload}}`; server→client request
  `{id:"srq-…", method, params}` answered with `{id, result}` (non-approval requests are declined `-32601`).

## 3. Methods the phone uses

| Purpose | Call |
|---|---|
| list chats | `session.list {limit, profile?}` → `{sessions:[{id,title,preview,message_count,last_active}]}` |
| what's running | `session.active_list {profile?}` → `{sessions:[{id,title,status,model,preview,…}]}` |
| open / re-attach | `session.resume {session_id:<stored id or exact title>, source:"mobile"}` → runtime `session_id`, `stored_session_id`, `messages[]`, `info{title,running}`, `open_requests[]`, `pending_approval` |
| new chat | `session.create {source:"mobile", profile?}` → `{session_id, stored_session_id, messages}` |
| send a command | `prompt.submit {session_id:<runtime id>, text, surface:"mobile"}` |
| stop | `session.interrupt {session_id}` |
| approvals (fallback) | `approval.pending {session_id}`; `approval.respond {session_id, request_id, choice}` (300 s timeout) |
| liveness | `ping` → `{pong:true}` |
| desktop status | `GET /api/status` (public) |
| Kanban | `GET /api/plugins/kanban/board`; `PATCH /api/plugins/kanban/tasks/{id} {status}`; `POST /api/plugins/kanban/tasks {title, body?, assignee?, priority?}`; `POST /api/plugins/kanban/tasks/{id}/comments {body}` |

## 4. Streamed agent events (session-scoped)

`message.start` · `message.delta {text}` · `reasoning.delta` / `thinking.delta {text}` ·
`tool.start {tool_id, name, args_text|preview|args}` · `tool.complete {tool_id, name, summary, result_text, duration_s}` ·
`session.title {title}` · `message.complete {text, usage{avg_tps, context_percent}, error?}` · `error {message}` ·
`sessions.changed` (reload list). They are folded into chat rows by `RemoteTranscript` (thinking block, live
tool rows, markdown answer) — the same widgets the desktop-style chat uses.

## 5. Approvals

* Arrive as server→client request **`approval`**: `{id:"srq-…", params:{session_id, request_id, command,
  description, choices:["once","session","always","deny"], tool_name}}`.
* The phone shows them in the **Setujui** tab (badge), inline in the chat of that session, and as an Android
  notification (via the app's `neovarch/device` channel; iOS: in-app only for now).
* Answer: JSON-RPC result `{choice}` on the same id (exactly what Hermes Desktop does). If the approval came
  from `approval.pending`/`pending_approval` (no request id), the phone calls `approval.respond` instead.
* Withdrawn by `request.cancel {id}` or `approval.cancelled {request_ids}` (answered elsewhere, timeout,
  interrupt) — the card disappears.
* Visibility: the gateway sends a session's approvals to connections attached to that session. The phone
  attaches to the chat it has open (and re-attaches on reconnect); approvals of other desktop sessions show up
  once that session is opened on the phone (`session.resume` returns them). A desktop-side broadcast of all
  pending approvals to paired phones would be a desktop-fork feature.

## 6. Security notes

* Token = full control of the agent on the PC (tools, terminal, files). It travels in the URL/headers; on a
  plain-`http` LAN it is visible to anyone sniffing that network. Outside the LAN the phone uses the end-to-end
  encrypted relay (section 7); `https`/`wss` URLs are also supported as-is.
* Revocation: per device for the relay/Bluetooth (Settings ▸ Remote ▸ Paired devices ▸ Cabut); rotating the
  desktop's token ("Buat token baru") still cuts every phone's LAN access at once.

---

## 7. Remote dari mana saja (relay + Bluetooth)

User guide, privacy and self-hosting: [relay.md](relay.md). Code: `relay/` (server), `core/neovarch/remote_link/`
(PC side), `lib/remote/link/` (phone side). Tests: `relay/test/`, `core/tests/test_remote_link.py`,
`test/remote_link_crypto_test.dart`, `test/remote_link_fallback_test.dart`; shared vectors in
`test/fixtures/link_vectors.json`.

### 7.1 Connection order on the phone

1. Every direct address from the pairing (`url` + `alt`, refreshed from `network.addresses`), **Tailscale first**
   (v1.4.7): tailnet IPs (100.64.0.0/10), then the MagicDNS name (`*.ts.net`), then LAN, then anything else. When
   the phone knows its VPN is off (Android `tailscaleStatus`), the LAN goes first instead. A DNS failure, refused
   port or timeout on one address moves to the next one silently.
2. **Bluetooth** — if the PC advertised a Bluetooth target and the phone setting is on.
3. **Relay** — only if the PC is known (`pc`/`pk`) and a relay URL is actually configured. There is no built-in
   relay since v1.4.7; the never-deployed `wss://relay.neovarchlabs.web.id` is ignored wherever it still appears.

The PC's QR puts the Tailscale IP as `url` when Tailscale is up, then MagicDNS and LAN addresses as `alt`.

Every REST call (model switch, Kanban, vault, uploads…) goes through the same connection manager
(`RemoteGateway._send`): over the live transport, and when a direct address stops answering mid-session it
reconnects over the next route and retries once. Users never see raw socket errors; a total failure reads
"PC tidak terjangkau. Pastikan PC menyala dan Tailscale aktif di HP dan PC…" with a **Coba lagi** action and, when
Tailscale is not ready on the phone, the **Siapkan Tailscale** steps. While on relay/Bluetooth the phone probes the
direct addresses every 45 s and switches back as soon as one answers.

### 7.2 Pairing payload additions (backward compatible)

`neovarch://pair?v=1&url=…&alt=…&token=…&name=…` **plus**

| Param | Meaning |
|---|---|
| `pc` | relay room id: `base64url(sha256(room_key))[:22]` |
| `pk` | PC X25519 public key (base64url, 32 bytes) — pinned by the phone |
| `relay` | relay URL (`wss://…`), prefilled from the build default, never typed by the user |
| `pair` | pairing code (valid 30 min, refreshed every 10 min) for enrolling over relay/Bluetooth |
| `bt`, `btch` | PC Bluetooth address and RFCOMM channel (only when Bluetooth is on) |

Old QRs (no `pc`/`pk`) still pair over the LAN; the phone then enrolls its device key on the first LAN connect.
The desktop puts the LAN IPs in `url`/first `alt`s and MagicDNS/tailnet addresses last.

### 7.3 REST on the remote gateway (token required)

| Route | Body / answer |
|---|---|
| `GET /api/remote/link` | `{protocol, pc_id, pc_pk, name, relay:{enabled,url,default_url,state,error,phones}, bluetooth:{enabled,state,error,address,channel,uuid,phones}, devices:[{id,name,added,last_seen,via}], pair_code, pair_expires}` |
| `POST /api/remote/link/config` | `{relay_enabled?, relay_url?, bluetooth_enabled?}` → same as GET |
| `POST /api/remote/devices` | `{pk, name}` (phone's device key, over the LAN) → `{device, pc_id, pc_pk, name, protocol, relay_url, bluetooth}` |
| `DELETE /api/remote/devices/{id}` | revoke; live relay/Bluetooth links of that device are dropped |

The desktop passes `NEOVARCH_RELAY`, `NEOVARCH_RELAY_URL`, `NEOVARCH_BT`, `NEOVARCH_REMOTE_NAME` when it starts the
remote gateway; the gateway keeps **one outbound WebSocket** to the relay, reconnecting with backoff (1 s → 60 s,
jittered), which survives sleep and network changes.

### 7.4 Relay wire protocol

```
PC     → wss://<relay>/v1/pc/<pc_id>?k=<room_key>      (relay checks sha256(k) prefix == pc_id)
phone  → wss://<relay>/v1/phone/<pc_id>
relay → PC     {"type":"join"|"leave","cid"} · {"type":"msg","cid","data"} · "pong"
PC → relay     {"type":"msg","cid","data"} · {"type":"close","cid"} · "ping"
relay → phone  <data> · {"relay":"pc_online"|"pc_offline"} · "pong"
phone → relay  <data> · "ping"
```

Limits: 256 KiB/message, 5 phones/room, 120 s idle, per-connection token-bucket rate limit. Close codes: 1009 too
big, 4000 replaced, 4001 closed by PC, 4008 room full, 4029 rate limited, 4040 idle.

### 7.5 Encrypted link (relay and Bluetooth)

```
phone → PC  {"t":"hello","v":1,"dev":<pk_dev>,"eph":<e_phone>}
PC → phone  {"t":"welcome","v":1,"pc":<pk_pc>,"eph":<e_pc>}
th   = SHA256("neovarch-link/1" | pk_dev | pk_pc | e_phone | e_pc)
keys = HKDF-SHA256(X25519(dev,pc) | X25519(e_phone,e_pc), salt=th, info="neovarch-link/1 keys", 64)
k_up = keys[0:32] (phone→PC), k_down = keys[32:64]
frame = {"t":"d","c":b64url(ChaCha20-Poly1305(k, nonce=0^4|ctr_be64, aad=th, flag|json_chunk))}
```

Counters are implicit (ordered transports): replay, reorder or loss fails authentication and closes the link.
Messages > 48 KiB are split (flag 1 = more parts). Inner messages:

| Direction | Message |
|---|---|
| phone → PC | `{"t":"auth"}` (known device) · `{"t":"pair","code","name"}` (new device, code from the QR) |
| PC → phone | `{"t":"ready","device","name"}` · `{"t":"denied","reason":"unknown_device"/"revoked"/"bad_code"}` |
| phone → PC | `{"t":"ws.open"}` → `{"t":"ws.opened"}`; both ways `{"t":"ws","d":<JSON-RPC frame>}`; `{"t":"ws.closed"}` |
| phone → PC | `{"t":"http","id","m","p":"/api/…?q","h":{…},"b":<base64>}` → `{"t":"http.res","id","s","h","b"}` |

The PC replays `ws`/`http` against its own gateway on loopback with a per-process internal token (the phone's
`Authorization` header is dropped), so every route, event and approval behaves exactly as on the LAN — including
attachments: uploads are the same multipart `POST /api/uploads` body inside the tunnel (≤ 15 MB over the relay),
downloads are `GET` paths (`RemoteGateway.fetchBytes`). REST and attachment shapes stay transport-agnostic: anything
documented in sections 1–5 works over the relay unchanged.
