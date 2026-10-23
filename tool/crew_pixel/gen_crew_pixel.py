#!/usr/bin/env python3
"""Crew pixel art: the single source of the side-view character frames and palettes.

All art here is original (drawn for Neovarch). Run from the repo root:

    python3 tool/crew_pixel/gen_crew_pixel.py

It writes desktop/apps/desktop/src/components/neovarch/crew-pixel-data.ts and
lib/remote/ui/crew_pixel_data.dart so desktop and phone draw the same people.

Legend: h hair · s skin · w eye white · e pupil · c shirt · d shirt shade ·
p pants · q pants shade · o shoes · . empty. Characters face right; 12×21.
"""
from __future__ import annotations

import json
import os

W, H = 12, 21

HEAD = [
    '...hhhhh....',
    '..hhhhhhh...',
    '..hhhhhhhh..',
    '..hhssssss..',
    '..hssswes...',
    '..hsssssss..',
    '...sssssss..',
    '....ssss....',
]
BLINK = '..hsssssss..'

TORSO = [
    '...cccccc...',
    '..cccccccc..',
    '..cdccccdc..',
    '..cdccccdc..',
    '..cdccccdc..',
    '..s.cccc.s..',
]

LEGS_STAND = [
    '....pppp....',
    '....pppp....',
    '....pq.pq...',
    '....pq.pq...',
    '....pq.pq...',
    '....pq.pq...',
    '...ooo.ooo..',
]

# four-step walk cycle (legs only)
LEGS_WALK = [
    LEGS_STAND,
    ['....pppp....', '....pppp....', '...pq..pq...', '...pq...pq..', '..pq....pq..', '..pq.....pq.', '.ooo....ooo.'],
    ['....pppp....', '....pppp....', '....pqpq....', '....pqpq....', '....pqpq....', '....pqpq....', '....oooo....'],
    ['....pppp....', '....pppp....', '...pq..pq...', '..pq...pq...', '..pq....pq..', '.pq.....pq..', '.ooo....ooo.'],
]

LEGS_SIT = [
    '....ppppppp.',
    '....qqqqqqq.',
    '.........pq.',
    '.........pq.',
    '.........pq.',
    '.........pq.',
    '.........ooo',
]

TYPE_ARMS = [
    ['..cccccccc..', '..ccccccddss', '..cccccc....', '...cccc.....'],
    ['..cccccccc..', '..ccccccdd..', '..cccccc..ss', '...cccc.....'],
]


def put(rows: list[str], x: int, y: int, k: str) -> None:
    r = list(rows[y])
    r[x] = k
    rows[y] = ''.join(r)


def figure(head=HEAD, torso=TORSO, legs=LEGS_STAND) -> list[str]:
    rows = list(head) + list(torso) + list(legs)
    assert len(rows) == H and all(len(r) == W for r in rows), rows
    return rows


def blink(rows: list[str]) -> list[str]:
    rows = list(rows)
    rows[4] = BLINK
    return rows


def frames() -> dict[str, list[list[str]]]:
    idle = figure()
    walk = [figure(legs=l) for l in LEGS_WALK]
    type_a = figure(torso=[TORSO[0]] + TYPE_ARMS[0] + ['....cccc....'], legs=LEGS_SIT)
    type_b = figure(torso=[TORSO[0]] + TYPE_ARMS[1] + ['....cccc....'], legs=LEGS_SIT)

    # wave: right arm raised, hand swings between two columns
    wave = []
    for hx in (10, 11):
        r = figure(torso=['...cccccc...', '..ccccccc...', '..cdcccc....', '..cdcccc....', '..cdcccc....', '..s.cccc....'])
        put(r, 9, 8, 'd'); put(r, 10, 7, 'd'); put(r, hx, 5, 's'); put(r, hx, 6, 's')
        wave.append(r)

    # cheer: both arms up, second frame is a hop (renderer lifts it one pixel)
    cheer = []
    for _ in range(2):
        r = figure(torso=['..dccccccd..', '...cccccc...', '...cccccc...', '...cccccc...', '...cccccc...', '....cccc....'])
        for x in (1, 10):
            put(r, x, 5, 's'); put(r, x, 6, 's'); put(r, x, 7, 'd')
        put(r, 2, 8, 'd'); put(r, 9, 8, 'd')
        cheer.append(r)
    cheer[1] = blink(cheer[1])  # happy squint on the hop

    # think: hand on chin, eyes look up
    think = []
    for i in range(2):
        r = figure(torso=['...cccccc...', '..cccccccd..', '..cdccccd...', '..cdcccd....', '..cdcccc....', '..s.cccc....'])
        put(r, 9, 7, 's'); put(r, 8, 8, 's')
        if i == 1:
            r[4] = '..hssssew...'
        think.append(r)

    # slump: head sunk, eyes shut, arms hanging
    slump_head = ['............'] + HEAD[:4] + [BLINK, '..hsssssss..', '...sssssss..']
    slump = [figure(head=slump_head, torso=['...cccccc...', '..cccccccc..', '..cdccccdc..', '..cdccccdc..', '..sdccccds..', '....cccc....'])]
    slump.append(slump[0])

    return {
        'cheer': cheer,
        'idle': [idle, blink(idle)],
        'slump': slump,
        'think': think,
        'type': [type_a, type_b],
        'wait': wave,
        'walk': walk,
    }


# hair, skin, shirt, shirt shade, pants, pants shade, shoes: ten looks picked by avatar (0-9)
PALETTES = [
    ['#2b1a12', '#f1c7a1', '#ee1c1c', '#8f0a0a', '#2a3550', '#1b2338', '#3a2418'],
    ['#111111', '#e0ac85', '#3d5a80', '#293d57', '#4a4a4a', '#2e2e2e', '#151515'],
    ['#6b3a1e', '#f6d2b4', '#f2b134', '#b67f12', '#5a3f2a', '#3d2a1b', '#2b1a12'],
    ['#1b1b2f', '#c68863', '#2f9e74', '#1d6b4e', '#3b3b5c', '#26263d', '#111111'],
    ['#3a2418', '#d79b72', '#8e6cd8', '#5c43a0', '#2e2e3a', '#1e1e27', '#4b1d0f'],
    ['#c7c2b8', '#f0c9a6', '#262626', '#111111', '#6b6458', '#4a443b', '#262626'],
    ['#4b1d0f', '#a86b4c', '#e8e4dc', '#b5afa5', '#2a4d69', '#1b3347', '#3a2418'],
    ['#e05d2b', '#f4d0b2', '#1f7a8c', '#14525e', '#3a3a3a', '#262626', '#5a3f2a'],
    ['#0d0d0d', '#8d5a3c', '#d94f70', '#9e2f4b', '#2b2b40', '#1b1b2a', '#0d0d0d'],
    ['#5a4636', '#e9b994', '#6a8f2a', '#47611b', '#5a4636', '#3d2f24', '#2b1a12'],
]
EYE_WHITE, PUPIL = '#f4f2ed', '#1a1010'
KEYS = 'hscdpqo'


def main() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    f = frames()
    head = '// GENERATED by tool/crew_pixel/gen_crew_pixel.py: edit the generator, not this file.\n'
    ts = head + (
        f'export const CREW_W = {W}\nexport const CREW_H = {H}\n'
        f"export const CREW_EYE_WHITE = '{EYE_WHITE}'\nexport const CREW_PUPIL = '{PUPIL}'\n"
        f"export const CREW_KEYS = '{KEYS}'\n"
        '/** hair, skin, shirt, shirt shade, pants, pants shade, shoes */\n'
        f'export const CREW_PALETTES: string[][] = {json.dumps(PALETTES, indent=2)}\n'
        'export type CrewPose = ' + ' | '.join(f"'{k}'" for k in sorted(f)) + '\n'
        f'export const CREW_FRAMES: Record<CrewPose, string[][]> = {json.dumps(f, indent=2)}\n'
    ).replace('"', "'")
    dart = head + (
        f'const crewW = {W};\nconst crewH = {H};\n'
        f"const crewEyeWhite = 0xFF{EYE_WHITE[1:]};\nconst crewPupil = 0xFF{PUPIL[1:]};\n"
        f"const crewKeys = '{KEYS}';\n"
        '/// hair, skin, shirt, shirt shade, pants, pants shade, shoes\n'
        'const crewPalettes = <List<int>>[\n'
        + ''.join('  [' + ', '.join('0xFF' + c[1:] for c in p) + '],\n' for p in PALETTES)
        + '];\n'
        'const crewFrames = <String, List<List<String>>>{\n'
        + ''.join(
            f"  '{k}': [\n" + ''.join('    [' + ', '.join(f"'{r}'" for r in fr) + '],\n' for fr in v) + '  ],\n'
            for k, v in sorted(f.items())
        )
        + '};\n'
    )
    with open(os.path.join(root, 'desktop/apps/desktop/src/components/neovarch/crew-pixel-data.ts'), 'w') as fh:
        fh.write(ts)
    with open(os.path.join(root, 'lib/remote/ui/crew_pixel_data.dart'), 'w') as fh:
        fh.write(dart)


if __name__ == '__main__':
    main()
