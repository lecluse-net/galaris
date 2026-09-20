import { ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, api, getStoredAccessToken } from '@/core/api'

/**
 * Confirmed global activation state.
 *
 * `null` means that the backend has not answered yet.  A transient startup or
 * network failure must not hide a navigation item from an otherwise authorized
 * user; only an explicit `{ enabled: false }` response does that.
 */
export const chatAvailable = ref<boolean | null>(null)

export function isChatNavigationVisible(): boolean {
  return chatAvailable.value !== false
}

export async function refreshChatAvailability(): Promise<void> {
  if (!getStoredAccessToken()) {
    chatAvailable.value = null
    return
  }
  try {
    const response = await api.get<{ enabled: boolean }>('/chat/status')
    chatAvailable.value = response.data.enabled
  } catch {
    // Keep the last confirmed value. RBAC independently hides the item when the
    // current role lacks access, while a backend startup race can recover on
    // focus/online without leaving the menu permanently absent.
  }
}

window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, () => void refreshChatAvailability())
window.addEventListener('focus', () => void refreshChatAvailability())
window.addEventListener('online', () => void refreshChatAvailability())
void refreshChatAvailability()
