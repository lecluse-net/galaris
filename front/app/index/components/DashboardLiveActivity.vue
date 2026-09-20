<template>
  <div class="row q-col-gutter-lg items-stretch">
    <div class="col-12 col-lg-6">
      <q-card flat class="activity-card full-height">
        <DashboardSectionHeader
          compact
          inline-on-mobile
          icon="task_alt"
          tone="blue"
          :title="t('index.dashboard.liveActivity.tasksTitle')"
          :subtitle="t('index.dashboard.liveActivity.tasksSubtitle')"
        >
          <template #badge>
            <q-badge rounded color="primary" class="activity-count-badge">{{ activeTasks.length }}</q-badge>
            <span class="live-label"><span class="live-pulse" aria-hidden="true"></span>{{ t('index.dashboard.liveActivity.live') }}</span>
          </template>
          <template #action>
            <q-btn
              flat
              dense
              no-caps
              color="primary"
              icon-right="arrow_forward"
              :label="t('index.dashboard.liveActivity.allTasks')"
              to="/task"
              class="activity-header-action"
            />
          </template>
        </DashboardSectionHeader>

        <q-separator />

        <q-card-section class="activity-body">
          <div v-if="tasksLoading && !activeTasks.length" class="activity-loading">
            <q-skeleton type="rect" height="62px" />
          </div>
          <div v-else-if="tasksError && !activeTasks.length" class="activity-empty activity-empty--error">
            <q-icon name="cloud_off" size="28px" />
            <span>{{ t('index.dashboard.liveActivity.loadError') }}</span>
          </div>
          <div v-else-if="!activeTasks.length" class="activity-empty">
            <q-icon name="task_alt" size="30px" />
            <span>{{ t('index.dashboard.liveActivity.noTasks') }}</span>
          </div>
          <q-list v-else separator class="activity-list">
            <q-item
              v-for="task in activeTasks"
              :key="task.id"
              clickable
              v-ripple
              :to="{ path: '/task', query: { task_id: task.id } }"
              class="activity-item"
            >
              <q-item-section avatar class="activity-avatar-section">
                <q-avatar size="38px" class="activity-avatar">
                  <img v-if="agentAvatarUrl(task.agent_id)" :src="agentAvatarUrl(task.agent_id)" alt="" />
                  <q-icon v-else name="smart_toy" color="primary" size="21px" />
                </q-avatar>
                <span class="live-pulse" aria-hidden="true"></span>
              </q-item-section>
              <q-item-section class="activity-content">
                <q-item-label class="activity-primary-line">
                  <strong>{{ task.label }}</strong>
                  <span>{{ agentName(task.agent_id) }}</span>
                </q-item-label>
                <q-item-label caption lines="1" class="activity-excerpt">
                  {{ taskExcerpt(task) }}
                </q-item-label>
              </q-item-section>
              <q-item-section side class="activity-side">
                <q-icon
                  :name="taskStatus(task).icon"
                  :color="taskStatus(task).color"
                  size="18px"
                  :class="{ 'activity-spin': task.status === 'DISPATCH' }"
                />
                <span>{{ t(taskStatus(task).labelKey) }}</span>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </div>

    <div class="col-12 col-lg-6">
      <q-card flat class="activity-card full-height">
        <DashboardSectionHeader
          compact
          inline-on-mobile
          icon="psychology"
          tone="violet"
          :title="t('index.dashboard.liveActivity.llmTitle')"
          :subtitle="t('index.dashboard.liveActivity.llmSubtitle')"
        >
          <template #badge>
            <q-badge rounded color="deep-purple" class="activity-count-badge">{{ runningCalls.length }}</q-badge>
            <span class="live-label"><span class="live-pulse" aria-hidden="true"></span>{{ t('index.dashboard.liveActivity.live') }}</span>
          </template>
          <template #action>
            <q-btn
              flat
              dense
              no-caps
              color="primary"
              icon-right="arrow_forward"
              :label="t('index.dashboard.liveActivity.allCalls')"
              :to="{ path: '/task', query: { tab: 'llm' } }"
              class="activity-header-action"
            />
          </template>
        </DashboardSectionHeader>

        <q-separator />

        <q-card-section class="activity-body">
          <div v-if="callsLoading && !runningCalls.length" class="activity-loading">
            <q-skeleton type="rect" height="62px" />
          </div>
          <div v-else-if="callsError && !runningCalls.length" class="activity-empty activity-empty--error">
            <q-icon name="cloud_off" size="28px" />
            <span>{{ t('index.dashboard.liveActivity.loadError') }}</span>
          </div>
          <div v-else-if="!runningCalls.length" class="activity-empty">
            <q-icon name="hourglass_empty" size="30px" />
            <span>{{ t('index.dashboard.liveActivity.noCalls') }}</span>
          </div>
          <q-list v-else separator class="activity-list">
            <q-item
              v-for="call in runningCalls"
              :key="call.id"
              clickable
              v-ripple
              :to="{ path: '/task', query: { tab: 'llm' } }"
              class="activity-item"
            >
              <q-item-section avatar class="activity-avatar-section">
                <q-avatar size="38px" class="activity-avatar activity-avatar--llm">
                  <img v-if="agentAvatarUrl(call.agent_id)" :src="agentAvatarUrl(call.agent_id)" alt="" />
                  <q-icon v-else name="smart_toy" color="deep-purple" size="21px" />
                </q-avatar>
                <span class="live-pulse" aria-hidden="true"></span>
              </q-item-section>
              <q-item-section class="activity-content">
                <q-item-label class="activity-primary-line">
                  <strong>{{ call.task_label || call.process_label || agentName(call.agent_id) }}</strong>
                  <span>{{ call.effective_model || call.requested_model }}</span>
                </q-item-label>
                <q-item-label caption lines="1" class="activity-excerpt">
                  {{ callExcerpt(call) }}
                </q-item-label>
                <div class="activity-call-metrics q-mt-xs">
                  <LlmCallTokenBadge :call="call" />
                  <q-badge color="purple">
                    <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                    {{ formatBilledCost(call.cost) }}
                  </q-badge>
                </div>
              </q-item-section>
              <q-item-section side class="activity-side activity-side--llm">
                <q-spinner-dots color="deep-purple" size="20px" />
                <span>{{ t('index.dashboard.liveActivity.generating') }}</span>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { richTextExcerpt } from '@/core/util'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useInterval } from 'quasar'
import { useI18n } from 'vue-i18n'
import { agentService } from '@/app/agent/services/agentService'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { formatBilledCost, LlmCallTokenBadge } from '@/app/llm'
import { llmCallService } from '@/app/llm/services/llmCallService'
import type { LLMCall, LLMToolCall } from '@/app/llm/types'
import { taskService } from '@/app/task/services/taskService'
import { getTaskStatusConfig, isTaskStatusAction } from '@/app/task/services/taskStatusService'
import type { AIMessage, Task } from '@/app/task/types'
import { websocket } from '@/core/websocket'
import DashboardSectionHeader from './DashboardSectionHeader.vue'

const MAX_ITEMS = 5
const { t } = useI18n()
const { registerInterval, removeInterval } = useInterval()
const agentStore = useAgentStore()
const tasks = ref<Task[]>([])
const calls = ref<LLMCall[]>([])
const agentAvatarUrls = reactive<Record<number, string>>({})
const tasksLoading = ref(true)
const callsLoading = ref(true)
const tasksError = ref(false)
const callsError = ref(false)
let refreshInFlight = false

const activeTasks = computed(() => tasks.value
  .filter(task => isTaskStatusAction(task.status) && !task.paused)
  .sort((a, b) => activityDate(b).localeCompare(activityDate(a)))
  .slice(0, MAX_ITEMS))

const runningCalls = computed(() => calls.value
  .filter(call => call.status === 'running')
  .sort((a, b) => b.started_at.localeCompare(a.started_at))
  .slice(0, MAX_ITEMS))

function activityDate(task: Task): string {
  return task.updated_at || task.created_at || ''
}

function agentName(agentId?: number): string {
  if (!agentId) return t('index.dashboard.agentFallback')
  const agent = agentStore.agents.find(item => item.id === agentId)
  if (!agent) return t('index.dashboard.liveActivity.agentNumber', { id: agentId })
  return `${agent.first_name} ${agent.last_name}`.trim() || agent.code
}

function agentAvatarUrl(agentId?: number): string | undefined {
  return agentId ? agentAvatarUrls[agentId] : undefined
}

function taskStatus(task: Task) {
  return getTaskStatusConfig(task.status)
}

function taskExcerpt(task: Task): string {
  const messages = task.execution_result?.messages || []
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.content?.trim()) return messageExcerpt(message)
  }
  return compactText(richTextExcerpt(task.objective ?? '') || t('index.dashboard.liveActivity.taskFallback'))
}

function messageExcerpt(message: AIMessage): string {
  const content = compactText(message.content)
  return message.type === 'tool'
    ? `${t('index.dashboard.liveActivity.tool', { name: message.tool_name || t('index.dashboard.liveActivity.unknownTool') })}${content ? ` — ${content}` : ''}`
    : content
}

function callExcerpt(call: LLMCall): string {
  const runningTool = [...(call.tool_calls || [])]
    .reverse()
    .find(tool => !isToolFinished(tool))
  if (runningTool) return toolExcerpt(runningTool, true)

  const response = compactText(call.response_text)
  if (response) return response

  const lastTool = call.tool_calls?.[call.tool_calls.length - 1]
  if (lastTool) return toolExcerpt(lastTool, false)

  return compactText(call.reasoning || call.prompt || t('index.dashboard.liveActivity.callFallback'))
}

function isToolFinished(tool: LLMToolCall): boolean {
  return ['completed', 'success', 'error', 'failed', 'cancelled'].includes(tool.status.toLowerCase())
}

function toolExcerpt(tool: LLMToolCall, running: boolean): string {
  const prefix = t(
    running ? 'index.dashboard.liveActivity.toolRunning' : 'index.dashboard.liveActivity.tool',
    { name: tool.name || t('index.dashboard.liveActivity.unknownTool') },
  )
  const details = compactText(summarizeValue(running ? tool.arguments : tool.result ?? tool.arguments))
  return `${prefix}${details ? ` — ${details}` : ''}`
}

function summarizeValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function compactText(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > 180 ? `${normalized.slice(0, 177)}…` : normalized
}

async function refreshActivity(): Promise<void> {
  if (refreshInFlight) return
  refreshInFlight = true
  const [taskResult, callResult] = await Promise.allSettled([
    taskService.getActive(MAX_ITEMS),
    llmCallService.getRunning(MAX_ITEMS),
  ])

  if (taskResult.status === 'fulfilled') {
    tasks.value = taskResult.value
    tasksError.value = false
  } else {
    tasksError.value = true
    console.error('Failed to load active tasks:', taskResult.reason)
  }
  if (callResult.status === 'fulfilled') {
    calls.value = callResult.value
    callsError.value = false
  } else {
    callsError.value = true
    console.error('Failed to load running LLM calls:', callResult.reason)
  }
  tasksLoading.value = false
  callsLoading.value = false
  refreshInFlight = false
}

function upsertTask(task: Task): void {
  const index = tasks.value.findIndex(item => item.id === task.id)
  if (!isTaskStatusAction(task.status) || task.paused) {
    if (index >= 0) tasks.value.splice(index, 1)
    return
  }
  if (index >= 0) tasks.value[index] = task
  else tasks.value.unshift(task)
}

function upsertCall(call: LLMCall): void {
  const index = calls.value.findIndex(item => item.id === call.id)
  if (call.status !== 'running') {
    if (index >= 0) calls.value.splice(index, 1)
    return
  }
  if (index >= 0) calls.value[index] = { ...calls.value[index], ...call }
  else calls.value.unshift(call)
}

function eventData<T>(response: { data?: T } | T): T {
  return typeof response === 'object' && response !== null && 'data' in response && response.data !== undefined
    ? response.data
    : response as T
}

const onTaskCreate = (response: { data?: Task } | Task) => upsertTask(eventData<Task>(response))
const onTaskUpdate = (response: { data?: Task } | Task) => upsertTask(eventData<Task>(response))
const onTaskDelete = (response: { data?: { id: string } } | { id: string }) => {
  const { id } = eventData(response)
  tasks.value = tasks.value.filter(task => task.id !== id)
}
const onTaskRefresh = () => { void refreshActivity() }
const onCallCreate = (response: { data?: LLMCall } | LLMCall) => upsertCall(eventData(response))
const onCallUpdate = (response: { data?: LLMCall } | LLMCall) => upsertCall(eventData(response))
const onCallDelete = (response: { data?: { id: string } } | { id: string }) => {
  const { id } = eventData(response)
  calls.value = calls.value.filter(call => call.id !== id)
}
const onCallCleanup = () => { void refreshActivity() }

async function loadAgents(): Promise<void> {
  await agentStore.fetchAgents()
  await Promise.all(agentStore.agents.map(async agent => {
    if (!agent.has_avatar || agentAvatarUrls[agent.id]) return
    try {
      agentAvatarUrls[agent.id] = await agentService.getAvatarBlobUrl(agent.id)
    } catch (error) {
      console.error(`Failed to load avatar for agent ${agent.id}:`, error)
    }
  }))
}

onMounted(() => {
  void refreshActivity()
  void loadAgents()
  websocket.createWebsocket()
  websocket.onEvent('task', 'create', onTaskCreate)
  websocket.onEvent('task', 'update', onTaskUpdate)
  websocket.onEvent('task', 'delete', onTaskDelete)
  websocket.onEvent('task', 'restore', onTaskRefresh)
  websocket.onEvent('task', 'cleanup', onTaskRefresh)
  websocket.onEvent('llm_call', 'create', onCallCreate)
  websocket.onEvent('llm_call', 'update', onCallUpdate)
  websocket.onEvent('llm_call', 'delete', onCallDelete)
  websocket.onEvent('llm_call', 'cleanup', onCallCleanup)
  registerInterval(() => { void refreshActivity() }, 15_000)
})

onUnmounted(() => {
  websocket.offEvent('task', 'create', onTaskCreate)
  websocket.offEvent('task', 'update', onTaskUpdate)
  websocket.offEvent('task', 'delete', onTaskDelete)
  websocket.offEvent('task', 'restore', onTaskRefresh)
  websocket.offEvent('task', 'cleanup', onTaskRefresh)
  websocket.offEvent('llm_call', 'create', onCallCreate)
  websocket.offEvent('llm_call', 'update', onCallUpdate)
  websocket.offEvent('llm_call', 'delete', onCallDelete)
  websocket.offEvent('llm_call', 'cleanup', onCallCleanup)
  removeInterval()
  Object.values(agentAvatarUrls).forEach(url => URL.revokeObjectURL(url))
})
</script>

<style scoped>
.activity-card {
  display: flex;
  overflow: hidden;
  flex-direction: column;
  border: 1px solid rgba(35, 50, 84, 0.085);
  border-radius: 19px;
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 10px 34px rgba(31, 45, 75, 0.065);
}

.activity-count-badge { min-width: 21px; justify-content: center; padding: 3px 6px; font-size: 0.62rem; }
.live-label { display: flex; gap: 5px; align-items: center; color: #22966d; font-size: 0.61rem; font-weight: 750; text-transform: uppercase; }

.activity-body { min-height: 74px; max-height: 280px; flex: 1; overflow-y: auto; padding: 0; }
.activity-loading { display: grid; gap: 1px; padding: 8px; }
.activity-loading .q-skeleton { border-radius: 10px; }
.activity-list { padding: 4px 0; }
.activity-item { min-height: 66px; padding: 8px 14px; }
.activity-item:hover { background: #f8faff; }
.activity-avatar-section { position: relative; min-width: 48px; padding-right: 10px; }
.activity-avatar { border: 2px solid #fff; background: #edf3ff; box-shadow: 0 2px 8px rgba(40, 57, 86, 0.14); }
.activity-avatar--llm { background: #f2edff; }
.activity-avatar-section > .live-pulse { position: absolute; right: 9px; bottom: 2px; border: 2px solid #fff; }
.activity-content { min-width: 0; }
.activity-primary-line { display: flex; min-width: 0; gap: 8px; align-items: baseline; }
.activity-primary-line strong { overflow: hidden; color: #2c3951; font-size: 0.75rem; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
.activity-primary-line span { overflow: hidden; flex: 0 1 auto; color: #9aa3b3; font-size: 0.61rem; text-overflow: ellipsis; white-space: nowrap; }
.activity-excerpt { overflow: hidden; margin-top: 3px; color: #68758b !important; font-size: 0.68rem; text-overflow: ellipsis; white-space: nowrap; }
.activity-call-metrics { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.activity-side { width: 76px; align-items: center; gap: 2px; padding-left: 10px; }
.activity-side span { max-width: 74px; overflow: hidden; color: #778299; font-size: 0.58rem; font-weight: 700; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.activity-side--llm span { color: #7657b8; }
.activity-empty { display: flex; min-height: 74px; flex-direction: column; gap: 5px; align-items: center; justify-content: center; padding: 12px 24px; color: #9aa4b5; font-size: 0.72rem; text-align: center; }
.activity-empty--error { color: #bf5a62; }

body.body--dark .activity-card { border-color: rgba(255, 255, 255, 0.09); background: rgba(29, 29, 29, 0.97); box-shadow: 0 10px 34px rgba(0, 0, 0, 0.35); }
body.body--dark .activity-item:hover { background: #232a3d; }
body.body--dark .activity-avatar { border-color: #1d1d1d; background: #253046; }
body.body--dark .activity-avatar--llm { background: #2c2540; }
body.body--dark .activity-avatar-section > .live-pulse { border-color: #1d1d1d; }
body.body--dark .activity-primary-line strong { color: #dbe2ee; }
body.body--dark .activity-excerpt { color: #97a2b8 !important; }
body.body--dark .activity-side--llm span { color: #a68ce8; }

.live-pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #27b37e; box-shadow: 0 0 0 0 rgba(39, 179, 126, 0.42); animation: activity-pulse 1.8s infinite; }
.activity-spin { animation: activity-spin 1.5s linear infinite; }

@keyframes activity-pulse {
  0% { box-shadow: 0 0 0 0 rgba(39, 179, 126, 0.42); }
  70% { box-shadow: 0 0 0 7px rgba(39, 179, 126, 0); }
  100% { box-shadow: 0 0 0 0 rgba(39, 179, 126, 0); }
}

@keyframes activity-spin { to { transform: rotate(360deg); } }

@media (max-width: 599px) {
  .activity-header-action { min-width: 34px; padding: 4px; }
  .activity-header-action :deep(.q-btn__content > span) { display: none; }
  .activity-side { width: 52px; }
  .activity-side span { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .live-pulse,
  .activity-spin { animation: none; }
}
</style>
