import api, {
    clearStoredSession,
    getStoredAccessToken,
    refreshAccessToken,
    saveAccessToken,
    invalidateSessionRequests,
    sessionGeneration,
    SupersededSessionError,
    withSessionLock
} from '@/core/api'
import type { AxiosResponse } from 'axios'

export type DocumentOpenMode = 'split' | 'dialog'

export interface User {
    id: number
    email: string
    display_name: string | null
    is_active: boolean
    language: string | null
    document_open_mode: DocumentOpenMode
    avatar_url: string | null
    created_at: string
}

export interface UserCredentials {
    email: string
    password: string
    otp_code?: string
}

export interface UserRegistration extends UserCredentials {
    display_name?: string
}

export interface UserUpdate {
    email?: string
    display_name?: string
    password?: string
    is_active?: boolean
    language?: string
    document_open_mode?: DocumentOpenMode
}

export interface TokenResponse {
    access_token: string
    token_type: string
}

export interface MfaStatus {
    enabled: boolean
    setup_pending: boolean
    recovery_codes_remaining: number
}

export interface MfaSetup {
    secret: string
    provisioning_uri: string
}

export interface MfaRecoveryCodes {
    recovery_codes: string[]
}

export interface RegistrationStatus {
    registration_open: boolean
    initial_admin_required: boolean
}

export const authService = {
    async getRegistrationStatus(): Promise<RegistrationStatus> {
        const response = await api.get<RegistrationStatus>('/auth/registration-status')
        return response.data
    },

    /**
     * Register a new user.
     */
    async register(userData: UserRegistration): Promise<User> {
        const response: AxiosResponse<User> = await api.post('/auth/register', userData)
        return response.data
    },

    /**
     * Authenticate a user.
     */
    async login(credentials: UserCredentials): Promise<TokenResponse> {
        invalidateSessionRequests()
        const generation = sessionGeneration()
        return withSessionLock(async () => {
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            const response: AxiosResponse<TokenResponse> = await api.post('/auth/login-json', credentials)
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            saveAccessToken(response.data.access_token)
            return response.data
        })
    },

    /**
     * End the current session.
     */
    async logout(): Promise<void> {
        clearStoredSession()
        await withSessionLock(() => api.post('/auth/logout')).then(() => undefined)
    },

    /**
     * Restore a browser/PWA session from its protected refresh cookie.
     */
    async refresh(): Promise<TokenResponse> {
        const accessToken = await refreshAccessToken()
        return { access_token: accessToken, token_type: 'bearer' }
    },

    /**
     * Refresh the session while the application is visible.
     */
    async keepAlive(): Promise<TokenResponse> {
        const response: AxiosResponse<TokenResponse> = await api.post('/auth/keep-alive')
        return response.data
    },

    /**
     * Return the authenticated user.
     */
    async getCurrentUser(): Promise<User> {
        const response: AxiosResponse<User> = await api.get('/auth/me')
        return response.data
    },

    /**
     * Delete the current user account.
     */
    async deleteAccount(): Promise<void> {
        await api.delete('/auth/me')
    },

    /**
     * Update the current user profile.
     */
    async updateProfile(data: UserUpdate): Promise<User> {
        const response: AxiosResponse<User> = await api.put('/auth/me', data)
        return response.data
    },

    async uploadAvatar(file: File): Promise<User> {
        const data = new FormData()
        data.append('file', file)
        const response: AxiosResponse<User> = await api.post('/auth/me/avatar', data)
        return response.data
    },

    async deleteAvatar(): Promise<User> {
        const response: AxiosResponse<User> = await api.delete('/auth/me/avatar')
        return response.data
    },

    async getMfaStatus(): Promise<MfaStatus> {
        const response = await api.get<MfaStatus>('/auth/mfa/status')
        return response.data
    },

    async setupMfa(): Promise<MfaSetup> {
        const response = await api.post<MfaSetup>('/auth/mfa/setup')
        return response.data
    },

    async confirmMfa(code: string): Promise<MfaRecoveryCodes> {
        const response = await api.post<MfaRecoveryCodes>('/auth/mfa/confirm', { code })
        return response.data
    },

    async disableMfa(password: string, code: string): Promise<void> {
        await api.post('/auth/mfa/disable', { password, code })
    },

    async regenerateMfaRecoveryCodes(code: string): Promise<MfaRecoveryCodes> {
        const response = await api.post<MfaRecoveryCodes>('/auth/mfa/recovery-codes', { code })
        return response.data
    },

    /**
     * Store the access token in localStorage.
     */
    saveToken(token: string): void {
        saveAccessToken(token)
    },

    /**
     * Return the access token from localStorage.
     */
    getToken(): string | null {
        return getStoredAccessToken()
    },

    /**
     * Remove browser-visible authentication data.
     */
    clearSession(): void {
        clearStoredSession()
    },

    /**
     * Return whether an access token is stored.
     */
    isAuthenticated(): boolean {
        return !!this.getToken()
    },

    // ==================== Admin Methods ====================

    async getUsers(params: { skip?: number; limit?: number; search?: string; sort_by?: string; descending?: boolean } = {}): Promise<{ items: User[]; total: number }> {
        const response: AxiosResponse<User[]> = await api.get('/auth/users', {
            params: { limit: 50, ...params }
        })
        return { items: response.data, total: Number(response.headers['x-total-count']) }
    },

    async getUser(id: number): Promise<User> {
        const response: AxiosResponse<User> = await api.get(`/auth/users/${id}`)
        return response.data
    },

    async createUser(data: UserRegistration & { is_active?: boolean }): Promise<User> {
        const response: AxiosResponse<User> = await api.post('/auth/users', data)
        return response.data
    },

    async updateUserAdmin(id: number, data: UserUpdate): Promise<User> {
        const response: AxiosResponse<User> = await api.put(`/auth/users/${id}`, data)
        return response.data
    },

    async deleteUser(id: number): Promise<void> {
        await api.delete(`/auth/users/${id}`)
    }
}
