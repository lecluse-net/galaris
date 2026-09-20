<template>
  <q-avatar
    :size="size"
    :color="avatarUrl ? undefined : color"
    :text-color="avatarUrl ? undefined : textColor"
    :title="displayName"
    class="internal-agent-avatar"
  >
    <img v-if="avatarUrl" :src="avatarUrl" :alt="displayName" />
    <span v-else class="text-weight-medium">{{ initials }}</span>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { chatService } from '../services/chatService'

const {
  agentId,
  name = '',
  size = '36px',
  color = 'blue-grey-2',
  textColor = 'blue-grey-9',
} = defineProps<{
  agentId: number
  name?: string
  size?: string
  color?: string
  textColor?: string
}>()

const avatarCache = new Map<number, string>()
const avatarLoads = new Map<number, Promise<string>>()
const avatarMisses = new Set<number>()
const avatarUrl = ref(avatarCache.get(agentId) || '')
const displayName = computed(() => name.trim() || `#${agentId}`)
const initials = computed(() => {
  const parts = displayName.value.split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] || ''
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || '' : ''
  return `${first}${last}`.toLocaleUpperCase() || '?'
})

watch(
  () => agentId,
  id => {
    avatarUrl.value = avatarCache.get(id) || ''
    if (!avatarUrl.value && !avatarMisses.has(id)) void loadAvatar(id)
  },
  { immediate: true },
)

async function loadAvatar(id: number): Promise<void> {
  let pending = avatarLoads.get(id)
  if (!pending) {
    pending = chatService.agentAvatarBlob(id).then(blob => URL.createObjectURL(blob))
    avatarLoads.set(id, pending)
  }
  try {
    const url = await pending
    avatarCache.set(id, url)
    if (agentId === id) avatarUrl.value = url
  } catch {
    avatarMisses.add(id)
  } finally {
    avatarLoads.delete(id)
  }
}
</script>

<style scoped>
.internal-agent-avatar {
  flex: 0 0 auto;
  box-shadow: 0 2px 8px var(--chat-shadow, rgba(31, 45, 61, 0.14));
}

:global(body.body--dark) .internal-agent-avatar {
  color: #c9d5ec !important;
  background: #2b3445 !important;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
}
</style>
