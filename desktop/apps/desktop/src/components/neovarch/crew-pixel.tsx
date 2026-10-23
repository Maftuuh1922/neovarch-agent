/**
 * Crew pixel scene: a side-view building cut open like a 2D sandbox game. Sky and two
 * drifting hill layers sit behind a brick shell with plank back walls and windows; every
 * member gets a desk bay on a wooden floor and moves by status (types, walks, waves,
 * cheers, thinks, slumps). Characters and palettes come from crew-pixel-data.ts, generated
 * by tool/crew_pixel/gen_crew_pixel.py, which also feeds the phone app. All art is original.
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

import { CREW_EYE_WHITE, CREW_FRAMES, CREW_H, CREW_KEYS, CREW_PALETTES, CREW_PUPIL, CREW_W, type CrewPose } from './crew-pixel-data'

export { CREW_FRAMES, CREW_PALETTES, type CrewPose } from './crew-pixel-data'

export type CrewMemberStatus = 'done' | 'error' | 'idle' | 'reviewing' | 'waiting' | 'working'

export interface Px {
  c: string
  x: number
  y: number
}

/** What a member does in the scene, from their own status and the crew's. */
export function crewPose(member: CrewMemberStatus, crew?: string): CrewPose {
  if (crew === 'proposed') {
    return 'think'
  }

  switch (member) {
    case 'working':
      return 'type'
    case 'reviewing':
      return 'walk'
    case 'waiting':
      return 'wait'
    case 'done':
      return 'cheer'
    case 'error':
      return 'slump'
    default:
      return crew === 'running' ? 'walk' : 'idle'
  }
}

/** One character frame as pixels (pure; tests and the scene share it). */
export function spritePixels(avatar: number, pose: CrewPose, tick: number): Px[] {
  const pal = CREW_PALETTES[((avatar % 10) + 10) % 10]
  const set = CREW_FRAMES[pose]
  // idle blinks briefly every ~3 s; everything else cycles its frames
  const i = pose === 'idle' ? (tick % 24 === 23 ? 1 : 0) : Math.floor(tick / 2) % set.length
  const out: Px[] = []

  set[i].forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const k = row[x]

      if (k === '.') {
        continue
      }

      const c = k === 'w' ? CREW_EYE_WHITE : k === 'e' ? CREW_PUPIL : pal[CREW_KEYS.indexOf(k)]
      out.push({ c, x, y })
    }
  })

  return out
}

export const BAY_W = 36
export const FLOOR_H = 48
const WALL = 4
const UTIL_W = 28
const SKY = 16
const ROOF = 14
const GROUND = 12

export interface CrewLayout {
  bays: Array<{ col: number; floor: number; x: number; y: number }>
  cols: number
  floors: number
  height: number
  scale: number
  width: number
}

/** Integer-scaled layout for a container `w` CSS px wide holding `n` members. */
export function crewLayout(w: number, n: number): CrewLayout {
  const scale = w >= 900 ? 4 : w >= 330 ? 3 : 2
  const width = Math.max(BAY_W + UTIL_W + WALL * 2, Math.floor(w / scale))
  const interior = width - WALL * 2
  const cols = Math.max(1, Math.min(6, Math.floor((interior - UTIL_W) / BAY_W)))
  const floors = Math.max(1, Math.ceil(n / cols))
  const height = SKY + ROOF + floors * FLOOR_H + GROUND
  const bays = Array.from({ length: floors * cols }, (_, i) => {
    const floor = Math.floor(i / cols)
    const col = i % cols

    // top floor first so the manager (first member) sits upstairs
    return { col, floor, x: WALL + col * BAY_W, y: SKY + ROOF + floor * FLOOR_H }
  })

  return { bays, cols, floors, height, scale, width }
}

function useTick(): number {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (typeof window === 'undefined' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      return
    }

    const t = window.setInterval(() => setTick(v => v + 1), 125)

    return () => window.clearInterval(t)
  }, [])

  return tick
}

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(fallback)

  useLayoutEffect(() => {
    const el = ref.current

    if (!el) {
      return
    }

    const read = () => el.clientWidth && setW(el.clientWidth)
    read()

    if (typeof ResizeObserver === 'undefined') {
      return
    }

    const ro = new ResizeObserver(read)
    ro.observe(el)

    return () => ro.disconnect()
  }, [])

  return [ref, w] as const
}

function Figure({ avatar, flip, pose, tick, x, y }: { avatar: number; flip?: boolean; pose: CrewPose; tick: number; x: number; y: number }) {
  const hop = pose === 'cheer' && Math.floor(tick / 2) % 2 === 1 ? -1 : 0

  return (
    <g transform={flip ? `translate(${x + CREW_W} ${y + hop}) scale(-1 1)` : `translate(${x} ${y + hop})`}>
      {spritePixels(avatar, pose, tick).map(p => (
        <rect fill={p.c} height={1} key={`${p.x}-${p.y}`} width={1} x={p.x} y={p.y} />
      ))}
    </g>
  )
}

/** Hill silhouette as 1-px columns (deterministic, wraps every 64 px so it can drift). */
function hills(width: number, base: number, amp: number, seed: number) {
  const out: Array<[number, number]> = []

  for (let x = 0; x < width + 64; x++) {
    const h = Math.round(amp * (0.6 + 0.4 * Math.sin((x + seed) / 9) * Math.cos((x + seed * 2) / 23)))
    out.push([x, base - h])
  }

  return out
}

/** The static shell: sky, hills, bricks, planks, floors, roof, ground, furniture. */
function Shell({ id, layout }: { id: string; layout: CrewLayout }) {
  const { bays, floors, height, width } = layout
  const top = SKY + ROOF
  const groundY = height - GROUND
  const utilX = width - WALL - UTIL_W
  const far = hills(width, top + 18, 14, 3)
  const near = hills(width, top + 30, 10, 41)

  return (
    <>
      <defs>
        <pattern height={4} id={`${id}-brick`} patternUnits="userSpaceOnUse" width={8}>
          <rect className="nv-crew-brick" height={4} width={8} />
          <rect className="nv-crew-brick-line" height={1} width={8} y={3} />
          <rect className="nv-crew-brick-line" height={2} width={1} x={3} y={1} />
        </pattern>
        <pattern height={6} id={`${id}-plank`} patternUnits="userSpaceOnUse" width={12}>
          <rect className="nv-crew-plank" height={6} width={12} />
          <rect className="nv-crew-plank-line" height={1} width={12} y={5} />
          <rect className="nv-crew-plank-line" height={5} width={1} x={7} />
        </pattern>
      </defs>
      <rect className="nv-crew-sky" height={height} width={width} />
      {[7, 23, 41, 66, 90, 117, 150, 181, 203].map((sx, i) => (
        <rect className="nv-crew-star" height={1} key={sx} width={1} x={sx % width} y={2 + ((i * 5) % 12)} />
      ))}
      <rect className="nv-crew-orb" height={6} width={6} x={width - 20} y={4} />
      <g className="nv-crew-hills nv-crew-hills-far">
        {far.map(([x, y]) => (
          <rect height={groundY - y} key={x} width={1} x={x} y={y} />
        ))}
      </g>
      <g className="nv-crew-hills nv-crew-hills-near">
        {near.map(([x, y]) => (
          <rect height={groundY - y} key={x} width={1} x={x} y={y} />
        ))}
      </g>
      {/* roof: stepped */}
      {[0, 1, 2, 3].map(i => (
        <rect className={i % 2 ? 'nv-crew-roof-shade' : 'nv-crew-roof'} height={3} key={i} width={width - 2 * (12 - i * 4)} x={12 - i * 4} y={SKY + i * 3} />
      ))}
      <rect className="nv-crew-roof-shade" height={2} width={width} y={SKY + 12} />
      {/* back wall around window holes, per floor */}
      {Array.from({ length: floors }, (_, f) => {
        const y = top + f * FLOOR_H
        const winY = y + 8

        return (
          <g key={f}>
            <rect fill={`url(#${id}-plank)`} height={8} width={width - WALL * 2} x={WALL} y={y} />
            <rect fill={`url(#${id}-plank)`} height={FLOOR_H - 4 - 18} width={width - WALL * 2} x={WALL} y={winY + 10} />
            {bays
              .filter(b => b.floor === f)
              .map(b => (
                <g key={b.col}>
                  <rect fill={`url(#${id}-plank)`} height={10} width={22} x={b.x} y={winY} />
                  <rect fill={`url(#${id}-plank)`} height={10} width={2} x={b.x + 34} y={winY} />
                  <rect className="nv-crew-frame-wood" height={10} width={1} x={b.x + 22} y={winY} />
                  <rect className="nv-crew-frame-wood" height={10} width={1} x={b.x + 33} y={winY} />
                  <rect className="nv-crew-frame-wood" height={1} width={12} x={b.x + 22} y={winY + 9} />
                </g>
              ))}
            <rect fill={`url(#${id}-plank)`} height={10} width={utilX - WALL - layout.cols * BAY_W + UTIL_W} x={WALL + layout.cols * BAY_W} y={winY} />
            {/* floor slab */}
            <rect className="nv-crew-slab" height={4} width={width - WALL * 2} x={WALL} y={y + FLOOR_H - 4} />
            <rect className="nv-crew-slab-shade" height={1} width={width - WALL * 2} x={WALL} y={y + FLOOR_H - 1} />
            {/* utility column: rack + coffee on the ground floor, books + plant upstairs, ladder between */}
            {f === floors - 1 ? (
              <g>
                <rect className="nv-crew-rack" height={20} width={9} x={utilX + 2} y={y + FLOOR_H - 24} />
                <rect className="nv-crew-metal" height={10} width={6} x={utilX + 14} y={y + FLOOR_H - 14} />
                <rect className="nv-crew-coffee" height={2} width={2} x={utilX + 16} y={y + FLOOR_H - 9} />
              </g>
            ) : (
              <g>
                <rect className="nv-crew-shelf" height={22} width={10} x={utilX + 2} y={y + FLOOR_H - 26} />
                {[0, 1, 2].map(r => (
                  <g key={r}>
                    <rect className="nv-crew-book-a" height={5} width={2} x={utilX + 3} y={y + FLOOR_H - 25 + r * 7} />
                    <rect className="nv-crew-book-b" height={5} width={2} x={utilX + 6} y={y + FLOOR_H - 25 + r * 7} />
                    <rect className="nv-crew-book-c" height={4} width={2} x={utilX + 9} y={y + FLOOR_H - 24 + r * 7} />
                  </g>
                ))}
                <rect className="nv-crew-pot" height={4} width={5} x={utilX + 15} y={y + FLOOR_H - 8} />
                <rect className="nv-crew-leaf" height={5} width={7} x={utilX + 14} y={y + FLOOR_H - 13} />
              </g>
            )}
            {f > 0 &&
              Array.from({ length: 13 }, (_, r) => (
                <rect className="nv-crew-ladder" height={1} key={r} width={5} x={utilX + 22} y={y - 4 + r * 4} />
              ))}
            {f > 0 && <rect className="nv-crew-ladder" height={FLOOR_H} width={1} x={utilX + 22} y={y - 4} />}
            {f > 0 && <rect className="nv-crew-ladder" height={FLOOR_H} width={1} x={utilX + 26} y={y - 4} />}
          </g>
        )
      })}
      {/* desks */}
      {bays.map(b => (
        <g key={`d${b.floor}-${b.col}`}>
          <rect className="nv-crew-desk" height={2} width={16} x={b.x + 19} y={b.y + FLOOR_H - 16} />
          <rect className="nv-crew-desk-shade" height={10} width={2} x={b.x + 20} y={b.y + FLOOR_H - 14} />
          <rect className="nv-crew-desk-shade" height={10} width={2} x={b.x + 32} y={b.y + FLOOR_H - 14} />
          <rect className="nv-crew-monitor" height={7} width={9} x={b.x + 24} y={b.y + FLOOR_H - 24} />
          <rect className="nv-crew-metal" height={1} width={3} x={b.x + 27} y={b.y + FLOOR_H - 17} />
        </g>
      ))}
      {/* outer stone shell */}
      <rect fill={`url(#${id}-brick)`} height={groundY - top + 2} width={WALL} y={top - 2} />
      <rect fill={`url(#${id}-brick)`} height={groundY - top + 2} width={WALL} x={width - WALL} y={top - 2} />
      {/* ground */}
      <rect className="nv-crew-dirt" height={GROUND} width={width} y={groundY} />
      <rect className="nv-crew-grass" height={2} width={width} y={groundY} />
      {Array.from({ length: Math.ceil(width / 7) }, (_, i) => (
        <rect className="nv-crew-dirt-speck" height={1} key={i} width={2} x={i * 7 + (i % 3)} y={groundY + 4 + (i % 4) * 2} />
      ))}
    </>
  )
}

export interface CrewSceneMember {
  activity?: string
  avatar: number
  bubble?: string
  id: string
  manager?: boolean
  name: string
  status: CrewMemberStatus
}

/** The whole building. Name tags and speech bubbles are HTML laid over the SVG. */
export function CrewScene({
  className,
  crewStatus,
  label,
  members,
  width: fixed
}: {
  className?: string
  crewStatus?: string
  label?: string
  members: CrewSceneMember[]
  width?: number
}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '')
  const [ref, measured] = useWidth(fixed ?? 644)
  const layout = useMemo(() => crewLayout(fixed ?? measured, members.length), [fixed, measured, members.length])
  const tick = useTick()
  const shell = useMemo(() => <Shell id={id} layout={layout} />, [id, layout])
  const { scale } = layout
  const rackOn = tick % 8 < 4

  const placed = members.map((m, i) => {
    const bay = layout.bays[i]
    const pose = crewPose(m.status, crewStatus)
    const floorY = bay.y + FLOOR_H - 4 - CREW_H
    let x = bay.x + 9
    let flip = false

    if (pose === 'walk') {
      // pace 0..22 px and back, each member offset so they don't march in step
      const span = 22
      const p = (tick + i * 7) % (span * 2)
      x = bay.x + 2 + (p < span ? p : span * 2 - p)
      flip = p >= span
    } else if (pose === 'wait' || pose === 'cheer' || pose === 'slump') {
      x = bay.x + 6
    }

    return { bay, flip, m, pose, x, y: floorY }
  })

  return (
    <div className={cn('nv-crew-scene', className)} data-slot="nv-crew-scene" ref={ref}>
      <svg
        aria-label={label}
        className="nv-crew-svg"
        height={layout.height * scale}
        role="img"
        shapeRendering="crispEdges"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        width={layout.width * scale}
      >
        {shell}
        <g className="nv-crew-leds">
          {Array.from({ length: 4 }, (_, r) => (
            <rect
              className={(r + Math.floor(tick / 3)) % 3 === 0 && rackOn ? 'nv-crew-led-on' : 'nv-crew-led'}
              height={1}
              key={r}
              width={2}
              x={layout.width - WALL - UTIL_W + 4}
              y={SKY + ROOF + layout.floors * FLOOR_H - 22 + r * 4}
            />
          ))}
          {Array.from({ length: 3 }, (_, k) => (
            <rect
              className="nv-crew-steam"
              height={1}
              key={k}
              width={1}
              x={layout.width - WALL - UTIL_W + 17 + ((tick + k) % 2)}
              y={SKY + ROOF + layout.floors * FLOOR_H - 17 - k * 2 - (tick % 3)}
            />
          ))}
        </g>
        {placed.map(({ bay, flip, m, pose, x, y }) => (
          <g className="nv-crew-station" data-member={m.id} data-pose={pose} data-status={m.status} key={m.id}>
            {pose === 'type' && <rect className="nv-crew-chair" height={8} width={3} x={bay.x + 9} y={y + 11} />}
            {pose === 'type' && <rect className="nv-crew-screen-lit" height={5} width={7} x={bay.x + 25} y={bay.y + FLOOR_H - 23} />}
            <Figure avatar={m.avatar} flip={flip} pose={pose} tick={tick} x={x} y={y} />
            {pose === 'walk' && m.status === 'reviewing' && (
              <g data-crew-clipboard="">
                <rect className="nv-crew-clip" height={4} width={3} x={flip ? x - 1 : x + 10} y={y + 10} />
                <rect fill="#f4f2ed" height={2} width={2} x={flip ? x - 0.5 : x + 10.5} y={y + 11} />
              </g>
            )}
          </g>
        ))}
      </svg>
      {placed.map(({ flip, m, pose, x, y }) => (
        <div
          className="nv-crew-tag"
          data-member={m.id}
          key={m.id}
          style={{ left: (x + CREW_W / 2) * scale, top: (y - 2) * scale }}
        >
          {m.bubble && (
            <span className={cn('nv-crew-bubble', pose === 'think' && 'nv-crew-bubble-think')} data-crew-bubble={m.status} data-flip={flip || undefined}>
              {m.bubble}
            </span>
          )}
          <span className="nv-crew-name">
            {m.manager && <span aria-hidden className="nv-crew-star-badge" />}
            {m.name}
          </span>
        </div>
      ))}
    </div>
  )
}

/** One member alone in a small bay (onboarding intro). */
export function CrewStation({
  avatar,
  className,
  label,
  size = 132,
  status
}: {
  avatar: number
  className?: string
  label?: string
  size?: number
  status: CrewMemberStatus
}) {
  const tick = useTick()
  const pose = crewPose(status)
  const s = Math.max(2, Math.floor(size / 32))

  return (
    <svg
      aria-label={label}
      className={cn('nv-crew-station nv-crew-station-solo', className)}
      data-pose={pose}
      data-status={status}
      height={28 * s}
      role="img"
      shapeRendering="crispEdges"
      viewBox="0 0 32 28"
      width={32 * s}
    >
      <rect className="nv-crew-plank" height={24} width={32} />
      <rect className="nv-crew-slab" height={4} width={32} y={24} />
      <rect className="nv-crew-desk" height={2} width={12} x={18} y={14} />
      <rect className="nv-crew-desk-shade" height={8} width={2} x={19} y={16} />
      <rect className="nv-crew-monitor" height={6} width={8} x={21} y={7} />
      {pose === 'type' && <rect className="nv-crew-screen-lit" height={4} width={6} x={22} y={8} />}
      <Figure avatar={avatar} pose={pose} tick={tick} x={pose === 'type' ? 6 : 3} y={3} />
      {(status === 'done' || status === 'waiting' || status === 'error') && (
        <g data-crew-bubble={status}>
          <rect className={`nv-crew-pip nv-crew-pip-${status}`} height={4} width={5} x={13} y={0} />
        </g>
      )}
    </svg>
  )
}
