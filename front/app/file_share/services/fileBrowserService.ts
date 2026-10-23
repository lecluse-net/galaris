import { api } from '@/core/api'

export interface FileScheme {
  scheme: string
  label: string
  capabilities: string[]
  native: boolean
  root_listable?: boolean
}
export interface FileEntry {
  uri: string
  name: string
  is_collection: boolean
  media_type: string
  size: number | null
  modified_at?: string | null
  capabilities: string[]
  metadata?: Record<string, unknown>
}
export interface FileListing {
  uri: string
  entries: FileEntry[]
  truncated: boolean
  next_cursor: string | null
}

export const fileBrowserService = {
  canMove(entry: FileEntry): boolean {
    return entry.capabilities.includes('move') && !/^(galaris|document|data|memory):\/\//.test(entry.uri)
  },
  canDelete(entry: FileEntry): boolean {
    return entry.capabilities.includes('delete') && !/^(galaris|data|memory):\/\//.test(entry.uri)
      && (!entry.uri.startsWith('document://') || /^document:\/\/[^/]+\/attachments\/[^/]+$/.test(entry.uri))
      && !!entry.uri.split('://')[1]
  },
  canRename(entry: FileEntry): boolean {
    return fileBrowserService.canMove(entry) || (!entry.is_collection && ((entry.metadata?.can_rename === true)
      || (/^document:\/\/[^/]+\/attachments\/[^/]+$/.test(entry.uri) && entry.capabilities.includes('delete'))))
  },
  async rename(agent: number, entry: FileEntry, name: string): Promise<string> {
    if (fileBrowserService.canMove(entry)) {
      return (await api.patch<{ uri: string }>('/file-share/browser/entry', { name }, { params: { agent_id: agent, uri: entry.uri } })).data.uri
    }
    const reference = typeof entry.metadata?.rename_uri === 'string' ? entry.metadata.rename_uri : entry.uri
    const dataset = /^data:\/\/([^/]+)\/attachments\/([^/]+)$/.exec(reference)
    if (dataset) {
      await api.patch(`/datasets/${dataset[1]}/attachments/${dataset[2]}`, { name })
      return entry.uri
    }
    if (entry.uri.startsWith('file://')) {
      await api.patch(`/file-share/files/${entry.uri.slice('file://'.length)}`, { name }, { params: { agent_id: agent } })
    } else {
      const [, document, attachment] = /^document:\/\/([^/]+)\/attachments\/([^/]+)$/.exec(entry.uri) ?? []
      if (!document || !attachment) throw new Error('Unsupported file rename')
      await api.patch(`/documents/${document}/attachments/${attachment}`, { name }, { params: { actor_agent_id: agent } })
    }
    return entry.uri
  },
  async remove(agent: number, entry: FileEntry): Promise<void> {
    await api.delete('/file-share/browser/entry', { params: { agent_id: agent, uri: entry.uri, recursive: entry.is_collection } })
  },
  async videoUrl(agent: number, uri: string, management = false): Promise<string | null> {
    return (await api.post<{ url: string | null }>('/file-share/browser/media', null, {
      params: { agent_id: agent, uri, management },
    })).data.url
  },
  async releaseVideoUrl(url: string): Promise<void> {
    await api.delete(url.replace(/^\/api\//, '/'))
  },
  async search(agent: number, uri: string, query: string, cursor?: string | null, signal?: AbortSignal, management = false): Promise<FileListing> {
    const { data } = await api.get<{ hits: { resource: FileEntry }[]; truncated: boolean; next_cursor: string | null }>('/file-share/browser/search', {
      params: { agent_id: agent, uri, query, cursor: cursor || undefined, management }, signal,
    })
    return { uri, entries: data.hits.map(hit => hit.resource), truncated: data.truncated, next_cursor: data.next_cursor }
  },
  async schemes(agent: number, signal?: AbortSignal): Promise<FileScheme[]> {
    return (await api.get<FileScheme[]>('/file-share/browser/schemes', { params: { agent_id: agent }, signal })).data
  },
  async list(agent: number, uri: string, cursor?: string | null, signal?: AbortSignal, management = false): Promise<FileListing> {
    return (await api.get<FileListing>('/file-share/browser/entries', {
      params: { agent_id: agent, uri, cursor: cursor || undefined, limit: 50, management }, signal,
    })).data
  },
  async info(agent: number, uri: string, signal?: AbortSignal): Promise<FileEntry> {
    return (await api.get<FileEntry>('/file-share/browser/info', { params: { agent_id: agent, uri }, signal })).data
  },
  async content(agent: number, uri: string, preview: boolean, signal?: AbortSignal, management = false): Promise<Blob> {
    return (await api.get<Blob>('/file-share/browser/content', {
      params: { agent_id: agent, uri, preview, management }, responseType: 'blob', signal,
    })).data
  },
  async thumbnail(agent: number, uri: string, signal?: AbortSignal): Promise<Blob> {
    return (await api.get<Blob>('/file-share/browser/thumbnail', {
      params: { agent_id: agent, uri }, responseType: 'blob', signal,
    })).data
  },
}
