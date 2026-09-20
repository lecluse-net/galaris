import api from '@/core/api'

export type AgentSelectionScope = 'management' | 'dialogue' | 'teams'

export interface AgentSelectionOption {
  id: number
  label: string
  has_avatar: boolean
}

export async function getAgentSelection(scope: AgentSelectionScope): Promise<AgentSelectionOption[]> {
  return (await api.get<AgentSelectionOption[]>('/agents/selection', { params: { scope } })).data
}
