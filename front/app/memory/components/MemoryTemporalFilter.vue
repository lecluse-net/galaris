<template>
  <q-input v-model="target" type="datetime-local" outlined dense required hide-bottom-space
    :label="t('memory.temporalSearch.target')"
    :rules="[validTarget]" />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MemoryTemporalFilter } from '../types'

const props = defineProps<{ modelValue: MemoryTemporalFilter }>()
const emit = defineEmits<{ 'update:modelValue': [value: MemoryTemporalFilter] }>()
const { t } = useI18n()
let referenceInstant = props.modelValue.target_at ? new Date(props.modelValue.target_at) : new Date()
const target = ref(localInput(referenceInstant))

function localInput(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function validTarget(value: string): true | string {
  const date = new Date(value)
  return !Number.isNaN(date.getTime()) && localInput(date) === value
    ? true : t('memory.temporalSearch.invalidTarget')
}

function apply(): void {
  if (validTarget(target.value) !== true) return
  // Preserve the current occurrence if the browser is in the repeated DST hour.
  const date = localInput(referenceInstant) === target.value ? new Date(referenceInstant) : new Date(target.value)
  date.setTime(Math.floor(date.getTime() / 60_000) * 60_000)
  referenceInstant = date
  emit('update:modelValue', {
    target_at: date.toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    lookahead_hours: 0,
  })
}

defineExpose({ apply })
</script>
