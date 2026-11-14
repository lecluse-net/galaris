<template>
  <img v-if="icon" :src="source" :alt="label" :width="size" :height="size" class="service-icon" />
  <q-icon v-else name="apps" color="primary" :size="`${size}px`" :aria-label="label" />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { ServiceIcon } from '../services/serviceApi'
const { icon, label = '', size = 28 } = defineProps<{ icon?: ServiceIcon | null; label?: string; size?: number }>()
const source = computed(() => icon ? icon.encoding === 'base64'
  ? `data:${icon.media_type};base64,${icon.data}`
  : `data:${icon.media_type};charset=utf-8,${encodeURIComponent(icon.data)}` : '')
</script>
<style scoped>
.service-icon { object-fit: contain; flex: none; vertical-align: middle; }
</style>
