import api from '@/core/api'
import type { AxiosResponse } from 'axios'
import type { User } from './authService'

export const userService = {
    async listUsers(search?: string): Promise<User[]> {
        const params: Record<string, string | number> = { limit: 500 }
        if (search) {
            params.search = search
        }
        const response: AxiosResponse<User[]> = await api.get('/auth/users', { params })
        return response.data
    }
}
