import { api } from '@/core/api'
import type {
  DreamOverview,
  DreamReceiptDetail,
  DreamReceiptPage,
  DreamReceiptStatus,
  DreamRuntimeView,
} from '../types'

export const dreamService = {
  async runtime(): Promise<DreamRuntimeView> {
    const response = await api.get<DreamRuntimeView>('/dream/runtime')
    return response.data
  },

  async overview(): Promise<DreamOverview> {
    const response = await api.get<DreamOverview>('/dream/overview')
    return response.data
  },

  async receipts(params: {
    page?: number
    pageSize?: number
    status?: DreamReceiptStatus | null
    active?: boolean
    dateFrom?: string | null
    dateTo?: string | null
    mechanism?: string | null
    search?: string
  }): Promise<DreamReceiptPage> {
    const response = await api.get<DreamReceiptPage>('/dream/receipts', {
      params: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
        status: params.status || undefined,
        active: params.active,
        date_from: params.dateFrom || undefined,
        date_to: params.dateTo || undefined,
        mechanism: params.mechanism || undefined,
        search: params.search?.trim() || undefined,
      },
    })
    return response.data
  },

  async receipt(id: string): Promise<DreamReceiptDetail> {
    const response = await api.get<DreamReceiptDetail>(
      `/dream/receipts/${encodeURIComponent(id)}`,
    )
    return response.data
  },
}
