<template>
  <div class="q-mt-md">
    <q-btn flat dense color="primary" icon="refresh" :label="t('llm.capabilityRefresh.action')"
      :loading="loading" @click="refresh" />
    <div v-if="error" role="alert" class="q-mt-sm">{{ t('llm.capabilityRefresh.error') }}</div>
    <div v-if="preview" class="q-mt-sm" role="status">
      <template v-if="changes.length || capabilitiesChanged">
        <div>{{ t('llm.capabilityRefresh.preview') }}</div>
        <ul>
          <li v-for="change in changes" :key="change.key">
            {{ modalityLabel(change.key) }}: {{ enabledLabel(change.before) }} → {{ enabledLabel(change.after) }}
          </li>
          <li v-if="capabilitiesChanged">
            {{ t('llm.detectedCapabilities') }}: {{ capabilityLabels(serviceCapabilities) }} → {{ capabilityLabels(proposedCapabilities) }}
          </li>
        </ul>
        <q-btn flat :label="t('common.cancel')" @click="preview = null" />
        <q-btn flat color="primary" :label="t('llm.capabilityRefresh.apply')" @click="apply" />
      </template>
      <div v-else>{{ t('llm.capabilityRefresh.unchanged') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import llmProviderService, { type AICapability, type LLMModalities, type LLMModelInfo } from '../services/llmProviderService'

const props = defineProps<{
  providerId: number
  modelName: string
  capability: AICapability
  modalities: LLMModalities
  serviceCapabilities: AICapability[]
}>()
const emit = defineEmits<{
  apply: [modalities: Partial<LLMModalities>, capabilities: AICapability[]]
}>()
const { t } = useI18n()
const loading = ref(false)
const error = ref(false)
const preview = ref<LLMModelInfo | null>(null)
let generation = 0

function reset() {
  generation++
  loading.value = false
  error.value = false
  preview.value = null
}
watch(() => [props.providerId, props.modelName, props.capability], reset, { flush: 'sync' })
onBeforeUnmount(reset)

const changes = computed(() => {
  const model = preview.value
  if (!model?.modalities) return []
  // Older servers do not distinguish unknown from false. Never reset saved
  // choices based on their default-filled response.
  return (model.known_modalities ?? []).flatMap(key => {
    const after = model.modalities?.[key]
    const before = props.modalities[key]
    return typeof after === 'boolean' && typeof before === 'boolean' && after !== before
      ? [{ key, before, after }] : []
  })
})
const proposedCapabilities = computed(() => {
  const model = preview.value
  if (!model) return props.serviceCapabilities
  const nativeInputs: Partial<Record<AICapability, keyof LLMModalities>> = {
    vision: 'input_image', audio_understanding: 'input_audio', video_understanding: 'input_video',
  }
  const preserved = props.serviceCapabilities.filter(capability => {
    const field = nativeInputs[capability]
    return field && !model.known_modalities?.includes(field)
  })
  return [...new Set([props.capability, ...model.service_capabilities, ...preserved])]
})
const capabilitiesChanged = computed(() => preview.value !== null
  && [...proposedCapabilities.value].sort().join(',') !== [...props.serviceCapabilities].sort().join(','))

function modalityLabel(key: keyof LLMModalities) {
  const [direction, kind] = key.split('_')
  return `${t(`llm.${direction}`)} · ${t(`llm.${kind}`)}`
}
function enabledLabel(value: boolean) {
  return t(`llm.capabilityRefresh.${value ? 'enabled' : 'disabled'}`)
}
function capabilityLabels(values: AICapability[]) {
  return values.map(value => t(`llm.capabilities.${value}`)).join(', ')
}
async function refresh() {
  reset()
  const request = generation
  loading.value = true
  try {
    const response = await llmProviderService.getProviderResources(props.providerId, props.capability, true)
    if (request !== generation) return
    const model = response.data.models.find(value => value.id === props.modelName)
    if (!model || !model.known_modalities) throw new Error('No refreshable metadata')
    preview.value = model
  } catch {
    if (request === generation) error.value = true
  } finally {
    if (request === generation) loading.value = false
  }
}
function apply() {
  if (!preview.value) return
  const modalities: Partial<LLMModalities> = {}
  for (const change of changes.value) modalities[change.key] = change.after
  emit('apply', modalities, [...proposedCapabilities.value])
  reset()
}
</script>
