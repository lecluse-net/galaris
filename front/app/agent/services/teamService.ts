import api from '@/core/api'
import { invalidateSessionReads } from '@/core/util/facade'

export interface TeamAgent {
  id: number
  label: string
  code: string
  manager_user_id: number
  team_ids: number[]
  has_avatar: boolean
}

export const teamService = {
  async agents(): Promise<TeamAgent[]> {
    return (await api.get<TeamAgent[]>('/agents/teams/agents')).data
  },
  async membership(team: number, agent: number, present: boolean): Promise<void> {
    await api.put(`/agents/teams/${team}/members/${agent}`, { present })
    invalidateSessionReads('agent-catalogue')
    invalidateSessionReads('agent-selection')
  },
}
