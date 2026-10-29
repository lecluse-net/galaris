<template>
  <q-badge class="permission-state" :style="permissionColorStyle(appearance.color)">
    <q-icon :name="appearance.icon" size="16px" />{{ label }}
  </q-badge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { permissionColorStyle, permissionStates } from '../permissionPresentation'
import type { PermissionState } from '../services/permissionDashboard'
const { state, label } = defineProps<{ state: Exclude<PermissionState, 'all'>; label: string }>()
const appearance = computed(() => permissionStates[state])
</script>

<style scoped>
.permission-state { gap: 4px; color: inherit; background: var(--permission-light); border: 1px solid var(--permission-accent); }
.permission-state .q-icon { color: var(--permission-accent); }
body.body--dark .permission-state { background: var(--permission-dark); }
</style>
