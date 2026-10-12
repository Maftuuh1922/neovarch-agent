// Tailscale is the primary way the Neovarch phone reaches this PC from
// anywhere (v1.4.7): the built-in cloud relay is not deployed, and the LAN only
// works on the same Wi-Fi. This module finds out, without root, whether
// Tailscale is installed, its daemon is running, the PC is logged in and the
// tunnel is up, and gives the per-OS steps Settings ▸ Remote shows when not.
//
// Detection only runs the unprivileged CLI (`tailscale status --json`, then
// `tailscale ip -4` as a fallback); nothing here installs or starts anything.

import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

/** not-installed → daemon-down → logged-out → stopped → starting → running */
export type TailscaleState = 'not-installed' | 'daemon-down' | 'logged-out' | 'stopped' | 'starting' | 'running'

export interface TailscaleDetect {
  state: TailscaleState
  /** The CLI that was found (null when not installed). */
  bin: string | null
  /** BackendState from `tailscale status --json` (Running, NeedsLogin, Stopped, …). */
  backendState: string | null
  /** MagicDNS name of this PC without the trailing dot. */
  dnsName: string | null
  /** Tailnet IPv4 addresses (100.64.0.0/10). */
  ips: string[]
  /** Tailscale account shown to the user (LoginName), when logged in. */
  account: string | null
}

export type TailscalePlatform = 'linux' | 'win32' | 'darwin' | string

/** 100.64.0.0/10: the CGNAT range Tailscale assigns tailnet addresses from. */
export function isTailnetIpv4(address: string): boolean {
  const m = /^100\.(\d+)\.\d+\.\d+$/.exec(address.trim())

  return Boolean(m && Number(m[1]) >= 64 && Number(m[1]) <= 127)
}

/** Where the Tailscale CLI usually lives when it is not on PATH (GUI installs). */
export function tailscaleBinaryCandidates(platform: TailscalePlatform, env: NodeJS.ProcessEnv = process.env): string[] {
  if (platform === 'win32') {
    const pf = env.ProgramFiles || 'C:\\Program Files'
    const pf86 = env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'

    return ['tailscale.exe', path.win32.join(pf, 'Tailscale', 'tailscale.exe'), path.win32.join(pf86, 'Tailscale', 'tailscale.exe')]
  }

  if (platform === 'darwin') {
    return [
      'tailscale',
      '/usr/local/bin/tailscale',
      '/opt/homebrew/bin/tailscale',
      '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
    ]
  }

  return ['tailscale', '/usr/bin/tailscale', '/usr/local/bin/tailscale', '/usr/sbin/tailscale', '/snap/bin/tailscale']
}

export interface CliResult {
  code: number | null
  stdout: string
  stderr: string
  /** spawn failed (ENOENT = not there) */
  missing?: boolean
}

/**
 * Classify the CLI's answers. Pure: the tests feed it recorded outputs.
 *  - no binary anywhere           → not-installed
 *  - "failed to connect to local tailscaled" / "is Tailscale running?" → daemon-down
 *  - BackendState NeedsLogin / NeedsMachineAuth → logged-out
 *  - BackendState Stopped (tailscale down)      → stopped
 *  - NoState / Starting                         → starting
 *  - Running                                    → running
 */
export function classifyTailscale(input: { bin: string | null; status: CliResult | null; ip4?: CliResult | null }): TailscaleDetect {
  const base: TailscaleDetect = { state: 'not-installed', bin: input.bin, backendState: null, dnsName: null, ips: [], account: null }

  if (!input.bin || !input.status || input.status.missing) {
    return { ...base, bin: null }
  }

  let json: {
    BackendState?: string
    Self?: { DNSName?: string; TailscaleIPs?: string[]; UserID?: number }
    User?: Record<string, { LoginName?: string }>
  } | null = null

  try {
    json = input.status.stdout.trim() ? JSON.parse(input.status.stdout) : null
  } catch {
    json = null
  }

  const ip4FromCli = (input.ip4?.code === 0 ? input.ip4.stdout : '')
    .split(/\s+/)
    .map(s => s.trim())
    .filter(isTailnetIpv4)

  if (!json || typeof json !== 'object') {
    const text = `${input.status.stderr}\n${input.status.stdout}`.toLowerCase()

    if (/tailscaled|is tailscale running|connection refused|no such file|cannot connect|failed to connect|not running/.test(text)) {
      return { ...base, state: 'daemon-down' }
    }

    // Some builds print nothing useful but `tailscale ip -4` still works.
    if (ip4FromCli.length) {
      return { ...base, state: 'running', ips: ip4FromCli }
    }

    return { ...base, state: 'daemon-down' }
  }

  const backend = typeof json.BackendState === 'string' ? json.BackendState : null
  const self = json.Self ?? {}
  const ips = [...new Set([...(self.TailscaleIPs ?? []).filter(isTailnetIpv4), ...ip4FromCli])]
  const dnsName = (self.DNSName ?? '').replace(/\.$/, '') || null
  const user = self.UserID !== undefined ? json.User?.[String(self.UserID)] : undefined
  const account = user?.LoginName || null

  const state: TailscaleState =
    backend === 'Running'
      ? 'running'
      : backend === 'NeedsLogin' || backend === 'NeedsMachineAuth'
        ? 'logged-out'
        : backend === 'Stopped'
          ? 'stopped'
          : backend === 'NoState' || backend === 'Starting'
            ? 'starting'
            : ips.length
              ? 'running'
              : 'daemon-down'

  return {
    ...base,
    state,
    backendState: backend,
    dnsName: state === 'running' ? dnsName : null,
    ips: state === 'running' ? ips : [],
    account: state === 'logged-out' ? null : account
  }
}

export interface DetectDeps {
  platform?: TailscalePlatform
  env?: NodeJS.ProcessEnv
  /** Run a CLI (never through a shell). */
  run?: (file: string, args: string[], timeoutMs: number) => Promise<CliResult>
  exists?: (p: string) => boolean
}

function defaultRun(file: string, args: string[], timeoutMs: number): Promise<CliResult> {
  return new Promise(resolve => {
    execFile(file, args, { timeout: timeoutMs, windowsHide: true, maxBuffer: 4 * 1024 * 1024 }, (err, stdout, stderr) => {
      const e = err as (NodeJS.ErrnoException & { code?: number | string }) | null

      resolve({
        code: e ? (typeof e.code === 'number' ? e.code : 1) : 0,
        stdout: String(stdout ?? ''),
        stderr: String(stderr ?? ''),
        missing: e?.code === 'ENOENT'
      })
    })
  })
}

/** Probe Tailscale on this PC (Linux, Windows, macOS), unprivileged. Never throws. */
export async function detectTailscale(deps: DetectDeps = {}): Promise<TailscaleDetect> {
  const platform = deps.platform ?? process.platform
  const run = deps.run ?? defaultRun
  const exists = deps.exists ?? ((p: string) => fs.existsSync(p))

  for (const bin of tailscaleBinaryCandidates(platform, deps.env)) {
    // Bare names go through PATH (execFile), absolute paths must exist first.
    if ((bin.includes('/') || bin.includes('\\')) && !exists(bin)) {
      continue
    }

    try {
      const status = await run(bin, ['status', '--json'], 4000)

      if (status.missing) {
        continue
      }

      const first = classifyTailscale({ bin, status })
      const ip4 = first.state === 'running' && first.ips.length === 0 ? await run(bin, ['ip', '-4'], 3000) : null

      return ip4 ? classifyTailscale({ bin, status, ip4 }) : first
    } catch {
      continue
    }
  }

  return classifyTailscale({ bin: null, status: null })
}

// ---- setup steps ------------------------------------------------------------

export interface TailscaleStep {
  title: string
  /** A command the user copies into a terminal (Copy button). */
  command?: string
  /** A page to open (download, sign in). */
  link?: { label: string; url: string }
  detail?: string
}

export const TAILSCALE_DOWNLOAD_URL = 'https://tailscale.com/download'
export const TAILSCALE_LINUX_INSTALL = 'curl -fsSL https://tailscale.com/install.sh | sh'
export const TAILSCALE_ARCH_INSTALL = 'sudo pacman -S tailscale && sudo systemctl enable --now tailscaled && sudo tailscale up'

/** /etc/os-release → "arch" for Arch and derivatives (Omarchy, EndeavourOS, Manjaro…), else the ID. */
export function linuxFamily(osRelease: string | null): 'arch' | 'other' {
  if (!osRelease) {
    return 'other'
  }

  const field = (key: string) => (new RegExp(`^${key}=("?)([^"\\n]*)\\1`, 'm').exec(osRelease)?.[2] ?? '').toLowerCase()
  const ids = `${field('ID')} ${field('ID_LIKE')}`.split(/\s+/)

  return ids.some(id => id === 'arch' || id === 'archarm' || id === 'manjaro' || id === 'endeavouros' || id === 'omarchy')
    ? 'arch'
    : 'other'
}

export function readOsRelease(readFile: (p: string) => string | null = p => {
  try {
    return fs.readFileSync(p, 'utf8')
  } catch {
    return null
  }
}): string | null {
  return readFile('/etc/os-release') ?? readFile('/usr/lib/os-release')
}

/**
 * What to do next on this OS for [state]. Commands verified against
 * tailscale.com/kb/1031/install-linux and the ArchWiki Tailscale page.
 */
export function tailscaleSetupSteps(
  state: TailscaleState,
  platform: TailscalePlatform,
  family: 'arch' | 'other' = 'other'
): TailscaleStep[] {
  if (state === 'running') {
    return []
  }

  const signIn: TailscaleStep = {
    title: 'Masuk dengan akun yang sama seperti di HP',
    detail: 'Pakai akun Tailscale (Google/Microsoft/GitHub) yang sama di HP dan PC.'
  }

  if (platform === 'win32' || platform === 'darwin') {
    const os = platform === 'win32' ? 'Windows' : 'macOS'

    if (state === 'not-installed') {
      return [
        { title: `Unduh Tailscale untuk ${os}`, link: { label: 'Buka tailscale.com/download', url: TAILSCALE_DOWNLOAD_URL } },
        { ...signIn, detail: `${signIn.detail} Setelah dipasang, buka Tailscale dari ${platform === 'win32' ? 'tray' : 'menu bar'} ▸ Log in.` },
        { title: 'Kembali ke sini dan tekan Periksa lagi' }
      ]
    }

    if (state === 'daemon-down') {
      return [
        { title: 'Buka aplikasi Tailscale', detail: `Tailscale terpasang tetapi belum berjalan. Jalankan dari ${platform === 'win32' ? 'menu Start' : 'Applications'}.` },
        { title: 'Tekan Periksa lagi' }
      ]
    }

    return [
      { ...signIn, detail: `${signIn.detail} Klik ikon Tailscale ▸ Log in / Connect.` },
      { title: 'Tekan Periksa lagi' }
    ]
  }

  // Linux
  if (state === 'not-installed') {
    return family === 'arch'
      ? [
          { title: 'Pasang dan nyalakan Tailscale (Arch/Omarchy)', command: TAILSCALE_ARCH_INSTALL, detail: 'Buka tautan yang muncul di terminal untuk masuk.' },
          signIn,
          { title: 'Kembali ke sini dan tekan Periksa lagi' }
        ]
      : [
          { title: 'Pasang Tailscale', command: TAILSCALE_LINUX_INSTALL },
          { title: 'Nyalakan dan masuk', command: 'sudo tailscale up', detail: 'Buka tautan yang muncul di terminal untuk masuk.' },
          signIn,
          { title: 'Kembali ke sini dan tekan Periksa lagi' }
        ]
  }

  if (state === 'daemon-down') {
    return [
      { title: 'Jalankan layanan Tailscale', command: 'sudo systemctl enable --now tailscaled' },
      { title: 'Nyalakan dan masuk', command: 'sudo tailscale up' },
      { title: 'Tekan Periksa lagi' }
    ]
  }

  return [
    {
      title: state === 'logged-out' ? 'Masuk ke Tailscale' : 'Nyalakan Tailscale',
      command: 'sudo tailscale up',
      detail: state === 'logged-out' ? 'Buka tautan yang muncul di terminal, pakai akun yang sama seperti di HP.' : undefined
    },
    { title: 'Tekan Periksa lagi' }
  ]
}

export const TAILSCALE_STATE_LABEL: Record<TailscaleState, string> = {
  'not-installed': 'Belum terpasang',
  'daemon-down': 'Terpasang, layanan belum berjalan',
  'logged-out': 'Belum masuk',
  stopped: 'Mati (tailscale down)',
  starting: 'Sedang menyambung…',
  running: 'Tersambung'
}
