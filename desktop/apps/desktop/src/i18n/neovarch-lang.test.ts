import { afterEach, describe, expect, it } from 'vitest'

import { nvRailCopy } from '@/components/neovarch/rail'

import { TRANSLATIONS } from './catalog'
import { localeConfigValue, normalizeLocale, resolveInitialLocale } from './languages'
import { nvLang } from './neovarch-lang'
import { NV_SOCIAL_EN, NV_SOCIAL_ID, socialT } from './neovarch-social'
import { setRuntimeI18nLocale } from './runtime'

describe('Neovarch ID/EN switch', () => {
  afterEach(() => setRuntimeI18nLocale('en'))

  it('keeps Indonesian as the default and for every older saved value', () => {
    expect(normalizeLocale('en')).toBe('en') // what older desktops saved for "Bahasa Indonesia"
    expect(nvLang('en')).toBe('id')
    expect(resolveInitialLocale(undefined, 'en-US')).toBe('en') // an English OS does not switch it
    expect(resolveInitialLocale(undefined, 'id-ID')).toBe('en')
  })

  it('English is a real choice that round-trips through display.language', () => {
    expect(localeConfigValue('en-us')).toBe('en-US')
    expect(normalizeLocale('en-US')).toBe('en-us')
    expect(resolveInitialLocale('en-US', 'id-ID')).toBe('en-us')
    expect(TRANSLATIONS['en-us'].settings.nav.about).toBe('About')
    expect(nvLang('en-us')).toBe('en')
  })

  it('switches Neovarch-only copy with the upstream strings', () => {
    expect(nvRailCopy('en').settings).toBe('Pengaturan')
    expect(nvRailCopy('en-us').settings).toBe('Settings')
    expect(nvRailCopy('en-us').social).toBe('Profile & Friends')
    expect(socialT('signIn')).toBe('Masuk dengan GitHub')
    setRuntimeI18nLocale('en-us')
    expect(socialT('signIn')).toBe('Sign in with GitHub')
    expect(socialT('friendsCount', { coding: 1, n: 3 })).toBe('3 friends · 1 coding now')
  })

  it('has English for every Indonesian social string, with the same placeholders', () => {
    for (const key of Object.keys(NV_SOCIAL_ID) as (keyof typeof NV_SOCIAL_ID)[]) {
      const want = NV_SOCIAL_ID[key].match(/\{\w+\}/g)?.sort() ?? []
      expect(NV_SOCIAL_EN[key].match(/\{\w+\}/g)?.sort() ?? [], key).toEqual(want)
    }
  })
})
