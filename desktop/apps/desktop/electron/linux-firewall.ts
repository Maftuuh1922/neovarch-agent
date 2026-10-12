/**
 * Linux firewall rule for the phone's LAN gateway (ufw / firewalld).
 *
 * Root cause of "HP hanya bisa lewat Tailscale, Wi-Fi yang sama gagal" on Linux:
 * distributions that turn a firewall on by default (Omarchy: ufw "deny incoming",
 * only LocalSend's 53317 open; Fedora: firewalld) drop the phone's connection to
 * port 9319 silently. Traffic over Tailscale arrives on `tailscale0`, which
 * Tailscale's own netfilter chain (and Omarchy's Tailscale setup) lets in, so the
 * same QR works over the tailnet and fails on the Wi-Fi. The desktop's own
 * "Periksa koneksi" probe still passed, because a connection from the PC to its
 * own LAN address goes over loopback and never meets the firewall.
 *
 * Fix: detect an active ufw/firewalld without root, and open the gateway port
 * for private LAN ranges only (10/8, 172.16/12, 192.168/16) through ONE polkit
 * prompt (pkexec). The gateway itself still requires a token. When pkexec is
 * missing or the prompt is dismissed we explain the exact command instead.
 */
import { execFile } from 'node:child_process'
import fs from 'node:fs'

export const LINUX_RULE_COMMENT = 'Neovarch Agent (HP remote)'

/** Private IPv4 ranges a phone on the same Wi-Fi/hotspot can come from. */
export const PRIVATE_CIDRS = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'] as const

export type LinuxFirewallKind = 'ufw' | 'firewalld' | 'none'

export type LinuxRun = (file: string, args: string[], timeoutMs: number) => Promise<number>

const run: LinuxRun = (file, args, timeoutMs) =>
  new Promise(resolve => {
    execFile(file, args, { timeout: timeoutMs }, err => {
      const code = (err as { code?: unknown } | null)?.code
      // ENOENT: the program is not installed (shell convention 127).
      resolve(err ? (typeof code === 'number' ? code : code === 'ENOENT' ? 127 : 1) : 0)
    })
  })

function validPort(port: number): number {
  if (!Number.isInteger(port) || port <= 0 || port >= 65536) {
    throw new Error(`invalid port ${port}`)
  }

  return port
}

/** `/etc/ufw/ufw.conf` is world-readable; ENABLED=yes means ufw comes up at boot. */
export function ufwEnabledFromConf(text: string | null): boolean {
  return Boolean(text && /^\s*ENABLED\s*=\s*yes\s*$/im.test(text))
}

/** Which firewall is active, detected without root. */
export async function detectLinuxFirewall(
  opts: { run?: LinuxRun; readFile?: (p: string) => string | null } = {}
): Promise<LinuxFirewallKind> {
  const exec = opts.run ?? run

  const read =
    opts.readFile ??
    ((p: string) => {
      try {
        return fs.readFileSync(p, 'utf8')
      } catch {
        return null
      }
    })

  if (ufwEnabledFromConf(read('/etc/ufw/ufw.conf'))) {
    // ufw.service is a oneshot: "active (exited)" while the rules are loaded.
    // No systemd (or no unit): trust ENABLED=yes.
    const code = await exec('systemctl', ['is-active', '--quiet', 'ufw'], 5_000)

    if (code === 0 || code === 127 || code === 4) {
      return 'ufw'
    }
  }

  if ((await exec('systemctl', ['is-active', '--quiet', 'firewalld'], 5_000)) === 0) {
    return 'firewalld'
  }

  return 'none'
}

/** Root shell script that opens the port for private LAN ranges (idempotent). */
export function linuxFirewallScript(kind: Exclude<LinuxFirewallKind, 'none'>, port: number): string {
  const p = validPort(port)

  if (kind === 'ufw') {
    // ufw skips a rule that already exists, so running this twice is harmless.
    return PRIVATE_CIDRS.map(
      c => `ufw allow in proto tcp from ${c} to any port ${p} comment '${LINUX_RULE_COMMENT}'`
    ).join(' && ')
  }

  return [
    ...PRIVATE_CIDRS.map(
      c => `firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="${c}" port port="${p}" protocol="tcp" accept'`
    ),
    'firewall-cmd --reload'
  ].join(' && ')
}

/** The same commands for a person to paste into a terminal. */
export function linuxManualCommand(kind: Exclude<LinuxFirewallKind, 'none'>, port: number): string {
  return linuxFirewallScript(kind, port)
    .split(' && ')
    .map(c => `sudo ${c}`)
    .join(' && ')
}

export function linuxFirewallBlockHelp(kind: LinuxFirewallKind, port: number): string {
  if (kind === 'none') {
    return (
      `Firewall Linux tidak terdeteksi aktif. Bila HP tetap tidak terjangkau lewat Wi-Fi, pastikan HP dan PC di jaringan ` +
      `yang sama dan router tidak memakai "AP/client isolation" (Wi-Fi tamu biasanya begitu).`
    )
  }

  return (
    `${kind} aktif dan memblokir HP di port ${port} (Tailscale tetap jalan karena lewat antarmuka tailscale0). ` +
    `Izinkan port ini hanya untuk jaringan lokal: ${linuxManualCommand(kind, port)}`
  )
}

export type LinuxFirewallResult = 'not-linux' | 'none' | 'added' | 'declined'

/**
 * Open the gateway port in an active ufw/firewalld through one polkit prompt.
 * 'none' when no firewall is active (nothing to do), 'declined' when pkexec is
 * missing, the prompt was dismissed, or the command failed.
 */
export async function ensureLinuxFirewallRule(
  port: number,
  opts: { platform?: NodeJS.Platform; run?: LinuxRun; readFile?: (p: string) => string | null; kind?: LinuxFirewallKind } = {}
): Promise<{ result: LinuxFirewallResult; kind: LinuxFirewallKind }> {
  const platform = opts.platform ?? process.platform

  if (platform !== 'linux') {
    return { result: 'not-linux', kind: 'none' }
  }

  const exec = opts.run ?? run
  const kind = opts.kind ?? (await detectLinuxFirewall({ run: exec, readFile: opts.readFile }))

  if (kind === 'none') {
    return { result: 'none', kind }
  }

  const code = await exec('pkexec', ['/bin/sh', '-c', linuxFirewallScript(kind, port)], 120_000)

  return { result: code === 0 ? 'added' : 'declined', kind }
}
