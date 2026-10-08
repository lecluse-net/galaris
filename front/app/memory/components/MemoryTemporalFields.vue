<template>
  <div class="memory-temporal">
    <div class="memory-temporal-heading">
      <div class="memory-temporal-title"><q-icon name="schedule" />{{ t('memory.temporal.title') }}</div>
      <div class="memory-temporal-actions">
        <q-btn flat round dense icon="info_outline" :aria-label="t('memory.temporal.hint')">
          <q-tooltip max-width="320px">{{ t('memory.temporal.hint') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="modelValue && !readonly" flat round dense icon="clear"
          :aria-label="t('memory.temporal.remove')" @click="emit('update:modelValue', null)">
          <q-tooltip>{{ t('memory.temporal.remove') }}</q-tooltip>
        </q-btn>
      </div>
    </div>
    <div class="memory-temporal-inputs">
      <div v-for="field in fields" :key="field.key" :class="`memory-temporal-${field.key}`">
        <q-input :model-value="modelValue?.[field.key] ?? null" :readonly="readonly"
          type="number" :min="field.min" :max="field.max" step="1" :clearable="!readonly" dense outlined stack-label hide-bottom-space
          :label="t(`memory.temporal.${field.key === 'day' ? 'dayShort' : field.key}`)" :aria-label="t(`memory.temporal.${field.key}`)"
          :placeholder="t('memory.temporal.anyShort')" :title="t('memory.temporal.any')"
          :rules="[value => validNumber(value, field.min, field.max)]"
          @update:model-value="change(field.key, $event)" />
      </div>
      <div class="memory-temporal-weekday">
        <q-select :model-value="modelValue?.weekday ?? null" :readonly="readonly" :clearable="!readonly"
          :options="weekdays" emit-value map-options dense outlined hide-bottom-space :label="t('memory.temporal.weekday')"
          @update:model-value="change('weekday', $event)" />
      </div>
    </div>
    <div class="text-caption q-mt-sm" role="status">{{ interpretation }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MemoryTemporalAnchor } from '../types'

const { modelValue, readonly = false } = defineProps<{ modelValue: MemoryTemporalAnchor | null; readonly?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: MemoryTemporalAnchor | null] }>()
const { t } = useI18n()
type NumericField = keyof MemoryTemporalAnchor
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
  emit('update:modelValue', [...fields.map(field => field.key), 'weekday' as const]
    .some(field => anchor[field] != null) ? anchor : null)
}
</script>

<style scoped>
.memory-temporal-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; }
.memory-temporal-title { display: flex; align-items: center; gap: 8px; font-size: 0.875rem; font-weight: 600; }
.memory-temporal-title .q-icon { color: var(--solaire-blue-accent); font-size: 18px; }
.memory-temporal-actions { display: flex; gap: 4px; }
.memory-temporal-inputs { display: grid; grid-template-columns: 88px 88px 112px 88px 88px minmax(160px, 200px); gap: 8px; margin-top: 8px; }
.memory-temporal-inputs > div { min-width: 0; }
.memory-temporal-inputs :deep(input) { font-variant-numeric: tabular-nums; }
@media (max-width: 799px) {
  .memory-temporal-inputs { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.5fr); }
}
</style>
