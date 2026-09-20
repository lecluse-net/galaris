<template>
  <q-avatar :size="size" class="participant-avatar">
    <img v-if="avatarUrl && !avatarMissing" :src="avatarUrl" :alt="name" @error="avatarMissing = true" />
    <span v-else>{{ initials }}</span>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ name: string; avatarUrl?: string | null; size?: string }>(), { size: '32px', avatarUrl: null })
const avatarMissing = ref(false)
const initials = computed(() => {
  const parts = props.name.trim().split(/\s+/).filter(Boolean)
  return `${parts[0]?.[0] || ''}${parts.length > 1 ? parts.at(-1)?.[0] || '' : ''}`.toLocaleUpperCase() || '?'
})
watch(() => props.avatarUrl, () => { avatarMissing.value = false })
</script>

<style scoped>
.participant-avatar { color: var(--chat-text-secondary, #5b6678); background: var(--chat-surface-soft, #dfe4eb); font-size: .72rem; font-weight: 650; }
.participant-avatar img { width: 100%; height: 100%; object-fit: cover; }
:global(body.body--dark) .participant-avatar { color: #c3ccda; background: #303641; }
</style>
