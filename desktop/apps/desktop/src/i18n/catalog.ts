import { mergeTranslations } from '@hermes/shared/i18n'

import { ar } from './ar'
import { de } from './de'
import { en as enUpstream } from './en'
import { es } from './es'
import { fr } from './fr'
import { ja } from './ja'
import { NEOVARCH_ID } from './neovarch-id'
import { ru } from './ru'
import type { BundledLocale, Translations } from './types'
import { zh } from './zh'
import { zhHant } from './zh-hant'

/** Neovarch's base catalog: upstream English with the Indonesian strings on top. */
export const NEOVARCH_BASE: Translations = mergeTranslations<Translations>(enUpstream, NEOVARCH_ID)

/** Unit tests run against the upstream English copy (the component tests assert
 *  those strings); `neovarch-id.test.ts` checks the Indonesian layer itself. The
 *  app — dev and production builds — always ships the Indonesian base. */
const en: Translations = import.meta.env.MODE === 'test' ? enUpstream : NEOVARCH_BASE

/** The catalogs compiled into the app. Runtime-registered languages (plugin
 *  packs, backend `.desktop.yaml` packs) are NOT here — resolve through
 *  `resolveTranslations()` in `./registry`, which layers them over these. */
export const TRANSLATIONS: Record<BundledLocale, Translations> = {
  en,
  // The ID/EN switch: plain English, the upstream catalog without the
  // Indonesian layer. `en` stays the Indonesian base (older desktops saved
  // `display.language: en` for it).
  'en-us': enUpstream,
  zh,
  'zh-hant': zhHant,
  ja,
  ar,
  ru,
  fr,
  de,
  es
}

export const BUNDLED_LOCALES = Object.keys(TRANSLATIONS) as readonly BundledLocale[]

export function isBundledLocale(value: unknown): value is BundledLocale {
  return typeof value === 'string' && Object.hasOwn(TRANSLATIONS, value)
}
