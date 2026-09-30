<template>
  <q-avatar
    :size="size"
    :color="avatarUrl ? undefined : color"
    :text-color="avatarUrl ? undefined : textColor"
    :title="displayName"
    :class="{ 'agent-avatar-fallback': !avatarUrl && !color }"
  >
    <img v-if="avatarUrl" :src="avatarUrl" :alt="displayName" />
    <span v-else class="text-weight-medium">{{ initials }}</span>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { onSessionReadInvalidation } from '@/core/util/facade'
import { useAgentStore } from '../stores/agentStore'
import { agentService } from '../services/agentService'

const {
  agentId,
  name = '',
  size = '36px',
  color,
  textColor,
  hasAvatar,
} = defineProps<{
  agentId: number
  name?: string
  size?: string
  color?: string
  textColor?: string
  hasAvatar?: boolean
}>()

const agentStore = useAgentStore()
const avatarUrl = ref('')
let request: AbortController | undefined
const agent = computed(() => agentStore.agents.find(item => item.id === agentId) ?? null)
const displayName = computed(() => {
  const value = agent.value
    ? `${agent.value.first_name} ${agent.value.last_name}`.trim()
    : name.trim()
  return value || `#${agentId}`
})
const initials = computed(() => {
  const parts = displayName.value.split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  const first = parts[0]?.[0] || ''
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || '' : ''
  return `${first}${last}`.toLocaleUpperCase()
})

const available = computed(() => hasAvatar ?? agent.value?.has_avatar)
watch(
  () => [agentId, hasAvatar ?? agent.value?.has_avatar, agent.value?.avatar_revision] as const,
  () => { void loadAvatar() },
  { immediate: true },
)

function clear(): void {
  request?.abort()
  if (avatarUrl.value) URL.revokeObjectURL(avatarUrl.value)
  avatarUrl.value = ''
}

async function loadAvatar(): Promise<void> {
  clear()
  if (!available.value) return
  const current = new AbortController()
  request = current
  try {
    const url = await agentService.getAvatarBlobUrl(agentId, current.signal, agent.value?.avatar_revision)
    if (current.signal.aborted) URL.revokeObjectURL(url)
    else avatarUrl.value = url
  } catch {
    // Initials remain the stable fallback when an avatar cannot be loaded.
  }
}

const unsubscribe = onSessionReadInvalidation('agent-avatar', key => {
  if (key === undefined || key === String(agentId)) void loadAvatar()
})
function onSessionChanged(event: Event): void {
  clear()
  if ((event as CustomEvent<string | null>).detail) void loadAvatar()
}
window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
onBeforeUnmount(() => {
  clear()
  unsubscribe()
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
})
</script>

<style scoped>
.agent-avatar-fallback { background: var(--solaire-gray-light); color: var(--solaire-gray-accent); }
:global(.body--dark) .agent-avatar-fallback { background: var(--solaire-gray-dark); }
</style>
