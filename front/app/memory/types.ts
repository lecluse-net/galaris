import type { DocumentAttachment, DocumentType } from '@/app/document/types'

export type MemoryNodeKind = 'memory' | 'document' | 'attachment' | 'folder' | 'file' | 'directory'

export type MemoryGraphEntityKind = MemoryNodeKind | 'topic' | 'contact' | 'conversation'

export type MemoryVisibility = 'private' | 'shared' | 'public'

export type MemoryRetrievalMode = 'lexical' | 'hybrid'

export type MemorySearchDegradationReason =
  | 'embedding_not_configured'
  | 'embedding_unavailable'
  | 'semantic_index_unavailable'
  | 'embedding_index_empty'
  | 'embedding_dimension_not_indexed'
  | 'semantic_search_failed'

export type MemorySortField =
  | 'title'
  | 'visibility'
  | 'owner'
  | 'access_count'
  | 'last_accessed_at'
  | 'updated_at'

export type ContactIdentityKind = 'messenger' | 'galaris_user'

export interface ContactIdentity {
  id: string
  kind: ContactIdentityKind
  namespace: string
  external_id: string
  display_name: string
  galaris_user_id: number | null
}

export interface Contact {
  memory_item_id: string
  owner_agent_id: number
  display_name: string
  memory_title: string
  identities: ContactIdentity[]
  linked_memory_count: number
  created_at: string
  updated_at: string | null
}

export interface ContactCreate {
  agent_id: number
  display_name: string
  email: string
}

export interface ContactUpdate {
  display_name: string
  split_identity_ids?: string[]
  expected_identity_ids?: string[]
}

export interface ContactPage {
  items: Contact[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface ContactMergeResult {
  contact: Contact
  rewired: Record<string, number>
}

export interface ContactForgetResult {
  forgotten_contact_item_id: string
  forgotten_memories: number
  resources_deleted: number
  cleared: Record<string, number>
}

export interface MemoryPayload {
  text?: string | null
  base64?: string | null
}

export interface MemoryAccess {
  can_read: boolean
  can_write: boolean
}

export interface CatalogueResource extends DocumentAttachment {
  uri: string
}

export interface MemoryItem {
  topic_id?: string | null
  document_id?: string | null
  document_revision?: number | null
  summary_document_revision?: number | null
  summary_outdated?: boolean
  file_sha256?: string | null
  file_media_type?: string | null
  file_size_bytes?: number | null
  primary_url?: string | null
  urls?: string[]
  temporal?: MemoryTemporalAnchor | null
  document_type: DocumentType
  content_profile?: 'rich-text' | 'document'
  content_profile_version?: number | null
  id: string
  revision: number
  lock_version: number
  owner_agent_id: number | null
  owner_user_id: number | null
  provider_code: string
  title: string
  node_kind: MemoryNodeKind
  content_type: string
  media_type: string
  filename: string | null
  keywords: string[]
  metadata: Record<string, unknown>
  visibility: MemoryVisibility
  read_only: boolean
  deletion_protected: boolean
  source_managed: boolean
  managed_source_kind: string | null
  managed_source_ref: string | null
  content_hash: string
  size_bytes: number
  last_accessed_at: string | null
  access_count: number
  valid_from: string | null
  valid_until: string | null
  old_at: string | null
  old_reason: string | null
  created_at: string
  updated_at: string | null
  access: MemoryAccess
}

export interface MemoryItemDetail extends MemoryItem {
  payload: MemoryPayload
  source_refs: string[]
}

export interface ManagedDocumentDetail {
  item: MemoryItemDetail
  agent_id: number | null
}

export interface MemoryItemCreate {
  temporal?: MemoryTemporalAnchor | null
  document_type?: DocumentType
  owner_agent_id: number
  title?: string
  payload: MemoryPayload
  node_kind?: MemoryNodeKind
  content_type?: string
  media_type?: string
  filename?: string | null
  keywords?: string[]
  metadata?: Record<string, unknown>
  visibility?: MemoryVisibility
  read_only?: boolean
}

export interface MemoryItemUpdate {
  temporal?: MemoryTemporalAnchor | null
  expected_revision?: number
  expected_lock_version?: number
  title?: string
  payload?: MemoryPayload
  content_type?: string
  media_type?: string
  filename?: string | null
  keywords?: string[]
  metadata?: Record<string, unknown>
  visibility?: MemoryVisibility
  read_only?: boolean
}

export interface MemorySearchHit {
  temporal_match_at?: string | null
  item: MemoryItem
  excerpt: string
  score: number
  source_refs: string[]
}

export interface MemoryTemporalAnchor {
  year?: number | null
  month?: number | null
  day?: number | null
  weekday?: number | null
  hour?: number | null
  minute?: number | null
}

export interface MemorySearchPage {
  recall_truncated?: boolean
  degradation_reason?: string | null
  temporal_window?: MemoryTemporalWindow | null
  query: string
  hits: MemorySearchHit[]
  total: number
  has_more: boolean
}

export interface MemoryTemporalFilter {
  target_at: string | null
  lookahead_hours: number | null
}

export interface MemoryTemporalWindow {
  start: string
  end: string
  timezone: string
}

export interface MemoryRankedItem {
  id: string
  title: string
  excerpt: string
  node_kind: MemoryNodeKind
  source_refs: string[]
}

export interface MemoryFilterOption {
  id: string
  label: string
}

export interface MemoryFilterOptions {
  topics: MemoryFilterOption[]
  contacts: MemoryFilterOption[]
}

export interface MemoryGraphCursor {
  activity_at: string
  id: string
  role_rank?: number | null
}

export interface MemoryGraphNode {
  resource_media_type?: string | null
  resource_uri?: string | null
  id: string
  node_kind: MemoryNodeKind | 'conversation'
  entity_kind: MemoryGraphEntityKind
  owner_agent_id: number | null
  title: string
  visibility: MemoryVisibility
  source_managed: boolean
  access_count: number
  last_accessed_at: string | null
  created_at: string
  updated_at: string | null
  activity_at: string
  has_relations: boolean
  relation_count: number
  children_count?: number
}

export interface MemoryGraphEdge {
  id: string
  source_item_id: string
  target_item_id: string
  relation_type: string
  confidence: number
  suggested: boolean
}

export interface MemoryGraphRelation {
  edge: MemoryGraphEdge
  other: MemoryGraphNode
}

export interface MemoryGraphPage {
  positions?: Record<string, [number, number]>
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  next_cursor: MemoryGraphCursor | null
  has_more: boolean
  edges_truncated: boolean
}

export interface MemoryRevision {
  revision: number
  task_id: string | null
  content_hash: string
  title: string
  keywords: string[]
  author_agent_id: number | null
  created_at: string
}

export interface MemoryLink {
  id: string
  source_item_id: string
  target_item_id: string
  relation_type: string
  confidence: number
  suggested: boolean
  created_by_agent_id: number | null
  metadata: Record<string, unknown>
  created_at: string
}

export type MemoryRelationType =
  | 'related_to'
  | 'supports'
  | 'contradicts'
  | 'depends_on'
  | 'precedes'
  | 'supersedes'

export type MemoryFindingKind = 'duplicate' | 'contradiction' | 'aging'

export type MemoryFindingStatus = 'pending' | 'applied' | 'dismissed' | 'obsolete' | 'error'

export interface MemoryFinding {
  id: string
  kind: MemoryFindingKind
  primary_item_id: string
  related_item_id: string | null
  primary_revision: number
  related_revision: number | null
  score: number | null
  threshold: number
  proposed_action: string
  status: MemoryFindingStatus
  details: Record<string, unknown>
  detected_at: string
  resolved_at: string | null
}

export type {
  Collaborator as DocumentCollaborator, SharingState as DocumentSharing,
  SharingUpdate as DocumentSharingLevelUpdate, SingleGrantUpdate as DocumentSharingUpdate,
} from '@/app/share'
