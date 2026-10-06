<template>
  <q-input v-model="target" type="datetime-local" outlined dense required hide-bottom-space :disable="!timezone"
    :label="t('memory.temporalSearch.target')"
    :rules="[validTarget]" />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MemoryTemporalFilter } from '../types'

const props = defineProps<{ modelValue: MemoryTemporalFilter; timezone: string | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: MemoryTemporalFilter] }>()
const { t } = useI18n()
let referenceInstant: Date | null = null
const target = ref('')

watch(() => [props.timezone, props.modelValue.target_at] as const, ([zone, value]) => {
  if (!zone) return
  if (value && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) {
    referenceInstant = null
    target.value = value
  } else {
    referenceInstant = value ? new Date(value) : new Date()
    target.value = localInput(referenceInstant, zone)
  }
}, { immediate: true })

function localInput(date: Date, zone: string): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

function validTarget(value: string): true | string {
  const date = new Date(`${value}Z`)
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) && !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 16) === value
    ? true : t('memory.temporalSearch.invalidTarget')
}

function apply(): void {
  if (!props.timezone || validTarget(target.value) !== true) return
  // Keep the current occurrence of a repeated hour in the global timezone.
  // Edited wall times are resolved by the server, which owns that timezone.
  const current = referenceInstant && localInput(referenceInstant, props.timezone) === target.value
    ? new Date(Math.floor(referenceInstant.getTime() / 60_000) * 60_000).toISOString() : target.value
  emit('update:modelValue', {
    target_at: current,
    lookahead_hours: 0,
  })
}

defineExpose({ apply })
</script>
