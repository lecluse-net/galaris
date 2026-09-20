import { api } from '@/core/api'
import type {
  Goal,
  GoalCommand,
  GoalCreate,
  GoalCyclePage,
  GoalDetail,
  GoalPage,
  GoalSettings,
  GoalSettingsUpdate,
  GoalStatus,
  GoalTreePage,
  GoalUpdate,
  MessengerReferrerOption,
} from '../types'

export const goalService = {
  async getSettings(): Promise<GoalSettings> {
    const response = await api.get<GoalSettings>('/goals/settings')
    return response.data
  },

  async updateSettings(data: GoalSettingsUpdate): Promise<GoalSettings> {
    const response = await api.patch<GoalSettings>('/goals/settings', data)
    return response.data
  },

  async list(params: {
    skip?: number
    limit?: number
    agentId?: number | null
    status?: GoalStatus | null
    search?: string
  } = {}): Promise<GoalPage> {
    const response = await api.get<GoalPage>('/goals', {
      params: {
        skip: params.skip ?? 0,
        limit: params.limit ?? 50,
        agent_id: params.agentId ?? undefined,
        status: params.status ?? undefined,
        q: params.search?.trim() || undefined,
      },
    })
    return response.data
  },

  async get(id: string): Promise<GoalDetail> {
    const response = await api.get<GoalDetail>(`/goals/${id}`)
    return response.data
  },

  async tree(): Promise<GoalTreePage> {
    const response = await api.get<GoalTreePage>('/goals/tree')
    return response.data
  },

  async listCycles(
    id: string,
    params: { page?: number; pageSize?: number } = {},
  ): Promise<GoalCyclePage> {
    const response = await api.get<GoalCyclePage>(`/goals/${id}/cycles`, {
      params: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      },
    })
    return response.data
  },

  async searchMessengerReferrers(
    agentId: number,
    query: string,
  ): Promise<MessengerReferrerOption[]> {
    const response = await api.get<MessengerReferrerOption[]>('/goals/referrers/messenger', {
      params: { agent_id: agentId, q: query.trim() },
    })
    return response.data
  },

  async create(data: GoalCreate): Promise<Goal> {
    const response = await api.post<Goal>('/goals', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

  async update(id: string, data: GoalUpdate): Promise<Goal> {
    const response = await api.put<Goal>(`/goals/${id}`, data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  },

  async pause(id: string, command: GoalCommand): Promise<Goal> {
    const response = await api.post<Goal>(`/goals/${id}/pause`, command)
    return response.data
  },

  async resume(id: string, command: GoalCommand): Promise<Goal> {
    const response = await api.post<Goal>(`/goals/${id}/resume`, command)
    return response.data
  },

  async complete(id: string, command: GoalCommand): Promise<Goal> {
    const response = await api.post<Goal>(`/goals/${id}/complete`, command)
    return response.data
  },

  async runNow(id: string, command: GoalCommand): Promise<Goal> {
    const response = await api.post<Goal>(`/goals/${id}/run-now`, command)
    return response.data
  },

  async delete(id: string): Promise<void> {
    await api.delete(`/goals/${id}`)
  },
}
