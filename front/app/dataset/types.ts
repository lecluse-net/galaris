import type { Collaborator, SharingState } from '@/app/share'
export const valueTypes = ['int', 'float', 'string', 'bool', 'Agent', 'File', 'User', 'Document', 'Dataset', 'array', 'object'] as const
export type ValueType = typeof valueTypes[number]
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }
export type TypedValue = { type: ValueType; value: JsonValue }
export interface Variable { name: string; type: ValueType; nullable: boolean; default?: TypedValue }
export interface Dataset {
  id: string; uri: string; title: string; revision: number; lock_version: number; content: string
  can_write: boolean; can_manage: boolean; can_delete: boolean; read_only: boolean
  global_access: number; group_access: number; keywords: string[]
  owner_agent_id: number | null; owner_user_id: number | null
  created_at: string | null; updated_at: string | null
}
export interface DatasetOwnerOptions { owner: Collaborator | null; options: Collaborator[] }
export interface Page<T> { items: T[]; total: number }
export type DatasetSharing = SharingState
export type UsageKind = 'documents' | 'processes' | 'agents'
export interface DatasetUsage { id: string; label: string; relation: 'document_reference' | 'process_definition' | 'process_run' | 'agent_trace'; url: string; uri?: string; last_used_at: string | null }
