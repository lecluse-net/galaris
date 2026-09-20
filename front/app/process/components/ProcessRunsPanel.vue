<template>
  <div>
    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="metric in metrics" :key="metric.key" class="col-6 col-md-3">
        <q-card flat bordered class="full-height process-metric-card">
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md" style="min-width: 0">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <q-skeleton v-if="operations === null" type="text" width="48px" height="32px" />
              <div v-else class="text-h5 text-weight-medium">{{ metric.value }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <section class="q-mb-lg">
      <q-card v-if="!activeRuns.length" flat bordered>
        <q-card-section class="text-center text-grey-7 q-py-lg">
          <q-icon name="hourglass_empty" size="32px" class="q-mb-sm" />
          <div>{{ t('executionMonitoring.noneInProgress') }}</div>
        </q-card-section>
      </q-card>
      <q-card v-else flat bordered>
        <q-list separator>
          <q-item
            v-for="run in activeRuns"
            :key="run.id"
            clickable
            class="process-active-run"
            @click="openRun($event, run)"
          >
            <q-item-section avatar>
              <q-avatar :color="statusColor(run.status)" text-color="white" :icon="statusIcon(run.status)" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ processLabel(run) }}</q-item-label>
              <q-item-label caption>{{ agentLabel(run) }} · {{ formatDate(run.created_at) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <StatusBadge
                :tone="statusTone(run.status)"
                :label="statusLabel(run.status)"
                :icon="statusIcon(run.status)"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </section>

    <q-card>
      <q-card-section class="process-runs-header">
        <div class="row items-center justify-between no-wrap process-runs-header-row">
          <div class="row items-center no-wrap process-runs-title">
            <q-icon name="history" size="sm" class="q-mr-sm" />
            <span class="text-subtitle1">
              {{ t('executionMonitoring.history', { count: pagination.rowsNumber }) }}
            </span>
          </div>
          <div class="row items-center process-runs-filters">
            <q-input
              v-model="search"
              dense
              outlined
              clearable
              debounce="300"
              :label="t('processes.tracking.search')"
              class="process-search-input"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
            <q-select
              v-model="selectedStatus"
              :options="statusOptions"
              dense
              outlined
              clearable
              emit-value
              map-options
              :label="t('processes.tracking.statusFilter')"
              class="process-status-select"
            />
            <AgentSelect
              v-model="selectedAgentId"
              :options="agentOptions"
              :label="t('processes.agentFilter')"
              clearable
              dense
              outlined
              class="process-agent-select"
            />
            <ExecutionDateFilters
              v-model:date-from="dateFrom"
              v-model:date-to="dateTo"
            />
          </div>
        </div>
        <q-separator class="q-mt-sm" />
      </q-card-section>

      <q-banner v-if="loadError" dense class="bg-red-1 text-negative q-mx-md q-mb-md" rounded>
        <template #avatar><q-icon name="error" /></template>
        {{ t('processes.tracking.loadError') }}
      </q-banner>

      <q-table
        flat
        :rows="runs"
        :columns="columns"
        v-model:pagination="pagination"
        :loading="loading"
        :grid="$q.screen.lt.md"
        row-key="id"
        :no-data-label="t('processes.tracking.noRuns')"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        class="process-runs-table"
        @request="onRequest"
        @row-click="openRun"
      >
        <template #body-cell-process_label="props">
          <q-td :props="props">
            <div class="text-weight-medium">{{ processLabel(props.row) }}</div>
            <div v-if="props.row.workflow_id" class="text-caption text-grey-7">
              {{ props.row.workflow_id }}
            </div>
          </q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <StatusBadge
              :tone="statusTone(props.row.status)"
              :label="statusLabel(props.row.status)"
              :icon="statusIcon(props.row.status)"
            />
          </q-td>
        </template>
        <template #item="props">
          <div class="q-table__grid-item col-12">
            <q-card
              flat
              bordered
              class="process-mobile-card"
              role="button"
              tabindex="0"
              @click="openRun($event, props.row)"
              @keydown.enter.prevent="openRun($event, props.row)"
              @keydown.space.prevent="openRun($event, props.row)"
            >
              <q-card-section class="q-pa-md">
                <div class="row items-start no-wrap q-gutter-sm">
                  <q-avatar
                    :color="statusColor(props.row.status)"
                    text-color="white"
                    :icon="statusIcon(props.row.status)"
                    size="40px"
                  />
                  <div class="col process-mobile-heading">
                    <div class="text-weight-medium ellipsis">{{ processLabel(props.row) }}</div>
                    <div class="text-caption text-grey-7 ellipsis">
                      {{ formatDate(props.row.created_at) }}
                    </div>
                  </div>
                  <StatusBadge
                    :tone="statusTone(props.row.status)"
                    :label="statusLabel(props.row.status)"
                    :icon="statusIcon(props.row.status)"
                  />
                </div>

                <div class="process-mobile-metadata q-mt-md">
                  <div>
                    <div class="metadata-label">{{ t('processes.agent') }}</div>
                    <div class="ellipsis">{{ agentLabel(props.row) }}</div>
                  </div>
                  <div>
                    <div class="metadata-label">{{ t('processes.tool') }}</div>
                    <div class="ellipsis">{{ props.row.tool_code }}</div>
                  </div>
                  <div>
                    <div class="metadata-label">{{ t('processes.duration') }}</div>
                    <div>{{ formatRunDuration(props.row) }}</div>
                  </div>
                  <div v-if="props.row.workflow_id">
                    <div class="metadata-label">{{ t('processes.engineProcessId') }}</div>
                    <div class="ellipsis text-mono">{{ props.row.workflow_id }}</div>
                  </div>
                </div>

                <div v-if="props.row.summary" class="process-mobile-summary q-mt-md">
                  {{ props.row.summary }}
                </div>
                <div v-if="props.row.error_message" class="text-caption text-negative q-mt-sm">
                  {{ props.row.error_message }}
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="detailDialogOpen">
      <q-card class="process-run-dialog galaris-detail-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="account_tree" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">
            {{ selectedRun ? processLabel(selectedRun) : t('processes.tracking.details') }}
          </div>
          <q-space />
          <q-btn
            v-close-popup
            flat
            round
            dense
            icon="close"
            :aria-label="t('processes.close')"
          />
        </q-card-section>

        <q-card-section v-if="detailLoading" class="text-center q-pa-xl">
          <q-spinner color="primary" size="2.5em" />
        </q-card-section>
        <q-card-section v-else-if="selectedRun" class="q-gutter-md">
          <div class="row items-center q-gutter-sm">
            <StatusBadge
              :tone="statusTone(selectedRun.status)"
              :label="statusLabel(selectedRun.status)"
              :icon="statusIcon(selectedRun.status)"
            />
            <span v-if="selectedRun.summary" class="text-subtitle1">{{ selectedRun.summary }}</span>
          </div>

          <div class="process-run-metadata">
            <div>
              <div class="metadata-label">{{ t('processes.runId') }}</div>
              <div class="text-body2 text-mono">{{ selectedRun.id }}</div>
            </div>
            <div>
              <div class="metadata-label">{{ t('processes.agent') }}</div>
              <div class="text-body2">{{ agentLabel(selectedRun) }}</div>
            </div>
            <div>
              <div class="metadata-label">{{ t('processes.tool') }}</div>
              <div class="text-body2">{{ selectedRun.tool_code }}</div>
            </div>
            <div>
              <div class="metadata-label">{{ t('processes.createdAt') }}</div>
              <div class="text-body2">{{ formatDate(selectedRun.created_at) }}</div>
            </div>
            <div>
              <div class="metadata-label">{{ t('processes.finishedAt') }}</div>
              <div class="text-body2">{{ formatDate(selectedRun.finished_at) }}</div>
            </div>
            <div>
              <div class="metadata-label">{{ t('processes.duration') }}</div>
              <div class="text-body2">{{ formatRunDuration(selectedRun) }}</div>
            </div>
          </div>

          <q-banner v-if="selectedRun.error_message" rounded class="bg-red-1 text-negative">
            <template #avatar><q-icon name="error" /></template>
            <span v-if="selectedRun.error_code">{{ selectedRun.error_code }} — </span>
            {{ selectedRun.error_message }}
          </q-banner>

          <q-expansion-item bordered icon="input" :label="t('processes.input')">
            <CodeEditor
              :model-value="pretty(selectedRun.input)"
              language="json"
              :label="t('processes.input')"
              readonly
              :show-error="false"
              :visible-lines="10"
              :min-lines="5"
              class="q-pa-md"
            />
          </q-expansion-item>
          <q-expansion-item bordered icon="output" :label="t('processes.output')">
            <CodeEditor
              :model-value="pretty(selectedRun.output)"
              language="json"
              :label="t('processes.output')"
              readonly
              :show-error="false"
              :visible-lines="10"
              :min-lines="5"
              class="q-pa-md"
            />
          </q-expansion-item>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useInterval, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { AgentSelect, useAgentStore } from '@/app/agent'
import {
  CodeEditor,
  ExecutionDateFilters,
  StatusBadge,
  type StatusBadgeTone,
} from '@/core/util'
import { websocket } from '@/core/websocket'
import {
  processService,
  type ProcessOperations,
  type ProcessRun,
  type ProcessRunStatus,
} from '../services/processService'

interface RunPagination {
  page: number
  rowsPerPage: number
  rowsNumber: number
  sortBy: string
  descending: boolean
}

interface RunsRequest {
  pagination: {
    page: number
    rowsPerPage: number
    sortBy?: string | null
    descending?: boolean
  }
}

const { t, te, locale } = useI18n()
const { registerInterval } = useInterval()
const agentStore = useAgentStore()
const runs = ref<ProcessRun[]>([])
const activeRuns = ref<ProcessRun[]>([])
const operations = ref<ProcessOperations | null>(null)
const loading = ref(false)
const loadError = ref(false)
const search = ref('')
const selectedStatus = ref<ProcessRunStatus | null>(null)
const selectedAgentId = ref<number | null>(null)
const dateFrom = ref<string | null>(null)
const dateTo = ref<string | null>(null)
const detailDialogOpen = ref(false)
const detailLoading = ref(false)
const selectedRun = ref<ProcessRun | null>(null)
let runRequestSequence = 0
let realtimeRefreshTimer: ReturnType<typeof setTimeout> | null = null
const pagination = ref<RunPagination>({
  page: 1,
  rowsPerPage: 50,
  rowsNumber: 0,
  sortBy: 'created_at',
  descending: true,
})

const columns = computed<QTableColumn[]>(() => [
  {
    name: 'created_at',
    label: t('processes.createdAt'),
    field: (run: ProcessRun) => formatDate(run.created_at),
    align: 'left',
    sortable: true,
  },
  {
    name: 'process_label',
    label: t('processes.process'),
    field: (run: ProcessRun) => processLabel(run),
    align: 'left',
  },
  {
    name: 'launcher_agent_id',
    label: t('processes.agent'),
    field: (run: ProcessRun) => agentLabel(run),
    align: 'left',
    sortable: true,
  },
  {
    name: 'tool_code',
    label: t('processes.tool'),
    field: 'tool_code',
    align: 'left',
  },
  {
    name: 'duration',
    label: t('processes.duration'),
    field: (run: ProcessRun) => formatRunDuration(run),
    align: 'right',
  },
  {
    name: 'status',
    label: t('processes.status'),
    field: 'status',
    align: 'left',
    sortable: true,
  },
])

const processRunStatuses: ProcessRunStatus[] = [
  'success',
  'error',
  'cancelled',
]
const statusOptions = computed(() => (
  processRunStatuses.map(status => ({ label: statusLabel(status), value: status }))
))
const agentOptions = computed(() => [
  { label: t('processes.allAgents'), value: null },
  ...agentStore.sortedAgents.map(agent => ({
    label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
    value: agent.id,
  })),
])

const metrics = computed(() => {
  const counts = operations.value?.status_counts ?? {}
  const active = ['queued', 'running', 'waiting', 'cancelling']
    .reduce((total, status) => total + (counts[status] ?? 0), 0)
  return [
    {
      key: 'completed',
      label: t('processes.tracking.metrics.completed'),
      value: counts.success ?? 0,
      icon: 'check_circle',
      color: 'positive',
    },
    {
      key: 'cancelled',
      label: t('processes.tracking.metrics.cancelled'),
      value: counts.cancelled ?? 0,
      icon: 'cancel',
      color: 'grey-7',
    },
    {
      key: 'active',
      label: t('processes.tracking.metrics.active'),
      value: active,
      icon: 'motion_photos_on',
      color: 'primary',
    },
    {
      key: 'errors',
      label: t('processes.tracking.metrics.errors'),
      value: counts.error ?? 0,
      icon: 'error',
      color: 'negative',
    },
  ]
})

function statusLabel(status: string): string {
  const key = `processes.statuses.${status}`
  return te(key) ? t(key) : status
}

function statusColor(status: string): string {
  return ({
    success: 'positive',
    error: 'negative',
    cancelled: 'grey',
    running: 'primary',
    waiting: 'orange',
    queued: 'blue-grey',
    cancelling: 'warning',
    unknown: 'dark',
  } as Record<string, string>)[status] ?? 'grey'
}

function statusTone(status: string): StatusBadgeTone {
  return ({
    success: 'success',
    error: 'error',
    cancelled: 'neutral',
    running: 'active',
    waiting: 'warning',
    queued: 'neutral',
    cancelling: 'warning',
    unknown: 'neutral',
  } satisfies Record<string, StatusBadgeTone>)[status] ?? 'neutral'
}

function statusIcon(status: string): string {
  return ({
    success: 'check_circle',
    error: 'error',
    cancelled: 'cancel',
    running: 'play_circle',
    waiting: 'hourglass_top',
    queued: 'schedule',
    cancelling: 'pending',
    unknown: 'help',
  } as Record<string, string>)[status] ?? 'help'
}

function processLabel(run: ProcessRun): string {
  return run.process_label || run.workflow_id || `#${run.process_id}`
}

function agentLabel(run: ProcessRun): string {
  return run.launcher_agent_code || `#${run.launcher_agent_id}`
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function formatRunDuration(run: ProcessRun): string {
  if (!run.started_at) return '—'
  const start = Date.parse(run.started_at)
  const end = run.finished_at ? Date.parse(run.finished_at) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—'
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

function createdAfter(): string | undefined {
  return dateFrom.value ? new Date(`${dateFrom.value}T00:00:00`).toISOString() : undefined
}

function createdBefore(): string | undefined {
  return dateTo.value ? new Date(`${dateTo.value}T23:59:59.999`).toISOString() : undefined
}

function pretty(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2)
}

async function loadRuns(
  page: number = pagination.value.page,
  rowsPerPage: number = pagination.value.rowsPerPage,
  sortBy: string = pagination.value.sortBy,
  descending: boolean = pagination.value.descending,
): Promise<void> {
  const requestSequence = ++runRequestSequence
  loading.value = true
  loadError.value = false
  try {
    const result = await processService.runs({
      page,
      pageSize: rowsPerPage,
      search: search.value,
      status: selectedStatus.value ?? undefined,
      createdAfter: createdAfter(),
      createdBefore: createdBefore(),
      sortBy,
      descending,
      active: false,
      agentId: selectedAgentId.value ?? undefined,
    })
    if (requestSequence !== runRequestSequence) return
    runs.value = result.items
    pagination.value = {
      page: result.page,
      rowsPerPage: result.page_size,
      rowsNumber: result.total,
      sortBy,
      descending,
    }
  } catch (error) {
    if (requestSequence !== runRequestSequence) return
    console.error('Error loading process runs:', error)
    loadError.value = true
  } finally {
    if (requestSequence === runRequestSequence) loading.value = false
  }
}

async function loadActiveRuns(): Promise<void> {
  try {
    const result = await processService.runs({
      page: 1,
      pageSize: 50,
      active: true,
      agentId: selectedAgentId.value ?? undefined,
    })
    activeRuns.value = result.items
  } catch (error) {
    console.error('Error loading active process runs:', error)
  }
}

async function loadOperations(): Promise<void> {
  try {
    operations.value = await processService.operations(selectedAgentId.value ?? undefined)
  } catch (error) {
    console.error('Error loading process metrics:', error)
  }
}

async function refreshAll(page: number = pagination.value.page): Promise<void> {
  await Promise.all([loadRuns(page), loadActiveRuns(), loadOperations()])
}

async function onRequest(request: RunsRequest): Promise<void> {
  await loadRuns(
    request.pagination.page,
    request.pagination.rowsPerPage,
    request.pagination.sortBy ?? 'created_at',
    request.pagination.descending ?? true,
  )
}

async function openRun(_event: Event, run: ProcessRun): Promise<void> {
  selectedRun.value = run
  detailDialogOpen.value = true
  detailLoading.value = true
  try {
    selectedRun.value = await processService.run(run.id)
  } catch (error) {
    console.error('Error loading process run details:', error)
  } finally {
    detailLoading.value = false
  }
}

watch([search, selectedStatus, dateFrom, dateTo], () => {
  void loadRuns(1)
})

watch(selectedAgentId, () => {
  void refreshAll(1)
})

function scheduleRealtimeRefresh(): void {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  realtimeRefreshTimer = setTimeout(() => {
    realtimeRefreshTimer = null
    void refreshAll()
  }, 300)
}

onMounted(() => {
  if (agentStore.agents.length === 0 && !agentStore.loading) {
    void agentStore.fetchAgents()
  }
  void refreshAll()
  registerInterval(() => { void refreshAll() }, 15000)
  websocket.createWebsocket()
  websocket.onEvent('process_run', 'create', scheduleRealtimeRefresh)
  websocket.onEvent('process_run', 'update', scheduleRealtimeRefresh)
  websocket.onEvent('process_run', 'delete', scheduleRealtimeRefresh)
})

onUnmounted(() => {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  websocket.offEvent('process_run', 'create', scheduleRealtimeRefresh)
  websocket.offEvent('process_run', 'update', scheduleRealtimeRefresh)
  websocket.offEvent('process_run', 'delete', scheduleRealtimeRefresh)
})
</script>

<style scoped>
.process-runs-header {
  padding-bottom: 0;
}

.process-runs-header-row {
  gap: 12px;
}

.process-runs-title {
  flex: 0 0 auto;
}

.process-runs-filters {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.process-runs-table :deep(tbody tr) {
  cursor: pointer;
}

.process-runs-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.process-runs-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 12px;
}

.process-search-input {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}

.process-status-select {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.process-agent-select {
  flex: 0 1 220px;
  width: 220px;
  min-width: 150px;
  max-width: 220px;
}

.process-mobile-card,
.process-mobile-heading {
  min-width: 0;
}

.process-mobile-card {
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.process-mobile-card:hover,
.process-mobile-card:focus-visible {
  border-color: var(--q-primary);
  box-shadow: 0 3px 12px rgb(25 118 210 / 14%);
  outline: none;
}

.process-mobile-metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}

.process-mobile-metadata > div {
  min-width: 0;
}

.process-mobile-summary {
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: #475467;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

body.body--dark .process-mobile-summary {
  color: #cdd5e0;
}

.process-run-dialog {
  width: 900px;
  max-width: 96vw;
  max-height: 96vh;
  overflow-y: auto;
}

.process-run-metadata {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.metadata-label {
  color: #667085;
  font-size: 12px;
}

body.body--dark .metadata-label {
  color: #98a2b8;
}

@media (max-width: 1023px) {
  .process-runs-header-row {
    flex-wrap: wrap;
  }

  .process-runs-title,
  .process-runs-filters {
    width: 100%;
  }

  .process-runs-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .process-search-input,
  .process-status-select,
  .process-agent-select {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .process-search-input,
  .process-runs-filters :deep(.execution-date-filters) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 599px) {
  .process-runs-filters {
    grid-template-columns: minmax(0, 1fr);
  }

  .process-search-input,
  .process-runs-filters :deep(.execution-date-filters) {
    grid-column: auto;
  }

  .process-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .process-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .process-metric-card :deep(.q-ml-md) {
    margin-left: 8px;
  }

  .process-active-run {
    align-items: flex-start;
    padding: 10px 12px;
  }

  .process-active-run :deep(.q-item__section--avatar) {
    min-width: 48px;
  }

  .process-active-run :deep(.q-item__section--side) {
    padding-left: 6px;
  }

  .process-active-run :deep(.q-chip) {
    margin: 0;
  }

  .process-runs-table :deep(.q-table__grid-item) {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
