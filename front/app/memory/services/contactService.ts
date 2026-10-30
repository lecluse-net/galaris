import { api } from '@/core/api'
import { notifyContactsChanged } from '../contactResource'
import type { Contact, ContactCreate, ContactForgetResult, ContactMergeResult, ContactPage, ContactUpdate } from '../types'

export const contactService = {
  async get(contactItemId: string, signal?: AbortSignal): Promise<Contact> {
    return (await api.get<Contact>(`/contacts/${encodeURIComponent(contactItemId)}`, { signal })).data
  },
  async defaults(): Promise<{ country: string }> {
    return (await api.get<{ country: string }>('/contacts/defaults')).data
  },
  async create(data: ContactCreate): Promise<Contact> {
    const response = await api.post<Contact>('/contacts', data)
    return response.data
  },
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

  async update(contactItemId: string, data: ContactUpdate): Promise<Contact> {
    const response = await api.patch<Contact>(
      `/contacts/${encodeURIComponent(contactItemId)}`, data,
    )
    notifyContactsChanged(contactItemId)
    return response.data
  },

  async merge(sourceContactItemId: string, targetContactItemId: string): Promise<ContactMergeResult> {
    const response = await api.post<ContactMergeResult>(
      `/contacts/${encodeURIComponent(sourceContactItemId)}/merge`,
      { target_contact_item_id: targetContactItemId },
    )
    notifyContactsChanged(sourceContactItemId, targetContactItemId)
    return response.data
  },

  async forget(contactItemId: string): Promise<ContactForgetResult> {
    const response = await api.delete<ContactForgetResult>(
      `/contacts/${encodeURIComponent(contactItemId)}`,
    )
    notifyContactsChanged(contactItemId)
    return response.data
  },
}
