<template>
  <section ref="board" class="calendar-board" :aria-label="t(`agenda.views.${view}`)">
    <template v-if="view === 'month'">
      <div class="month-weekdays"><div>{{ t('agenda.weekNumberHeader') }}</div><div v-for="day in days.slice(0, 7)" :key="day">{{ label(day, { weekday: 'short' }) }}</div></div>
      <div class="month-grid">
        <template v-for="(day, index) in days" :key="day">
        <div v-if="index % 7 === 0" class="month-week-number" :aria-label="t('agenda.weekNumber', { week: isoWeekNumber(day) })">{{ isoWeekNumber(day) }}</div>
        <div class="month-cell" :class="{ 'outside-month': day.slice(0, 7) !== date.slice(0, 7), 'is-today': day === today, 'can-create': canCreate }"
          role="group" :aria-label="`${t('agenda.create')} · ${label(day, { dateStyle: 'full' })}`" :tabindex="canCreate ? 0 : undefined"
          @click="createDay($event, day)" @keydown.enter.self.prevent="createDay($event, day)" @keydown.space.self.prevent="createDay($event, day)"
          @dragover.prevent @drop.prevent="drop($event, day)">
          <div class="day-heading"><q-btn flat round dense color="primary" :label="String(Number(day.slice(8)))" :aria-label="label(day, { dateStyle: 'full' })" @click.stop="emit('day', day)" /></div>
          <div class="month-events"><CalendarEventChip v-for="event in byDay(day).slice(0, 3)" :key="occurrenceKey(event)" v-bind="chipProps(event)" compact @open="emit('open', $event)" />
            <q-btn v-if="byDay(day).length > 3" outline dense no-caps color="primary" :label="t('agenda.more', { count: byDay(day).length - 3 })" @click.stop="emit('day', day)" /></div>
        </div>
        </template>
      </div>
    </template>
    <template v-else-if="view === 'week' || view === 'day'">
      <div class="time-grid-header" :style="gridStyle"><div aria-hidden="true" /><div v-for="day in days" :key="day" :class="{ 'is-today': day === today }"><q-btn flat no-caps color="primary" :label="label(day, { weekday: 'short', day: 'numeric' })" @click="emit('day', day)" /></div></div>
      <div class="all-day-grid" :style="gridStyle"><div class="text-caption q-pa-xs">{{ t('agenda.allDay') }}</div>
        <div v-for="day in days" :key="day" class="all-day-cell" :class="{ 'can-create': canCreate }" role="group"
          :aria-label="`${t('agenda.create')} · ${t('agenda.allDay')} · ${day}`" :tabindex="canCreate ? 0 : undefined"
          @click="createDay($event, day)" @keydown.enter.self.prevent="createDay($event, day)" @keydown.space.self.prevent="createDay($event, day)"
          @dragover.prevent @drop.prevent="drop($event, day)">
          <CalendarEventChip v-for="event in byDay(day).filter(event => event.all_day)" :key="occurrenceKey(event)" v-bind="chipProps(event)" compact @open="emit('open', $event)" />
        </div>
      </div>
      <div ref="timeScroll" class="time-scroll">
        <div class="time-columns" :style="gridStyle"><div class="hour-labels"><span v-for="hour in 24" :key="hour" :style="{ top: `${(hour - 1) * 60}px` }">{{ String(hour - 1).padStart(2, '0') }}:00</span></div>
          <div v-for="day in days" :key="day" class="time-day" @dragover.prevent @drop.prevent="drop($event, day, dropTime($event))"
            @pointerdown="startSelection($event, day)" @pointermove="updateSelection" @pointerup="finishSelection" @pointercancel="cancelPointerSelection" @lostpointercapture="cancelPointerSelection">
            <div v-for="hour in 24" :key="hour" class="hour-slot"><q-btn v-if="canCreate" flat no-caps class="create-slot" :aria-label="`${t('agenda.create')} · ${day} ${clockTime((hour - 1) * 60)}`" @click="activateSlot($event, day, (hour - 1) * 60)" /></div>
            <CalendarEventChip v-for="row in positions(day)" :key="occurrenceKey(row.event)" v-bind="chipProps(row.event)" compact class="timed-event"
              :style="{ top: `${row.top}px`, '--event-height': `${row.height}px`, '--event-width': `calc(${row.span * 100 / row.columns}% - 3px)`, '--event-left': `${row.column * 100 / row.columns}%` }" @open="emit('open', $event)" />
            <div v-if="day === today" class="now-line" :style="{ top: `${nowMinutes}px` }" />
            <div v-if="selection?.day === day && selectedRange" class="slot-selection" role="status" aria-live="polite" :style="{ top: `${selectedRange.start}px`, height: `${selectedRange.end - selectedRange.start}px` }">{{ clockTime(selectedRange.start) }} – {{ clockTime(selectedRange.end) }}</div>
          </div>
        </div>
      </div>
    </template>
    <template v-else>
      <div v-if="!events.length" class="empty-schedule"><q-icon name="event_available" size="44px" /><p>{{ t('agenda.noEvents') }}</p></div>
      <template v-for="day in days" :key="day"><section v-if="byDay(day).length" class="schedule-day">
        <q-btn outline no-caps color="primary" class="schedule-date" :label="label(day, { weekday: 'short', day: 'numeric', month: 'short' })" @click="emit('day', day)" />
        <div class="schedule-events"><CalendarEventChip v-for="event in byDay(day)" :key="occurrenceKey(event)" v-bind="chipProps(event)" @open="emit('open', $event)" /></div>
      </section></template>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { SolaireColor } from '@/core/util'
import { defaultCalendarColor } from '../presentation'
import type { CalendarEvent, CalendarFeed } from '../services/calendarService'
import { eventOnDay, isoWeekNumber, occurrenceKey, positionEvents, wallTime, type CalendarView } from '../calendarDates'
import CalendarEventChip, { type EventExecutionSummary } from './CalendarEventChip.vue'
const props = defineProps<{ view: CalendarView; days: string[]; date: string; timezone: string; events: CalendarEvent[]; feeds: CalendarFeed[]; colors?: Record<number, SolaireColor>; executions: Record<string, EventExecutionSummary>; canCreate: boolean; canEdit: boolean }>()
const emit = defineEmits<{ open: [event: CalendarEvent]; day: [day: string]; create: [day: string, time?: string, endTime?: string]; move: [event: CalendarEvent, day: string, time?: string] }>()
const { t, locale } = useI18n(), $q = useQuasar()
const timeScroll = ref<HTMLElement | null>(null), now = ref(new Date())
const today = computed(() => wallTime(now.value, props.timezone).slice(0, 10))
const nowMinutes = computed(() => { const wall = wallTime(now.value, props.timezone); return Number(wall.slice(11, 13)) * 60 + Number(wall.slice(14)) })
const gridStyle = computed(() => ({ gridTemplateColumns: `58px repeat(${props.days.length}, minmax(0, 1fr))` }))
const daysMap = computed(() => new Map(props.days.map(day => [day, props.events.filter(event => eventOnDay(event, day, props.timezone))])))
const positionsMap = computed(() => new Map(props.days.map(day => [day, positionEvents(props.events, day, props.timezone)])))
function byDay(day: string): CalendarEvent[] { return daysMap.value.get(day) ?? [] }
function positions(day: string) { return positionsMap.value.get(day) ?? [] }
function label(day: string, options: Intl.DateTimeFormatOptions): string { return new Intl.DateTimeFormat(locale.value, { timeZone: 'UTC', ...options }).format(new Date(`${day}T12:00:00Z`)) }
function chipProps(event: CalendarEvent) { return { event, timezone: props.timezone, color: props.colors?.[event.calendar_id] ?? defaultCalendarColor(event.calendar_id, Math.max(0, props.feeds.findIndex(feed => feed.id === event.calendar_id))), dark: $q.dark.isActive, movable: !event.goal_event && !event.memory_event && props.canEdit && Boolean(props.feeds.find(feed => feed.id === event.calendar_id)?.writable) && event.sync_state !== 'conflict', execution: props.executions[occurrenceKey(event)] } }
function createDay(event: MouseEvent | KeyboardEvent, day: string): void {
  if (props.canCreate && !(event.target as HTMLElement).closest('button, a, input, [role="button"]')) emit('create', day)
}
const clockTime = (minutes: number): string => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
interface SlotSelection { day: string; anchor: number; focus: number; pointer: number; column: HTMLElement }
const selection = ref<SlotSelection | null>(null)
const selectedRange = computed(() => selection.value ? { start: Math.min(selection.value.anchor, selection.value.focus), end: Math.max(selection.value.anchor + (selection.value.anchor === selection.value.focus ? 60 : 0), selection.value.focus) } : null)
function selectionHour(event: PointerEvent, column: HTMLElement): number { return Math.min(1380, Math.max(0, Math.floor((event.clientY - column.getBoundingClientRect().top) / 60) * 60)) }
function startSelection(event: PointerEvent, day: string): void {
  if (!props.canCreate || event.button !== 0 || !event.isPrimary || (event.target as HTMLElement).closest('.calendar-event')) return
  cancelSelection()
  const column = event.currentTarget as HTMLElement, hour = selectionHour(event, column)
  selection.value = { day, anchor: hour, focus: hour, pointer: event.pointerId, column }
  column.setPointerCapture(event.pointerId)
  if (event.pointerType !== 'touch') event.preventDefault()
}
function updateSelection(event: PointerEvent): void {
  if (selection.value?.pointer === event.pointerId) selection.value.focus = selectionHour(event, selection.value.column)
}
function finishSelection(event: PointerEvent): void {
  const current = selection.value
  if (!current || current.pointer !== event.pointerId) return
  const bounds = current.column.getBoundingClientRect()
  updateSelection(event)
  const range = selectedRange.value
  cancelSelection()
  if (range && props.canCreate && event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom) emit('create', current.day, clockTime(range.start), clockTime(range.end))
}
function cancelSelection(): void {
  const current = selection.value
  selection.value = null
  if (current?.column.hasPointerCapture(current.pointer)) current.column.releasePointerCapture(current.pointer)
}
function cancelPointerSelection(event: PointerEvent): void { if (selection.value?.pointer === event.pointerId) cancelSelection() }
function activateSlot(event: Event, day: string, hour: number): void {
  // Pointer gestures finish on pointerup; keyboard activation still creates a one-hour slot.
  if (event instanceof MouseEvent && event.detail === 0 && props.canCreate) emit('create', day, clockTime(hour), clockTime(hour + 60))
}
function cancelOnEscape(event: KeyboardEvent): void { if (event.key === 'Escape' && selection.value) { event.preventDefault(); cancelSelection() } }
watch(() => [props.view, props.date, props.timezone, props.canCreate], cancelSelection)
function drop(event: DragEvent, day: string, time?: string): void {
  const identity = event.dataTransfer?.getData('application/x-galaris-event')
  const source = props.events.find(item => occurrenceKey(item) === identity)
  if (source && chipProps(source).movable) emit('move', source, day, time)
}
function dropTime(event: DragEvent): string {
  const minutes = Math.min(1425, Math.max(0, Math.round((event.clientY - (event.currentTarget as HTMLElement).getBoundingClientRect().top) / 15) * 15))
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}
watch(() => props.view, async () => { await nextTick(); if (timeScroll.value) timeScroll.value.scrollTop = 7 * 60 }, { immediate: true })
let clock: ReturnType<typeof setInterval> | undefined
onMounted(() => { clock = setInterval(() => { now.value = new Date() }, 60_000); window.addEventListener('keydown', cancelOnEscape); window.addEventListener('blur', cancelSelection) })
onBeforeUnmount(() => { clearInterval(clock); cancelSelection(); window.removeEventListener('keydown', cancelOnEscape); window.removeEventListener('blur', cancelSelection) })
</script>
<style scoped>
.calendar-board { border: 1px solid var(--q-separator-color, rgba(0,0,0,.12)); border-radius: 8px; overflow: hidden; background: #fff; }
.body--dark .calendar-board { background: var(--q-dark, var(--solaire-gray-dark)); }
.month-weekdays, .month-grid { display: grid; grid-template-columns: 30px repeat(7, minmax(0, 1fr)); }
.month-weekdays { text-align: center; padding: 10px 0; font-size: 12px; }
.month-week-number { text-align: center; padding: 10px 2px; font-size: 12px; border-top: 1px solid rgba(128,128,128,.25); border-right: 1px solid rgba(128,128,128,.25); }
.month-cell { min-height: 142px; border-top: 1px solid rgba(128,128,128,.25); border-right: 1px solid rgba(128,128,128,.25); padding: 3px; min-width: 0; }
.outside-month { background: var(--solaire-gray-light); }
.body--dark .outside-month { background: var(--solaire-gray-dark); }
.day-heading { display: flex; justify-content: space-between; align-items: center; }
.is-today { background: var(--solaire-blue-light); }
.body--dark .is-today { background: var(--solaire-blue-dark); }
.month-events, .schedule-events { display: grid; gap: 3px; }
.time-grid-header, .all-day-grid, .time-columns { display: grid; }
.time-grid-header { text-align: center; align-items: center; border-bottom: 1px solid rgba(128,128,128,.25); }
.all-day-cell { border-left: 1px solid rgba(128,128,128,.25); padding: 3px; min-height: 36px; }
.can-create { cursor: pointer; }
.can-create:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: -2px; }
.time-scroll { max-height: 68vh; min-height: 350px; overflow-y: auto; scrollbar-gutter: stable; }
.time-columns { height: 1440px; }
.hour-labels { position: relative; }
.hour-labels span { position: absolute; right: 8px; font-size: 11px; }
.time-day { position: relative; min-width: 0; border-left: 1px solid rgba(128,128,128,.25); user-select: none; touch-action: pan-y pinch-zoom; }
.hour-slot { height: 60px; border-top: 1px solid rgba(128,128,128,.25); }
.create-slot { width: 100%; height: 100%; }
.timed-event { position: absolute; z-index: 1; overflow: hidden; height: var(--event-height); min-height: 0; width: var(--event-width); left: var(--event-left); }
.timed-event:hover, .timed-event:focus-visible { z-index: 4; left: 0; width: calc(100% - 3px); height: auto; min-height: max(var(--event-height), 64px); outline: 2px solid var(--event-accent); outline-offset: -2px; }
.timed-event :deep(.q-btn__content) { align-items: flex-start; }
.timed-event :deep(.event-heading) { display: block; }
.timed-event :deep(.event-time) { display: block; }
.timed-event :deep(.event-heading > .ellipsis) { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; white-space: normal; overflow: hidden; }
.timed-event:hover :deep(.event-heading > .ellipsis), .timed-event:focus-visible :deep(.event-heading > .ellipsis) { display: block; overflow-wrap: anywhere; }
.now-line { position: absolute; width: 100%; height: 2px; pointer-events: none; background: var(--solaire-red-accent); z-index: 2; }
.slot-selection { position: absolute; left: 0; right: 2px; z-index: 3; pointer-events: none; border: 2px solid var(--solaire-blue-accent); border-radius: 4px; background: var(--solaire-blue-light); padding: 5px; font-size: 12px; }
.body--dark .slot-selection { background: var(--solaire-blue-dark); }
.schedule-day { display: flex; align-items: flex-start; gap: 20px; padding: 14px; border-bottom: 1px solid rgba(128,128,128,.25); }
.schedule-date { width: 105px; flex-shrink: 0; }
.schedule-events { flex: 1; min-width: 0; }
.empty-schedule { text-align: center; padding: 64px 12px; color: var(--solaire-gray-accent); }
@media (max-width: 1023px) { .month-cell { min-height: 100px; } .month-events { gap: 2px; } .day-heading .q-btn { min-height: 26px; min-width: 26px; font-size: 12px; } .schedule-day { gap: 8px; padding: 8px; } .schedule-date { width: 76px; } }
@media (max-width: 599px) { .month-cell { padding: 1px; } .month-events :deep(.event-time) { display: none; } .month-events :deep(.event-heading) { font-size: 10px; } .month-events :deep(.event-status) { gap: 2px; } }
</style>
