import type { DocumentLibraryFilters, DocumentOwnerKind, DocumentType } from './types'
export interface LibraryFilterState {
  document_type: DocumentType | null
  keyword: string | null
  owner_kind: DocumentOwnerKind | null
  owner: number | null
  created_from: string
  created_until: string
  updated_from: string
  updated_until: string
  sort_by: 'position' | 'title' | 'created_at' | 'updated_at' | 'document_type'
  sort_desc: boolean
}
export function defaultLibraryFilters(): LibraryFilterState {
  return { document_type: null, keyword: null, owner_kind: null, owner: null, created_from: '', created_until: '', updated_from: '', updated_until: '', sort_by: 'position', sort_desc: false }
}
export function libraryRequestFilters(filters: LibraryFilterState): DocumentLibraryFilters {
  function boundary(value: string, exclusive: boolean): string | null {
    if (!value) return null
    const date = new Date(`${value}T00:00:00`)
    if (exclusive) date.setDate(date.getDate() + 1)
    return date.toISOString()
  }
  return { ...filters, created_from: boundary(filters.created_from, false), created_until: boundary(filters.created_until, true), updated_from: boundary(filters.updated_from, false), updated_until: boundary(filters.updated_until, true) }
}
