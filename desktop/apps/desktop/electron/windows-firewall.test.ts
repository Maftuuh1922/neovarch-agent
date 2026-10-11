import { describe, expect, it } from 'vitest'

import {
  addRuleArgs,
  elevatedPowerShellArgs,
  ensureFirewallRule,
  firewallHelp,
  firewallRuleName,
  manualCommand
} from './windows-firewall'

describe('windows firewall rule for the LAN gateway', () => {
  it('builds an inbound TCP allow rule for the port on private networks', () => {
    const args = addRuleArgs(9319)

    expect(args).toContain('dir=in')
    expect(args).toContain('action=allow')
    expect(args).toContain('localport=9319')
    expect(args).toContain('profile=private,domain')
    expect(args).toContain(`name=${firewallRuleName(9319)}`)
  })

  it('elevates through one UAC prompt', () => {
    const ps = elevatedPowerShellArgs(9319).join(' ')

    expect(ps).toContain('-Verb RunAs')
    expect(ps).toContain("'localport=9319'")
  })

  it('explains the manual fix in Indonesian', () => {
    expect(manualCommand(9319)).toMatch(/^netsh advfirewall firewall add rule name="Neovarch Agent \(HP remote\) TCP 9319" dir=in/)
    expect(firewallHelp(9319)).toContain('Pribadi')
  })

  it('does nothing off Windows', async () => {
    expect(await ensureFirewallRule(9319, { platform: 'linux', run: async () => 1 })).toBe('not-windows')
  })

  it('keeps an existing rule and adds a missing one', async () => {
    const calls: string[] = []

    expect(await ensureFirewallRule(9319, { platform: 'win32', run: async f => (calls.push(f), 0) })).toBe('exists')
    expect(calls).toEqual(['netsh'])

    let added = false
    const run = async (file: string) => {
      if (file === 'powershell.exe') {
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
