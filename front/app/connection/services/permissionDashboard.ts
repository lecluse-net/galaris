import type { Component } from 'vue'

export type PermissionState = 'all' | 'allowed' | 'denied' | 'ask' | 'pending'
export type PermissionCounts = Partial<Record<Exclude<PermissionState, 'all'>, number>>
export interface PermissionQuery {
  agentId: number
  search: string
  state: PermissionState
  offset: number
  limit: number
  signal: AbortSignal
  toolId?: number | null
  customizedOnly?: boolean
}
export interface PermissionControl {
  id: string
  label: string
  hint?: string
  value: string
  options: { value: string; label: string; disable?: boolean }[]
  disabled?: boolean
  save: (value: string) => Promise<unknown>
}
export interface PermissionEntry {
  id: string
  toolId?: number
  title: string
  description?: string
  scope?: string
  state: Exclude<PermissionState, 'all'>
  origin?: string
  note?: string
  controls: PermissionControl[]
  customized?: boolean
  children?: PermissionEntry[]
}
export interface PermissionPage {
  items: PermissionEntry[]
  total: number
  counts: PermissionCounts
  customizedCount?: number
  warnings?: string[]
  tools?: { value: number; label: string }[]
}
export interface PermissionPanelDefinition {
  id: string
  title: string
  icon: string
  order: number
  privileges: string[]
  filterTools?: boolean
  groupTools?: boolean
  component?: Component
  componentProps?: Record<string, unknown>
  load?: (query: PermissionQuery) => Promise<PermissionPage>
}

export interface PermissionPagination { page: number; rowsPerPage: number; rowsNumber?: number }

export function filterPermissionEntries(items: PermissionEntry[], query: PermissionQuery): PermissionPage {
  const needle = query.search.trim().toLocaleLowerCase()
  const matching = items.filter(row => (query.toolId == null || row.toolId === query.toolId)
    && (!needle || [row.title, row.description, row.scope, row.origin, row.note]
      .some(value => value?.toLocaleLowerCase().includes(needle))))
  const customizedCount = matching.filter(row => row.customized === true).length
  const visible = query.customizedOnly ? matching.filter(row => row.customized === true) : matching
  const counts: PermissionCounts = {}
  for (const row of visible) counts[row.state] = (counts[row.state] ?? 0) + 1
  const filtered = visible.filter(row => query.state === 'all' || row.state === query.state)
  return { items: filtered.slice(query.offset, query.offset + query.limit), total: filtered.length, counts, customizedCount }
}
