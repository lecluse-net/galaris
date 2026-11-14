<template>
  <span class="execution-badge" :class="`execution-badge--${state}`" :title="t(`agenda.states.${state}`)">
    <q-icon :name="icons[state]" size="14px" /><span v-if="!compact">{{ t(`agenda.states.${state}`) }}</span>
    <span v-else class="sr-only">{{ t(`agenda.states.${state}`) }}</span><span v-if="count && count > 1">{{ count }}</span>
  </span>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { ExecutionState } from '../services/calendarService'
defineProps<{ state: ExecutionState; compact?: boolean; count?: number }>()
const { t } = useI18n()
const icons: Record<ExecutionState, string> = { scheduled: 'schedule', cancelled: 'block', skipped: 'skip_next', pending: 'hourglass_top', dispatch_error: 'error_outline', queued: 'playlist_play', running: 'autorenew', judging: 'fact_check', waiting: 'hourglass_empty', paused: 'pause_circle', done: 'check_circle', error: 'error', unavailable: 'help_outline' }
</script>
<style scoped>
.execution-badge { --state-color: var(--solaire-gray-accent); display: inline-flex; align-items: center; gap: 4px; font-size: 12px; white-space: nowrap; }
.execution-badge .q-icon { color: var(--state-color); }
.execution-badge--done { --state-color: var(--solaire-green-accent); }
.execution-badge--judging, .execution-badge--running, .execution-badge--queued { --state-color: var(--solaire-blue-accent); }
.execution-badge--error, .execution-badge--dispatch_error { --state-color: var(--solaire-red-accent); }
.execution-badge--waiting, .execution-badge--pending, .execution-badge--paused { --state-color: var(--solaire-orange-accent); }
.execution-badge--scheduled { --state-color: var(--solaire-iris-accent); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
