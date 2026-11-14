<template>
  <div class="q-gutter-y-sm">
    <q-input :model-value="localStart" type="datetime-local" stack-label outlined dense :label="t('goal.agenda.firstPassage')" :rules="[() => valid || t('goal.agenda.invalidDate')]" @update:model-value="setStart(String($event ?? ''))" />
    <q-select :model-value="model.timezone" :options="zones" use-input input-debounce="0" outlined dense :label="t('goal.agenda.timezone')" @filter="filterZones" @update:model-value="setZone" />
    <div class="row q-col-gutter-sm">
      <q-input v-model.number="model.interval" class="col-5" type="number" min="1" max="365" outlined dense :label="t('goal.agenda.every')" :rules="[value => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 365 || t('goal.agenda.invalidInterval')]" />
      <q-select v-model="model.frequency" class="col" :options="frequencies" emit-value map-options outlined dense :label="t('goal.agenda.frequency')" />
    </div>
    <q-input v-model.number="model.max_lateness_minutes" type="number" min="0" max="10080" outlined dense :label="t('goal.agenda.lateness')" :rules="[value => Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 10080 || t('goal.agenda.invalidLateness')]" />
    <p class="text-caption q-mb-none">{{ t('goal.agenda.scheduleHint') }}</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { wallTime, zonedInstant } from '@/core/util'
import type { GoalRecurrence } from '../types'
const model = defineModel<GoalRecurrence>({ required: true })
const { t } = useI18n()
const valid = ref(true)
const localStart = computed(() => wallTime(model.value.start_at, model.value.timezone))
const allZones = [...new Set([model.value.timezone, 'UTC', ...Intl.supportedValuesOf('timeZone')])]
const zones = ref(allZones)
const frequencies = computed(() => ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].map(value => ({ value, label: t(`goal.agenda.frequencies.${value}`) })))
function filterZones(value: string, update: (fn: () => void) => void): void { update(() => { zones.value = allZones.filter(zone => zone.toLowerCase().includes(value.toLowerCase())) }) }
function setStart(value: string): void {
  try { model.value = { ...model.value, start_at: zonedInstant(value, model.value.timezone) }; valid.value = true }
  catch { valid.value = false }
}
function setZone(zone: string): void {
  try { model.value = { ...model.value, start_at: zonedInstant(localStart.value, zone), timezone: zone }; valid.value = true }
  catch { valid.value = false }
}
</script>
