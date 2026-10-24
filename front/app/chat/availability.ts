import { effectScope, ref, watch } from 'vue'
import { getActivePinia } from 'pinia'
import { AUTH_TOKEN_CHANGED_EVENT, api, getStoredAccessToken } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'

/**
 * Confirmed global activation state.
 *
 * `null` means that the backend has not answered yet.  A transient startup or
 * network failure must not hide a navigation item from an otherwise authorized
 * user; only an explicit `{ enabled: false }` response does that.
 */
export const chatAvailable = ref<boolean | null>(null)
let observing = false
let revision = 0

function observeAccess(): boolean {
  const pinia = getActivePinia()
  if (observing || !pinia) return false
  observing = true
  const store = usePrivilegeStore(pinia)
  // Match the lifetime of the module's window listeners, across Sidebar mounts.
  effectScope(true).run(() => watch(() => [store.loaded, store.hasAnyPrivilege([privileges.CHAT_ACCESS, privileges.MESSAGING_CONFIG_ACCESS, privileges.MESSAGING_CONFIG_EDIT])],
    () => void refreshChatAvailability(), { immediate: true, flush: 'sync' }))
  return true
}

export function isChatNavigationVisible(): boolean {
  observeAccess()
  return chatAvailable.value !== false
}

export async function refreshChatAvailability(): Promise<void> {
  const current = ++revision
  const pinia = getActivePinia()
  const token = getStoredAccessToken()
  if (!pinia || !token || !usePrivilegeStore(pinia).loaded
    || !usePrivilegeStore(pinia).hasAnyPrivilege([privileges.CHAT_ACCESS, privileges.MESSAGING_CONFIG_ACCESS, privileges.MESSAGING_CONFIG_EDIT])) {
    chatAvailable.value = null
    return
  }
  try {
    const response = await api.get<{ enabled: boolean }>('/chat/status')
    if (current === revision && token === getStoredAccessToken()) chatAvailable.value = response.data.enabled
  } catch {
    // Keep the last confirmed value. RBAC independently hides the item when the
    // current role lacks access, while a backend startup race can recover on
    // focus/online without leaving the menu permanently absent.
  }
}

window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, () => {
  revision++
  if (!getStoredAccessToken()) chatAvailable.value = null
  observeAccess()
})
function refreshWhenReady(): void {
  if (!observeAccess()) void refreshChatAvailability()
}
window.addEventListener('focus', refreshWhenReady)
window.addEventListener('online', refreshWhenReady)
