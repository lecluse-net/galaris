import { computed, onScopeDispose, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@/core/user'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CONNECTIONS_CHANGED_EVENT } from '@/app/connection'
import { fetchBrowserAvailability } from '../services/browserService'

export const useBrowserSettingsStore = defineStore('browserSettings', () => {
    const auth = useAuthStore()
    const access = usePrivilegeStore()
    const canAccess = computed(() => access.hasPrivilege(privileges.PARAMS_ACCESS)
        || access.hasPrivilege(privileges.PARAMS_EDIT))
    const available = ref<boolean | null>(null)
    const loading = ref(false)
    const failed = ref(false)
    let generation = 0

    async function refresh(): Promise<void> {
        const request = ++generation
        if (!auth.token || !canAccess.value) {
            available.value = null
            loading.value = false
            failed.value = false
            return
        }
        loading.value = true
        failed.value = false
        try {
            const enabled = await fetchBrowserAvailability()
            if (request === generation) available.value = enabled
        } catch {
            if (request === generation) {
                available.value = null
                failed.value = true
            }
        } finally {
            if (request === generation) loading.value = false
        }
    }

    watch([() => auth.token, canAccess], () => {
        available.value = null
        void refresh()
    }, { immediate: true })
    const onRefresh = () => { void refresh() }
    for (const event of ['focus', 'online', CONNECTIONS_CHANGED_EVENT]) {
        window.addEventListener(event, onRefresh)
    }
    onScopeDispose(() => {
        generation++
        for (const event of ['focus', 'online', CONNECTIONS_CHANGED_EVENT]) {
            window.removeEventListener(event, onRefresh)
        }
    })
    return { available, loading, failed, canAccess, refresh }
})
