// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const gw = vi.hoisted(() => ({ request: vi.fn() }))

vi.mock('@/store/gateway', async () => {
  const { atom } = await import('nanostores')

  return { $gateway: atom(gw) }
})

const { emitGatewayEvent } = await import('@/contrib/events')
const { $crew, $crews, CREW_INTRO_KEY } = await import('./crew-store')
const { NeovarchCrewPage, CREW_TABS } = await import('./crew')
const { CREW_FRAMES, CREW_PALETTES, crewLayout, crewPose, CrewScene, CrewStation, spritePixels } = await import('./crew-pixel')

const { nvCrewAr, nvCrewDe, nvCrewEn, nvCrewEs, nvCrewFr, nvCrewId, nvCrewJa, nvCrewRu, nvCrewZh, nvCrewZhHant } =
  await import('@/i18n/nv-crew')

const { NEOVARCH_ID } = await import('@/i18n/neovarch-id')

const member = (id: string, name: string, role: string, tools: string[] = [], extra = {}) => ({
  avatar: Number(id.slice(1)),
  goal: `${role} goal`,
  id,
  model: '',
  name,
  role,
  status: 'idle',
  tools,
  ...extra
})

const task = (id: string, title: string, member_id: string, extra = {}) => ({
  description: `${title} desc`,
  expected_output: '',
  id,
  member_id,
  output: '',
  status: 'todo',
  title,
  ...extra
})

const PROPOSAL = {
  allow_side_effects: false,
  created_at: 10,
  designed_by: 'agent',
  error: '',
  final_output: '',
  goal: 'Perbaiki bug login',
  id: 'c1',
  log: [],
  manager: 'm1',
  members: [
    member('m1', 'Arga', 'Manajer teknis', ['files']),
    member('m2', 'Fajar', 'Programmer', ['files', 'write', 'shell'])
  ],
  process: 'hierarchical',
  side_effects: ['shell', 'write'],
  status: 'proposed',
  tasks: [task('t1', 'Implementasi', 'm2')],
  template: 'coding',
  title: 'Bug login',
  updated_at: 10
}

function respond(overrides: Record<string, unknown> = {}) {
  gw.request.mockImplementation(async (method: string, params: Record<string, unknown>) => {
    if (method in overrides) {
      const v = overrides[method]

      return typeof v === 'function' ? (v as (p: unknown) => unknown)(params) : v
    }

    if (method === 'crew.list') {
      return { crews: [] }
    }

    throw new Error(`unexpected ${method}`)
  })
}

function page() {
  return render(
    <MemoryRouter>
      <NeovarchCrewPage />
    </MemoryRouter>
  )
}

beforeEach(() => {
  window.localStorage.setItem(CREW_INTRO_KEY, '1')
  gw.request.mockReset()
  $crew.set(null)
  $crews.set([])
})

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe('Crew page', () => {
  // The test renders without the locale provider, so the English catalog shows.
  it('has at most three menus', () => {
    respond()
    page()
    expect(CREW_TABS).toHaveLength(3)
    expect(screen.getAllByRole('tab').map(t => t.textContent)).toEqual(['Crew', 'History', 'Advanced'])
  })

  it('shows the short onboarding once', () => {
    window.localStorage.removeItem(CREW_INTRO_KEY)
    respond()
    page()
    expect(screen.getByRole('dialog', { name: 'Meet Crew' })).toBeTruthy()
    fireEvent.click(screen.getByText('Got it'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(window.localStorage.getItem(CREW_INTRO_KEY)).toBe('1')
  })

  it('goal → crew.propose, then the proposal waits for approval with consent for side effects', async () => {
    respond({ 'crew.propose': PROPOSAL, 'crew.approve': { ...PROPOSAL, allow_side_effects: true, status: 'running' } })
    page()
    fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Perbaiki bug login' } })
    fireEvent.click(screen.getByText('Build crew'))
    await screen.findByText('Bug login')
    expect(gw.request).toHaveBeenCalledWith('crew.propose', { goal: 'Perbaiki bug login' })
    expect(screen.getByText('Designed by the main agent')).toBeTruthy()
    expect(screen.getAllByText('Fajar').length).toBeGreaterThan(0)
    expect(screen.getByText('Led by a manager', { exact: false })).toBeTruthy()
    const approve = screen.getByText('Approve & start') as HTMLButtonElement
    expect(approve.disabled).toBe(true)                    // side effects need the extra consent
    fireEvent.click(screen.getByRole('checkbox'))
    expect(approve.disabled).toBe(false)
    fireEvent.click(approve)
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('crew.approve', { allow_side_effects: true, id: 'c1' }))
  })

  it('templates send the template id', async () => {
    respond({ 'crew.propose': { ...PROPOSAL, designed_by: 'template', side_effects: [] } })
    page()
    fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Riset EV' } })
    fireEvent.click(screen.getByText('Research + Report'))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('crew.propose', { goal: 'Riset EV', template: 'riset_laporan' })
    )
  })

  it('a crew.update push moves the pixel room live and shows approvals', async () => {
    respond({ 'approval.respond': { ok: true } })
    $crew.set(PROPOSAL as never)
    page()
    act(() =>
      emitGatewayEvent({
        payload: {
          ...PROPOSAL,
          members: [
            { ...PROPOSAL.members[0], status: 'reviewing' },
            {
              ...PROPOSAL.members[1],
              approval: { command: 'npm test', request_id: 'apr-1', session_id: 's9' },
              status: 'waiting'
            }
          ],
          status: 'running',
          tasks: [task('t1', 'Implementasi', 'm2', { status: 'running' })]
        },
        session_id: null,
        type: 'crew.update'
      } as never)
    )
    expect(document.querySelector('[data-member="m2"]')?.getAttribute('data-status')).toBe('waiting')
    expect(document.querySelector('.nv-crew-station[data-status="reviewing"]')).toBeTruthy()
    expect(screen.getByText('npm test')).toBeTruthy()
    expect(screen.getByText('Stop')).toBeTruthy()
    fireEvent.click(screen.getByText('Allow'))
    await waitFor(() =>
      expect(gw.request).toHaveBeenCalledWith('approval.respond', { choice: 'once', request_id: 'apr-1', session_id: 's9' })
    )
  })

  it('Lanjutan edits role/tools/flow and saves through crew.update', async () => {
    respond({ 'crew.update': (p: { patch: Record<string, unknown> }) => ({ ...PROPOSAL, ...p.patch, updated_at: 11 }) })
    $crew.set(PROPOSAL as never)
    page()
    fireEvent.click(screen.getByText('Advanced'))
    const roles = screen.getAllByDisplayValue('Programmer')
    fireEvent.change(roles[0], { target: { value: 'Penguji' } })
    fireEvent.click(screen.getAllByLabelText('Web')[0])
    fireEvent.change(screen.getByLabelText('Flow'), { target: { value: 'sequential' } })
    fireEvent.click(screen.getByText('Save changes'))
    await waitFor(() => expect(gw.request).toHaveBeenCalledWith('crew.update', expect.anything()))

    const call = gw.request.mock.calls.find(c => c[0] === 'crew.update')![1] as {
      patch: { manager: null; members: Array<{ role: string; tools: string[] }>; process: string }
    }

    expect(call.patch.process).toBe('sequential')
    expect(call.patch.manager).toBeNull()
    expect(call.patch.members[1].role).toBe('Penguji')
    expect(call.patch.members[0].tools).toContain('web')
    expect(screen.getByText('Old office & company')).toBeTruthy()
  })

  it('history lists crews and opens one', async () => {
    respond({
      'crew.get': { ...PROPOSAL, final_output: 'Semua tes lulus', status: 'done' },
      'crew.list': { crews: [{ ...PROPOSAL, done: 1, members: 2, tasks: 1, status: 'done' }] }
    })
    page()
    fireEvent.click(screen.getByText('History'))
    fireEvent.click(await screen.findByText('Bug login'))
    await screen.findByText('Semua tes lulus')
    expect(screen.getByText('Run again')).toBeTruthy()
  })
})

describe('pixel sprite', () => {
  it('draws 12×21 side-view frames with ten palettes and animates by pose', () => {
    for (const set of Object.values(CREW_FRAMES)) {
      expect(set.length).toBeGreaterThan(0)
      expect(set.every(f => f.length === 21 && f.every(r => r.length === 12))).toBe(true)
    }

    expect(CREW_PALETTES).toHaveLength(10)
    expect(spritePixels(0, 'type', 0)).not.toEqual(spritePixels(0, 'type', 2)) // typing frames differ
    expect(spritePixels(0, 'walk', 0)).not.toEqual(spritePixels(0, 'walk', 2))
    expect(spritePixels(3, 'idle', 23).some(p => p.c === '#1a1010')).toBe(false) // blink: eyes closed
    expect(spritePixels(3, 'idle', 0).some(p => p.c === '#1a1010')).toBe(true)
    expect(spritePixels(13, 'cheer', 0)).toEqual(spritePixels(3, 'cheer', 0))
    expect(Math.max(...spritePixels(0, 'idle', 0).map(p => p.y))).toBe(20)
  })

  it('maps statuses to poses', () => {
    expect(crewPose('working', 'running')).toBe('type')
    expect(crewPose('reviewing', 'running')).toBe('walk')
    expect(crewPose('waiting', 'running')).toBe('wait')
    expect(crewPose('done', 'done')).toBe('cheer')
    expect(crewPose('error', 'failed')).toBe('slump')
    expect(crewPose('idle', 'running')).toBe('walk')
    expect(crewPose('idle', 'done')).toBe('idle')
    expect(crewPose('working', 'proposed')).toBe('think')
  })

  it('lays the building out at integer scale', () => {
    const phone = crewLayout(360, 3)
    expect(phone).toMatchObject({ cols: 2, floors: 2, scale: 3, width: 120 })
    const desk = crewLayout(644, 5)
    expect(desk).toMatchObject({ cols: 4, floors: 2, scale: 3 })
    expect(crewLayout(1200, 4)).toMatchObject({ scale: 4, cols: 6, floors: 1 })
    expect(crewLayout(200, 1).scale).toBe(2)
    expect(desk.bays).toHaveLength(8)
  })

  it('renders the scene with bubbles, tags and stations', () => {
    const { container } = render(
      <CrewScene
        crewStatus="running"
        members={[
          { avatar: 1, bubble: 'npm test', id: 'a', manager: true, name: 'Ana', status: 'waiting' },
          { avatar: 2, bubble: 'Draft', id: 'b', name: 'Budi', status: 'working' }
        ]}
        width={644}
      />
    )
    expect(container.querySelector('[data-crew-bubble="waiting"]')?.textContent).toBe('npm test')
    expect(container.querySelector('.nv-crew-station[data-member="b"]')?.getAttribute('data-pose')).toBe('type')
    expect(container.querySelector('.nv-crew-screen-lit')).toBeTruthy()
    expect(container.querySelector('.nv-crew-star-badge')).toBeTruthy()
    expect(container.querySelector('svg')?.getAttribute('width')).toBe(String(crewLayout(644, 2).width * 3))
  })

  it('renders solo stations for the intro', () => {
    const { container, rerender } = render(<CrewStation avatar={1} status="done" />)
    expect(container.querySelector('[data-crew-bubble="done"]')).toBeTruthy()
    rerender(<CrewStation avatar={1} status="working" />)
    expect(container.querySelector('.nv-crew-screen-lit')).toBeTruthy()
  })
})

describe('Crew strings', () => {
  it('exist in every bundled locale with the same keys', () => {
    const keys = (o: object): string[] =>
      Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? keys(v).map(x => `${k}.${x}`) : [k]))

    const base = keys(nvCrewEn).sort()

    for (const loc of [nvCrewId, nvCrewDe, nvCrewEs, nvCrewFr, nvCrewJa, nvCrewRu, nvCrewAr, nvCrewZh, nvCrewZhHant]) {
      expect(keys(loc).sort()).toEqual(base)
      expect(loc.title).toBe('Crew')
    }

    expect((NEOVARCH_ID as { nvCrew: unknown }).nvCrew).toBe(nvCrewId)
  })
})
