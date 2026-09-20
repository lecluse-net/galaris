export type MemoryType = 'core' | 'working' | 'episodic' | 'semantic' | 'procedural' | 'social'
export type MemoryNodeKind = 'memory' | 'document' | 'attachment' | 'folder'
export type MemoryGraphEntityKind = 'memory' | 'document' | 'attachment' | 'folder' | 'topic' | 'contact' | 'conversation'
export type MemoryVisibility = 'private' | 'shared' | 'public'
export type DocumentGlobalAccess = 0 | 1 | 2
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
  | 'memory_type'
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

export interface MemoryGrant {
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

export type DocumentType = 'html' | 'dataset'

export interface MemoryItem {
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
  memory_type: MemoryType
  node_kind: MemoryNodeKind
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
  access: MemoryAccess
  grants: MemoryGrant[]
}

export interface MemoryItemDetail extends MemoryItem {
  payload: MemoryPayload
  source_refs: string[]
}

export interface DocumentLibraryEntry {
  position?: number
  tags?: DocumentTag[]
  owner_label?: string
  user_access?: { can_read: boolean; can_write: boolean }
  item: MemoryItem
  agent_ids: number[]
  writable_agent_ids: number[]
}

export interface DocumentFolderOption {
  path: string
  kind: 'custom' | 'goal'
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
  list_only?: boolean
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
  include_descendants?: boolean
  include_owners?: boolean
  classification?: 'all' | 'classified' | 'unclassified'
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
  item: MemoryItemDetail
  agent_id: number | null
}

export type DocumentOwnerKind = 'agent' | 'user'

export interface DocumentOwnerOption {
  kind: DocumentOwnerKind
  id: number
  label: string
  subtitle: string
  avatar_url: string | null
  is_current_user: boolean
}

export interface DocumentOwnerOptions {
  agents: DocumentOwnerOption[]
  users: DocumentOwnerOption[]
}

export interface DocumentCreate {
  document_type?: DocumentType
  owner_kind: DocumentOwnerKind
  owner_id: number
  actor_agent_id: number
  title: string
  folder?: string
}

export interface MemoryItemCreate {
  document_type?: DocumentType
  owner_agent_id: number
  title: string
  payload: MemoryPayload
  memory_type?: MemoryType
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
  expected_revision?: number
  expected_lock_version?: number
  title?: string
  payload?: MemoryPayload
  memory_type?: MemoryType
  content_type?: string
  media_type?: string
  filename?: string | null
  keywords?: string[]
  metadata?: Record<string, unknown>
  visibility?: MemoryVisibility
  read_only?: boolean
}

export interface MemorySearchHit {
  item: MemoryItem
  excerpt: string
  score: number
  source_refs: string[]
}

export interface MemorySearchPage {
  query: string
  hits: MemorySearchHit[]
  total: number
  has_more: boolean
}

export interface MemoryRankedItem {
  id: string
  title: string
  excerpt: string
  memory_type: MemoryType
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
}

export interface MemoryGraphNode {
  resource_media_type?: string | null
  id: string
  node_kind: MemoryNodeKind | 'conversation'
  entity_kind: MemoryGraphEntityKind
  owner_agent_id: number | null
  title: string
  memory_type: MemoryType
  visibility: MemoryVisibility
  source_managed: boolean
  access_count: number
  last_accessed_at: string | null
  created_at: string
  updated_at: string | null
  activity_at: string
  has_relations: boolean
  relation_count: number
}

export interface MemoryGraphEdge {
  id: string
  source_item_id: string
  target_item_id: string
  relation_type: string
  confidence: number
  suggested: boolean
}

export interface MemoryGraphPage {
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

export interface DocumentContentRevision {
  media_type?: string
  content_profile_version?: number | null
  revision: number
  task_id: string | null
  content_hash: string
  author_agent_id: number | null
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

export interface DocumentCollaborator { kind: 'agent' | 'user' | 'team'; id: number; label: string; can_write: boolean; group_ids?: number[]; avatar_url?: string | null; has_avatar?: boolean }
export interface DocumentSharing { lock_version: number; can_manage: boolean; grants: DocumentCollaborator[]; options: DocumentCollaborator[]; level: DocumentSharingLevel; can_write: boolean; owner: DocumentCollaborator | null; owner_groups: DocumentCollaborator[] }
export interface DocumentSharingUpdate { kind: DocumentCollaborator['kind']; id: number; can_write: boolean | null; expected_lock_version: number }

export type DocumentSharingLevel = 'private' | 'groups' | 'public'
export interface DocumentSharingLevelUpdate { level: DocumentSharingLevel; can_write: boolean; grants: Pick<DocumentCollaborator, 'kind' | 'id' | 'can_write'>[]; expected_lock_version: number }
