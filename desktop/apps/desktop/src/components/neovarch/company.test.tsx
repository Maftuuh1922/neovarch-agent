// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OfficeAgent } from './office-store'

const gw = vi.hoisted(() => ({ request: vi.fn() }))

vi.mock('@/store/gateway', async () => {
  const { atom } = await import('nanostores')

  return { $gateway: atom(gw) }
})

vi.mock('./office3d-scene', () => ({
  createOfficeScene: () => ({
    dispose: vi.fn(),
    resetCamera: vi.fn(),
    setAgents: vi.fn(),
    setPaused: vi.fn(),
    setSelected: vi.fn()
  })
}))

const { $company, orgTree } = await import('./company-store')
const { CompanyPanel } = await import('./company')
const { sceneAgentsFromSnapshot } = await import('./office3d-model')

const agent = (id: number, name: string, title: string, reports_to: null | number, extra = {}) => ({
  budget: { cents: 0, level: 'ok', pct: null, tokens: 0 },
  budget_monthly_cents: 0,
  budget_monthly_tokens: 0,
  current_ticket: null,
  heartbeat_s: 0,
  id,
  job_description: '',
  model: '',
  name,
  pause_reason: null,
  pending_approvals: 0,
  reports_to,
  reports_to_name: null,
  role: 'pegawai',
  session_id: null,
  status: 'idle',
  ticket_counts: {},
  title,
  ...extra
})

const SNAP = {
  active_agents: [],
  agents: [
    agent(3, 'Raka', 'Engineer', 2),
    agent(1, 'Dimas', 'CEO', null),
    agent(2, 'Hana', 'CTO', 1, { status: 'paused', pause_reason: 'budget' })
  ],
  budget: { cents: 0, level: 'ok', pct: null, tokens: 0 },
  company: {
    autorun: false,
    budget_monthly_cents: 0,
    budget_monthly_tokens: 0,
    max_parallel: 2,
    mission: 'Bikin aplikasi yang membantu orang',
    name: 'Neovarch Studio',
    price_in_per_mtok: 0,
    price_out_per_mtok: 0,
    require_hire_approval: true,
    require_review: true,
    ticket_prefix: 'NV',
    warn_pct: 80
  },
  exists: true as const,
  goals: [],
  pending_approvals: 1,
  projects: [],
  routines: [],
  ticket_counts: {
    backlog: 0,
    blocked: 0,
    cancelled: 0,
    done: 0,
    in_progress: 1,
    review: 0,
    todo: 1
  }
}

const TICKETS = [
  {
    assignee_id: 3,
    assignee_name: 'Raka',
    blocked_by: 0,
    description: '',
    id: 7,
    key: 'NV-7',
    locked: true,
    parent_id: null,
    priority: 1,
    project_id: null,
    status: 'in_progress',
    status_label: 'Dikerjakan',
    title: 'Perbaiki crash',
    updated_at: 0
  },
  {
    assignee_id: null,
    assignee_name: null,
    blocked_by: 0,
    description: '',
    id: 8,
    key: 'NV-8',
    locked: false,
    parent_id: null,
    priority: 1,
    project_id: null,
    status: 'todo',
    status_label: 'Akan dikerjakan',
    title: 'Tulis dokumentasi',
    updated_at: 0
  }
]

let snapshot: unknown = SNAP

function respond(method: string, params: Record<string, unknown> = {}) {
  switch (method) {
    case 'company.snapshot':
      return snapshot

    case 'company.ticket.list':
      return { tickets: TICKETS }

    case 'company.ticket.get':
      return {
        ...TICKETS[0],
        ancestry: [
          { id: 1, title: 'Rilis 1.5 stabil', type: 'goal' },
          {
            id: 1,
            title: 'Bikin aplikasi yang membantu orang',
            type: 'mission'
          }
        ],
        blockers: [],
        children: [],
        comments: [
          {
            author_name: 'Raka',
            author_type: 'agent',
            body: 'Sedang saya telusuri',
            created_at: 0,
            id: 1
          }
        ],
        work_products: []
      }

    case 'company.approval.list':
      return {
        approvals: [
          {
            agent_name: 'Raka',
            created_at: 0,
            id: 5,
            kind: 'review',
            note: '',
            payload: { summary: 'Crash sudah hilang' },
            status: 'pending',
            ticket_key: 'NV-7',
            title: 'Tinjau hasil NV-7'
          }
        ]
      }

    case 'company.activity':
      return {
        items: [
          {
            action: 'ticket.created',
            actor_name: 'Kamu',
            actor_type: 'user',
            id: 1,
            summary: 'membuat NV-7',
            ts: 0
          }
        ]
      }

    default:
      return { ok: true, params }
  }
}

beforeEach(() => {
  gw.request.mockReset()
  gw.request.mockImplementation(async (method: string, params?: Record<string, unknown>) => respond(method, params))
  snapshot = SNAP
  $company.set(SNAP as never)
})

afterEach(() => {
  cleanup()
})

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('Perusahaan (company) views', () => {
  it('starts empty (no demo staff) and creates the first organisasi', async () => {
    snapshot = { exists: false }
    $company.set({ exists: false })
    wrap(<CompanyPanel tab="org" />)
    expect(screen.getByText('Kantor masih kosong')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Coba contoh/ })).toBeNull()
    fireEvent.change(screen.getByPlaceholderText('mis. Neovarch Labs'), { target: { value: 'Neovarch Labs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buat organisasi' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.unit.save', { kind: 'organisasi', name: 'Neovarch Labs' })
    )
  })

  it('hides the other Kantor tabs until something exists', async () => {
    const { visibleCompanyTabs } = await import('./company')
    expect(visibleCompanyTabs(false).map(t => t.value)).toEqual(['org'])
    expect(visibleCompanyTabs(true).length).toBe(7)
  })

  it('fires (deletes) an employee and lists organisasi → agency units', async () => {
    $company.set({
      ...SNAP,
      agents: [agent(1, 'Dimas', 'CEO', null, { unit_id: 11 })],
      units: [
        { id: 10, kind: 'organisasi', name: 'Neovarch Labs', parent_id: null },
        { id: 11, kind: 'agency', name: 'Kreatif', parent_id: 10 }
      ]
    } as never)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<CompanyPanel tab="org" />)
    const units = screen.getByRole('list', { name: 'Organisasi dan agency' })
    expect(within(units).getAllByText(/^(Neovarch Labs|Kreatif)$/).map(n => n.textContent)).toEqual([
      'Neovarch Labs',
      'Kreatif'
    ])
    const list = screen.getByRole('list', { name: 'Struktur organisasi' })
    fireEvent.click(within(list).getByRole('button', { name: 'Berhentikan' }))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.agent.delete', { id: 1 }))
    confirm.mockRestore()
  })

  it('draws the org chart as a tree and wakes / resumes agents', async () => {
    wrap(<CompanyPanel tab="org" />)
    const list = screen.getByRole('list', { name: 'Struktur organisasi' })

    const names = within(list)
      .getAllByText(/^(Dimas|Hana|Raka)$/)
      .map(n => n.textContent)

    expect(names).toEqual(['Dimas', 'Hana', 'Raka'])
    expect(within(list).getByText(/Dijeda · anggaran/)).toBeTruthy()
    fireEvent.click(within(list).getAllByRole('button', { name: 'Bangunkan' })[0]!)
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.agent.wake', { id: 1 }))
    fireEvent.click(within(list).getByRole('button', { name: 'Lanjutkan' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.agent.resume', {
        id: 2
      })
    )
  })

  it('shows tickets in kanban columns and moves one from its detail panel', async () => {
    wrap(<CompanyPanel tab="tickets" />)
    const board = await screen.findByLabelText('Papan tiket')
    await waitFor(() => expect(within(board).getByText('Perbaiki crash')).toBeTruthy())
    const col = board.querySelector('[data-status="in_progress"]') as HTMLElement
    expect(within(col).getByText('NV-7')).toBeTruthy()
    expect(
      within(board.querySelector('[data-status="todo"]') as HTMLElement).getByText('Belum ditugaskan')
    ).toBeTruthy()
    fireEvent.click(within(col).getByText('Perbaiki crash'))
    const detail = await screen.findByLabelText('Tiket NV-7')
    expect(within(detail).getByText(/Rilis 1.5 stabil → Bikin aplikasi/)).toBeTruthy()
    expect(within(detail).getByText('Sedang saya telusuri')).toBeTruthy()
    fireEvent.click(within(detail).getByRole('button', { name: '→ Ditinjau' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.ticket.move', {
        id: 7,
        status: 'review'
      })
    )
  })

  it('creates a ticket for an agent', async () => {
    wrap(<CompanyPanel tab="tickets" />)
    fireEvent.change(screen.getByLabelText('Judul tiket'), {
      target: { value: 'Riset kompetitor' }
    })
    fireEvent.change(screen.getAllByLabelText('Penanggung jawab')[0]!, {
      target: { value: '3' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Tambah' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.ticket.save', {
        assignee_id: 3,
        project_id: null,
        title: 'Riset kompetitor'
      })
    )
  })

  it('approves a pending review with a note', async () => {
    wrap(<CompanyPanel tab="approvals" />)
    await screen.findByText('Tinjau hasil NV-7')
    expect(screen.getByText('Crash sudah hilang')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Catatan'), {
      target: { value: 'mantap' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Setujui' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.approval.decide', {
        decision: 'approve',
        id: 5,
        note: 'mantap'
      })
    )
  })

  it('toggles autorun through company.update', async () => {
    wrap(<CompanyPanel tab="activity" />)
    await screen.findByText('membuat NV-7')
    fireEvent.click(screen.getByLabelText('Jalan otomatis'))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.update', {
        autorun: true
      })
    )
  })
})

describe('company helpers', () => {
  it('orgTree orders managers before reports, depth by chain', () => {
    const tree = orgTree(SNAP.agents as never)
    expect(tree.map(t => [t.agent.name, t.depth])).toEqual([
      ['Dimas', 0],
      ['Hana', 1],
      ['Raka', 2]
    ])
  })

  it('3D desks follow the real ticket status of company agents', () => {
    const base: OfficeAgent = {
      current_task: 'NV-7 · Perbaiki crash',
      current_tool: null,
      id: 'company:3',
      kind: 'company',
      last_activity: 0,
      last_activity_text: null,
      message_count: 0,
      model: '',
      name: 'Raka',
      pending_approval: null,
      role: 'Engineer',
      session_id: null,
      source: 'company',
      status: 'idle',
      title: null,
      company: {
        agent_id: 3,
        agent_status: 'idle',
        budget_pct: null,
        pause_reason: null,
        paused: false,
        reports_to: 2,
        ticket_key: 'NV-7',
        ticket_status: 'blocked',
        ticket_title: 'Perbaiki crash',
        title: 'Engineer'
      }
    }

    const snap = {
      agents: [base],
      counts: { idle: 1, total: 1, 'waiting-approval': 0, working: 0 },
      feed: [],
      generated_at: 0,
      host: 'pc',
      kanban: {},
      seq: 0,
      vault: { configured: false, connected: false, note_count: 0, path: '' }
    }

    const [blocked] = sceneAgentsFromSnapshot(snap)
    expect(blocked).toMatchObject({
      label: 'NV-7 · Terhambat',
      status: 'error',
      statusText: 'Terhambat'
    })

    const [review] = sceneAgentsFromSnapshot({
      ...snap,
      agents: [{ ...base, company: { ...base.company!, ticket_status: 'review' } }]
    })

    expect(review).toMatchObject({
      status: 'waiting',
      statusText: 'Menunggu tinjauan'
    })

    const [working] = sceneAgentsFromSnapshot({
      ...snap,
      agents: [
        {
          ...base,
          status: 'working',
          company: { ...base.company!, ticket_status: 'in_progress' }
        }
      ]
    })

    expect(working).toMatchObject({
      label: 'NV-7 · Dikerjakan',
      status: 'working'
    })

    const [paused] = sceneAgentsFromSnapshot({
      ...snap,
      agents: [
        {
          ...base,
          company: {
            ...base.company!,
            paused: true,
            pause_reason: 'budget',
            ticket_status: 'todo'
          }
        }
      ]
    })

    expect(paused).toMatchObject({
      status: 'idle',
      statusText: 'Dijeda · anggaran habis'
    })
  })
})
