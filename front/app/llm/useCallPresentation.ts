import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { reasoningEffortColor } from './presentation'
import { useLLMProviderStore } from './stores/llmProviderStore'
import type { LLMCall } from './types'

/** Both call layouts resolve live model metadata and localized labels identically. */
export function useCallPresentation(call: () => LLMCall) {
  const store = useLLMProviderStore()
  const { t, te } = useI18n()
  onMounted(() => {
    if (!store.llms.length && !store.loadingLLMs) void store.fetchLLMs().catch(() => undefined)
  })
  const llm = computed(() => store.llms.find(item => item.id === call().llm_id))
  return {
    modelLabel: computed(() => llm.value?.label || call().effective_model || call().requested_model),
    providerName: computed(() => llm.value?.provider_name || call().provider_name),
    reasoningEffortLabel: computed(() => {
      const effort = call().reasoning_effort
      return effort ? t(`llm.reasoningEfforts.${effort}`) : null
    }),
    reasoningEffortBadgeColor: computed(() => {
      const effort = call().reasoning_effort
      return effort ? reasoningEffortColor(effort) : 'solaire-gray'
    }),
    callPurposeLabel: computed(() => {
      const value = call(), key = value.purpose ? `llmCalls.purposes.${value.purpose}` : ''
      return key ? te(key) ? t(key) : value.purpose : t(`llmCalls.callTypes.${value.call_type}`)
    }),
  }
}
