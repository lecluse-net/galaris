import { api } from '@/core/api'

export type MemoryDreamAction = 'describe' | 'read_document' | 'thumbnail' | 'findings' | 'structure'
export interface MemoryDreamActionResult { receipt_id: string; result_count: number }
import { attachmentReference, browserResourceKind } from '@/core/util'
import { thumbnailReady } from '../thumbnailEvents'
import type { AppDatasetRequest, AppDatasetResult, AppGrant, AppPermissions } from '../documentApps'
import type {
  DocumentSharing, DocumentSharingUpdate,
  DocumentAttachment,
  CatalogueResource,
  DocumentCreate,
  DocumentContentDiff,
  DocumentContentRevisionDetail,
  DocumentContentRevisionPage,
  DocumentGlobalAccess,
  DocumentFolderOption,
  DocumentLibraryPage,
  DocumentLibraryFilters,
  DocumentTag,
  DocumentTagIcon,
  DocumentTagDeletionResult,
  DocumentOrderMove,
  DocumentOwnerKind,
  DocumentOwnerOptions,
  ManagedDocumentDetail,
  MemoryItem,
  MemoryItemCreate,
  MemoryItemDetail,
  MemoryItemUpdate,
  MemoryGraphCursor,
  MemoryFinding,
  MemoryGraphPage,
  MemoryGraphNode,
  MemoryFilterOptions,
  MemoryLink,
  MemoryNodeKind,
  MemoryRevision,
  MemoryRankedItem,
  MemoryRelationType,
  MemorySearchPage,
  MemorySortField,
} from '../types'

export const memoryService = {
  async dreamActions(id: string, agentId: number): Promise<MemoryDreamAction[]> {
    const response = await api.get<{ actions: MemoryDreamAction[] }>(
      `/dream/memory/${encodeURIComponent(id)}/actions`, { params: { agent_id: agentId } },
    )
    return response.data.actions
  },

  async runDreamAction(id: string, agentId: number, action: MemoryDreamAction, nodeKind?: MemoryNodeKind | 'conversation'): Promise<MemoryDreamActionResult> {
    const snapshot = action === 'thumbnail' && nodeKind === 'document'
      ? await this.documentThumbnailSnapshot(id, agentId, new AbortController().signal) : null
    const response = await api.post<MemoryDreamActionResult>(
      `/dream/memory/${encodeURIComponent(id)}/actions/${action}`, snapshot,
      { params: { agent_id: agentId }, timeout: 600_000 },
    )
    if (action === 'thumbnail' && response.data.result_count > 0) {
      const signal = new AbortController().signal
      try {
        if (nodeKind === 'document') await this.documentThumbnail(id, agentId, signal)
        else if (nodeKind === 'file') {
          const resource = (await this.fileResources(id, agentId, signal, 1))[0]
          const blob = resource ? await this.fileResourceThumbnail(id, resource.id, agentId, signal, true) : null
          if (blob?.size) thumbnailReady({ agentId, itemId: id, blob })
        } else if (nodeKind === 'attachment') {
          const item = await this.getItem(id, agentId)
          const uri = item.primary_url ?? item.metadata.resource_uri
          const reference = typeof uri === 'string' ? attachmentReference(uri) : null
          const blob = reference ? await this.documentAttachmentThumbnailBlob(reference[0], reference[1], agentId, signal, true) : null
          if (blob?.size) thumbnailReady({ agentId, itemId: id, resourceUri: typeof uri === 'string' ? uri : undefined, blob })
        }
      } catch {
        // The action already succeeded; a preview read can be retried on reopening.
      }
    }
    return response.data
  },

  async graphFileThumbnail(node: MemoryGraphNode, agentId: number, signal: AbortSignal, generate = false,
    resourceCache?: Map<string, CatalogueResource>): Promise<Blob | null> {
    if (node.node_kind === 'document') return generate ? this.documentThumbnail(node.id, agentId, signal) : null
    if (node.node_kind === 'attachment') {
      const reference = attachmentReference(node.resource_uri ?? '')
      return reference ? this.documentAttachmentThumbnailBlob(reference[0], reference[1], agentId, signal, !generate) : null
    }
    if (node.node_kind !== 'file') return null
    const resourceKey = `${node.id}:${node.updated_at ?? node.activity_at}`
    let resource = resourceCache?.get(resourceKey)
    if (!resource) {
      resource = (await this.fileResources(node.id, agentId, signal, 1))[0]
      if (resource && !signal.aborted && resourceCache) {
        if (resourceCache.size >= 3000) {
          const oldest = resourceCache.keys().next().value
          if (oldest !== undefined) resourceCache.delete(oldest)
        }
        resourceCache.set(resourceKey, resource)
      }
    }
    if (!resource || browserResourceKind(resource.media_type, resource.name) === 'audio') return null
    return this.fileResourceThumbnail(node.id, resource.id, agentId, signal, !generate)
  },
  async fileResources(itemId: string, agentId: number, signal?: AbortSignal, limit = 500): Promise<CatalogueResource[]> {
    return (await api.get<CatalogueResource[]>(`/file-share/items/${itemId}/resources`, { params: { agent_id: agentId, limit }, signal })).data
  },
  async fileResourceBlob(itemId: string, entryId: string, agentId: number, preview = true): Promise<Blob> {
    return (await api.get<Blob>(`/file-share/items/${itemId}/resources/${entryId}/content`, { params: { agent_id: agentId, preview }, responseType: 'blob' })).data
  },
  async fileResourceThumbnail(itemId: string, entryId: string, agentId: number, signal?: AbortSignal, cachedOnly = false): Promise<Blob> {
    const blob = (await api.get<Blob>(`/file-share/items/${itemId}/resources/${entryId}/thumbnail`, { params: { agent_id: agentId, cached_only: cachedOnly }, responseType: 'blob', signal })).data
    if (!cachedOnly && !signal?.aborted) thumbnailReady({ agentId, itemId, blob })
    return blob
  },
  async temporalDefaults(): Promise<{ timezone: string; lookahead_hours: number }> {
    return (await api.get<{ timezone: string; lookahead_hours: number }>('/memory/temporal/defaults')).data
  },
  async appPermissions(documentId: string, signal: AbortSignal): Promise<AppPermissions> {
    return (await api.get<AppPermissions>(`/memory/documents/${documentId}/app-permissions`, { signal })).data
  },
  async setAppPermission(documentId: string, revision: number, grant: AppGrant, access: AppGrant['access'], signal: AbortSignal): Promise<AppPermissions> {
    return (await api.put<AppPermissions>(`/memory/documents/${documentId}/app-permissions/${encodeURIComponent(grant.app_key)}/${encodeURIComponent(grant.alias)}`, {
      document_revision: revision, access,
    }, { signal })).data
  },
  async appDataset(documentId: string, revision: number, appId: string, alias: string, data: AppDatasetRequest, signal: AbortSignal): Promise<AppDatasetResult> {
    return (await api.post<AppDatasetResult>(`/memory/documents/${documentId}/apps/${encodeURIComponent(appId)}/datasets/${encodeURIComponent(alias)}`, {
      ...data, document_revision: revision,
    }, { signal })).data
  },
  async documentThumbnailSnapshot(id: string, agentId: number | null, signal: AbortSignal): Promise<{ html: string; revision: number; lock_version: number } | null> {
    const item = agentId === null
      ? (await api.get<ManagedDocumentDetail>(`/memory/documents/${id}`, { signal })).data.item
      : (await api.get<MemoryItemDetail>(`/memory/items/${id}`, { params: { agent_id: agentId }, signal })).data
    if (item.document_type === 'dataset') return null
    const { preparePortableDocumentSnapshot } = await import('@/core/util/facade')
    const html = await preparePortableDocumentSnapshot(item.payload.text ?? '', item.title, signal,
      (documentId, attachmentId) => memoryService.documentAttachmentBlob(documentId, attachmentId, agentId, signal))
    return { html, revision: item.revision, lock_version: item.lock_version }
  },
  async documentThumbnail(id: string, agentId: number | null, signal: AbortSignal): Promise<Blob | null> {
    const snapshot = await this.documentThumbnailSnapshot(id, agentId, signal)
    if (!snapshot) return null
    const response = await api.post<Blob>(`/memory/documents/${id}/thumbnail`, snapshot, {
      params: { agent_id: agentId }, responseType: 'blob', signal,
    })
    const blob = response.status === 200 && response.data.type === 'image/png' ? response.data : null
    if (blob && !signal.aborted) thumbnailReady({ agentId, itemId: id, blob })
    return blob
  },
  async itemSharing(id: string): Promise<DocumentSharing> { return (await api.get<DocumentSharing>(`/memory/items/${id}/sharing`)).data },
  async updateItemSharing(id: string, data: import('../types').DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/memory/items/${id}/sharing`, data)).data },
  async updateDocumentSharingLevel(id: string, data: import('../types').DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/memory/documents/${id}/sharing-level`, data)).data },
  async documentSharing(id: string): Promise<DocumentSharing> { return (await api.get<DocumentSharing>(`/memory/documents/${id}/sharing`)).data },
  async updateDocumentSharing(id: string, data: DocumentSharingUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/memory/documents/${id}/sharing`, data)).data },
  async createDocumentLinkCard(id: string, agentId: number | null, url: string): Promise<{ html: string; attachment: DocumentAttachment | null }> {
    const response = await api.post<{ html: string; attachment: DocumentAttachment | null }>(`/memory/documents/${id}/link-card`, { url }, { params: { actor_agent_id: agentId } })
    return response.data
  },
  async exportDocumentBundle(id: string, agentId: number | null, html: string, signal: AbortSignal): Promise<Blob> {
    const response = await api.post<Blob>(`/memory/documents/${id}/export-bundle`, { html }, { params: { agent_id: agentId }, responseType: 'blob', signal })
    return response.data
  },
  async exportDocumentPdf(id: string, html: string, signal: AbortSignal): Promise<Blob> {
    const response = await api.post<Blob>(`/memory/documents/${id}/export-pdf`, { html }, {
      responseType: 'blob', signal,
    })
    return response.data
  },

  async listDocumentTags(): Promise<{ user_id: number; tags: DocumentTag[] }> {
    return (await api.get<{ user_id: number; tags: DocumentTag[] }>('/memory/documents/tags')).data
  },
  async saveDocumentTag(data: { name: string; parent_id: string | null; icon?: string | null }, id?: string): Promise<DocumentTag> {
    return id
      ? (await api.put<DocumentTag>(`/memory/documents/tags/${id}`, data)).data
      : (await api.post<DocumentTag>('/memory/documents/tags', data)).data
  },
  async deleteDocumentTag(id: string, confirmed = false): Promise<DocumentTagDeletionResult> {
    return (await api.delete<DocumentTagDeletionResult>(`/memory/documents/tags/${id}`, { params: { confirmed } })).data
  },
  async assignDocumentTag(documentId: string, tagId: string, remove = false): Promise<void> {
    const url = `/memory/documents/${documentId}/tags/${tagId}`
    if (remove) await api.delete(url)
    else await api.put(url)
  },
  async moveDocumentToTag(documentId: string, tagId: string | null): Promise<void> {
    await api.put(`/memory/documents/${documentId}/tags`, { tag_id: tagId })
  },
  async reorderDocuments(data: DocumentOrderMove): Promise<void> {
    await api.put('/memory/documents/order', data)
  },
  async sortDocumentFolder(parentId: string | null, descending: boolean): Promise<void> {
    await api.put('/memory/documents/order/sort', { parent_id: parentId, descending })
  },
  async resolveDocumentIcons(documentIds: string[]): Promise<Record<string, string | null>> {
    return (await api.post<Record<string, string | null>>('/memory/documents/icons/resolve', { document_ids: documentIds })).data
  },
  async saveDocumentIcon(documentId: string, icon: string | null): Promise<{ icon: string | null }> {
    return (await api.put<{ icon: string | null }>(`/memory/documents/${documentId}/icon`, { icon })).data
  },
  async listDocumentTagIcons(): Promise<DocumentTagIcon[]> {
    return (await api.get<DocumentTagIcon[]>('/memory/documents/tag-icons')).data
  },
  async uploadDocumentTagIcon(name: string, data: string): Promise<DocumentTagIcon> {
    return (await api.post<DocumentTagIcon>('/memory/documents/tag-icons', { name, data })).data
  },
  async browseDocumentLibrary(params: DocumentLibraryFilters): Promise<DocumentLibraryPage> {
    const response = await api.post<DocumentLibraryPage>('/memory/documents/library', {
      ...params,
      query: params.query ?? '',
      keyword: params.keyword ?? null,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    })
    return response.data
  },

  async getManagedDocument(id: string): Promise<ManagedDocumentDetail> {
    const response = await api.get<ManagedDocumentDetail>(`/memory/documents/${id}`)
    return response.data
  },

  async listDocumentContentRevisions(id: string, limit = 50, offset = 0): Promise<DocumentContentRevisionPage> {
    const response = await api.get<DocumentContentRevisionPage>(
      `/memory/documents/${id}/content-revisions`,
      { params: { limit, offset } },
    )
    return response.data
  },

  async getDocumentContentRevision(
    id: string,
    revision: number,
  ): Promise<DocumentContentRevisionDetail> {
    const response = await api.get<DocumentContentRevisionDetail>(
      `/memory/documents/${id}/content-revisions/${revision}`,
    )
    return response.data
  },

  async diffDocumentContentRevision(
    id: string,
    revision: number,
  ): Promise<DocumentContentDiff> {
    const response = await api.get<DocumentContentDiff>(
      `/memory/documents/${id}/content-revisions/${revision}/diff`,
    )
    return response.data
  },

  async restoreDocumentContentRevision(
    id: string,
    revision: number,
    expectedRevision: number,
  ): Promise<MemoryItem> {
    const response = await api.post<MemoryItem>(
      `/memory/documents/${id}/content-revisions/${revision}/restore`,
      { expected_revision: expectedRevision },
    )
    return response.data
  },

  async listDocumentOwnerOptions(search = ''): Promise<DocumentOwnerOptions> {
    const response = await api.get<DocumentOwnerOptions>('/memory/documents/owner-options', {
      params: { search },
    })
    return response.data
  },

  async createDocument(data: DocumentCreate): Promise<MemoryItem> {
    const response = await api.post<MemoryItem>('/memory/documents', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

  async changeDocumentOwner(
    id: string,
    expectedRevision: number,
    expectedLockVersion: number,
    kind: DocumentOwnerKind,
    ownerId: number,
  ): Promise<MemoryItem> {
    const response = await api.patch<MemoryItem>(`/memory/documents/${id}/owner`, {
      expected_revision: expectedRevision,
      expected_lock_version: expectedLockVersion,
      kind,
      id: ownerId,
    })
    return response.data
  },

  async setDocumentGlobalAccess(
    id: string,
    expectedRevision: number,
    expectedLockVersion: number,
    globalAccess: DocumentGlobalAccess,
  ): Promise<MemoryItem> {
    const response = await api.patch<MemoryItem>(`/memory/documents/${id}/global-access`, {
      expected_revision: expectedRevision,
      expected_lock_version: expectedLockVersion,
      global_access: globalAccess,
    })
    return response.data
  },

  async moveDocument(id: string, expectedRevision: number, expectedLockVersion: number, folder: string): Promise<MemoryItem> {
    const response = await api.patch<MemoryItem>(`/memory/documents/${id}/folder`, {
      expected_revision: expectedRevision,
      expected_lock_version: expectedLockVersion,
      folder,
    })
    return response.data
  },

  async browse(params: {
    hybrid?: boolean
    temporal?: import('../types').MemoryTemporalFilter | null
    agentId: number
    query?: string
    keyword?: string | null
    limit?: number
    offset?: number
    nodeKinds?: MemoryNodeKind[]
    sortBy?: MemorySortField | null
    sortDescending?: boolean
    topicItemId?: string | null
    contactItemId?: string | null
  }): Promise<MemorySearchPage> {
    const response = await api.post<MemorySearchPage>('/memory/browse', {
      hybrid: params.hybrid ?? false,
      temporal: params.temporal ?? null,
      agent_id: params.agentId,
      query: params.query ?? '',
      keyword: params.keyword ?? null,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      node_kinds: params.nodeKinds ?? [],
      sort_by: params.sortBy ?? null,
      sort_desc: params.sortDescending ?? true,
      filter_topic_item_id: params.topicItemId ?? null,
      filter_contact_item_id: params.contactItemId ?? null,
    })
    return response.data
  },

  async listDocumentKeywords(agentId: number | null): Promise<string[]> {
    if (agentId === null) return []
    const response = await api.get<string[]>('/memory/documents/keywords', {
      params: { agent_id: agentId },
    })
    return response.data
  },

  async listDocumentFolders(agentId: number | null): Promise<string[]> {
    if (agentId === null) return []
    const response = await api.get<string[]>('/memory/documents/folders', {
      params: { agent_id: agentId },
    })
    return response.data
  },

  async listDocumentFolderOptions(agentId: number | null): Promise<DocumentFolderOption[]> {
    if (agentId === null) return []
    const response = await api.get<DocumentFolderOption[]>('/memory/documents/folders', {
      params: { agent_id: agentId, details: true },
    })
    return response.data
  },

  async listDocumentAttachments(id: string, agentId: number | null): Promise<DocumentAttachment[]> {
    const response = await api.get<DocumentAttachment[]>(`/memory/documents/${id}/attachments`, {
      params: { agent_id: agentId },
    })
    return response.data
  },

  async addDocumentAttachment(id: string, agentId: number | null, file: File, signal?: AbortSignal, progress?: (value: number) => void): Promise<DocumentAttachment> {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<DocumentAttachment>(
      `/memory/documents/${id}/attachments`,
      form,
      { params: { actor_agent_id: agentId }, signal, onUploadProgress: event => progress?.(event.total ? event.loaded / event.total : 0) },
    )
    return response.data
  },

  async importDocumentImage(id: string, agentId: number | null, url: string, signal: AbortSignal): Promise<DocumentAttachment> {
    const response = await api.post<DocumentAttachment>(`/memory/documents/${id}/import-image`, { url }, {
      params: { actor_agent_id: agentId }, signal,
    })
    return response.data
  },

  async documentAttachmentInfo(id: string, attachmentId: string, agentId: number | null): Promise<DocumentAttachment> {
    const response = await api.get<DocumentAttachment>(`/memory/documents/${id}/attachments/${attachmentId}/info`, { params: { agent_id: agentId } })
    return response.data
  },

  async documentAttachmentBlob(id: string, attachmentId: string, agentId: number | null, signal?: AbortSignal): Promise<Blob> {
    const response = await api.get<Blob>(
      `/memory/documents/${id}/attachments/${attachmentId}`,
      { params: { agent_id: agentId }, responseType: 'blob', signal },
    )
    return response.data
  },

  async documentAttachmentThumbnailBlob(id: string, attachmentId: string, agentId: number | null, signal?: AbortSignal, cachedOnly = false): Promise<Blob> {
    const response = await api.get<Blob>(
      `/memory/documents/${id}/attachments/${attachmentId}/thumbnail`,
      { params: { agent_id: agentId, cached_only: cachedOnly }, responseType: 'blob', signal },
    )
    if (!cachedOnly && !signal?.aborted) thumbnailReady({ agentId,
      resourceUri: `document://${id}/attachments/${attachmentId}`, blob: response.data })
    return response.data
  },

  async deleteDocumentAttachment(id: string, attachmentId: string, agentId: number | null): Promise<void> {
    await api.delete(`/memory/documents/${id}/attachments/${attachmentId}`, {
      params: { actor_agent_id: agentId },
    })
  },

  async listFilterOptions(agentId: number): Promise<MemoryFilterOptions> {
    const response = await api.get<MemoryFilterOptions>('/memory/filter-options', {
      params: { agent_id: agentId },
    })
    return response.data
  },

  async search(params: {
    agentId: number
    query: string
    semanticQuery?: string
    limit?: number
    nodeKinds?: MemoryNodeKind[]
    excludeSourceManaged?: boolean
  }): Promise<MemoryRankedItem[]> {
    const payload: Record<string, unknown> = {
      agent_id: params.agentId,
      query: params.query,
    }
    if (params.semanticQuery !== undefined) payload.semantic_query = params.semanticQuery
    if (params.limit !== undefined) payload.limit = params.limit
    if (params.nodeKinds !== undefined) payload.node_kinds = params.nodeKinds
    if (params.excludeSourceManaged !== undefined) {
      payload.exclude_source_managed = params.excludeSourceManaged
    }
    const response = await api.post<MemoryRankedItem[]>('/memory/search', payload)
    return response.data
  },

  async getItem(id: string, agentId?: number | null, revision?: number): Promise<MemoryItemDetail> {
    if (agentId === null) return (await memoryService.getManagedDocument(id)).item
    const params: { agent_id?: number; revision?: number } = {}
    if (agentId !== undefined) params.agent_id = agentId
    if (revision !== undefined) params.revision = revision
    const response = await api.get<MemoryItemDetail>(`/memory/items/${id}`, {
      params,
    })
    return response.data
  },

  async listFindings(agentId: number, itemId?: string): Promise<MemoryFinding[]> {
    const response = await api.get<MemoryFinding[]>('/memory/findings', {
      params: {
        agent_id: agentId,
        item_id: itemId,
        finding_status: 'pending',
        limit: 500,
      },
    })
    return response.data
  },

  async applyFinding(id: string, canonicalItemId?: string): Promise<MemoryFinding> {
    const response = await api.post<MemoryFinding>(`/memory/findings/${id}/apply`, {
      canonical_item_id: canonicalItemId ?? null,
    })
    return response.data
  },

  async dismissFinding(id: string): Promise<MemoryFinding> {
    const response = await api.post<MemoryFinding>(`/memory/findings/${id}/dismiss`)
    return response.data
  },

  async listGraphRoots(params: {
    agentId: number
    query?: string
    topicItemId?: string | null
    contactItemId?: string | null
    limit?: number
    edgeLimit?: number
    cursor?: MemoryGraphCursor | null
    knownItemIds?: string[]
  }): Promise<MemoryGraphPage> {
    const response = await api.post<MemoryGraphPage>('/memory/graph/roots', {
      agent_id: params.agentId,
      query: params.query ?? '',
      topic_item_id: params.topicItemId ?? null,
      contact_item_id: params.contactItemId ?? null,
      limit: params.limit ?? 60,
      edge_limit: params.edgeLimit ?? 300,
      cursor: params.cursor ?? null,
      known_item_ids: params.knownItemIds ?? [],
    })
    return response.data
  },

  async createItem(data: MemoryItemCreate): Promise<MemoryItem> {
    const response = await api.post<MemoryItem>('/memory/items', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

  async updateItem(id: string, agentId: number | null, data: MemoryItemUpdate): Promise<MemoryItem> {
    if (agentId === null) return (await api.patch<MemoryItem>(`/memory/documents/${id}`, data, { headers: { 'X-Editorial-Profile-Version': '1' } })).data
    const response = await api.put<MemoryItem>(`/memory/items/${id}`, data, {
      headers: { 'X-Editorial-Profile-Version': '1' },
      params: { actor_agent_id: agentId },
    })
    return response.data
  },

  async forgetItem(id: string, agentId: number | null): Promise<void> {
    await api.delete(`/memory/items/${id}`, { params: { actor_agent_id: agentId } })
  },

  async listRevisions(id: string, agentId: number, limit = 50, offset = 0): Promise<MemoryRevision[]> {
    const response = await api.get<MemoryRevision[]>(`/memory/items/${id}/revisions`, {
      params: { agent_id: agentId, limit, offset },
    })
    return response.data
  },

  async setItemGrant(id: string, agentId: number, canWrite: boolean): Promise<MemoryItem> {
    const response = await api.put<MemoryItem>(
      `/memory/items/${id}/grants/${agentId}`,
      { can_write: canWrite },
    )
    return response.data
  },

  async removeItemGrant(id: string, agentId: number): Promise<MemoryItem> {
    const response = await api.delete<MemoryItem>(`/memory/items/${id}/grants/${agentId}`)
    return response.data
  },

  async setDocumentGrant(
    id: string,
    ownerAgentId: number,
    targetAgentId: number,
    canWrite: boolean,
  ): Promise<MemoryItem> {
    const response = await api.put<MemoryItem>(
      `/memory/documents/${id}/grants/${targetAgentId}`,
      { can_write: canWrite },
      { params: { owner_agent_id: ownerAgentId } },
    )
    return response.data
  },

  async removeDocumentGrant(
    id: string,
    ownerAgentId: number,
    targetAgentId: number,
  ): Promise<MemoryItem> {
    const response = await api.delete<MemoryItem>(
      `/memory/documents/${id}/grants/${targetAgentId}`,
      { params: { owner_agent_id: ownerAgentId } },
    )
    return response.data
  },

  async setManagedDocumentGrant(
    id: string,
    targetAgentId: number,
    canWrite: boolean,
    expectedLockVersion: number,
  ): Promise<MemoryItem> {
    const response = await api.put<MemoryItem>(
      `/memory/documents/${id}/collaborators/${targetAgentId}`,
      { can_write: canWrite, expected_lock_version: expectedLockVersion },
    )
    return response.data
  },

  async removeManagedDocumentGrant(
    id: string,
    targetAgentId: number,
    expectedLockVersion: number,
  ): Promise<MemoryItem> {
    const response = await api.delete<MemoryItem>(
      `/memory/documents/${id}/collaborators/${targetAgentId}`,
      { params: { expected_lock_version: expectedLockVersion } },
    )
    return response.data
  },

  async listLinks(id: string, agentId: number): Promise<MemoryLink[]> {
    const response = await api.get<MemoryLink[]>(`/memory/items/${id}/links`, {
      params: { actor_agent_id: agentId },
    })
    return response.data
  },

  async createLink(data: {
    source_item_id: string
    target_item_id: string
    relation_type: MemoryRelationType
  }, agentId: number): Promise<MemoryLink> {
    const response = await api.post<MemoryLink>('/memory/links', data, {
      params: { actor_agent_id: agentId },
    })
    return response.data
  },
}
