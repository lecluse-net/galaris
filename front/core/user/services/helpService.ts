import api from '@/core/api'

export const helpService = {
  async listDismissed(): Promise<string[]> {
    const response = await api.get<string[]>('/auth/me/help-dismissals')
    return response.data
  },
  async dismiss(helpKey: string): Promise<void> {
    await api.put(`/auth/me/help-dismissals/${encodeURIComponent(helpKey)}`)
  },
}
