import { useStore } from '@nanostores/react'
import { type FormEvent, useEffect, useMemo, useState } from 'react'

import { $gateway } from '@/store/gateway'

import {
  type CompanyAgent,
  companyCall,
  type CompanyGoal,
  type CompanyProject,
  type CompanyRoutine,
  type CompanySnapshot,
  type CompanyTicket,
  formatCents,
  GOAL_STATUS_LABEL,
  TICKET_LABEL,
  type TicketDetail
} from './company-store'
import { ErrorLine, idOrNull, useAction, wholeOrNull } from './company-ui'
import { relativeTime } from './office-store'

/** Extra Perusahaan views: goals/projects, routines, the agent editor (budget, heartbeat, model) and ticket
 *  blockers. Every write goes through the core's `company.*` RPCs; the core re-validates everything. */

const now = () => Date.now() / 1000

/** Delete with a second click instead of a modal ("Hapus" → "Yakin hapus?"). */
function ConfirmButton({
  busy,
  label = 'Hapus',
  onConfirm
}: {
  busy: boolean
  label?: string
  onConfirm: () => void
}) {
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) {
      return
    }

    const t = setTimeout(() => setArmed(false), 4000)

    return () => clearTimeout(t)
  }, [armed])

  return (
    <button
      className="nv-co-btn"
      data-variant={armed ? 'danger' : undefined}
      disabled={busy}
      onClick={() => {
        if (armed) {
          setArmed(false)
          onConfirm()
        } else {
          setArmed(true)
        }
      }}
      type="button"
    >
      {armed ? `Yakin ${label.toLowerCase()}?` : label}
    </button>
  )
}

// ------------------------------------------------------------ model pick --

interface ModelOptionsResponse {
  model?: string
  provider?: string
  providers?: { models?: unknown; name?: string; slug?: string }[]
}

export interface CompanyModelOption {
  label: string
  model: string
  provider: string
}

const SEP = '\u0001'

/** Flattens `model.options` (the same catalog the composer and Settings → Model read) into picker rows. */
export function companyModelOptions(res: ModelOptionsResponse | null | undefined): CompanyModelOption[] {
  const out: CompanyModelOption[] = []
  const seen = new Set<string>()

  for (const p of Array.isArray(res?.providers) ? res.providers : []) {
    const slug = typeof p?.slug === 'string' ? p.slug : ''
    const models = Array.isArray(p?.models) ? p.models : []

    for (const m of models) {
      if (typeof m !== 'string' || !m || seen.has(slug + SEP + m)) {
        continue
      }

      seen.add(slug + SEP + m)
      out.push({ label: `${m} · ${p.name || slug}`, model: m, provider: slug })
    }
  }

  return out
}

/** Per-agent model: empty = the PC's default model. Reuses the core's `model.options` route. */
export function CompanyModelSelect({
  disabled,
  model,
  onChange,
  provider,
  sessionId
}: {
  disabled?: boolean
  model: string
  onChange: (model: string, provider: string) => void
  provider: string
  sessionId?: null | string
}) {
  const gateway = useStore($gateway)
  const [options, setOptions] = useState<CompanyModelOption[]>([])
  const [error, setError] = useState<null | string>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true

    if (!gateway) {
      setError('Belum terhubung ke core')

      return
    }

    gateway
      .request<ModelOptionsResponse>('model.options', sessionId ? { session_id: sessionId } : {})
      .then(res => {
        if (alive) {
          setOptions(companyModelOptions(res))
          setError(null)
          setLoaded(true)
        }
      })
      .catch(e => {
        if (alive) {
          setError(e instanceof Error ? e.message : String(e))
          setLoaded(true)
        }
      })

    return () => {
      alive = false
    }
  }, [gateway, sessionId])

  const value = model ? provider + SEP + model : ''
  const known = !model || options.some(o => o.model === model && o.provider === provider)

  return (
    <div className="nv-co-model" data-slot="nv-company-model">
      <select
        aria-label="Model pegawai"
        disabled={disabled}
        onChange={e => {
          const [p = '', m = ''] = e.target.value ? e.target.value.split(SEP) : []
          onChange(m, p)
        }}
        value={value}
      >
        <option value="">Model bawaan PC</option>
        {!known && <option value={value}>{provider ? `${model} · ${provider}` : model}</option>}
        {options.map(o => (
          <option key={o.provider + SEP + o.model} value={o.provider + SEP + o.model}>
            {o.label}
          </option>
        ))}
      </select>
      {loaded && !error && options.length === 0 && (
        <p className="nv-co-muted">Belum ada penyedia model. Atur di Pengaturan → Model.</p>
      )}
      {error && <p className="nv-co-muted">Daftar model belum bisa dimuat: {error}</p>}
    </div>
  )
}

// ---------------------------------------------------------- agent editor --

/** Edit one employee: profile, manager, heartbeat, monthly budget and model. */
export function AgentEditor({
  agent,
  agents,
  onClose
}: {
  agent: CompanyAgent
  agents: CompanyAgent[]
  onClose: () => void
}) {
  const [form, setForm] = useState({
    budget_monthly_cents: String(agent.budget_monthly_cents || 0),
    budget_monthly_tokens: String(agent.budget_monthly_tokens || 0),
    heartbeat_s: String(agent.heartbeat_s || 0),
    job_description: agent.job_description || '',
    model: agent.model || '',
    name: agent.name,
    provider: agent.provider || '',
    reports_to: agent.reports_to === null ? '' : String(agent.reports_to),
    title: agent.title || ''
  })

  const [error, run, busy] = useAction()
  const [localError, setLocalError] = useState<null | string>(null)
  const set = (key: keyof typeof form, value: string) => setForm(f => ({ ...f, [key]: value }))

  // A manager may not be the agent itself or anyone below it (the core rejects cycles too).
  const managers = useMemo(() => {
    const below = new Set<number>([agent.id])
    let grew = true

    while (grew) {
      grew = false

      for (const a of agents) {
        if (a.reports_to !== null && below.has(a.reports_to) && !below.has(a.id)) {
          below.add(a.id)
          grew = true
        }
      }
    }

    return agents.filter(a => !below.has(a.id) && a.status !== 'terminated')
  }, [agent.id, agents])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const cents = wholeOrNull(form.budget_monthly_cents)
    const tokens = wholeOrNull(form.budget_monthly_tokens)
    const heartbeat = wholeOrNull(form.heartbeat_s)

    if (cents === null || tokens === null || heartbeat === null) {
      setLocalError('Anggaran dan detak harus angka 0 atau lebih.')

      return
    }

    if (!form.name.trim()) {
      setLocalError('Nama wajib diisi.')

      return
    }

    setLocalError(null)
    void run(async () => {
      await companyCall('agent.save', {
        budget_monthly_cents: cents,
        budget_monthly_tokens: tokens,
        heartbeat_s: heartbeat,
        id: agent.id,
        job_description: form.job_description,
        model: form.model,
        name: form.name.trim(),
        provider: form.provider,
        reports_to: idOrNull(form.reports_to),
        title: form.title
      })
      onClose()
    })
  }

  return (
    <form aria-label={`Ubah ${agent.name}`} className="nv-co-form nv-co-card nv-co-editor" onSubmit={submit}>
      <div className="nv-co-grid">
        <label>
          Nama
          <input onChange={e => set('name', e.target.value)} required value={form.name} />
        </label>
        <label>
          Jabatan
          <input onChange={e => set('title', e.target.value)} value={form.title} />
        </label>
        <label>
          Melapor ke
          <select onChange={e => set('reports_to', e.target.value)} value={form.reports_to}>
            <option value="">Kamu (pemilik)</option>
            {managers.map(a => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Detak (detik, 0 = hanya saat ada kejadian)
          <input inputMode="numeric" onChange={e => set('heartbeat_s', e.target.value)} value={form.heartbeat_s} />
        </label>
        <label>
          Anggaran per bulan (sen USD, 0 = tanpa batas)
          <input
            inputMode="numeric"
            onChange={e => set('budget_monthly_cents', e.target.value)}
            value={form.budget_monthly_cents}
          />
        </label>
        <label>
          Batas token per bulan (0 = tanpa batas)
          <input
            inputMode="numeric"
            onChange={e => set('budget_monthly_tokens', e.target.value)}
            value={form.budget_monthly_tokens}
          />
        </label>
      </div>
      <label>
        Model
        <CompanyModelSelect
          disabled={busy}
          model={form.model}
          onChange={(model, provider) => setForm(f => ({ ...f, model, provider }))}
          provider={form.provider}
          sessionId={agent.session_id}
        />
      </label>
      <label>
        Deskripsi kerja
        <textarea onChange={e => set('job_description', e.target.value)} rows={2} value={form.job_description} />
      </label>
      <div className="nv-co-row">
        <button className="nv-co-btn" data-variant="primary" disabled={busy} type="submit">
          Simpan
        </button>
        <button className="nv-co-btn" disabled={busy} onClick={onClose} type="button">
          Batal
        </button>
        <span className="nv-co-spacer" />
        <ConfirmButton
          busy={busy}
          label="Berhentikan"
          onConfirm={() =>
            void run(async () => {
              await companyCall('agent.terminate', { id: agent.id })
              onClose()
            })
          }
        />
      </div>
      <ErrorLine error={localError ?? error} />
    </form>
  )
}

// ------------------------------------------------------- goals/projects --

function goalTree(goals: CompanyGoal[]): { depth: number; goal: CompanyGoal }[] {
  const ids = new Set(goals.map(g => g.id))
  const out: { depth: number; goal: CompanyGoal }[] = []
  const seen = new Set<number>()

  const walk = (parent: null | number, depth: number) => {
    for (const g of goals) {
      const key = g.parent_id !== null && ids.has(g.parent_id) ? g.parent_id : null

      if (key === parent && !seen.has(g.id)) {
        seen.add(g.id)
        out.push({ depth, goal: g })
        walk(g.id, depth + 1)
      }
    }
  }

  walk(null, 0)

  return out
}

/** Goal ids that may be `goal`'s parent: anything but itself and its descendants. */
function parentChoices(goals: CompanyGoal[], goal: CompanyGoal | null): CompanyGoal[] {
  if (!goal) {
    return goals
  }

  const below = new Set<number>([goal.id])
  let grew = true

  while (grew) {
    grew = false

    for (const g of goals) {
      if (g.parent_id !== null && below.has(g.parent_id) && !below.has(g.id)) {
        below.add(g.id)
        grew = true
      }
    }
  }

  return goals.filter(g => !below.has(g.id))
}

function GoalForm({ goal, goals, onDone }: { goal: CompanyGoal | null; goals: CompanyGoal[]; onDone: () => void }) {
  const [title, setTitle] = useState(goal?.title ?? '')
  const [description, setDescription] = useState(goal?.description ?? '')
  const [parent, setParent] = useState(goal?.parent_id ? String(goal.parent_id) : '')
  const [status, setStatus] = useState(goal?.status || 'active')
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('goal.save', {
        ...(goal ? { id: goal.id, status } : {}),
        description,
        parent_id: idOrNull(parent),
        title: title.trim()
      })

      if (!goal) {
        setTitle('')
        setDescription('')
        setParent('')
      }

      onDone()
    })
  }

  return (
    <form
      aria-label={goal ? `Ubah tujuan ${goal.title}` : 'Tujuan baru'}
      className="nv-co-form nv-co-card"
      onSubmit={submit}
    >
      {!goal && <h3>Tujuan baru</h3>}
      <div className="nv-co-row">
        <input
          aria-label="Judul tujuan"
          onChange={e => setTitle(e.target.value)}
          placeholder="mis. Rilis versi 1.5 dengan stabil"
          required
          value={title}
        />
        <select aria-label="Tujuan induk" onChange={e => setParent(e.target.value)} value={parent}>
          <option value="">Langsung di bawah misi</option>
          {parentChoices(goals, goal).map(g => (
            <option key={g.id} value={g.id}>
              {g.title}
            </option>
          ))}
        </select>
        {goal && (
          <select aria-label="Status tujuan" onChange={e => setStatus(e.target.value)} value={status}>
            {Object.entries(GOAL_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
      </div>
      <textarea
        aria-label="Keterangan tujuan"
        onChange={e => setDescription(e.target.value)}
        placeholder="Kenapa tujuan ini penting (opsional)"
        rows={2}
        value={description}
      />
      <div className="nv-co-row">
        <button className="nv-co-btn" data-variant="primary" disabled={busy || !title.trim()} type="submit">
          {goal ? 'Simpan' : 'Tambah tujuan'}
        </button>
        {goal && (
          <button className="nv-co-btn" disabled={busy} onClick={onDone} type="button">
            Batal
          </button>
        )}
      </div>
      <ErrorLine error={error} />
    </form>
  )
}

function ProjectForm({
  goals,
  onDone,
  project
}: {
  goals: CompanyGoal[]
  onDone: () => void
  project: CompanyProject | null
}) {
  const [name, setName] = useState(project?.name ?? '')
  const [description, setDescription] = useState(project?.description ?? '')
  const [goal, setGoal] = useState(project?.goal_id ? String(project.goal_id) : '')
  const [budget, setBudget] = useState(String(project?.budget_monthly_cents ?? 0))
  const [localError, setLocalError] = useState<null | string>(null)
  const [error, run, busy] = useAction()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const cents = wholeOrNull(budget)

    if (cents === null) {
      setLocalError('Anggaran harus angka 0 atau lebih.')

      return
    }

    setLocalError(null)
    void run(async () => {
      await companyCall('project.save', {
        ...(project ? { id: project.id } : {}),
        budget_monthly_cents: cents,
        description,
        goal_id: idOrNull(goal),
        name: name.trim()
      })

      if (!project) {
        setName('')
        setDescription('')
        setGoal('')
        setBudget('0')
      }

      onDone()
    })
  }

  return (
    <form
      aria-label={project ? `Ubah proyek ${project.name}` : 'Proyek baru'}
      className="nv-co-form nv-co-card"
      onSubmit={submit}
    >
      {!project && <h3>Proyek baru</h3>}
      <div className="nv-co-row">
        <input
          aria-label="Nama proyek"
          onChange={e => setName(e.target.value)}
          placeholder="mis. Aplikasi desktop"
          required
          value={name}
        />
        <select aria-label="Tujuan proyek" onChange={e => setGoal(e.target.value)} value={goal}>
          <option value="">Tanpa tujuan</option>
          {goals.map(g => (
            <option key={g.id} value={g.id}>
              {g.title}
            </option>
          ))}
        </select>
        <input
          aria-label="Anggaran proyek per bulan (sen USD)"
          inputMode="numeric"
          onChange={e => setBudget(e.target.value)}
          placeholder="Anggaran (sen)"
          title="Anggaran per bulan dalam sen USD, 0 = tanpa batas"
          value={budget}
        />
      </div>
      <textarea
        aria-label="Keterangan proyek"
        onChange={e => setDescription(e.target.value)}
        placeholder="Keterangan (opsional)"
        rows={2}
        value={description}
      />
      <div className="nv-co-row">
        <button className="nv-co-btn" data-variant="primary" disabled={busy || !name.trim()} type="submit">
          {project ? 'Simpan' : 'Tambah proyek'}
        </button>
        {project && (
          <button className="nv-co-btn" disabled={busy} onClick={onDone} type="button">
            Batal
          </button>
        )}
      </div>
      <ErrorLine error={localError ?? error} />
    </form>
  )
}

function MissionForm({ snap }: { snap: CompanySnapshot }) {
  const [mission, setMission] = useState(snap.company.mission)
  const [error, run, busy] = useAction()

  useEffect(() => setMission(snap.company.mission), [snap.company.mission])

  return (
    <form
      className="nv-co-form nv-co-card"
      onSubmit={e => {
        e.preventDefault()
        void run(() => companyCall('update', { mission }))
      }}
    >
      <h3>Misi perusahaan</h3>
      <textarea aria-label="Misi" onChange={e => setMission(e.target.value)} rows={2} value={mission} />
      <button
        className="nv-co-btn"
        data-variant="primary"
        disabled={busy || mission === snap.company.mission}
        type="submit"
      >
        Simpan misi
      </button>
      <ErrorLine error={error} />
    </form>
  )
}

/** "Tujuan" tab: the mission, the goal tree under it, and projects tied to goals (with their own budget). */
export function GoalsAndProjects({ snap }: { snap: CompanySnapshot }) {
  const goals = Array.isArray(snap.goals) ? snap.goals : []
  const projects = Array.isArray(snap.projects) ? snap.projects : []
  const [editGoal, setEditGoal] = useState<null | number>(null)
  const [editProject, setEditProject] = useState<null | number>(null)
  const [error, run, busy] = useAction()
  const goalName = (id: null | number) => goals.find(g => g.id === id)?.title

  return (
    <div className="nv-co-plan" data-slot="nv-company-goals">
      <div className="nv-co-plan-col">
        <MissionForm snap={snap} />
        <section aria-label="Tujuan" className="nv-co-card">
          <h3>Tujuan</h3>
          {goals.length === 0 && (
            <p className="nv-co-empty">
              Belum ada tujuan. Tujuan menjelaskan “kenapa” sebuah tiket ada, dan ikut dibaca setiap pegawai.
            </p>
          )}
          <ul className="nv-co-list">
            {goalTree(goals).map(({ depth, goal }) =>
              editGoal === goal.id ? (
                <li key={goal.id}>
                  <GoalForm goal={goal} goals={goals} onDone={() => setEditGoal(null)} />
                </li>
              ) : (
                <li className="nv-co-item" data-goal={goal.id} key={goal.id} style={{ marginLeft: `${depth * 1.25}rem` }}>
                  <div className="nv-co-row">
                    <strong>{goal.title}</strong>
                    <span className="nv-co-chip">{GOAL_STATUS_LABEL[goal.status] ?? goal.status}</span>
                    <span className="nv-co-spacer" />
                    <button className="nv-co-btn" disabled={busy} onClick={() => setEditGoal(goal.id)} type="button">
                      Ubah
                    </button>
                    <ConfirmButton
                      busy={busy}
                      onConfirm={() => void run(() => companyCall('goal.delete', { id: goal.id }))}
                    />
                  </div>
                  {goal.description && <p className="nv-co-desc">{goal.description}</p>}
                </li>
              )
            )}
          </ul>
          <ErrorLine error={error} />
        </section>
        <GoalForm goal={null} goals={goals} onDone={() => undefined} />
      </div>
      <div className="nv-co-plan-col">
        <section aria-label="Proyek" className="nv-co-card">
          <h3>Proyek</h3>
          {projects.length === 0 && <p className="nv-co-empty">Belum ada proyek.</p>}
          <ul className="nv-co-list">
            {projects.map(p =>
              editProject === p.id ? (
                <li key={p.id}>
                  <ProjectForm goals={goals} onDone={() => setEditProject(null)} project={p} />
                </li>
              ) : (
                <li className="nv-co-item" data-project={p.id} key={p.id}>
                  <div className="nv-co-row">
                    <strong>{p.name}</strong>
                    <span className="nv-co-muted">{goalName(p.goal_id) ?? 'Tanpa tujuan'}</span>
                    <span className="nv-co-chip">
                      {p.budget_monthly_cents > 0 ? `${formatCents(p.budget_monthly_cents)}/bln` : 'tanpa batas'}
                    </span>
                    <span className="nv-co-spacer" />
                    <button className="nv-co-btn" disabled={busy} onClick={() => setEditProject(p.id)} type="button">
                      Ubah
                    </button>
                    <ConfirmButton
                      busy={busy}
                      onConfirm={() => void run(() => companyCall('project.delete', { id: p.id }))}
                    />
                  </div>
                  {p.description && <p className="nv-co-desc">{p.description}</p>}
                </li>
              )
            )}
          </ul>
        </section>
        <ProjectForm goals={goals} onDone={() => undefined} project={null} />
      </div>
    </div>
  )
}

// -------------------------------------------------------------- routines --

const SCHEDULE_HINT = 'Contoh: every 1d, every 6h, 09:00 (setiap hari), atau cron “0 9 * * 1”'

function RoutineForm({
  onDone,
  routine,
  snap
}: {
  onDone: () => void
  routine: CompanyRoutine | null
  snap: CompanySnapshot
}) {
  const [form, setForm] = useState({
    agent_id: routine?.agent_id ? String(routine.agent_id) : '',
    description: routine?.description ?? '',
    name: routine?.name ?? '',
    project_id: routine?.project_id ? String(routine.project_id) : '',
    schedule: routine?.schedule ?? '',
    title: routine?.title ?? ''
  })

  const [error, run, busy] = useAction()
  const set = (key: keyof typeof form, value: string) => setForm(f => ({ ...f, [key]: value }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await companyCall('routine.save', {
        ...(routine ? { id: routine.id } : {}),
        agent_id: idOrNull(form.agent_id),
        description: form.description,
        name: form.name.trim(),
        project_id: idOrNull(form.project_id),
        schedule: form.schedule.trim(),
        title: form.title.trim() || form.name.trim()
      })

      if (!routine) {
        setForm({ agent_id: '', description: '', name: '', project_id: '', schedule: '', title: '' })
      }

      onDone()
    })
  }

  return (
    <form
      aria-label={routine ? `Ubah rutinitas ${routine.name}` : 'Rutinitas baru'}
      className="nv-co-form nv-co-card"
      onSubmit={submit}
    >
      {!routine && <h3>Rutinitas baru</h3>}
      <div className="nv-co-grid">
        <label>
          Nama
          <input onChange={e => set('name', e.target.value)} placeholder="mis. Ringkasan mingguan" required value={form.name} />
        </label>
        <label>
          Jadwal
          <input
            onChange={e => set('schedule', e.target.value)}
            placeholder="every 7d"
            required
            title={SCHEDULE_HINT}
            value={form.schedule}
          />
        </label>
        <label>
          Untuk pegawai
          <select onChange={e => set('agent_id', e.target.value)} value={form.agent_id}>
            <option value="">Belum ditugaskan</option>
            {snap.agents
              .filter(a => a.status !== 'pending_approval')
              .map(a => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Proyek
          <select onChange={e => set('project_id', e.target.value)} value={form.project_id}>
            <option value="">Tanpa proyek</option>
            {(snap.projects ?? []).map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Judul tiket yang dibuat
        <input onChange={e => set('title', e.target.value)} placeholder="Sama dengan nama" value={form.title} />
      </label>
      <textarea
        aria-label="Keterangan tiket"
        onChange={e => set('description', e.target.value)}
        placeholder="Isi tiket (opsional)"
        rows={2}
        value={form.description}
      />
      <p className="nv-co-muted">{SCHEDULE_HINT}</p>
      <div className="nv-co-row">
        <button
          className="nv-co-btn"
          data-variant="primary"
          disabled={busy || !form.name.trim() || !form.schedule.trim()}
          type="submit"
        >
          {routine ? 'Simpan' : 'Tambah rutinitas'}
        </button>
        {routine && (
          <button className="nv-co-btn" disabled={busy} onClick={onDone} type="button">
            Batal
          </button>
        )}
      </div>
      <ErrorLine error={error} />
    </form>
  )
}

/** "Rutinitas" tab: recurring work that becomes a ticket on schedule (only while the heartbeat is on). */
export function Routines({ snap }: { snap: CompanySnapshot }) {
  const routines = Array.isArray(snap.routines) ? snap.routines : []
  const [edit, setEdit] = useState<null | number>(null)
  const [error, run, busy] = useAction()
  const [notice, setNotice] = useState<null | string>(null)
  const agentName = (id: null | number | undefined) => snap.agents.find(a => a.id === id)?.name

  return (
    <div className="nv-co-plan" data-slot="nv-company-routines">
      <div className="nv-co-plan-col">
        {!snap.company.autorun && (
          <p className="nv-co-card nv-co-muted">
            Heartbeat Kantor sedang dijeda: rutinitas tidak membuat tiket sendiri. Pakai “Jalankan sekarang” untuk
            mencobanya.
          </p>
        )}
        <section aria-label="Rutinitas" className="nv-co-card">
          <h3>Rutinitas</h3>
          {routines.length === 0 && (
            <p className="nv-co-empty">Belum ada rutinitas. Contoh: laporan mingguan tiap Senin untuk Sari.</p>
          )}
          <ul className="nv-co-list">
            {routines.map(r =>
              edit === r.id ? (
                <li key={r.id}>
                  <RoutineForm onDone={() => setEdit(null)} routine={r} snap={snap} />
                </li>
              ) : (
                <li className="nv-co-item" data-routine={r.id} key={r.id}>
                  <div className="nv-co-row">
                    <strong>{r.name}</strong>
                    <span className="nv-co-chip nv-co-mono">{r.schedule}</span>
                    <span className="nv-co-muted">{agentName(r.agent_id) ?? 'Belum ditugaskan'}</span>
                    <span className="nv-co-spacer" />
                    <label className="nv-co-switch">
                      <input
                        aria-label={`Aktifkan ${r.name}`}
                        checked={Boolean(r.enabled)}
                        disabled={busy}
                        onChange={e =>
                          void run(() => companyCall('routine.save', { enabled: e.target.checked, id: r.id }))
                        }
                        type="checkbox"
                      />
                      <span>Aktif</span>
                    </label>
                  </div>
                  <p className="nv-co-muted">
                    {r.enabled && r.next_run_at
                      ? `Berikutnya ${new Date(r.next_run_at * 1000).toLocaleString('id-ID')}`
                      : 'Tidak terjadwal'}
                    {r.last_run_at ? ` · terakhir ${relativeTime(r.last_run_at, now())}` : ''}
                  </p>
                  <div className="nv-co-row">
                    <button
                      className="nv-co-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const t = await companyCall<CompanyTicket>('routine.trigger', { id: r.id })
                          setNotice(t?.key ? `Tiket ${t.key} dibuat.` : 'Tiket dibuat.')
                        })
                      }
                      type="button"
                    >
                      Jalankan sekarang
                    </button>
                    <button className="nv-co-btn" disabled={busy} onClick={() => setEdit(r.id)} type="button">
                      Ubah
                    </button>
                    <ConfirmButton
                      busy={busy}
                      onConfirm={() => void run(() => companyCall('routine.delete', { id: r.id }))}
                    />
                  </div>
                </li>
              )
            )}
          </ul>
          {notice && (
            <p className="nv-co-muted" role="status">
              {notice}
            </p>
          )}
          <ErrorLine error={error} />
        </section>
      </div>
      <div className="nv-co-plan-col">
        <RoutineForm onDone={() => undefined} routine={null} snap={snap} />
      </div>
    </div>
  )
}

// -------------------------------------------------------------- blockers --

/** Ticket detail: which tickets block this one; add (with any open ticket) or remove. */
export function TicketBlockers({
  detail,
  onChanged,
  tickets
}: {
  detail: TicketDetail
  onChanged: () => Promise<unknown>
  tickets: CompanyTicket[]
}) {
  const [pick, setPick] = useState('')
  const [error, run, busy] = useAction()
  const current = new Set(detail.blockers.map(b => b.id))

  const choices = tickets.filter(
    t => t.id !== detail.id && !current.has(t.id) && t.status !== 'done' && t.status !== 'cancelled'
  )

  return (
    <section aria-label="Hambatan" className="nv-co-blockers" data-slot="nv-company-blockers">
      <p className="nv-co-desc">
        {detail.blockers.length === 0 ? 'Tidak ada hambatan.' : 'Terhambat oleh:'}
      </p>
      {detail.blockers.length > 0 && (
        <ul className="nv-co-list">
          {detail.blockers.map(b => (
            <li className="nv-co-row" key={b.id}>
              <span className="nv-co-key">{b.key}</span>
              <span>{b.title}</span>
              <span className="nv-co-pill" data-ticket={b.status}>
                {TICKET_LABEL[b.status]}
              </span>
              <button
                aria-label={`Lepas hambatan ${b.key}`}
                className="nv-co-btn"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await companyCall('ticket.unblock', { blocker_id: b.id, id: detail.id })
                    await onChanged()
                  })
                }
                type="button"
              >
                Lepas
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="nv-co-row">
        <select aria-label="Tambah hambatan" onChange={e => setPick(e.target.value)} value={pick}>
          <option value="">Pilih tiket penghambat…</option>
          {choices.map(t => (
            <option key={t.id} value={t.id}>
              {t.key} · {t.title}
            </option>
          ))}
        </select>
        <button
          className="nv-co-btn"
          disabled={busy || !pick}
          onClick={() =>
            void run(async () => {
              await companyCall('ticket.block', { blocker_id: Number(pick), id: detail.id })
              setPick('')
              await onChanged()
            })
          }
          type="button"
        >
          Tambah hambatan
        </button>
      </div>
      <ErrorLine error={error} />
    </section>
  )
}
