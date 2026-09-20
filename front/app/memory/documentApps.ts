export interface DocumentApp {
  id: string
  title: string
  html?: string
  css?: string
  javascript?: string
  datasets?: Record<string, { uri: string; access?: 'read' | 'write' }>
}
export interface AppDatasetRequest {
  operation: 'read' | 'replace' | 'append'
  expected_revision?: number
  value?: unknown
}
export interface AppDatasetResult { revision: number; data: unknown }
export interface AppGrant {
  app_key: string
  app_title: string
  alias: string
  dataset_id: string
  dataset_title: string | null
  requested_access: 'read' | 'write'
  access: 'read' | 'write' | null
}
export interface AppPermissions { document_revision: number; grants: AppGrant[] }

/** Invalid source drafts stay opaque and never enter the runtime. */
export function parseDocumentApp(source: string): DocumentApp | null {
  try {
    const app = JSON.parse(source) as DocumentApp
    if (!app || typeof app.id !== 'string' || !/^[a-z][a-z0-9_-]{0,39}$/.test(app.id) || typeof app.title !== 'string' || !app.title.trim()) return null
    if ([app.html, app.css, app.javascript].some(value => value !== undefined && typeof value !== 'string')) return null
    if (app.datasets !== undefined) {
      if (!app.datasets || typeof app.datasets !== 'object' || Array.isArray(app.datasets)) return null
      for (const [alias, binding] of Object.entries(app.datasets)) {
        if (!/^[a-z][a-z0-9_-]{0,39}$/.test(alias) || !binding || typeof binding.uri !== 'string' || !/^document:\/\/[0-9a-f-]{36}$/.test(binding.uri) || ![undefined, 'read', 'write'].includes(binding.access)) return null
      }
    }
    return app
  } catch { return null }
}
