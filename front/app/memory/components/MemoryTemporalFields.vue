<template>
  <div class="memory-temporal">
    <div class="text-subtitle2">{{ t('memory.temporal.title') }}</div>
    <p class="text-caption">{{ t('memory.temporal.hint') }}</p>
    <div class="row q-col-gutter-sm">
      <div v-for="field in fields" :key="field.key" class="col-6 col-sm-4">
        <q-input :model-value="modelValue?.[field.key] ?? null" :readonly="readonly"
          type="number" :min="field.min" :max="field.max" step="1" clearable dense outlined
          :label="t(`memory.temporal.${field.key}`)" :placeholder="t('memory.temporal.any')"
          :rules="[value => validNumber(value, field.min, field.max)]"
          @update:model-value="change(field.key, $event)" />
      </div>
      <div class="col-6 col-sm-4">
        <q-select :model-value="modelValue?.weekday ?? null" :readonly="readonly" clearable
          :options="weekdays" emit-value map-options dense outlined :label="t('memory.temporal.weekday')"
          @update:model-value="change('weekday', $event)" />
      </div>
      <div class="col-12">
        <q-input :model-value="modelValue?.timezone ?? defaultTimezone" :readonly="readonly" dense outlined
          :label="t('memory.temporal.timezone')" :hint="timezoneError ? t('memory.temporal.timezoneError') : undefined"
          @update:model-value="changeTimezone(String($event ?? ''))" />
      </div>
    </div>
    <div class="text-caption q-mt-sm" role="status">{{ interpretation }}</div>
    <q-btn v-if="modelValue && !readonly" flat dense no-caps icon="clear"
      :label="t('memory.temporal.remove')" @click="emit('update:modelValue', null)" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { memoryService } from '../services/memoryService'
import type { MemoryTemporalAnchor } from '../types'

const { modelValue, readonly = false } = defineProps<{ modelValue: MemoryTemporalAnchor | null; readonly?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: MemoryTemporalAnchor | null] }>()
const { t } = useI18n()
const defaultTimezone = ref('')
const timezoneError = ref(false)
type NumericField = Exclude<keyof MemoryTemporalAnchor, 'timezone'>
const fields: { key: NumericField; min: number; max: number }[] = [
  { key: 'day', min: 1, max: 31 }, { key: 'month', min: 1, max: 12 },
  { key: 'year', min: 1, max: 9999 }, { key: 'hour', min: 0, max: 23 },
  { key: 'minute', min: 0, max: 59 },
]
const weekdays = computed(() => Array.from({ length: 7 }, (_, i) => ({
  value: i + 1, label: t(`memory.temporal.weekdays.${i + 1}`),
})))
const interpretation = computed(() => {
  if (!modelValue) return t('memory.temporal.none')
  const parts = [...fields.map(field => ({ key: field.key, value: modelValue[field.key] })),
    { key: 'weekday', value: modelValue.weekday }]
    .filter(part => part.value != null)
    .map(part => t('memory.temporal.constraint', {
      field: t(`memory.temporal.${part.key}`),
      value: part.key === 'weekday' ? t(`memory.temporal.weekdays.${part.value}`) : part.value,
    }))
  return t('memory.temporal.interpretation', { constraints: parts.join(' · ') })
})
function validNumber(value: unknown, min: number, max: number): true | string {
  return value === null || value === '' || (Number.isInteger(Number(value)) && Number(value) >= min && Number(value) <= max)
    || t('memory.temporal.invalidNumber', { min, max })
}
function change(key: NumericField, value: string | number | null): void {
  if (readonly) return
  const anchor: MemoryTemporalAnchor = { ...modelValue, [key]: value === '' || value === null ? null : Number(value) }
  if (!anchor.timezone && defaultTimezone.value) anchor.timezone = defaultTimezone.value
  emit('update:modelValue', [...fields.map(field => field.key), 'weekday' as const]
    .some(field => anchor[field] != null) ? anchor : null)
}
function changeTimezone(value: string): void {
  if (readonly) return
  defaultTimezone.value = value
  if (modelValue) emit('update:modelValue', { ...modelValue, timezone: value })
}
onMounted(async () => {
  if (readonly || modelValue?.timezone) return
  try {
    const defaults = await memoryService.temporalDefaults()
    if (!defaultTimezone.value) defaultTimezone.value = defaults.timezone
  } catch {
    timezoneError.value = true
  }
})
</script>
