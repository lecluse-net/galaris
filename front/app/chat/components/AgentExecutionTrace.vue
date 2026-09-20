<template>
  <section v-if="visible" class="execution-trace" :class="{ 'execution-trace--error': hasError }">
    <button type="button" class="trace-summary" :aria-expanded="expanded" @click="toggleTrace">
      <q-icon :name="summaryIcon" class="summary-icon" />
      <span class="summary-label">{{ summaryLabel }}</span>
      <q-spinner-dots v-if="liveRound?.active" color="primary" size="22px" />
      <span
        v-for="(tool, index) in toolSummaries"
        :key="`${tool.name}:${index}`"
        class="tool-summary"
        :class="`tool-summary--${tool.tone}`"
      >
        <q-icon :name="tool.icon" />
        <span>{{ tool.name }}</span>
      </span>
      <span class="summary-tail">
        <span class="summary-metrics">
          <span>{{ formatDuration(summaryExecutionTime) }}</span>
          <span v-if="summaryCost > 0">{{ formatCost(summaryCost) }}</span>
        </span>
        <q-icon :name="expanded ? 'expand_less' : 'expand_more'" />
      </span>
    </button>

    <q-slide-transition>
      <div v-show="expanded" class="trace-detail">
        <div v-if="loading && !displayedExecutionResult" class="trace-loading"><q-spinner color="primary" size="22px" /></div>
        <div v-else>
          <div v-if="loadError" class="trace-error">{{ loadError }}</div>
          <ExecutionResultComponent
            :execution-result="displayedExecutionResult"
            :running="Boolean(liveRound?.active)"
            :llm-calls="llmCalls"
            :llm-calls-loading="llmCallsLoading"
            :llm-calls-error="llmCallsError"
            show-memory
            embedded
          >
            <template #details>
              <ConversationExecutionDetails
                :round="roundDetail"
                :status="detailStatus"
                :loading="loading"
                :calls="llmCalls"
                :calls-loading="llmCallsLoading"
                :calls-error="llmCallsError"
              />
            </template>
          </ExecutionResultComponent>
        </div>
      </div>
    </q-slide-transition>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { websocket } from '@/core/websocket'
import { conversationService, ConversationExecutionDetails, type ConversationRoundDetail } from '@/app/conversation'
import { ExecutionResultComponent, reconcileAIResult, type ExecutionResult } from '@/app/task'
import type { ConversationActivity, LiveAgentRound } from '../types'
import { conversationRoundId } from '../liveState'

const props = defineProps<{
  roomId: string
  activity?: ConversationActivity
  liveRound?: LiveAgentRound | null
}>()
const { t } = useI18n()
const expanded = ref(false)
const loading = ref(false)
const loadError = ref('')
const roundDetail = ref<ConversationRoundDetail | null>(null)
const bufferedExecutionResult = ref<{ roundId: string; result: ExecutionResult } | null>(null)
const llmCalls = ref<Awaited<ReturnType<typeof conversationService.llmCalls>>>([])
const llmCallsLoading = ref(false)
const llmCallsError = ref('')
const roundId = computed(() => conversationRoundId(props.activity, props.liveRound))
const detailStatus = computed(() => {
  if (props.liveRound?.active) return 'RUNNING'
  if (props.liveRound) return props.liveRound.success ? 'SUCCEEDED' : 'FAILED'
  return props.activity?.status ?? roundDetail.value?.status
})
let detailRequest = 0
type ConversationLlmCall = Awaited<ReturnType<typeof conversationService.llmCalls>>[number]

type ToolTone = 'web' | 'file' | 'task' | 'message' | 'media' | 'code' | 'calendar' | 'data' | 'default'
interface ToolSummary { name: string; icon: string; tone: ToolTone }

const visible = computed(() => Boolean(props.liveRound || props.activity))
const hasError = computed(() => Boolean(
  props.liveRound && !props.liveRound.active && !props.liveRound.success
  || props.activity && ['FAILED', 'ERROR_RESOLVED', 'CANCELLED'].includes(props.activity.status),
))
const summaryIcon = computed(() => hasError.value ? 'error' : props.liveRound?.active ? 'psychology' : 'settings_suggest')
const summaryLabel = computed(() => {
  if (hasError.value) return t('chat.executionProblem')
  if (props.liveRound?.active) return t('chat.thinking')
  return t('chat.executionDetail')
})
const liveMessages = computed(() => props.liveRound?.ai_result.messages || [])
const displayedExecutionResult = computed(() => {
  const result = reconcileAIResult(
    roundDetail.value?.execution_result ?? null,
    bufferedExecutionResult.value?.roundId === roundId.value
      ? bufferedExecutionResult.value.result
      : null,
  )
  if (!result) return null
  const hasDetail = Boolean(
    (result.messages?.length ?? 0)
    || result.prompt
    || result.system_prompt
    || result.result
    || result.tools_used.length
    || result.execution_time > 0
    || result.cost > 0,
  )
  return hasDetail ? result : null
})
const toolSummaries = computed<ToolSummary[]>(() => {
  let names: string[]
  if (props.liveRound) {
    names = liveMessages.value
      .filter(message => message.type === 'tool')
      .map(message => message.tool_name || 'tool')
  } else {
    names = props.activity?.tools_used ?? []
  }
  return names.filter(name => name.toLowerCase() !== 'thinking').map(name => ({ name, ...toolPresentation(name) }))
})
const summaryExecutionTime = computed(() => (
  props.liveRound ? props.liveRound.ai_result.execution_time || 0 : props.activity?.execution_time || 0
))
const summaryCost = computed(() => (
  props.liveRound ? props.liveRound.ai_result.cost || 0 : props.activity?.cost || 0
))

function eventData<T>(response: { data?: T } | T): T {
  return typeof response === 'object' && response !== null && 'data' in response && response.data !== undefined
    ? response.data
    : response as T
}

function mergeLlmCalls(
  snapshot: readonly ConversationLlmCall[],
  live: readonly ConversationLlmCall[],
): ConversationLlmCall[] {
  const calls = new Map(snapshot.map(call => [call.id, call]))
  for (const call of live) calls.set(call.id, call)
  return [...calls.values()].sort((left, right) => left.started_at.localeCompare(right.started_at))
}

function upsertLlmCall(call: ConversationLlmCall): void {
  if (call.conversation_round_id !== roundId.value) return
  llmCalls.value = mergeLlmCalls(
    llmCalls.value.filter(item => item.id !== call.id),
    [call],
  )
}

const onLlmCallCreate = (
  response: { data?: ConversationLlmCall } | ConversationLlmCall,
) => upsertLlmCall(eventData(response))
const onLlmCallUpdate = (
  response: { data?: ConversationLlmCall } | ConversationLlmCall,
) => upsertLlmCall(eventData(response))
const onLlmCallDelete = (response: { data?: { id: string } } | { id: string }) => {
  const { id } = eventData(response)
  llmCalls.value = llmCalls.value.filter(call => call.id !== id)
}
const onLlmCallCleanup = () => { if (expanded.value) void loadDetail() }

async function loadDetail(): Promise<void> {
  const currentRoundId = roundId.value
  if (!currentRoundId) return
  const request = ++detailRequest
  loading.value = true
  llmCallsLoading.value = true
  loadError.value = ''
  llmCallsError.value = ''
  const [roundResult, callsResult] = await Promise.allSettled([
    conversationService.getRound(currentRoundId),
    conversationService.llmCalls(currentRoundId),
  ])
  if (request !== detailRequest || currentRoundId !== roundId.value) return
  if (roundResult.status === 'fulfilled') {
    roundDetail.value = roundResult.value
  } else {
    loadError.value = apiErrorDetail(roundResult.reason) ?? t('chat.error')
  }
  if (callsResult.status === 'fulfilled') {
    llmCalls.value = mergeLlmCalls(callsResult.value, llmCalls.value)
  } else {
    llmCallsError.value = apiErrorDetail(callsResult.reason) ?? t('chat.error')
  }
  loading.value = false
  llmCallsLoading.value = false
}

async function toggleTrace(): Promise<void> {
  expanded.value = !expanded.value
  if (expanded.value) await loadDetail()
}

function toolPresentation(name: string): Pick<ToolSummary, 'icon' | 'tone'> {
  const normalized = name.toLowerCase()
  if (/(search|web|browser|url|http)/.test(normalized)) return { icon: 'travel_explore', tone: 'web' }
  if (/(file|document|memory|workspace)/.test(normalized)) return { icon: 'description', tone: 'file' }
  if (/(task|process|workflow|goal)/.test(normalized)) return { icon: 'account_tree', tone: 'task' }
  if (/(message|messenger|chat|mail|telegram|whatsapp|matrix)/.test(normalized)) return { icon: 'forum', tone: 'message' }
  if (/(image|photo|video|audio|voice|speech)/.test(normalized)) return { icon: 'perm_media', tone: 'media' }
  if (/(code|shell|exec|command|terminal)/.test(normalized)) return { icon: 'terminal', tone: 'code' }
  if (/(calendar|(^|[_:. -])(event|date|time)([_:. -]|$))/.test(normalized)) return { icon: 'event', tone: 'calendar' }
  if (/(database|query|sql|(^|[_:. -])data([_:. -]|$))/.test(normalized)) return { icon: 'storage', tone: 'data' }
  return { icon: 'build_circle', tone: 'default' }
}
function formatDuration(seconds: number): string { return seconds < 1 ? `${Math.round(seconds * 1_000)} ms` : `${seconds.toFixed(1)} s` }
function formatCost(cost: number): string { return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 4 }).format(cost) }

watch(roundId, () => {
  detailRequest += 1
  loading.value = false
  llmCallsLoading.value = false
  roundDetail.value = null
  llmCalls.value = []
  expanded.value = false
  loadError.value = ''
  llmCallsError.value = ''
})

watch(
  [() => props.liveRound?.active, () => props.activity?.status],
  ([active, status], [previousActive, previousStatus]) => {
    if (!expanded.value) return
    if ((active === false && previousActive === true) || status !== previousStatus) {
      void loadDetail()
    }
  },
)

watch(
  [roundId, () => props.liveRound?.ai_result],
  ([currentRoundId, liveResult]) => {
    if (!currentRoundId) {
      bufferedExecutionResult.value = null
      return
    }
    if (!liveResult) {
      if (bufferedExecutionResult.value?.roundId !== currentRoundId) {
        bufferedExecutionResult.value = null
      }
      return
    }
    const previous = bufferedExecutionResult.value?.roundId === currentRoundId
      ? bufferedExecutionResult.value.result
      : null
    bufferedExecutionResult.value = {
      roundId: currentRoundId,
      result: reconcileAIResult(previous, liveResult) ?? liveResult,
    }
  },
  { immediate: true },
)

onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('llm_call', 'create', onLlmCallCreate)
  websocket.onEvent('llm_call', 'update', onLlmCallUpdate)
  websocket.onEvent('llm_call', 'delete', onLlmCallDelete)
  websocket.onEvent('llm_call', 'cleanup', onLlmCallCleanup)
})

onBeforeUnmount(() => {
  detailRequest += 1
  websocket.offEvent('llm_call', 'create', onLlmCallCreate)
  websocket.offEvent('llm_call', 'update', onLlmCallUpdate)
  websocket.offEvent('llm_call', 'delete', onLlmCallDelete)
  websocket.offEvent('llm_call', 'cleanup', onLlmCallCleanup)
})
</script>

<style scoped>
.execution-trace { margin: 2px -9px 8px; overflow: hidden; color: var(--chat-text-secondary, #536071); background: var(--chat-surface-soft, #f5f7fa); border: 1px solid var(--chat-border, rgba(53, 69, 94, .1)); border-radius: 10px; }
.execution-trace:first-child { margin-top: -6px; }
.execution-trace--error { color: var(--q-negative); background: var(--chat-danger-soft, #fff1f1); border-color: color-mix(in srgb, var(--q-negative) 34%, transparent); }
.trace-summary { display: flex; width: 100%; min-height: 34px; align-items: center; flex-wrap: wrap; gap: 5px 7px; padding: 6px 9px; color: inherit; background: transparent; border: 0; font: inherit; text-align: left; cursor: pointer; }
.summary-icon { font-size: 18px; }
.summary-label { font-size: .75rem; font-weight: 650; }
.summary-tail { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; margin-left: auto; }
.summary-metrics { display: flex; gap: 7px; color: var(--chat-text-subtle, #8a93a2); font-size: .66rem; }
.tool-summary { display: inline-flex; min-width: 0; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 999px; font-size: .67rem; }
.tool-summary--web { color: #0d5f9f; background: #e3f2fd; }
.tool-summary--file { color: #6741a5; background: #eee7fb; }
.tool-summary--task { color: #00796b; background: #dff3ef; }
.tool-summary--message { color: #3f51a5; background: #e7eafb; }
.tool-summary--media { color: #a64b00; background: #fff0df; }
.tool-summary--code { color: #37474f; background: #e4ecef; }
.tool-summary--calendar { color: #2e7d32; background: #e5f4e7; }
.tool-summary--data { color: #8a3568; background: #f7e5f0; }
.tool-summary--default { color: var(--chat-text-secondary, #4e6177); background: var(--chat-surface-raised, #e8edf4); }
.trace-detail { max-height: min(720px, 72vh); padding: 4px 8px 8px; overflow: auto; background: var(--chat-surface-raised, #fff); border-top: 1px solid var(--chat-border, rgba(53, 69, 94, .09)); }
.trace-detail :deep(.exec-expansion) { margin-top: 0; }
.trace-detail :deep(.execution-result-shell) { margin-top: 0; background: transparent; border: 0; border-radius: 0; box-shadow: none; }
.trace-detail :deep(.execution-result-shell > .q-card__section) { padding: 2px 0 0; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs) { min-height: 26px; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-tab) { min-height: 26px; padding: 0 6px; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-tab__label) { font-size: .62rem; line-height: 1; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-icon) { font-size: 13px; }
.trace-loading { display: flex; min-height: 44px; align-items: center; justify-content: center; color: var(--chat-text-muted, #7b8493); }
.trace-error { padding: 8px; color: #a52f36; font-size: .72rem; }
</style>
