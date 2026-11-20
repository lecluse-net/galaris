<template>
  <ChatExecutionDetails v-if="visible" :key="roundId ?? roomId" v-model:expanded="expanded"
    :label="summaryLabel" :icon="summaryIcon" :tools="toolNames" :running="Boolean(liveRound?.active)"
    :error="hasError" :warning="rewriting" :execution-time="summaryExecutionTime" :cost="summaryCost"
    @open="loadDetail"
  >
    <template v-if="canControl && actions.length" #controls>
      <q-btn v-for="action in actions" :key="action" flat round dense size="sm"
        :icon="controlIcons[action]" :aria-label="t(`chat.responseControl.${action}`)"
        :disable="pendingAction !== null" :loading="pendingAction === action"
        @click="control(action)">
        <q-tooltip>{{ t(`chat.responseControl.${action}Hint`) }}</q-tooltip>
      </q-btn>
    </template>
    <template #notice>
      <div v-if="controlError" class="trace-error" role="alert">{{ controlError }}</div>
    </template>
        <div v-if="loading && !displayedExecutionResult" class="trace-loading"><q-spinner color="primary" size="22px" /></div>
        <div v-else>
          <div v-if="loadError" class="trace-error">{{ loadError }}</div>
          <ExecutionResultComponent
            :execution-result="displayedExecutionResult"
            :running="Boolean(liveRound?.active)"
            :suspended="waitingForAuthorization"
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
  </ChatExecutionDetails>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore, privileges } from '@/core/authorize'
import { apiErrorDetail } from '@/core/api'
import { websocket } from '@/core/websocket'
import { conversationService, ConversationExecutionDetails, useConversationCallProgress, type ConversationRoundDetail } from '@/app/conversation'
import { ExecutionResultComponent, reconcileAIResult, type ExecutionResult } from '@/app/task'
import type { ConversationActivity, ConversationControlAction, LiveAgentRound } from '../types'
import { chatService } from '../services/chatService'
import { conversationRoundId } from '../liveState'
import ChatExecutionDetails from './ChatExecutionDetails.vue'

const props = defineProps<{
  roomId: string
  activity?: ConversationActivity
  liveRound?: LiveAgentRound | null
  allowControl?: boolean
}>()
const emit = defineEmits<{ controlled: [] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const pendingAction = ref<ConversationControlAction | null>(null)
const controlError = ref('')
const actions = computed(() => (props.activity?.available_actions ?? []).filter(action => action !== 'respond'))
const canControl = computed(() => props.allowControl && privilegeStore.hasPrivilege(privileges.CHAT_SEND))
const controlIcons: Record<ConversationControlAction, string> = {
  pause: 'pause', stop: 'stop', resume: 'play_arrow', restart: 'replay', respond: 'quickreply',
}
async function control(action: ConversationControlAction): Promise<void> {
  const id = roundId.value
  if (!id || pendingAction.value || !canControl.value) return
  const roomId = props.roomId
  pendingAction.value = action
  controlError.value = ''
  try {
    await chatService.controlResponse(roomId, id, action, Math.max(props.activity?.attempt ?? 0, props.liveRound?.attempt ?? 0))
    if (roomId !== props.roomId || id !== roundId.value) return
    emit('controlled')
  } catch (error) {
    if (roomId !== props.roomId || id !== roundId.value) return
    controlError.value = apiErrorDetail(error) ?? t('chat.responseControl.error')
    emit('controlled')
  } finally {
    if (roomId === props.roomId && id === roundId.value) pendingAction.value = null
  }
}
const expanded = ref(false)
const loading = ref(false)
const loadError = ref('')
const roundDetail = ref<ConversationRoundDetail | null>(null)
const bufferedExecutionResult = ref<{ roundId: string; result: ExecutionResult } | null>(null)
const llmCalls = ref<Awaited<ReturnType<typeof conversationService.llmCalls>>>([])
const llmCallsLoading = ref(false)
const llmCallsError = ref('')
const roundId = computed(() => conversationRoundId(props.activity, props.liveRound))
const waitingForAuthorization = computed(() => {
  if (props.liveRound?.active) return false
  if (props.liveRound?.ai_result.disposition) {
    return props.liveRound.ai_result.disposition === 'waiting_for_authorization'
  }
  return (props.activity?.status ?? roundDetail.value?.status) === 'WAITING_APPROVAL'
})
const detailStatus = computed(() => {
  if (props.activity && ['PAUSED', 'CANCELLED'].includes(props.activity.status)) return props.activity.status
  if (props.liveRound?.active) return 'RUNNING'
  if (waitingForAuthorization.value) return 'WAITING_APPROVAL'
  if (props.liveRound) return props.liveRound.success ? 'SUCCEEDED' : 'FAILED'
  return props.activity?.status ?? roundDetail.value?.status
})
let detailRequest = 0
type ConversationLlmCall = Awaited<ReturnType<typeof conversationService.llmCalls>>[number]

const visible = computed(() => Boolean(props.liveRound || props.activity))
const rewriting = computed(() => !props.activity?.control_action && !props.activity?.response_only
  && !['PAUSED', 'CANCELLED'].includes(props.activity?.status ?? '') && Boolean(
  props.activity?.status === 'SUPERSEDED'
  || props.liveRound?.ai_result.metadata?.interrupted_by_new_input === true,
))
const hasError = computed(() => !waitingForAuthorization.value && !['PAUSED', 'CANCELLED'].includes(props.activity?.status ?? '') && !rewriting.value && Boolean(
  props.liveRound && !props.liveRound.active && !props.liveRound.success
  || props.activity && ['FAILED', 'ERROR_RESOLVED', 'CANCELLED'].includes(props.activity.status),
))
const summaryIcon = computed(() => props.activity?.status === 'PAUSED' ? 'pause' : props.activity?.status === 'CANCELLED' ? 'stop' : waitingForAuthorization.value ? 'hourglass_top' : rewriting.value ? 'autorenew' : hasError.value ? 'error' : props.liveRound?.active ? 'psychology' : 'settings_suggest')
const summaryLabel = computed(() => {
  if (props.activity?.control_action === 'pause') return t('chat.responseControl.pausing')
  if (props.activity?.control_action === 'stop') return t('chat.responseControl.stopping')
  if (props.activity?.control_action === 'respond') return t('chat.responseControl.responding')
  if (props.activity?.status === 'PAUSED') return t('chat.responseControl.paused')
  if (props.activity?.status === 'CANCELLED') return t('chat.responseControl.stopped')
  if (waitingForAuthorization.value) return t('conversation.history.statuses.WAITING_APPROVAL')
  if (props.liveRound?.active && props.activity?.response_only) return t('chat.responseControl.responding')
  if (rewriting.value) return t('chat.rewritingResponse')
  if (hasError.value) return t('chat.executionProblem')
  if (props.liveRound?.active) return ''
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
const toolNames = computed(() => {
  let names: string[]
  if (props.liveRound) {
    names = liveMessages.value
      .filter(message => message.type === 'tool')
      .map(message => message.tool_name || 'tool')
  } else {
    names = props.activity?.tools_used ?? []
  }
  return names
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
useConversationCallProgress(id => llmCalls.value.find(call => call.id === id), upsertLlmCall)
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

watch(roundId, () => {
  pendingAction.value = null
  controlError.value = ''
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
.trace-loading { display: flex; min-height: 44px; align-items: center; justify-content: center; color: var(--chat-text-muted, #7b8493); }
.trace-error { padding: 8px; color: #a52f36; font-size: .72rem; }
</style>
