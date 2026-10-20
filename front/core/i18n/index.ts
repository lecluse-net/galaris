import { createI18n } from 'vue-i18n'
import { Lang } from 'quasar'
import quasarEn from 'quasar/lang/en-US'
import quasarFr from 'quasar/lang/fr'
import quasarZh from 'quasar/lang/zh-CN'
import english from './catalogs/en'
import frenchUrl from 'virtual:galaris-locale-fr'
import chineseUrl from 'virtual:galaris-locale-zh'
import type { Messages } from './catalogs/merge'

export type AppLocale = 'fr' | 'en' | 'zh'

export const SUPPORTED_LOCALES: { value: AppLocale; label: string }[] = [
  { value: 'fr', label: 'Français' },
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文（简体）' },
]

/** Fallback locale when neither a profile nor the browser provides a supported locale. */
export const DEFAULT_LOCALE: AppLocale = 'en'

export function isSupportedLocale(value: unknown): value is AppLocale {
  return value === 'fr' || value === 'en' || value === 'zh'
}

const quasarLocales = { fr: quasarFr, en: quasarEn, zh: quasarZh } as const

/**
 * Return the locale matching the browser's primary language when supported
 * (any regional variant matches its base language, e.g. fr-CA -> fr),
 * otherwise the English fallback.
 */
export function detectBrowserLocale(): AppLocale {
  const base = (navigator.language || '').toLowerCase().split('-')[0]
  return isSupportedLocale(base) ? base : DEFAULT_LOCALE
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages: { en: english, fr: {}, zh: {} },
})

const catalogUrls = { fr: frenchUrl, zh: chineseUrl }
const loaded = new Set<AppLocale>(['en'])
const pending = new Map<AppLocale, Promise<void>>()
let localeRequest = 0

/** Prepare a language once; failed downloads remain retryable. */
async function loadLocale(locale: AppLocale): Promise<void> {
  if (loaded.has(locale) || locale === 'en') return
  let request = pending.get(locale)
  if (!request) {
    request = fetch(catalogUrls[locale]).then(async response => {
      if (!response.ok) throw new Error(`Unable to load ${locale} catalog: HTTP ${response.status}`)
      const messages: unknown = await response.json()
      if (!messages || typeof messages !== 'object' || Array.isArray(messages)) throw new Error(`Invalid ${locale} catalog`)
      i18n.global.setLocaleMessage(locale, messages as Messages)
      loaded.add(locale)
    }).finally(() => { pending.delete(locale) })
    pending.set(locale, request)
  }
  await request
}

/** Switch only after loading, and never apply an obsolete session or choice. */
export function setLocale(locale: AppLocale, isCurrent: () => boolean = () => true): Promise<boolean> {
  const request = ++localeRequest
  const apply = (): boolean => {
    if (request !== localeRequest || !isCurrent()) return false
    i18n.global.locale.value = locale
    Lang.set(quasarLocales[locale])
    document.documentElement.setAttribute('lang', locale)
    return true
  }
  // Cached languages still apply synchronously, including the English fallback.
  if (loaded.has(locale)) return Promise.resolve(apply())
  return loadLocale(locale).then(apply)
}

/**
 * Apply the user's preferred locale, then the browser locale, then English.
 */
export function applyUserLocale(preferred?: string | null, isCurrent?: () => boolean): Promise<boolean> {
  return setLocale(isSupportedLocale(preferred) ? preferred : detectBrowserLocale(), isCurrent)
}

/** Return the current locale. */
export function getLocale(): AppLocale {
  return i18n.global.locale.value as AppLocale
}

document.documentElement.setAttribute('lang', DEFAULT_LOCALE)
Lang.set(quasarLocales.en)

// Bootstrap waits before mounting. An unavailable language leaves a usable
// English interface; selecting it again can retry the download.
export const initialLocaleReady = applyUserLocale().catch(error => {
  console.error('Unable to load the browser language:', error)
})

export default i18n
