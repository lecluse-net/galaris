<template>
  <q-btn dense unelevated no-caps align="left" class="calendar-event" :style="colorStyle"
    :draggable="movable" :aria-label="accessibleLabel" @click.stop="emit('open', event)" @dragstart="drag">
    <div class="event-content">
      <div class="event-heading"><span v-if="!event.all_day" class="event-time">{{ time }}</span><span class="ellipsis">{{ event.summary || t('calendars.untitledEvent') }}</span></div>
      <div class="event-status">
        <q-icon v-if="event.goal_event" name="flag" size="12px" :title="t('goal.agenda.layer')" />
        <q-icon v-if="event.memory_event" name="memory" size="12px" :title="t('agenda.memoryLayer')" />
        <q-icon v-if="event.recurring" name="repeat" size="12px" :title="t('agenda.repeated')" />
        <q-icon v-if="event.sync_state === 'pending' || event.sync_state === 'conflict'" :name="event.sync_state === 'conflict' ? 'sync_problem' : 'cloud_upload'" size="12px" :title="t(`agenda.sync.${event.sync_state}`)" />
        <span v-if="event.memory_event && !compact" class="text-caption">{{ t('agenda.memoryInformational') }}</span>
        <q-spinner v-else-if="!execution" size="12px" :aria-label="t('agenda.statesLoading')" />
        <q-icon v-else-if="execution.failed" name="help_outline" size="13px" :title="t('agenda.statesError')" />
        <template v-else-if="execution.total"><ExecutionBadge v-for="item in stateCounts" :key="item.state" :state="item.state" :count="item.count" :compact="compact" /></template>
        <span v-else-if="!compact" class="text-caption">{{ t('agenda.noTasks') }}</span>
      </div>
    </div>
    <q-tooltip>{{ event.summary }} · {{ event.calendar_label }}<br />{{ event.memory_event ? t('agenda.memoryInformational') : t('agenda.executions', { count: execution?.total ?? 0 }) }}</q-tooltip>
  </q-btn>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss, type SolaireColor } from '@/core/util'
import type { CalendarEvent, CalendarReminder, ExecutionState } from '../services/calendarService'
import ExecutionBadge from './ExecutionBadge.vue'
export interface EventExecutionSummary { items?: CalendarReminder[]; states?: Partial<Record<ExecutionState, number>>; total: number; failed?: boolean }
const props = defineProps<{ event: CalendarEvent; timezone: string; color: SolaireColor; dark: boolean; movable: boolean; compact?: boolean; execution?: EventExecutionSummary }>()
const emit = defineEmits<{ open: [event: CalendarEvent]; drag: [event: CalendarEvent] }>()
const { t, locale } = useI18n()
const colorStyle = computed(() => { const tone = solaireCss[props.color]; return { '--event-bg': props.dark ? tone.dark : tone.light, '--event-accent': tone.accent } })
const time = computed(() => new Intl.DateTimeFormat(locale.value, { timeZone: props.timezone, hour: '2-digit', minute: '2-digit' }).format(new Date(props.event.start)))
const stateCounts = computed(() => {
  const counts = new Map<ExecutionState, number>()
  props.execution?.items?.forEach(item => counts.set(item.state, (counts.get(item.state) ?? 0) + 1))
  Object.entries(props.execution?.states ?? {}).forEach(([state, count]) => counts.set(state as ExecutionState, count))
  return [...counts].map(([state, count]) => ({ state, count }))
})
const accessibleLabel = computed(() => [props.event.summary, props.event.all_day ? t('agenda.allDay') : time.value,
  ...stateCounts.value.map(item => `${t(`agenda.states.${item.state}`)} ${item.count}`)].join(' · '))
function drag(event: DragEvent): void {
  if (!props.movable) { event.preventDefault(); return }
  event.dataTransfer?.setData('application/x-galaris-event', `${props.event.event_id}:${props.event.recurrence_key}`)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
  emit('drag', props.event)
}
</script>
<style scoped>
.calendar-event { background: var(--event-bg); color: inherit; border-left: 3px solid var(--event-accent); width: 100%; min-width: 0; max-width: 100%; }
.event-content { width: 100%; text-align: left; min-width: 0; line-height: 1.3; padding: 2px 4px; }
.event-heading { display: flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; }
.event-time { white-space: nowrap; font-weight: 400; font-size: 11px; }
.event-status { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; min-height: 14px; }
</style>
