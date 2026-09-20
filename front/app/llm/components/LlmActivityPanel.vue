<template>
  <div>
    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="metric in metrics" :key="metric.label" class="col-6 col-md">
        <q-card
          flat
          bordered
          class="full-height llm-metric-card"
          :class="{
            'llm-metric-card--interactive': metric.key === 'errors',
            'llm-metric-card--active': metric.key === 'errors' && errorsOnly,
          }"
          :role="metric.key === 'errors' ? 'button' : undefined"
          :tabindex="metric.key === 'errors' ? 0 : undefined"
          :aria-pressed="metric.key === 'errors' ? errorsOnly : undefined"
          @click="metric.key === 'errors' && toggleErrorsOnly()"
          @keydown.enter.prevent="metric.key === 'errors' && toggleErrorsOnly()"
          @keydown.space.prevent="metric.key === 'errors' && toggleErrorsOnly()"
        >
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md" style="min-width: 0">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <div class="text-h5 text-weight-medium ellipsis" :title="String(metric.value)">{{ metric.value }}</div>
            </div>
          </q-card-section>
          <q-tooltip v-if="metric.key === 'errors'">
            {{ $t(errorsOnly ? 'llmCalls.metrics.showAll' : 'llmCalls.metrics.showErrorsOnly') }}
          </q-tooltip>
        </q-card>
      </div>
    </div>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">{{ error }}</q-banner>

    <section class="q-mb-lg">
      <q-card v-if="!runningCalls.length" flat bordered>
        <q-card-section class="text-center text-grey-7 q-py-lg">
          <q-icon name="hourglass_empty" size="32px" class="q-mb-sm" />
          <div>{{ $t('executionMonitoring.noneInProgress') }}</div>
        </q-card-section>
      </q-card>
      <div v-else class="column q-gutter-md">
        <LlmCall
          v-for="call in runningCalls"
          :key="call.id"
          :call="call"
          :agent-name="agentName(call.agent_id)"
          :agent-avatar-url="agentAvatarUrl(call.agent_id)"
          :task-color="taskColor(call)"
          :deletable="canPurge"
          @delete="requestDelete"
        />
      </div>
    </section>

    <section>
      <q-card flat bordered class="llm-history-card">
        <q-card-section class="llm-history-header">
          <div class="row items-center justify-between no-wrap llm-history-header-row">
            <div class="row items-center no-wrap">
              <q-icon
                :name="errorsOnly ? 'error' : 'history'"
                :color="errorsOnly ? 'negative' : 'primary'"
                size="sm"
                class="q-mr-sm"
              />
              <span class="text-subtitle1">
                {{ $t(errorsOnly ? 'llmCalls.errorHistory' : 'llmCalls.recent', { count: historyPagination.rowsNumber }) }}
              </span>
            </div>
            <ExecutionDateFilters
              v-model:date-from="dateFrom"
              v-model:date-to="dateTo"
              @change="dateRangeChanged"
            />
          </div>
          <q-separator class="q-mt-sm" />
        </q-card-section>
        <q-table
          v-model:pagination="historyPagination"
          :rows="recentCalls"
          :columns="historyColumns"
          row-key="id"
          grid
          flat
          hide-header
          :loading="loading"
          :rows-per-page-options="[10, 20, 50, 100, 500]"
          :no-data-label="$t(errorsOnly ? 'llmCalls.noRecentErrors' : 'llmCalls.noRecent')"
          class="llm-history-table"
          @request="onHistoryRequest"
        >
          <template #item="props">
            <div class="col-12 q-px-md q-pb-md">
              <LlmCall
                :call="props.row"
                :agent-name="agentName(props.row.agent_id)"
                :agent-avatar-url="agentAvatarUrl(props.row.agent_id)"
                :task-color="taskColor(props.row)"
                :deletable="canPurge"
                @delete="requestDelete"
              />
            </div>
          </template>
        </q-table>
      </q-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar'
import { websocket } from '@/core/websocket'
import { usePrivilegeStore, privileges } from '@/core/authorize'
import { ExecutionDateFilters, startVisiblePolling } from '@/core/util'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { agentService } from '@/app/agent/services/agentService'
import LlmCall from './LlmCall.vue'
import { llmCallService } from '../services/llmCallService'
import { assignTaskColors, callTaskKey, type LlmTaskColor } from '../taskColors'
import type { LLMCall, LLMCallPage, LLMCallSummary } from '../types'

const { t, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const agentStore = useAgentStore()
const liveCalls = ref<LLMCall[]>([])
const recentCalls = ref<LLMCall[]>([])
const agentAvatarUrls = reactive<Record<number, string>>({})
const loading = ref(false)
const error = ref('')
const errorsOnly = ref(false)
const dateFrom = ref<string | null>(null)
const dateTo = ref<string | null>(null)
const summary = ref<LLMCallSummary>({
  running: 0,
  completed: 0,
  errors: 0,
  total_cost: 0,
  total_inference_cost: 0,
})
const canPurge = computed(() => privilegeStore.hasPrivilege(privileges.LLM_CALL_PURGE))
let stopPolling: (() => void) | undefined
let historyRefreshTimer: ReturnType<typeof setTimeout> | undefined

type HistoryRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

const historyColumns: QTableColumn[] = [
  { name: 'call', label: '', field: 'id' },
]
const historyPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const runningCalls = computed(() => liveCalls.value.filter(call => call.status === 'running'))
const taskColors = computed(() => assignTaskColors([runningCalls.value, recentCalls.value]))

const metrics = computed(() => [
  { key: 'completed', label: t('llmCalls.metrics.completed'), value: summary.value.completed, icon: 'check_circle', color: 'positive' },
  { key: 'cost', label: t('llmCalls.metrics.cost'), value: formatCost(summary.value.total_cost), icon: 'payments', color: 'secondary' },
  { key: 'inferenceCost', label: t('llmCalls.metrics.inferenceCost'), value: formatCost(summary.value.total_inference_cost), icon: 'calculate', color: 'deep-purple' },
  { key: 'running', label: t('llmCalls.metrics.running'), value: summary.value.running, icon: 'motion_photos_on', color: 'primary' },
  { key: 'errors', label: t('llmCalls.metrics.errors'), value: summary.value.errors, icon: 'error', color: 'negative' },
])

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [runningCalls] = await Promise.all([
      llmCallService.getRunning(50),
      loadHistoryPage(),
    ])
    liveCalls.value = runningCalls
      .sort(sortCalls)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('llmCalls.loadError')
  } finally {
    loading.value = false
  }
}

async function loadHistoryPage(
  page: number = historyPagination.value.page,
  rowsPerPage: number = historyPagination.value.rowsPerPage,
): Promise<void> {
  let response = await llmCallService.getHistory(
    page,
    rowsPerPage,
    errorsOnly.value,
    dateFrom.value,
    dateTo.value,
  )
  const lastPage = Math.max(1, Math.ceil(response.total / response.page_size))
  if (response.page > lastPage) {
    response = await llmCallService.getHistory(
      lastPage,
      rowsPerPage,
      errorsOnly.value,
      dateFrom.value,
      dateTo.value,
    )
  }
  applyHistoryPage(response)
}

function applyHistoryPage(response: LLMCallPage): void {
  recentCalls.value = response.items
  summary.value = response.summary
  historyPagination.value = {
    page: response.page,
    rowsPerPage: response.page_size,
    rowsNumber: response.total,
  }
}

async function onHistoryRequest(request: HistoryRequest): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await loadHistoryPage(request.pagination.page, request.pagination.rowsPerPage)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('llmCalls.loadError')
  } finally {
    loading.value = false
  }
}

function refreshHistory(): void {
  if (document.hidden) return // The visibility resume refresh loads the latest history.
  void loadHistoryPage().catch((reason: unknown) => {
    error.value = reason instanceof Error ? reason.message : t('llmCalls.loadError')
  })
}

function scheduleHistoryRefresh(): void {
  if (historyRefreshTimer) clearTimeout(historyRefreshTimer)
  if (document.hidden) return
  historyRefreshTimer = setTimeout(refreshHistory, 300)
}

function toggleErrorsOnly(): void {
  errorsOnly.value = !errorsOnly.value
  historyPagination.value.page = 1
  loading.value = true
  error.value = ''
  void loadHistoryPage(1, historyPagination.value.rowsPerPage)
    .catch((reason: unknown) => {
      error.value = reason instanceof Error ? reason.message : t('llmCalls.loadError')
    })
    .finally(() => {
      loading.value = false
    })
}

function dateRangeChanged(): void {
  historyPagination.value.page = 1
  loading.value = true
  void loadHistoryPage(1, historyPagination.value.rowsPerPage)
    .catch((reason: unknown) => {
      error.value = reason instanceof Error ? reason.message : t('llmCalls.loadError')
    })
    .finally(() => {
      loading.value = false
    })
}

function upsert(call: LLMCall): void {
  const index = liveCalls.value.findIndex(item => item.id === call.id)
  if (call.status !== 'running') {
    if (index >= 0) liveCalls.value.splice(index, 1)
    scheduleHistoryRefresh()
    return
  }
  if (index >= 0) liveCalls.value[index] = call
  else liveCalls.value.unshift(call)
  liveCalls.value.sort(sortCalls)
  scheduleHistoryRefresh()
}

const onCreate = (response: { data: LLMCall }) => upsert(response.data)
const onUpdate = (response: { data: LLMCall }) => upsert(response.data)
// After a server purge, retain only calls that are still running locally.
const onCleanup = () => {
  liveCalls.value = liveCalls.value.filter(call => call.status === 'running')
  recentCalls.value = []
  historyPagination.value = {
    page: 1,
    rowsPerPage: historyPagination.value.rowsPerPage,
    rowsNumber: 0,
  }
  refreshHistory()
}
const onDelete = (response: { data: { id: string } }) => {
  removeCall(response.data.id)
  refreshHistory()
}

onMounted(() => {
  void load()
  void Promise.all([loadAgents(), agentStore.fetchTitles()])
  websocket.createWebsocket()
  websocket.onEvent('llm_call', 'create', onCreate)
  websocket.onEvent('llm_call', 'update', onUpdate)
  websocket.onEvent('llm_call', 'cleanup', onCleanup)
  websocket.onEvent('llm_call', 'delete', onDelete)
  stopPolling = startVisiblePolling(load, 30_000)
})

onBeforeUnmount(() => {
  websocket.offEvent('llm_call', 'create', onCreate)
  websocket.offEvent('llm_call', 'update', onUpdate)
  websocket.offEvent('llm_call', 'cleanup', onCleanup)
  websocket.offEvent('llm_call', 'delete', onDelete)
  stopPolling?.()
  if (historyRefreshTimer) clearTimeout(historyRefreshTimer)
  Object.values(agentAvatarUrls).forEach(url => URL.revokeObjectURL(url))
})

function removeCall(callId: string): void {
  liveCalls.value = liveCalls.value.filter(call => call.id !== callId)
  const removedFromHistory = recentCalls.value.some(call => call.id === callId)
  recentCalls.value = recentCalls.value.filter(call => call.id !== callId)
  if (removedFromHistory) {
    historyPagination.value.rowsNumber = Math.max(0, historyPagination.value.rowsNumber - 1)
  }
}

function requestDelete(call: LLMCall): void {
  if (!canPurge.value) {
    $q.notify({ type: 'negative', message: t('llmCalls.notify.deleteDenied') })
    return
  }
  showConfirmationDialog({
    title: t('llmCalls.deleteConfirm'),
    message: t('llmCalls.deleteMessage'),
    cancel: { flat: true, label: t('llmCalls.cancel') },
    ok: { flat: true, color: 'negative', label: t('llmCalls.delete') },
  }).onOk(() => {
    void deleteCall(call.id)
  })
}

async function deleteCall(callId: string): Promise<void> {
  try {
    await llmCallService.delete(callId)
    removeCall(callId)
    await loadHistoryPage()
    $q.notify({ type: 'positive', message: t('llmCalls.notify.deleted') })
  } catch (reason) {
    $q.notify({ type: 'negative', message: t('llmCalls.notify.deleteError') })
  }
}

function sortCalls(a: LLMCall, b: LLMCall): number {
  return b.started_at.localeCompare(a.started_at)
}

function agentName(agentId?: number): string | undefined {
  if (!agentId) return undefined
  const agent = agentStore.agents.find(item => item.id === agentId)
  return agent ? agentStore.getFullName(agent, t) : `Agent #${agentId}`
}

function agentAvatarUrl(agentId?: number): string | undefined {
  return agentId ? agentAvatarUrls[agentId] : undefined
}

async function loadAgents(): Promise<void> {
  await agentStore.fetchAgents()
  await Promise.all(agentStore.agents.map(async agent => {
    if (!agent.has_avatar || agentAvatarUrls[agent.id]) return
    try {
      agentAvatarUrls[agent.id] = await agentService.getAvatarBlobUrl(agent.id)
    } catch (reason) {
      console.error(`Failed to load avatar for agent ${agent.id}:`, reason)
    }
  }))
}

function taskColor(call: LLMCall): LlmTaskColor {
  return taskColors.value.get(callTaskKey(call))!
}

function formatCost(cost: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 4,
  }).format(cost || 0)
}
</script>

<style scoped>
.llm-history-header {
  padding-bottom: 0;
}

.llm-history-header-row {
  gap: 12px;
}

.llm-history-table {
  background: transparent;
}

.llm-history-table :deep(.q-table__bottom) {
  padding-right: 0;
  padding-left: 0;
}

.llm-metric-card {
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.llm-metric-card--interactive {
  cursor: pointer;
}

.llm-metric-card--interactive:hover,
.llm-metric-card--interactive:focus-visible {
  border-color: var(--q-negative);
  box-shadow: 0 4px 14px rgb(193 40 46 / 14%);
  outline: none;
  transform: translateY(-1px);
}

.llm-metric-card--active {
  border-color: var(--q-negative);
  box-shadow: 0 0 0 1px var(--q-negative), 0 5px 16px rgb(193 40 46 / 18%);
}

@media (max-width: 1023px) {
  .llm-history-header-row {
    flex-wrap: wrap;
  }

  .llm-history-header-row :deep(.execution-date-filters) {
    width: 100%;
  }
}

@media (max-width: 599px) {
  .llm-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .llm-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .llm-metric-card :deep(.q-ml-md) {
    margin-left: 8px;
  }

  .llm-history-table :deep(.q-table__grid-item) {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
