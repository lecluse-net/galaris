import { api } from '@/core/api'
import { createOwnerOptionsCache } from '@/app/share/facade'
import { thumbnailReady } from '@/core/util/facade'
import type { AppDatasetRequest, AppDatasetResult } from '../documentApps'
import type { DocumentSharing, DocumentSharingUpdate, DocumentAttachment, DocumentCreate, DocumentContentDiff, DocumentContentRevisionDetail, DocumentContentRevisionPage, DocumentGlobalAccess, DocumentFolderOption, DocumentLibraryPage, DocumentLibraryFilters, DocumentTag, DocumentTagIcon, DocumentTagDeletionResult, DocumentOrderMove, DocumentOwnerKind, DocumentOwnerOptions, ManagedDocumentDetail, DocumentResourceRedirect, DocumentDatasetAttachments, DocumentProcessAttachments, DocumentRecord, DocumentDetail, DocumentUpdate } from '../types'

export class DatasetDocumentRedirect extends Error {
  constructor(readonly uri: string) { super('This resource is a Dataset.') }
  get href(): string { return `/dataset/${encodeURIComponent(this.uri.slice('data://'.length))}` }
}

function editorialDocument(detail: ManagedDocumentDetail | DocumentResourceRedirect): ManagedDocumentDetail {
  if ('resource_type' in detail) throw new DatasetDocumentRedirect(detail.resource_uri)
  // Also handle responses/seeds retained by a client during the transition.
  if (detail.item.document_type === 'dataset') throw new DatasetDocumentRedirect(`data://${detail.item.id}`)
  if (!['text', 'html', 'data'].includes(detail.item.document_type)) throw new Error('This resource is not an HTML Document.')
  return detail
}

export interface DocumentInternalAttachments {
  items: { uri: string; name: string; is_collection: boolean; media_type: string; size: number | null; capabilities: string[]; metadata?: Record<string, unknown>; available: boolean }[]
  lock_version: number
}

export interface DocumentFolderEntry {
  uri: string
  name: string
  is_collection: boolean
  media_type: string
  size: number | null
  capabilities: string[]
  metadata: { document_folder?: boolean; icon?: string | null }
}
export interface DocumentFolderPage {
  folder: DocumentFolderEntry
  entries: DocumentFolderEntry[]
  total: number
}

const ownerOptionsCache = createOwnerOptionsCache<DocumentOwnerOptions>()

export const documentService = {
async summary(id: string, agentId: number | null, signal?: AbortSignal): Promise<DocumentDetail> {
  return (await api.get<DocumentDetail>(`/documents/${id}/summary`, {
    params: { agent_id: agentId ?? undefined }, signal,
  })).data
},
async folderCollection(id: string | null, agentId: number | null, options: { offset?: number; limit?: number; query?: string; metadata_only?: boolean } = {}, signal?: AbortSignal): Promise<DocumentFolderPage> {
  return (await api.get<DocumentFolderPage>(`/documents/folder-collections${id ? '/' + encodeURIComponent(id) : ''}`, {
    params: { agent_id: agentId, ...options }, signal,
  })).data
},
async linkThumbnail(url: string, agentId: number | null, signal: AbortSignal): Promise<Blob | null> {
  const response = await api.post<Blob>('/documents/link-card/thumbnail', { url }, {
    params: { agent_id: agentId }, responseType: 'blob', signal,
  })
  return response.status === 204 ? null : response.data
},
async updateSummary(id: string, agentId: number | null, data: DocumentUpdate): Promise<DocumentDetail> {
  return (await api.put<DocumentDetail>(`/documents/${id}/summary`, data, {
    params: { actor_agent_id: agentId }, headers: { 'X-Editorial-Profile-Version': '1' },
  })).data
},

async regenerateSummary(id: string, agentId: number | null, expectedLockVersion: number): Promise<DocumentDetail> {
  return (await api.post<DocumentDetail>(`/documents/${id}/summary/regenerate`, {
    expected_lock_version: expectedLockVersion,
  }, { params: { actor_agent_id: agentId ?? undefined } })).data
},

async internalAttachments(id: string, agentId: number | null, resourceAgentId: number, signal?: AbortSignal): Promise<DocumentInternalAttachments> {
    return (await api.get<DocumentInternalAttachments>(`/documents/${id}/internal-attachments`, { params: { agent_id: agentId, resource_agent_id: resourceAgentId }, signal })).data
  },

async changeInternalAttachments(id: string, uris: string[], agentId: number | null, resourceAgentId: number, version: number, remove = false): Promise<DocumentInternalAttachments> {
    return (await api.put<DocumentInternalAttachments>(`/documents/${id}/internal-attachments`, { uris, remove, resource_agent_id: resourceAgentId, expected_lock_version: version }, { params: { actor_agent_id: agentId } })).data
  },

async documentProcesses(id: string, agentId: number | null, signal?: AbortSignal): Promise<DocumentProcessAttachments> {
    return (await api.get(`/documents/${id}/process-attachments`, { params: { agent_id: agentId }, signal })).data
  },

async changeDocumentProcess(id: string, uri: string, agentId: number | null, version: number, remove = false): Promise<DocumentProcessAttachments> {
    return (await api.put(`/documents/${id}/process-attachments`, { uri, expected_lock_version: version, remove }, { params: { actor_agent_id: agentId } })).data
  },

async documentDatasets(id: string, agentId: number | null): Promise<DocumentDatasetAttachments> {
    return (await api.get<DocumentDatasetAttachments>(`/documents/${id}/dataset-attachments`, { params: { agent_id: agentId } })).data
  },

async attachDataset(id: string, datasetId: string, agentId: number | null, version: number): Promise<DocumentDatasetAttachments> {
    return (await api.put<DocumentDatasetAttachments>(`/documents/${id}/dataset-attachments`, {
      dataset_id: datasetId, expected_lock_version: version,
    }, { params: { actor_agent_id: agentId } })).data
  },

async detachDataset(id: string, datasetId: string, agentId: number | null, version: number): Promise<DocumentDatasetAttachments> {
    return (await api.delete<DocumentDatasetAttachments>(`/documents/${id}/dataset-attachments/${datasetId}`, {
      params: { actor_agent_id: agentId, expected_lock_version: version },
    })).data
  },

async appDataset(documentId: string, revision: number, appId: string, alias: string, data: AppDatasetRequest, signal: AbortSignal): Promise<AppDatasetResult> {
    return (await api.post<AppDatasetResult>(`/documents/${documentId}/apps/${encodeURIComponent(appId)}/datasets/${encodeURIComponent(alias)}`, {
      ...data, document_revision: revision,
    }, { signal })).data
  },

async documentThumbnailSnapshot(id: string, agentId: number | null, signal: AbortSignal): Promise<{ html: string; revision: number; lock_version: number } | null> {
    const detail = (await api.get<ManagedDocumentDetail | DocumentResourceRedirect>(`/documents/${id}`, {
      params: { agent_id: agentId ?? undefined }, signal,
    })).data
    if ('resource_type' in detail || detail.item.document_type === 'dataset') return null
    const item = detail.item
    const { documentType } = await import('../documentTypes')
    const html = await documentType(item.document_type).snapshot(item.payload.text ?? '', item.title, signal,
      (documentId, attachmentId) => documentService.documentAttachmentBlob(documentId, attachmentId, detail.agent_id, signal))
    return { html, revision: item.revision, lock_version: item.lock_version }
  },

async documentThumbnail(id: string, agentId: number | null, signal: AbortSignal): Promise<Blob | null> {
    const snapshot = await this.documentThumbnailSnapshot(id, agentId, signal)
    if (!snapshot) return null
    const response = await api.post<Blob>(`/documents/${id}/thumbnail`, snapshot, {
      params: { agent_id: agentId }, responseType: 'blob', signal,
    })
    const blob = response.status === 200 && response.data.type === 'image/webp' ? response.data : null
    if (blob && !signal.aborted) thumbnailReady({ agentId, itemId: id, blob })
    return blob
  },

async itemSharing(id: string): Promise<DocumentSharing> { return (await api.get<DocumentSharing>(`/documents/${id}/sharing`)).data },

async updateItemSharing(id: string, data: import('../types').DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/documents/${id}/sharing`, data)).data },

async updateDocumentSharingLevel(id: string, data: import('../types').DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/documents/${id}/sharing-level`, data)).data },

async documentSharing(id: string): Promise<DocumentSharing> { return (await api.get<DocumentSharing>(`/documents/${id}/sharing`)).data },

async folderSharing(id: string): Promise<DocumentSharing> { return (await api.get<DocumentSharing>(`/documents/tags/${id}/sharing`)).data },

async updateFolderSharing(id: string, data: import('../types').DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/documents/tags/${id}/sharing`, data)).data },

async updateDocumentSharing(id: string, data: DocumentSharingUpdate): Promise<DocumentSharing> { return (await api.put<DocumentSharing>(`/documents/${id}/sharing`, data)).data },

async createDocumentLinkCard(id: string, agentId: number | null, url: string): Promise<{ html: string; attachment: DocumentAttachment | null }> {
    const response = await api.post<{ html: string; attachment: DocumentAttachment | null }>(`/documents/${id}/link-card`, { url }, { params: { actor_agent_id: agentId } })
    return response.data
  },

async exportDocumentBundle(id: string, agentId: number | null, html: string, signal: AbortSignal): Promise<Blob> {
    const response = await api.post<Blob>(`/documents/${id}/export-bundle`, { html }, { params: { agent_id: agentId }, responseType: 'blob', signal })
    return response.data
  },

async exportDocumentPdf(id: string, html: string, signal: AbortSignal): Promise<Blob> {
    const response = await api.post<Blob>(`/documents/${id}/export-pdf`, { html }, {
      responseType: 'blob', signal,
    })
    return response.data
  },

async listDocumentTags(): Promise<{ user_id: number; tags: DocumentTag[] }> {
    return (await api.get<{ user_id: number; tags: DocumentTag[] }>('/documents/tags')).data
  },

async saveDocumentTag(data: { name: string; parent_id: string | null; icon?: string | null }, id?: string): Promise<DocumentTag> {
    return id
      ? (await api.put<DocumentTag>(`/documents/tags/${id}`, data)).data
      : (await api.post<DocumentTag>('/documents/tags', data)).data
  },

async deleteDocumentTag(id: string, confirmed = false): Promise<DocumentTagDeletionResult> {
    return (await api.delete<DocumentTagDeletionResult>(`/documents/tags/${id}`, { params: { confirmed } })).data
  },

async assignDocumentTag(documentId: string, tagId: string, remove = false): Promise<void> {
    const url = `/documents/${documentId}/tags/${tagId}`
    if (remove) await api.delete(url)
    else await api.put(url)
  },

async moveDocumentToTag(documentId: string, tagId: string | null, atRoot = false): Promise<void> {
    await api.put(`/documents/${documentId}/tags`, { tag_id: tagId, ...(atRoot ? { at_root: true } : {}) })
  },

async moveDocumentUnderDocument(documentId: string, parentDocumentId: string | null): Promise<void> {
    await api.put(`/documents/${documentId}/parent`, { parent_document_id: parentDocumentId })
  },

async reorderDocuments(data: DocumentOrderMove): Promise<void> {
    await api.put('/documents/order', data)
  },

async sortDocumentFolder(parentId: string | null, descending: boolean): Promise<void> {
    await api.put('/documents/order/sort', { parent_id: parentId, descending })
  },

async resolveDocumentIcons(documentIds: string[]): Promise<Record<string, string | null>> {
    return (await api.post<Record<string, string | null>>('/documents/icons/resolve', { document_ids: documentIds })).data
  },

async saveDocumentIcon(documentId: string, icon: string | null): Promise<{ icon: string | null }> {
    return (await api.put<{ icon: string | null }>(`/documents/${documentId}/icon`, { icon })).data
  },

async listDocumentTagIcons(): Promise<DocumentTagIcon[]> {
    return (await api.get<DocumentTagIcon[]>('/documents/tag-icons')).data
  },

async uploadDocumentTagIcon(name: string, data: string): Promise<DocumentTagIcon> {
    return (await api.post<DocumentTagIcon>('/documents/tag-icons', { name, data })).data
  },

async browseDocumentLibrary(params: DocumentLibraryFilters, signal?: AbortSignal): Promise<DocumentLibraryPage> {
    const response = await api.post<DocumentLibraryPage>('/documents/library', {
      ...params,
      query: params.query ?? '',
      keyword: params.keyword ?? null,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    }, { signal })
    return response.data
  },

async getManagedDocument(id: string): Promise<ManagedDocumentDetail> {
    const response = await api.get<ManagedDocumentDetail | DocumentResourceRedirect>(`/documents/${id}`)
    return editorialDocument(response.data)
  },

async listDocumentContentRevisions(id: string, limit = 50, offset = 0): Promise<DocumentContentRevisionPage> {
    const response = await api.get<DocumentContentRevisionPage>(
      `/documents/${id}/content-revisions`,
      { params: { limit, offset } },
    )
    return response.data
  },

async getDocumentContentRevision(
    id: string,
    revision: number,
  ): Promise<DocumentContentRevisionDetail> {
    const response = await api.get<DocumentContentRevisionDetail>(
      `/documents/${id}/content-revisions/${revision}`,
    )
    return response.data
  },

async diffDocumentContentRevision(
    id: string,
    revision: number,
  ): Promise<DocumentContentDiff> {
    const response = await api.get<DocumentContentDiff>(
      `/documents/${id}/content-revisions/${revision}/diff`,
    )
    return response.data
  },

async restoreDocumentContentRevision(
    id: string,
    revision: number,
    expectedRevision: number,
  ): Promise<DocumentRecord> {
    const response = await api.post<DocumentRecord>(
      `/documents/${id}/content-revisions/${revision}/restore`,
      { expected_revision: expectedRevision },
    )
    return response.data
  },

async listDocumentOwnerOptions(search = ''): Promise<DocumentOwnerOptions> {
    return ownerOptionsCache.read(search, async signal => (await api.get<DocumentOwnerOptions>('/documents/owner-options', {
      params: { search }, signal,
    })).data)
  },

async createDocument(data: DocumentCreate): Promise<DocumentRecord> {
    const response = await api.post<DocumentRecord>('/documents', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

async changeDocumentOwner(
    id: string,
    expectedRevision: number,
    expectedLockVersion: number,
    kind: DocumentOwnerKind,
    ownerId: number,
  ): Promise<DocumentRecord> {
    const response = await api.patch<DocumentRecord>(`/documents/${id}/owner`, {
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
  ): Promise<DocumentRecord> {
    const response = await api.patch<DocumentRecord>(`/documents/${id}/global-access`, {
      expected_revision: expectedRevision,
      expected_lock_version: expectedLockVersion,
      global_access: globalAccess,
    })
    return response.data
  },

async moveDocument(id: string, expectedRevision: number, expectedLockVersion: number, folder: string): Promise<DocumentRecord> {
    const response = await api.patch<DocumentRecord>(`/documents/${id}/folder`, {
      expected_revision: expectedRevision,
      expected_lock_version: expectedLockVersion,
      folder,
    })
    return response.data
  },

async listDocumentKeywords(agentId: number | null): Promise<string[]> {
    if (agentId === null) return []
    const response = await api.get<string[]>('/documents/keywords', {
      params: { agent_id: agentId },
    })
    return response.data
  },

async listDocumentFolders(agentId: number | null): Promise<string[]> {
    if (agentId === null) return []
    const response = await api.get<string[]>('/documents/folders', {
      params: { agent_id: agentId },
    })
    return response.data
  },

async listDocumentFolderOptions(agentId: number | null): Promise<DocumentFolderOption[]> {
    if (agentId === null) return []
    const response = await api.get<DocumentFolderOption[]>('/documents/folders', {
      params: { agent_id: agentId, details: true },
    })
    return response.data
  },

async listDocumentAttachments(id: string, agentId: number | null): Promise<DocumentAttachment[]> {
    const response = await api.get<DocumentAttachment[]>(`/documents/${id}/attachments`, {
      params: { agent_id: agentId },
    })
    return response.data
  },

async addDocumentAttachment(id: string, agentId: number | null, file: File, signal?: AbortSignal, progress?: (value: number) => void): Promise<DocumentAttachment> {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<DocumentAttachment>(
      `/documents/${id}/attachments`,
      form,
      { params: { actor_agent_id: agentId }, signal, onUploadProgress: event => progress?.(event.total ? event.loaded / event.total : 0) },
    )
    return response.data
  },

async importDocumentImage(id: string, agentId: number | null, url: string, signal: AbortSignal): Promise<DocumentAttachment> {
    const response = await api.post<DocumentAttachment>(`/documents/${id}/import-image`, { url }, {
      params: { actor_agent_id: agentId }, signal,
    })
    return response.data
  },

async documentAttachmentInfo(id: string, attachmentId: string, agentId: number | null): Promise<DocumentAttachment> {
    const response = await api.get<DocumentAttachment>(`/documents/${id}/attachments/${attachmentId}/info`, { params: { agent_id: agentId } })
    return response.data
  },

async documentAttachmentBlob(id: string, attachmentId: string, agentId: number | null, signal?: AbortSignal): Promise<Blob> {
    const response = await api.get<Blob>(
      `/documents/${id}/attachments/${attachmentId}`,
      { params: { agent_id: agentId }, responseType: 'blob', signal },
    )
    return response.data
  },

async documentAttachmentThumbnailBlob(id: string, attachmentId: string, agentId: number | null, signal?: AbortSignal, cachedOnly = false): Promise<Blob> {
    const response = await api.get<Blob>(
      `/documents/${id}/attachments/${attachmentId}/thumbnail`,
      { params: { agent_id: agentId, cached_only: cachedOnly }, responseType: 'blob', signal },
    )
    if (!cachedOnly && !signal?.aborted) thumbnailReady({ agentId,
      resourceUri: `document://${id}/attachments/${attachmentId}`, blob: response.data })
    return response.data
  },

async deleteDocumentAttachment(id: string, attachmentId: string, agentId: number | null): Promise<void> {
    await api.delete(`/documents/${id}/attachments/${attachmentId}`, {
      params: { actor_agent_id: agentId },
    })
  },

async renameDocumentAttachment(id: string, attachmentId: string, agentId: number | null, name: string): Promise<DocumentAttachment> {
    return (await api.patch<DocumentAttachment>(`/documents/${id}/attachments/${attachmentId}`, { name }, { params: { actor_agent_id: agentId } })).data
  },

async getDocument(id: string, agentId?: number | null): Promise<DocumentDetail> {
    return editorialDocument((await api.get<ManagedDocumentDetail | DocumentResourceRedirect>(`/documents/${id}`, {
      params: { agent_id: agentId ?? undefined },
    })).data).item
  },

async updateDocument(id: string, agentId: number | null, data: DocumentUpdate): Promise<DocumentRecord> {
    return (await api.patch<DocumentRecord>(`/documents/${id}`, data, {
      headers: { 'X-Editorial-Profile-Version': '1' }, params: { actor_agent_id: agentId ?? undefined },
    })).data
  },

async deleteDocument(id: string, agentId: number | null): Promise<void> {
    await api.delete(`/documents/${id}`, { params: { actor_agent_id: agentId } })
  },

async setDocumentGrant(
    id: string,
    ownerAgentId: number,
    targetAgentId: number,
    canWrite: boolean,
  ): Promise<DocumentRecord> {
    const response = await api.put<DocumentRecord>(
      `/documents/${id}/grants/${targetAgentId}`,
      { can_write: canWrite },
      { params: { owner_agent_id: ownerAgentId } },
    )
    return response.data
  },

async removeDocumentGrant(
    id: string,
    ownerAgentId: number,
    targetAgentId: number,
  ): Promise<DocumentRecord> {
    const response = await api.delete<DocumentRecord>(
      `/documents/${id}/grants/${targetAgentId}`,
      { params: { owner_agent_id: ownerAgentId } },
    )
    return response.data
  },

async setManagedDocumentGrant(
    id: string,
    targetAgentId: number,
    canWrite: boolean,
    expectedLockVersion: number,
  ): Promise<DocumentRecord> {
    const response = await api.put<DocumentRecord>(
      `/documents/${id}/collaborators/${targetAgentId}`,
      { can_write: canWrite, expected_lock_version: expectedLockVersion },
    )
    return response.data
  },

async removeManagedDocumentGrant(
    id: string,
    targetAgentId: number,
    expectedLockVersion: number,
  ): Promise<DocumentRecord> {
    const response = await api.delete<DocumentRecord>(
      `/documents/${id}/collaborators/${targetAgentId}`,
      { params: { expected_lock_version: expectedLockVersion } },
    )
    return response.data
  }
}
