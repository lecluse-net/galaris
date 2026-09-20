<template>
  <div>
    <div v-if="scope === 'global'" class="text-caption text-grey-7 q-mb-sm">
      {{ t('goal.runtime.globalScheduleSubtitle') }}
    </div>
    <q-toggle
      v-if="showEnabledToggle"
      v-model="enabled"
      color="primary"
      :label="t(scope === 'global'
        ? 'goal.runtime.enableGlobalSchedule'
        : 'goal.runtime.enableSchedule')"
    />
    <div v-if="enabled" class="q-mt-sm">
      <div class="row items-center justify-between q-gutter-sm q-mb-sm">
        <div class="text-body2 text-grey-8">
          <span class="gt-sm">{{ t('goal.runtime.gridHint') }}</span>
          <span class="lt-md">{{ t('goal.runtime.gridHintMobile') }}</span>
        </div>
        <q-btn
          flat
          dense
          color="negative"
          icon="deselect"
          :label="t('goal.runtime.clearGrid')"
          :disable="slots.size === 0"
          @click="slots = new Set()"
        />
      </div>

      <div class="goal-schedule-grid-wrapper">
        <table ref="scheduleGrid" class="goal-schedule-grid">
          <thead>
            <tr>
              <th class="goal-schedule-grid__hour" scope="col">{{ t('goal.runtime.hour') }}</th>
              <th
                v-for="weekday in weekdays"
                :key="weekday"
                class="goal-schedule-grid__group-header"
                scope="col"
              >
                <button
                  type="button"
                  class="goal-schedule-grid__group-button"
                  :aria-label="weekdayToggleLabel(weekday)"
                  data-schedule-group="weekday"
                  :data-group-index="weekday"
                  @pointerdown="beginGroupDrag($event, 'weekday', weekday)"
                  @click="handleWeekdayClick($event, weekday)"
                >
                  <span class="gt-sm">{{ weekdayLabel(weekday) }}</span>
                  <span class="lt-md">{{ weekdayShortLabel(weekday) }}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="hour in hours" :key="hour">
              <th
                class="goal-schedule-grid__hour goal-schedule-grid__group-header"
                scope="row"
              >
                <button
                  type="button"
                  class="goal-schedule-grid__group-button"
                  :aria-label="hourToggleLabel(hour)"
                  data-schedule-group="hour"
                  :data-group-index="hour"
                  @pointerdown="beginGroupDrag($event, 'hour', hour)"
                  @click="handleHourClick($event, hour)"
                >
                  {{ hourRangeLabel(hour) }}
                </button>
              </th>
              <td
                v-for="weekday in weekdays"
                :key="weekday"
                :class="{
                  'goal-schedule-grid__slot--active': isSlotActive(weekday, hour),
                  'goal-schedule-grid__slot--inactive': !isSlotActive(weekday, hour),
                  'goal-schedule-grid__slot--forbidden': !isSlotAllowed(weekday, hour),
                }"
                data-schedule-slot
                :data-weekday="weekday"
                :data-hour="hour"
                role="checkbox"
                :tabindex="isSlotAllowed(weekday, hour) ? 0 : -1"
                :aria-checked="isSlotActive(weekday, hour)"
                :aria-disabled="!isSlotAllowed(weekday, hour)"
                :aria-label="slotLabel(weekday, hour)"
                @pointerdown="beginSlotDrag($event, weekday, hour)"
                @click="handleSlotClick($event, weekday, hour)"
                @keydown.enter.prevent="toggleSlot(weekday, hour)"
                @keydown.space.prevent="toggleSlot(weekday, hour)"
              >
                <q-icon
                  :name="!isSlotAllowed(weekday, hour)
                    ? 'lock'
                    : isSlotActive(weekday, hour) ? 'check' : 'close'"
                  :color="!isSlotAllowed(weekday, hour)
                    ? 'grey-6'
                    : isSlotActive(weekday, hour) ? 'positive' : 'negative'"
                  size="18px"
                  aria-hidden="true"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <q-banner
        v-if="slots.size === 0"
        rounded
        class="bg-orange-1 text-warning q-mt-md"
      >
        {{ t('goal.runtime.noSlots') }}
      </q-banner>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  GOAL_SCHEDULE_HOURS,
  GOAL_SCHEDULE_WEEKDAYS,
  goalScheduleSlotKey,
  type GoalScheduleSlots,
} from '../scheduleGrid'

const {
  scope = 'goal',
  allowedSlots,
  showEnabledToggle = true,
} = defineProps<{
  scope?: 'global' | 'goal'
  allowedSlots?: GoalScheduleSlots
  showEnabledToggle?: boolean
}>()

const enabled = defineModel<boolean>('enabled', { required: true })
const slots = defineModel<GoalScheduleSlots>('slots', { required: true })
const { t } = useI18n()
const hours = GOAL_SCHEDULE_HOURS
const weekdays = GOAL_SCHEDULE_WEEKDAYS
const scheduleGrid = useTemplateRef<HTMLTableElement>('scheduleGrid')
const draggedSlots = new Set<string>()
const draggedGroups = new Set<number>()
type ScheduleGroupKind = 'weekday' | 'hour'
let activePointerId: number | null = null
let activeGroupKind: ScheduleGroupKind | null = null
let dragShouldActivate = false

function weekdayLabel(weekday: number): string {
  return t(`goal.runtime.weekdays.${weekday}`)
}

function weekdayShortLabel(weekday: number): string {
  return t(`goal.runtime.weekdaysShort.${weekday}`)
}

function hourRangeLabel(hour: number): string {
  return `${hour} h–${(hour + 1) % 24} h`
}

function slotLabel(weekday: number, hour: number): string {
  return t('goal.runtime.slotLabel', {
    day: weekdayLabel(weekday),
    start: `${hour} h`,
    end: `${(hour + 1) % 24} h`,
  })
}

function weekdayToggleLabel(weekday: number): string {
  return t('goal.runtime.toggleWeekdayLabel', { day: weekdayLabel(weekday) })
}

function hourToggleLabel(hour: number): string {
  return t('goal.runtime.toggleHourLabel', { range: hourRangeLabel(hour) })
}

function isSlotActive(weekday: number, hour: number): boolean {
  return slots.value.has(goalScheduleSlotKey(weekday, hour))
}

function isSlotAllowed(weekday: number, hour: number): boolean {
  return allowedSlots?.has(goalScheduleSlotKey(weekday, hour)) ?? true
}

function toggleSlot(weekday: number, hour: number): void {
  if (!isSlotAllowed(weekday, hour)) return
  setSlot(weekday, hour, !isSlotActive(weekday, hour))
}

function paintSlot(weekday: number, hour: number): void {
  const key = goalScheduleSlotKey(weekday, hour)
  if (draggedSlots.has(key) || !isSlotAllowed(weekday, hour)) return
  draggedSlots.add(key)
  setSlot(weekday, hour, dragShouldActivate)
}

function beginSlotDrag(event: PointerEvent, weekday: number, hour: number): void {
  if ((event.pointerType === 'mouse' && event.button !== 0)
    || !isSlotAllowed(weekday, hour)) return
  if (event.pointerType === 'touch') return

  event.preventDefault()
  stopSlotDrag()
  activePointerId = event.pointerId
  dragShouldActivate = !isSlotActive(weekday, hour)
  paintSlot(weekday, hour)
  window.addEventListener('pointermove', handleSlotDrag, { passive: false })
  window.addEventListener('pointerup', finishSlotDrag)
  window.addEventListener('pointercancel', finishSlotDrag)
}

function groupCoordinates(
  kind: ScheduleGroupKind,
  index: number,
): ReadonlyArray<readonly [number, number]> {
  if (kind === 'weekday') {
    return hours.map((hour) => [index, hour] as const)
  }
  return weekdays.map((weekday) => [weekday, index] as const)
}

function paintGroup(kind: ScheduleGroupKind, index: number): void {
  if (activeGroupKind !== kind || draggedGroups.has(index)) return
  draggedGroups.add(index)
  const updated = new Set(slots.value)
  for (const [weekday, hour] of groupCoordinates(kind, index)) {
    if (!isSlotAllowed(weekday, hour)) continue
    const key = goalScheduleSlotKey(weekday, hour)
    if (dragShouldActivate) updated.add(key)
    else updated.delete(key)
  }
  slots.value = updated
}

function beginGroupDrag(
  event: PointerEvent,
  kind: ScheduleGroupKind,
  index: number,
): void {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  if (event.pointerType === 'touch') return
  const allowedCoordinates = groupCoordinates(kind, index).filter(([weekday, hour]) => (
    isSlotAllowed(weekday, hour)
  ))
  if (allowedCoordinates.length === 0) return

  event.preventDefault()
  stopSlotDrag()
  activePointerId = event.pointerId
  activeGroupKind = kind
  dragShouldActivate = allowedCoordinates.some(([weekday, hour]) => (
    !isSlotActive(weekday, hour)
  ))
  paintGroup(kind, index)
  window.addEventListener('pointermove', handleSlotDrag, { passive: false })
  window.addEventListener('pointerup', finishSlotDrag)
  window.addEventListener('pointercancel', finishSlotDrag)
}

function handleSlotDrag(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) return
  event.preventDefault()
  if (activeGroupKind) {
    const group = document.elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>(`[data-schedule-group="${activeGroupKind}"]`)
    if (!group || !scheduleGrid.value?.contains(group)) return
    const index = Number(group.dataset.groupIndex)
    if (!Number.isInteger(index)) return
    paintGroup(activeGroupKind, index)
    return
  }

  const slot = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>('[data-schedule-slot]')
  if (!slot || !scheduleGrid.value?.contains(slot)) return

  const weekday = Number(slot.dataset.weekday)
  const hour = Number(slot.dataset.hour)
  if (!Number.isInteger(weekday) || !Number.isInteger(hour)) return
  paintSlot(weekday, hour)
}

function finishSlotDrag(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) return
  stopSlotDrag()
}

function stopSlotDrag(): void {
  activePointerId = null
  activeGroupKind = null
  draggedSlots.clear()
  draggedGroups.clear()
  window.removeEventListener('pointermove', handleSlotDrag)
  window.removeEventListener('pointerup', finishSlotDrag)
  window.removeEventListener('pointercancel', finishSlotDrag)
}

function toggleGroup(coordinates: ReadonlyArray<readonly [number, number]>): void {
  const allowedCoordinates = coordinates.filter(([weekday, hour]) => (
    isSlotAllowed(weekday, hour)
  ))
  if (allowedCoordinates.length === 0) return

  const shouldActivate = allowedCoordinates.some(([weekday, hour]) => (
    !isSlotActive(weekday, hour)
  ))
  const updated = new Set(slots.value)
  for (const [weekday, hour] of allowedCoordinates) {
    const key = goalScheduleSlotKey(weekday, hour)
    if (shouldActivate) updated.add(key)
    else updated.delete(key)
  }
  slots.value = updated
}

function toggleWeekday(weekday: number): void {
  toggleGroup(hours.map((hour) => [weekday, hour] as const))
}

function toggleHour(hour: number): void {
  toggleGroup(weekdays.map((weekday) => [weekday, hour] as const))
}

function handleWeekdayClick(event: MouseEvent, weekday: number): void {
  if (isTapClick(event)) toggleWeekday(weekday)
}

function handleHourClick(event: MouseEvent, hour: number): void {
  if (isTapClick(event)) toggleHour(hour)
}

function handleSlotClick(event: MouseEvent, weekday: number, hour: number): void {
  if (isTapClick(event)) toggleSlot(weekday, hour)
}

function isTapClick(event: MouseEvent): boolean {
  return event.detail === 0
    || ('pointerType' in event && event.pointerType === 'touch')
}

function setSlot(weekday: number, hour: number, active: boolean): void {
  const updated = new Set(slots.value)
  const key = goalScheduleSlotKey(weekday, hour)
  if (active) updated.add(key)
  else updated.delete(key)
  slots.value = updated
}

onBeforeUnmount(stopSlotDrag)
</script>

<style scoped>
.goal-schedule-grid-wrapper {
  overflow: auto;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
}

.goal-schedule-grid {
  width: 100%;
  min-width: 520px;
  border-collapse: separate;
  border-spacing: 0;
  text-align: center;
  font-size: 12px;
}

.goal-schedule-grid th,
.goal-schedule-grid td {
  min-width: 58px;
  height: 32px;
  padding: 0 3px;
  background: white;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.goal-schedule-grid td {
  cursor: pointer;
  touch-action: none;
  user-select: none;
  transition: background-color 120ms ease;
}

.goal-schedule-grid td:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid currentcolor;
  outline-offset: -3px;
}

.goal-schedule-grid th.goal-schedule-grid__group-header {
  padding: 0;
}

.goal-schedule-grid__group-button {
  width: 100%;
  height: 100%;
  min-height: 32px;
  padding: 0 3px;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  font-weight: inherit;
  touch-action: none;
  user-select: none;
}

.goal-schedule-grid__group-button:hover {
  background: rgba(255, 255, 255, 0.14);
}

.goal-schedule-grid tbody .goal-schedule-grid__group-button:hover {
  background: rgba(0, 0, 0, 0.06);
}

.goal-schedule-grid__group-button:focus-visible {
  outline: 2px solid currentcolor;
  outline-offset: -3px;
}

.goal-schedule-grid thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--q-primary);
  color: white;
}

.goal-schedule-grid .goal-schedule-grid__hour {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 82px;
  white-space: nowrap;
  background: #fafafa;
  color: rgba(0, 0, 0, 0.75);
}

.goal-schedule-grid thead .goal-schedule-grid__hour {
  z-index: 3;
  background: var(--q-primary);
  color: white;
}

.goal-schedule-grid td.goal-schedule-grid__slot--active {
  background: color-mix(in srgb, var(--q-positive) 18%, white);
}

.goal-schedule-grid td.goal-schedule-grid__slot--inactive {
  background: color-mix(in srgb, var(--q-negative) 14%, white);
}

.goal-schedule-grid td.goal-schedule-grid__slot--active:hover {
  background: color-mix(in srgb, var(--q-positive) 26%, white);
}

.goal-schedule-grid td.goal-schedule-grid__slot--inactive:hover {
  background: color-mix(in srgb, var(--q-negative) 22%, white);
}

.goal-schedule-grid td.goal-schedule-grid__slot--forbidden {
  cursor: not-allowed;
  background: repeating-linear-gradient(
    -45deg,
    rgba(0, 0, 0, 0.04),
    rgba(0, 0, 0, 0.04) 6px,
    rgba(0, 0, 0, 0.09) 6px,
    rgba(0, 0, 0, 0.09) 12px
  );
}

:global(.body--dark) .goal-schedule-grid th,
:global(.body--dark) .goal-schedule-grid td {
  background: #1d1d1d;
  color: white;
}

:global(.body--dark) .goal-schedule-grid .goal-schedule-grid__hour {
  background: #252525;
  color: rgba(255, 255, 255, 0.85);
}

:global(.body--dark) .goal-schedule-grid thead th,
:global(.body--dark) .goal-schedule-grid thead .goal-schedule-grid__hour {
  background: var(--q-primary);
  color: white;
}

:global(.body--dark) .goal-schedule-grid td.goal-schedule-grid__slot--active {
  background: color-mix(in srgb, var(--q-positive) 24%, #1d1d1d);
}

:global(.body--dark) .goal-schedule-grid td.goal-schedule-grid__slot--inactive {
  background: color-mix(in srgb, var(--q-negative) 20%, #1d1d1d);
}

:global(.body--dark) .goal-schedule-grid tbody .goal-schedule-grid__group-button:hover {
  background: rgba(255, 255, 255, 0.09);
}

:global(.body--dark) .goal-schedule-grid td.goal-schedule-grid__slot--active:hover {
  background: color-mix(in srgb, var(--q-positive) 32%, #1d1d1d);
}

:global(.body--dark) .goal-schedule-grid td.goal-schedule-grid__slot--inactive:hover {
  background: color-mix(in srgb, var(--q-negative) 28%, #1d1d1d);
}

:global(.body--dark) .goal-schedule-grid td.goal-schedule-grid__slot--forbidden {
  background: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.03),
    rgba(255, 255, 255, 0.03) 6px,
    rgba(255, 255, 255, 0.09) 6px,
    rgba(255, 255, 255, 0.09) 12px
  );
}

@media (max-width: 1023.98px) {
  .goal-schedule-grid-wrapper {
    overflow: visible;
  }

  .goal-schedule-grid {
    min-width: 0;
    table-layout: fixed;
    font-size: 10px;
  }

  .goal-schedule-grid th,
  .goal-schedule-grid td {
    min-width: 0;
    height: 30px;
    padding: 0;
  }

  .goal-schedule-grid td,
  .goal-schedule-grid__group-button {
    touch-action: pan-y;
  }

  .goal-schedule-grid__group-button {
    min-height: 30px;
    padding: 0;
  }

  .goal-schedule-grid .goal-schedule-grid__hour {
    position: static;
    width: 50px;
    min-width: 0;
  }

  .goal-schedule-grid thead th {
    position: static;
  }
}
</style>
