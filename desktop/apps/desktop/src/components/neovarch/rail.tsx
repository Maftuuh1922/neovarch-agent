import { useStore } from '@nanostores/react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { ARTIFACTS_ROUTE, CAPABILITIES_ROUTE, CRON_ROUTE, navigateToWorkspacePage } from '@/app/routes'
import { openNeovarchKanban } from '@/components/neovarch/home'
import { CREW_ROUTE } from '@/components/neovarch/crew-store'
import { OFFICE_ROUTE } from '@/components/neovarch/office-store'
import { $socialAvatar, $socialStatus, SOCIAL_ROUTE } from '@/components/neovarch/social-store'
import { VAULT_ROUTE } from '@/components/neovarch/vault'
import { Tip } from '@/components/ui/tooltip'
import { type Locale, useI18n } from '@/i18n'
import { nvPick } from '@/i18n/neovarch-lang'
import { NV_SOCIAL_EN, NV_SOCIAL_ID } from '@/i18n/neovarch-social'
import {
  Brain,
  Clock,
  FileText,
  LayoutDashboard,
  MessageSquareText,
  Moon,
  Plus,
  QrCode,
  Settings,
  Sun,
  UserCircle,
  Users,
  Zap
} from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $sidebarOpen, toggleSidebarOpen } from '@/store/layout'
import { requestFreshSession } from '@/store/profile'
import { useTheme } from '@/themes/context'

import { HaloMark } from './halo-mark'

export const NV_RAIL_WIDTH = 60

export const NV_COPY = {
  home: 'Beranda',
  newChat: 'Obrolan baru',
  sessions: 'Sesi',
  skills: 'Skill & alat',
  kanban: 'Tugas (Kanban)',
  artifacts: 'Artefak',
  cron: 'Jadwal',
  office: 'Crew',
  vault: 'Vault Obsidian',
  social: NV_SOCIAL_ID.rail as string,
  pairPhone: 'Pasangkan HP',
  settings: 'Pengaturan',
  toDark: 'Tema gelap',
  toLight: 'Tema terang'
}

export const NV_COPY_EN: typeof NV_COPY = {
  home: 'Home',
  newChat: 'New chat',
  sessions: 'Sessions',
  skills: 'Skills & tools',
  kanban: 'Tasks (Kanban)',
  artifacts: 'Artifacts',
  cron: 'Schedule',
  office: 'Crew',
  vault: 'Obsidian vault',
  social: NV_SOCIAL_EN.rail,
  pairPhone: 'Pair phone',
  settings: 'Settings',
  toDark: 'Dark theme',
  toLight: 'Light theme'
}

/** The rail's labels in the app's language (Settings → ID/EN). */
export function nvRailCopy(locale?: Locale): typeof NV_COPY {
  return nvPick({ en: NV_COPY_EN, id: NV_COPY }, locale)
}

interface RailItem {
  active?: boolean
  icon: ReactNode
  id: string
  label: string
  onSelect: () => void
}

function RailButton({ item }: { item: RailItem }) {
  return (
    <Tip label={item.label} side="right">
      <button
        aria-label={item.label}
        aria-pressed={item.active ?? undefined}
        className={cn('nv-rail-button', item.active && 'nv-rail-button-active')}
        data-nv-rail={item.id}
        onClick={item.onSelect}
        type="button"
      >
        {item.icon}
      </button>
    </Tip>
  )
}

/**
 * Neovarch's slim icon rail — every primary destination one click away, so the
 * sessions panel beside it can stay a collapsible list instead of Hermes'
 * nav-plus-sessions column.
 */
export function NeovarchRail() {
  const navigate = useNavigate()
  const location = useLocation()
  const NV = nvRailCopy(useI18n().locale)
  // One session list: the chat's own sidebar (search, pins, groups, Kanban).
  // The separate rail drawer duplicated it and was removed.
  const sessionsOpen = useStore($sidebarOpen)
  const avatar = useStore($socialAvatar)
  // subscribing loads the social status once at launch (avatar refresh)
  useStore($socialStatus)

  const { renderedMode, setMode } = useTheme()
  const path = location.pathname
  const page = (to: string) => () => navigateToWorkspacePage(navigate, to)
  const icon = 'size-[1.05rem]'

  const top: RailItem[] = [
    {
      icon: <Plus className={icon} />,
      id: 'new-chat',
      label: NV.newChat,
      onSelect: () => {
        navigate('/')
        requestFreshSession()
      }
    },
    {
      active: sessionsOpen,
      icon: <MessageSquareText className={icon} />,
      id: 'sessions',
      label: NV.sessions,
      onSelect: () => toggleSidebarOpen()
    }
  ]

  const middle: RailItem[] = [
    {
      active: path.startsWith(CREW_ROUTE) || path.startsWith(OFFICE_ROUTE),
      icon: <Users className={icon} />,
      id: 'office',
      label: NV.office,
      onSelect: () => navigate(CREW_ROUTE)
    },
    {
      active: path.startsWith(SOCIAL_ROUTE),
      icon: avatar ? (
        <img alt="" className="nv-rail-avatar" data-slot="nv-rail-avatar" src={avatar} />
      ) : (
        <UserCircle className={icon} />
      ),
      id: 'social',
      label: NV.social,
      onSelect: () => navigate(SOCIAL_ROUTE)
    },
    {
      active: path.startsWith(VAULT_ROUTE),
      icon: <Brain className={icon} />,
      id: 'vault',
      label: NV.vault,
      onSelect: () => navigate(VAULT_ROUTE)
    },
    {
      active: path.startsWith(CAPABILITIES_ROUTE),
      icon: <Zap className={icon} />,
      id: 'skills',
      label: NV.skills,
      onSelect: page(CAPABILITIES_ROUTE)
    },
    {
      active: path.startsWith('/kanban'),
      icon: <LayoutDashboard className={icon} />,
      id: 'kanban',
      label: NV.kanban,
      onSelect: () => void openNeovarchKanban(navigate)
    },
    {
      active: path.startsWith(ARTIFACTS_ROUTE),
      icon: <FileText className={icon} />,
      id: 'artifacts',
      label: NV.artifacts,
      onSelect: page(ARTIFACTS_ROUTE)
    },
    {
      active: path.startsWith(CRON_ROUTE),
      icon: <Clock className={icon} />,
      id: 'cron',
      label: NV.cron,
      onSelect: page(CRON_ROUTE)
    }
  ]

  const isDark = renderedMode === 'dark'

  const bottom: RailItem[] = [
    {
      icon: <QrCode className={icon} />,
      id: 'pair-phone',
      label: NV.pairPhone,
      onSelect: () => navigate('/settings?tab=remote')
    },
    {
      icon: isDark ? <Sun className={icon} /> : <Moon className={icon} />,
      id: 'theme',
      label: isDark ? NV.toLight : NV.toDark,
      onSelect: () => setMode(isDark ? 'light' : 'dark')
    },
    {
      active: path.startsWith('/settings'),
      icon: <Settings className={icon} />,
      id: 'settings',
      label: NV.settings,
      onSelect: () => navigate('/settings')
    }
  ]

  return (
    <nav aria-label="Neovarch" className="nv-rail" data-slot="nv-rail" style={{ width: NV_RAIL_WIDTH }}>
      <Tip label={NV.home} side="right">
        <button
          aria-label={NV.home}
          className="nv-rail-logo"
          data-nv-rail="home"
          onClick={() => navigate('/')}
          type="button"
        >
          <HaloMark className="size-5" />
        </button>
      </Tip>
      <div className="nv-rail-group">
        {top.map(item => (
          <RailButton item={item} key={item.id} />
        ))}
      </div>
      <span aria-hidden="true" className="nv-rail-rule" />
      <div className="nv-rail-group">
        {middle.map(item => (
          <RailButton item={item} key={item.id} />
        ))}
      </div>
      <div className="nv-rail-group mt-auto">
        {bottom.map(item => (
          <RailButton item={item} key={item.id} />
        ))}
      </div>
    </nav>
  )
}
