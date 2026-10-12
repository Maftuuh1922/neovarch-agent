import { describe, expect, it } from 'vitest'

import { compactTokens, parseTokenUsage } from './token-usage-store'

describe('parseTokenUsage', () => {
  it('reads the core /api/usage answer', () => {
    const s = parseTokenUsage({
      date: '2026-10-12',
      lifetime: { cached: 250, calls: 3, input: 450, output: 55, total: 505 },
      models: [{ calls: 2, cached: 250, input: 400, model: 'mimo', output: 50, provider: '9router', total: 450 }],
      session: { cached: 0, calls: 1, input: 10, output: 2, total: 12 },
      today: { cached: 250, calls: 2, input: 350, output: 35, total: 385 }
    })

    expect(s?.today.total).toBe(385)
    expect(s?.lifetime.calls).toBe(3)
    expect(s?.session?.total).toBe(12)
    expect(s?.models[0]).toMatchObject({ model: 'mimo', provider: '9router', total: 450 })
  })

  it('returns null for an older core or junk', () => {
    expect(parseTokenUsage(null)).toBeNull()
    expect(parseTokenUsage({ detail: 'Not Found' })).toBeNull()
  })

  it('fills total from input + output and clamps junk numbers', () => {
    const s = parseTokenUsage({ lifetime: { input: 5, output: -3 }, today: { input: 'x', output: 4 } })

    expect(s?.lifetime).toEqual({ cached: 0, calls: 0, input: 5, output: 0, total: 5 })
    expect(s?.today.total).toBe(4)
  })
})

describe('compactTokens', () => {
  it.each([
    [950, '950'],
    [1500, '1,5rb'],
    [12_400, '12rb'],
    [3_400_000, '3,4jt'],
    [2_100_000_000, '2,1M'],
    [2_000_000, '2jt']
  ])('%d → %s', (n, out) => expect(compactTokens(n)).toBe(out))
})
