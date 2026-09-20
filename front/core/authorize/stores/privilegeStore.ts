import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { privilegeService } from '@/core/authorize/services/privilege.service'
import { useAuthStore } from '@/core/user/stores/authStore'
import { useAuthorizeStore } from '@/core/authorize/stores/authorizeStore'

/**
 * Store for managing current user's privileges.
 *
 * Features:
 * - Lazy loading: Privileges are loaded only when needed (hasPrivilege called)
 * - Auto-refresh: Privileges are cleared and reloaded when:
 *   - User logs in/out
 *   - User switches role
 * - Reactive: Components using hasPrivilege() will react to privilege changes
 */
export const usePrivilegeStore = defineStore('privilege', () => {
    const authStore = useAuthStore()
    const authorizeStore = useAuthorizeStore()

    // State
    const privileges = ref<string[]>([])
    const loaded = ref(false)
    const loading = ref(false)
    let attempted = false
    let revision = 0
    let pending: Promise<void> | null = null
    let initialized = false

    // Getters
    /**
     * Check if the user has a specific privilege.
     * Triggers lazy loading if privileges haven't been loaded yet.
     */
    const hasPrivilege = computed(() => {
        return (privilegeCode: string): boolean => {
            // Ensure privileges are loaded before checking
            if (!attempted && !loaded.value && !loading.value && authStore.isAuthenticated) {
                // Trigger async load (don't await, let it happen in background)
                loadPrivileges()
            }
            return allPrivileges.value.includes(privilegeCode)
        }
    })

    /**
     * Get all privilege codes for the current role,
     * including implicit "user" or "guest".
     */
    const allPrivileges = computed(() => {
        const result = [...privileges.value]
        if (authStore.isAuthenticated) {
            result.push('user')
        } else {
            result.push('guest')
        }
        return result
    })

    /**
     * Check if privileges have been loaded.
     */
    const isLoaded = computed(() => loaded.value)

    /**
     * Check if privileges are currently being loaded.
     */
    const isLoading = computed(() => loading.value)

    // Actions
    /**
     * Load privileges from the server.
     * This is called automatically when hasPrivilege is used and data isn't loaded.
     */
    async function loadPrivileges(): Promise<void> {
        if (!authStore.isAuthenticated) {
            privileges.value = []
            loaded.value = false
            return
        }

        if (pending) return pending
        const requestRevision = revision
        attempted = true
        loading.value = true
        pending = (async () => {
            try {
                const data = await privilegeService.getMyPrivileges()
                if (requestRevision !== revision) return
                privileges.value = data
                loaded.value = true
            } catch (e) {
                if (requestRevision !== revision) return
                console.error('Failed to load privileges', e)
                privileges.value = []
                loaded.value = false
            } finally {
                if (requestRevision === revision) {
                    loading.value = false
                    pending = null
                }
            }
        })()
        return pending
    }

    /**
     * Clear privileges from memory.
     * Called automatically on logout or when we need to force a refresh.
     */
    function clearPrivileges(): void {
        revision += 1
        pending = null
        attempted = false
        privileges.value = []
        loaded.value = false
        loading.value = false
    }

    /**
     * Force a refresh of privileges from the server.
     */
    async function refreshPrivileges(): Promise<void> {
        clearPrivileges()
        await loadPrivileges()
    }

    /**
     * Initialize watchers for auto-refresh.
     * Should be called once when the app starts.
     */
    function init(): void {
        if (initialized) return
        initialized = true
        // Invalidate the previous request before loading a new identity/role.
        watch(
            [() => authStore.isAuthenticated, () => authStore.user?.id, () => authorizeStore.activeRole?.id],
            () => {
                clearPrivileges()
                if (authStore.isAuthenticated) void loadPrivileges()
            },
            { immediate: true }
        )
    }

    return {
        // State (read-only)
        privileges: allPrivileges,
        loaded: isLoaded,
        loading: isLoading,
        // Getters
        hasPrivilege,
        // Actions
        loadPrivileges,
        clearPrivileges,
        refreshPrivileges,
        init
    }
})
