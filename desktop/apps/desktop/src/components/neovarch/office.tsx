import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { sessionRoute } from '@/app/routes'
import { useI18n } from '@/i18n'
import { Brain, Users } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $activeSessionId, $busy } from '@/store/session'

import { OfficeAgentAvatar } from './agent-identity'
import { COMPANY_TABS, CompanyPanel, type CompanyTab, visibleCompanyTabs } from './company'
import { $company, hasCompany } from './company-store'
import { CREW_ROUTE } from './crew-store'
import { KartuCardButton } from './kartu-card-dialog'
import { Office3D } from './office-3d'
import { MiniOffice3D } from './office-mini-3d'
import { OfficeModelSelect } from './office-model-select'
import {
  $office,
  $officeError,
  $officeView,
  OFFICE_STATUS_LABEL,
  type OfficeAgent,
  officeWorkingCount,
  refreshOffice,
  type OfficeFeedItem,
  type OfficeView,
  relativeTime,
  setOfficeView
} from './office-store'

function useNow(intervalMs = 5000): number {
  const [now, setNow] = useState(() => Date.now() / 1000)

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), intervalMs)

    return () => window.clearInterval(t)
  }, [intervalMs])

  return now
}

export function StatusDot({ status }: { status: OfficeAgent['status'] }) {
  return <span aria-hidden="true" className="nv-office-dot" data-status={status} />
}

function Desk({ agent, now }: { agent: OfficeAgent; now: number }) {
  const navigate = useNavigate()
  const open = agent.session_id ? () => navigate(sessionRoute(agent.session_id!)) : undefined

  return (
    <article className="nv-office-desk" data-nv-desk={agent.id} data-status={agent.status}>
      <header className="nv-office-desk-head">
        <OfficeAgentAvatar agent={agent} size={40} />
        <div className="min-w-0">
          <h3 className="nv-office-name">{agent.name}</h3>
          <p className="nv-office-role">{agent.role}</p>
        </div>
        <span className="nv-office-status" data-status={agent.status}>
          <StatusDot status={agent.status} />
          {OFFICE_STATUS_LABEL[agent.status]}
        </span>
      </header>
      <dl className="nv-office-facts">
        <div>
          <dt>Tugas</dt>
          <dd title={agent.current_task ?? undefined}>{agent.current_task || 'Belum ada tugas'}</dd>
        </div>
        {agent.current_tool && (
          <div>
            <dt>Sedang</dt>
            <dd className="nv-office-mono" title={agent.current_tool}>
              {agent.current_tool}
            </dd>
          </div>
        )}
        {agent.pending_approval?.command && (
          <div>
            <dt>Minta izin</dt>
            <dd className="nv-office-mono" title={agent.pending_approval.command}>
              {agent.pending_approval.command}
            </dd>
          </div>
        )}
        <div>
          <dt>Aktivitas</dt>
          <dd title={agent.last_activity_text ?? undefined}>
            {relativeTime(agent.last_activity, now)}
            {agent.last_activity_text ? ` · ${agent.last_activity_text}` : ''}
          </dd>
        </div>
      </dl>
      <OfficeModelSelect agent={agent} />
      {open && (
        <button className="nv-office-open" onClick={open} type="button">
          Buka obrolan
        </button>
      )}
    </article>
  )
}

function FeedRow({ item, now }: { item: OfficeFeedItem; now: number }) {
  return (
    <li className="nv-office-feed-row" data-kind={item.kind}>
      <span className="nv-office-feed-who">{item.agent}</span>
      <span className="nv-office-feed-text">{item.text}</span>
      <time className="nv-office-feed-time">{relativeTime(item.ts, now)}</time>
    </li>
  )
}

const VIEWS: { label: string; value: OfficeView }[] = [
  { label: '3D', value: '3d' },
  { label: 'Daftar', value: 'list' }
]

export function ViewToggle({ onChange, value }: { onChange: (view: OfficeView) => void; value: OfficeView }) {
  return (
    <div aria-label="Tampilan kantor" className="nv-office-view-toggle" data-slot="nv-office-view-toggle" role="group">
      {VIEWS.map(option => (
        <button
          aria-pressed={value === option.value}
          data-view={option.value}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

type OfficeTab = 'room' | CompanyTab
const OFFICE_TAB_KEY = 'neovarch.desktop.office-tab.v1'
const OFFICE_TABS: { label: string; value: OfficeTab }[] = [{ label: 'Ruang', value: 'room' }, ...COMPANY_TABS]

function readOfficeTab(): OfficeTab {
  try {
    const saved = window.localStorage.getItem(OFFICE_TAB_KEY)

    return OFFICE_TABS.some(t => t.value === saved) ? (saved as OfficeTab) : 'room'
  } catch {
    return 'room'
  }
}

/** Kantor sections: the room itself, then the Perusahaan views (org chart, tickets, approvals, costs, activity).
 *  Until the Kantor has anything in it, only Ruang and Organisasi show (the rest would be empty pages). */
export function OfficeTabs({
  exists = true,
  onChange,
  value
}: {
  exists?: boolean
  onChange: (tab: OfficeTab) => void
  value: OfficeTab
}) {
  const tabs: { label: string; value: OfficeTab }[] = [{ label: 'Ruang', value: 'room' }, ...visibleCompanyTabs(exists)]

  return (
    <nav aria-label="Bagian kantor" className="nv-office-tabs" data-slot="nv-office-tabs" role="tablist">
      {tabs.map(tab => (
        <button
          aria-selected={value === tab.value}
          data-tab={tab.value}
          key={tab.value}
          onClick={() => onChange(tab.value)}
          role="tab"
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

/** The Office page: every agent the core runs, at its desk, plus a live feed. */
export function NeovarchOfficePage() {
  const office = useStore($office)
  const error = useStore($officeError)
  const now = useNow()
  const navigate = useNavigate()
  const view = useStore($officeView)
  const companySnap = useStore($company)
  const companyExists = hasCompany(companySnap)
  const [savedTab, setTabState] = useState<OfficeTab>(readOfficeTab)
  // A hidden tab (nothing exists yet) falls back to the room.
  const tab: OfficeTab =
    savedTab === 'room' || visibleCompanyTabs(companyExists).some(t => t.value === savedTab) ? savedTab : 'room'

  const setTab = (next: OfficeTab) => {
    setTabState(next)

    try {
      window.localStorage.setItem(OFFICE_TAB_KEY, next)
    } catch {
      // storage unavailable: the choice holds for this run
    }
  }

  const list = (
    <section aria-label="Meja agen" className="nv-office-grid">
      {office === null && !error && <p className="nv-office-empty">Memuat kantor…</p>}
      {error && (
        <div className="nv-office-empty" role="alert">
          <p>Kantor belum bisa dimuat: {error}</p>
          <button className="nv-office-retry" onClick={() => void refreshOffice()} type="button">
            Coba lagi
          </button>
        </div>
      )}
      {office && (!Array.isArray(office.agents) || office.agents.length === 0) && (
        <div className="nv-office-empty">
          <Users className="size-5" />
          <p>
            Kantor masih kosong. Minta Neovarch Agent di Chat untuk membuat organisasi, agency, dan merekrut pegawai,
            atau buka tab Organisasi.
          </p>
        </div>
      )}
      {(Array.isArray(office?.agents) ? office.agents : []).map(agent => (
        <Desk agent={agent} key={agent.id} now={now} />
      ))}
    </section>
  )

  return (
    <div className="nv-office" data-slot="nv-office">
      <header className="nv-office-header">
        <div>
          <p className="nv-office-kicker">Kantor</p>
          <h1 className="nv-office-title">Pegawai Neovarch</h1>
          <p className="nv-office-sub">
            Pegawai yang kamu rekrut lewat Neovarch Agent, statusnya, dan apa yang mereka kerjakan. Diperbarui langsung.
          </p>
        </div>
        <div className="nv-office-header-tools">
          {tab === 'room' && <ViewToggle onChange={setOfficeView} value={view} />}
          <KartuCardButton />
          <div className="nv-office-counters">
            <span>
              <StatusDot status="working" /> {officeWorkingCount(office)} bekerja
            </span>
            <span>
              <StatusDot status="waiting-approval" /> {office?.counts['waiting-approval'] ?? 0} menunggu
            </span>
            <span>
              <StatusDot status="idle" /> {office?.counts.idle ?? 0} santai
            </span>
          </div>
        </div>
      </header>

      <OfficeTabs exists={companyExists} onChange={setTab} value={tab} />

      {tab !== 'room' ? (
        <CompanyPanel tab={tab} />
      ) : (
        <div className="nv-office-body">
          {view === '3d' ? (
            <Office3D fallback={list} office={office} onOpenSession={id => navigate(sessionRoute(id))} />
          ) : (
            list
          )}

          <aside className="nv-office-side">
            <section className="nv-office-card" data-slot="nv-office-vault">
              <h2 className="nv-office-card-title">
                <Brain className="size-3.5" /> Memori Obsidian
              </h2>
              {office?.vault.connected ? (
                <>
                  <p className="nv-office-vault-state" data-state="connected">
                    <StatusDot status="working" /> Terhubung · {office.vault.note_count} catatan
                  </p>
                  <p className="nv-office-mono nv-office-path" title={office.vault.path}>
                    {office.vault.path}
                  </p>
                </>
              ) : (
                <>
                  <p className="nv-office-vault-state" data-state="off">
                    <StatusDot status="idle" />{' '}
                    {office?.vault.configured ? `Folder tidak ditemukan: ${office.vault.path}` : 'Belum dihubungkan'}
                  </p>
                  <button
                    className="nv-office-open"
                    onClick={() => navigate('/settings?tab=config%3Amemory')}
                    type="button"
                  >
                    Pilih vault
                  </button>
                </>
              )}
            </section>

            <section className="nv-office-card nv-office-feed-card">
              <h2 className="nv-office-card-title">Aktivitas</h2>
              {office && office.feed.length === 0 ? (
                <p className="nv-office-empty-line">Belum ada aktivitas.</p>
              ) : (
                <ol className="nv-office-feed" data-slot="nv-office-feed">
                  {office?.feed.map(item => (
                    <FeedRow item={item} key={item.id} now={now} />
                  ))}
                </ol>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  )
}

/** Compact "Crew" card for the context rail beside the conversation; opens the Crew page. */
export function NeovarchOfficeMini() {
  const office = useStore($office)
  const busy = useStore($busy)
  const activeSessionId = useStore($activeSessionId)
  const navigate = useNavigate()
  const s = useI18n().t.nvCrew
  const agents = Array.isArray(office?.agents) ? office.agents.slice(0, 5) : []
  const working = officeWorkingCount(office, busy ? [activeSessionId] : [])

  return (
    <button
      className={cn('nv-context-card nv-office-mini')}
      data-slot="nv-office-mini"
      onClick={() => navigate(CREW_ROUTE)}
      title={s.mini.open}
      type="button"
    >
      <span className="nv-context-label">
        <Users className="size-3.5" /> {s.title}
        <span className="nv-office-mini-count">
          {office || busy ? s.mini.working.replace('{n}', String(working)) : ''}
        </span>
      </span>
      <MiniOffice3D office={office} />
      {agents.length === 0 ? (
        <span className="nv-context-empty">{s.mini.empty}</span>
      ) : (
        <span className="nv-office-mini-list">
          {agents.map(agent => (
            <span className="nv-office-mini-row" data-status={agent.status} key={agent.id}>
              <OfficeAgentAvatar agent={agent} feed={office?.feed} size={32} />
              <span className="min-w-0">
                <span className="nv-office-mini-name">{agent.name}</span>
                <span className="nv-office-mini-task">
                  {agent.current_tool || agent.current_task || OFFICE_STATUS_LABEL[agent.status]}
                </span>
              </span>
            </span>
          ))}
        </span>
      )}
    </button>
  )
}
