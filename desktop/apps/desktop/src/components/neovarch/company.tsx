import './company.css'

import { useStore } from '@nanostores/react'
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { sessionRoute } from '@/app/routes'

import {
  $company,
  $companyError,
  $companyRev,
  AGENT_STATUS_LABEL,
  APPROVAL_KIND_LABEL,
  type CompanyActivity,
  type CompanyAgent,
  type CompanyApproval,
  companyCall,
  type CompanyCosts,
  type CompanySnapshot,
  type CompanyTicket,
  type CompanyUnit,
  formatCents,
  formatTokens,
  hasCompany,
  orgTree,
  TICKET_COLUMNS,
  TICKET_LABEL,
  TICKET_TRANSITIONS,
  type TicketDetail,
  type TicketStatus,
  unitTree
} from './company-store'
import { AgentEditor, GoalsAndProjects, Routines, TicketBlockers } from './company-plan'
import { ErrorLine, useAction } from './company-ui'
import { relativeTime } from './office-store'

export type CompanyTab = 'activity' | 'approvals' | 'costs' | 'goals' | 'org' | 'routines' | 'tickets'

export const COMPANY_TABS: { label: string; value: CompanyTab }[] = [
  { label: 'Organisasi', value: 'org' },
  { label: 'Tiket', value: 'tickets' },
  { label: 'Tujuan', value: 'goals' },
  { label: 'Rutinitas', value: 'routines' },
  { label: 'Persetujuan', value: 'approvals' },
  { label: 'Biaya', value: 'costs' },
  { label: 'Aktivitas', value: 'activity' }
]

/** Before anything exists only the org view is shown (its empty state creates the first unit). */
export function visibleCompanyTabs(exists: boolean): { label: string; value: CompanyTab }[] {
  return exists ? COMPANY_TABS : COMPANY_TABS.filter(tab => tab.value === 'org')
}

const now = () => Date.now() / 1000

// ------------------------------------------------------------------ setup --

export function CompanySetup() {
  const [name, setName] = useState('')
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('unit.save', { kind: 'organisasi', name })
      setName('')
    })
  }

  return (
    <section className="nv-co-setup" data-slot="nv-company-setup">
      <h2>Kantor masih kosong</h2>
      <p>
        Susunannya Organisasi → Agency → Orang, sedalam yang kamu mau. Minta Neovarch Agent di Chat, misalnya “buat
        organisasi Neovarch Labs dengan agency Kreatif, lalu rekrut Sinta sebagai copywriter”, atau buat organisasi
        pertamamu di sini. Tidak ada pegawai yang berjalan sendiri sampai kamu menyalakan “Jalan otomatis”.
      </p>
      <form className="nv-co-form" onSubmit={submit}>
        <label>
          Nama organisasi
          <input onChange={e => setName(e.target.value)} placeholder="mis. Neovarch Labs" required value={name} />
        </label>
        <div className="nv-co-row">
          <button className="nv-co-btn" data-variant="primary" disabled={busy || !name.trim()} type="submit">
            Buat organisasi
          </button>
        </div>
      </form>
      <ErrorLine error={error} />
    </section>
  )
}

function CompanyBar({ snap }: { snap: CompanySnapshot }) {
  const [error, run, busy] = useAction()
  const c = snap.company

  return (
    <div className="nv-co-bar" data-slot="nv-company-bar">
      <div className="min-w-0">
        <p className="nv-co-name">{c.name}</p>
        <p className="nv-co-mission" title={c.mission}>
          {c.mission || 'Belum ada misi'}
        </p>
      </div>
      <div className="nv-co-bar-tools">
        <span className="nv-co-chip">{snap.pending_approvals} menunggu persetujuan</span>
        <label className="nv-co-switch" title="Agen bangun sendiri saat ada tiket, komentar, atau jadwal">
          <input
            aria-label="Jalan otomatis"
            checked={c.autorun}
            disabled={busy}
            onChange={e => void run(() => companyCall('update', { autorun: e.target.checked }))}
            type="checkbox"
          />
          <span>Jalan otomatis</span>
        </label>
      </div>
      <ErrorLine error={error} />
    </div>
  )
}

// -------------------------------------------------------------------- org --

function AgentNode({
  agent,
  agents,
  depth,
  running,
  units = []
}: {
  agent: CompanyAgent
  agents: CompanyAgent[]
  depth: number
  running: boolean
  units?: CompanyUnit[]
}) {
  const navigate = useNavigate()
  const [error, run, busy] = useAction()
  const [editing, setEditing] = useState(false)
  const status = running ? 'running' : agent.status

  return (
    <li className="nv-co-node" data-status={status} style={{ marginLeft: `${depth * 1.5}rem` }}>
      <div className="nv-co-node-head">
        <span className="nv-co-node-name">{agent.name}</span>
        <span className="nv-co-node-title">{agent.title || agent.role}</span>
        <span className="nv-co-pill" data-status={status}>
          {AGENT_STATUS_LABEL[status]}
          {agent.status === 'paused' && agent.pause_reason === 'budget' ? ' · anggaran' : ''}
        </span>
      </div>
      <p className="nv-co-node-task">
        {agent.current_ticket
          ? `${agent.current_ticket.key} · ${agent.current_ticket.title} (${TICKET_LABEL[agent.current_ticket.status]})`
          : 'Tidak memegang tiket'}
      </p>
      <p className="nv-co-muted nv-co-node-meta">
        Model: {agent.model || 'bawaan PC'}
        {agent.budget_monthly_cents > 0 ? ` · anggaran ${formatCents(agent.budget_monthly_cents)}/bln` : ''}
        {agent.budget_monthly_tokens > 0 ? ` · ${formatTokens(agent.budget_monthly_tokens)}/bln` : ''}
      </p>
      {agent.budget.pct !== null && (
        <div
          aria-label={`Anggaran terpakai ${agent.budget.pct}%`}
          className="nv-co-meter"
          data-level={agent.budget.level}
        >
          <i style={{ width: `${Math.min(100, agent.budget.pct)}%` }} />
        </div>
      )}
      <div className="nv-co-row">
        {agent.status !== 'pending_approval' && agent.status !== 'paused' && !running && (
          <button
            className="nv-co-btn"
            disabled={busy}
            onClick={() => void run(() => companyCall('agent.wake', { id: agent.id }))}
            type="button"
          >
            Bangunkan
          </button>
        )}
        {running && (
          <button
            className="nv-co-btn"
            disabled={busy}
            onClick={() => void run(() => companyCall('agent.stop', { id: agent.id }))}
            type="button"
          >
            Hentikan
          </button>
        )}
        {agent.status === 'paused' || agent.status === 'error' ? (
          <button
            className="nv-co-btn"
            disabled={busy}
            onClick={() => void run(() => companyCall('agent.resume', { id: agent.id }))}
            type="button"
          >
            Lanjutkan
          </button>
        ) : (
          agent.status !== 'pending_approval' && (
            <button
              className="nv-co-btn"
              disabled={busy}
              onClick={() => void run(() => companyCall('agent.pause', { id: agent.id }))}
              type="button"
            >
              Jeda
            </button>
          )
        )}
        <button
          className="nv-co-btn"
          disabled={busy || agent.status === 'pending_approval'}
          onClick={() =>
            void run(async () => {
              const res = await companyCall<{ session_id: string }>('agent.chat', { id: agent.id })
              navigate(sessionRoute(res.session_id))
            })
          }
          type="button"
        >
          Ngobrol
        </button>
        <button
          aria-expanded={editing}
          className="nv-co-btn"
          disabled={busy}
          onClick={() => setEditing(v => !v)}
          type="button"
        >
          Ubah
        </button>
        {units.length > 0 && (
          <select
            aria-label={`Pindahkan ${agent.name}`}
            disabled={busy}
            onChange={e =>
              void run(() =>
                companyCall('agent.move', { id: agent.id, unit_id: e.target.value ? Number(e.target.value) : null })
              )
            }
            value={agent.unit_id ?? ''}
          >
            <option value="">Tanpa unit</option>
            {units.map(u => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        )}
        <button
          className="nv-co-btn"
          data-variant="danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Berhentikan dan hapus ${agent.name} dari Kantor?`)) {
              void run(() => companyCall('agent.delete', { id: agent.id }))
            }
          }}
          type="button"
        >
          Berhentikan
        </button>
      </div>
      {(agent.skills?.length || agent.tools?.length || agent.persona) && (
        <p className="nv-co-muted nv-co-node-meta">
          {agent.skills?.length ? `Skill: ${agent.skills.join(', ')}` : ''}
          {agent.tools?.length ? `${agent.skills?.length ? ' · ' : ''}Alat: ${agent.tools.join(', ')}` : ''}
          {agent.persona ? `${agent.skills?.length || agent.tools?.length ? ' · ' : ''}Persona: ${agent.persona}` : ''}
        </p>
      )}
      <ErrorLine error={error} />
      {editing && <AgentEditor agent={agent} agents={agents} onClose={() => setEditing(false)} />}
    </li>
  )
}

function HireForm({ agents, units = [] }: { agents: CompanyAgent[]; units?: CompanyUnit[] }) {
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [reportsTo, setReportsTo] = useState('')
  const [unit, setUnit] = useState('')
  const [job, setJob] = useState('')
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('agent.save', {
        job_description: job,
        name,
        reports_to: reportsTo ? Number(reportsTo) : null,
        title,
        unit_id: unit ? Number(unit) : null
      })
      setName('')
      setTitle('')
      setJob('')
    })
  }

  return (
    <form className="nv-co-form nv-co-card" onSubmit={submit}>
      <h3>Rekrut pegawai</h3>
      <div className="nv-co-row">
        <input aria-label="Nama" onChange={e => setName(e.target.value)} placeholder="Nama" required value={name} />
        <input aria-label="Jabatan" onChange={e => setTitle(e.target.value)} placeholder="Jabatan" value={title} />
        <select aria-label="Melapor ke" onChange={e => setReportsTo(e.target.value)} value={reportsTo}>
          <option value="">Melapor ke kamu</option>
          {agents.map(a => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        {units.length > 0 && (
          <select aria-label="Unit" onChange={e => setUnit(e.target.value)} value={unit}>
            <option value="">Tanpa unit</option>
            {units.map(u => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <textarea
        aria-label="Deskripsi kerja"
        onChange={e => setJob(e.target.value)}
        placeholder="Deskripsi kerja"
        rows={2}
        value={job}
      />
      <button className="nv-co-btn" data-variant="primary" disabled={busy || !name.trim()} type="submit">
        Rekrut
      </button>
      <ErrorLine error={error} />
    </form>
  )
}

function UnitForm({ parent, units }: { parent?: CompanyUnit; units: CompanyUnit[] }) {
  const [name, setName] = useState('')
  const [parentId, setParentId] = useState(parent ? String(parent.id) : '')
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('unit.save', {
        kind: parentId ? 'agency' : 'organisasi',
        name,
        parent_id: parentId ? Number(parentId) : null
      })
      setName('')
    })
  }

  return (
    <form className="nv-co-form nv-co-card" onSubmit={submit}>
      <h3>Tambah organisasi / agency</h3>
      <div className="nv-co-row">
        <input aria-label="Nama unit" onChange={e => setName(e.target.value)} placeholder="Nama" required value={name} />
        <select aria-label="Di bawah" onChange={e => setParentId(e.target.value)} value={parentId}>
          <option value="">Organisasi baru (paling atas)</option>
          {units.map(u => (
            <option key={u.id} value={u.id}>
              Agency di bawah {u.name}
            </option>
          ))}
        </select>
      </div>
      <button className="nv-co-btn" data-variant="primary" disabled={busy || !name.trim()} type="submit">
        Tambah
      </button>
      <ErrorLine error={error} />
    </form>
  )
}

function UnitRow({ depth, people, unit }: { depth: number; people: number; unit: CompanyUnit }) {
  const [error, run, busy] = useAction()

  return (
    <li className="nv-co-node" data-kind={unit.kind} style={{ marginLeft: `${depth * 1.5}rem` }}>
      <div className="nv-co-node-head">
        <span className="nv-co-node-name">{unit.name}</span>
        <span className="nv-co-node-title">{unit.kind === 'organisasi' ? 'Organisasi' : 'Agency'}</span>
        <span className="nv-co-pill">{people} orang</span>
        <button
          className="nv-co-btn"
          data-variant="danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Hapus ${unit.name}? Isinya pindah ke unit di atasnya.`)) {
              void run(() => companyCall('unit.delete', { id: unit.id }))
            }
          }}
          type="button"
        >
          Hapus
        </button>
      </div>
      <ErrorLine error={error} />
    </li>
  )
}

export function OrgChart({ snap }: { snap: CompanySnapshot }) {
  const active = new Set(snap.active_agents ?? [])
  const units = Array.isArray(snap.units) ? snap.units : []
  const tree = unitTree(units)
  const ordered = tree.map(t => t.unit)

  return (
    <div className="nv-co-split">
      <div>
        {tree.length > 0 && (
          <ul aria-label="Organisasi dan agency" className="nv-co-org" data-slot="nv-company-units">
            {tree.map(({ depth, unit }) => (
              <UnitRow
                depth={depth}
                key={unit.id}
                people={snap.agents.filter(a => a.unit_id === unit.id).length}
                unit={unit}
              />
            ))}
          </ul>
        )}
        <ul aria-label="Struktur organisasi" className="nv-co-org" data-slot="nv-company-org">
          {snap.agents.length === 0 && (
            <li className="nv-co-empty">
              Belum ada pegawai. Rekrut di sini, atau minta Neovarch Agent di Chat (“rekrut Sinta sebagai copywriter di
              agency Kreatif”).
            </li>
          )}
          {orgTree(snap.agents).map(({ agent, depth }) => (
            <AgentNode
              agent={agent}
              agents={snap.agents}
              depth={depth}
              key={agent.id}
              running={active.has(agent.id) || agent.status === 'running'}
              units={ordered}
            />
          ))}
        </ul>
      </div>
      <div>
        <UnitForm units={ordered} />
        <HireForm agents={snap.agents} units={ordered} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- tickets --

function useTickets(): [CompanyTicket[], null | string] {
  const rev = useStore($companyRev)
  const [tickets, setTickets] = useState<CompanyTicket[]>([])
  const [error, setError] = useState<null | string>(null)

  useEffect(() => {
    let alive = true

    companyCall<{ tickets: CompanyTicket[] }>('ticket.list')
      .then(res => {
        if (alive) {
          setTickets(Array.isArray(res?.tickets) ? res.tickets : [])
          setError(null)
        }
      })
      .catch(e => {
        if (alive) {
          setError(e instanceof Error ? e.message : String(e))
        }
      })

    return () => {
      alive = false
    }
  }, [rev])

  return [tickets, error]
}

function NewTicket({ snap }: { snap: CompanySnapshot }) {
  const [title, setTitle] = useState('')
  const [assignee, setAssignee] = useState('')
  const [project, setProject] = useState('')
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('ticket.save', {
        assignee_id: assignee ? Number(assignee) : null,
        project_id: project ? Number(project) : null,
        title
      })
      setTitle('')
    })
  }

  return (
    <form className="nv-co-row nv-co-newticket" onSubmit={submit}>
      <input
        aria-label="Judul tiket"
        onChange={e => setTitle(e.target.value)}
        placeholder="Tiket baru…"
        required
        value={title}
      />
      <select aria-label="Penanggung jawab" onChange={e => setAssignee(e.target.value)} value={assignee}>
        <option value="">Tanpa penanggung jawab</option>
        {snap.agents
          .filter(a => a.status !== 'pending_approval')
          .map(a => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
      </select>
      {snap.projects.length > 0 && (
        <select aria-label="Proyek" onChange={e => setProject(e.target.value)} value={project}>
          <option value="">Tanpa proyek</option>
          {snap.projects.map(p => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      <button className="nv-co-btn" data-variant="primary" disabled={busy || !title.trim()} type="submit">
        Tambah
      </button>
      <ErrorLine error={error} />
    </form>
  )
}

export function TicketDetailPanel({
  id,
  onClose,
  snap,
  tickets = []
}: {
  id: number
  onClose: () => void
  snap: CompanySnapshot
  tickets?: CompanyTicket[]
}) {
  const rev = useStore($companyRev)
  const [detail, setDetail] = useState<null | TicketDetail>(null)
  const [comment, setComment] = useState('')
  const [loadError, setLoadError] = useState<null | string>(null)
  const [error, run, busy] = useAction()

  useEffect(() => {
    let alive = true

    companyCall<TicketDetail>('ticket.get', { id })
      .then(d => {
        if (alive) {
          setDetail(d)
          setLoadError(null)
        }
      })
      .catch(e => {
        if (alive) {
          setDetail(null)
          setLoadError(e instanceof Error ? e.message : String(e))
        }
      })

    return () => {
      alive = false
    }
  }, [id, rev])

  if (!detail) {
    return (
      <aside className="nv-co-detail">
        {loadError ? (
          <div className="nv-co-empty" role="alert">
            <p>Tiket belum bisa dimuat: {loadError}</p>
            <button className="nv-co-btn" onClick={onClose} type="button">
              Tutup
            </button>
          </div>
        ) : (
          <p className="nv-co-empty">Memuat tiket…</p>
        )}
      </aside>
    )
  }

  const reload = async () => setDetail(await companyCall<TicketDetail>('ticket.get', { id }))

  return (
    <aside aria-label={`Tiket ${detail.key}`} className="nv-co-detail" data-slot="nv-company-ticket">
      <header className="nv-co-row nv-co-detail-head">
        <span className="nv-co-key">{detail.key}</span>
        <span className="nv-co-pill" data-ticket={detail.status}>
          {TICKET_LABEL[detail.status]}
        </span>
        {detail.locked && <span className="nv-co-chip">sedang dikerjakan</span>}
        <button aria-label="Tutup" className="nv-co-btn nv-co-close" onClick={onClose} type="button">
          ×
        </button>
      </header>
      <h3>{detail.title}</h3>
      {detail.description && <p className="nv-co-desc">{detail.description}</p>}
      {detail.ancestry.length > 0 && (
        <p className="nv-co-ancestry" title="Kenapa tiket ini ada">
          {detail.ancestry.map(a => (a.key ? `${a.key} ${a.title}` : a.title)).join(' → ')}
        </p>
      )}
      <div className="nv-co-row">
        <select
          aria-label="Penanggung jawab"
          disabled={busy || detail.locked}
          onChange={e =>
            void run(async () => {
              await companyCall('ticket.assign', {
                agent_id: e.target.value ? Number(e.target.value) : null,
                id
              })
              await reload()
            })
          }
          value={detail.assignee_id ?? ''}
        >
          <option value="">Tanpa penanggung jawab</option>
          {snap.agents.map(a => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        {TICKET_TRANSITIONS[detail.status].map(to => (
          <button
            className="nv-co-btn"
            data-to={to}
            disabled={busy}
            key={to}
            onClick={() =>
              void run(async () => {
                await companyCall('ticket.move', { id, status: to })
                await reload()
              })
            }
            type="button"
          >
            {to === 'todo' && (detail.status === 'done' || detail.status === 'cancelled')
              ? 'Buka lagi'
              : `→ ${TICKET_LABEL[to]}`}
          </button>
        ))}
      </div>
      <ErrorLine error={error} />
      <TicketBlockers detail={detail} onChanged={reload} tickets={tickets} />
      {detail.children.length > 0 && (
        <p className="nv-co-desc">
          Subtiket: {detail.children.map(c => `${c.key} (${TICKET_LABEL[c.status]})`).join(', ')}
        </p>
      )}
      {detail.work_products.length > 0 && (
        <ul className="nv-co-list">
          {detail.work_products.map(w => (
            <li key={w.id}>
              <strong>{w.title}</strong> <span className="nv-co-mono">{w.ref}</span>
            </li>
          ))}
        </ul>
      )}
      <ol className="nv-co-thread" data-slot="nv-company-thread">
        {detail.comments.map(c => (
          <li data-author={c.author_type} key={c.id}>
            <span className="nv-co-who">{c.author_name || (c.author_type === 'user' ? 'Kamu' : 'Sistem')}</span>
            <time>{relativeTime(c.created_at, now())}</time>
            <p>{c.body}</p>
          </li>
        ))}
      </ol>
      <form
        className="nv-co-row"
        onSubmit={e => {
          e.preventDefault()
          void run(async () => {
            await companyCall('ticket.comment', { body: comment, id })
            setComment('')
            await reload()
          })
        }}
      >
        <input
          aria-label="Komentar"
          onChange={e => setComment(e.target.value)}
          placeholder="Tulis komentar…"
          value={comment}
        />
        <button className="nv-co-btn" disabled={busy || !comment.trim()} type="submit">
          Kirim
        </button>
      </form>
    </aside>
  )
}

export function TicketBoard({ snap }: { snap: CompanySnapshot }) {
  const [tickets, error] = useTickets()
  const [open, setOpen] = useState<null | number>(null)
  const byStatus = (s: TicketStatus) => tickets.filter(t => t.status === s)

  return (
    <div className="nv-co-tickets">
      <NewTicket snap={snap} />
      <ErrorLine error={error} />
      <div className="nv-co-board-wrap">
        <div aria-label="Papan tiket" className="nv-co-board" data-slot="nv-company-board">
          {TICKET_COLUMNS.map(col => (
            <section className="nv-co-col" data-status={col.status} key={col.status}>
              <h3>
                {col.label} <span>{byStatus(col.status).length}</span>
              </h3>
              {byStatus(col.status).map(t => (
                <button
                  className="nv-co-ticket"
                  data-ticket={t.key}
                  key={t.id}
                  onClick={() => setOpen(t.id)}
                  type="button"
                >
                  <span className="nv-co-key">{t.key}</span>
                  <span className="nv-co-ticket-title">{t.title}</span>
                  <span className="nv-co-ticket-meta">
                    {t.assignee_name || 'Belum ditugaskan'}
                    {t.locked ? ' · dikerjakan' : ''}
                    {t.blocked_by ? ` · ${t.blocked_by} hambatan` : ''}
                  </span>
                </button>
              ))}
            </section>
          ))}
        </div>
        {open !== null && <TicketDetailPanel id={open} onClose={() => setOpen(null)} snap={snap} tickets={tickets} />}
      </div>
    </div>
  )
}

// -------------------------------------------------------------- approvals --

export function Approvals() {
  const rev = useStore($companyRev)
  const [items, setItems] = useState<CompanyApproval[]>([])
  const [history, setHistory] = useState(false)
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [error, run, busy] = useAction()

  const load = useCallback(async () => {
    const res = await companyCall<{ approvals: CompanyApproval[] }>('approval.list', {
      status: history ? null : 'pending'
    })

    setItems(Array.isArray(res?.approvals) ? res.approvals : [])
  }, [history])

  const [loadError, setLoadError] = useState<null | string>(null)

  useEffect(() => {
    load()
      .then(() => setLoadError(null))
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [load, rev])

  const decide = (id: number, decision: 'approve' | 'reject') =>
    void run(async () => {
      await companyCall('approval.decide', {
        decision,
        id,
        note: notes[id] ?? ''
      })
      await load()
    })

  return (
    <div className="nv-co-approvals" data-slot="nv-company-approvals">
      <label className="nv-co-switch">
        <input checked={history} onChange={e => setHistory(e.target.checked)} type="checkbox" />
        <span>Tampilkan riwayat</span>
      </label>
      <ErrorLine error={error ?? (loadError ? `Persetujuan belum bisa dimuat: ${loadError}` : null)} />
      {items.length === 0 && !loadError && (
        <p className="nv-co-empty">{history ? 'Belum ada riwayat persetujuan.' : 'Tidak ada yang menunggu persetujuanmu.'}</p>
      )}
      <ul className="nv-co-list">
        {items.map(ap => (
          <li className="nv-co-card" data-status={ap.status} key={ap.id}>
            <div className="nv-co-row">
              <span className="nv-co-chip">{APPROVAL_KIND_LABEL[ap.kind]}</span>
              <strong>{ap.title}</strong>
              <time>{relativeTime(ap.created_at, now())}</time>
            </div>
            {typeof ap.payload.plan === 'string' && <p className="nv-co-desc">{ap.payload.plan}</p>}
            {typeof ap.payload.summary === 'string' && <p className="nv-co-desc">{ap.payload.summary}</p>}
            {ap.status === 'pending' ? (
              <div className="nv-co-row">
                <input
                  aria-label="Catatan"
                  onChange={e => setNotes({ ...notes, [ap.id]: e.target.value })}
                  placeholder="Catatan (opsional)"
                  value={notes[ap.id] ?? ''}
                />
                <button
                  className="nv-co-btn"
                  data-variant="primary"
                  disabled={busy}
                  onClick={() => decide(ap.id, 'approve')}
                  type="button"
                >
                  Setujui
                </button>
                <button className="nv-co-btn" disabled={busy} onClick={() => decide(ap.id, 'reject')} type="button">
                  Tolak
                </button>
              </div>
            ) : (
              <p className="nv-co-desc">
                {ap.status === 'approved' ? 'Disetujui' : ap.status === 'rejected' ? 'Ditolak' : 'Dibatalkan'}
                {ap.note ? ` — ${ap.note}` : ''}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ costs --

function Meter({ pct, level }: { level?: string; pct: null | number }) {
  if (pct === null) {
    return <span className="nv-co-muted">tanpa batas</span>
  }

  return (
    <span className="nv-co-meter-wrap">
      <span className="nv-co-meter" data-level={level ?? (pct >= 100 ? 'exceeded' : 'ok')}>
        <i style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
      {pct}%
    </span>
  )
}

export function Costs() {
  const rev = useStore($companyRev)
  const [costs, setCosts] = useState<CompanyCosts | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [loadError, setLoadError] = useState<null | string>(null)
  const [retry, setRetry] = useState(0)
  const [error, run, busy] = useAction()

  useEffect(() => {
    companyCall<CompanyCosts>('costs')
      .then(c => {
        setLoadError(null)
        setCosts(c)
        setForm({
          budget_monthly_cents: String(c.budget_monthly_cents),
          budget_monthly_tokens: String(c.budget_monthly_tokens),
          price_in_per_mtok: String(c.price_in_per_mtok),
          price_out_per_mtok: String(c.price_out_per_mtok),
          warn_pct: String(c.warn_pct)
        })
      })
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [rev, retry])

  if (loadError && !costs) {
    return (
      <div className="nv-co-empty" role="alert">
        <p>Biaya belum bisa dimuat: {loadError}</p>
        <button className="nv-co-btn" onClick={() => setRetry(n => n + 1)} type="button">
          Coba lagi
        </button>
      </div>
    )
  }

  if (!costs || !Array.isArray(costs.by_agent) || !costs.total) {
    return <p className="nv-co-empty">Memuat biaya…</p>
  }

  const field = (key: string, label: string) => (
    <label key={key}>
      {label}
      <input inputMode="decimal" onChange={e => setForm({ ...form, [key]: e.target.value })} value={form[key] ?? ''} />
    </label>
  )

  return (
    <div className="nv-co-costs" data-slot="nv-company-costs">
      <div className="nv-co-card">
        <p className="nv-co-big">
          {formatCents(costs.total.cents)} · {formatTokens(costs.total.tokens)}
        </p>
        <p className="nv-co-muted">Bulan {costs.month} (UTC)</p>
        <Meter level={costs.total.level} pct={costs.total.pct} />
      </div>
      <table className="nv-co-table">
        <thead>
          <tr>
            <th>Pegawai</th>
            <th>Biaya</th>
            <th>Token</th>
            <th>Anggaran</th>
          </tr>
        </thead>
        <tbody>
          {costs.by_agent.length === 0 && (
            <tr>
              <td className="nv-co-muted" colSpan={4}>
                Belum ada pegawai.
              </td>
            </tr>
          )}
          {costs.by_agent.map(r => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td>{formatCents(r.cents)}</td>
              <td>{formatTokens(r.tokens)}</td>
              <td>
                <Meter pct={r.pct} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {Array.isArray(costs.by_project) && costs.by_project.length > 0 && (
        <table className="nv-co-table">
          <thead>
            <tr>
              <th>Proyek</th>
              <th>Biaya</th>
              <th>Token</th>
              <th>Anggaran</th>
            </tr>
          </thead>
          <tbody>
            {costs.by_project.map(r => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{formatCents(r.cents)}</td>
                <td>{formatTokens(r.tokens)}</td>
                <td>
                  <Meter pct={r.pct} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        className="nv-co-form nv-co-card"
        onSubmit={e => {
          e.preventDefault()
          void run(() =>
            companyCall('update', {
              budget_monthly_cents: Math.round(Number(form.budget_monthly_cents) || 0),
              budget_monthly_tokens: Math.round(Number(form.budget_monthly_tokens) || 0),
              price_in_per_mtok: Number(form.price_in_per_mtok) || 0,
              price_out_per_mtok: Number(form.price_out_per_mtok) || 0,
              warn_pct: Math.round(Number(form.warn_pct) || 80)
            })
          )
        }}
      >
        <h3>Anggaran perusahaan (0 = tanpa batas)</h3>
        <div className="nv-co-grid">
          {field('budget_monthly_cents', 'Batas per bulan (sen USD)')}
          {field('budget_monthly_tokens', 'Batas token per bulan')}
          {field('price_in_per_mtok', 'Harga input (sen / 1 jt token)')}
          {field('price_out_per_mtok', 'Harga output (sen / 1 jt token)')}
          {field('warn_pct', 'Peringatan di (%)')}
        </div>
        <p className="nv-co-muted">
          Anggaran per pegawai diatur lewat “Ubah” di tab Organisasi; anggaran proyek di tab Tujuan. Saat anggaran pegawai habis, pegawai itu otomatis dijeda sampai kamu menaikkan anggarannya.
        </p>
        <button className="nv-co-btn" data-variant="primary" disabled={busy} type="submit">
          Simpan
        </button>
        <ErrorLine error={error} />
      </form>
    </div>
  )
}

// --------------------------------------------------------------- activity --

export function ActivityLog() {
  const rev = useStore($companyRev)
  const [items, setItems] = useState<CompanyActivity[]>([])
  const [loadError, setLoadError] = useState<null | string>(null)

  useEffect(() => {
    companyCall<{ items: CompanyActivity[] }>('activity', { limit: 150 })
      .then(res => {
        setItems(Array.isArray(res?.items) ? res.items : [])
        setLoadError(null)
      })
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [rev])

  return (
    <ol className="nv-co-activity" data-slot="nv-company-activity">
      {loadError && (
        <li className="nv-co-error" role="alert">
          Aktivitas belum bisa dimuat: {loadError}
        </li>
      )}
      {items.length === 0 && !loadError && <li className="nv-co-empty">Belum ada aktivitas.</li>}
      {items.map(item => (
        <li data-action={item.action} key={item.id}>
          <span className="nv-co-who">{item.actor_name}</span>
          <span>{item.summary}</span>
          <time>{relativeTime(item.ts, now())}</time>
        </li>
      ))}
    </ol>
  )
}

// ------------------------------------------------------------------ panel --

/** The Perusahaan views inside the Kantor. Without a company only the setup card shows. */
export function CompanyPanel({ tab }: { tab: CompanyTab }) {
  const snap = useStore($company)
  const error = useStore($companyError)

  if (error && !snap) {
    return <p className="nv-co-empty">Data perusahaan belum bisa dimuat: {error}</p>
  }

  if (snap === null) {
    return <p className="nv-co-empty">Memuat perusahaan…</p>
  }

  if (!hasCompany(snap)) {
    return <CompanySetup />
  }

  return (
    <div className="nv-co" data-slot="nv-company" data-tab={tab}>
      <CompanyBar snap={snap} />
      {tab === 'org' && <OrgChart snap={snap} />}
      {tab === 'tickets' && <TicketBoard snap={snap} />}
      {tab === 'goals' && <GoalsAndProjects snap={snap} />}
      {tab === 'routines' && <Routines snap={snap} />}
      {tab === 'approvals' && <Approvals />}
      {tab === 'costs' && <Costs />}
      {tab === 'activity' && <ActivityLog />}
    </div>
  )
}
