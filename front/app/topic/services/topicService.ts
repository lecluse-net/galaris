import { api } from '@/core/api'
import type {
  Topic,
  TopicContent,
  TopicInput,
  TopicLinkedMemory,
  TopicMutationResult,
  TopicPage,
  TopicRef,
  TopicAssignmentAudit,
  TopicAssignmentSubjectKind,
} from '../types'

export const topicService = {
  async refs(ids: string[]): Promise<TopicRef[]> {
    const uniqueIds = [...new Set(ids.filter(Boolean))]
    if (!uniqueIds.length) return []
    const params = new URLSearchParams()
    for (const id of uniqueIds.slice(0, 500)) params.append('ids', id)
    const response = await api.get<TopicRef[]>('/topics/refs', { params })
    return response.data
  },

  async assignmentAudit(params: {
    topicId: string
    subjectKind: TopicAssignmentSubjectKind
    subjectId: string
  }): Promise<TopicAssignmentAudit> {
    const response = await api.get<TopicAssignmentAudit>(
      '/dream/topic-assignment',
      {
        params: {
          topic_id: params.topicId,
          subject_kind: params.subjectKind,
          subject_id: params.subjectId,
        },
      },
    )
    return response.data
  },

  async list(params: {
    skip?: number
    limit?: number
    search?: string
    month?: string
  } = {}): Promise<TopicPage> {
    const response = await api.get<TopicPage>('/topics', {
      params: {
        skip: params.skip ?? 0,
        limit: params.limit ?? 50,
        q: params.search?.trim() || undefined,
        month: params.month,
      },
    })
    return response.data
  },

  async get(id: string): Promise<Topic> {
    const response = await api.get<Topic>(`/topics/${encodeURIComponent(id)}`)
    return response.data
  },

  async content(id: string, limit = 50): Promise<TopicContent> {
    const response = await api.get<TopicContent>(
      `/topics/${encodeURIComponent(id)}/content`,
      { params: { limit } },
    )
    return response.data
  },

  async listKeywords(): Promise<string[]> {
    const response = await api.get<string[]>('/topics/keywords')
    return response.data
  },

  async create(data: TopicInput): Promise<Topic> {
    const response = await api.post<Topic>('/topics', data)
    return response.data
  },

  async update(topic: Topic, data: TopicInput): Promise<Topic> {
    const response = await api.put<Topic>(`/topics/${encodeURIComponent(topic.id)}`, {
      ...data,
      revision: topic.revision,
    })
    return response.data
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/topics/${encodeURIComponent(id)}`)
  },

  async linkedMemories(id: string): Promise<TopicLinkedMemory[]> {
    const response = await api.get<TopicLinkedMemory[]>(
      `/topics/${encodeURIComponent(id)}/memories`,
    )
    return response.data
  },

  async merge(sourceId: string, targetId: string): Promise<TopicMutationResult> {
    const response = await api.post<TopicMutationResult>(
      `/topics/${encodeURIComponent(sourceId)}/merge`,
      { target_topic_id: targetId },
    )
    return response.data
  },

  async split(
    sourceId: string,
    data: TopicInput & { memory_item_ids: string[] },
  ): Promise<TopicMutationResult> {
    const response = await api.post<TopicMutationResult>(
      `/topics/${encodeURIComponent(sourceId)}/split`,
      data,
    )
    return response.data
  },

  async forConversation(connectionId: number, roomId: string): Promise<Topic[]> {
    const response = await api.get<Topic[]>('/topics/conversation', {
      params: { connection_id: connectionId, room_id: roomId },
    })
    return response.data
  },
}
