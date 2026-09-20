import api from '@/core/api'
import type { AxiosResponse } from 'axios'

// ==================== Service ====================

/**
 * Service for managing current user's privileges.
 * Provides methods to fetch and check privileges for the active role.
 */
export const privilegeService = {
    /**
     * Get the list of privilege codes for the current user's active role.
     * Returns an empty array if no role is active or user is not authenticated.
     */
    async getMyPrivileges(): Promise<string[]> {
        const response: AxiosResponse<string[]> = await api.get('/authorize/my-privileges')
        return response.data
    }
}
