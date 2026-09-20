import { api } from '@/core/api'
import type { LLMCall } from '@/app/llm/types'
import type {
  VoiceConversationDetail,
  VoiceConversationPage,
  VoiceConversationStatus,
  VoiceConversationTurnDetail,
} from '../types'

export const voiceConversationService = {
  async list(params: {
    page?: number
    pageSize?: number
    agentId?: number | null
    status?: VoiceConversationStatus | null
    topicId?: string | null
    dateFrom?: string | null
    dateTo?: string | null
    search?: string
    active?: boolean | null
  }): Promise<VoiceConversationPage> {
    const response = await api.get<VoiceConversationPage>('/voice/conversations', {
      params: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
        agent_id: params.agentId ?? undefined,
        status: params.status || undefined,
        topic_id: params.topicId || undefined,
        date_from: params.dateFrom || undefined,
        date_to: params.dateTo || undefined,
        search: params.search?.trim() || undefined,
        active: params.active ?? undefined,
      },
    })
    return response.data
  },

  async get(id: string): Promise<VoiceConversationDetail> {
    const response = await api.get<VoiceConversationDetail>(
      `/voice/conversations/${encodeURIComponent(id)}`,
    )
    return response.data
  },

  async getTurn(id: string): Promise<VoiceConversationTurnDetail> {
    const response = await api.get<VoiceConversationTurnDetail>(
      `/voice/conversations/turns/${encodeURIComponent(id)}`,
    )
    return response.data
  },

  async updateTurnTopic(
    id: string,
    topicId: string | null,
  ): Promise<VoiceConversationTurnDetail> {
    const response = await api.put<VoiceConversationTurnDetail>(
      `/voice/conversations/turns/${encodeURIComponent(id)}/topic`,
      { topic_id: topicId },
    )
    return response.data
  },

  async exportTurn(id: string): Promise<Record<string, unknown>> {
    const response = await api.get<Record<string, unknown>>(
      `/voice/conversations/turns/${encodeURIComponent(id)}/dataset`,
    )
    return response.data
  },

  async deleteTurn(id: string): Promise<void> {
    await api.delete(`/voice/conversations/turns/${encodeURIComponent(id)}`)
  },

  async llmCalls(voiceTurnId: string): Promise<LLMCall[]> {
    const response = await api.get<LLMCall[]>('/llm-calls', {
      params: {
        voice_turn_id: voiceTurnId,
        limit: 500,
      },
    })
    return response.data
  },
}
