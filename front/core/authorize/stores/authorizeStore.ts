import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { jwtDecode } from 'jwt-decode'
import { useAuthStore } from '@/core/user/stores/authStore'
import { authorizeService, type AssignmentWithRole } from '@/core/authorize/services/authorize.service'
import { sessionGeneration, SupersededSessionError } from '@/core/api'
import { localizedAuthorizeLabel } from '../presentation'

export const useAuthorizeStore = defineStore('authorize', () => {
    const authStore = useAuthStore()
    const activeRole = ref<{ id: number; code: string; display_name?: string } | null>(null)
    const assignments = ref<AssignmentWithRole[]>([])
    const loading = ref(false)

    const roleLabel = computed(() => {
        if (!activeRole.value) return ''
        return localizedAuthorizeLabel(activeRole.value)
    })

    function decodeRoleFromToken(tokenStr: string) {
        try {
            const decoded: any = jwtDecode(tokenStr)
            if (decoded.role_id) {
                activeRole.value = {
                    id: decoded.role_id,
                    code: decoded.role_code,
                    display_name: decoded.role_name
                }
            } else {
                activeRole.value = null
            }
        } catch (e) {
            console.error('Invalid token for role decoding', e)
            activeRole.value = null
        }
    }

    async function fetchAssignments(userId: number) {
        const generation = sessionGeneration()
        try {
            const result = await authorizeService.getUserAssignments(userId)
            if (generation !== sessionGeneration() || authStore.user?.id !== userId) return
            assignments.value = result

            // Auto-switch logic: 
            // 1. If not logged in or already have a role, do nothing.
            // 2. If no role, try to find default assignment
            // 3. Fallback to first assignment
            if (authStore.isAuthenticated && !activeRole.value && assignments.value.length > 0) {
                const defaultAssignment = assignments.value.find((a: any) => a.is_default)
                if (defaultAssignment) {
                    await switchRole(defaultAssignment.role_id)
                } else {
                    await switchRole(assignments.value[0].role_id)
                }
            }
        } catch (e) {
            console.error('Failed to fetch assignments', e)
        }
    }

    async function setDefaultAssignment(assignmentId: number) {
        try {
            await authorizeService.setDefaultAssignment(assignmentId)
            // Update local state
            assignments.value = assignments.value.map(a => ({
                ...a,
                is_default: a.id === assignmentId
            }))
        } catch (e) {
            console.error('Failed to set default assignment', e)
            throw e
        }
    }

    async function switchRole(roleId: number) {
        let generation = sessionGeneration()
        loading.value = true
        try {
            const response = await authorizeService.switchRole(roleId)
            // Update token in authStore (Identity + Context)
            if (generation !== sessionGeneration()) throw new SupersededSessionError()
            const loadingUser = authStore.setToken(response.access_token)
            generation = sessionGeneration()
            await loadingUser
        } catch (err) {
            console.error('Switch role failed', err)
            throw err
        } finally {
            if (generation === sessionGeneration()) loading.value = false
        }
    }

    function init() {
        // Watch for token changes to update active role
        watch(() => authStore.token, (newToken) => {
            if (newToken) {
                decodeRoleFromToken(newToken)
            } else {
                activeRole.value = null
                assignments.value = []
            }
        }, { immediate: true })

        // Watch for user changes to fetch assignments
        watch(() => authStore.user, async (newUser) => {
            if (newUser) {
                await fetchAssignments(newUser.id)
            } else {
                assignments.value = []
            }
        }, { immediate: true })
    }

    return {
        activeRole,
        assignments,
        roleLabel,
        loading,
        switchRole,
        setDefaultAssignment,
        init
    }
})
