import { api } from '@/core/api'

export interface FileIndexRun {
  id: string
  root_uri: string
  status: string
  scanned: number
  directories: number
  error_type: string | null
  updated_at: string
}
export interface FileIndexPage { runs: FileIndexRun[]; total: number; pending_repairs: number; failed_repairs: number }
export const fileIndexService = {
  async list(agentId: number, page = 1, pageSize = 50): Promise<FileIndexPage> {
    return (await api.get<FileIndexPage>('/file-share/indexing', { params: { agent_id: agentId, page, page_size: pageSize } })).data
  },
  async start(agentId: number, rootUri: string): Promise<FileIndexRun> {
    return (await api.post<FileIndexRun>('/file-share/indexing', { agent_id: agentId, root_uri: rootUri })).data
  },
  async cancel(agentId: number, id: string): Promise<void> {
    await api.post(`/file-share/indexing/${id}/cancel`, null, { params: { agent_id: agentId } })
  },
  async retryRepairs(agentId: number): Promise<void> {
    await api.post('/file-share/indexing/repairs/retry', null, { params: { agent_id: agentId } })
  },
}
