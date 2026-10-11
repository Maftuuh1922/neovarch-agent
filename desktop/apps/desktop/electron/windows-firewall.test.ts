import { describe, expect, it } from 'vitest'

import {
  addRuleArgs,
  checkPowerShellArgs,
  elevatedScript,
  legacyFirewallRuleName,
  linuxFirewallHelp,
  elevatedPowerShellArgs,
  ensureFirewallRule,
  firewallHelp,
  firewallRuleName,
  manualCommand
} from './windows-firewall'

describe('windows firewall rule for the LAN gateway', () => {
  it('builds an inbound TCP allow rule on every profile, limited to the local subnet and tailnet', () => {
    const args = addRuleArgs(9319)

    expect(args).toContain('dir=in')
    expect(args).toContain('action=allow')
    expect(args).toContain('localport=9319')
    // New Wi-Fi networks are "Publik" on Windows: a private-only rule never applied there.
    expect(args).toContain('profile=any')
    expect(args).toContain('remoteip=localsubnet,100.64.0.0/10')
    expect(args).toContain(`name=${firewallRuleName(9319)}`)
    expect(firewallRuleName(9319)).not.toBe(legacyFirewallRuleName(9319))
  })

  it('elevates through one UAC prompt and removes block rules for the gateway python', () => {
    const ps = elevatedPowerShellArgs(9319, 'C:\\Py\\python.exe').join(' ')

    expect(ps).toContain('-Verb RunAs')
    expect(ps).toContain('-EncodedCommand')
    const script = elevatedScript(9319, 'C:\\Py\\python.exe')

    expect(script).toContain("Get-NetFirewallApplicationFilter -Program 'C:\\Py\\python.exe'")
    expect(script).toContain("$_.Action -eq 'Block'")
    expect(script).toContain('Remove-NetFirewallRule')
    expect(script).toContain(`delete rule name='${legacyFirewallRuleName(9319)}'`)
    expect(script).toContain("'localport=9319'")
    expect(elevatedScript(9319)).not.toContain('Get-NetFirewallApplicationFilter')
  })

  it('treats a block rule for the gateway python as a missing rule', () => {
    const check = checkPowerShellArgs(9319, 'C:\\Py\\python.exe').join(' ')

    expect(check).toContain(firewallRuleName(9319))
    expect(check).toContain('exit 2')
  })

  it('explains the manual fix in Indonesian', () => {
    expect(manualCommand(9319)).toMatch(/^netsh advfirewall firewall add rule name="Neovarch Agent \(HP remote\) TCP 9319 v2" dir=in/)
    expect(firewallHelp(9319)).toContain('diblokir')
    expect(linuxFirewallHelp(9319)).toContain('ufw allow 9319/tcp')
  })

  it('does nothing off Windows', async () => {
    expect(await ensureFirewallRule(9319, { platform: 'linux', run: async () => 1 })).toBe('not-windows')
  })

  it('keeps an existing rule and adds a missing one', async () => {
    const calls: string[] = []

    expect(await ensureFirewallRule(9319, { platform: 'win32', run: async f => (calls.push(f), 0) })).toBe('exists')
    expect(calls).toEqual(['powershell.exe'])

    let added = false
    const run = async (_file: string, args: string[]) => {
      if (args.join(' ').includes('-Verb RunAs')) {
        added = true

        return 0
      }

      return added ? 0 : 1
    }

    expect(await ensureFirewallRule(9319, { platform: 'win32', run })).toBe('added')
    expect(await ensureFirewallRule(9320, { platform: 'win32', run: async () => 1 })).toBe('declined')
    expect(await ensureFirewallRule(9321, { platform: 'win32', prompt: false, run: async () => 1 })).toBe('declined')
  })
})
