// Neovarch Remote: lets the Neovarch phone app (Flutter, remote-only) drive this
// desktop over the LAN.
//
// The desktop's own backend binds 127.0.0.1 and only accepts loopback peers, and
// the Hermes core refuses a non-loopback bind unless a dashboard auth provider is
// registered (`--insecure` is a no-op since the June 2026 hardening). So when the
// user enables remote access we spawn a SECOND, dedicated
//   neovarch serve --host 0.0.0.0 --port 9319 --isolated
// (9319, not Hermes' 9119: a co-installed Hermes dashboard/gateway keeps its
// port. If the port is already taken we report it and never touch the owner.)
// with the core's bundled username/password provider (plugins/dashboard_auth/basic)
// configured through HERMES_DASHBOARD_BASIC_AUTH_* env vars. We own its signing
// secret, so we mint the phone's access token ourselves in the exact format the
// provider's `verify_session` accepts:
//   base64url(json({sub, kind:"access", exp}) + HMAC-SHA256(secret, json))
// (urlsafe base64 WITH padding, compact JSON, signature appended without separator).
// The gated middleware accepts it as `Authorization: Bearer` on REST and as
// `?token=` on /api/ws. Rotating the secret ("Buat token baru") invalidates every
// paired phone.

import { type ChildProcess, execFile, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

import { DEFAULT_RELAY_URL, normalizeRelayUrl } from './relay-defaults'
import { ensureFirewallRule, firewallHelp } from './windows-firewall'

export const REMOTE_DEFAULT_PORT = 9319
/** core/neovarch/background.py RESTART_EXIT_CODE: the gateway asks to be started again. */
export const GATEWAY_RESTART_EXIT_CODE = 75
/** Hermes Agent's dashboard/gateway default; Neovarch must never take it. */
export const HERMES_DEFAULT_PORT = 9119
const TOKEN_SUBJECT = 'neovarch-remote'
const TOKEN_TTL_SECONDS = 5 * 365 * 24 * 60 * 60

export interface RemoteSettings {
  enabled: boolean
  port: number
  secret: string // base64, >= 32 bytes
  issuedAt: number // unix seconds; token exp = issuedAt + TTL (stable QR between renders)
  preferredAddress: string | null
  deviceName: string
  /** Remote dari mana saja: the PC also keeps an outbound connection to the relay. */
  relayEnabled: boolean
  /** null = DEFAULT_RELAY_URL (relay-defaults.ts) */
  relayUrl: string | null
  /** Bluetooth transport (off by default). */
  bluetoothEnabled: boolean
}

/** A phone allowed to use the relay / Bluetooth (core /api/remote/link). */
export interface RemoteLinkDevice {
  id: string
  name: string | null
  added: number | null
  last_seen: number | null
  via: string | null
}

export interface RemoteTransportStatus {
  enabled: boolean
  state: 'off' | 'connecting' | 'online' | 'offline' | 'unavailable' | string
  error: string | null
  phones: number
}

/** What the remote gateway reports on GET /api/remote/link. */
export interface RemoteLinkInfo {
  pc_id: string
  pc_pk: string
  name?: string
  relay: RemoteTransportStatus & { url: string; default_url?: string }
  bluetooth: RemoteTransportStatus & { address: string | null; channel: number | null; uuid?: string | null }
  devices: RemoteLinkDevice[]
  pair_code: string
  pair_expires: number
}

export interface RemoteAddress {
  address: string
  iface: string
  /** lan: private LAN IPv4; tailscale: tailnet IPv4 (100.64.0.0/10); magicdns: Tailscale MagicDNS name */
  kind?: 'lan' | 'magicdns' | 'tailscale'
}

export interface TailscaleInfo {
  dnsName: string | null
  ips: string[]
}

export interface RemoteStatus {
  enabled: boolean
  running: boolean
  starting: boolean
  port: number
  addresses: RemoteAddress[]
  address: string | null
  url: string | null
  token: string | null
  pairingUri: string | null
  /** fallback origins the phone tries after `url`, in order (other LAN, MagicDNS, tailnet IP) */
  altUrls: string[]
  tailscale: TailscaleInfo | null
  deviceName: string
  profile: string | null
  error: string | null
  logTail: string
  /** Remote dari mana saja (relay) */
  relay: { enabled: boolean; url: string; defaultUrl: string; state: string; error: string | null; phones: number }
  bluetooth: { enabled: boolean; state: string; error: string | null; address: string | null; phones: number }
  devices: RemoteLinkDevice[]
}

export interface RemoteSpawnSpec {
  command: string
  args: string[]
  env: NodeJS.ProcessEnv
  cwd?: string
  shell?: boolean | string
}

export interface RemoteControllerDeps {
  settingsPath: string
  /** Build the spawn spec for the given hermes argv (after `hermes`). */
  resolveSpawn: (args: string[]) => Promise<RemoteSpawnSpec>
  currentProfile: () => string | null
  log: (line: string) => void
  onChanged?: (status: RemoteStatus) => void
  /** Where the running LAN gateway's PID is recorded (default: next to settings). */
  pidFilePath?: string
  /** Test seams for stale-gateway recovery. */
  processCommandLine?: (pid: number) => string | null
  killProcessGroup?: (pid: number, signal: NodeJS.Signals) => void
  portInUse?: (port: number) => Promise<boolean>
  /** Every running process as pid + command line (orphan gateways without a PID file). */
  listProcesses?: () => Promise<ProcessRow[]>
  /** Test seam for the gateway's /api/remote/* calls. */
  fetch?: typeof fetch
  /**
   * "Jalankan di latar belakang": the gateway is started detached with its
   * output in a log file (not a pipe into Electron), a gateway left running by
   * an earlier session is adopted instead of reaped, and quit may detach.
   */
  backgroundMode?: () => boolean
  /** Background gateway output (default: neovarch-remote-gateway.log next to settings). */
  gatewayLogPath?: string
}

export interface ProcessRow {
  command: string
  pid: number
}

// ---- stale LAN gateway recovery ------------------------------------------
//
// The LAN gateway runs in its own process group (detached) so stop() reaches a
// python child behind a shell shim. That also means a desktop that died hard
// (SIGKILL, power loss, a crash before before-quit) leaves the gateway running,
// and the next launch's autostart found its port busy and gave up with
// "Port 9319 sudah dipakai" while the orphan kept serving: two core processes
// and a remote page stuck in an error. The PID is now recorded, and a recorded
// PID whose command line is still our `serve --port <port>` gateway is stopped
// before the port check. Anything else on the port is never touched.

/** argv of a live process, NUL-separated args joined by spaces; null when unknown. */
export function readProcessCommandLine(pid: number): string | null {
  if (!Number.isInteger(pid) || pid <= 0) {
    return null
  }

  if (process.platform === 'linux') {
    try {
      const raw = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8')

      return raw ? raw.split('\0').join(' ').trim() : null
    } catch {
      return null
    }
  }

  // macOS/Windows: no cheap, dependable argv probe here; never judge.
  return null
}

/** Is this command line our own LAN gateway (`serve ... --port <port> ... --isolated`)? */
export function isOwnRemoteGatewayCommand(commandLine: string | null | undefined, port: number): boolean {
  if (typeof commandLine !== 'string' || !commandLine) {
    return false
  }

  const args = commandLine.split(/\s+/)
  const portAt = args.indexOf('--port')

  return (
    args.includes('serve') &&
    args.includes('--isolated') &&
    args.includes('0.0.0.0') &&
    portAt !== -1 &&
    args[portAt + 1] === String(port)
  )
}

export function readRemotePid(pidFilePath: string): number | null {
  try {
    const pid = Number.parseInt(fs.readFileSync(pidFilePath, 'utf8').trim(), 10)

    return Number.isInteger(pid) && pid > 0 ? pid : null
  } catch {
    return null
  }
}

/** All processes with their command lines; [] when the platform gives no cheap listing. */
export async function listProcesses(): Promise<ProcessRow[]> {
  if (process.platform === 'linux') {
    let names: string[] = []

    try {
      names = fs.readdirSync('/proc').filter(name => /^\d+$/.test(name))
    } catch {
      return []
    }

    return names
      .map(name => ({ command: readProcessCommandLine(Number(name)) ?? '', pid: Number(name) }))
      .filter(row => row.command)
  }

  const run = (command: string, args: string[]) =>
    new Promise<string>(resolve => {
      execFile(command, args, { maxBuffer: 16 * 1024 * 1024, timeout: 8000, windowsHide: true }, (error, stdout) =>
        resolve(error ? '' : String(stdout || ''))
      )
    })

  const rows = (text: string, sep: RegExp) =>
    text
      .split(/\r?\n/)
      .map(line => line.trim().match(sep))
      .filter((m): m is RegExpMatchArray => Boolean(m))
      .map(m => ({ command: m[2]!, pid: Number(m[1]) }))
      .filter(row => Number.isInteger(row.pid) && row.pid > 0)

  if (process.platform === 'win32') {
    const out = await run('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--isolated*' } | " +
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    ])

    return rows(out, /^(\d+)\t(.+)$/)
  }

  return rows(await run('ps', ['-axo', 'pid=,command=']), /^(\d+)\s+(.+)$/)
}

/** PIDs of our own LAN gateways (`serve --host 0.0.0.0 --port <port> --isolated`) still running. */
export function ownGatewayPids(rows: ProcessRow[], port: number, exclude: (number | undefined)[] = []): number[] {
  const skip = new Set(exclude.filter((pid): pid is number => typeof pid === 'number'))

  return rows.filter(row => !skip.has(row.pid) && isOwnRemoteGatewayCommand(row.command, port)).map(row => row.pid)
}

function defaultKillProcessGroup(pid: number, signal: NodeJS.Signals): void {
  if (process.platform === 'win32') {
    // A Windows gateway is a launcher with a python child: end the whole tree.
    execFile('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => {})

    return
  }

  try {
    process.kill(-pid, signal)
  } catch {
    try {
      process.kill(pid, signal)
    } catch {
      // already gone
    }
  }
}

// ---- token minting (mirrors plugins/dashboard_auth/basic `_sign`) ----------

export function decodeSecret(secret: string): Buffer {
  return Buffer.from(secret, 'base64')
}

export function mintAccessToken(secret: Buffer, issuedAtSeconds = Math.floor(Date.now() / 1000)): string {
  // Python: json.dumps(payload, separators=(",", ":")) keeps insertion order.
  const raw = Buffer.from(JSON.stringify({ sub: TOKEN_SUBJECT, kind: 'access', exp: issuedAtSeconds + TOKEN_TTL_SECONDS }))
  const sig = crypto.createHmac('sha256', secret).update(raw).digest()

  // Python's urlsafe_b64encode keeps '=' padding.
  return Buffer.concat([raw, sig]).toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

export function verifyAccessToken(token: string, secret: Buffer, nowSeconds = Math.floor(Date.now() / 1000)): boolean {
  try {
    const blob = Buffer.from(token.replace(/-/g, '+').replace(/_/g, '/'), 'base64')

    if (blob.length <= 32) {
      return false
    }

    const raw = blob.subarray(0, blob.length - 32)
    const sig = blob.subarray(blob.length - 32)
    const expected = crypto.createHmac('sha256', secret).update(raw).digest()

    if (!crypto.timingSafeEqual(sig, expected)) {
      return false
    }

    const payload = JSON.parse(raw.toString('utf8'))

    return payload.kind === 'access' && Number(payload.exp) > nowSeconds
  } catch {
    return false
  }
}

// ---- port ownership ---------------------------------------------------------

/** True when something already accepts connections on 127.0.0.1:<port>. */
export function portInUse(port: number, host = '127.0.0.1', timeoutMs = 800): Promise<boolean> {
  return new Promise(resolve => {
    const socket = net.connect({ port, host })
    const done = (busy: boolean) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(busy)
    }

    socket.setTimeout(timeoutMs, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

// ---- LAN addresses ----------------------------------------------------------

// Adapters the phone can never reach the PC through. Linux/macOS names are
// prefixes; Windows names are descriptive ("vEthernet (WSL)", "VirtualBox
// Host-Only Network", "VMware Network Adapter VMnet8", "Bluetooth Network
// Connection"), so they are matched anywhere. Before this, a VirtualBox
// host-only 192.168.56.1 ranked first on Windows and went into the QR code.
const VIRTUAL_IFACE =
  /^(docker|br-|veth|virbr|vmnet|vboxnet|lo\d*$|utun|awdl|llw|zt|tun|tap)|vethernet|hyper-v|\bwsl\b|virtualbox|vmware|virtual|bluetooth|loopback|npcap|tap-|openvpn|wireguard|zerotier|hamachi|radmin|\bvpn\b/i

export function lanAddresses(interfaces = os.networkInterfaces()): RemoteAddress[] {
  const out: RemoteAddress[] = []

  for (const [iface, entries] of Object.entries(interfaces)) {
    for (const entry of entries ?? []) {
      if (entry.family !== 'IPv4' || entry.internal || entry.address.startsWith('169.254.')) {
        continue
      }

      out.push({ address: entry.address, iface, kind: isTailnetIp(entry.address) ? 'tailscale' : 'lan' })
    }
  }

  const rank = (a: RemoteAddress) =>
    (VIRTUAL_IFACE.test(a.iface) ? 10 : 0) +
    (/^192\.168\./.test(a.address) ? 0 : /^10\./.test(a.address) ? 1 : /^172\.(1[6-9]|2\d|3[01])\./.test(a.address) ? 2 : /^100\./.test(a.address) ? 3 : 4)

  return out.sort((a, b) => rank(a) - rank(b))
}

/** 100.64.0.0/10: the CGNAT range Tailscale assigns tailnet addresses from. */
export function isTailnetIp(address: string): boolean {
  const m = /^100\.(\d+)\./.exec(address)

  return Boolean(m && Number(m[1]) >= 64 && Number(m[1]) <= 127)
}

/** Parse `tailscale status --json` (Self.DNSName + Self.TailscaleIPs). */
export function parseTailscaleStatus(json: string): TailscaleInfo | null {
  try {
    const self = (JSON.parse(json) as { Self?: { DNSName?: string; TailscaleIPs?: string[] } }).Self

    if (!self) {
      return null
    }

    return {
      dnsName: (self.DNSName ?? '').replace(/\.$/, '') || null,
      ips: (self.TailscaleIPs ?? []).filter(isTailnetIp)
    }
  } catch {
    return null
  }
}

export function readTailscale(): Promise<TailscaleInfo | null> {
  const exe = process.platform === 'win32' ? 'tailscale.exe' : 'tailscale'

  return new Promise(resolve => {
    execFile(exe, ['status', '--json'], { timeout: 4000, windowsHide: true }, (err, stdout) => {
      resolve(err ? null : parseTailscaleStatus(String(stdout)))
    })
  })
}

/** Phone try order after the primary `url`: other real LAN addresses, MagicDNS, tailnet IPs. */
export function fallbackUrls(input: {
  primary: string | null
  addresses: RemoteAddress[]
  tailscale: TailscaleInfo | null
  port: number
}): string[] {
  const hosts: string[] = []
  const lan = input.addresses.filter(a => !isTailnetIp(a.address) && !VIRTUAL_IFACE.test(a.iface))
  const tailnet = new Set([
    ...input.addresses.filter(a => isTailnetIp(a.address)).map(a => a.address),
    ...(input.tailscale?.ips ?? [])
  ])

  hosts.push(...lan.map(a => a.address))

  if (input.tailscale?.dnsName) {
    hosts.push(input.tailscale.dnsName)
  }

  hosts.push(...[...tailnet].sort())

  return [...new Set(hosts)].filter(h => h !== input.primary).map(h => `http://${h}:${input.port}`)
}

export function buildPairingUri(input: {
  url: string
  token: string
  name: string
  profile: string | null
  alt?: string[]
  /** Remote dari mana saja: relay room id, PC public key, relay URL, pairing code, Bluetooth target. */
  link?: { pcId: string; pcPk: string; relayUrl: string | null; pairCode: string; btAddress?: string | null; btChannel?: number | null } | null
}): string {
  const q = new URLSearchParams({ v: '1', url: input.url })

  for (const alt of input.alt ?? []) {
    q.append('alt', alt)
  }

  q.set('token', input.token)
  q.set('name', input.name)

  if (input.profile) {
    q.set('profile', input.profile)
  }

  if (input.link) {
    q.set('pc', input.link.pcId)
    q.set('pk', input.link.pcPk)

    if (input.link.relayUrl) {
      q.set('relay', input.link.relayUrl)
    }

    q.set('pair', input.link.pairCode)

    if (input.link.btAddress) {
      q.set('bt', input.link.btAddress)

      if (input.link.btChannel) {
        q.set('btch', String(input.link.btChannel))
      }
    }
  }

  return `neovarch://pair?${q.toString()}`
}

// ---- controller -------------------------------------------------------------

function newSecret(): string {
  return crypto.randomBytes(32).toString('base64')
}

export const FALLBACK_DEVICE_NAME = 'PC Neovarch'

/**
 * The name the phone shows for this PC. Some Linux hosts (containers, minimal
 * installs) report an empty hostname or the literal "(none)"; those fall back
 * to a readable default instead of being shown to the user.
 */
export function resolveDeviceName(name: string | null | undefined = os.hostname()): string {
  const trimmed = typeof name === 'string' ? name.trim() : ''

  if (!trimmed || trimmed === '(none)') {
    return FALLBACK_DEVICE_NAME
  }

  return trimmed.slice(0, 64)
}

function defaultSettings(): RemoteSettings {
  return {
    enabled: false,
    port: REMOTE_DEFAULT_PORT,
    secret: newSecret(),
    issuedAt: Math.floor(Date.now() / 1000),
    preferredAddress: null,
    deviceName: resolveDeviceName(),
    relayEnabled: true,
    relayUrl: null,
    bluetoothEnabled: false
  }
}

export function createRemoteController(deps: RemoteControllerDeps) {
  let settings = readSettings()
  let child: ChildProcess | null = null
  let running = false
  let starting = false
  let error: string | null = null
  let logTail = ''
  let generation = 0
  let link: RemoteLinkInfo | null = null
  let linkTimer: ReturnType<typeof setInterval> | null = null
  let tailscale: TailscaleInfo | null = null
  let tailscaleAt = 0
  // Set once the app is quitting: a late autostart/rotate must not spawn a
  // gateway that outlives the desktop.
  let closed = false
  const pidFilePath = deps.pidFilePath ?? path.join(path.dirname(deps.settingsPath), 'neovarch-remote.pid')
  const commandLineOf = deps.processCommandLine ?? readProcessCommandLine
  const killGroup = deps.killProcessGroup ?? defaultKillProcessGroup
  const probePort = deps.portInUse ?? ((port: number) => portInUse(port))
  const processRows = deps.listProcesses ?? listProcesses
  const background = () => deps.backgroundMode?.() === true
  const gatewayLogPath = deps.gatewayLogPath ?? path.join(path.dirname(deps.settingsPath), 'neovarch-remote-gateway.log')
  // A background gateway started by an earlier desktop session (no ChildProcess handle).
  let adoptedPid: number | null = null
  let adoptTimer: ReturnType<typeof setInterval> | null = null

  function readGatewayLogTail(): string {
    try {
      const st = fs.statSync(gatewayLogPath)
      const len = Math.min(st.size, 8000)
      const fd = fs.openSync(gatewayLogPath, 'r')

      try {
        const buf = Buffer.alloc(len)
        fs.readSync(fd, buf, 0, len, st.size - len)

        return buf.toString('utf8')
      } finally {
        fs.closeSync(fd)
      }
    } catch {
      return ''
    }
  }

  function stopAdoptWatch() {
    if (adoptTimer) {
      clearInterval(adoptTimer)
      adoptTimer = null
    }
  }

  /**
   * Background mode: keep the gateway an earlier session left running (same
   * secret, same port) instead of killing it. True when adopted.
   */
  async function adoptBackgroundGateway(): Promise<boolean> {
    const pid = readRemotePid(pidFilePath)

    if (pid === null || !isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port)) {
      return false
    }

    try {
      const res = await (deps.fetch ?? fetch)(`http://127.0.0.1:${settings.port}/api/status`, { signal: AbortSignal.timeout(2000) })

      if (!res.ok) {
        return false
      }
    } catch {
      return false
    }

    adoptedPid = pid
    running = true
    deps.log(`[remote] adopted background LAN gateway pid=${pid}`)
    stopAdoptWatch()
    adoptTimer = setInterval(() => {
      if (adoptedPid !== null && !isOwnRemoteGatewayCommand(commandLineOf(adoptedPid), settings.port)) {
        deps.log(`[remote] background gateway pid=${adoptedPid} is gone`)
        adoptedPid = null
        running = false
        stopAdoptWatch()
        stopLinkPoll()
        link = null
        clearPid()

        if (settings.enabled && !closed) {
          void start()
        } else {
          emit()
        }
      }
    }, 5000)
    adoptTimer.unref?.()

    return true
  }

  function writePid(pid: number | undefined) {
    if (!pid) {
      return
    }

    try {
      fs.mkdirSync(path.dirname(pidFilePath), { recursive: true })
      fs.writeFileSync(pidFilePath, `${pid}\n`, 'utf8')
    } catch {
      // Best effort: without it only hard-crash recovery is lost.
    }
  }

  function clearPid(pid?: number) {
    if (pid !== undefined && readRemotePid(pidFilePath) !== pid) {
      return
    }

    try {
      fs.unlinkSync(pidFilePath)
    } catch {
      // not there
    }
  }

  /** Stop a gateway a previous (crashed or older) desktop left behind. Returns its PID. */
  async function reapStaleGateway(): Promise<number | null> {
    const recorded = await reapRecordedGateway()

    if (recorded !== null) {
      return recorded
    }

    return reapOrphanGateways()
  }

  /**
   * A LAN gateway with no PID file: one started by an older desktop (v1.3.x
   * wrote none) keeps port 9319, so the phone kept talking to that old core
   * ("versi 1.3.0, 0 sesi aktif") while this desktop refused to start its own
   * ("port sudah dipakai"). Only processes whose command line is exactly our
   * `serve --host 0.0.0.0 --port <port> --isolated` are stopped.
   */
  async function reapOrphanGateways(): Promise<number | null> {
    if (!(await probePort(settings.port))) {
      return null
    }

    let pids: number[] = []

    try {
      pids = ownGatewayPids(await processRows(), settings.port, [child?.pid, process.pid])
    } catch {
      return null
    }

    for (const pid of pids) {
      deps.log(`[remote] stopping LAN gateway pid=${pid} left by an older desktop`)
      killGroup(pid, 'SIGTERM')
    }

    if (!pids.length) {
      return null
    }

    for (let i = 0; i < 20 && (await probePort(settings.port)); i++) {
      await new Promise(r => setTimeout(r, 150))
    }

    if (await probePort(settings.port)) {
      for (const pid of pids) {
        killGroup(pid, 'SIGKILL')
      }

      for (let i = 0; i < 10 && (await probePort(settings.port)); i++) {
        await new Promise(r => setTimeout(r, 150))
      }
    }

    return pids[0] ?? null
  }

  async function reapRecordedGateway(): Promise<number | null> {
    const pid = readRemotePid(pidFilePath)

    if (pid === null) {
      return null
    }

    if (!isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port)) {
      // Dead, reused by another program, or unverifiable: just forget it.
      clearPid()

      return null
    }

    deps.log(`[remote] stopping stale LAN gateway pid=${pid} left by an earlier run`)
    killGroup(pid, 'SIGTERM')

    for (let i = 0; i < 20; i++) {
      if (!isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port)) {
        break
      }

      await new Promise(r => setTimeout(r, 150))
    }

    if (isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port)) {
      killGroup(pid, 'SIGKILL')
    }

    clearPid()

    return pid
  }

  // Tailscale is optional: read it lazily (at most once a minute) and re-emit
  // when the MagicDNS name or tailnet IPs change.
  function refreshTailscale(force = false) {
    if (!force && Date.now() - tailscaleAt < 60_000) {
      return
    }

    tailscaleAt = Date.now()
    void readTailscale().then(next => {
      if (JSON.stringify(next) !== JSON.stringify(tailscale)) {
        tailscale = next
        emit()
      }
    })
  }

  function readSettings(): RemoteSettings {
    try {
      const parsed = JSON.parse(fs.readFileSync(deps.settingsPath, 'utf8'))
      const base = defaultSettings()

      return {
        enabled: parsed.enabled === true,
        // v1.2.x defaulted to 9119, Hermes Agent's port; move those to Neovarch's own.
        port:
          Number.isInteger(parsed.port) && parsed.port > 0 && parsed.port < 65536 && parsed.port !== HERMES_DEFAULT_PORT
            ? parsed.port
            : base.port,
        secret: typeof parsed.secret === 'string' && decodeSecret(parsed.secret).length >= 32 ? parsed.secret : base.secret,
        issuedAt: Number.isInteger(parsed.issuedAt) && parsed.issuedAt > 0 ? parsed.issuedAt : base.issuedAt,
        preferredAddress: typeof parsed.preferredAddress === 'string' ? parsed.preferredAddress : null,
        deviceName: typeof parsed.deviceName === 'string' ? resolveDeviceName(parsed.deviceName) : base.deviceName,
        relayEnabled: typeof parsed.relayEnabled === 'boolean' ? parsed.relayEnabled : base.relayEnabled,
        relayUrl: typeof parsed.relayUrl === 'string' ? normalizeRelayUrl(parsed.relayUrl) : null,
        bluetoothEnabled: parsed.bluetoothEnabled === true
      }
    } catch {
      return defaultSettings()
    }
  }

  function writeSettings() {
    try {
      fs.mkdirSync(path.dirname(deps.settingsPath), { recursive: true })
      fs.writeFileSync(deps.settingsPath, JSON.stringify(settings, null, 2), { encoding: 'utf8', mode: 0o600 })
    } catch (err) {
      deps.log(`[remote] failed to save settings: ${(err as Error).message}`)
    }
  }

  function status(): RemoteStatus {
    const addresses = lanAddresses()

    const address =
      (settings.preferredAddress && addresses.find(a => a.address === settings.preferredAddress)?.address) ||
      addresses[0]?.address ||
      null

    const url = address ? `http://${address}:${settings.port}` : null
    const token = mintAccessToken(decodeSecret(settings.secret), settings.issuedAt)
    const profile = deps.currentProfile()
    refreshTailscale()
    const altUrls = fallbackUrls({ primary: address, addresses, tailscale, port: settings.port })
    const relayUrl = settings.relayUrl || DEFAULT_RELAY_URL

    const pairLink =
      link && running
        ? {
            pcId: link.pc_id,
            pcPk: link.pc_pk,
            relayUrl: settings.relayEnabled ? link.relay?.url || relayUrl : null,
            pairCode: link.pair_code,
            btAddress: settings.bluetoothEnabled ? link.bluetooth?.address : null,
            btChannel: settings.bluetoothEnabled ? link.bluetooth?.channel : null
          }
        : null

    return {
      enabled: settings.enabled,
      running,
      starting,
      port: settings.port,
      addresses,
      address,
      url,
      token: settings.enabled ? token : null,
      pairingUri:
        settings.enabled && url
          ? buildPairingUri({ url, token, name: settings.deviceName, profile, alt: altUrls, link: pairLink })
          : null,
      altUrls,
      tailscale,
      deviceName: settings.deviceName,
      profile,
      error,
      logTail: logTail.slice(-2000),
      relay: {
        enabled: settings.relayEnabled,
        url: relayUrl,
        defaultUrl: DEFAULT_RELAY_URL,
        state: !settings.enabled || !settings.relayEnabled ? 'off' : (link?.relay?.state ?? 'connecting'),
        error: link?.relay?.error ?? null,
        phones: link?.relay?.phones ?? 0
      },
      bluetooth: {
        enabled: settings.bluetoothEnabled,
        state: !settings.enabled || !settings.bluetoothEnabled ? 'off' : (link?.bluetooth?.state ?? 'connecting'),
        error: link?.bluetooth?.error ?? null,
        address: link?.bluetooth?.address ?? null,
        phones: link?.bluetooth?.phones ?? 0
      },
      devices: link?.devices ?? []
    }
  }

  /** Env for the remote gateway's encrypted-link transports (core remote_link/service.py). */
  function linkEnv(): NodeJS.ProcessEnv {
    return {
      NEOVARCH_LINK: '1',
      NEOVARCH_RELAY: settings.relayEnabled ? '1' : '0',
      NEOVARCH_RELAY_URL: settings.relayUrl || DEFAULT_RELAY_URL,
      NEOVARCH_BT: settings.bluetoothEnabled ? '1' : '0',
      NEOVARCH_REMOTE_NAME: settings.deviceName
    }
  }

  /** Ask the running gateway for its link identity, pairing code, transports and devices. */
  async function linkCall(method: 'GET' | 'POST' | 'DELETE', route: string, body?: unknown): Promise<RemoteLinkInfo | null> {
    const token = mintAccessToken(decodeSecret(settings.secret), settings.issuedAt)

    try {
      const res = await (deps.fetch ?? fetch)(`http://127.0.0.1:${settings.port}${route}`, {
        method,
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(5000)
      })

      if (!res.ok) {
        return null
      }

      const j = (await res.json()) as RemoteLinkInfo

      return j && typeof j.pc_id === 'string' ? j : null
    } catch {
      return null
    }
  }

  async function refreshLink() {
    if (!running) {
      return
    }

    const next = await linkCall('GET', '/api/remote/link')

    if (next && JSON.stringify(next) !== JSON.stringify(link)) {
      link = next
      emit()
    }
  }

  function startLinkPoll() {
    stopLinkPoll()
    void refreshLink()
    linkTimer = setInterval(() => void refreshLink(), 15_000)
    linkTimer.unref?.()
  }

  function stopLinkPoll() {
    if (linkTimer) {
      clearInterval(linkTimer)
      linkTimer = null
    }
  }

  function emit() {
    deps.onChanged?.(status())
  }

  async function waitForReady(gen: number, timeoutMs = 90_000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs

    while (Date.now() < deadline) {
      if (gen !== generation || !child) {
        return false
      }

      try {
        const res = await fetch(`http://127.0.0.1:${settings.port}/api/status`, { signal: AbortSignal.timeout(2000) })

        if (res.ok) {
          return true
        }
      } catch {
        // not up yet
      }

      await new Promise(r => setTimeout(r, 750))
    }

    return false
  }

  // Windows: ask once per app run for the inbound firewall rule (UAC prompt).
  let firewallAsked = false

  async function start() {
    if (child || starting || closed) {
      return
    }

    const gen = ++generation
    starting = true
    error = null
    logTail = ''
    emit()

    try {
      if (adoptedPid !== null) {
        return
      }

      if (background() && (await adoptBackgroundGateway())) {
        startLinkPoll()

        return
      }

      // Never fight another program (a co-installed Hermes on 9119, anything
      // else) for the port: refuse up front instead of spawning and probing a
      // server that is not ours.
      await reapStaleGateway()

      if (gen !== generation || closed) {
        return
      }

      if (await probePort(settings.port)) {
        error =
          settings.port === HERMES_DEFAULT_PORT
            ? `Port ${settings.port} dipakai Hermes Agent. Pilih port lain untuk Neovarch (bawaan ${REMOTE_DEFAULT_PORT}).`
            : `Port ${settings.port} sudah dipakai aplikasi lain. Pilih port lain.`
        deps.log(`[remote] port ${settings.port} busy; not starting`)

        return
      }

      const spec = await deps.resolveSpawn(['serve', '--host', '0.0.0.0', '--port', String(settings.port), '--isolated'])

      if (gen !== generation || closed) {
        return
      }

      const env: NodeJS.ProcessEnv = {
        ...spec.env,
        HERMES_DASHBOARD_BASIC_AUTH_USERNAME: TOKEN_SUBJECT,
        // Random per start and never shown: the phone never logs in with a
        // password, it presents the HMAC token minted above.
        HERMES_DASHBOARD_BASIC_AUTH_PASSWORD: crypto.randomBytes(24).toString('base64url'),
        HERMES_DASHBOARD_BASIC_AUTH_SECRET: settings.secret,
        // Windows consoles default to cp1252/cp437; keep the core's stdio UTF-8.
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        ...linkEnv()
      }

      delete env.HERMES_DESKTOP // the primary backend owns cron ticks
      delete env.HERMES_DASHBOARD_SESSION_TOKEN
      env.NEOVARCH_DESKTOP_PID = String(process.pid)
      const bg = background()
      deps.log(`[remote] starting LAN gateway on 0.0.0.0:${settings.port}${bg ? ' (background)' : ''}`)

      // Background: output goes to a log file so nothing ties the gateway to
      // this Electron process (a closed pipe would kill it on its next write).
      let logFd: number | null = null

      if (bg) {
        try {
          fs.mkdirSync(path.dirname(gatewayLogPath), { recursive: true })
          logFd = fs.openSync(gatewayLogPath, 'a')
        } catch {
          logFd = null
        }
      }

      const proc = spawn(spec.command, spec.args, {
        cwd: spec.cwd,
        env,
        shell: spec.shell,
        stdio: logFd !== null ? ['ignore', logFd, logFd] : ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
        // Own process group on POSIX so stop() also reaches a python child behind a shell shim;
        // background mode also detaches on Windows so the gateway outlives the app.
        detached: process.platform !== 'win32' || bg
      })

      if (logFd !== null) {
        try {
          fs.closeSync(logFd)
        } catch {
          // the child holds its own copy
        }
      }

      child = proc
      writePid(proc.pid)

      const onData = (chunk: Buffer) => {
        logTail = (logTail + chunk.toString('utf8')).slice(-8000)
      }

      proc.stdout?.on('data', onData)
      proc.stderr?.on('data', onData)
      proc.once('error', err => {
        error = `Gagal menjalankan gateway remote: ${err.message}`
      })
      proc.once('exit', (code, signal) => {
        clearPid(proc.pid)

        if (child === proc) {
          child = null
          running = false
          starting = false
          stopLinkPoll()
          link = null

          if (!logTail) {
            logTail = readGatewayLogTail()
          }

          // Restart asked from the phone on Windows (no exec() there): start again.
          if (code === GATEWAY_RESTART_EXIT_CODE && settings.enabled && !closed && gen === generation) {
            deps.log('[remote] gateway asked for a restart')
            emit()
            void start()

            return
          }

          if (settings.enabled && gen === generation && code === 0 && signal === null) {
            error = 'Gateway remote dihentikan (dari HP). Matikan lalu nyalakan lagi akses remote untuk memulainya.'
          } else if (settings.enabled && gen === generation) {
            const tail = logTail.trim().split('\n').slice(-3).join(' ')
            error = `Gateway remote berhenti (kode ${code ?? signal}). ${tail}`.trim()
          }

          deps.log(`[remote] gateway exited code=${code} signal=${signal}`)
          emit()
        }
      })

      const ready = await waitForReady(gen)

      if (gen !== generation) {
        return
      }

      running = ready && child === proc

      if (running) {
        startLinkPoll()
      }

      if (running && process.platform === 'win32' && !firewallAsked) {
        firewallAsked = true
        void ensureFirewallRule(settings.port)
          .then(result => {
            deps.log(`[remote] windows firewall rule for port ${settings.port}: ${result}`)

            if (result === 'declined') {
              deps.log(`[remote] ${firewallHelp(settings.port)}`)
            }
          })
          .catch(err => deps.log(`[remote] windows firewall check failed: ${(err as Error).message}`))
      }

      if (!ready && child === proc) {
        error = error || `Gateway remote tidak merespons di port ${settings.port}. Port mungkin sudah dipakai aplikasi lain.`
      }
    } catch (err) {
      error = (err as Error).message
    } finally {
      if (gen === generation) {
        starting = false
      }

      emit()
    }
  }

  async function stop() {
    generation++
    const proc = child
    child = null
    running = false
    starting = false
    stopLinkPoll()
    link = null

    if (adoptedPid !== null) {
      const pid = adoptedPid
      adoptedPid = null
      stopAdoptWatch()
      killGroup(pid, 'SIGTERM')

      for (let i = 0; i < 20 && isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port); i++) {
        await new Promise(r => setTimeout(r, 150))
      }

      if (isOwnRemoteGatewayCommand(commandLineOf(pid), settings.port)) {
        killGroup(pid, 'SIGKILL')
      }

      clearPid()
    }

    if (!proc || proc.exitCode !== null) {
      return
    }

    await new Promise<void>(resolve => {
      const timer = setTimeout(() => {
        try {
          if (process.platform !== 'win32' && proc.pid) {
            process.kill(-proc.pid, 'SIGKILL')
          } else {
            proc.kill('SIGKILL')
          }
        } catch {
          // already gone
        }

        resolve()
      }, 5000)

      proc.once('exit', () => {
        clearTimeout(timer)
        resolve()
      })

      try {
        if (process.platform === 'win32' && proc.pid) {
          spawn('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { windowsHide: true })
        } else if (proc.pid) {
          try {
            process.kill(-proc.pid, 'SIGTERM')
          } catch {
            proc.kill('SIGTERM')
          }
        } else {
          proc.kill('SIGTERM')
        }
      } catch {
        clearTimeout(timer)
        resolve()
      }
    })
  }

  async function setEnabled(on: boolean) {
    settings = { ...settings, enabled: on }
    writeSettings()
    error = null

    if (on) {
      void start()
    } else {
      await stop()
    }

    emit()

    return status()
  }

  async function rotate() {
    settings = { ...settings, secret: newSecret(), issuedAt: Math.floor(Date.now() / 1000) }
    writeSettings()

    if (settings.enabled) {
      await stop()
      void start()
    }

    emit()

    return status()
  }

  function update(patch: Partial<Pick<RemoteSettings, 'deviceName' | 'preferredAddress'>>) {
    if (typeof patch.deviceName === 'string' && patch.deviceName.trim()) {
      settings.deviceName = patch.deviceName.trim().slice(0, 64)
    }

    if (patch.preferredAddress === null || typeof patch.preferredAddress === 'string') {
      settings.preferredAddress = patch.preferredAddress
    }

    writeSettings()
    emit()

    return status()
  }

  /** Settings → Remote: "Akses dari mana saja (relay)" toggle and relay URL (empty = default). */
  async function setRelay(patch: { enabled?: boolean; url?: string | null }) {
    if (typeof patch.enabled === 'boolean') {
      settings.relayEnabled = patch.enabled
    }

    if (patch.url !== undefined) {
      const raw = (patch.url ?? '').trim()
      const n = raw ? normalizeRelayUrl(raw) : null

      if (raw && !n) {
        error = 'Relay URL harus diawali wss:// atau https://'
        emit()

        return status()
      }

      settings.relayUrl = n && n !== DEFAULT_RELAY_URL ? n : null
    }

    error = null
    writeSettings()

    if (running) {
      const next = await linkCall('POST', '/api/remote/link/config', {
        relay_enabled: settings.relayEnabled,
        relay_url: settings.relayUrl || DEFAULT_RELAY_URL
      })

      if (next) {
        link = next
      }
    }

    emit()

    return status()
  }

  /** Settings → Remote: Bluetooth transport (off by default). */
  async function setBluetooth(on: boolean) {
    settings.bluetoothEnabled = on
    writeSettings()

    if (running) {
      const next = await linkCall('POST', '/api/remote/link/config', { bluetooth_enabled: on })

      if (next) {
        link = next
      }
    }

    emit()

    return status()
  }

  /** Revoke one paired phone's relay/Bluetooth access (its live link is dropped). */
  async function revokeDevice(id: string) {
    if (running && /^[A-Za-z0-9_-]{1,64}$/.test(id)) {
      await linkCall('DELETE', `/api/remote/devices/${encodeURIComponent(id)}`)
      await refreshLink()
    }

    emit()

    return status()
  }

  /** Probe what the phone will call: the Kanban board with the phone's token. */
  async function check(): Promise<{ ok: boolean; message: string }> {
    if (!running) {
      return { ok: false, message: 'Gateway remote belum berjalan.' }
    }

    const token = mintAccessToken(decodeSecret(settings.secret), settings.issuedAt)
    const host = status().address || '127.0.0.1'

    try {
      const res = await fetch(`http://${host}:${settings.port}/api/plugins/kanban/board`, {
        headers: { Authorization: `Bearer ${token}`, 'X-Hermes-Session-Token': token },
        signal: AbortSignal.timeout(5000)
      })

      if (res.ok) {
        return { ok: true, message: `Terhubung: ${host}:${settings.port} menerima token (Kanban OK).` }
      }

      if (res.status === 404) {
        return { ok: true, message: 'Token diterima, tetapi plugin Kanban nonaktif (tab Tugas di HP tidak akan berisi).' }
      }

      return { ok: false, message: `Gateway menjawab HTTP ${res.status}.` }
    } catch (err) {
      return {
        ok: false,
        message:
          `Tidak bisa menjangkau ${host}:${settings.port} (${(err as Error).message}). ` +
          (process.platform === 'win32' ? firewallHelp(settings.port) : 'Periksa firewall.')
      }
    }
  }

  return {
    status,
    setEnabled,
    rotate,
    update,
    setRelay,
    setBluetooth,
    revokeDevice,
    refreshLink,
    check,
    stop,
    /** Start at boot when the user left remote access on. */
    autostart() {
      if (settings.enabled && !closed) {
        void start()
      }
    },
    /** Quit path: no new gateway from here on, and the running one is stopped. */
    shutdown() {
      closed = true

      return stop()
    },
    /**
     * Quit path with "Jalankan di latar belakang": leave the gateway running on
     * its own (its PID file stays, so the next launch adopts it).
     */
    async detach() {
      closed = true
      generation++
      stopLinkPoll()
      stopAdoptWatch()
      const proc = child

      if (proc && proc.exitCode === null) {
        proc.removeAllListeners('exit')
        proc.stdout?.destroy()
        proc.stderr?.destroy()
        proc.unref()
        deps.log(`[remote] leaving LAN gateway pid=${proc.pid} running in the background`)
      }

      child = null
      adoptedPid = null
    },
    /** Whether a gateway process is attached (quit must wait for it). */
    hasProcess() {
      return child !== null && child.exitCode === null
    },
    /** Authenticated call to the running gateway (Settings ▸ Remote ▸ latar belakang). */
    async gatewayJson<T>(method: 'GET' | 'POST', route: string, body?: unknown): Promise<T | null> {
      if (!running) {
        return null
      }

      const token = mintAccessToken(decodeSecret(settings.secret), settings.issuedAt)

      try {
        const res = await (deps.fetch ?? fetch)(`http://127.0.0.1:${settings.port}${route}`, {
          method,
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: AbortSignal.timeout(5000)
        })

        return res.ok ? ((await res.json()) as T) : null
      } catch {
        return null
      }
    },
    /** True while a gateway is up (spawned here or adopted from the background). */
    isRunning() {
      return running
    },
    reapStaleGateway
  }
}

export type RemoteController = ReturnType<typeof createRemoteController>
