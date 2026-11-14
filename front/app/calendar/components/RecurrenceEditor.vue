<template>
  <div class="recurrence-editor q-gutter-y-sm">
    <q-select v-model="frequency" outlined dense emit-value map-options :label="t('agenda.recurrence')" :options="frequencies" @update:model-value="publish" />
    <template v-if="frequency !== 'none' && frequency !== 'custom'">
      <q-input v-model.number="interval" outlined dense type="number" :min="1" :max="1000" :label="t('agenda.interval')" :rules="[positive]" @update:model-value="publish" />
      <div v-if="frequency === 'weekly'" class="row" :aria-label="t('agenda.weekdays')"><q-checkbox v-for="(day, index) in weekdayCodes" :key="day" v-model="weekdays" :val="day" :label="weekdayLabel(index)" @update:model-value="publish" /></div>
      <div class="row q-col-gutter-sm"><q-select v-model="ending" class="col" outlined dense emit-value map-options :label="t('agenda.repeatEnd')" :options="endings" @update:model-value="publish" />
        <q-input v-if="ending === 'count'" v-model.number="count" class="col" outlined dense type="number" :min="1" :max="10000" :label="t('agenda.occurrences')" :rules="[positive]" @update:model-value="publish" />
        <q-input v-if="ending === 'until'" v-model="until" class="col" outlined dense type="date" stack-label :label="t('agenda.repeatUntil')" :rules="[value => Boolean(value) || t('agenda.required')]" @update:model-value="publish" />
      </div>
    </template>
    <q-input v-if="frequency === 'custom'" v-model="custom" outlined type="textarea" rows="2" :label="t('agenda.rule')" :rules="[value => Boolean(value?.trim()) || t('agenda.required')]" @update:model-value="publish" />
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { addDays, zonedInstant } from '../calendarDates'
const props = defineProps<{ modelValue: string | null; allDay: boolean; timezone: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()
const { t, locale } = useI18n()
const frequency = ref('none'), interval = ref(1), count = ref(10), until = ref(''), ending = ref('never'), custom = ref(''), weekdays = ref<string[]>([])
const weekdayCodes = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const frequencies = computed(() => ['none', 'daily', 'weekly', 'monthly', 'yearly', 'custom'].map(value => ({ value, label: t(`agenda.frequencies.${value}`) })))
const endings = computed(() => ['never', 'until', 'count'].map(value => ({ value, label: t(`agenda.${value}`) })))
const positive = (value: unknown) => Number.isInteger(Number(value)) && Number(value) > 0 || t('agenda.required')
function weekdayLabel(index: number): string { return new Intl.DateTimeFormat(locale.value, { timeZone: 'UTC', weekday: 'short' }).format(new Date(Date.UTC(2026, 0, 5 + index))) }
let published: string | null | undefined
watch(() => props.modelValue, rule => {
  if (published === rule) return
  custom.value = rule ?? ''
  const parts = Object.fromEntries((rule ?? '').replace(/^RRULE:/i, '').split(';').map(part => part.split('=')))
  const simple = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].includes(parts.FREQ ?? '') && Object.keys(parts).every(key => ['FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY'].includes(key)) && (!parts.BYDAY || parts.FREQ === 'WEEKLY')
  frequency.value = !rule ? 'none' : simple ? parts.FREQ!.toLowerCase() : 'custom'
  interval.value = Number(parts.INTERVAL ?? 1); count.value = Number(parts.COUNT ?? 10)
  weekdays.value = parts.BYDAY?.split(',') ?? []
  ending.value = parts.COUNT ? 'count' : parts.UNTIL ? 'until' : 'never'
  until.value = parts.UNTIL ? `${parts.UNTIL.slice(0, 4)}-${parts.UNTIL.slice(4, 6)}-${parts.UNTIL.slice(6, 8)}` : ''
}, { immediate: true })
function publish(): void {
  if (frequency.value === 'none') published = null
  else if (frequency.value === 'custom') published = custom.value.trim().replace(/^RRULE:/i, '')
  else {
    const parts = [`FREQ=${frequency.value.toUpperCase()}`, `INTERVAL=${Math.max(1, interval.value)}`]
    if (frequency.value === 'weekly' && weekdays.value.length) parts.push(`BYDAY=${weekdays.value.join(',')}`)
    if (ending.value === 'count') parts.push(`COUNT=${Math.max(1, count.value)}`)
    if (ending.value === 'until' && until.value) {
      try { parts.push(`UNTIL=${props.allDay ? until.value.replaceAll('-', '') : new Date(Date.parse(zonedInstant(`${addDays(until.value, 1)}T00:00`, props.timezone)) - 1000).toISOString().replaceAll(/[-:]/g, '').replace('.000', '')}`) } catch { return }
    }
    published = parts.join(';')
  }
  emit('update:modelValue', published)
}
watch(() => [props.allDay, props.timezone], () => { if (ending.value === 'until') publish() })
</script>
