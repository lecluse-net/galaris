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
import { computed } from 'vue'
import { useChatAvatar } from '../useChatAvatar'

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

const avatarUrl = useChatAvatar(() => agentId)
const displayName = computed(() => name.trim() || `#${agentId}`)
const initials = computed(() => {
  const parts = displayName.value.split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] || ''
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || '' : ''
  return `${first}${last}`.toLocaleUpperCase() || '?'
})
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
