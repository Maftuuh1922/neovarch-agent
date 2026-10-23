/**
 * Pixel art for Crew members: a 12×12 bust sprite behind a little desk with a laptop,
 * drawn as crisp SVG rects (no images, no gradients). The same sprite map and palettes
 * live in the phone app (lib/remote/ui/crew_pixel.dart) so both look alike.
 *
 * Status drives the scene: `working` types (two frames) with a lit laptop, `reviewing`
 * holds a clipboard, `waiting` shows a "!" bubble, `done` a check bubble, `idle` blinks.
 */
import { cn } from '@/lib/utils'

export type CrewMemberStatus = 'done' | 'error' | 'idle' | 'reviewing' | 'waiting' | 'working'

// h hair · s skin · e eye · c shirt · d shirt shade · . empty
export const CREW_SPRITE = [
  '....hhhh....',
  '...hhhhhh...',
  '..hhhhhhhh..',
  '..hssssssh..',
  '..sesssses..',
  '..ssssssss..',
  '...ssssss...',
  '....ssss....',
  '..cccccccc..',
  '.cccccccccc.',
  '.cdccccccdc.',
  '.cdccccccdc.'
]

// eyes closed (blink) for idle
const BLINK_ROW = '..ssssssss..'

// hands on the desk, two typing frames
export const CREW_HANDS = ['..ss....ss..', '...ss..ss...']

/** hair, skin, shirt, shirt shade: ten looks, picked by `avatar` (0-9). */
export const CREW_PALETTES: Array<[string, string, string, string]> = [
  ['#2b1a12', '#f1c7a1', '#ee1c1c', '#8f0a0a'],
  ['#111111', '#e0ac85', '#3d5a80', '#293d57'],
  ['#6b3a1e', '#f6d2b4', '#f2b134', '#b67f12'],
  ['#1b1b2f', '#c68863', '#2f9e74', '#1d6b4e'],
  ['#3a2418', '#d79b72', '#8e6cd8', '#5c43a0'],
  ['#c7c2b8', '#f0c9a6', '#262626', '#111111'],
  ['#4b1d0f', '#a86b4c', '#e8e4dc', '#b5afa5'],
  ['#e05d2b', '#f4d0b2', '#1f7a8c', '#14525e'],
  ['#0d0d0d', '#8d5a3c', '#d94f70', '#9e2f4b'],
  ['#5a4636', '#e9b994', '#6a8f2a', '#47611b']
]

const EYE = '#1a1010'

export interface Px {
  c: string
  x: number
  y: number
}

/** The sprite as pixels for one frame (pure; tests and the phone renderer share the map). */
export function spritePixels(avatar: number, status: CrewMemberStatus, frame: number): Px[] {
  const [hair, skin, shirt, shade] = CREW_PALETTES[((avatar % 10) + 10) % 10]
  const colors: Record<string, string> = { c: shirt, d: shade, e: EYE, h: hair, s: skin }
  const rows = [...CREW_SPRITE]

  if (status === 'idle' && frame % 2 === 1) {
    rows[4] = BLINK_ROW
  }

  if (status === 'working' || status === 'reviewing') {
    rows.push(CREW_HANDS[frame % 2])
  } else {
    rows.push(CREW_HANDS[0])
  }

  const out: Px[] = []
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const k = row[x]

      if (k !== '.') {
        out.push({ c: colors[k], x, y })
      }
    }
  })

  return out
}

function Rects({ px, dx = 0, dy = 0 }: { px: Px[]; dx?: number; dy?: number }) {
  return (
    <>
      {px.map(p => (
        <rect fill={p.c} height={1} key={`${p.x}-${p.y}`} width={1} x={p.x + dx} y={p.y + dy} />
      ))}
    </>
  )
}

function Bubble({ status }: { status: CrewMemberStatus }) {
  if (status !== 'waiting' && status !== 'done' && status !== 'error') {
    return null
  }

  const fill = status === 'done' ? '#2f9e74' : status === 'waiting' ? '#f2b134' : '#ee1c1c'

  return (
    <g data-crew-bubble={status}>
      <rect fill={fill} height={5} width={6} x={15} y={0} />
      <rect fill={fill} height={1} width={1} x={16} y={5} />
      {status === 'done' ? (
        <>
          <rect fill="#fff" height={1} width={1} x={16} y={2} />
          <rect fill="#fff" height={1} width={1} x={17} y={3} />
          <rect fill="#fff" height={1} width={1} x={18} y={2} />
          <rect fill="#fff" height={1} width={1} x={19} y={1} />
        </>
      ) : (
        <>
          <rect fill="#1a1010" height={2} width={1} x={18} y={1} />
          <rect fill="#1a1010" height={1} width={1} x={18} y={3} />
        </>
      )}
    </g>
  )
}

/** One member at their desk. `size` is the rendered width in CSS px (height follows 22×19). */
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
  const lit = status === 'working' || status === 'reviewing'

  return (
    <svg
      aria-label={label}
      className={cn('nv-crew-station', className)}
      data-status={status}
      height={(size * 19) / 22}
      role="img"
      shapeRendering="crispEdges"
      viewBox="0 0 22 19"
      width={size}
    >
      {/* chair back */}
      <rect className="nv-crew-chair" height={6} width={10} x={6} y={7} />
      {/* the member: two frames swapped by CSS steps() so typing/blinking needs no JS timer */}
      <g className="nv-crew-frame nv-crew-frame-a">
        <Rects dx={5} dy={2} px={spritePixels(avatar, status, 0)} />
      </g>
      <g className="nv-crew-frame nv-crew-frame-b">
        <Rects dx={5} dy={2} px={spritePixels(avatar, status, 1)} />
      </g>
      {status === 'reviewing' && (
        <g data-crew-clipboard="">
          <rect fill="#b67f12" height={4} width={3} x={15} y={11} />
          <rect fill="#f4f2ed" height={2} width={2} x={15.5} y={12} />
        </g>
      )}
      {/* desk */}
      <rect className="nv-crew-desk" height={2} width={22} x={0} y={15} />
      <rect className="nv-crew-desk-shade" height={2} width={2} x={1} y={17} />
      <rect className="nv-crew-desk-shade" height={2} width={2} x={19} y={17} />
      {/* laptop seen from behind; its rim lights while the member works */}
      <rect className={cn('nv-crew-laptop', lit && 'nv-crew-laptop-lit')} height={4} width={7} x={7.5} y={11} />
      <rect className="nv-crew-laptop-logo" height={1} width={1} x={10.5} y={12.5} />
      <Bubble status={status} />
    </svg>
  )
}
