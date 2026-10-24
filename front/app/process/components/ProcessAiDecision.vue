<template>
  <div class="q-gutter-y-sm">
    <q-select :model-value="config.ai_mode ?? 'task'" :options="modes" emit-value map-options outlined
      :readonly="readonly" :label="t('nativeProcesses.aiMode')" @update:model-value="emit('change', 'ai_mode', $event)" />
    <template v-if="config.ai_mode === 'llm'">
      <q-select :model-value="config.llm_id ?? null" :options="options" emit-value map-options outlined hide-bottom-space
        :readonly="readonly" :loading="loading" :label="t('nativeProcesses.llmModel')"
        :error="error" :error-message="t('nativeProcesses.llmModelsError')"
        @popup-show="load" @update:model-value="emit('change', 'llm_id', $event)">
        <template #no-option><q-item><q-item-section>{{ t('nativeProcesses.noLlmModels') }}</q-item-section></q-item></template>
      </q-select>
      <div class="text-caption">{{ t('nativeProcesses.simpleLlmHint') }}</div>
      <q-btn v-if="error" outline color="primary" :label="t('nativeProcesses.retry')" @click="load" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { nativeProcessService, type ProcessDecisionModel } from '../services/nativeProcessService'

const props = defineProps<{ config: Record<string, unknown>; readonly: boolean }>()
const emit = defineEmits<{ change: [key: string, value: unknown] }>()
const { t } = useI18n()
const models = ref<ProcessDecisionModel[]>([]), loading = ref(false), error = ref(false)
let pending: AbortController | null = null
const modes = computed(() => ['task', 'llm'].map(value => ({ value, label: t(`nativeProcesses.aiModes.${value}`) })))
const options = computed(() => {
  const values = models.value.map(model => ({ value: model.id, label: `${model.label} · ${model.provider}` }))
  if (typeof props.config.llm_id === 'number' && !values.some(option => option.value === props.config.llm_id))
    values.push({ value: props.config.llm_id, label: t('nativeProcesses.unavailableLlm', { id: props.config.llm_id }) })
  return values
})
async function load(): Promise<void> {
  if (pending) return
  const request = new AbortController()
  pending = request; loading.value = true; error.value = false
  try {
    const result = await nativeProcessService.decisionModels(request.signal)
    if (pending === request) models.value = result
  } catch {
    if (pending === request && !request.signal.aborted) error.value = true
  } finally {
    if (pending === request) { pending = null; loading.value = false }
  }
}
watch(() => props.config.ai_mode, mode => { if (mode === 'llm') void load() }, { immediate: true })
onBeforeUnmount(() => { pending?.abort(); pending = null })
</script>
