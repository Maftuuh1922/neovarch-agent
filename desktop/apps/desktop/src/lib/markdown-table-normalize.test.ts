import { describe, expect, it } from 'vitest'

import { preprocessMarkdown } from './markdown-preprocess'
import { normalizeMarkdownTables } from './markdown-table-normalize'

// The exact shape from the 1.4.7 bug report (MiMo via 9Router).
const ONE_LINE =
  '2. Soal "mimo 2.5" — ketiga rute mati di hulunya: | Rute | Error | Perbaikan | |---|---|---| | `mimo/mimo-v2.5` | 401 Invalid API Key | isi API key | | `op-p/mimo-v2.5` | 402 saldo $0 | top up | | `mimo/mimo-v2.6-flash` | 403 membership habis | berlangganan |'

describe('normalizeMarkdownTables', () => {
  it('splits a one-line table into header, delimiter and rows, prose kept apart', () => {
    const out = normalizeMarkdownTables(ONE_LINE)
    expect(out.split('\n')).toEqual([
      '2. Soal "mimo 2.5" — ketiga rute mati di hulunya:',
      '',
      '| Rute | Error | Perbaikan |',
      '| --- | --- | --- |',
      '| `mimo/mimo-v2.5` | 401 Invalid API Key | isi API key |',
      '| `op-p/mimo-v2.5` | 402 saldo $0 | top up |',
      '| `mimo/mimo-v2.6-flash` | 403 membership habis | berlangganan |'
    ])
  })

  it('keeps text after the table as its own paragraph', () => {
    const out = normalizeMarkdownTables('| a | b | |:--|--:| | 1 | 2 | Jadi begitu.')
    expect(out.split('\n')).toEqual(['| a | b |', '| :-- | --: |', '| 1 | 2 |', '', 'Jadi begitu.'])
  })

  it('does not split on pipes inside inline code or escaped pipes', () => {
    const out = normalizeMarkdownTables('| cmd | arti | |---|---| | `a | b` | pipa \\| literal |')
    expect(out.split('\n')).toEqual(['| cmd | arti |', '| --- | --- |', '| `a | b` | pipa \\| literal |'])
  })

  it('streaming: nothing changes before the delimiter is complete; a half row is kept', () => {
    expect(normalizeMarkdownTables('Tabel: | a | b | |-')).toBe('Tabel: | a | b | |-')
    const partial = normalizeMarkdownTables('| a | b | |---|---| | 1 | 2 | | 3')
    expect(partial.split('\n')).toEqual(['| a | b |', '| --- | --- |', '| 1 | 2 |', '| 3 |  |'])
  })

  it('moves prose off a header line when the delimiter is on the next line', () => {
    const out = normalizeMarkdownTables('Ringkasan: | a | b |\n|---|---|\n| 1 | 2 |')
    expect(out.split('\n')).toEqual(['Ringkasan:', '', '| a | b |', '|---|---|', '| 1 | 2 |'])
  })

  it('leaves proper tables, code fences and plain pipes alone', () => {
    const proper = '| a | b |\n|---|---|\n| 1 | 2 |'
    expect(normalizeMarkdownTables(proper)).toBe(proper)
    const fenced = '```\n| a | b | |---|---| | 1 | 2 |\n```'
    expect(normalizeMarkdownTables(fenced)).toBe(fenced)
    expect(normalizeMarkdownTables('pilih a | b saja')).toBe('pilih a | b saja')
  })

  it('runs inside preprocessMarkdown (chat transcript path)', () => {
    const out = preprocessMarkdown(ONE_LINE)
    expect(out).toContain('\n| Rute | Error | Perbaikan |\n| --- | --- | --- |\n')
  })
})
