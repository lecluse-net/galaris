import { useI18n } from 'vue-i18n'

const uuid = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'

/** Resolve an exact business reference or its same-installation page URL. */
export function referenceId(value: string, kind: string, path: string, parameter?: string): string | null {
  const native = new RegExp(`^galaris://${kind}/(${uuid})$`, 'i').exec(value)
  if (native) return native[1]!.toLowerCase()
  try {
    const url = new URL(value, window.location.origin)
    if (url.origin !== window.location.origin) return null
    const id = parameter ? url.pathname === path ? url.searchParams.get(parameter) : null
      : url.pathname.startsWith(path + '/') ? url.pathname.slice(path.length + 1) : null
    return id && new RegExp(`^${uuid}$`, 'i').test(id) ? id.toLowerCase() : null
  } catch { return null }
}

/** A portable HTML snapshot; UI controls and full execution content never enter the document. */
export function referenceCardHtml(uri: string, title: string, metadata: readonly (string | null | undefined)[], details: readonly string[] = []): string {
  const card = document.createElement('blockquote'), heading = document.createElement('p')
  card.className = 'galaris-link-card'
  const link = document.createElement('a'), label = document.createElement('strong')
  link.href = uri; label.textContent = title; link.append(label); heading.append(link); card.append(heading)
  for (const text of [metadata.filter(Boolean).join(' · '), ...details, uri]) {
    if (!text) continue
    const paragraph = document.createElement('p'); paragraph.textContent = text; card.append(paragraph)
  }
  return card.outerHTML
}
export function referenceDate(value: string | null | undefined, formatting = defaultReferenceFormatting): string {
  if (!value || !Number.isFinite(Date.parse(value))) return ''
  return new Intl.DateTimeFormat(formatting.locale, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

export function referenceStatus(key: string, status: string, formatting = defaultReferenceFormatting): string {
  const path = `${key}.${status}`
  return formatting.te(path) ? formatting.t(path) : status
}

export interface ReferenceFormatting {
  locale: string
  t: (key: string, values?: Record<string, string | number>) => string
  te: (key: string) => boolean
}
export function useReferenceFormatting(): () => ReferenceFormatting {
  const { t, te, locale } = useI18n()
  return () => ({ locale: locale.value, te, t: (key, values) => values ? t(key, values) : t(key) })
}
export const defaultReferenceFormatting: ReferenceFormatting = {
  locale: document.documentElement.lang || 'en', t: key => key, te: () => false,
}
