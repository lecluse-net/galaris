<template>
  <q-select v-model="selected" outlined dense clearable use-input emit-value map-options
    :options="options" :label="label" :disable="disable || !canRead" :loading="loading"
    :input-debounce="250" :error="failed" :error-message="t('contacts.loadError')"
    @filter="filter" @popup-show="refresh">
    <template #prepend><q-icon name="person" /></template>
    <template #no-option><q-item><q-item-section>{{ t('contacts.noRows') }}</q-item-section></q-item></template>
  </q-select>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { contactService } from '../services/contactService'
import { CONTACT_CHANGED_EVENT } from '../contactResource'

const props = defineProps<{ agentId: number; label: string; disable?: boolean }>()
const selected = defineModel<string | null>({ required: true })
const { t } = useI18n(), permissions = usePrivilegeStore()
const canRead = computed(() => permissions.hasAnyPrivilege([privileges.CONTACT_ACCESS, privileges.CONTACT_EDIT]))
const options = ref<{ value: string; label: string }[]>([]), query = ref(''), revision = ref(0)
const loading = ref(false), failed = ref(false)
const refresh = (): void => { revision.value++ }
function filter(value: string, update: (callback: () => void) => void): void {
  update(() => { query.value = value })
}
watch([() => props.agentId, selected, canRead, query, revision], async ([agentId, identifier, allowed, search], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  options.value = []; failed.value = false; loading.value = false
  if (!allowed || !agentId) return
  loading.value = true
  try {
    const page = await contactService.list({ agentId, query: search, limit: 50 }, request.signal)
    const choices = page.items.map(contact => ({ value: contact.memory_item_id, label: contact.display_name }))
    if (identifier && !choices.some(option => option.value === identifier)) {
      const current = await contactService.get(identifier, request.signal)
      if (current.owner_agent_id === agentId) choices.unshift({ value: current.memory_item_id, label: current.display_name })
    }
    if (!request.signal.aborted) options.value = choices
  } catch { if (!request.signal.aborted) failed.value = true }
  finally { if (!request.signal.aborted) loading.value = false }
}, { immediate: true })
onMounted(() => {
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, refresh)
  window.addEventListener(CONTACT_CHANGED_EVENT, refresh)
})
onBeforeUnmount(() => {
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, refresh)
  window.removeEventListener(CONTACT_CHANGED_EVENT, refresh)
})
</script>
