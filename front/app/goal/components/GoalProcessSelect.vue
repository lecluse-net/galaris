<template>
  <div>
    <q-select
      v-model="selection"
      :options="options"
      option-value="id"
      emit-value
      map-options
      outlined
      dense
      :label="t('goal.cycleProcess.label')"
      :hint="agentId !== null && !loading && !loadError && processes.length === 0 ? t('goal.cycleProcess.empty') : undefined"
      :display-value="displayValue"
      :loading="loading"
      :disable="agentId === null"
    />
    <q-banner v-if="loadError" role="alert" dense>
      {{ t('goal.cycleProcess.loadError') }}
      <template #action>
        <q-btn outline color="primary" :label="t('common.retry')" @click="retry++" />
      </template>
    </q-banner>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { goalService } from '../services/goalService'
import type { GoalProcessOption } from '../types'

const { agentId } = defineProps<{ agentId: number | null }>()
const processId = defineModel<number | null>({ required: true })
const { t } = useI18n()
const processes = ref<GoalProcessOption[]>([])
const loading = ref(false)
const loadError = ref(false)
const retry = ref(0)
const options = computed(() => [
  { id: 'task', label: t('goal.cycleProcess.task') },
  ...processes.value,
])
const selection = computed<number | 'task'>({
  get: () => processId.value ?? 'task',
  set: value => { processId.value = value === 'task' ? null : value },
})
const displayValue = computed(() => {
  return options.value.find(option => option.id === selection.value)?.label
    ?? t(loading.value || loadError.value ? 'goal.cycleProcess.configured' : 'goal.cycleProcess.unavailable')
})

watch([() => agentId, retry], async ([id], _previous, onCleanup) => {
  const request = new AbortController()
  onCleanup(() => request.abort())
  processes.value = []
  loadError.value = false
  loading.value = id !== null
  if (id === null) return
  try {
    const result = await goalService.processOptions(id, request.signal)
    if (!request.signal.aborted) processes.value = result
  } catch {
    if (!request.signal.aborted) loadError.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true, flush: 'sync' })
</script>
