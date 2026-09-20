<template>
  <q-avatar :size="size" :title="name" class="user-avatar">
    <img v-if="avatarUrl && !failed" :src="avatarUrl" :alt="name" @error="failed = true" />
    <span v-else>{{ initials }}</span>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const { name, avatarUrl = null, size = '36px' } = defineProps<{
  name: string
  avatarUrl?: string | null
  size?: string
}>()
const failed = ref(false)
const initials = computed(() => {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return `${parts[0]?.[0] ?? '?'}${parts.length > 1 ? parts.at(-1)?.[0] ?? '' : ''}`.toLocaleUpperCase()
})
watch(() => avatarUrl, () => { failed.value = false })
</script>

<style scoped>
.user-avatar { background: var(--solaire-gray-light); color: var(--solaire-gray-accent); font-weight: 600; }
.user-avatar img { object-fit: cover; }
:global(.body--dark) .user-avatar { background: var(--solaire-gray-dark); }
</style>
