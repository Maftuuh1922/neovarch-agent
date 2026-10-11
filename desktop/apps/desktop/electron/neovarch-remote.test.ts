import { describe, expect, it } from 'vitest'

import {
  buildPairingUri,
  decodeSecret,
  FALLBACK_DEVICE_NAME,
  fallbackUrls,
  isTailnetIp,
  lanAddresses,
  mintAccessToken,
  parseTailscaleStatus,
  resolveDeviceName,
  verifyAccessToken
} from './neovarch-remote'

// Vector produced by the Hermes core's own signer (plugins/dashboard_auth/basic `_sign`):
// urlsafe_b64encode(json.dumps(payload, separators=(",", ":")) + hmac_sha256(secret, json)).
const SECRET = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='
const PY_TOKEN =
  'eyJzdWIiOiJuZW92YXJjaC1yZW1vdGUiLCJraW5kIjoiYWNjZXNzIiwiZXhwIjoxOTE3NjgwMDAwfV4rLKqa3Agh4LhUO4M7pCZO1lOGjoLnckp9jymhQhUh'

describe('neovarch remote token', () => {
  it('matches the core basic-auth signer byte for byte', () => {
    expect(mintAccessToken(decodeSecret(SECRET), 1760000000)).toBe(PY_TOKEN)
  })

  it('verifies its own tokens and rejects a rotated secret', () => {
    const token = mintAccessToken(decodeSecret(SECRET), 1760000000)
    expect(verifyAccessToken(token, decodeSecret(SECRET), 1760000001)).toBe(true)
    expect(verifyAccessToken(token, Buffer.alloc(32, 7), 1760000001)).toBe(false)
  })

  it('builds the phone pairing URI', () => {
    const uri = buildPairingUri({ url: 'http://192.168.1.5:9119', token: 'abc=', name: 'PC Kantor', profile: 'default' })
    const q = new URL(uri.replace('neovarch://', 'http://x/')).searchParams
    expect(uri.startsWith('neovarch://pair?v=1&')).toBe(true)
    expect(q.get('url')).toBe('http://192.168.1.5:9119')
    expect(q.get('token')).toBe('abc=')
    expect(q.get('name')).toBe('PC Kantor')
    expect(q.get('profile')).toBe('default')
  })

  it('prefers real LAN interfaces over virtual ones', () => {
    const list = lanAddresses({
      docker0: [{ address: '172.17.0.1', family: 'IPv4', internal: false } as never],
      lo: [{ address: '127.0.0.1', family: 'IPv4', internal: true } as never],
      wlan0: [{ address: '192.168.1.5', family: 'IPv4', internal: false } as never]
    })
    expect(list.map(a => a.address)).toEqual(['192.168.1.5', '172.17.0.1'])
  })

  it('skips Windows virtual adapters (Hyper-V/WSL, VirtualBox, VMware, Bluetooth) for the QR', () => {
    const v4 = (address: string) => [{ address, family: 'IPv4', internal: false } as never]
    const list = lanAddresses({
      'VirtualBox Host-Only Network': v4('192.168.56.1'),
      'vEthernet (WSL)': v4('172.28.144.1'),
      'vEthernet (Default Switch)': v4('172.20.0.1'),
      'VMware Network Adapter VMnet8': v4('192.168.137.1'),
      'Bluetooth Network Connection': v4('192.168.44.1'),
      'Local Area Connection': v4('10.0.0.7'),
      'Wi-Fi': v4('192.168.1.23')
    })
    expect(list[0]).toEqual({ address: '192.168.1.23', iface: 'Wi-Fi', kind: 'lan' })
    expect(list[1]?.address).toBe('10.0.0.7')
  })

  it('falls back to a readable PC name when the hostname is empty or "(none)"', () => {
    expect(resolveDeviceName('')).toBe(FALLBACK_DEVICE_NAME)
    expect(resolveDeviceName('  ')).toBe(FALLBACK_DEVICE_NAME)
    expect(resolveDeviceName('(none)')).toBe(FALLBACK_DEVICE_NAME)
    expect(resolveDeviceName(' workstation ')).toBe('workstation')
    expect(FALLBACK_DEVICE_NAME).toBe('PC Neovarch')
  })

  it('adds Tailscale fallbacks (MagicDNS, then tailnet IP) to the pairing URI', () => {
    expect(isTailnetIp('100.64.0.1')).toBe(true)
    expect(isTailnetIp('100.127.255.1')).toBe(true)
    expect(isTailnetIp('100.128.0.1')).toBe(false)
    expect(isTailnetIp('192.168.1.5')).toBe(false)
    const ts = parseTailscaleStatus(
      JSON.stringify({ Self: { DNSName: 'pc-kantor.tail1234.ts.net.', TailscaleIPs: ['100.84.12.7', 'fd7a:115c::1'] } })
    )
    expect(ts).toEqual({ dnsName: 'pc-kantor.tail1234.ts.net', ips: ['100.84.12.7'] })
    expect(parseTailscaleStatus('not json')).toBeNull()
    const addresses = lanAddresses({
      wlan0: [{ address: '192.168.1.5', family: 'IPv4', internal: false } as never],
      eth0: [{ address: '10.0.0.7', family: 'IPv4', internal: false } as never],
      tailscale0: [{ address: '100.84.12.7', family: 'IPv4', internal: false } as never],
      docker0: [{ address: '172.17.0.1', family: 'IPv4', internal: false } as never]
    })
    expect(addresses.find(a => a.address === '100.84.12.7')?.kind).toBe('tailscale')
    const alt = fallbackUrls({ primary: '192.168.1.5', addresses, tailscale: ts, port: 9319 })
    expect(alt).toEqual(['http://10.0.0.7:9319', 'http://pc-kantor.tail1234.ts.net:9319', 'http://100.84.12.7:9319'])
    const uri = buildPairingUri({ url: 'http://192.168.1.5:9319', token: 't', name: 'PC', profile: null, alt })
    const q = new URL(uri.replace('neovarch://', 'http://x/')).searchParams
    expect(q.get('url')).toBe('http://192.168.1.5:9319')
    expect(q.getAll('alt')).toEqual(alt)
    expect(q.get('token')).toBe('t')
  })
})
