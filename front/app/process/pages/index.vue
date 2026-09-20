<template>
  <q-page class="process-page q-pa-md">
    <PageHeader help-key="processes" :help-text="$t('contextHelpPages.processes')" :icon="navigationIcon('account_tree')" :title="t('nav.processes')" :description="t('nav.processes_desc')" />

    <div class="process-toolbar q-mb-md">
      <q-input v-model="definitionFilter" class="process-definition-filter" dense outlined clearable debounce="250" :placeholder="t('processes.filter')">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <AgentSelect
        v-model="definitionAgentFilter"
        :options="definitionAgentOptions"
        :label="t('processes.agentFilter')"
        clearable
        dense
        outlined
        class="process-agent-filter"
      />
      <div v-if="canAdmin" class="process-toolbar-actions">
        <q-btn color="secondary" icon="sync" :label="t('processes.syncN8n')" @click="syncN8n" />
        <q-btn color="primary" icon="add" :label="t('processes.newDefinition')" @click="openDefinition()" />
      </div>
    </div>

    <q-banner v-if="store.health" rounded class="q-mb-md" :class="healthBannerClass">
      <template #avatar><q-icon :name="healthIcon" /></template>
      <div class="text-weight-medium">{{ store.health.message }}</div>
      <div v-if="store.operations" class="process-health-stats text-caption q-mt-xs">
        {{ t('processes.pendingJobs', { count: store.operations.pending_start_jobs }) }} ·
        {{ t('processes.staleRuns', { count: store.operations.stale_active_runs }) }} ·
        {{ t('processes.failedToday', { count: store.operations.failed_last_24h }) }}
      </div>
      <template #action>
        <q-btn flat round icon="refresh" :aria-label="t('processes.refresh')" @click="loadOperations" />
      </template>
    </q-banner>

    <q-table
      :rows="store.definitions"
      :columns="definitionColumns"
      :filter="definitionFilter"
      row-key="id"
      :loading="store.loading"
      :grid="$q.screen.lt.md"
      :no-data-label="t('processes.noRows')"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
      class="process-table"
      @row-click="openDefinitionFromRow"
    >
      <template #item="props">
        <div class="process-grid-item">
          <q-card
            flat
            bordered
            class="process-grid-card"
            role="button"
            tabindex="0"
            @click="openDefinition(props.row)"
            @keyup.enter="openDefinition(props.row)"
            @keyup.space.prevent="openDefinition(props.row)"
          >
            <q-card-section class="q-pb-sm">
              <div class="row items-start no-wrap q-gutter-sm">
                <q-avatar size="38px" color="secondary" text-color="white"><q-icon name="account_tree" /></q-avatar>
                <div class="col min-width-0">
                  <div class="text-subtitle2 ellipsis">{{ props.row.label }}</div>
                  <div class="text-caption text-grey-7 ellipsis">{{ toolLabel(props.row.tool_id) }} · {{ props.row.engine_process_id }}</div>
                </div>
                <q-icon name="chevron_right" color="grey-6" size="sm" />
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section class="q-py-sm">
              <div class="row items-center no-wrap q-gutter-sm">
                <q-avatar size="28px" color="primary" text-color="white">
                  <img v-if="props.row.agent_id !== null && avatarUrls[props.row.agent_id]" :src="avatarUrls[props.row.agent_id]" :alt="agentLabel(props.row.agent_id)" />
                  <q-icon v-else name="person" />
                </q-avatar>
                <span class="text-body2 ellipsis">{{ agentLabel(props.row.agent_id) }}</span>
              </div>
              <div v-if="props.row.description" class="process-card-description text-caption text-grey-7 q-mt-sm">{{ props.row.description }}</div>
            </q-card-section>
          </q-card>
        </div>
      </template>
      <template #body-cell-agent_id="props">
        <q-td :props="props">
          <div v-if="props.row.agent_id !== null" class="row items-center no-wrap q-gutter-sm">
            <q-avatar size="32px" color="primary" text-color="white">
              <img v-if="avatarUrls[props.row.agent_id]" :src="avatarUrls[props.row.agent_id]" :alt="agentLabel(props.row.agent_id)" />
              <q-icon v-else name="person" />
            </q-avatar>
            <span>{{ agentLabel(props.row.agent_id) }}</span>
          </div>
          <span v-else>—</span>
        </q-td>
      </template>
      <template #body-cell-tool_id="props"><q-td :props="props">{{ toolLabel(props.row.tool_id) }}</q-td></template>
    </q-table>

    <q-dialog v-model="definitionDialog">
      <q-card class="process-detail-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="account_tree" size="sm" />
          <div class="text-subtitle1 text-weight-medium ellipsis q-ml-sm">
            {{ definitionId ? definitionForm.label : t('processes.newDefinition') }}
          </div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('processes.close')" />
        </q-card-section>

        <q-separator />

        <q-card-section class="process-detail-content">
          <q-form class="q-gutter-md" @submit.prevent="saveDefinition">
            <template v-if="!definitionId">
              <q-banner dense rounded class="bg-blue-1 text-blue-9">
                <template #avatar><q-icon name="lock_open" /></template>
                {{ t('processes.creationNotice') }}
              </q-banner>
              <q-select
                v-model="definitionForm.tool_id"
                :options="toolOptions"
                emit-value
                map-options
                dense
                outlined
                :label="t('processes.tool')"
                @update:model-value="onToolChanged"
              />
              <div v-if="selectedToolCode === 'n8n'" class="process-workflow-select-row">
                <q-select
                  :model-value="definitionForm.engine_process_id"
                  class="col"
                  :options="workflowOptions"
                  emit-value
                  map-options
                  dense
                  outlined
                  :label="t('processes.workflow')"
                  :hint="t('processes.workflowHint')"
                  @update:model-value="onWorkflowChanged"
                >
                  <template #option="scope">
                    <q-item v-bind="scope.itemProps">
                      <q-item-section>
                        <q-item-label>{{ scope.opt.label }}</q-item-label>
                        <q-item-label caption>{{ scope.opt.value }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <q-icon v-if="scope.opt.disable" name="block" color="negative" />
                      </q-item-section>
                    </q-item>
                  </template>
                  <template #no-option><q-item><q-item-section class="text-grey">{{ t('processes.noWorkflow') }}</q-item-section></q-item></template>
                </q-select>
                <q-btn v-if="canAdmin" class="process-workflow-sync" flat round color="secondary" icon="sync" :aria-label="t('processes.syncN8n')" @click="syncSelectedTool" />
              </div>
              <AgentSelect v-model="definitionForm.agent_id" :options="agentOptions" clearable dense outlined :label="t('processes.agent')" />
            </template>

            <q-card v-else flat bordered>
              <q-card-section class="q-py-sm">
                <div class="process-metadata">
                  <div class="process-metadata-item">
                    <q-avatar size="32px" color="grey-3" text-color="grey-7"><q-icon name="extension" size="20px" /></q-avatar>
                    <div><div class="metadata-label">{{ t('processes.tool') }}</div><div class="text-weight-bold">{{ toolLabel(definitionForm.tool_id) }}</div></div>
                  </div>
                  <div class="process-metadata-item">
                    <q-avatar size="32px" color="grey-3" text-color="grey-7">
                      <img v-if="definitionForm.agent_id !== null && avatarUrls[definitionForm.agent_id]" :src="avatarUrls[definitionForm.agent_id]" alt="" />
                      <q-icon v-else name="person" size="20px" />
                    </q-avatar>
                    <div><div class="metadata-label">{{ t('processes.agent') }}</div><div class="text-weight-bold">{{ agentLabel(definitionForm.agent_id) }}</div></div>
                  </div>
                  <div class="process-metadata-item">
                    <q-avatar size="32px" color="grey-3" text-color="grey-7"><q-icon name="fingerprint" size="20px" /></q-avatar>
                    <div><div class="metadata-label">{{ t('processes.engineProcessId') }}</div><div class="text-weight-bold">{{ definitionForm.engine_process_id }}</div></div>
                  </div>
                </div>
              </q-card-section>
            </q-card>

            <q-input v-model="definitionForm.description" outlined type="textarea" autogrow :readonly="!canAdmin" :label="t('processes.description')" />

            <div class="process-definition-actions">
              <q-btn v-if="definitionId && canLaunch" color="green" icon="play_arrow" :label="t('processes.newRun')" :disable="definitionForm.agent_id === null" @click="showRunForm = !showRunForm" />
              <q-btn v-if="canAdmin" color="primary" icon="save" :label="t('processes.save')" :loading="saving" :disable="definitionId === undefined && (!definitionForm.tool_id || !definitionForm.engine_process_id)" @click="saveDefinition" />
              <q-btn v-if="definitionId && canAdmin" color="negative" icon="delete" :label="t('processes.delete')" @click="removeCurrentDefinition" />
            </div>
          </q-form>

          <q-slide-transition>
            <q-card v-if="definitionId && showRunForm && canLaunch" flat bordered class="q-mt-md bg-green-1">
              <q-card-section>
                <div class="text-subtitle2 text-positive q-mb-md"><q-icon name="play_arrow" class="q-mr-xs" />{{ t('processes.launchParameters') }}</div>
                <CodeEditor v-model="runForm.input" language="json" :label="t('processes.input')" :visible-lines="8" :min-lines="5" />
                <div class="process-launch-actions q-mt-md">
                  <q-btn color="green" icon="play_arrow" :label="t('processes.start')" :loading="starting" @click="startRun" />
                </div>
              </q-card-section>
            </q-card>
          </q-slide-transition>

          <q-card v-if="definitionId" flat bordered class="q-mt-md">
            <q-card-section class="run-history-header q-py-sm">
              <div class="text-subtitle2 text-primary"><q-icon name="history" class="q-mr-xs" />{{ t('processes.executions') }}</div>
              <q-space />
              <q-input v-model="runFilter" dense borderless clearable debounce="200" :placeholder="t('processes.filterRuns')" class="run-filter">
                <template #prepend><q-icon name="search" /></template>
              </q-input>
              <q-btn flat round icon="refresh" :aria-label="t('processes.refresh')" @click="loadRunPage()" />
            </q-card-section>
            <q-separator />
            <q-table
              flat
              dense
              :rows="processRuns"
              :columns="runColumns"
              v-model:pagination="runPagination"
              :filter="runFilter"
              :loading="store.loadingRuns"
              :grid="$q.screen.lt.md"
              row-key="id"
              :no-data-label="t('processes.noRuns')"
              :rows-per-page-options="[10, 20, 50, 100, 500]"
              class="run-table"
              @request="onRunsRequest"
              @row-click="openRunFromRow"
            >
              <template #item="props">
                <div class="run-grid-item">
                  <q-card
                    flat
                    bordered
                    class="run-grid-card"
                    role="button"
                    tabindex="0"
                    @click="openRun(props.row)"
                    @keyup.enter="openRun(props.row)"
                    @keyup.space.prevent="openRun(props.row)"
                  >
                    <q-card-section class="q-pb-sm">
                      <div class="row items-center no-wrap q-gutter-sm">
                        <q-chip dense :color="statusColor(props.row.status)" text-color="white">{{ statusLabel(props.row.status) }}</q-chip>
                        <q-space />
                        <q-icon name="chevron_right" color="grey-6" size="sm" />
                      </div>
                      <div class="text-subtitle2 ellipsis q-mt-xs">{{ props.row.summary || shortId(props.row.id) }}</div>
                      <div class="text-caption text-grey-7 ellipsis">{{ agentLabel(props.row.launcher_agent_id) }}</div>
                    </q-card-section>
                    <q-separator />
                    <q-card-section class="run-card-dates q-py-sm text-caption">
                      <div><span class="text-grey-7">{{ t('processes.createdAt') }}</span><span>{{ formatDate(props.row.created_at) }}</span></div>
                      <div><span class="text-grey-7">{{ t('processes.finishedAt') }}</span><span>{{ formatDate(props.row.finished_at) }}</span></div>
                      <div v-if="props.row.error_message" class="process-card-description text-negative">{{ props.row.error_message }}</div>
                    </q-card-section>
                  </q-card>
                </div>
              </template>
              <template #body-cell-status="props"><q-td :props="props"><q-chip dense :color="statusColor(props.row.status)" text-color="white">{{ statusLabel(props.row.status) }}</q-chip></q-td></template>
            </q-table>
          </q-card>

        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog v-model="runDetailDialog" :maximized="$q.screen.lt.md">
      <q-card class="process-run-detail-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="account_tree" size="sm" />
          <div class="text-subtitle1 text-weight-medium ellipsis q-ml-sm">{{ t('processes.details') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('processes.close')" />
        </q-card-section>
        <q-separator />
        <div v-if="runDetailLoading" class="col flex flex-center">
          <q-spinner color="primary" size="2.5em" />
        </div>
        <div v-else-if="store.currentRun" class="process-run-detail-content">
          <ProcessRunDetailContent
            :run="store.currentRun"
            :analysis="store.currentAnalysis"
            :can-operate-runs="canOperateRuns"
            :can-analyze="canAnalyze"
            :can-admin="canAdmin"
            :can-read-tasks="canReadTasks"
            @refresh="refreshCurrent"
            @analyze="analyzeCurrent"
            @retry="retryCurrent"
            @cancel="cancelCurrent"
            @delete="removeRun"
            @copy-id="copyRunId"
          />
        </div>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { agentService } from '@/app/agent/services/agentService'
import { AgentSelect } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CodeEditor, PageHeader } from '@/core/util'
import ProcessRunDetailContent from '../components/ProcessRunDetailContent.vue'
import { useProcessRunActions } from '../composables/useProcessRunActions'
import { useProcessStore } from '../stores/processStore'
import { processService, type AgentOption, type ProcessDefinition, type ProcessRun, type ProcessTool, type ToolProcessDefinition } from '../services/processService'

const store = useProcessStore()
const $q = useQuasar()
const { t, te } = useI18n()
const privilegeStore = usePrivilegeStore()
const canAdmin = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN))
const canLaunch = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_LAUNCH))
const canOperateRuns = computed(() => canLaunch.value || canAdmin.value)
const canAnalyze = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_READ) || canAdmin.value)
const canReadTasks = computed(() => (
  privilegeStore.hasPrivilege(privileges.TASK_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TASK_EDIT)
))
const { runDetailDialog, runDetailLoading, openRun, removeRun, refreshCurrent, cancelCurrent, retryCurrent, analyzeCurrent } = useProcessRunActions({
  store,
  canAdmin: () => canAdmin.value,
  canOperate: () => canOperateRuns.value,
  canAnalyze: () => canAnalyze.value,
  notify, errorDetail, translate: key => t(key),
  confirmRemoval: proceed => {
    showConfirmationDialog({ title: t('common.confirm'), message: t('processes.confirmDeleteRun'), cancel: true }).onOk(proceed)
  },
})
const definitionDialog = ref(false)
const definitionId = ref<number | undefined>()
const definitionFilter = ref('')
const definitionAgentFilter = ref<number | null>(null)
const runFilter = ref('')
const runPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'created_at', descending: true })
const processTools = ref<ProcessTool[]>([])
const showRunForm = ref(false)
const saving = ref(false)
const starting = ref(false)
const definitionForm = reactive({ agent_id: null as number | null, tool_id: null as number | null, engine_process_id: '', label: '', description: null as string | null })
const runForm = reactive({ input: '{}' })
const avatarUrls = reactive<Record<number, string>>({})
const columns = (items: QTableColumn[]): QTableColumn[] => items
const definitionColumns = computed(() => columns([
  { name: 'tool_id', label: t('processes.tool'), field: (row: ProcessDefinition) => toolLabel(row.tool_id), align: 'left', sortable: true },
  { name: 'label', label: t('processes.label'), field: 'label', align: 'left', sortable: true },
  { name: 'agent_id', label: t('processes.agent'), field: (row: ProcessDefinition) => agentLabel(row.agent_id), align: 'left', sortable: true },
  { name: 'description', label: t('processes.description'), field: 'description', align: 'left', sortable: true },
]))
const runColumns = computed(() => columns([
  { name: 'status', label: t('processes.status'), field: 'status', align: 'left', sortable: true },
  { name: 'launcher_agent_id', label: t('processes.agent'), field: (row: ProcessRun) => agentLabel(row.launcher_agent_id), align: 'left', sortable: true },
  { name: 'created_at', label: t('processes.createdAt'), field: (row: ProcessRun) => formatDate(row.created_at), align: 'left', sortable: true },
  { name: 'finished_at', label: t('processes.finishedAt'), field: (row: ProcessRun) => formatDate(row.finished_at), align: 'left', sortable: true },
]))
const processRuns = computed(() => store.runs.filter(run => run.process_id === definitionId.value))
const toolOptions = computed(() => processTools.value.map(tool => ({ label: tool.label, value: tool.id })))
const selectedToolCode = computed(() => processTools.value.find(tool => tool.id === definitionForm.tool_id)?.code ?? '')
const workflowOptions = computed(() => store.discovered.map(workflow => ({
  label: workflow.label,
  value: workflow.engine_process_id,
  disable: !workflow.active,
})))
const agentOptions = computed(() => store.agents.map(agent => ({ label: agentDisplayLabel(agent), value: agent.id })))
const definitionAgentOptions = computed(() => [
  { label: t('processes.allAgents'), value: null },
  ...agentOptions.value,
])

function agentDisplayLabel(agent: AgentOption): string { return `${agent.first_name} ${agent.last_name}`.trim() || '—' }
function agentLabel(agentId: number | null): string { const agent = store.agents.find(item => item.id === agentId); return agent ? agentDisplayLabel(agent) : '—' }
function toolLabel(toolId: number | null): string { return processTools.value.find(tool => tool.id === toolId)?.label ?? '—' }
function defaultToolId(): number | null { return processTools.value.find(tool => tool.code === 'n8n')?.id ?? processTools.value[0]?.id ?? null }
function applyWorkflow(workflow: ToolProcessDefinition): void { Object.assign(definitionForm, { engine_process_id: workflow.engine_process_id, label: workflow.label, description: workflow.description }) }
function onWorkflowChanged(engineProcessId: string): void { const workflow = store.discovered.find(item => item.engine_process_id === engineProcessId); if (workflow) applyWorkflow(workflow) }
function onToolChanged(): void { Object.assign(definitionForm, { engine_process_id: '', label: '', description: null }); store.discovered = [] }
async function syncSelectedTool(): Promise<void> { if (!canAdmin.value || !selectedToolCode.value) return; try { await store.sync(selectedToolCode.value) } catch (error) { console.error(error); notify('negative', errorDetail(error)) } }
async function syncN8n(): Promise<void> { if (!canAdmin.value) return; try { await Promise.all([store.sync('n8n'), loadOperations()]); notify('positive', t('processes.synced')) } catch (error) { console.error(error); notify('negative', errorDetail(error)) } }
async function loadAgentAvatars(): Promise<void> { await Promise.all(store.agents.filter(agent => agent.has_avatar).map(async (agent) => { try { avatarUrls[agent.id] = await agentService.getAvatarBlobUrl(agent.id) } catch (error) { console.error(`Failed to load avatar for agent ${agent.id}:`, error) } })) }
function parseJson(value: string): Record<string, unknown> { const parsed: unknown = JSON.parse(value || '{}'); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('object expected'); return parsed as Record<string, unknown> }
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—' }
function shortId(id: string): string { return `${id.slice(0, 8)}…${id.slice(-4)}` }
function statusLabel(status: string): string { const key = `processes.statuses.${status}`; return te(key) ? t(key) : status }
function statusColor(status: string): string { return ({ success: 'positive', error: 'negative', cancelled: 'grey', running: 'primary', waiting: 'orange', queued: 'blue-grey', cancelling: 'warning', unknown: 'dark' } as Record<string, string>)[status] || 'grey' }
function errorDetail(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return t('processes.genericError')
}
const healthBannerClass = computed(() => ({ healthy: 'bg-green-1 text-positive', degraded: 'bg-orange-1 text-warning', error: 'bg-red-1 text-negative' } as const)[store.health?.status ?? 'error'])
const healthIcon = computed(() => ({ healthy: 'check_circle', degraded: 'warning', error: 'error' } as const)[store.health?.status ?? 'error'])
function notify(type: 'positive' | 'negative', message: string): void { $q.notify({ type, message }) }
function resetDefinition(): void { Object.assign(definitionForm, { agent_id: null, tool_id: defaultToolId(), engine_process_id: '', label: '', description: null }); definitionId.value = undefined; runDetailDialog.value = false; runDetailLoading.value = false; showRunForm.value = false; runForm.input = '{}'; runFilter.value = ''; runPagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'created_at', descending: true }; store.$patch((state) => { state.runs = []; state.runsTotal = 0; state.currentRun = null; state.currentAnalysis = null }) }
async function loadRunPage(page: number = runPagination.value.page, rowsPerPage: number = runPagination.value.rowsPerPage, filter: string = runFilter.value, sortBy: string = runPagination.value.sortBy, descending: boolean = runPagination.value.descending): Promise<void> { if (!definitionForm.engine_process_id) return; await store.loadRuns(definitionForm.engine_process_id, page, rowsPerPage, filter, sortBy, descending); runPagination.value = { page: store.runsPage, rowsPerPage: store.runsPageSize, rowsNumber: store.runsTotal, sortBy: store.runsSortBy, descending: store.runsDescending } }
async function onRunsRequest(props: { pagination: { page: number; rowsPerPage: number; sortBy?: string | null; descending?: boolean }; filter?: string }): Promise<void> { await loadRunPage(props.pagination.page, props.pagination.rowsPerPage, props.filter ?? '', props.pagination.sortBy ?? 'created_at', props.pagination.descending ?? true) }
async function openDefinition(item?: ProcessDefinition): Promise<void> { resetDefinition(); if (item) { definitionId.value = item.id; Object.assign(definitionForm, { agent_id: item.agent_id, tool_id: item.tool_id, engine_process_id: item.engine_process_id, label: item.label, description: item.description }) } definitionDialog.value = true; if (item) await loadRunPage(1, runPagination.value.rowsPerPage, '') }
async function openDefinitionFromRow(_event: Event, row: ProcessDefinition): Promise<void> { await openDefinition(row) }
async function saveDefinition(): Promise<void> {
  if (!canAdmin.value) return
  if (!definitionForm.tool_id) return
  saving.value = true
  try {
    if (definitionId.value !== undefined) {
      const record = await processService.updateDefinition(definitionId.value, { description: definitionForm.description })
      definitionForm.description = record.description
      await store.loadDefinitions(definitionAgentFilter.value ?? undefined)
    } else {
      if (!definitionForm.engine_process_id || !definitionForm.label) return
      const record = await store.saveDefinition(
        { agent_id: definitionForm.agent_id, tool_id: definitionForm.tool_id, engine_process_id: definitionForm.engine_process_id, label: definitionForm.label, description: definitionForm.description },
        definitionAgentFilter.value ?? undefined,
      )
      definitionId.value = record.id
      Object.assign(definitionForm, { agent_id: record.agent_id, tool_id: record.tool_id, engine_process_id: record.engine_process_id, label: record.label, description: record.description })
    }
    notify('positive', t('processes.saved'))
  } catch (error) { console.error(error); notify('negative', errorDetail(error)) }
  finally { saving.value = false }
}
async function removeCurrentDefinition(): Promise<void> { if (!canAdmin.value || definitionId.value === undefined) return; const id = definitionId.value; showConfirmationDialog({ title: t('common.confirm'), message: t('processes.confirmDelete'), cancel: true }).onOk(async () => { await store.deleteDefinition(id); definitionDialog.value = false; notify('positive', t('processes.deleted')) }) }
async function startRun(): Promise<void> {
  if (!canLaunch.value) return
  if (!definitionForm.agent_id || !definitionForm.engine_process_id) return
  starting.value = true
  try {
    await store.startRun({ agent_id: definitionForm.agent_id, workflow_id: definitionForm.engine_process_id, input: parseJson(runForm.input), files: [], wait_for_completion: false })
    await loadRunPage(1)
    showRunForm.value = false
    runForm.input = '{}'
    notify('positive', t('processes.started'))
  } catch (error) { console.error(error); notify('negative', errorDetail(error)) }
  finally { starting.value = false }
}
async function openRunFromRow(_event: Event, row: ProcessRun): Promise<void> { await openRun(row) }
async function copyRunId(id: string): Promise<void> { await copyToClipboard(id); notify('positive', t('processes.copied')) }
async function loadOperations(): Promise<void> {
  try { await Promise.all([store.loadHealth('n8n'), store.loadOperations()]) }
  catch (error) { console.error('Error loading process operations:', error) }
}

watch(
  () => [store.runsPage, store.runsPageSize, store.runsTotal, store.runsSortBy, store.runsDescending] as const,
  ([page, rowsPerPage, rowsNumber, sortBy, descending]) => {
    runPagination.value = { page, rowsPerPage, rowsNumber, sortBy, descending }
  },
)

watch(definitionAgentFilter, agentId => {
  void store.loadDefinitions(agentId ?? undefined).catch((error: unknown) => { console.error(error) })
})

onMounted(async () => {
  try {
    const [tools] = await Promise.all([processService.tools(), store.loadAll(), loadOperations()])
    processTools.value = tools
    definitionForm.tool_id = defaultToolId()
    await loadAgentAvatars()
  } catch { notify('negative', t('processes.genericError')) }
})
onUnmounted(() => { Object.values(avatarUrls).forEach(url => URL.revokeObjectURL(url)) })
</script>

<style scoped>
.process-table :deep(tbody tr), .run-table :deep(tbody tr) { cursor: pointer; }
.process-toolbar { display: flex; align-items: center; gap: 8px; }
.process-definition-filter { flex: 1 1 auto; min-width: 0; }
.process-agent-filter { flex: 0 1 260px; min-width: 200px; }
.process-toolbar-actions, .process-definition-actions, .process-launch-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.process-detail-card { width: 1100px; max-width: 96vw; margin: auto; height: fit-content; max-height: 96vh; overflow-y: auto; }
.process-detail-content { padding: 20px; }
.process-workflow-select-row { display: flex; align-items: flex-start; }
.process-workflow-select-row .q-select { flex: 1 1 auto; min-width: 0; }
.process-workflow-sync { margin-top: 4px; margin-left: 8px; }
.process-metadata { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.process-metadata-item { display: flex; align-items: center; gap: 8px; min-width: 0; }
.metadata-label { color: #667085; font-size: 12px; line-height: 1.2; }
body.body--dark .metadata-label { color: #98a2b8; }
.run-history-header { display: flex; align-items: center; gap: 8px; }
.run-filter { width: 220px; }
.process-grid-item, .run-grid-item { width: 50%; padding: 8px; }
.process-grid-card, .run-grid-card { height: 100%; cursor: pointer; }
.process-grid-card:focus-visible, .run-grid-card:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 2px; }
.process-card-description { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow-wrap: anywhere; }
.run-card-dates { display: grid; gap: 4px; }
.run-card-dates > div:not(.process-card-description) { display: flex; justify-content: space-between; gap: 12px; }
.process-run-detail-dialog { display: flex; flex-direction: column; width: 1100px; max-width: 96vw; height: 90vh; max-height: 900px; }
.process-run-detail-content { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.min-width-0 { min-width: 0; }
@media (max-width: 1023px) {
  .process-toolbar { align-items: stretch; flex-wrap: wrap; }
  .process-definition-filter { flex-basis: 100%; }
  .process-agent-filter { flex: 1 1 260px; }
  .process-toolbar-actions { width: 100%; }
  .process-health-stats { line-height: 1.7; }
  .process-detail-card { width: calc(100vw - 16px); max-width: calc(100vw - 16px); max-height: calc(100vh - 16px); }
  .process-detail-content { padding: 16px; }
  .process-run-detail-dialog { width: 100%; max-width: none; height: 100%; max-height: none; }
  .process-grid-item, .run-grid-item { width: 100%; padding: 6px 0; }
  .run-history-header { align-items: stretch; flex-wrap: wrap; }
  .run-history-header > .q-space { display: none; }
  .run-filter { order: 3; width: 100%; margin: 0; }
}
@media (max-width: 599px) {
  .process-page { padding: 8px; }
  .process-toolbar-actions, .process-definition-actions, .process-launch-actions { display: grid; grid-template-columns: 1fr; }
  .process-agent-filter { flex-basis: 100%; width: 100%; }
  .process-toolbar-actions .q-btn, .process-definition-actions .q-btn, .process-launch-actions .q-btn { width: 100%; }
  .process-detail-content { padding: 12px; }
  .process-workflow-select-row { align-items: stretch; flex-direction: column; }
  .process-workflow-select-row .q-select { width: 100%; }
  .process-workflow-sync { align-self: flex-end; margin: 4px 0 0; }
  .process-metadata { grid-template-columns: 1fr; }
}
</style>
