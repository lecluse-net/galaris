import { api } from '@/core/api'
import type { ContactForgetResult, ContactMergeResult, ContactPage } from '../types'

export const contactService = {
  async list(params: {
    agentId: number
    query?: string
    limit?: number
    offset?: number
  }): Promise<ContactPage> {
    const response = await api.get<ContactPage>('/contacts', {
      params: {
        agent_id: params.agentId,
        q: params.query ?? '',
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      },
    })
    return response.data
  },

  async merge(sourceContactItemId: string, targetContactItemId: string): Promise<ContactMergeResult> {
    const response = await api.post<ContactMergeResult>(
      `/contacts/${encodeURIComponent(sourceContactItemId)}/merge`,
      { target_contact_item_id: targetContactItemId },
    )
    return response.data
  },

  async forget(contactItemId: string): Promise<ContactForgetResult> {
    const response = await api.delete<ContactForgetResult>(
      `/contacts/${encodeURIComponent(contactItemId)}`,
    )
    return response.data
  },
}
