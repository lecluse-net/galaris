<template>
  <q-avatar
    :size="size"
    :color="avatarUrl ? undefined : color"
    :text-color="avatarUrl ? undefined : textColor"
    :title="displayName"
    :class="{ 'agent-avatar-fallback': !avatarUrl && !color }"
  >
    <img v-if="avatarUrl" :key="avatarUrl" :src="avatarUrl" :alt="displayName" @error="imageFailed" />
    <slot v-else name="fallback"><span class="text-weight-medium">{{ initials }}</span></slot>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { sessionGeneration } from '@/core/api'
import { onReadSessionChanged, onSessionReadInvalidation } from '@/core/util/facade'
import { useAgentStore } from '../stores/agentStore'
import { agentService } from '../services/agentService'

const {
  agentId,
  name = '',
  size = '36px',
  color,
  textColor,
  hasAvatar = undefined,
  updatedAt,
} = defineProps<{
  agentId: number
  name?: string
  size?: string
  color?: string
  textColor?: string
  hasAvatar?: boolean
  updatedAt?: string | null
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
const revision = computed(() => updatedAt ?? agent.value?.updated_at)
let session: string | null = sessionGeneration()
watch(
  [() => agentId, available, revision],
  () => { void loadAvatar() },
  { immediate: true },
)

function clear(): void {
  request?.abort()
  request = undefined
  if (avatarUrl.value) URL.revokeObjectURL(avatarUrl.value)
  avatarUrl.value = ''
}

function imageFailed(event: Event): void {
  if ((event.currentTarget as HTMLImageElement).src === avatarUrl.value) clear()
}

async function loadAvatar(refresh = false): Promise<void> {
  clear()
  if (session === null || !Number.isInteger(agentId) || agentId <= 0) return
  if (!refresh && available.value === false) return
  const current = new AbortController()
  request = current
  try {
    const url = await agentService.getAvatarBlobUrl(agentId, current.signal, revision.value)
    if (current.signal.aborted) {
      if (url) URL.revokeObjectURL(url)
    } else {
      avatarUrl.value = url
    }
  } catch {
    // Initials remain the stable fallback when an avatar cannot be loaded.
  }
}

const unsubscribe = onSessionReadInvalidation('agent-avatar', key => {
  if (key === undefined || key === String(agentId)) void loadAvatar(key !== undefined)
})
const unsubscribeSession = onReadSessionChanged(authenticated => {
  const next = authenticated ? sessionGeneration() : null
  if (next === session) return
  session = next
  void loadAvatar()
})
onBeforeUnmount(() => {
  clear()
  unsubscribe()
  unsubscribeSession()
})
</script>

<style scoped>
.agent-avatar-fallback { background: var(--solaire-gray-light); color: var(--solaire-gray-accent); }
:global(.body--dark) .agent-avatar-fallback { background: var(--solaire-gray-dark); }
</style>
