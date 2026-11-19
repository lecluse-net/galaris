<template>
  <q-item-section v-if="badges.length" side class="menu-badges">
    <q-badge
      v-for="badge in badges"
      :key="badge.key"
      :color="badge.tone === 'warning' ? undefined : 'secondary'"
      :class="{ 'menu-badge--warning': badge.tone === 'warning' }"
      :aria-label="badge.label && $t(badge.label.key, badge.label.params ?? {})"
    >
      {{ badge.text }}
      <q-tooltip v-if="badge.label">{{ $t(badge.label.key, badge.label.params ?? {}) }}</q-tooltip>
    </q-badge>
  </q-item-section>
</template>

<script setup lang="ts">
import type { NavigationBadge } from '../types'

defineProps<{ badges: NavigationBadge[] }>()
</script>

<style scoped>
.menu-badges { flex-direction: row; align-items: center; gap: 4px; padding-left: 8px; }
.menu-badge--warning { background: var(--solaire-orange-accent); color: var(--solaire-orange-dark); }
</style>
