import { defineStore } from 'pinia'
import { ref, computed, onScopeDispose } from 'vue'
import { authService, type User, type UserCredentials, type UserRegistration, type UserUpdate, type TokenResponse } from '../services/authService'
import type { AxiosError } from 'axios'
import { applyUserLocale, i18n, setLocale, type AppLocale } from '@/core/i18n'
import { apiErrorDetail, AUTH_TOKEN_CHANGED_EVENT, runBeforeLogoutHooks, sessionGeneration, SupersededSessionError } from '@/core/api'

interface ApiErrorResponse {
    detail?: string | {
        code?: string
        message?: string
    }
}

export const useAuthStore = defineStore('auth', () => {
    // State
    const user = ref<User | null>(null)
    const token = ref<string | null>(null)

    const loading = ref(false)
    const error = ref<string | null>(null)
    const mfaRequired = ref(false)
    let authOperation = 0
    let observedGeneration = sessionGeneration()
    // Getters
    const isAuthenticated = computed(() => !!token.value && !!user.value)
    const userEmail = computed(() => user.value?.email ?? '')
    const userDisplayName = computed(() => user.value?.display_name || user.value?.email)

    /**
     * Set token directly (used by other modules like Authorize)
     */
    async function setToken(newToken: string): Promise<void> {
        authService.saveToken(newToken)
        token.value = newToken
        await fetchCurrentUser()
    }

    function redirectToGuestHome(): void {
        if (window.location.pathname === '/') return
        window.location.href = '/'
    }

    function clearLocalSession(redirect = false): void {
        user.value = null
        token.value = null
        authService.clearSession()
        error.value = null
        if (redirect) redirectToGuestHome()
    }

    function synchronizeToken(event: Event): void {
        const nextToken = (event as CustomEvent<string | null>).detail
        token.value = nextToken
        if (observedGeneration !== sessionGeneration()) user.value = null
        observedGeneration = sessionGeneration()
        if (!nextToken) {
            user.value = null
        }
    }

    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronizeToken)
    function synchronizeBrowserSession(event: StorageEvent): void {
        if (event.key !== null && !['access_token', 'galaris:session-generation'].includes(event.key)) return
        if (observedGeneration !== sessionGeneration()) {
            authOperation += 1
            observedGeneration = sessionGeneration()
            user.value = null
            token.value = null
            loading.value = false
            error.value = null
            mfaRequired.value = false
        }
        if (event.key === 'access_token' || event.key === null) {
            token.value = authService.getToken()
            if (token.value) void fetchCurrentUser()
            else user.value = null
        }
    }
    window.addEventListener('storage', synchronizeBrowserSession)
    onScopeDispose(() => {
        window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronizeToken)
        window.removeEventListener('storage', synchronizeBrowserSession)
    })

    /**
     * Restore the persistent browser/PWA session, with a legacy token fallback.
     */
    async function initializeAuth(): Promise<void> {
        const generation = sessionGeneration()
        const savedToken = authService.getToken()
        const savedUser = localStorage.getItem('user')
        if (savedUser) {
            try {
                user.value = JSON.parse(savedUser) as User
                applyUserLocale(user.value.language)
            } catch {
                localStorage.removeItem('user')
            }
        }

        try {
            const response = await authService.refresh()
            if (generation !== sessionGeneration()) return
            token.value = response.access_token
            await fetchCurrentUser()
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) return
            // Existing installations initially have no refresh cookie. Keep a
            // still-valid legacy access token long enough to create one at login.
            if (!savedToken) return
            token.value = savedToken
            await fetchCurrentUser()
        }
    }

    /**
     * Register a new user.
     */
    async function register(userData: UserRegistration): Promise<User> {
        const generation = sessionGeneration()
        loading.value = true
        error.value = null
        try {
            const response = await authService.register(userData)
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            // Log in automatically after registration.
            await login({
                email: userData.email,
                password: userData.password
            })
            return response
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) throw err
            void (err as AxiosError<ApiErrorResponse>)
            error.value = i18n.global.t('auth.registerError')
            throw error.value
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    /**
     * Authenticate a user.
     */
    async function login(credentials: UserCredentials): Promise<TokenResponse> {
        const operation = ++authOperation
        loading.value = true
        error.value = null
        try {
            const response = await authService.login(credentials)
            if (operation !== authOperation) throw new SupersededSessionError()
            token.value = response.access_token
            await fetchCurrentUser({ required: true })
            if (operation !== authOperation) throw new SupersededSessionError()
            mfaRequired.value = false
            return response
        } catch (err) {
            if (operation !== authOperation || err instanceof SupersededSessionError) throw err
            const detail = (err as AxiosError<ApiErrorResponse>).response?.data?.detail
            const code = typeof detail === 'object' ? detail.code : undefined
            mfaRequired.value = code === 'mfa_required' || code === 'invalid_mfa_code'
            error.value = (
                typeof detail === 'object' && detail.message
                    ? detail.message
                    : apiErrorDetail(err) || i18n.global.t('auth.loginError')
            )
            throw error.value
        } finally {
            if (operation === authOperation) loading.value = false
        }
    }

    /**
     * End the current session.
     */
    async function logout(): Promise<void> {
        authOperation += 1
        loading.value = true
        const cleanup = runBeforeLogoutHooks()
        const revocation = authService.logout()
        const generation = sessionGeneration()
        try {
            await Promise.all([cleanup, revocation])
        } catch (err) {
            console.error('Logout failed:', err)
        } finally {
            if (generation === sessionGeneration()) {
                clearLocalSession(true)
                loading.value = false
            }
        }
    }

    /**
     * Load the current user.
     */
    async function fetchCurrentUser({ required = false }: { required?: boolean } = {}): Promise<void> {
        if (!token.value) return

        const generation = sessionGeneration()
        loading.value = true
        try {
            const userData = await authService.getCurrentUser()
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            user.value = userData
            localStorage.setItem('user', JSON.stringify(userData))
            // Apply the profile locale, falling back to the browser and then English.
            applyUserLocale(userData.language)
        } catch (err) {
            // An explicit login is complete only once identity has loaded. Keep
            // its form open on failure; background restoration remains best effort.
            if (required) throw err
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) return
            console.error('Unable to load the current user:', err)
            if ((err as AxiosError).response?.status === 401) {
                clearLocalSession(true)
            }
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    /**
     * Delete the current account.
     */
    async function deleteAccount(): Promise<void> {
        const generation = sessionGeneration()
        loading.value = true
        error.value = null
        try {
            await authService.deleteAccount()
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            await logout()
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) throw err
            void (err as AxiosError<ApiErrorResponse>)
            error.value = i18n.global.t('user.profile.accountDeleteError')
            throw error.value
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    /**
     * Update the current user profile.
     */
    async function updateProfile(profileData: UserUpdate): Promise<User> {
        const generation = sessionGeneration()
        loading.value = true
        error.value = null
        try {
            const updatedUser = await authService.updateProfile(profileData)
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            user.value = updatedUser
            localStorage.setItem('user', JSON.stringify(updatedUser))
            return updatedUser
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) throw err
            void (err as AxiosError<ApiErrorResponse>)
            error.value = i18n.global.t('user.profile.updateError')
            throw error.value
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    async function uploadAvatar(file: File): Promise<User> {
        const generation = sessionGeneration()
        loading.value = true
        error.value = null
        try {
            const updatedUser = await authService.uploadAvatar(file)
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            user.value = updatedUser
            localStorage.setItem('user', JSON.stringify(updatedUser))
            return updatedUser
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) throw err
            void (err as AxiosError<ApiErrorResponse>)
            error.value = i18n.global.t('user.profile.avatarUploadError')
            throw error.value
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    async function deleteAvatar(): Promise<User> {
        const generation = sessionGeneration()
        loading.value = true
        error.value = null
        try {
            const updatedUser = await authService.deleteAvatar()
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            user.value = updatedUser
            localStorage.setItem('user', JSON.stringify(updatedUser))
            return updatedUser
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) throw err
            void (err as AxiosError<ApiErrorResponse>)
            error.value = i18n.global.t('user.profile.avatarDeleteError')
            throw error.value
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    /**
     * Apply the user's language immediately and persist it to the profile.
     */
    async function setLanguage(locale: AppLocale): Promise<void> {
        const generation = sessionGeneration()
        setLocale(locale)
        try {
            const updatedUser = await authService.updateProfile({ language: locale })
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            user.value = updatedUser
            localStorage.setItem('user', JSON.stringify(updatedUser))
        } catch (err) {
            if (generation !== sessionGeneration() || err instanceof SupersededSessionError) return
            console.error('Unable to save the user language:', err)
        }
    }

    return {
        // State
        user,
        token,
        loading,
        error,
        mfaRequired,
        // Getters
        isAuthenticated,
        userEmail,
        userDisplayName,
        // Actions
        initializeAuth,
        register,
        login,
        logout,
        fetchCurrentUser,
        deleteAccount,
        updateProfile,
        uploadAvatar,
        deleteAvatar,
        setToken,
        setLanguage,
        clearLocalSession
    }
})
