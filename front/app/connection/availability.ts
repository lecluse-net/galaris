import { effectScope, ref, watch } from 'vue'
import { getActivePinia } from 'pinia'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { mailService } from './services/mailService'

const mailAvailable = ref(false)
let observing = false
let revision = 0

function observeAccess(): boolean {
  const pinia = getActivePinia()
  if (observing || !pinia) return false
  observing = true
  const store = usePrivilegeStore(pinia)
  // Match the lifetime of the module's window listeners, across Sidebar mounts.
  effectScope(true).run(() => watch(() => [store.loaded, store.hasAnyPrivilege([privileges.MAIL_ACCESS, privileges.MAIL_EDIT])],
    () => void refreshMailAvailability(), { immediate: true, flush: 'sync' }))
  return true
}

export function isMailNavigationVisible(): boolean {
  observeAccess()
  return mailAvailable.value
}

export async function refreshMailAvailability(): Promise<void> {
  const current = ++revision
  const pinia = getActivePinia()
  const token = getStoredAccessToken()
  if (!pinia || !token || !usePrivilegeStore(pinia).loaded
    || !usePrivilegeStore(pinia).hasAnyPrivilege([privileges.MAIL_ACCESS, privileges.MAIL_EDIT])) {
    mailAvailable.value = false
    return
  }
  try {
    const response = await mailService.status()
    if (current === revision && token === getStoredAccessToken()) mailAvailable.value = response.data.enabled
  } catch {
    // Keep the last confirmed state across transient startup/network failures.
  }
}

window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, () => {
  revision++
  if (!getStoredAccessToken()) mailAvailable.value = false
  observeAccess()
})
function refreshWhenReady(): void {
  if (!observeAccess()) void refreshMailAvailability()
}
window.addEventListener('focus', refreshWhenReady)
window.addEventListener('online', refreshWhenReady)
