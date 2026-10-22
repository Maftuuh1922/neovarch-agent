// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

// @ts-expect-error plain .mjs build script without types
import { buildVisualBundle, BUNDLE_PATH } from '../../../scripts/build-visual-bundle.mjs'

describe('Android visual bundle', () => {
  it('assets/diagram/visual.js matches src/lib/visual (run scripts/build-visual-bundle.mjs)', async () => {
    const built: string = await buildVisualBundle()
    expect(readFileSync(BUNDLE_PATH, 'utf8')).toBe(built)
  }, 60_000)
})
