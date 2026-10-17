<template>
  <q-badge v-if="variant !== 'diagram'" rounded :style="{ backgroundColor: solaireCss[color][$q.dark.isActive ? 'dark' : 'light'] }"
    :text-color="$q.dark.isActive ? 'white' : 'dark'" class="q-px-sm q-py-xs">
    {{ label }}
  </q-badge>
  <q-badge v-else class="process-status-badge" :style="{
    '--process-status-accent': solaireCss[color].accent,
    '--process-status-background': solaireCss[color][$q.dark.isActive ? 'dark' : 'light'],
  }" :text-color="$q.dark.isActive ? 'white' : 'dark'">
    <q-icon v-if="status === 'running' || status === 'waiting'" :name="status === 'running' ? 'play_circle' : 'hourglass_top'" size="14px" />
    <span>{{ label }}</span>
  </q-badge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss, type SolaireColor } from '@/core/util'

const props = defineProps<{ status: string; variant?: 'list' | 'diagram' }>()
const { t, te } = useI18n()
const states: Record<string, SolaireColor> = {
  success: 'green', completed: 'green', error: 'red', failed: 'red', running: 'blue',
  waiting: 'orange', cancelling: 'orange', queued: 'cyan', cancelled: 'gray',
}
const color = computed(() => states[props.status] ?? 'gray')
const label = computed(() => { const key = `processes.statuses.${props.status}`; return te(key) ? t(key) : props.status })
</script>

<style scoped>
.process-status-badge { display: inline-flex; align-items: center; gap: 4px; min-height: 20px; padding: 2px 6px; border: 2px solid var(--process-status-accent); border-radius: 10px; background-color: var(--process-status-background); font-size: 12px; font-weight: normal; line-height: 16px; white-space: nowrap; }
.process-status-badge :deep(.q-icon) { color: inherit !important; }
</style>
