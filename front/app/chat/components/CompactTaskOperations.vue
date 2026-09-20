<template>
  <div v-if="visible" class="compact-operations">
    <div
      v-if="showSummary && (hiddenCount || props.executionResult)"
      class="compact-operation compact-operation--summary"
    >
      <span v-if="hiddenCount" class="compact-summary-label">
        <q-icon name="more_horiz" size="16px" />
        <span>{{ t('chat.previousOperations', { count: hiddenCount }) }}</span>
      </span>
      <span class="compact-summary-metrics">
        <q-badge color="blue-7" class="compact-summary-badge">
          <q-icon name="timer" size="13px" />
          {{ formatDuration(props.executionResult?.execution_time ?? 0) }}
        </q-badge>
        <q-badge color="purple-6" class="compact-summary-badge">
          <q-icon name="attach_money" size="13px" />
          {{ formatCost(props.executionResult?.cost ?? 0) }}
        </q-badge>
      </span>
    </div>
    <div
      v-for="operation in showOperations ? operations : []"
      :key="operation.index"
      class="compact-operation"
      :class="{
        'compact-operation--tool': operation.kind === 'tool',
        'compact-operation--thinking': operation.kind === 'thinking',
        'compact-operation--stream-tail': operation.kind === 'text' || operation.kind === 'thinking',
        'compact-operation--error': operation.step.success === false,
      }"
    >
      <div class="compact-operation-heading">
        <q-icon :name="operation.icon" :color="operation.color" size="16px" class="compact-operation-icon" />
        <span class="compact-operation-label">{{ operation.label }}</span>
        <q-spinner-dots
          v-if="running && operation.index === lastIndex"
          color="primary"
          size="15px"
          class="compact-operation-spinner"
        />
      </div>
      <div
        v-if="operation.arguments.length || operation.preview"
        class="compact-operation-body"
      >
        <table
          v-if="operation.arguments.length"
          class="compact-arguments-table"
          :aria-label="t('chat.arguments')"
        >
          <tbody>
            <tr v-for="argument in operation.arguments" :key="argument.name">
              <th scope="row" :title="argument.name"><code>{{ argument.name }}</code></th>
              <td :title="argument.value"><code>{{ argument.value }}</code></td>
            </tr>
          </tbody>
        </table>
        <span v-if="operation.preview" class="compact-operation-preview">
          {{ operation.preview }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { shouldAnimateTaskStatus, type AIMessage, type ExecutionResult, type TaskStatus } from '@/app/task'
import { compactStreamingTail } from '../compactTaskOperations'

const MAX_VISIBLE_OPERATIONS = 4
const MAX_TOOL_PREVIEW_CHARS = 1_000

const props = withDefaults(defineProps<{
  executionResult?: ExecutionResult
  status: TaskStatus
  paused?: boolean
  operationalState?: 'QUEUED' | 'RUNNING' | 'WAITING' | 'PAUSED' | 'TERMINAL'
  display?: 'all' | 'summary' | 'operations'
}>(), {
  paused: false,
  display: 'all',
})
const { t } = useI18n()

type OperationKind = 'thinking' | AIMessage['type']
interface CompactOperation {
  index: number
  step: AIMessage
  kind: OperationKind
  icon: string
  color: string
  label: string
  arguments: CompactArgument[]
  preview: string
}
interface CompactArgument { name: string; value: string }

const running = computed(() => shouldAnimateTaskStatus(props))
const allOperations = computed<CompactOperation[]>(() => (
  (props.executionResult?.messages ?? []).map((step, index) => {
    const kind = step.type === 'tool' && step.tool_name === 'thinking' ? 'thinking' : step.type
    return {
      index,
      step,
      kind,
      icon: operationIcon(kind),
      color: step.success === false ? 'negative' : operationColor(kind),
      label: operationLabel(step, kind),
      arguments: kind === 'tool' ? operationArguments(step.tool_arguments) : [],
      preview: operationPreview(step, kind),
    }
  })
))
const operations = computed(() => allOperations.value.slice(-MAX_VISIBLE_OPERATIONS))
const hiddenCount = computed(() => Math.max(0, allOperations.value.length - operations.value.length))
const showSummary = computed(() => props.display !== 'operations')
const showOperations = computed(() => props.display !== 'summary')
const visible = computed(() => (
  showSummary.value && (hiddenCount.value > 0 || Boolean(props.executionResult))
  || showOperations.value && operations.value.length > 0
))
const lastIndex = computed(() => allOperations.value.at(-1)?.index ?? -1)

function operationLabel(step: AIMessage, kind: OperationKind): string {
  if (step.success === false && step.type !== 'tool') return t('chat.interactionError')
  if (kind === 'thinking') return t('chat.interactionThinking')
  if (step.type === 'tool') return step.tool_name || 'tool'
  return t('chat.aiMessage')
}

function operationPreview(step: AIMessage, kind: OperationKind): string {
  const normalized = (step.content || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/[`*_>#-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (kind === 'text' || kind === 'thinking') return compactStreamingTail(normalized)
  return normalized.length > MAX_TOOL_PREVIEW_CHARS
    ? `${normalized.slice(0, MAX_TOOL_PREVIEW_CHARS - 1).trim()}…`
    : normalized
}

function operationArguments(argumentsValue?: Record<string, unknown>): CompactArgument[] {
  return Object.entries(argumentsValue ?? {}).map(([name, value]) => ({
    name,
    value: formatArgumentValue(value),
  }))
}

function formatArgumentValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === undefined) return 'undefined'
  try { return JSON.stringify(value) ?? String(value) }
  catch { return String(value) }
}

function formatDuration(seconds: number): string {
  return seconds < 1 ? `${Math.round(seconds * 1_000)} ms` : `${seconds.toFixed(1)} s`
}

function formatCost(cost: number): string {
  const formatted = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(cost)
  return formatted
}

function operationIcon(kind: OperationKind): string {
  return {
    thinking: 'psychology',
    tool: 'build',
    text: 'article',
    image: 'image',
    audio: 'audiotrack',
    video: 'videocam',
  }[kind]
}

function operationColor(kind: OperationKind): string {
  return {
    thinking: 'amber-9',
    tool: 'teal',
    text: 'primary',
    image: 'purple',
    audio: 'orange',
    video: 'deep-purple',
  }[kind]
}
</script>

<style scoped>
.compact-operations { display: grid; gap: 2px; margin-top: 3px; }
.compact-operation { display: block; min-width: 0; color: var(--chat-task-text-muted, #475467); font-size: var(--chat-task-font-size, .8rem); line-height: 1.28; }
.compact-operation:not(.compact-operation--summary) { padding: 2px 4px 3px 5px; border-left: 2px solid var(--chat-operation-border, rgba(71, 84, 103, .25)); border-radius: 0 3px 3px 0; background: var(--chat-operation-soft, rgba(71, 84, 103, .035)); }
.compact-operation--tool { --chat-operation-border: rgba(0, 137, 123, .48); --chat-operation-soft: rgba(0, 137, 123, .045); }
.compact-operation--thinking { --chat-operation-border: rgba(245, 158, 11, .55); --chat-operation-soft: rgba(245, 158, 11, .055); }
.compact-operation--error { --chat-operation-border: rgba(193, 0, 21, .62); --chat-operation-soft: rgba(193, 0, 21, .045); }
.compact-operation-heading { display: flex; width: 100%; min-width: 0; align-items: flex-start; gap: 4px; }
.compact-operation-icon { flex: 0 0 auto; margin-top: -1px; }
.compact-operation-label { flex: 1 1 auto; min-width: 0; color: var(--chat-text, #344054); overflow-wrap: anywhere; font-weight: 650; }
.compact-operation-body { min-width: 0; margin-left: 20px; }
.compact-arguments-table { width: 100%; margin: 2px 0 1px; table-layout: auto; overflow: hidden; border: 1px solid var(--chat-border, rgba(35, 46, 66, .09)); border-collapse: separate; border-spacing: 0; border-radius: 3px; color: var(--chat-task-text-muted, #475467); background: var(--chat-parameters-bg, #fff); font-size: inherit; line-height: 1.15; }
.compact-arguments-table th,.compact-arguments-table td { height: 16px; padding: 0 3px; overflow: hidden; border-bottom: 1px solid var(--chat-border, rgba(35, 46, 66, .09)); background: transparent; text-align: left; white-space: nowrap; }
.compact-arguments-table tr:last-child th,.compact-arguments-table tr:last-child td { border-bottom: 0; }
.compact-arguments-table th { width: 1%; max-width: 40%; color: var(--chat-text, #344054); font-weight: 650; }
.compact-arguments-table td { width: 99%; max-width: 0; padding-right: 0; font-weight: 400; }
.compact-arguments-table code { display: block; overflow: hidden; font: inherit; text-overflow: ellipsis; white-space: nowrap; }
.compact-operation-preview { display: block; min-width: 0; margin-top: 1px; color: var(--chat-task-text-muted, #475467); overflow-wrap: anywhere; }
.compact-operation--stream-tail .compact-operation-preview { display: -webkit-box; max-height: 2.56em; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; }
.compact-operation--tool .compact-operation-preview { display: -webkit-box; max-height: 6.4em; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 5; line-clamp: 5; }
.compact-operation-spinner { flex: 0 0 auto; margin-left: 1px; }
.compact-operation--error,.compact-operation--error .compact-operation-preview { color: var(--q-negative); }
.compact-operation--summary { display: flex; min-width: 0; align-items: center; gap: 6px; color: var(--chat-task-text-subtle, #667085); }
.compact-summary-label { display: flex; min-width: 0; flex: 1 1 auto; align-items: center; gap: 4px; }
.compact-summary-label > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compact-summary-metrics { display: flex; flex: 0 0 auto; gap: 4px; margin-left: auto; white-space: nowrap; }
.compact-summary-badge { display: inline-flex; align-items: center; gap: 2px; padding: 2px 5px; font-size: inherit; line-height: 1.1; }
</style>
