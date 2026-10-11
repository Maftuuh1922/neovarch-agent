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
 *
 * v1.4.7 (root cause of "HP tidak bisa terhubung lewat Wi-Fi yang sama"):
 *  - Windows marks every new Wi-Fi as "Publik". The old rule only covered
 *    private/domain, so on a fresh network it never applied. The rule now
 *    covers every profile but only accepts the local subnet and the Tailscale
 *    range (100.64.0.0/10); the gateway itself still requires a token.
 *  - Dismissing Windows' first "allow access?" prompt for python.exe creates
 *    inbound BLOCK rules for that program, and a block rule beats any allow
 *    rule. The elevated step removes those block rules for the gateway's own
 *    Python, and the check treats their presence as "rule missing".
 */
import { execFile } from 'node:child_process'

export const FIREWALL_RULE_PREFIX = 'Neovarch Agent (HP remote)'

/** Remote addresses allowed in: same network, plus Tailscale's CGNAT range. */
export const FIREWALL_REMOTE_IP = 'localsubnet,100.64.0.0/10'

/** v2: all profiles (new Wi-Fi is "Publik" by default) limited to the local subnet + tailnet. */
export function firewallRuleName(port: number): string {
  return `${FIREWALL_RULE_PREFIX} TCP ${port} v2`
}

/** The v1.4.6 rule (private/domain only), removed when the v2 rule is added. */
export function legacyFirewallRuleName(port: number): string {
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
    'profile=any',
    `remoteip=${FIREWALL_REMOTE_IP}`,
    'description=Izinkan aplikasi HP Neovarch Agent terhubung ke PC ini lewat Wi-Fi atau Tailscale.'
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

function psQuote(v: string): string {
  return `'${v.replace(/'/g, "''")}'`
}

/**
 * PowerShell (run elevated) that removes inbound block rules Windows created for
 * the gateway's Python when its first prompt was dismissed, drops the old v1
 * rule and adds the v2 allow rule.
 */
export function elevatedScript(port: number, program?: string | null): string {
  const lines = [
    "$ErrorActionPreference = 'SilentlyContinue'"
  ]

  if (program) {
    lines.push(
      `Get-NetFirewallApplicationFilter -Program ${psQuote(program)} | Get-NetFirewallRule | ` +
        "Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule"
    )
  }

  lines.push(`netsh advfirewall firewall delete rule name=${psQuote(legacyFirewallRuleName(port))} | Out-Null`)
  lines.push(`& netsh ${addRuleArgs(port).map(psQuote).join(' ')} | Out-Null`)
  lines.push('exit $LASTEXITCODE')

  return lines.join('; ')
}

/** PowerShell that runs the fix elevated (one UAC prompt) and waits for it. */
export function elevatedPowerShellArgs(port: number, program?: string | null): string[] {
  const encoded = Buffer.from(elevatedScript(port, program), 'utf16le').toString('base64')

  return [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    `$p = Start-Process -FilePath powershell.exe -ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','${encoded}' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode`
  ]
}

/** Non-elevated check: exit 0 only when the v2 rule exists and no inbound block rule targets the gateway's Python. */
export function checkPowerShellArgs(port: number, program?: string | null): string[] {
  const parts = [
    `$r = Get-NetFirewallRule -DisplayName ${psQuote(firewallRuleName(port))} -ErrorAction SilentlyContinue`,
    'if (-not $r) { exit 1 }'
  ]

  if (program) {
    parts.push(
      `$b = Get-NetFirewallApplicationFilter -Program ${psQuote(program)} -ErrorAction SilentlyContinue | Get-NetFirewallRule | ` +
        "Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' -and $_.Enabled -eq 'True' }",
      'if ($b) { exit 2 }'
    )
  }

  parts.push('exit 0')

  return ['-NoProfile', '-NonInteractive', '-Command', parts.join('; ')]
}

export function firewallHelp(port: number): string {
  return (
    `Windows Firewall kemungkinan memblokir HP. Izinkan port ${port}: ` +
    `buka Terminal (Administrator) lalu jalankan: ${manualCommand(port)} ` +
    '— lalu di Windows Security › Firewall › Izinkan aplikasi, pastikan Python/Neovarch tidak diblokir.'
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
  opts: { platform?: NodeJS.Platform; run?: Run; prompt?: boolean; program?: string | null } = {}
): Promise<FirewallResult> {
  const platform = opts.platform ?? process.platform

  if (platform !== 'win32') {
    return 'not-windows'
  }

  const exec = opts.run ?? run
  const program = opts.program && /\.exe$/i.test(opts.program) ? opts.program : null

  if ((await exec('powershell.exe', checkPowerShellArgs(port, program), 15_000)) === 0) {
    return 'exists'
  }

  if (opts.prompt === false) {
    return 'declined'
  }

  const code = await exec('powershell.exe', elevatedPowerShellArgs(port, program), 120_000)

  if (code === 0 && (await exec('powershell.exe', checkPowerShellArgs(port, program), 15_000)) === 0) {
    return 'added'
  }

  return 'declined'
}

/** Linux: the phone is dropped when ufw/firewalld is active and the port is closed. */
export function linuxFirewallHelp(port: number): string {
  return (
    `Jika firewall Linux aktif, buka port ${port}: ` +
    `sudo ufw allow ${port}/tcp  (ufw)  atau  sudo firewall-cmd --add-port=${port}/tcp --permanent && sudo firewall-cmd --reload  (firewalld).`
  )
}
