/**
 * Neovarch's ID/EN switch for Neovarch-only copy (rail, Profil & Teman, …)
 * that lives outside the upstream key tree. `display.language: en` is the
 * Indonesian base (see catalog.ts); any other language shows the English copy,
 * so picking English in Settings changes these surfaces too, not only the
 * upstream strings.
 */
import { getRuntimeI18nLocale } from './runtime'
import type { Locale } from './types'

export type NvLang = 'en' | 'id'

export function nvLang(locale: Locale = getRuntimeI18nLocale()): NvLang {
  return locale === 'en' ? 'id' : 'en'
}

/** `{ id, en }` → the string for the active (or given) locale. */
export function nvPick<T>(copy: { en: T; id: T }, locale?: Locale): T {
  return copy[nvLang(locale)]
}
