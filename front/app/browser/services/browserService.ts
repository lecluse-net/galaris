import { api } from '@/core/api'

export async function fetchBrowserAvailability(): Promise<boolean> {
    const response = await api.get<{ enabled: boolean }>('/browser/status')
    return response.data.enabled
}
