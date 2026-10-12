import { useEffect, useState } from 'react'

import remotePairingArt from '@/assets/neovarch/remote-pairing.webp'
import { HaloMark } from '@/components/neovarch/halo-mark'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { Input } from '@/components/ui/input'
import { QrCode, RefreshCw } from '@/lib/icons'
import { confirm } from '@/store/confirm'

import { ListRow, SectionHeading, SettingsContent, ToggleRow } from './primitives'

// Settings ▸ Remote / Perangkat — pair the Neovarch phone app with this PC.
// The main process (electron/neovarch-remote.ts) runs a LAN-bound, auth-gated
// `neovarch serve` on port 9319 and mints the phone's token; this page shows the
// pairing QR (neovarch://pair?v=1&url=…&token=…&name=…&profile=…).

const CAPTION = 'text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)'
const MONO = 'font-mono text-[0.6875rem] leading-4 break-all text-(--ui-text-secondary)'

// Shown only outside Electron (renderer preview / screenshots), clearly labelled.
const PREVIEW_STATUS: NeovarchRemoteStatus = {
  enabled: true,
  running: true,
  starting: false,
  port: 9319,
  addresses: [
    { address: '192.168.1.5', iface: 'wlan0' },
    { address: '100.84.12.7', iface: 'tailscale0', kind: 'tailscale' }
  ],
  altUrls: ['http://pc-kantor.tail1234.ts.net:9319', 'http://100.84.12.7:9319'],
  tailscale: { dnsName: 'pc-kantor.tail1234.ts.net', ips: ['100.84.12.7'] },
  address: '192.168.1.5',
  url: 'http://192.168.1.5:9319',
  token: 'eyJzdWIiOiJuZW92YXJjaC1yZW1vdGUiLCJraW5kIjoiYWNjZXNzIiwiZXhwIjoxOTE3NjgwMDAwfdcg06aPZhiOLEAVRMba-pi23576xtM_tVRtdvf8-eZL',
  pairingUri:
    'neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.5%3A9319&token=eyJzdWIiOiJuZW92YXJjaC1yZW1vdGUiLCJraW5kIjoiYWNjZXNzIiwiZXhwIjoxOTE3NjgwMDAwfdcg06aPZhiOLEAVRMba-pi23576xtM_tVRtdvf8-eZL&name=PC+Kantor&profile=default',
  deviceName: 'PC Kantor',
  profile: 'default',
  error: null,
  logTail: '',
  relay: {
    enabled: true,
    url: 'wss://relay.neovarchlabs.web.id',
    defaultUrl: 'wss://relay.neovarchlabs.web.id',
    state: 'online',
    error: null,
    phones: 1
  },
  bluetooth: { enabled: false, state: 'off', error: null, address: null, phones: 0 },
  devices: [
    {
      id: 'q3Jm0xA1bC2dE3fG',
      name: 'HP Andi',
      added: 1791000000,
      created_at: 1791000000,
      last_seen: 1791480000,
      expires_at: 1791480000 + 30 * 86400,
      via: 'relay'
    }
  ]
}

async function renderQr(payload: string): Promise<string> {
  const QRCode = await import('qrcode')

  return QRCode.toDataURL(payload, {
    errorCorrectionLevel: 'M',
    margin: 2,
    width: 232,
    color: { dark: '#0d0606', light: '#f4f2ed' }
  })
}

export function RemoteSettings() {
  const api = window.hermesDesktop?.neovarchRemote
  const preview = !api
  const [status, setStatus] = useState<NeovarchRemoteStatus | null>(preview ? PREVIEW_STATUS : null)
  const [qr, setQr] = useState('')
  const [busy, setBusy] = useState(false)
  const [check, setCheck] = useState<{ ok: boolean; message: string } | null>(null)
  const [name, setName] = useState('')

  useEffect(() => {
    if (!api) {
      return
    }

    let alive = true
    void api.get().then(s => alive && setStatus(s))
    const off = api.onChanged(s => setStatus(s))

    return () => {
      alive = false
      off()
    }
  }, [api])

  useEffect(() => setName(status?.deviceName ?? ''), [status?.deviceName])

  useEffect(() => {
    let alive = true

    if (status?.pairingUri) {
      void renderQr(status.pairingUri).then(url => alive && setQr(url))
    } else {
      setQr('')
    }

    return () => {
      alive = false
    }
  }, [status?.pairingUri])

  const run = async (fn: () => Promise<NeovarchRemoteStatus>) => {
    setBusy(true)
    setCheck(null)

    try {
      setStatus(await fn())
    } finally {
      setBusy(false)
    }
  }

  const rotate = async () => {
    const ok = await confirm({
      title: 'Buat token baru?',
      description: 'Semua HP yang sudah dipasangkan akan terputus dan harus memindai QR baru.',
      confirmLabel: 'Buat token baru',
      destructive: true
    })

    if (ok && api) {
      await run(() => api.rotate())
    }
  }

  const runCheck = async () => {
    if (!api) {
      setCheck({ ok: true, message: 'Pratinjau: pemeriksaan hanya berjalan di aplikasi desktop.' })

      return
    }

    setBusy(true)

    try {
      setCheck(await api.check())
    } finally {
      setBusy(false)
    }
  }

  const stateLabel = !status?.enabled
    ? 'Nonaktif'
    : status.running
      ? `Berjalan di port ${status.port}`
      : status.starting
        ? 'Memulai gateway…'
        : 'Berhenti'

  return (
    <SettingsContent>
      <section className="nv-remote-hero" data-slot="nv-remote-hero">
        <img alt="" aria-hidden="true" className="nv-remote-art" draggable={false} src={remotePairingArt} />
        <div className="nv-remote-copy">
          <span className="nv-eyebrow">Remote / Perangkat</span>
          <h2 className="nv-remote-title">Pasangkan HP</h2>
          <div className="nv-remote-device">
            <HaloMark className={status?.running ? 'size-3 text-(--nv-red)' : 'size-3 text-[#7d7470]'} />
            <span className="nv-remote-device-name">{status?.deviceName || 'PC Neovarch'}</span>
            <span className="nv-remote-device-state">{stateLabel}</span>
          </div>
          <ol className="nv-remote-steps">
            <li>
              <span>01</span>Aktifkan akses remote
            </li>
            <li>
              <span>02</span>Pindai QR dari HP
            </li>
            <li>
              <span>03</span>Obrolan, persetujuan &amp; Kanban di HP
            </li>
          </ol>
        </div>
      </section>
      <SectionHeading icon={QrCode} meta={stateLabel} title="Detail koneksi" />
      <p className={`${CAPTION} mb-2`}>
        Kendalikan agen di PC ini dari aplikasi Neovarch di HP: obrolan, persetujuan, dan Kanban. Pindai QR sekali —
        HP tersambung langsung di Wi‑Fi yang sama, atau dari mana saja lewat relay terenkripsi (tanpa aplikasi
        tambahan).
        {preview && ' (Pratinjau — data contoh.)'}
      </p>

      <ToggleRow
        checked={Boolean(status?.enabled)}
        description="Menjalankan gateway kedua yang terkunci token di 0.0.0.0:9319 agar HP bisa terhubung."
        disabled={busy || !status || preview}
        label="Aktifkan akses remote"
        onChange={on => api && void run(() => api.setEnabled(on))}
      />

      {status?.error && (
        <p className="my-2 rounded-[4px] bg-(--ui-bg-quaternary) px-3 py-2 text-xs text-destructive">{status.error}</p>
      )}

      {status?.enabled && (
        <>
          <ListRow
            below={
              <div className="mt-3 flex flex-wrap items-start gap-5">
                <div className="nv-qr-frame grid size-[232px] place-items-center bg-[#f4f2ed]">
                  {qr ? (
                    <img alt="QR pemasangan Neovarch" className="size-[232px]" src={qr} />
                  ) : (
                    <span className="text-xs text-[#0d0606]/60">
                      {status.url ? 'Membuat QR…' : 'Tidak ada alamat LAN'}
                    </span>
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-3">
                  <Field copy={status.url ?? ''} label="Alamat">
                    <span className={MONO}>{status.url ?? '—'}</span>
                  </Field>
                  <Field copy={status.token ?? ''} label="Token">
                    <span className={MONO}>{status.token ?? '—'}</span>
                  </Field>
                  {(status.altUrls?.length ?? 0) > 0 && (
                    <div data-nv-remote-alt="">
                      <p className={CAPTION}>Cadangan (dicoba HP bila LAN tidak terjangkau)</p>
                      {status.altUrls!.map(u => (
                        <p className={MONO} key={u}>
                          {u}
                        </p>
                      ))}
                    </div>
                  )}
                  {status.tailscale?.dnsName && (
                    <p className={CAPTION} data-nv-remote-tailscale="">
                      Tailscale: <span className="font-mono">{status.tailscale.dnsName}</span> — HP bisa terhubung dari
                      mana saja selama Tailscale aktif di keduanya.
                    </p>
                  )}
                  {status.profile && (
                    <p className={CAPTION}>
                      Profil: <span className="font-mono">{status.profile}</span>
                    </p>
                  )}
                </div>
              </div>
            }
            description="Di HP: buka Neovarch Agent ▸ Pindai QR dari PC. QR hanya bisa dipakai sekali dan berlaku 10 menit; setelah dipindai, QR baru muncul otomatis."
            title="Pasangkan HP"
            wide
          />

          <AnywhereSection api={api} busy={busy} preview={preview} run={run} status={status} />

          <BackgroundSection preview={preview} />

          {status.addresses.length > 1 && (
            <ListRow
              action={
                <select
                  className="h-8 rounded-[4px] bg-(--ui-bg-quaternary) px-2 text-xs text-(--ui-text-primary)"
                  disabled={busy}
                  onChange={e => api && void run(() => api.update({ preferredAddress: e.target.value }))}
                  value={status.address ?? ''}
                >
                  {status.addresses.map(a => (
                    <option key={a.address} value={a.address}>
                      {a.address} ({a.kind === 'tailscale' ? 'Tailscale' : a.iface})
                    </option>
                  ))}
                </select>
              }
              description="PC ini punya beberapa alamat jaringan. Pilih yang bisa dijangkau HP."
              title="Alamat LAN"
            />
          )}

          <ListRow
            action={
              <Input
                className="h-8 w-56"
                disabled={busy || preview}
                onBlur={() => api && name.trim() && name !== status.deviceName && void run(() => api.update({ deviceName: name }))}
                onChange={e => setName(e.target.value)}
                value={name}
              />
            }
            description="Nama yang tampil di daftar PC pada HP."
            title="Nama PC"
          />

          <ListRow
            action={
              <Button disabled={busy || !status.running} onClick={() => void runCheck()} size="sm" variant="outline">
                Periksa koneksi
              </Button>
            }
            description={
              check ? (
                <span className={check.ok ? 'text-(--ui-text-secondary)' : 'text-destructive'}>{check.message}</span>
              ) : (
                'Memanggil /api/plugins/kanban/board dengan token HP lewat alamat LAN.'
              )
            }
            title="Status"
          />

          <ListRow
            action={
              <Button disabled={busy || preview} onClick={() => void rotate()} size="sm" variant="destructive">
                <RefreshCw />
                Buat token baru
              </Button>
            }
            description="Mengganti kunci rahasia dan memulai ulang gateway. Semua HP terputus (cara mencabut akses)."
            title="Cabut akses HP"
          />

          <p className={`${CAPTION} mt-3`}>
            Token = kendali penuh atas agen di PC ini. Di Wi‑Fi tanpa enkripsi token bisa disadap; di luar rumah HP
            memakai relay yang terenkripsi ujung‑ke‑ujung. Bila HP hanya bisa lewat Tailscale, firewall PC memblokir
            port {status.port} di Wi‑Fi: tekan Periksa koneksi untuk membukanya (khusus jaringan lokal).
          </p>
        </>
      )}
    </SettingsContent>
  )
}

const RELAY_STATE: Record<string, string> = {
  off: 'Nonaktif',
  connecting: 'Menghubungkan…',
  online: 'Tersambung',
  offline: 'Terputus — mencoba lagi',
  unavailable: 'Tidak tersedia'
}

export function relayStateLabel(state: string | undefined, phones = 0): string {
  const base = RELAY_STATE[state ?? 'off'] ?? state ?? 'Nonaktif'

  return state === 'online' && phones > 0 ? `${base} · ${phones} HP aktif` : base
}

function formatSeen(ts: number | null): string {
  if (!ts) {
    return '—'
  }

  return new Date(ts * 1000).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })
}

/** "Kedaluwarsa …" line under a paired phone (auto-unpaired after remote.pairing_idle_days idle). */
export function formatExpiry(ts: number | null | undefined, nowMs = Date.now()): string {
  if (ts === undefined) {
    return 'Masa aktif: tidak diketahui (perbarui core)'
  }

  if (ts === null) {
    return 'Tidak kedaluwarsa otomatis'
  }

  const days = Math.ceil((ts * 1000 - nowMs) / 86_400_000)
  const when = new Date(ts * 1000).toLocaleDateString('id-ID', { dateStyle: 'medium' })

  if (days <= 0) {
    return `Kedaluwarsa ${when} · pasangkan ulang`
  }

  return `Kedaluwarsa ${when} (${days} hari lagi) bila tidak dipakai`
}

const VIA: Record<string, string> = { lan: 'LAN', relay: 'relay', bluetooth: 'Bluetooth' }

// "Akses dari mana saja": the remote gateway's outbound relay connection, the
// Bluetooth transport and the phones allowed to use them (docs/relay.md).
function AnywhereSection({
  api,
  busy,
  preview,
  run,
  status
}: {
  api: Window['hermesDesktop']['neovarchRemote']
  busy: boolean
  preview: boolean
  run: (fn: () => Promise<NeovarchRemoteStatus>) => Promise<void>
  status: NeovarchRemoteStatus
}) {
  const relay = status.relay
  const bt = status.bluetooth
  const [url, setUrl] = useState(relay?.url ?? '')

  useEffect(() => setUrl(relay?.url ?? ''), [relay?.url])

  const revoke = async (id: string, name: string | null) => {
    const ok = await confirm({
      title: `Cabut ${name || 'HP ini'}?`,
      description:
        'HP ini langsung terputus dari relay dan Bluetooth dan harus memindai QR lagi untuk tersambung dari luar rumah.',
      confirmLabel: 'Cabut',
      destructive: true
    })

    if (ok && api?.revokeDevice) {
      await run(() => api.revokeDevice!(id))
    }
  }

  const online = relay?.state === 'online'

  return (
    <div data-nv-remote-anywhere="">
      <ToggleRow
        checked={Boolean(relay?.enabled)}
        description={
          <span>
            PC menjaga satu koneksi keluar ke relay sehingga HP bisa tersambung dari mana saja (data seluler, Wi‑Fi
            lain) tanpa Tailscale atau membuka port. Isi pesan terenkripsi ujung‑ke‑ujung; relay tidak bisa
            membacanya.{' '}
            <span data-nv-relay-state={relay?.state ?? 'off'}>
              Status:{' '}
              <span className={online ? 'text-(--ui-text-primary)' : 'text-(--ui-text-tertiary)'}>
                {relayStateLabel(relay?.state, relay?.phones)}
              </span>
            </span>
            {relay?.error && relay.state !== 'online' && (
              <span className="block text-(--ui-text-tertiary)">({relay.error})</span>
            )}
          </span>
        }
        disabled={busy || preview || !api?.setRelay}
        label="Akses dari mana saja (relay)"
        onChange={on => api?.setRelay && void run(() => api.setRelay!({ enabled: on }))}
      />

      {relay?.enabled && (
        <ListRow
          action={
            <Input
              aria-label="Relay URL"
              className="h-8 w-72 font-mono text-xs"
              disabled={busy || preview}
              onBlur={() =>
                api?.setRelay && url.trim() !== (relay?.url ?? '') && void run(() => api.setRelay!({ url: url.trim() || null }))
              }
              onChange={e => setUrl(e.target.value)}
              placeholder={relay?.defaultUrl}
              value={url}
            />
          }
          description={
            relay && relay.url !== relay.defaultUrl
              ? 'Relay sendiri. Kosongkan untuk kembali ke relay bawaan NeovarchLabs.'
              : 'Relay bawaan NeovarchLabs (gratis). Bisa diganti dengan relay Anda sendiri (lihat docs/relay.md).'
          }
          title="Relay URL"
        />
      )}

      <ToggleRow
        checked={Boolean(bt?.enabled)}
        description={
          bt?.enabled
            ? `Untuk HP di dekat PC tanpa internet. Status: ${relayStateLabel(bt.state, bt.phones)}${bt.error ? ` (${bt.error})` : ''}${bt.address ? ` · ${bt.address}` : ''}`
            : 'Untuk HP di dekat PC tanpa internet (Linux dengan BlueZ). Aktifkan juga di pengaturan HP.'
        }
        disabled={busy || preview || !api?.setBluetooth}
        label="Bluetooth"
        onChange={on => api?.setBluetooth && void run(() => api.setBluetooth!(on))}
      />

      <ListRow
        below={
          (status.devices?.length ?? 0) > 0 ? (
            <ul className="mt-2 space-y-1.5" data-nv-remote-devices="">
              {status.devices!.map(d => (
                <li className="flex items-center justify-between gap-3 rounded-[4px] bg-(--ui-bg-quaternary) px-2.5 py-1.5" key={d.id}>
                  <div className="min-w-0">
                    <p className="truncate text-xs text-(--ui-text-primary)">{d.name || 'HP'}</p>
                    <p className={CAPTION}>
                      Terakhir aktif: {formatSeen(d.last_seen)}
                      {d.via ? ` · lewat ${VIA[d.via] ?? d.via}` : ''} · <span className="font-mono">{d.id}</span>
                    </p>
                    <p className={CAPTION} data-nv-device-expiry="">
                      {formatExpiry(d.expires_at)}
                    </p>
                  </div>
                  <Button
                    disabled={busy || preview}
                    onClick={() => void revoke(d.id, d.name)}
                    size="sm"
                    variant="outline"
                  >
                    Cabut
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className={`${CAPTION} mt-1`}>
              Belum ada. HP terdaftar otomatis setelah memindai QR atau tersambung lewat LAN.
            </p>
          )
        }
        description="HP yang boleh tersambung lewat LAN, relay atau Bluetooth. HP yang lama tidak dipakai dilepas otomatis dan harus memindai QR lagi."
        title="Perangkat terpasang"
        wide
      />
    </div>
  )
}

function Field({ children, copy, label }: { children: React.ReactNode; copy: string; label: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[0.6875rem] font-medium tracking-wide text-(--ui-text-tertiary) uppercase">{label}</span>
        {copy && <CopyButton appearance="inline" label={`Salin ${label.toLowerCase()}`} text={copy} />}
      </div>
      <div className="rounded-[4px] bg-(--ui-bg-quaternary) px-2.5 py-2">{children}</div>
    </div>
  )
}

// "Jalankan di latar belakang": the gateway + relay client keep running after
// the window is closed (tray icon), optionally started at login. The phone can
// change the same settings (GET/POST /api/remote/background).
const PREVIEW_BACKGROUND: NeovarchBackgroundStatus = {
  runInBackground: true,
  startAtLogin: true,
  updatedAt: 0,
  trayAvailable: true,
  autostartSupported: true,
  service: { state: 'running', mode: 'app', desktop_attached: true, pid: 4242, port: 9319, uptime_s: 5400 },
  agent: { sessions: 2, running: 1 },
  error: null
}

export function backgroundServiceLabel(st: NeovarchBackgroundStatus | null): string {
  if (!st) {
    return '—'
  }

  if (!st.service) {
    return st.runInBackground ? 'Aktif — gateway belum berjalan' : 'Mati'
  }

  if (st.service.state === 'stopping') {
    return 'Sedang dihentikan'
  }

  if (st.service.state === 'restarting') {
    return 'Sedang dimulai ulang'
  }

  return st.runInBackground ? 'Berjalan di latar belakang' : 'Berjalan (ikut jendela aplikasi)'
}

function BackgroundSection({ preview }: { preview: boolean }) {
  const api = window.hermesDesktop?.neovarchBackground
  const [st, setSt] = useState<NeovarchBackgroundStatus | null>(preview || !api ? PREVIEW_BACKGROUND : null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!api) {
      return
    }

    let alive = true
    void api.get().then(s => alive && setSt(s))
    const off = api.onChanged(s => setSt(s))

    return () => {
      alive = false
      off()
    }
  }, [api])

  const set = async (patch: { runInBackground?: boolean; startAtLogin?: boolean }) => {
    if (!api) {
      return
    }

    setBusy(true)

    try {
      setSt(await api.set(patch))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-nv-remote-background="">
      <ToggleRow
        checked={Boolean(st?.runInBackground)}
        description={
          st?.trayAvailable === false
            ? 'Gateway dan relay tetap berjalan setelah aplikasi ditutup. (Ikon tray tidak tersedia di desktop ini.)'
            : 'Gateway dan relay tetap berjalan saat jendela ditutup; Neovarch pindah ke ikon tray. HP tetap bisa tersambung.'
        }
        disabled={busy || !st || !api}
        label="Jalankan di latar belakang"
        onChange={on => void set({ runInBackground: on })}
      />
      <ToggleRow
        checked={Boolean(st?.startAtLogin)}
        description="Buka Neovarch (tersembunyi di tray) setiap kali Anda masuk ke komputer."
        disabled={busy || !st || !api || st.autostartSupported === false}
        label="Mulai saat login"
        onChange={on => void set({ startAtLogin: on })}
      />
      <ListRow
        description={
          st?.service
            ? `PID ${st.service.pid} · port ${st.service.port} · ${st.agent?.running ?? 0} agen berjalan dari ${st.agent?.sessions ?? 0} sesi`
            : 'Gateway remote belum berjalan.'
        }
        title={`Layanan latar: ${backgroundServiceLabel(st)}`}
      />
      {st?.error && (
        <p className="my-2 rounded-[4px] bg-(--ui-bg-quaternary) px-3 py-2 text-xs text-destructive">{st.error}</p>
      )}
    </div>
  )
}
