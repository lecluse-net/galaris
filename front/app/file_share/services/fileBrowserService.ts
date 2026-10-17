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
  async schemes(agent: number, signal?: AbortSignal): Promise<FileScheme[]> {
    return (await api.get<FileScheme[]>('/file-share/browser/schemes', { params: { agent_id: agent }, signal })).data
  },
  async list(agent: number, uri: string, cursor?: string | null, signal?: AbortSignal): Promise<FileListing> {
    return (await api.get<FileListing>('/file-share/browser/entries', {
      params: { agent_id: agent, uri, cursor: cursor || undefined, limit: 50 }, signal,
    })).data
  },
  async info(agent: number, uri: string, signal?: AbortSignal): Promise<FileEntry> {
    return (await api.get<FileEntry>('/file-share/browser/info', { params: { agent_id: agent, uri }, signal })).data
  },
  async content(agent: number, uri: string, preview: boolean, signal?: AbortSignal): Promise<Blob> {
    return (await api.get<Blob>('/file-share/browser/content', {
      params: { agent_id: agent, uri, preview }, responseType: 'blob', signal,
    })).data
  },
  async thumbnail(agent: number, uri: string, signal?: AbortSignal): Promise<Blob> {
    return (await api.get<Blob>('/file-share/browser/thumbnail', {
      params: { agent_id: agent, uri }, responseType: 'blob', signal,
    })).data
  },
}
