<template>
  <img v-if="icon" :src="source" :alt="label" :width="size" :height="size" class="service-icon" />
  <span v-else-if="fallback.startsWith('img:/menu-icons/')" class="service-menu-icon" role="img"
    :aria-label="label" :aria-hidden="!label || undefined"
    :style="{ width: `${size}px`, height: `${size}px`, '--service-menu-icon': `url(${fallback.slice(4)})` }" />
  <q-icon v-else :name="fallback" :style="{ color: 'var(--solaire-blue-accent)' }" :size="`${size}px`" :aria-label="label" />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { navigationIcon } from '@/core/navigation'
import type { ServiceIcon } from '../services/serviceApi'
const { icon, label = '', size = 28, fallback = navigationIcon('hub') } = defineProps<{ icon?: ServiceIcon | null; label?: string; size?: number; fallback?: string }>()
const source = computed(() => icon ? icon.encoding === 'base64'
  ? `data:${icon.media_type};base64,${icon.data}`
  : `data:${icon.media_type};charset=utf-8,${encodeURIComponent(icon.data)}` : '')
</script>
<style scoped>
.service-icon { object-fit: contain; flex: none; vertical-align: middle; }
.service-menu-icon {
  display: inline-block; flex: none; vertical-align: middle;
  background: var(--solaire-blue-accent);
  mask: var(--service-menu-icon) center / contain no-repeat;
  -webkit-mask: var(--service-menu-icon) center / contain no-repeat;
}
</style>
