// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const gw = vi.hoisted(() => ({ request: vi.fn() }))

vi.mock('@/store/gateway', async () => {
  const { atom } = await import('nanostores')

  return { $gateway: atom(gw) }
})

const { $company } = await import('./company-store')
const { CompanyPanel, COMPANY_TABS } = await import('./company')
const { companyModelOptions } = await import('./company-plan')

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
  provider: '',
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
  agents: [agent(1, 'Dimas', 'CEO', null), agent(2, 'Hana', 'CTO', 1), agent(3, 'Raka', 'Engineer', 2)],
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
  goals: [
    { description: '', id: 1, parent_id: null, status: 'active', title: 'Rilis 1.5 stabil' },
    { description: 'tanpa crash', id: 2, parent_id: 1, status: 'active', title: 'Stabil di Windows' }
  ],
  pending_approvals: 0,
  projects: [{ budget_monthly_cents: 500, description: '', goal_id: 1, id: 4, name: 'Aplikasi desktop' }],
  routines: [
    {
      agent_id: 1,
      description: '',
      enabled: 1,
      id: 9,
      last_run_at: null,
      name: 'Ringkasan mingguan',
      next_run_at: 1_790_000_000,
      project_id: null,
      schedule: 'every 7d',
      title: 'Ringkasan mingguan'
    }
  ],
  ticket_counts: { backlog: 0, blocked: 0, cancelled: 0, done: 0, in_progress: 0, review: 0, todo: 2 }
}

const ticket = (id: number, key: string, title: string, status = 'todo') => ({
  assignee_id: null,
  assignee_name: null,
  blocked_by: 0,
  description: '',
  id,
  key,
  locked: false,
  parent_id: null,
  priority: 1,
  project_id: null,
  status,
  status_label: '',
  title,
  updated_at: 0
})

const TICKETS = [ticket(7, 'NV-7', 'Perbaiki crash'), ticket(8, 'NV-8', 'Siapkan API'), ticket(9, 'NV-9', 'Lama', 'done')]

let blockers: { id: number; key: string; status: string; title: string }[] = []
let failModels = false

function respond(method: string, params: Record<string, unknown> = {}) {
  switch (method) {
    case 'company.snapshot':
      return SNAP

    case 'company.ticket.list':
      return { tickets: TICKETS }

    case 'company.ticket.get':
      return { ...TICKETS[0], ancestry: [], blockers, children: [], comments: [], work_products: [] }

    case 'company.ticket.block':
      blockers = [{ id: 8, key: 'NV-8', status: 'todo', title: 'Siapkan API' }]

      return TICKETS[0]

    case 'company.ticket.unblock':
      blockers = []

      return TICKETS[0]

    case 'company.routine.trigger':
      return { ...TICKETS[0], key: 'NV-12' }

    case 'model.options':
      if (failModels) {
        throw new Error('core sibuk')
      }

      return {
        providers: [
          { models: ['gpt-4o', 'gpt-4o-mini'], name: 'OpenAI', slug: 'openai' },
          { models: ['llama3'], name: 'Lab', slug: 'custom:lab' },
          { models: 'rusak', name: 'Aneh', slug: 'x' }
        ]
      }

    default:
      return { ok: true, params }
  }
}

beforeEach(() => {
  blockers = []
  failModels = false
  gw.request.mockReset()
  gw.request.mockImplementation(async (method: string, params?: Record<string, unknown>) => respond(method, params))
  $company.set(SNAP as never)
})

afterEach(() => cleanup())

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('Perusahaan: goals, projects, routines, agent editor, blockers', () => {
  it('has Tujuan and Rutinitas tabs', () => {
    expect(COMPANY_TABS.map(t => t.label)).toEqual(
      expect.arrayContaining(['Organisasi', 'Tiket', 'Tujuan', 'Rutinitas', 'Persetujuan', 'Biaya', 'Aktivitas live'])
    )
  })

  it('creates a sub-goal under an existing goal', async () => {
    wrap(<CompanyPanel tab="goals" />)
    const form = screen.getByRole('form', { name: 'Tujuan baru' })
    fireEvent.change(within(form).getByLabelText('Judul tujuan'), { target: { value: 'Stabil di Linux' } })
    fireEvent.change(within(form).getByLabelText('Tujuan induk'), { target: { value: '1' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Tambah tujuan' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.goal.save', {
        description: '',
        parent_id: 1,
        title: 'Stabil di Linux'
      })
    )
  })

  it('edits a goal without offering itself or its children as parent, and deletes with confirmation', async () => {
    wrap(<CompanyPanel tab="goals" />)
    const item = document.querySelector('[data-goal="1"]') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Ubah' }))
    const form = screen.getByRole('form', { name: 'Ubah tujuan Rilis 1.5 stabil' })
    const parents = within(form)
      .getAllByRole('option')
      .map(o => o.textContent)
    expect(parents).not.toContain('Stabil di Windows')
    fireEvent.change(within(form).getByLabelText('Status tujuan'), { target: { value: 'done' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Simpan' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.goal.save', {
        description: '',
        id: 1,
        parent_id: null,
        status: 'done',
        title: 'Rilis 1.5 stabil'
      })
    )
    const child = document.querySelector('[data-goal="2"]') as HTMLElement
    fireEvent.click(within(child).getByRole('button', { name: 'Hapus' }))
    expect(gw.request).not.toHaveBeenCalledWith('company.goal.delete', { id: 2 })
    fireEvent.click(within(child).getByRole('button', { name: 'Yakin hapus?' }))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.goal.delete', { id: 2 }))
  })

  it('creates a project with a budget and rejects a negative one locally', async () => {
    wrap(<CompanyPanel tab="goals" />)
    const form = screen.getByRole('form', { name: 'Proyek baru' })
    fireEvent.change(within(form).getByLabelText('Nama proyek'), { target: { value: 'Situs' } })
    fireEvent.change(within(form).getByLabelText('Anggaran proyek per bulan (sen USD)'), { target: { value: '-3' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Tambah proyek' }))
    expect(await within(form).findByRole('alert')).toHaveProperty('textContent', 'Anggaran harus angka 0 atau lebih.')
    expect(gw.request).not.toHaveBeenCalledWith('company.project.save', expect.anything())
    fireEvent.change(within(form).getByLabelText('Anggaran proyek per bulan (sen USD)'), { target: { value: '250' } })
    fireEvent.change(within(form).getByLabelText('Tujuan proyek'), { target: { value: '2' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Tambah proyek' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.project.save', {
        budget_monthly_cents: 250,
        description: '',
        goal_id: 2,
        name: 'Situs'
      })
    )
  })

  it('shows a core error inline when saving fails', async () => {
    gw.request.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'company.goal.save') {
        throw new Error('Tujuan tidak boleh menjadi induk dirinya sendiri')
      }

      return respond(method, params)
    })
    wrap(<CompanyPanel tab="goals" />)
    const form = screen.getByRole('form', { name: 'Tujuan baru' })
    fireEvent.change(within(form).getByLabelText('Judul tujuan'), { target: { value: 'X' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Tambah tujuan' }))
    expect((await within(form).findByRole('alert')).textContent).toMatch(/induk dirinya sendiri/)
  })

  it('lists routines, notes autorun is off, triggers, toggles and creates one', async () => {
    wrap(<CompanyPanel tab="routines" />)
    expect(screen.getByText(/Heartbeat Kantor sedang dijeda/)).toBeTruthy()
    const item = document.querySelector('[data-routine="9"]') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Jalankan sekarang' }))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.routine.trigger', { id: 9 }))
    expect(await screen.findByText('Tiket NV-12 dibuat.')).toBeTruthy()
    fireEvent.click(within(item).getByLabelText('Aktifkan Ringkasan mingguan'))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.routine.save', { enabled: false, id: 9 })
    )
    const form = screen.getByRole('form', { name: 'Rutinitas baru' })
    fireEvent.change(within(form).getByLabelText('Nama'), { target: { value: 'Cek bug harian' } })
    fireEvent.change(within(form).getByLabelText('Jadwal'), { target: { value: 'every 1d' } })
    fireEvent.change(within(form).getByLabelText(/^Untuk pegawai/), { target: { value: '3' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Tambah rutinitas' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.routine.save', {
        agent_id: 3,
        description: '',
        name: 'Cek bug harian',
        project_id: null,
        schedule: 'every 1d',
        title: 'Cek bug harian'
      })
    )
  })

  it('edits an agent: budget, heartbeat and model from model.options; manager list excludes its own reports', async () => {
    wrap(<CompanyPanel tab="org" />)
    const list = screen.getByRole('list', { name: 'Struktur organisasi' })
    const hanaNode = within(list).getByText('Hana').closest('li') as HTMLElement
    fireEvent.click(within(hanaNode).getByRole('button', { name: 'Ubah' }))
    const form = await screen.findByRole('form', { name: 'Ubah Hana' })
    const managers = within(within(form).getByLabelText(/^Melapor ke/))
      .getAllByRole('option')
      .map(o => o.textContent)
    expect(managers).toEqual(['Kamu (pemilik)', 'Dimas'])
    const model = within(form).getByLabelText('Model pegawai') as HTMLSelectElement
    await waitFor(() => expect(within(model).getByText('llama3 · Lab')).toBeTruthy())
    expect(gw.request).toHaveBeenCalledWith('model.options', {})
    fireEvent.change(model, { target: { value: within(model).getByText('llama3 · Lab').getAttribute('value') } })
    fireEvent.change(within(form).getByLabelText(/Anggaran per bulan/), { target: { value: '150' } })
    fireEvent.change(within(form).getByLabelText(/Batas token per bulan/), { target: { value: '20000' } })
    fireEvent.change(within(form).getByLabelText(/Detak/), { target: { value: '600' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Simpan' }))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('company.agent.save', {
        budget_monthly_cents: 150,
        budget_monthly_tokens: 20000,
        heartbeat_s: 600,
        id: 2,
        job_description: '',
        model: 'llama3',
        name: 'Hana',
        provider: 'custom:lab',
        reports_to: 1,
        title: 'CTO'
      })
    )
  })

  it('keeps the agent editor usable when the model list cannot load', async () => {
    failModels = true
    wrap(<CompanyPanel tab="org" />)
    const list = screen.getByRole('list', { name: 'Struktur organisasi' })
    const node = within(list).getByText('Raka').closest('li') as HTMLElement
    fireEvent.click(within(node).getByRole('button', { name: 'Ubah' }))
    expect(await screen.findByText(/Daftar model belum bisa dimuat: core sibuk/)).toBeTruthy()
    const form = screen.getByRole('form', { name: 'Ubah Raka' })
    fireEvent.change(within(form).getByLabelText(/Anggaran per bulan/), { target: { value: 'abc' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Simpan' }))
    expect((await within(form).findByRole('alert')).textContent).toMatch(/0 atau lebih/)
  })

  it('adds and removes a ticket blocker from the ticket detail (done tickets are not offered)', async () => {
    wrap(<CompanyPanel tab="tickets" />)
    const board = await screen.findByLabelText('Papan tiket')
    await waitFor(() => expect(within(board).getByText('Perbaiki crash')).toBeTruthy())
    fireEvent.click(within(board).getByText('Perbaiki crash'))
    const detail = await screen.findByLabelText('Tiket NV-7')
    expect(within(detail).getByText('Tidak ada hambatan.')).toBeTruthy()
    const pick = within(detail).getByLabelText('Tambah hambatan')
    const offered = within(pick)
      .getAllByRole('option')
      .map(o => o.textContent)
    expect(offered).toEqual(['Pilih tiket penghambat…', 'NV-8 · Siapkan API'])
    fireEvent.change(pick, { target: { value: '8' } })
    fireEvent.click(within(detail).getByRole('button', { name: 'Tambah hambatan' }))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.ticket.block', { blocker_id: 8, id: 7 }))
    fireEvent.click(await within(detail).findByRole('button', { name: 'Lepas hambatan NV-8' }))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('company.ticket.unblock', { blocker_id: 8, id: 7 }))
    await waitFor(() => expect(within(detail).getByText('Tidak ada hambatan.')).toBeTruthy())
  })
})

describe('companyModelOptions', () => {
  it('flattens model.options and drops malformed rows', () => {
    expect(
      companyModelOptions({
        providers: [
          { models: ['a', 'a', '', 3], name: 'P', slug: 'p' },
          { models: 'x', slug: 'q' }
        ]
      })
    ).toEqual([{ label: 'a · P', model: 'a', provider: 'p' }])
    expect(companyModelOptions(null)).toEqual([])
  })
})
