import type { Component } from 'vue'

export interface WorkingDocumentSnapshot {
  id: string
  title: string
  media_type?: string
  content_profile?: 'rich-text' | 'document'
  content_profile_version?: number | null
  revision: number
  updated_at: string | null
  payload: { text?: string | null }
}

export interface WorkingDocumentEditorContribution {
  component: Component
  iconComponent?: Component
  thumbnailComponent?: Component
  search: (query: string, limit: number, offset: number) => Promise<WorkingDocumentSearchPage>
}

export interface WorkingDocumentReference { id: string; title: string }
export interface WorkingDocumentSearchPage { items: WorkingDocumentReference[]; total: number }

interface WorkingDocumentEditorModule {
  default: WorkingDocumentEditorContribution
}

const modules = import.meta.glob<WorkingDocumentEditorModule>(
  '../../app/*/documentEditor.ts',
  { eager: true },
)

export const workingDocumentEditor = Object.values(modules)
  .map(module => module.default.component)
  .find(Boolean)

export const workingDocumentIcon = Object.values(modules)
  .map(module => module.default.iconComponent)
  .find(Boolean)

export const workingDocumentThumbnail = Object.values(modules)
  .map(module => module.default.thumbnailComponent)
  .find(Boolean)

export async function searchWorkingDocuments(query: string, limit = 50, offset = 0): Promise<WorkingDocumentSearchPage> {
  const provider = Object.values(modules)[0]?.default
  if (!provider) throw new Error('Document provider unavailable')
  return provider.search(query, limit, offset)
}
