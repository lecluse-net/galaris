<template>
  <q-tabs
    v-model="activeTab"
    dense
    class="llm-call-tabs text-grey"
    inline-label
    active-color="primary"
    indicator-color="primary"
    align="left"
    narrow-indicator
  >
    <q-tab name="trace" class="llm-call-tab">
      <div class="llm-call-tab__content row items-center no-wrap">
        <q-icon name="hub" size="16px" />
        <span>{{ $t('task.execution.thoughtSteps') }}</span>
      </div>
    </q-tab>
    <q-tab name="prompt" class="llm-call-tab">
      <div class="llm-call-tab__content row items-center no-wrap">
        <q-icon name="message" size="16px" />
        <span>{{ $t('task.dispatch.prompt') }}</span>
      </div>
    </q-tab>
    <q-tab name="system-prompt" class="llm-call-tab">
      <div class="llm-call-tab__content row items-center no-wrap">
        <q-icon name="settings" size="16px" />
        <span>{{ $t('task.dispatch.systemPrompt') }}</span>
      </div>
    </q-tab>
    <q-tab name="response" class="llm-call-tab">
      <div class="llm-call-tab__content row items-center no-wrap">
        <q-icon name="reply" size="16px" />
        <span>{{ $t('llmCalls.response') }}</span>
      </div>
    </q-tab>
  </q-tabs>

  <q-separator />

  <q-tab-panels v-model="activeTab" animated>
    <q-tab-panel name="trace">
      <div v-if="executionResult?.messages?.length" class="trace-timeline">
        <div
          v-for="(step, index) in executionResult.messages"
          :key="index"
          class="timeline-item"
        >
          <div class="timeline-connector">
            <div class="timeline-dot" :class="'timeline-dot-' + stepKind(step)"></div>
            <div v-if="index < executionResult.messages.length - 1" class="timeline-line"></div>
          </div>

          <div class="timeline-content-col">
            <div class="timeline-header" @click="toggleStep(index)">
              <div class="timeline-header-left">
                <q-icon :name="getStepIcon(step)" :color="getStepColor(step)" size="xs" class="q-mr-xs" />
                <span v-if="stepKind(step) === 'thinking'" class="text-caption text-amber-9">
                  {{ $t('task.execution.thinking') }}
                </span>
                <span v-else-if="step.type === 'tool'" class="tool-name text-body2">{{ step.tool_name }}</span>
                <span v-else class="text-caption text-grey">{{ $t('task.execution.ai') }}</span>
              </div>
              <div class="timeline-header-right">
                <span class="text-caption text-grey q-mr-sm">{{ truncateContent(step.content) }}</span>
                <q-badge
                  v-if="step.execution_time !== undefined && step.execution_time > 0"
                  color="blue"
                  size="sm"
                  class="q-mr-xs"
                >
                  <q-icon name="timer" size="xs" class="q-mr-xs" />
                  {{ formatExecutionTime(step.execution_time) }}
                </q-badge>
                <q-badge
                  v-if="step.cost !== undefined && step.cost > 0"
                  color="purple"
                  size="sm"
                  class="q-mr-xs"
                >
                  <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                  {{ formatCostShort(step.cost) }}
                </q-badge>
                <q-icon :name="expandedSteps.has(index) ? 'expand_less' : 'expand_more'" size="xs" />
              </div>
            </div>

            <q-slide-transition>
              <div v-show="expandedSteps.has(index)" class="timeline-expanded">
                <q-card v-if="step.type !== 'tool'" flat bordered class="trace-card">
                  <q-card-section class="q-py-xs q-px-sm">
                    <Markdown :content="step.content" />
                  </q-card-section>
                </q-card>

                <q-card
                  v-else
                  flat
                  bordered
                  class="trace-card tool-card"
                  :class="{ 'thinking-card': stepKind(step) === 'thinking' }"
                >
                  <q-card-section class="q-py-xs q-px-sm">
                    <q-table
                      v-if="step.tool_arguments && Object.keys(step.tool_arguments).length"
                      :rows="formatArgumentsToTable(step.tool_arguments)"
                      :columns="argumentColumns"
                      row-key="name"
                      flat
                      dense
                      bordered
                      hide-pagination
                      :pagination="{ rowsPerPage: 0 }"
                      class="arguments-table q-mb-xs"
                    >
                      <template #body-cell-name="tableProps">
                        <td class="text-left">
                          <code class="argument-name">{{ tableProps.value }}</code>
                        </td>
                      </template>
                      <template #body-cell-value="tableProps">
                        <td class="text-left">
                          <code class="argument-value">{{ tableProps.value }}</code>
                        </td>
                      </template>
                    </q-table>

                    <Markdown :content="step.content" />
                  </q-card-section>
                </q-card>
              </div>
            </q-slide-transition>
          </div>
        </div>
      </div>
      <div v-else class="trace-timeline">
        <div class="timeline-item timeline-item--pending">
          <div class="timeline-connector">
            <div class="timeline-dot timeline-dot-pending"></div>
          </div>
          <div class="timeline-content-col">
            <div class="timeline-header timeline-header--pending">
              <div class="timeline-header-left">
                <q-icon name="pending" color="grey-7" size="xs" class="q-mr-xs" />
                <span class="text-caption text-grey">
                  {{ props.call.status === 'running'
                    ? $t('task.execution.starting')
                    : $t('task.execution.noTrace') }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </q-tab-panel>

    <q-tab-panel name="prompt" class="q-pa-none">
      <CodeEditor
        v-if="props.call.prompt"
        :model-value="props.call.prompt"
        language="markdown"
        readonly
        :show-error="false"
        :visible-lines="24"
      />
      <div v-else class="text-grey text-center q-pa-md">
        {{ $t('task.dispatch.noPrompt') }}
      </div>
    </q-tab-panel>

    <q-tab-panel name="system-prompt" class="q-pa-none">
      <CodeEditor
        v-if="props.call.system_prompt"
        :model-value="props.call.system_prompt"
        language="markdown"
        readonly
        :show-error="false"
        :visible-lines="24"
      />
      <div v-else class="text-grey text-center q-pa-md">
        {{ $t('task.dispatch.noSystemPrompt') }}
      </div>
    </q-tab-panel>

    <q-tab-panel name="response" class="q-pa-none">
      <CodeEditor
        v-if="hasFinalResponse"
        :model-value="formattedFinalResponse"
        language="json"
        readonly
        :show-error="false"
        :visible-lines="24"
      />
      <div v-else class="text-grey text-center q-pa-md">
        {{ $t('llmCalls.noResponse') }}
      </div>
    </q-tab-panel>

  </q-tab-panels>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeEditor, Markdown } from '@/core/util'
import type { AIMessage } from '@/app/task/types'
import { callExecutionResult, formatCostShort, formatExecutionTime } from '../presentation'
import type { LLMCall } from '../types'

const props = defineProps<{
  call: LLMCall
}>()

const { t } = useI18n()

const executionResult = computed(() => callExecutionResult(
  props.call,
  t('task.llmCalls.toolPending'),
  {
    contextTitle: t('llmCalls.context.title'),
    contextKey: t('llmCalls.context.key'),
    contextValue: t('llmCalls.context.value'),
  },
))

const hasFinalResponse = computed(() => Boolean(
  props.call.response_text
  || props.call.reasoning
  || props.call.tool_calls.length
  || Object.keys(props.call.usage).length
  || props.call.finish_reason,
))

const formattedFinalResponse = computed((): string => JSON.stringify({
  id: props.call.upstream_request_id ?? null,
  model: props.call.effective_model,
  response: props.call.response_text || null,
  reasoning: props.call.reasoning || null,
  tool_calls: props.call.tool_calls,
  finish_reason: props.call.finish_reason ?? null,
  usage: props.call.usage,
}, null, 2))

const activeTab = ref('trace')
const expandedSteps = ref<Set<number>>(new Set())

watch(
  () => executionResult.value?.messages?.length,
  (newLength) => {
    if (newLength && newLength > 0) {
      expandedSteps.value.add(newLength - 1)
    }
  },
  { immediate: true },
)

const toggleStep = (index: number): void => {
  if (expandedSteps.value.has(index)) {
    expandedSteps.value.delete(index)
  } else {
    expandedSteps.value.add(index)
  }
}

const truncateContent = (content: string | null): string => {
  if (!content) return ''
  const stripped = content.replace(/<[^>]*>/g, '').replace(/\n/g, ' ').trim()
  return stripped.length > 50 ? `${stripped.substring(0, 50)}...` : stripped
}

const stepKind = (step: AIMessage): string => {
  if (step.type === 'tool' && step.tool_name === 'thinking') return 'thinking'
  return step.type
}

const getStepColor = (step: AIMessage): string => {
  switch (stepKind(step)) {
    case 'text': return 'primary'
    case 'image': return 'purple'
    case 'audio': return 'orange'
    case 'video': return 'deep-purple'
    case 'tool': return 'teal'
    case 'thinking': return 'amber-9'
    default: return 'grey'
  }
}

const getStepIcon = (step: AIMessage): string => {
  switch (stepKind(step)) {
    case 'text': return 'article'
    case 'image': return 'image'
    case 'audio': return 'audiotrack'
    case 'video': return 'videocam'
    case 'tool': return 'build'
    case 'thinking': return 'psychology'
    default: return 'help'
  }
}

const formatArgumentsToTable = (args: Record<string, unknown>): Array<{ name: string; value: string }> => (
  Object.entries(args).map(([name, value]) => ({
    name,
    value: typeof value === 'object' ? JSON.stringify(value) : String(value),
  }))
)

const argumentColumns = computed(() => [
  { name: 'name', label: t('task.execution.argument'), field: 'name', align: 'left' as const },
  { name: 'value', label: t('task.execution.value'), field: 'value', align: 'left' as const },
])
</script>

<style scoped>
.q-tab-panels {
  background: transparent;
}

.llm-call-tabs {
  height: 30px !important;
  min-height: 30px !important;
  font-size: 12px;
}

.llm-call-tabs :deep(.q-tabs__content),
.llm-call-tabs :deep(.q-tab),
.llm-call-tab {
  height: 30px !important;
  min-height: 30px !important;
}

.llm-call-tabs :deep(.q-tab),
.llm-call-tab {
  padding: 0 5px !important;
}

.llm-call-tabs :deep(.q-tab__content) {
  min-width: 0;
  min-height: 30px;
  padding: 0;
  flex-direction: row;
  line-height: 1;
}

.llm-call-tab__content {
  gap: 3px;
  font-size: 12px;
  line-height: 1;
}

.llm-call-tabs :deep(.q-tab__indicator) {
  height: 1px;
}

.trace-card {
  border-left: 3px solid #ccc;
}

.trace-card.tool-card {
  border-left-color: #00bcd4;
}

.trace-card.tool-card.thinking-card {
  border-left-color: #ff8f00;
  background: rgba(255, 193, 7, 0.06);
}

.arguments-table {
  font-size: 0.85em;
  margin: 0;
  border-bottom: 1px solid #e0e0e0;
}

.arguments-table :deep(.q-table) {
  table-layout: fixed;
  width: 100%;
}

.arguments-table :deep(.q-table__middle) {
  overflow-x: hidden;
}

.arguments-table :deep(td:first-child),
.arguments-table :deep(th:first-child) {
  width: 30%;
}

.arguments-table :deep(.q-table__top) {
  display: none;
}

.arguments-table :deep(th) {
  font-weight: 600;
  background: #f5f5f5;
  padding: 4px 8px;
}

.arguments-table :deep(td) {
  padding: 4px 8px;
  vertical-align: top;
}

.arguments-table :deep(.q-table tbody tr:last-child td) {
  border-bottom: none;
}

.argument-name,
.argument-value {
  display: inline-block;
  max-width: 100%;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.argument-name {
  color: #00897b;
  font-weight: 500;
}

.argument-value {
  color: #333;
}

body.body--dark .argument-name {
  color: #4db6ac;
}

body.body--dark .argument-value {
  color: #d0d0d0;
}

.trace-timeline {
  display: flex;
  flex-direction: column;
}

.timeline-item {
  display: flex;
  flex-direction: row;
  min-height: 32px;
}

.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex-shrink: 0;
}

.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ccc;
  flex-shrink: 0;
  margin-top: 8px;
}

.timeline-dot-text { background: #1976d2; }
.timeline-dot-image { background: #9c27b0; }
.timeline-dot-audio { background: #ff9800; }
.timeline-dot-video { background: #673ab7; }
.timeline-dot-tool { background: #009688; }
.timeline-dot-thinking { background: #ff8f00; }
.timeline-dot-pending { background: #9e9e9e; }

.timeline-line {
  width: 2px;
  flex: 1;
  min-height: 20px;
  background: #e0e0e0;
}

body.body--dark .timeline-line {
  background: #3a3f47;
}

.timeline-content-col {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: 1;
  padding: 4px 8px;
  background: #f5f5f5;
  border-radius: 4px;
  cursor: pointer;
  margin: 4px 0;
}

.timeline-header:hover {
  background: #eee;
}

.timeline-header--pending,
.timeline-header--pending:hover {
  cursor: default;
  background: #f5f5f5;
}

body.body--dark .arguments-table :deep(th),
body.body--dark .timeline-header {
  background: #2a2a2a;
}

body.body--dark .timeline-header:hover {
  background: #333;
}

body.body--dark .timeline-header--pending,
body.body--dark .timeline-header--pending:hover {
  background: #2a2a2a;
}

.timeline-header-left,
.timeline-header-right {
  display: flex;
  align-items: center;
}

.timeline-expanded {
  padding: 4px 0;
}

.tool-card .q-card__section {
  max-height: 300px;
  overflow-y: auto;
  overflow-x: hidden;
}

.tool-card :deep(.markdown-content pre) {
  overflow-x: visible;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.tool-card :deep(.markdown-content pre code),
.tool-card :deep(.markdown-content code) {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
</style>
