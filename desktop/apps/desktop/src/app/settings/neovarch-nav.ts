import { Brain, Cpu, Info, Palette, QrCode, ShieldLock, Wrench } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'

import type { OverlayNavGroup, OverlayNavLink } from '../overlays/overlay-split-layout'

/**
 * Neovarch's short Settings index: seven numbered groups instead of Hermes'
 * long flat list. Every Hermes page still exists — it is folded inside one of
 * these groups (its own sub-pages show under it while it is open).
 */
const GROUPS: { icon: IconComponent; id: string; label: string; members: string[] }[] = [
  { icon: Cpu, id: 'nv:model', label: 'Model', members: ['config:model', 'providers', 'config:chat'] },
  {
    icon: Palette,
    id: 'nv:appearance',
    label: 'Tampilan',
    members: ['config:appearance', 'config:workspace', 'notifications', 'keybinds', 'config:voice']
  },
  { icon: QrCode, id: 'nv:remote', label: 'Remote / HP', members: ['remote', 'gateway'] },
  { icon: ShieldLock, id: 'nv:security', label: 'Keamanan', members: ['config:safety', 'vault', 'keys'] },
  { icon: Brain, id: 'nv:memory', label: 'Memori & Skill', members: ['obsidian', 'config:memory', 'sessions', 'plugins'] },
  { icon: Wrench, id: 'nv:advanced', label: 'Lanjutan', members: ['config:advanced', 'config:browser', 'billing'] },
  { icon: Info, id: 'nv:about', label: 'Tentang', members: ['about'] }
]

/** Indonesian labels for the Settings pages and sub-pages Neovarch lists. */
export const NV_SETTINGS_LABELS: Record<string, string> = {
  'config:model': 'Pilihan model',
  providers: 'Penyedia',
  'config:chat': 'Obrolan',
  'config:appearance': 'Tampilan',
  'config:workspace': 'Ruang kerja',
  notifications: 'Notifikasi',
  keybinds: 'Pintasan keyboard',
  'config:voice': 'Suara',
  remote: 'Pasangkan HP',
  gateway: 'Gateway',
  'config:safety': 'Keamanan',
  vault: 'Brankas kredensial',
  keys: 'Kunci & tool',
  obsidian: 'Vault Obsidian',
  'config:memory': 'Memori',
  sessions: 'Arsip sesi',
  plugins: 'Plugin',
  'config:advanced': 'Lanjutan',
  'config:browser': 'Browser',
  billing: 'Tagihan',
  about: 'Tentang',
  'config:model:main': 'Model utama',
  'config:model:fallbacks': 'Model cadangan',
  'config:model:auxiliary': 'Model pembantu',
  'config:model:moa': 'Gabungan agen',
  'pview:accounts': 'Akun',
  'pview:github': 'Akun GitHub',
  'pview:keys': 'Kunci API',
  'pview:custom-endpoints': 'Endpoint kustom',
  'pview:local': 'Model lokal',
  'config:chat:behavior': 'Perilaku',
  'config:chat:attachments': 'Lampiran',
  'config:appearance:general': 'Umum',
  'config:appearance:theme': 'Tema',
  'config:appearance:typography': 'Huruf',
  'config:appearance:window-layout': 'Tata letak jendela',
  'config:appearance:chat-display': 'Tampilan obrolan',
  'config:appearance:pet': 'Maskot',
  'config:workspace:projects': 'Proyek',
  'config:workspace:shell': 'Shell',
  'config:workspace:files': 'File',
  'notifications:alerts': 'Peringatan',
  'notifications:sounds': 'Suara notifikasi',
  'keybinds:shortcuts': 'Pintasan',
  'keybinds:hud-gesture': 'Gestur HUD',
  'keybinds:screen-capture': 'Tangkapan layar',
  'config:voice:conversation': 'Percakapan',
  'config:voice:transcription': 'Transkripsi',
  'config:voice:speech': 'Ucapan',
  'gateway:connection': 'Koneksi',
  'gateway:devices': 'Perangkat',
  'gateway:managed-updates': 'Pembaruan terkelola',
  'config:safety:approvals': 'Persetujuan',
  'config:safety:privacy': 'Privasi',
  'config:safety:checkpoints': 'Checkpoint',
  'vault:credentials': 'Kredensial',
  'vault:sources': 'Sumber',
  'kview:tools': 'Tool',
  'kview:settings': 'Pengaturan',
  'config:memory:persistent': 'Memori tetap',
  'config:memory:context': 'Konteks',
  'sessions:archived': 'Sesi diarsipkan',
  'sessions:default-directory': 'Folder bawaan',
  'config:advanced:desktop': 'Desktop',
  'config:advanced:runtime': 'Runtime',
  'config:advanced:tools': 'Tool',
  'config:advanced:terminal': 'Terminal',
  'config:advanced:delegation': 'Delegasi',
  'config:advanced:output': 'Keluaran',
  'config:browser:profile': 'Profil',
  'config:browser:network': 'Jaringan',
  'bview:overview': 'Ringkasan',
  'bview:plans': 'Paket',
  'about:updates': 'Pembaruan'
}

function relabel<T extends OverlayNavLink>(link: T): T {
  return {
    ...link,
    label: NV_SETTINGS_LABELS[link.id] ?? link.label,
    children: link.children?.map(child => relabel(child))
  }
}

/** The flat Hermes list with Neovarch's Indonesian labels (used by breadcrumbs). */
export function relabelSettingsNav(flat: OverlayNavGroup[]): OverlayNavGroup[] {
  return flat.map(group => relabel(group))
}

/**
 * Fold the flat Hermes Settings list into the seven numbered groups. A page
 * that belongs to no group (a future Hermes addition) lands in "Lanjutan" so
 * nothing becomes unreachable.
 */
export function groupSettingsNav(flat: OverlayNavGroup[]): OverlayNavGroup[] {
  const byId = new Map(flat.map(entry => [entry.id, relabel(entry)]))
  const claimed = new Set(GROUPS.flatMap(group => group.members))
  const strays = flat.filter(entry => !claimed.has(entry.id)).map(entry => relabel(entry))

  return GROUPS.map(group => {
    const members = group.members.map(id => byId.get(id)).filter((entry): entry is OverlayNavGroup => Boolean(entry))
    const children: OverlayNavLink[] = group.id === 'nv:advanced' ? [...members, ...strays] : members
    const active = children.some(child => child.active)

    if (children.length === 1) {
      const only = children[0]

      return { active, icon: group.icon, id: group.id, label: group.label, onSelect: only.onSelect, children: only.children }
    }

    return {
      active,
      children: children.map(child => ({
        active: child.active,
        children: child.children,
        icon: child.icon,
        id: child.id,
        label: child.label,
        onSelect: child.onSelect
      })),
      icon: group.icon,
      id: group.id,
      label: group.label,
      onSelect: () => children[0]?.onSelect()
    }
  })
}
