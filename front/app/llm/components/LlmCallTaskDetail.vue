<template>
  <q-expansion-item
    v-model="isExpanded"
    icon="memory"
    header-class="text-indigo text-subtitle2"
    class="llm-call-task-detail"
    dense
    toggle-indicator
  >
    <template v-slot:header>
      <q-item-section class="llm-call-main">
        <div class="llm-call-header-grid">
          <q-item-label class="llm-call-heading row items-center">
            <q-icon name="memory" color="indigo" size="20px" />
            <q-badge class="llm-purpose-badge" color="deep-purple" outline>
              {{ callPurposeLabel }}
            </q-badge>
            <span class="llm-label">{{ modelLabel }}</span>
            <q-badge
              v-if="reasoningEffortLabel"
              class="llm-outline-badge reasoning-effort-badge"
              :color="reasoningEffortBadgeColor"
              outline
            >
              <q-icon name="psychology" size="xs" class="q-mr-xs" />
              {{ reasoningEffortLabel }}
              <q-tooltip>{{ t('llm.reasoningEffort') }}</q-tooltip>
            </q-badge>
            <q-badge v-if="providerName" class="llm-outline-badge" color="indigo" outline>
              {{ providerName }}
            </q-badge>
          </q-item-label>

          <div class="llm-call-metrics row items-center">
            <template v-if="!running">
              <StatusBadge
                :tone="success ? 'success' : 'error'"
                :icon="success ? 'check_circle' : 'error'"
                :label="success ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
              />
              <q-badge v-if="call.duration" color="blue" size="sm">
                <q-icon name="timer" size="xs" class="q-mr-xs" />
                {{ formatExecutionTime(call.duration) }}
              </q-badge>
            </template>
            <q-spinner-dots v-else color="indigo" size="24px" />
            <LlmCallTokenBadge :call="call" />
            <q-badge
              color="purple"
              size="sm"
              :title="showApiCost
                ? t('llmCalls.inferenceCost', { cost: formatApiCost(call.inference_cost) })
                : undefined"
            >
              <q-icon name="attach_money" size="xs" class="q-mr-xs" />
              {{ formatBilledCost(call.cost) }}
            </q-badge>
            <q-btn
              v-if="deletable"
              flat
              dense
              round
              color="negative"
              icon="delete_forever"
              size="sm"
              :title="$t('llmCalls.deleteCall')"
              :aria-label="$t('llmCalls.deleteCall')"
              @click.stop="emit('delete', call)"
            />
          </div>
        </div>
        <q-item-label v-if="!isExpanded && preview" caption lines="2">
          {{ preview }}
        </q-item-label>
        <q-item-label v-else-if="running" caption class="text-indigo">
          {{ $t('llmCalls.streaming') }}
        </q-item-label>
      </q-item-section>
    </template>

    <q-card flat bordered class="q-mt-sm">
      <LlmCallDetails :call="call" />
    </q-card>
  </q-expansion-item>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { StatusBadge } from '@/core/util'
import LlmCallDetails from './LlmCallDetails.vue'
import LlmCallTokenBadge from './LlmCallTokenBadge.vue'
import {
  formatApiCost,
  formatBilledCost,
  formatExecutionTime,
  reasoningEffortColor,
} from '../presentation'
import { useLLMProviderStore } from '../stores/llmProviderStore'
import type { LLMCall } from '../types'

const props = withDefaults(defineProps<{
  call: LLMCall
  deletable?: boolean
}>(), {
  deletable: false,
})

const emit = defineEmits<{
  delete: [call: LLMCall]
}>()

const { t, te } = useI18n()
const store = useLLMProviderStore()
const isExpanded = ref(false)

// Resolve the label and provider through llm_id. Load the configured LLM list
// only once for the complete call list.
onMounted(() => {
  if (!store.llms.length && !store.loadingLLMs) void store.fetchLLMs()
})

const llm = computed(() => store.llms.find(item => item.id === props.call.llm_id))
const modelLabel = computed(() => llm.value?.label || props.call.effective_model || props.call.requested_model)
const providerName = computed(() => llm.value?.provider_name || props.call.provider_name)
const reasoningEffortLabel = computed(() => {
  const effort = props.call.reasoning_effort
  return effort ? t(`llm.reasoningEfforts.${effort}`) : null
})
const reasoningEffortBadgeColor = computed(() => {
  const effort = props.call.reasoning_effort
  return effort ? reasoningEffortColor(effort) : 'grey-7'
})
const callPurposeLabel = computed(() => {
  const purposeKey = props.call.purpose
    ? `llmCalls.purposes.${props.call.purpose}`
    : ''
  if (!purposeKey) return t(`llmCalls.callTypes.${props.call.call_type}`)
  return te(purposeKey) ? t(purposeKey) : props.call.purpose ?? purposeKey
})

const running = computed(() => props.call.status === 'running')
const success = computed(() => props.call.status === 'completed')
const showApiCost = computed(() => props.call.inference_cost !== props.call.cost)
const preview = computed(() => props.call.response_text?.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim() || '')
</script>

<style scoped>
.llm-call-task-detail :deep(.q-expansion-item__container) {
  border-radius: 8px;
}

.llm-call-task-detail :deep(.q-expansion-item__header) {
  border-radius: 8px;
}

.llm-call-main,
.llm-call-heading {
  min-width: 0;
}

.llm-call-header-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px 12px;
}

.llm-call-heading,
.llm-call-metrics {
  flex-wrap: wrap;
  gap: 4px;
}

.llm-call-metrics {
  justify-content: flex-end;
}

.llm-label {
  min-width: 0;
  font-weight: 500;
  line-height: 20px;
  overflow-wrap: anywhere;
}

.llm-outline-badge {
  height: 20px;
}

.llm-purpose-badge {
  height: auto;
  min-height: 20px;
  max-width: 100%;
  padding-block: 3px;
  white-space: normal;
  line-height: 1.2;
  overflow-wrap: anywhere;
  text-align: left;
}

@media (max-width: 1023px) {
  .llm-call-task-detail :deep(.q-expansion-item__header) {
    align-items: flex-start;
    padding: 10px 8px 10px 12px;
  }

  .llm-call-header-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .llm-call-metrics {
    justify-content: flex-start;
  }
}
</style>
