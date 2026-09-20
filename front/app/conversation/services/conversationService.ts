import { api } from '@/core/api'
import type { LLMCall } from '@/app/llm/types'
import type {
  ConversationMessagePage,
  ConversationRoundDetail,
  ConversationStatus,
  ConversationUnknownNotification,
} from '../types'

export const conversationService = {
  async resolveDelivery(roundId: string, decision: 'DELIVERED' | 'SKIPPED', evidence: string,
    notification?: ConversationUnknownNotification): Promise<ConversationRoundDetail> {
    const { data } = await api.post<ConversationRoundDetail>(
      `/conversations/rounds/${encodeURIComponent(roundId)}/delivery-resolution`, {
        decision, evidence,
        notification: notification ? {
          kind: notification.kind, link_id: notification.link_id, attempt_number: notification.attempt_number,
        } : undefined,
      },
    )
    return data
  },
  async listMessages(params: {
    page?: number
    pageSize?: number
    agentId?: number | null
    status?: ConversationStatus | null
    channelKind?: string | null
    topicId?: string | null
    search?: string
    active?: boolean | null
    dateFrom?: string | null
    dateTo?: string | null
    errorsOnly?: boolean
  }): Promise<ConversationMessagePage> {
    const response = await api.get<ConversationMessagePage>('/conversations/messages', {
      params: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
        agent_id: params.agentId ?? undefined,
        status: params.status || undefined,
        channel_kind: params.channelKind || undefined,
        topic_id: params.topicId || undefined,
        search: params.search?.trim() || undefined,
        errors_only: params.errorsOnly || undefined,
        active: params.active ?? undefined,
        date_from: params.dateFrom || undefined,
        date_to: params.dateTo || undefined,
      },
    })
    return response.data
  },

  async getRound(roundId: string): Promise<ConversationRoundDetail> {
    const response = await api.get<ConversationRoundDetail>(
      `/conversations/rounds/${encodeURIComponent(roundId)}`,
    )
    return response.data
  },

  async updateRoundTopic(
    roundId: string,
    topicId: string | null,
  ): Promise<ConversationRoundDetail> {
    const response = await api.put<ConversationRoundDetail>(
      `/conversations/rounds/${encodeURIComponent(roundId)}/topic`,
      { topic_id: topicId },
    )
    return response.data
  },

  async exportRound(roundId: string): Promise<Record<string, unknown>> {
    const response = await api.get<Record<string, unknown>>(
      `/conversations/rounds/${encodeURIComponent(roundId)}/dataset`,
    )
    return response.data
  },

  async deleteRound(roundId: string): Promise<void> {
    await api.delete(`/conversations/rounds/${encodeURIComponent(roundId)}`)
  },

  async llmCalls(roundId: string): Promise<LLMCall[]> {
    const response = await api.get<LLMCall[]>('/llm-calls', {
      params: {
        conversation_round_id: roundId,
        limit: 500,
      },
    })
    return response.data
  },
}
