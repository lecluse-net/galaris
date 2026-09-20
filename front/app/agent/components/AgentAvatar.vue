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
import { computed, ref, watch } from 'vue'
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

const avatarCache = new Map<number, string>()
const avatarLoads = new Map<number, Promise<string>>()
const agentStore = useAgentStore()
const avatarUrl = ref(avatarCache.get(agentId) || '')
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

watch(
  () => [agentId, hasAvatar ?? agent.value?.has_avatar] as const,
  ([id, hasAvatar]) => {
    avatarUrl.value = avatarCache.get(id) || ''
    if (hasAvatar && !avatarUrl.value) void loadAvatar(id)
  },
  { immediate: true },
)

async function loadAvatar(id: number): Promise<void> {
  let pending = avatarLoads.get(id)
  if (!pending) {
    pending = agentService.getAvatarBlobUrl(id)
    avatarLoads.set(id, pending)
  }
  try {
    const url = await pending
    avatarCache.set(id, url)
    if (agentId === id) avatarUrl.value = url
  } catch {
    // Initials remain the stable fallback when an avatar cannot be loaded.
  } finally {
    avatarLoads.delete(id)
  }
}
</script>

<style scoped>
.agent-avatar-fallback { background: var(--solaire-gray-light); color: var(--solaire-gray-accent); }
:global(.body--dark) .agent-avatar-fallback { background: var(--solaire-gray-dark); }
</style>
