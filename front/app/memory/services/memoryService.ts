import { api } from '@/core/api'
import { attachmentReference, browserResourceKind } from '@/core/util'
import { thumbnailReady } from '@/core/util/facade'
import type { GraphContext, GraphState, GraphStatePatch } from '../graphState'
import type { CatalogueResource, MemoryItem, MemoryItemCreate, MemoryItemDetail, MemoryItemUpdate, MemoryGraphCursor, MemoryFinding, MemoryGraphPage, MemoryGraphNode, MemoryFilterOptions, MemoryLink, MemoryNodeKind, MemoryRevision, MemoryRankedItem, MemoryRelationType, MemorySearchPage, MemorySortField } from '../types'
import { documentService } from '@/app/document'

export type MemoryDreamAction = 'describe' | 'read_document' | 'thumbnail' | 'findings' | 'structure'
export interface MemoryDreamActionResult { receipt_id: string; result_count: number }

export const memoryService = {
async readGraphState(context: GraphContext): Promise<GraphState> {
    return (await api.post<GraphState>('/memory/graph/state/read', context)).data
  },

async saveGraphState(context: GraphContext, patch: GraphStatePatch): Promise<GraphState> {
    return (await api.post<GraphState>('/memory/graph/state', { ...context, ...patch })).data
  },

async dreamActions(id: string, agentId: number): Promise<MemoryDreamAction[]> {
    const response = await api.get<{ actions: MemoryDreamAction[] }>(
      `/dream/memory/${encodeURIComponent(id)}/actions`, { params: { agent_id: agentId } },
    )
    return response.data.actions
  },

async runDreamAction(id: string, agentId: number, action: MemoryDreamAction, nodeKind?: MemoryNodeKind | 'conversation'): Promise<MemoryDreamActionResult> {
    const snapshot = action === 'thumbnail' && nodeKind === 'document'
      ? await documentService.documentThumbnailSnapshot(id, agentId, new AbortController().signal) : null
    const response = await api.post<MemoryDreamActionResult>(
      `/dream/memory/${encodeURIComponent(id)}/actions/${action}`, snapshot,
      { params: { agent_id: agentId }, timeout: 600_000 },
    )
    if (action === 'thumbnail' && response.data.result_count > 0) {
      const signal = new AbortController().signal
      try {
        if (nodeKind === 'document') await documentService.documentThumbnail(id, agentId, signal)
        else if (nodeKind === 'file') {
          const resource = (await this.fileResources(id, agentId, signal, 1))[0]
          const blob = resource ? await this.fileResourceThumbnail(id, resource.id, agentId, signal, true) : null
          if (blob?.size) thumbnailReady({ agentId, itemId: id, blob })
        } else if (nodeKind === 'attachment') {
          const item = await this.getItem(id, agentId)
          const uri = item.primary_url ?? item.metadata.resource_uri
          const reference = typeof uri === 'string' ? attachmentReference(uri) : null
          const blob = reference ? await documentService.documentAttachmentThumbnailBlob(reference[0], reference[1], agentId, signal, true) : null
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
    if (node.node_kind === 'document') return generate ? documentService.documentThumbnail(node.id, agentId, signal) : null
    if (node.node_kind === 'attachment') {
      const reference = attachmentReference(node.resource_uri ?? '')
      return reference ? documentService.documentAttachmentThumbnailBlob(reference[0], reference[1], agentId, signal, !generate) : null
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
    const params: { agent_id?: number; revision?: number } = {}
    if (agentId != null) params.agent_id = agentId
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
    orderBy?: 'activity' | 'hierarchy'
    deferResourceChildren?: boolean
    deferResourceFiles?: boolean
    cursor?: MemoryGraphCursor | null
    knownItemIds?: string[]
    includeMatchingRoots?: boolean
    includeSavedPositions?: boolean
    signal?: AbortSignal
  }): Promise<MemoryGraphPage> {
    const response = await api.post<MemoryGraphPage>('/memory/graph/roots', {
      agent_id: params.agentId,
      query: params.query ?? '',
      topic_item_id: params.topicItemId ?? null,
      contact_item_id: params.contactItemId ?? null,
      limit: params.limit ?? 60,
      edge_limit: params.edgeLimit ?? 300,
      order_by: params.orderBy ?? 'activity',
      defer_resource_children: params.deferResourceChildren ?? false,
      defer_resource_files: params.deferResourceFiles ?? false,
      cursor: params.cursor ?? null,
      known_item_ids: params.knownItemIds ?? [],
      include_matching_roots: params.includeMatchingRoots ?? false,
      include_saved_positions: params.includeSavedPositions ?? false,
    }, { signal: params.signal })
    return response.data
  },

async expandGraphNode(params: {
    agentId: number; itemId: string; query: string; topicItemId: string | null; contactItemId: string | null
    cursor?: MemoryGraphCursor | null; childrenOnly?: boolean; limit?: number; signal?: AbortSignal
  }): Promise<MemoryGraphPage> {
    return (await api.post<MemoryGraphPage>('/memory/graph/expand', {
      agent_id: params.agentId, item_id: params.itemId, query: params.query,
      topic_item_id: params.topicItemId, contact_item_id: params.contactItemId,
      limit: params.limit ?? 100, cursor: params.cursor ?? null, children_only: params.childrenOnly ?? false, include_saved_positions: true,
    }, { signal: params.signal })).data
  },

async createItem(data: MemoryItemCreate): Promise<MemoryItem> {
    const response = await api.post<MemoryItem>('/memory/items', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

async updateItem(id: string, agentId: number | null, data: MemoryItemUpdate): Promise<MemoryItem> {
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
  }
}
