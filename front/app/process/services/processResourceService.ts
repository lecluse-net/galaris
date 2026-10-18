import { api } from '@/core/api'
import type { BpmnGraph } from './nativeProcessService'

export interface ProcessResourcePreview {
  uri: string; kind: 'process' | 'process_run'; id: string; title: string; description: string | null
  revision: number; graph: BpmnGraph; process_uri: string
}
export const processResourceService = {
  async search(query: string, agentId: number | null = null, signal?: AbortSignal): Promise<{ uri: string; title: string; context: string }[]> {
    return (await api.get('/processes/internal/resource-options', { params: { query, agent_id: agentId ?? undefined }, signal })).data
  },
  async preview(uri: string, agentId: number | null = null, signal?: AbortSignal, thumbnail = false): Promise<ProcessResourcePreview> {
    return (await api.get<ProcessResourcePreview>('/processes/internal/resource-preview', {
      params: { uri, agent_id: agentId ?? undefined, thumbnail }, signal,
    })).data
  },
}
