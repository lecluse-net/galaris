import { i18n } from '@/core/i18n'

export interface AuthorizeLabel {
  code: string
  display_name?: string | null
}

/**
 * Resolve reference-data labels that contain an i18n key while preserving
 * administrator-defined free text and the technical code fallback.
 */
export function localizedAuthorizeLabel(item: AuthorizeLabel): string {
  const label = item.display_name?.trim()
  if (!label) return item.code
  return i18n.global.te(label) ? i18n.global.t(label) : label
}
