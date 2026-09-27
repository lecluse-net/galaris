import api, { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { createSessionReadCache } from '@/core/util/facade'

export type AgentSelectionScope = 'management' | 'dialogue' | 'teams'

export interface AgentSelectionOption {
  id: number
  label: string
  has_avatar: boolean
}

const selections = createSessionReadCache<AgentSelectionOption[]>({ sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, group: 'agent-selection', maxAgeMs: 0, maxEntries: 0 })

export async function getAgentSelection(scope: AgentSelectionScope, signal?: AbortSignal): Promise<AgentSelectionOption[]> {
  const options = await selections.read(scope, async signal => (
    await api.get<AgentSelectionOption[]>('/agents/selection', { params: { scope }, signal })
  ).data, signal)
  return options.map(option => ({ ...option }))
}
