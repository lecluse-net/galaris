import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { contactService } from './services/contactService'
import type { Contact } from './types'
import { CONTACT_CHANGED_EVENT } from './contactResource'

/** A live, uncached read: late replies and revoked sessions never revive a card. */
export function useContactResource(identifier: () => string, refreshOnChange = true) {
  const permissions = usePrivilegeStore()
  const canRead = computed(() => permissions.hasAnyPrivilege([privileges.CONTACT_ACCESS, privileges.CONTACT_EDIT]))
  const canEdit = computed(() => permissions.hasPrivilege(privileges.CONTACT_EDIT))
  const contact = ref<Contact | null>(null), loading = ref(false), error = ref(false), revision = ref(0)
  const refresh = (): void => { revision.value++ }
  const changed = (event: Event): void => {
    if (refreshOnChange && (event as CustomEvent<string[]>).detail.includes(identifier())) refresh()
  }
  watch([identifier, revision, canRead], async ([id, , allowed], _, cleanup) => {
    const request = new AbortController()
    cleanup(() => request.abort())
    contact.value = null; error.value = false; loading.value = false
    if (!allowed) { error.value = true; return }
    loading.value = true
    try {
      const value = await contactService.get(id, request.signal)
      if (!request.signal.aborted) contact.value = value
    } catch { if (!request.signal.aborted) error.value = true }
    finally { if (!request.signal.aborted) loading.value = false }
  }, { immediate: true })
  onMounted(() => {
    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, refresh)
    window.addEventListener(CONTACT_CHANGED_EVENT, changed)
  })
  onBeforeUnmount(() => {
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, refresh)
    window.removeEventListener(CONTACT_CHANGED_EVENT, changed)
  })
  return { contact, loading, error, canEdit, refresh }
}
