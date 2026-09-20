<template>
  <div class="llm-call" :style="callStyle">
    <div class="llm-call-header row no-wrap">
      <div class="agent-avatar-section flex flex-center">
        <img v-if="agentAvatarUrl" class="agent-photo" :src="agentAvatarUrl" :alt="agentName" />
        <q-icon v-else name="support_agent" :color="taskColor.name" size="42px" />
      </div>

      <div class="llm-call-content col q-px-sm q-py-xs">
        <div class="llm-call-summary row items-center q-gutter-xs no-wrap">
          <span class="agent-title ellipsis" :title="`${agentDisplayName} - ${callTitle}`">
            <span class="agent-name">{{ agentDisplayName }}</span>
            <span class="text-grey-7"> - {{ callTitle }}</span>
          </span>
          <q-space />
          <StatusBadge
            v-if="call.status !== 'running'"
            :tone="call.status === 'completed' ? 'success' : 'error'"
            :icon="call.status === 'completed' ? 'check_circle' : 'error'"
            :label="call.status === 'completed' ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
          />
          <q-spinner-dots v-else :color="taskColor.name" size="20px" />
          <q-badge v-if="call.duration" color="blue">
            <q-icon name="timer" size="xs" class="q-mr-xs" />
            {{ formatDuration(call.duration) }}
          </q-badge>
          <LlmCallTokenBadge :call="call" />
          <q-badge
            color="purple"
            :title="showApiCost
              ? t('llmCalls.inferenceCost', { cost: formatApiCost(call.inference_cost) })
              : undefined"
          >
            <q-icon name="attach_money" size="xs" class="q-mr-xs" />
            {{ formatBilledCost(call.cost) }}
          </q-badge>
        </div>

        <div class="call-identifiers q-mt-xs">
          <template v-if="call.task_id">
            <span class="task-uuid-link" :title="$t('llmCalls.task')" @click="taskDialog = true">
              {{ taskResourceUri(call.task_id) }}
            </span>
            <span class="text-grey-7">/</span>
          </template>
          <button
            type="button"
            class="call-id-copy"
            :title="$t('common.copyShort')"
            :aria-label="$t('common.copy')"
            @click="copyCallId"
          >
            {{ call.id }}
          </button>
        </div>

        <div class="call-meta row items-center q-gutter-xs text-caption text-grey-7 no-wrap">
          <span>{{ formatDate(call.started_at) }}</span>
          <q-badge class="llm-purpose-badge" outline :color="taskColor.name">
            {{ callPurposeLabel }}
          </q-badge>
          <q-badge class="llm-model-badge" outline :color="taskColor.name">{{ modelLabel }}</q-badge>
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
          <q-badge v-if="providerName" class="llm-outline-badge" color="teal" outline>
            {{ providerName }}
          </q-badge>
          <q-space />
          <q-btn
            flat
            dense
            size="sm"
            :icon="detailsExpanded ? 'expand_less' : 'expand_more'"
            :label="$t('llmCalls.details')"
            @click="detailsExpanded = !detailsExpanded"
          />
          <q-btn
            v-if="deletable"
            flat
            dense
            round
            color="negative"
            icon="delete_forever"
            :title="$t('llmCalls.deleteCall')"
            :aria-label="$t('llmCalls.deleteCall')"
            @click.stop="emit('delete', call)"
          />
        </div>
      </div>
    </div>
    <q-slide-transition>
      <div v-show="detailsExpanded" class="details">
        <LlmCallDetails :call="call" />
      </div>
    </q-slide-transition>

    <q-dialog v-model="taskDialog">
      <q-card class="task-dialog">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('llmCalls.task') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" />
        </q-card-section>

        <q-separator />

        <q-card-section>
          <TaskDetail :task-id="call.task_id ?? null" />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar } from 'quasar'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { StatusBadge } from '@/core/util'
import TaskDetail from '@/app/task/components/TaskDetail.vue'
import { taskResourceUri } from '@/app/task/resourceUri'
import LlmCallDetails from './LlmCallDetails.vue'
import LlmCallTokenBadge from './LlmCallTokenBadge.vue'
import { formatApiCost, formatBilledCost, reasoningEffortColor } from '../presentation'
import { useLLMProviderStore } from '../stores/llmProviderStore'
import type { LlmTaskColor } from '../taskColors'
import type { LLMCall } from '../types'

const props = withDefaults(defineProps<{
  call: LLMCall
  agentName?: string
  agentAvatarUrl?: string
  taskColor: LlmTaskColor
  deletable?: boolean
}>(), {
  agentName: undefined,
  agentAvatarUrl: undefined,
  deletable: false,
})

const emit = defineEmits<{
  delete: [call: LLMCall]
}>()

const { t, te, locale } = useI18n()
const $q = useQuasar()
const agentStore = useAgentStore()
const llmStore = useLLMProviderStore()
const detailsExpanded = ref(false)
const taskDialog = ref(false)

onMounted(() => {
  if (!llmStore.llms.length && !llmStore.loadingLLMs) void llmStore.fetchLLMs()
})

const llm = computed(() => llmStore.llms.find(item => item.id === props.call.llm_id))
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
const showApiCost = computed(() => props.call.inference_cost !== props.call.cost)
const callPurposeLabel = computed(() => {
  const purposeKey = props.call.purpose
    ? `llmCalls.purposes.${props.call.purpose}`
    : ''
  if (!purposeKey) return t(`llmCalls.callTypes.${props.call.call_type}`)
  return te(purposeKey) ? t(purposeKey) : props.call.purpose ?? purposeKey
})
const callTitle = computed(() => (
  props.call.task_label
  || props.call.process_label
  || callPurposeLabel.value
))

const agentDisplayName = computed(() => {
  const agent = props.call.agent_id
    ? agentStore.agents.find(item => item.id === props.call.agent_id)
    : undefined
  if (!agent) {
    return props.call.agent_name || props.agentName || t('llmCalls.internalService')
  }
  return `${agent.first_name} ${agent.last_name}`.trim()
})
const callStyle = computed(() => ({
  '--task-color': props.taskColor.hex,
  '--task-color-soft': `${props.taskColor.hex}12`,
}))

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  return `${seconds.toFixed(2)}s`
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value))
}

async function copyCallId(): Promise<void> {
  try {
    await copyToClipboard(props.call.id)
    $q.notify({ type: 'positive', message: t('common.copied') })
  } catch (error) {
    console.error('Unable to copy LLM call ID', error)
    $q.notify({ type: 'negative', message: t('common.copyError') })
  }
}
</script>

<style scoped>
.llm-call {
  border: 1px solid color-mix(in srgb, var(--task-color) 38%, transparent);
  border-left: 5px solid var(--task-color);
  border-radius: 8px;
  overflow: hidden;
  background: linear-gradient(135deg, var(--task-color-soft), transparent 42%);
}

.llm-call-header {
  min-height: 80px;
}

.agent-avatar-section {
  width: 92px;
  flex: 0 0 92px;
  overflow: hidden;
  background: color-mix(in srgb, var(--task-color) 12%, transparent);
  border-right: 1px solid color-mix(in srgb, var(--task-color) 22%, transparent);
}

.agent-photo {
  width: 100%;
  height: 100%;
  min-height: 80px;
  object-fit: cover;
  display: block;
}

.llm-call-content {
  min-width: 0;
}

.call-meta {
  min-height: 28px;
}

.llm-model-badge,
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

.call-meta :deep(.q-btn) {
  min-height: 28px;
}

.agent-title {
  min-width: 0;
  font-size: 1rem;
  font-weight: 600;
}

.agent-name {
  color: var(--task-color);
}

.call-identifiers {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  color: var(--task-color);
  font-family: monospace;
  font-size: 0.78rem;
  overflow-wrap: anywhere;
}

.call-id-copy {
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  overflow-wrap: anywhere;
}

.call-id-copy:hover,
.call-id-copy:focus-visible {
  text-decoration: underline;
}

.task-dialog {
  width: min(1100px, calc(100vw - 32px));
  max-width: 1100px;
}

.task-uuid-link {
  color: var(--task-color);
  text-decoration: none;
  cursor: pointer;
}

.task-uuid-link:hover {
  text-decoration: underline;
}

.details {
    background-color: white;
}

body.body--dark .details {
    background-color: #1d1d1d;
}

@media (max-width: 1023px) {
  .llm-call-header {
    min-height: 64px;
  }

  .agent-avatar-section {
    width: 64px;
    flex-basis: 64px;
  }

  .agent-photo {
    min-height: 64px;
  }

  .llm-call-summary,
  .call-meta {
    flex-wrap: wrap !important;
    row-gap: 4px;
  }

  .llm-call-content > .row > .q-space,
  .call-meta > .q-space {
    display: none;
  }

  .agent-title {
    flex: 1 1 100%;
  }

  .call-identifiers {
    align-items: flex-start;
    flex-wrap: wrap;
    font-size: 0.7rem;
  }

  .call-meta > span:first-child {
    flex: 1 1 100%;
  }

  .call-meta :deep(.q-btn) {
    margin-left: 0;
  }
}
</style>
