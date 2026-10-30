export type DocumentNodeKind = 'document'

export type MemoryVisibility = 'private' | 'shared' | 'public'

export type DocumentGlobalAccess = 0 | 1 | 2

export interface DocumentPayload {
  text?: string | null
  base64?: string | null
}

export interface DocumentAccess {
  can_read: boolean
  can_write: boolean
}

export interface DocumentGrant {
  agent_id: number
  can_write: boolean
}

export interface DocumentAttachment {
  id: string
  memory_item_id?: string | null
  name: string
  media_type: string
  size_bytes: number
  created_at: string
}

export type DocumentType = 'text' | 'data' | 'html' | 'dataset' | 'process'

export interface DocumentRecord {
  topic_id?: string | null
  document_id?: string | null
  document_revision?: number | null
  summary_outdated?: boolean
  file_sha256?: string | null
  file_media_type?: string | null
  file_size_bytes?: number | null
  primary_url?: string | null
  urls?: string[]
  temporal?: DocumentTemporalAnchor | null
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
  node_kind: DocumentNodeKind
  content_type: string
  media_type: string
  filename: string | null
  keywords: string[]
  metadata: Record<string, unknown>
  visibility: MemoryVisibility
  global_access: DocumentGlobalAccess
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
  access: DocumentAccess
  grants: DocumentGrant[]
}

export interface DocumentDetail extends DocumentRecord {
  payload: DocumentPayload
  source_refs: string[]
}

export interface DocumentLibraryEntry {
  parent_document_id?: string | null
  children_count?: number
  position?: number
  tags?: DocumentTag[]
  owner_label?: string
  user_access?: { can_read: boolean; can_write: boolean }
  item: DocumentRecord
  agent_ids: number[]
  writable_agent_ids: number[]
}

export interface DocumentFolderOption {
  path: string
  kind: 'custom'
  shared: boolean
}

export interface DocumentLibraryPage {
  owners?: DocumentOwnerOption[]
  query: string
  entries: DocumentLibraryEntry[]
  total: number
  keywords: string[]
  has_more: boolean
}

export interface DocumentTag {
  memory_item_id?: string | null
  position?: number
  id: string
  name: string
  parent_id: string | null
  icon?: string | null
}

export interface DocumentTagIcon { id: string; name: string; data: string }

export interface DocumentTagDeletionResult { deleted: boolean; tag_count: number; document_count: number }

export interface DocumentOrderNode { kind: 'tag' | 'document'; id: string }

export interface DocumentOrderMove {
  node: DocumentOrderNode
  parent_id: string | null
  parent_document_id?: string | null
  list_only?: boolean
  at_root?: boolean
  anchor?: DocumentOrderNode
  after?: boolean
}

export interface DocumentLibraryFilters {
  document_type?: DocumentType | null
  query?: string
  keyword?: string | null
  limit?: number
  offset?: number
  tag_id?: string | null
  parent_document_id?: string | null
  include_descendants?: boolean
  include_owners?: boolean
  include_keywords?: boolean
  classification?: 'all' | 'classified' | 'unclassified' | 'root'
  owner_kind?: DocumentOwnerKind | null
  owner?: number | null
  created_from?: string | null
  created_until?: string | null
  updated_from?: string | null
  updated_until?: string | null
  sort_by?: 'position' | 'title' | 'created_at' | 'updated_at' | 'document_type'
  sort_desc?: boolean
}

export interface ManagedDocumentDetail {
  item: DocumentDetail
  agent_id: number | null
}

export interface DocumentResourceRedirect {
  resource_type: 'dataset'
  resource_uri: string
}

export interface DocumentDatasetAttachment {
  uri: string
  title: string | null
  available: boolean
}

export interface DocumentProcessAttachments {
  items: { uri: string; title: string | null; kind?: 'process' | 'process_run'; available: boolean }[]
  lock_version: number
}

export interface DocumentDatasetAttachments {
  items: DocumentDatasetAttachment[]
  lock_version: number
}

export type DocumentOwnerKind = 'agent' | 'user'

export interface DocumentOwnerOption {
  kind: DocumentOwnerKind
  id: number
  label: string
  subtitle: string
  avatar_url: string | null
  has_avatar?: boolean
  is_current_user: boolean
}

export interface DocumentOwnerOptions {
  agents: DocumentOwnerOption[]
  users: DocumentOwnerOption[]
}

export interface DocumentCreate {
  import_from?: { uri: string; agent_id: number }
  document_type?: 'text' | 'data' | 'html'
  owner_kind: DocumentOwnerKind
  owner_id: number
  actor_agent_id: number | null
  title: string
  folder?: string
}

export interface DocumentUpdate {
  temporal?: DocumentTemporalAnchor | null
  expected_revision?: number
  expected_lock_version?: number
  title?: string
  payload?: DocumentPayload
  content_type?: string
  media_type?: string
  filename?: string | null
  keywords?: string[]
  metadata?: Record<string, unknown>
  visibility?: MemoryVisibility
  read_only?: boolean
}

export interface DocumentTemporalAnchor {
  year?: number | null
  month?: number | null
  day?: number | null
  weekday?: number | null
  hour?: number | null
  minute?: number | null
}

export interface DocumentContentRevision {
  media_type?: string
  content_profile_version?: number | null
  revision: number
  task_id: string | null
  content_hash: string
  author_agent_id: number | null
  author_user_id?: number | null
  created_at: string
}

export interface DocumentContentRevisionDetail extends DocumentContentRevision {
  content: string
}

export interface DocumentContentRevisionPage {
  items: DocumentContentRevision[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export type DocumentContentDiffLineKind = 'context' | 'added' | 'removed'

export interface DocumentContentDiffLine {
  kind: DocumentContentDiffLineKind
  text: string
  old_line: number | null
  new_line: number | null
}

export interface DocumentContentDiffHunk {
  old_start: number
  old_count: number
  new_start: number
  new_count: number
  lines: DocumentContentDiffLine[]
}

export interface DocumentContentDiff {
  structure_changed?: boolean
  previous_html?: string | null
  current_html?: string | null
  revision: number
  current_revision: number
  additions: number
  deletions: number
  hunks: DocumentContentDiffHunk[]
}

export type DocumentSharingLevel = 'private' | 'groups' | 'public'
export type { Collaborator as DocumentCollaborator, SharingState as DocumentSharing, SharingUpdate as DocumentSharingLevelUpdate, SingleGrantUpdate as DocumentSharingUpdate } from '@/app/share'
