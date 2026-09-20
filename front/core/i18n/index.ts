import { createI18n, type LocaleMessageValue, type VueMessageType } from 'vue-i18n'
import { Lang } from 'quasar'
import quasarEn from 'quasar/lang/en-US'
import quasarFr from 'quasar/lang/fr'
import quasarZh from 'quasar/lang/zh-CN'
import baseFr from './locales/fr'
import baseEn from './locales/en'
import baseZh from './locales/zh'
import { deepMergeMessages } from './merge'

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

type Messages = Record<string, LocaleMessageValue<VueMessageType>>

// Shared base messages (common and language).
const messages: Record<AppLocale, Messages> = {
  fr: { ...baseFr },
  en: { ...baseEn },
  zh: { ...baseZh },
}

// Collect module locales automatically. Every app/**, core/**, or bridge/** i18n.ts file
// exporting { fr, en, zh } is merged into the shared instance. English remains the
// per-key fallback while a module's Chinese catalog is being loaded.
const moduleLocales = import.meta.glob<{ default: { fr: Messages; en: Messages; zh?: Messages } }>(
  ['../../app/**/i18n.ts', '../../core/**/i18n.ts', '../../bridge/**/i18n.ts'],
  { eager: true }
)
for (const path in moduleLocales) {
  const mod = moduleLocales[path].default
  if (mod?.fr) deepMergeMessages(messages.fr, mod.fr)
  if (mod?.en) deepMergeMessages(messages.en, mod.en)
  if (mod?.en) deepMergeMessages(messages.zh, mod.en)
  if (mod?.zh) deepMergeMessages(messages.zh, mod.zh)
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

const initialLocale = detectBrowserLocale()

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: initialLocale,
  fallbackLocale: DEFAULT_LOCALE,
  messages,
})

/** Apply the in-memory locale. The user profile remains the persistence source of truth. */
export function setLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  Lang.set(quasarLocales[locale])
  document.documentElement.setAttribute('lang', locale)
}

/**
 * Apply the user's preferred locale, then the browser locale, then English.
 */
export function applyUserLocale(preferred?: string | null): void {
  setLocale(isSupportedLocale(preferred) ? preferred : detectBrowserLocale())
}

/** Return the current locale. */
export function getLocale(): AppLocale {
  return i18n.global.locale.value as AppLocale
}

document.documentElement.setAttribute('lang', initialLocale)
Lang.set(quasarLocales[initialLocale])

export default i18n
