/**
 * Windows Defender Firewall rule for the phone's LAN gateway.
 *
 * On Windows, the first time Python listens on 0.0.0.0 the firewall asks
 * "allow access?". If that prompt was dismissed, or the Wi-Fi is marked
 * "Public", every connection from the phone is dropped silently. The
 * desktop's own "Periksa" probe still passes, because it connects from the PC
 * itself, so the user sees "connected" on the PC and "cannot reach" on the
 * phone. This module adds one inbound TCP rule for the gateway port, once,
 * through a UAC prompt, and explains in Indonesian when that is not possible.
 */
import { execFile } from 'node:child_process'

export const FIREWALL_RULE_PREFIX = 'Neovarch Agent (HP remote)'

export function firewallRuleName(port: number): string {
  return `${FIREWALL_RULE_PREFIX} TCP ${port}`
}

/** netsh arguments that show the rule (exit code 0 = it exists). */
export function showRuleArgs(port: number): string[] {
  return ['advfirewall', 'firewall', 'show', 'rule', `name=${firewallRuleName(port)}`]
}

/** netsh arguments that add the inbound allow rule for the gateway port (private + domain networks). */
export function addRuleArgs(port: number): string[] {
  return [
    'advfirewall',
    'firewall',
    'add',
    'rule',
    `name=${firewallRuleName(port)}`,
    'dir=in',
    'action=allow',
    'protocol=TCP',
    `localport=${port}`,
    'profile=private,domain',
    'description=Izinkan aplikasi HP Neovarch Agent terhubung ke PC ini lewat Wi-Fi.'
  ]
}

/** The same command for a person to paste into an Administrator terminal. */
export function manualCommand(port: number): string {
  const quoted = addRuleArgs(port).map(a => {
    const eq = a.indexOf('=')

    return a.includes(' ') && eq > 0 ? `${a.slice(0, eq + 1)}"${a.slice(eq + 1)}"` : a
  })

  return `netsh ${quoted.join(' ')}`
}

/** PowerShell that runs netsh elevated (one UAC prompt) and waits for it. */
export function elevatedPowerShellArgs(port: number): string[] {
  const list = addRuleArgs(port)
    .map(a => `'${a.replace(/'/g, "''")}'`)
    .join(',')

  return [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    `$p = Start-Process -FilePath netsh -ArgumentList ${list} -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode`
  ]
}

export function firewallHelp(port: number): string {
  return (
    `Windows Firewall kemungkinan memblokir HP. Izinkan port ${port} untuk jaringan Pribadi: ` +
    `buka Terminal (Administrator) lalu jalankan: ${manualCommand(port)} ` +
    '— dan pastikan Wi-Fi PC disetel sebagai jaringan "Pribadi", bukan "Publik".'
  )
}

type Run = (file: string, args: string[], timeoutMs: number) => Promise<number>

const run: Run = (file, args, timeoutMs) =>
  new Promise(resolve => {
    execFile(file, args, { timeout: timeoutMs, windowsHide: true }, err => {
      resolve(err ? (typeof (err as { code?: unknown }).code === 'number' ? (err as { code: number }).code : 1) : 0)
    })
  })

export type FirewallResult = 'not-windows' | 'exists' | 'added' | 'declined'

/**
 * Make sure the inbound rule exists. Asks for elevation (UAC) at most once per
 * call; the caller remembers a decline so the prompt does not come back on
 * every start.
 */
export async function ensureFirewallRule(
  port: number,
  opts: { platform?: NodeJS.Platform; run?: Run; prompt?: boolean } = {}
): Promise<FirewallResult> {
  const platform = opts.platform ?? process.platform

  if (platform !== 'win32') {
    return 'not-windows'
  }

  const exec = opts.run ?? run

  if ((await exec('netsh', showRuleArgs(port), 10_000)) === 0) {
    return 'exists'
  }

  if (opts.prompt === false) {
    return 'declined'
  }

  const code = await exec('powershell.exe', elevatedPowerShellArgs(port), 120_000)

  if (code === 0 && (await exec('netsh', showRuleArgs(port), 10_000)) === 0) {
    return 'added'
  }

  return 'declined'
}
