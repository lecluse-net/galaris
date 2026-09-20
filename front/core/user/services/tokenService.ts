import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface UserToken {
    id: number
    user_id: number
    label: string | null
    token: string
    enabled: boolean
    created_at: string
}

export interface UserTokenCreate {
    label?: string
    enabled?: boolean
}

export interface UserTokenUpdate {
    label?: string
    enabled?: boolean
}

export const tokenService = {
    async listTokens(): Promise<UserToken[]> {
        const response: AxiosResponse<UserToken[]> = await api.get('/auth/me/tokens')
        return response.data
    },

    async createToken(data: UserTokenCreate = {}): Promise<UserToken> {
        const response: AxiosResponse<UserToken> = await api.post('/auth/me/tokens', data)
        return response.data
    },

    async updateToken(tokenId: number, data: UserTokenUpdate): Promise<UserToken> {
        const response: AxiosResponse<UserToken> = await api.put(`/auth/me/tokens/${tokenId}`, data)
        return response.data
    },

    async deleteToken(tokenId: number): Promise<void> {
        await api.delete(`/auth/me/tokens/${tokenId}`)
    }
}
