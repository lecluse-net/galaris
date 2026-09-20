import { ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken } from '@/core/api'
import { mailService } from './services/mailService'

const mailAvailable = ref(false)

export function isMailNavigationVisible(): boolean {
  return mailAvailable.value
}

export async function refreshMailAvailability(): Promise<void> {
  if (!getStoredAccessToken()) {
    mailAvailable.value = false
    return
  }
  try {
    mailAvailable.value = (await mailService.status()).data.enabled
  } catch {
    // Keep the last confirmed state across transient startup/network failures.
  }
}

window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, () => void refreshMailAvailability())
window.addEventListener('focus', () => void refreshMailAvailability())
window.addEventListener('online', () => void refreshMailAvailability())
void refreshMailAvailability()
