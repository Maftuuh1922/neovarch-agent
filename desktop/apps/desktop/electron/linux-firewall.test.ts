import { describe, expect, it } from 'vitest'

import {
  detectLinuxFirewall,
  ensureLinuxFirewallRule,
  linuxFirewallBlockHelp,
  linuxFirewallScript,
  linuxManualCommand,
  PRIVATE_CIDRS,
  ufwEnabledFromConf
} from './linux-firewall'

type Call = { file: string; args: string[] }

function fakeRun(codes: Record<string, number>) {
  const calls: Call[] = []

  const run = async (file: string, args: string[]) => {
    calls.push({ file, args })
    const key = `${file} ${args.join(' ')}`
    const hit = Object.keys(codes).find(k => key.startsWith(k))

    return hit === undefined ? 3 : codes[hit]
  }

  return { run, calls }
}

// Omarchy's /etc/ufw/ufw.conf after install/config/firewall.sh
const OMARCHY_UFW_CONF = '# /etc/ufw/ufw.conf\n#\n\n# Set to yes to start on boot.\nENABLED=yes\n\nLOGLEVEL=low\n'

describe('linux firewall for the LAN gateway', () => {
  it('reads ENABLED=yes from ufw.conf', () => {
    expect(ufwEnabledFromConf(OMARCHY_UFW_CONF)).toBe(true)
    expect(ufwEnabledFromConf('ENABLED=no\n')).toBe(false)
    expect(ufwEnabledFromConf(null)).toBe(false)
  })

  it('detects ufw (Omarchy default) without root', async () => {
    const { run } = fakeRun({ 'systemctl is-active --quiet ufw': 0 })

    expect(await detectLinuxFirewall({ run, readFile: () => OMARCHY_UFW_CONF })).toBe('ufw')
  })

  it('detects firewalld, and none when nothing is active', async () => {
    const fw = fakeRun({ 'systemctl is-active --quiet firewalld': 0 })

    expect(await detectLinuxFirewall({ run: fw.run, readFile: () => null })).toBe('firewalld')

    const none = fakeRun({})

    expect(await detectLinuxFirewall({ run: none.run, readFile: () => 'ENABLED=no' })).toBe('none')
  })

  it('opens the port only for private LAN ranges, never to everyone', () => {
    const ufw = linuxFirewallScript('ufw', 9319)

    for (const c of PRIVATE_CIDRS) {
      expect(ufw).toContain(`from ${c} to any port 9319`)
    }

    expect(ufw).not.toMatch(/ufw allow 9319/)
    expect(ufw).not.toContain('0.0.0.0/0')

    const fwd = linuxFirewallScript('firewalld', 9319)

    expect(fwd).toContain('source address="192.168.0.0/16" port port="9319" protocol="tcp" accept')
    expect(fwd).toContain('firewall-cmd --reload')
    expect(fwd).not.toContain('--add-port')
    expect(() => linuxFirewallScript('ufw', 0)).toThrow()
    expect(linuxManualCommand('ufw', 9319).split(' && ').every(c => c.startsWith('sudo ufw allow'))).toBe(true)
  })

  it('asks once through pkexec and reports added / declined', async () => {
    const ok = fakeRun({ pkexec: 0 })
    const added = await ensureLinuxFirewallRule(9319, { platform: 'linux', run: ok.run, kind: 'ufw' })

    expect(added).toEqual({ result: 'added', kind: 'ufw' })
    expect(ok.calls).toHaveLength(1)
    expect(ok.calls[0].file).toBe('pkexec')
    expect(ok.calls[0].args.slice(0, 2)).toEqual(['/bin/sh', '-c'])

    // 126: the polkit prompt was dismissed
    const no = fakeRun({ pkexec: 126 })

    expect((await ensureLinuxFirewallRule(9319, { platform: 'linux', run: no.run, kind: 'ufw' })).result).toBe('declined')
  })

  it('does nothing when no firewall is active or not on Linux', async () => {
    const none = fakeRun({})

    expect((await ensureLinuxFirewallRule(9319, { platform: 'linux', run: none.run, readFile: () => null })).result).toBe('none')
    expect(none.calls.some(c => c.file === 'pkexec')).toBe(false)
    expect((await ensureLinuxFirewallRule(9319, { platform: 'win32' })).result).toBe('not-linux')
  })

  it('explains why Tailscale works and LAN does not', () => {
    const help = linuxFirewallBlockHelp('ufw', 9319)

    expect(help).toContain('tailscale0')
    expect(help).toContain('sudo ufw allow in proto tcp from 192.168.0.0/16 to any port 9319')
    expect(linuxFirewallBlockHelp('none', 9319)).toContain('isolation')
  })
})
