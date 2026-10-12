import { describe, expect, it } from 'vitest'

import {
  classifyTailscale,
  type CliResult,
  detectTailscale,
  isTailnetIpv4,
  linuxFamily,
  TAILSCALE_ARCH_INSTALL,
  TAILSCALE_DOWNLOAD_URL,
  TAILSCALE_LINUX_INSTALL,
  tailscaleBinaryCandidates,
  tailscaleSetupSteps
} from './tailscale-detect'

const ok = (stdout: string): CliResult => ({ code: 0, stdout, stderr: '' })

const RUNNING = JSON.stringify({
  BackendState: 'Running',
  Self: { DNSName: 'pc-kantor.tail1234.ts.net.', TailscaleIPs: ['100.84.12.7', 'fd7a:115c:a1e0::1'], UserID: 7 },
  User: { '7': { LoginName: 'andi@example.com' } }
})

describe('classifyTailscale', () => {
  it('no binary → not-installed', () => {
    expect(classifyTailscale({ bin: null, status: null }).state).toBe('not-installed')
    expect(classifyTailscale({ bin: 'tailscale', status: { code: null, stdout: '', stderr: '', missing: true } }).state).toBe(
      'not-installed'
    )
  })

  it('daemon not running → daemon-down', () => {
    const r = classifyTailscale({
      bin: 'tailscale',
      status: { code: 1, stdout: '', stderr: 'failed to connect to local tailscaled; it doesn’t appear to be running' }
    })

    expect(r.state).toBe('daemon-down')
    expect(r.ips).toEqual([])
  })

  it('NeedsLogin → logged-out, Stopped → stopped, Starting → starting', () => {
    expect(classifyTailscale({ bin: 'tailscale', status: ok('{"BackendState":"NeedsLogin","Self":{}}') }).state).toBe('logged-out')
    expect(classifyTailscale({ bin: 'tailscale', status: ok('{"BackendState":"Stopped","Self":{"TailscaleIPs":["100.84.12.7"]}}') })).toMatchObject({
      state: 'stopped',
      ips: []
    })
    expect(classifyTailscale({ bin: 'tailscale', status: ok('{"BackendState":"Starting"}') }).state).toBe('starting')
  })

  it('Running → MagicDNS without the trailing dot, IPv4 tailnet IPs, account', () => {
    expect(classifyTailscale({ bin: 'tailscale', status: ok(RUNNING) })).toEqual({
      state: 'running',
      bin: 'tailscale',
      backendState: 'Running',
      dnsName: 'pc-kantor.tail1234.ts.net',
      ips: ['100.84.12.7'],
      account: 'andi@example.com'
    })
  })

  it('falls back to `tailscale ip -4`', () => {
    const r = classifyTailscale({
      bin: 'tailscale',
      status: ok('{"BackendState":"Running","Self":{"DNSName":"pc.ts.net."}}'),
      ip4: ok('100.101.1.2\n')
    })

    expect(r.ips).toEqual(['100.101.1.2'])
  })
})

describe('detectTailscale', () => {
  it('tries PATH, then the GUI install path on Windows', async () => {
    const calls: string[] = []

    const d = await detectTailscale({
      platform: 'win32',
      env: { ProgramFiles: 'C:\\Program Files' },
      exists: p => p === 'C:\\Program Files\\Tailscale\\tailscale.exe',
      run: async (file, args) => {
        calls.push(`${file} ${args.join(' ')}`)

        return file === 'tailscale.exe' ? { code: null, stdout: '', stderr: '', missing: true } : ok(RUNNING)
      }
    })

    expect(d.state).toBe('running')
    expect(d.bin).toBe('C:\\Program Files\\Tailscale\\tailscale.exe')
    expect(calls[0]).toBe('tailscale.exe status --json')
  })

  it('nothing found → not-installed (never throws)', async () => {
    const d = await detectTailscale({
      platform: 'linux',
      exists: () => false,
      run: async () => ({ code: null, stdout: '', stderr: '', missing: true })
    })

    expect(d.state).toBe('not-installed')
  })

  it('only runs status/ip, never sudo', async () => {
    const seen: string[][] = []

    await detectTailscale({
      platform: 'linux',
      exists: () => true,
      run: async (file, args) => {
        seen.push([file, ...args])

        return ok('{"BackendState":"Running","Self":{}}')
      }
    })

    expect(seen.every(c => !c.includes('sudo') && (c[1] === 'status' || c[1] === 'ip'))).toBe(true)
  })
})

describe('setup steps', () => {
  it('Linux: official install script then sudo tailscale up', () => {
    const steps = tailscaleSetupSteps('not-installed', 'linux', 'other')

    expect(steps[0]!.command).toBe('curl -fsSL https://tailscale.com/install.sh | sh')
    expect(steps[1]!.command).toBe('sudo tailscale up')
    expect(TAILSCALE_LINUX_INSTALL).toBe(steps[0]!.command)
  })

  it('Arch / Omarchy: pacman + systemd + up in one command', () => {
    const steps = tailscaleSetupSteps('not-installed', 'linux', 'arch')

    expect(steps[0]!.command).toBe(TAILSCALE_ARCH_INSTALL)
    expect(TAILSCALE_ARCH_INSTALL).toBe('sudo pacman -S tailscale && sudo systemctl enable --now tailscaled && sudo tailscale up')
  })

  it('Windows / macOS: download link', () => {
    for (const p of ['win32', 'darwin']) {
      const steps = tailscaleSetupSteps('not-installed', p)

      expect(steps[0]!.link?.url).toBe(TAILSCALE_DOWNLOAD_URL)
      expect(steps.some(s => s.command)).toBe(false)
    }
  })

  it('daemon down / logged out / running', () => {
    expect(tailscaleSetupSteps('daemon-down', 'linux')[0]!.command).toBe('sudo systemctl enable --now tailscaled')
    expect(tailscaleSetupSteps('logged-out', 'linux')[0]!.command).toBe('sudo tailscale up')
    expect(tailscaleSetupSteps('running', 'linux')).toEqual([])
  })

  it('linuxFamily reads /etc/os-release', () => {
    expect(linuxFamily('NAME="Arch Linux"\nID=arch\n')).toBe('arch')
    expect(linuxFamily('ID=endeavouros\nID_LIKE=arch\n')).toBe('arch')
    expect(linuxFamily('ID=ubuntu\nID_LIKE=debian\n')).toBe('other')
    expect(linuxFamily(null)).toBe('other')
  })

  it('binary candidates per OS', () => {
    expect(tailscaleBinaryCandidates('darwin')).toContain('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
    expect(tailscaleBinaryCandidates('linux')[0]).toBe('tailscale')
  })

  it('isTailnetIpv4', () => {
    expect(isTailnetIpv4('100.64.0.1')).toBe(true)
    expect(isTailnetIpv4('100.127.255.1')).toBe(true)
    expect(isTailnetIpv4('100.128.0.1')).toBe(false)
    expect(isTailnetIpv4('192.168.1.5')).toBe(false)
  })
})
