import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { useI18n } from '@/i18n'
import type { NvCrewTranslations } from '@/i18n/nv-crew'
import { cn } from '@/lib/utils'

import { CrewStation } from './crew-pixel'
import {
  $crew,
  $crewBusy,
  $crewError,
  $crews,
  answerCrewApproval,
  approveCrew,
  cancelCrew,
  closeCrew,
  type Crew,
  CREW_SIDE_EFFECT_TOOLS,
  CREW_TEMPLATES,
  CREW_TOOL_GROUPS,
  type CrewMember,
  type CrewTask,
  type CrewTemplateId,
  type CrewToolGroup,
  deleteCrew,
  fmt,
  introSeen,
  markIntroSeen,
  openCrew,
  proposeCrew,
  refreshCrews,
  updateCrew
} from './crew-store'
import { OFFICE_ROUTE } from './office-store'

export type CrewTab = 'advanced' | 'crew' | 'history'
export const CREW_TABS: CrewTab[] = ['crew', 'history', 'advanced']

/** Pixel room: every member at a desk with their live status. */
export function CrewRoom({ crew, s }: { crew: Crew; s: NvCrewTranslations }) {
  return (
    <div className="nv-crew-room" data-slot="nv-crew-room">
      {crew.members.map(m => (
        <figure className="nv-crew-seat" data-member={m.id} data-status={m.status} key={m.id}>
          <CrewStation avatar={m.avatar} label={`${m.name} · ${s.status[m.status] ?? m.status}`} status={m.status} />
          <figcaption>
            <span className="nv-crew-seat-name">
              {m.name}
              {crew.manager === m.id && <span className="nv-crew-badge">{s.manager}</span>}
            </span>
            <span className="nv-crew-seat-role">{m.role}</span>
            <span className="nv-crew-seat-status" data-status={m.status}>
              {s.status[m.status] ?? m.status}
              {m.activity ? ` · ${m.activity}` : ''}
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

function ToolChips({ s, tools }: { s: NvCrewTranslations; tools: CrewToolGroup[] }) {
  if (!tools.length) {
    return <span className="nv-crew-chip nv-crew-chip-muted">{s.noTools}</span>
  }

  return (
    <>
      {tools.map(t => (
        <span
          className={cn('nv-crew-chip', CREW_SIDE_EFFECT_TOOLS.includes(t) && 'nv-crew-chip-risk')}
          key={t}
        >
          {s.tools[t]}
        </span>
      ))}
    </>
  )
}

function TaskList({ crew, s }: { crew: Crew; s: NvCrewTranslations }) {
  const byId = Object.fromEntries(crew.members.map(m => [m.id, m]))

  return (
    <ol className="nv-crew-tasks" data-slot="nv-crew-tasks">
      {crew.tasks.map((t, i) => (
        <li data-status={t.status} key={t.id}>
          <span className="nv-crew-task-n">{i + 1}</span>
          <div className="min-w-0">
            <p className="nv-crew-task-title">{t.title}</p>
            <p className="nv-crew-task-who">
              {byId[t.member_id]?.name ?? '—'} · {byId[t.member_id]?.role ?? ''}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}

function Approvals({ crew, s }: { crew: Crew; s: NvCrewTranslations }) {
  const waiting = crew.members.filter(m => m.status === 'waiting' && m.approval)

  if (!waiting.length) {
    return null
  }

  return (
    <div className="nv-crew-approvals">
      {waiting.map(m => (
        <div className="nv-crew-approval" key={m.id}>
          <p>
            <strong>{m.name}</strong> · <code>{m.approval?.command}</code>
          </p>
          <div className="nv-crew-actions">
            <button className="nv-crew-btn nv-crew-btn-primary" onClick={() => void answerCrewApproval(m, 'once')} type="button">
              {s.allow}
            </button>
            <button className="nv-crew-btn" onClick={() => void answerCrewApproval(m, 'deny')} type="button">
              {s.deny}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

/** The proposal (before approval) or the working/finished crew. */
export function CrewView({ crew, onEdit, s }: { crew: Crew; onEdit: () => void; s: NvCrewTranslations }) {
  const busy = useStore($crewBusy)
  const [consent, setConsent] = useState(false)
  const done = crew.tasks.filter(t => t.status === 'done').length
  const needsConsent = crew.side_effects.length > 0
  const proposal = crew.status === 'proposed'
  const finished = crew.status === 'done' || crew.status === 'failed' || crew.status === 'cancelled'

  useEffect(() => setConsent(false), [crew.id, crew.updated_at])

  return (
    <section className="nv-crew-view" data-crew-status={crew.status} data-slot="nv-crew-view">
      <header className="nv-crew-view-head">
        <div className="min-w-0">
          <p className="nv-crew-goal">{crew.goal}</p>
          <h2 className="nv-crew-view-title">{crew.title}</h2>
          <p className="nv-crew-meta">
            <span className="nv-crew-pill" data-status={crew.status}>
              {s.crewStatus[crew.status]}
            </span>
            <span>{crew.designed_by === 'agent' ? s.designedByAgent : s.designedByTemplate}</span>
            <span>
              {s.flow}: {s.flows[crew.process]}
            </span>
            {!proposal && <span>{fmt(s.progress, { done, total: crew.tasks.length })}</span>}
          </p>
        </div>
      </header>

      <CrewRoom crew={crew} s={s} />
      <Approvals crew={crew} s={s} />

      {proposal && (
        <div className="nv-crew-grid">
          <div className="nv-crew-card">
            <h3 className="nv-crew-card-title">{s.members}</h3>
            <ul className="nv-crew-members">
              {crew.members.map(m => (
                <li key={m.id}>
                  <p className="nv-crew-member-line">
                    <strong>{m.name}</strong> · {m.role}
                    {crew.manager === m.id && <span className="nv-crew-badge">{s.manager}</span>}
                  </p>
                  {m.goal && <p className="nv-crew-member-goal">{m.goal}</p>}
                  <p className="nv-crew-chips">
                    <ToolChips s={s} tools={m.tools} />
                    <span className="nv-crew-chip nv-crew-chip-muted">{m.model || s.modelDefault}</span>
                  </p>
                </li>
              ))}
            </ul>
          </div>
          <div className="nv-crew-card">
            <h3 className="nv-crew-card-title">{s.tasks}</h3>
            <TaskList crew={crew} s={s} />
          </div>
        </div>
      )}

      {!proposal && (
        <div className="nv-crew-card">
          <h3 className="nv-crew-card-title">{s.tasks}</h3>
          <TaskList crew={crew} s={s} />
        </div>
      )}

      {finished && (crew.final_output || crew.error) && (
        <div className="nv-crew-card nv-crew-result" data-slot="nv-crew-result">
          <h3 className="nv-crew-card-title">{s.result}</h3>
          {crew.error && <p className="nv-crew-error">{crew.error}</p>}
          {crew.final_output && <pre>{crew.final_output}</pre>}
        </div>
      )}

      {(proposal || finished) && needsConsent && !(finished && crew.allow_side_effects) && (
        <label className="nv-crew-consent">
          <input checked={consent} onChange={e => setConsent(e.target.checked)} type="checkbox" />
          <span>
            <strong>{s.sideEffects}</strong> {s.sideEffectsConsent}
          </span>
        </label>
      )}

      <div className="nv-crew-actions">
        {(proposal || finished) && (
          <button
            className="nv-crew-btn nv-crew-btn-primary"
            disabled={busy || (needsConsent && !consent && !(finished && crew.allow_side_effects))}
            onClick={() => void approveCrew(crew.id, needsConsent && (consent || crew.allow_side_effects))}
            type="button"
          >
            {proposal ? s.approve : s.runAgain}
          </button>
        )}
        {crew.status === 'running' && (
          <button className="nv-crew-btn" disabled={busy} onClick={() => void cancelCrew(crew.id)} type="button">
            {s.stop}
          </button>
        )}
        {crew.status !== 'running' && (
          <button className="nv-crew-btn" onClick={onEdit} type="button">
            {s.edit}
          </button>
        )}
        {crew.status !== 'running' && (
          <button className="nv-crew-btn nv-crew-btn-ghost" disabled={busy} onClick={() => void deleteCrew(crew.id)} type="button">
            {s.discard}
          </button>
        )}
        {finished && (
          <button className="nv-crew-btn nv-crew-btn-ghost" onClick={closeCrew} type="button">
            {s.propose}
          </button>
        )}
      </div>
    </section>
  )
}

export function CrewGoalForm({ s }: { s: NvCrewTranslations }) {
  const busy = useStore($crewBusy)
  const [goal, setGoal] = useState('')

  const submit = (template?: CrewTemplateId) => {
    if (goal.trim()) {
      void proposeCrew(goal.trim(), template)
    }
  }

  return (
    <section className="nv-crew-form" data-slot="nv-crew-form">
      <label className="nv-crew-label" htmlFor="nv-crew-goal">
        {s.goalLabel}
      </label>
      <textarea
        className="nv-crew-input"
        id="nv-crew-goal"
        onChange={e => setGoal(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            submit()
          }
        }}
        placeholder={s.goalPlaceholder}
        rows={3}
        value={goal}
      />
      <div className="nv-crew-actions">
        <button className="nv-crew-btn nv-crew-btn-primary" disabled={busy || !goal.trim()} onClick={() => submit()} type="button">
          {busy ? s.proposing : s.propose}
        </button>
      </div>
      <p className="nv-crew-label">{s.templatesLabel}</p>
      <div className="nv-crew-templates">
        {CREW_TEMPLATES.map(id => (
          <button
            className="nv-crew-template"
            data-template={id}
            disabled={busy || !goal.trim()}
            key={id}
            onClick={() => submit(id)}
            type="button"
          >
            {s.templates[id]}
          </button>
        ))}
      </div>
    </section>
  )
}

export function CrewHistory({ onOpen, s }: { onOpen: () => void; s: NvCrewTranslations }) {
  const crews = useStore($crews)

  useEffect(() => void refreshCrews(), [])

  if (!crews.length) {
    return <p className="nv-crew-empty">{s.historyEmpty}</p>
  }

  return (
    <ul className="nv-crew-history" data-slot="nv-crew-history">
      {crews.map(c => (
        <li key={c.id}>
          <button
            className="nv-crew-history-row"
            onClick={() => {
              void openCrew(c.id)
              onOpen()
            }}
            type="button"
          >
            <span className="min-w-0">
              <span className="nv-crew-history-title">{c.title}</span>
              <span className="nv-crew-history-sub">
                {s.templates[c.template] ?? c.template} · {fmt(s.progress, { done: c.done, total: c.tasks })}
              </span>
            </span>
            <span className="nv-crew-pill" data-status={c.status}>
              {s.crewStatus[c.status]}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

const blankMember = (i: number): CrewMember => ({
  avatar: i % 10,
  goal: '',
  id: `m${Date.now().toString(36)}${i}`,
  model: '',
  name: '',
  role: '',
  status: 'idle',
  tools: []
})

/** Lanjutan: manual edit of role/goal/tools/model/task/flow, then the old Kantor. */
export function CrewAdvanced({ crew, s }: { crew: Crew | null; s: NvCrewTranslations }) {
  const navigate = useNavigate()
  const busy = useStore($crewBusy)
  const [draft, setDraft] = useState<Crew | null>(crew)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setDraft(crew)
    setSaved(false)
  }, [crew?.id, crew?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  const legacy = (
    <div className="nv-crew-card nv-crew-legacy">
      <p>{s.legacyHint}</p>
      <button className="nv-crew-btn" onClick={() => navigate(OFFICE_ROUTE)} type="button">
        {s.legacy}
      </button>
    </div>
  )

  if (!draft || draft.status === 'running') {
    return (
      <div className="nv-crew-advanced">
        <p className="nv-crew-empty">{s.advancedEmpty}</p>
        {legacy}
      </div>
    )
  }

  const setMember = (i: number, patch: Partial<CrewMember>) =>
    setDraft({ ...draft, members: draft.members.map((m, j) => (j === i ? { ...m, ...patch } : m)) })

  const setTask = (i: number, patch: Partial<CrewTask>) =>
    setDraft({ ...draft, tasks: draft.tasks.map((t, j) => (j === i ? { ...t, ...patch } : t)) })

  const save = async () => {
    const res = await updateCrew(draft.id, {
      manager: draft.process === 'hierarchical' ? draft.manager || draft.members[0]?.id : null,
      members: draft.members,
      process: draft.process,
      tasks: draft.tasks,
      title: draft.title
    })

    setSaved(Boolean(res))
  }

  return (
    <div className="nv-crew-advanced" data-slot="nv-crew-advanced">
      <div className="nv-crew-card">
        <div className="nv-crew-row">
          <label className="nv-crew-field">
            <span>{s.flow}</span>
            <select
              aria-label={s.flow}
              onChange={e => setDraft({ ...draft, process: e.target.value as Crew['process'] })}
              value={draft.process}
            >
              <option value="sequential">{s.flows.sequential}</option>
              <option value="hierarchical">{s.flows.hierarchical}</option>
            </select>
          </label>
          {draft.process === 'hierarchical' && (
            <label className="nv-crew-field">
              <span>{s.manager}</span>
              <select
                aria-label={s.manager}
                onChange={e => setDraft({ ...draft, manager: e.target.value })}
                value={draft.manager ?? draft.members[0]?.id}
              >
                {draft.members.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name || m.role || m.id}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      <div className="nv-crew-card">
        <h3 className="nv-crew-card-title">{s.members}</h3>
        {draft.members.map((m, i) => (
          <fieldset className="nv-crew-edit" data-member={m.id} key={m.id}>
            <div className="nv-crew-row">
              <label className="nv-crew-field">
                <span>{s.name}</span>
                <input onChange={e => setMember(i, { name: e.target.value })} value={m.name} />
              </label>
              <label className="nv-crew-field">
                <span>{s.role}</span>
                <input onChange={e => setMember(i, { role: e.target.value })} value={m.role} />
              </label>
              <label className="nv-crew-field">
                <span>
                  {s.model} · {s.freeOnly}
                </span>
                <input
                  onChange={e => setMember(i, { model: e.target.value })}
                  placeholder={s.modelDefault}
                  value={m.model}
                />
              </label>
            </div>
            <label className="nv-crew-field">
              <span>{s.goal}</span>
              <input onChange={e => setMember(i, { goal: e.target.value })} value={m.goal} />
            </label>
            <div className="nv-crew-chips">
              {CREW_TOOL_GROUPS.map(g => (
                <label className={cn('nv-crew-toggle', CREW_SIDE_EFFECT_TOOLS.includes(g) && 'nv-crew-chip-risk')} key={g}>
                  <input
                    checked={m.tools.includes(g)}
                    onChange={e =>
                      setMember(i, { tools: e.target.checked ? [...m.tools, g] : m.tools.filter(x => x !== g) })
                    }
                    type="checkbox"
                  />
                  {s.tools[g]}
                </label>
              ))}
              <button
                className="nv-crew-btn nv-crew-btn-ghost"
                disabled={draft.members.length <= 1}
                onClick={() => setDraft({ ...draft, members: draft.members.filter((_, j) => j !== i) })}
                type="button"
              >
                {s.remove}
              </button>
            </div>
          </fieldset>
        ))}
        <button
          className="nv-crew-btn"
          disabled={draft.members.length >= 5}
          onClick={() => setDraft({ ...draft, members: [...draft.members, blankMember(draft.members.length)] })}
          type="button"
        >
          {s.addMember}
        </button>
      </div>

      <div className="nv-crew-card">
        <h3 className="nv-crew-card-title">{s.tasks}</h3>
        {draft.tasks.map((t, i) => (
          <fieldset className="nv-crew-edit" data-task={t.id} key={t.id}>
            <div className="nv-crew-row">
              <label className="nv-crew-field">
                <span>
                  {s.task} {i + 1}
                </span>
                <input onChange={e => setTask(i, { title: e.target.value })} value={t.title} />
              </label>
              <label className="nv-crew-field">
                <span>{s.assignee}</span>
                <select onChange={e => setTask(i, { member_id: e.target.value })} value={t.member_id}>
                  {draft.members.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.name || m.role || m.id}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <textarea
              aria-label={`${s.task} ${i + 1}`}
              className="nv-crew-input"
              onChange={e => setTask(i, { description: e.target.value })}
              rows={2}
              value={t.description}
            />
            <button
              className="nv-crew-btn nv-crew-btn-ghost"
              disabled={draft.tasks.length <= 1}
              onClick={() => setDraft({ ...draft, tasks: draft.tasks.filter((_, j) => j !== i) })}
              type="button"
            >
              {s.remove}
            </button>
          </fieldset>
        ))}
        <button
          className="nv-crew-btn"
          disabled={draft.tasks.length >= 8}
          onClick={() =>
            setDraft({
              ...draft,
              tasks: [
                ...draft.tasks,
                {
                  description: '',
                  expected_output: '',
                  id: `t${Date.now().toString(36)}`,
                  member_id: draft.members[0]?.id ?? '',
                  output: '',
                  status: 'todo',
                  title: ''
                }
              ]
            })
          }
          type="button"
        >
          {s.addTask}
        </button>
      </div>

      <div className="nv-crew-actions">
        <button className="nv-crew-btn nv-crew-btn-primary" disabled={busy} onClick={() => void save()} type="button">
          {s.save}
        </button>
        {saved && <span className="nv-crew-saved">{s.saved}</span>}
      </div>
      {legacy}
    </div>
  )
}

export function CrewIntro({ onDone, s }: { onDone: () => void; s: NvCrewTranslations }) {
  const steps = [s.intro.step1, s.intro.step2, s.intro.step3]

  return (
    <div aria-label={s.intro.title} aria-modal="true" className="nv-crew-intro" data-slot="nv-crew-intro" role="dialog">
      <div className="nv-crew-intro-card">
        <div className="nv-crew-intro-art">
          {[1, 4, 9].map((a, i) => (
            <CrewStation avatar={a} key={a} size={96} status={i === 1 ? 'working' : i === 2 ? 'done' : 'idle'} />
          ))}
        </div>
        <h2>{s.intro.title}</h2>
        <ol>
          {steps.map((x, i) => (
            <li key={x}>
              <span className="nv-crew-task-n">{i + 1}</span>
              {x}
            </li>
          ))}
        </ol>
        <div className="nv-crew-actions">
          <button className="nv-crew-btn nv-crew-btn-primary" onClick={onDone} type="button">
            {s.intro.start}
          </button>
          <button className="nv-crew-btn nv-crew-btn-ghost" onClick={onDone} type="button">
            {s.intro.skip}
          </button>
        </div>
      </div>
    </div>
  )
}

/** The Crew page (rail "Crew"): three menus — Crew, Riwayat, Lanjutan. */
export function NeovarchCrewPage({ initialTab = 'crew' }: { initialTab?: CrewTab }) {
  const s = useI18n().t.nvCrew
  const crew = useStore($crew)
  const error = useStore($crewError)
  useStore($crews) // keeps the list (and crew.update pushes) live while the page is open
  const [tab, setTab] = useState<CrewTab>(initialTab)
  const [intro, setIntro] = useState(() => !introSeen())

  return (
    <div className="nv-crew" data-slot="nv-crew-page">
      <header className="nv-crew-header">
        <div>
          <p className="nv-office-kicker">{s.kicker}</p>
          <h1 className="nv-office-title">{s.title}</h1>
          <p className="nv-office-sub">{s.sub}</p>
        </div>
        <span className="nv-crew-chip nv-crew-chip-muted">{s.freeOnly}</span>
      </header>
      <nav aria-label={s.title} className="nv-crew-tabs" role="tablist">
        {CREW_TABS.map(id => (
          <button
            aria-selected={tab === id}
            className={cn('nv-crew-tab', tab === id && 'nv-crew-tab-active')}
            data-tab={id}
            key={id}
            onClick={() => setTab(id)}
            role="tab"
            type="button"
          >
            {s.tabs[id]}
          </button>
        ))}
      </nav>
      {error && <p className="nv-crew-error">{error}</p>}
      <div className="nv-crew-body">
        {tab === 'crew' && (crew ? <CrewView crew={crew} onEdit={() => setTab('advanced')} s={s} /> : <CrewGoalForm s={s} />)}
        {tab === 'history' && <CrewHistory onOpen={() => setTab('crew')} s={s} />}
        {tab === 'advanced' && <CrewAdvanced crew={crew} s={s} />}
      </div>
      {intro && (
        <CrewIntro
          onDone={() => {
            markIntroSeen()
            setIntro(false)
          }}
          s={s}
        />
      )}
    </div>
  )
}
