import api from '@/core/api'

export interface ConnectionTest {
    ok: boolean
    code: string
    message: string
}

export const configurationService = {
    async defaults(): Promise<{ galaris_base_url: string }> {
        return (await api.get<{ galaris_base_url: string }>('/n8n/settings')).data
    },
    async test(): Promise<ConnectionTest> {
        return (await api.post<ConnectionTest>('/n8n/test')).data
    },
}
