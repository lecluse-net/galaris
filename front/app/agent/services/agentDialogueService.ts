import { api } from '@/core/api'
import { readSessionImage } from '@/core/util/facade'

export interface DialogueAgent {
  agent_id: number
  connection_id: number
  code: string
  display_name: string
  active: boolean
  suggested_room_label?: string
}

export interface DialogueAgentProfile {
  job_title: string | null
  job_description: string | null
  personality: string | null
  external_services: { code: string; label: string }[]
}

export const agentDialogueService = {
  async page(page = 1, pageSize = 50, signal?: AbortSignal): Promise<{ agents: DialogueAgent[]; total: number }> {
    return (await api.get<{ agents: DialogueAgent[]; total: number }>('/chat/recipients', {
      params: { page, page_size: pageSize }, signal,
    })).data
  },
  async profile(agentId: number, signal?: AbortSignal): Promise<DialogueAgentProfile> {
    return (await api.get<DialogueAgentProfile>(`/chat/agents/${agentId}/profile`, { signal })).data
  },
  avatarBlob(agentId: number, signal?: AbortSignal): Promise<Blob | null> {
    return readSessionImage('agent-avatar', String(agentId), `/chat/agents/${agentId}/avatar`, { signal, endpoint: 'chat' })
  },
}
