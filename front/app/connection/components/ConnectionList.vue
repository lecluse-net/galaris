<template>
  <div>
    <!-- Filters and add button. -->
    <div class="row q-mb-md q-gutter-md items-center justify-between connection-toolbar">
      <div class="row q-gutter-md items-center connection-filters">
        <AgentSelect
          v-model="filterAgent"
          :options="agentFilterOptions"
          :label="$t('connection.filterAgent')"
          clearable
          style="min-width: 200px"
          dense
          outlined
          emit-value
          map-options
        />
        <q-select
          v-model="filterTool"
          :options="toolFilterOptions"
          :label="$t('connection.filterTool')"
          clearable
          style="min-width: 200px"
          dense
          outlined
          emit-value
          map-options
        />
        <q-btn-toggle
          v-model="filterState"
          :options="stateFilterOptions"
          color="grey-4"
          text-color="grey-8"
          toggle-color="primary"
          dense
          unelevated
          no-caps
        />
      </div>
      <div class="row q-gutter-sm items-center connection-actions">
        <q-btn
          v-if="canEdit"
          outline
          no-caps
          color="primary"
          icon="refresh"
          :label="$t('connection.refreshTools')"
          :aria-label="$t('connection.refreshToolsTitle')"
          :loading="connectionStore.loading"
          @click="onRefreshTools"
        >
          <q-tooltip>{{ $t('connection.refreshToolsTitle') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="canEdit" color="primary" icon="add" :label="$t('connection.newConnection')" @click="openDialog()" />
      </div>
    </div>

    <q-table
      :rows="filteredConnections"
      :columns="columns"
      :grid="$q.screen.lt.md"
      row-key="id"
      :loading="connectionStore.loading"
      v-model:pagination="pagination"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      class="connection-table"
    >
      <template v-slot:body-cell-agent_id="props">
        <q-td :props="props">
          {{ getAgentName(props.row.agent_id) }}
        </q-td>
      </template>
      <template v-slot:body-cell-tool_id="props">
        <q-td :props="props">
          {{ getToolLabel(props.row.tool_id) }}
          <SystemToolIcon v-if="isSystemTool(props.row.tool_id)" class="q-ml-xs" />
        </q-td>
      </template>
      <template v-slot:body-cell-active="props">
        <q-td :props="props">
          <q-toggle
            v-if="canEdit"
            :model-value="props.row.active"
            color="positive"
            :disable="connectionStore.loading || isSystemTool(props.row.tool_id)"
            @update:model-value="toggleActive(props.row)"
          />
        </q-td>
      </template>
      <template v-slot:body-cell-params="props">
        <q-td :props="props">
          <div v-if="hasVisibleParams(props.row.id, props.row.tool_id)" class="config-table">
            <div
              v-for="param in getVisibleConnectionParams(props.row.id, props.row.tool_id)"
              :key="param.name"
              class="config-row"
            >
              <div class="config-col-name">{{ param.name }}</div>
              <div class="config-col-value">
                {{ formatConfigValue(param.name, param.value, props.row.tool_id) }}
              </div>
            </div>
          </div>
          <span v-else class="text-grey-6 text-italic">-</span>
        </q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn v-if="canEdit && !isSystemTool(props.row.tool_id)" flat round color="primary" icon="edit" size="sm" @click="openDialog(props.row)" />
          <q-btn v-if="canEdit && !isSystemTool(props.row.tool_id)" flat round color="negative" icon="delete" size="sm" @click="confirmDelete(props.row)" />
        </q-td>
      </template>

      <template #item="props">
        <div class="q-table__grid-item col-12">
          <q-card flat bordered class="connection-mobile-card">
            <q-card-section class="q-pa-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <q-icon name="link" color="primary" size="24px" />
                <div class="col connection-mobile-heading">
                  <div class="text-weight-medium ellipsis">
                    {{ getToolLabel(props.row.tool_id) }}
          <SystemToolIcon v-if="isSystemTool(props.row.tool_id)" class="q-ml-xs" />
                  </div>
                  <div class="text-caption text-grey-7 ellipsis">
                    {{ getAgentName(props.row.agent_id) }}
                  </div>
                </div>
                <q-toggle
                  v-if="canEdit"
                  :model-value="props.row.active"
                  color="positive"
                  size="sm"
                  :disable="connectionStore.loading || isSystemTool(props.row.tool_id)"
                  :label="props.row.active ? $t('connection.active') : $t('connection.inactive')"
                  :aria-label="props.row.active ? $t('connection.active') : $t('connection.inactive')"
                  @update:model-value="toggleActive(props.row)"
                />
                <q-badge
                  v-else
                  :color="props.row.active ? 'positive' : 'grey-6'"
                  :label="props.row.active ? $t('connection.active') : $t('connection.inactive')"
                />
              </div>

              <div
                v-if="hasVisibleParams(props.row.id, props.row.tool_id)"
                class="config-table full-width q-mt-sm"
              >
                <div
                  v-for="param in getVisibleConnectionParams(props.row.id, props.row.tool_id)"
                  :key="param.name"
                  class="config-row"
                >
                  <div class="config-col-name">{{ param.name }}</div>
                  <div class="config-col-value">
                    {{ formatConfigValue(param.name, param.value, props.row.tool_id) }}
                  </div>
                </div>
              </div>
            </q-card-section>

            <template v-if="canEdit && !isSystemTool(props.row.tool_id)">
              <q-separator />
              <q-card-actions align="right" class="q-px-sm q-py-xs">
                <q-btn
                  flat round color="primary" icon="edit" size="sm"
                  :aria-label="$t('common.edit')"
                  @click="openDialog(props.row)"
                />
                <q-btn
                  flat round color="negative" icon="delete" size="sm"
                  :aria-label="$t('common.delete')"
                  @click="confirmDelete(props.row)"
                />
              </q-card-actions>
            </template>
          </q-card>
        </div>
      </template>
    </q-table>

    <q-dialog v-model="showDialog">
      <q-card class="connection-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ isEdit ? $t('connection.editDialogTitle') : $t('connection.addDialogTitle') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup />
        </q-card-section>

        <q-banner v-if="saveError" dense inline-actions class="bg-negative text-white">
          <template #avatar>
            <q-icon name="error" />
          </template>
          {{ saveError }}
          <template #action>
            <q-btn
              v-if="existingConnectionTarget"
              flat
              color="white"
              :label="t('connection.showExisting')"
              @click="showExistingConnection"
            />
          </template>
        </q-banner>

        <q-card-section class="connection-dialog-body q-pt-md scroll">
          <ConnectionForm

            :connection="currentConnection"
            :connection-params="currentConnectionParams"
            :configured-params="currentConnectionConfiguredParams"
            :loading="connectionStore.loading"
            :agent-options="agentOptions"
            :tool-options="toolOptions"
            :tools="toolStore.tools"
            :default-agent-id="filterAgent"
            :default-tool-id="filterTool"
            :persist-for-action="persistForAction"
            @submit="onSubmit"
            @configured="onEmbeddedConfigured"
            @cancel="showDialog = false"
          />
        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog v-model="showDeleteDialog">
      <q-card>
        <q-card-section class="galaris-dialog-title">
          <div class="text-h6">{{ $t('connection.deleteTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section>
          {{ $t('connection.deleteMessage') }}
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="$t('common.cancel')" color="primary" v-close-popup />
          <q-btn v-if="canEdit" flat :label="$t('common.delete')" color="negative" @click="onDelete" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { isAxiosError } from 'axios'
import { ref, computed, onMounted, watch } from 'vue'
import type { QTableProps } from 'quasar'
import { useQuasar } from 'quasar'
import { useConnectionStore, type Connection } from '../stores/connectionStore'
import type { ConnectionCreate, ConnectionUpdate } from '../services/connectionService'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { AgentSelect } from '@/app/agent'
import { useToolStore } from '@/app/tools/stores/toolStore'
import type { Tool } from '@/app/tools/services/toolService'
import ConnectionForm from './ConnectionForm.vue'
import { SystemToolIcon } from '@/app/tools'
import { useI18n } from 'vue-i18n'
import { toolMessageKey } from '@/app/tools/presentation'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { mailService, type MailApproverOption } from '../services/mailService'
import { refreshMailAvailability } from '../availability'

const SESSION_FILTER_AGENT_KEY = 'connection_filter_agent_id'
const SESSION_FILTER_TOOL_KEY = 'connection_filter_tool_id'
const SESSION_FILTER_STATE_KEY = 'connection_filter_state'

type FilterState = 'active' | 'inactive' | 'all'
interface ExistingConnectionTarget {
  agentId: number
  toolId: number
}

interface ConnectionPersistencePayload {
  id: number | null
  data: { agent_id: number; tool_id: number; active: boolean }
  params: Record<string, string | null>
}

interface VisibleConnectionParam {
  name: string
  value: unknown
}

const connectionStore = useConnectionStore()
const agentStore = useAgentStore()
const toolStore = useToolStore()
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))

const showDialog = ref(false)
const showDeleteDialog = ref(false)
const currentConnection = ref<Connection | null>(null)
const currentConnectionParams = ref<Record<string, unknown> | null>(null)
const currentConnectionConfiguredParams = ref<string[]>([])
const connectionToDelete = ref<Connection | null>(null)
const saveError = ref<string | null>(null)
const existingConnectionTarget = ref<ExistingConnectionTarget | null>(null)
const approverLabels = ref<Map<number, string>>(new Map())

const filterAgent = ref<number | null>(null)
const filterTool = ref<number | null>(null)
const filterState = ref<FilterState>('active')

function loadFiltersFromSession(): void {
  const agentRaw = sessionStorage.getItem(SESSION_FILTER_AGENT_KEY)
  const toolRaw = sessionStorage.getItem(SESSION_FILTER_TOOL_KEY)
  if (agentRaw !== null) {
    const parsed = Number(agentRaw)
    filterAgent.value = Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }
  if (toolRaw !== null) {
    const parsed = Number(toolRaw)
    filterTool.value = Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }
  const stateRaw = sessionStorage.getItem(SESSION_FILTER_STATE_KEY)
  if (stateRaw === 'active' || stateRaw === 'inactive' || stateRaw === 'all') {
    filterState.value = stateRaw
  }
}

function saveFiltersToSession(): void {
  if (filterAgent.value !== null) {
    sessionStorage.setItem(SESSION_FILTER_AGENT_KEY, String(filterAgent.value))
  } else {
    sessionStorage.removeItem(SESSION_FILTER_AGENT_KEY)
  }
  if (filterTool.value !== null) {
    sessionStorage.setItem(SESSION_FILTER_TOOL_KEY, String(filterTool.value))
  } else {
    sessionStorage.removeItem(SESSION_FILTER_TOOL_KEY)
  }
  sessionStorage.setItem(SESSION_FILTER_STATE_KEY, filterState.value)
}

const pagination = ref({
  sortBy: 'id',
  descending: false,
  page: 1,
  rowsPerPage: 50
})

const isEdit = computed(() => !!currentConnection.value)

const agentFilterOptions = computed(() =>
  agentStore.agents.map(e => ({ label: `${e.first_name} ${e.last_name}`, value: e.id }))
)

const toolFilterOptions = computed(() =>
  toolStore.tools.map(tool => ({ label: localizedToolLabel(tool), value: tool.id }))
)

const stateFilterOptions = computed(() => [
  { label: t('connection.stateActive'), value: 'active' as FilterState },
  { label: t('connection.stateInactive'), value: 'inactive' as FilterState },
  { label: t('connection.stateAll'), value: 'all' as FilterState }
])

const filteredConnections = computed(() => {
  let result = connectionStore.connections
  if (filterAgent.value !== null)
    result = result.filter(c => c.agent_id === filterAgent.value)
  if (filterTool.value !== null)
    result = result.filter(c => c.tool_id === filterTool.value)
  if (filterState.value === 'active')
    result = result.filter(c => c.active)
  else if (filterState.value === 'inactive')
    result = result.filter(c => !c.active)
  return result
})

const columns = computed<QTableProps['columns']>(() => [
  { name: 'agent_id', label: t('connection.colAgent'), field: 'agent_id', sortable: true, align: 'left' },
  { name: 'tool_id', label: t('connection.colTool'), field: 'tool_id', sortable: true, align: 'left' },
  { name: 'active', label: t('connection.colState'), field: 'active', sortable: true, align: 'center' },
  { name: 'params', label: t('connection.colParams'), field: 'params', align: 'left' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' }
])

const agentOptions = computed(() =>
  agentStore.agents.map(e => ({
    value: e.id,
    label: `${e.first_name} ${e.last_name}`,
    agentDriver: e.agent_driver,
  }))
)

const toolOptions = computed(() =>
  toolStore.tools.filter(tool => tool.can_disable !== false).map(tool => ({ id: tool.id, label: localizedToolLabel(tool) }))
)

function localizedToolLabel(tool: Tool): string {
  const key = toolMessageKey(tool.code, 'label')
  return key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
}

function getAgentName(agentId: number): string {
  const e = agentStore.agents.find(e => e.id === agentId)
  return e ? `${e.first_name} ${e.last_name}` : `ID: ${agentId}`
}

function isSystemTool(toolId: number): boolean {
  return toolStore.tools.find(tool => tool.id === toolId)?.can_disable === false
}
function getToolLabel(toolId: number): string {
  const tool = toolStore.tools.find(item => item.id === toolId)
  return tool ? localizedToolLabel(tool) : `ID: ${toolId}`
}

function getToolSchema(toolId: number) {
  const t = toolStore.tools.find(t => t.id === toolId)
  return t?.connection_schema?.params ?? null
}

function isPasswordField(fieldName: string, toolId: number): boolean {
  const params = getToolSchema(toolId)
  return params?.[fieldName]?.type === 'password'
}

function isUserField(fieldName: string, toolId: number): boolean {
  const params = getToolSchema(toolId)
  return params?.[fieldName]?.type === 'user'
}

function isGloballyForcedField(fieldName: string, toolId: number): boolean {
  const tool = toolStore.tools.find(tool => tool.id === toolId)
  const globalParam = tool?.global_params?.[fieldName]
  return globalParam?.configured === true && globalParam.forced === true
}

function hasDisplayValue(value: unknown): boolean {
  return value !== null
    && value !== undefined
    && (typeof value !== 'string' || value.trim().length > 0)
}

function formatConfigValue(fieldName: string, value: unknown, toolId: number): string {
  if (value === null || value === undefined) return '-'
  if (isUserField(fieldName, toolId)) {
    const userId = Number(value)
    return Number.isInteger(userId) && userId > 0
      ? approverLabels.value.get(userId) ?? t('connection.mail.userUnavailable')
      : '-'
  }
  if (typeof value === 'boolean') return value ? t('common.yes') : t('common.no')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function getConnectionParams(connectionId: number): Record<string, unknown> {
  return connectionStore.getParamsForConnection(connectionId) || {}
}

function getVisibleConnectionParams(connectionId: number, toolId: number): VisibleConnectionParam[] {
  return Object.entries(getConnectionParams(connectionId))
    .filter(([name, value]) => (
      !isPasswordField(name, toolId)
      && !isGloballyForcedField(name, toolId)
      && hasDisplayValue(value)
    ))
    .map(([name, value]) => ({ name, value }))
}

function hasVisibleParams(connectionId: number, toolId: number): boolean {
  return getVisibleConnectionParams(connectionId, toolId).length > 0
}

async function openDialog(connection?: Connection) {
  if (!canEdit.value || (connection && isSystemTool(connection.tool_id))) return
  saveError.value = null
  existingConnectionTarget.value = null
  currentConnection.value = connection || null
  if (connection) {
    try {
      await connectionStore.fetchConnectionParams(connection.id)
      currentConnectionParams.value = connectionStore.getParamsForConnection(connection.id)
      currentConnectionConfiguredParams.value = connectionStore.getConfiguredParamsForConnection(connection.id)
    } catch {
      currentConnectionParams.value = null
      currentConnectionConfiguredParams.value = []
    }
  } else {
    currentConnectionParams.value = null
    currentConnectionConfiguredParams.value = []
  }
  showDialog.value = true
}

function confirmDelete(connection: Connection) {
  if (!canEdit.value || isSystemTool(connection.tool_id)) return
  connectionToDelete.value = connection
  showDeleteDialog.value = true
}

async function toggleActive(connection: Connection) {
  if (!canEdit.value || isSystemTool(connection.tool_id)) return
  const newActive = !connection.active
  try {
    await connectionStore.updateConnection(connection.id, { active: newActive })
    await refreshMailAvailability()
    $q.notify({
      type: 'positive',
      message: newActive ? t('connection.activated') : t('connection.deactivated')
    })
  } catch (error) {
    console.error('Error toggling connection active state:', error)
    $q.notify({ type: 'negative', message: t('connection.toggleError') })
  }
}

async function onRefreshTools() {
  if (!canEdit.value) return
  try {
    const result = await connectionStore.refreshToolCatalogs()
    if (result.created > 0) {
      await connectionStore.fetchConnections(
        filterTool.value ?? undefined,
        filterAgent.value ?? undefined
      )
      await loadAllConnectionParams()
    }
    $q.notify({
      type: result.complete ? 'positive' : 'warning',
      message: result.complete
        ? t('connection.refreshToolsComplete', {
            created: result.created,
            agents: result.agents_refreshed,
            tools: result.tools_discovered,
            documents: result.documents_indexed
          })
        : t('connection.refreshToolsPartial', {
            agents: result.agents_refreshed,
            total: result.agents_scanned,
            sources: result.source_failures,
            failures: result.agent_failures
          })
    })
  } catch (error) {
    console.error('Error refreshing tool catalogs:', error)
    $q.notify({ type: 'negative', message: t('connection.refreshToolsError') })
  }
}

async function persistForAction(payload: ConnectionPersistencePayload): Promise<Connection> {
  if (!canEdit.value) throw new Error(t('connection.saveError'))
  saveError.value = null
  existingConnectionTarget.value = null

  const duplicate = connectionStore.connections.find(connection =>
    connection.id !== payload.id
    && connection.agent_id === payload.data.agent_id
    && connection.tool_id === payload.data.tool_id
  )
  if (duplicate) {
    setDuplicateError(payload.data.agent_id, payload.data.tool_id)
    throw new Error(duplicateConnectionMessage(payload.data.agent_id, payload.data.tool_id))
  }

  try {
    const inactiveData = { ...payload.data, active: false }
    const connection = payload.id
      ? await connectionStore.updateConnection(payload.id, inactiveData)
      : await connectionStore.createConnection(inactiveData)

    if (Object.keys(payload.params).length > 0) {
      await connectionStore.createOrUpdateParamsBulk(connection.id, payload.params)
    }
    return connection
  } catch (error) {
    saveError.value = apiErrorDetail(error) || t('connection.saveError')
    throw error
  }
}

async function onSubmit(payload: ConnectionPersistencePayload) {
  if (!canEdit.value) return
  saveError.value = null
  existingConnectionTarget.value = null

  const duplicate = connectionStore.connections.find(connection =>
    connection.id !== payload.id
    && connection.agent_id === payload.data.agent_id
    && connection.tool_id === payload.data.tool_id
  )
  if (duplicate) {
    setDuplicateError(payload.data.agent_id, payload.data.tool_id)
    return
  }

  try {
    let connection: Connection

    if (payload.id) {
      const updateData: ConnectionUpdate = { ...payload.data }
      connection = await connectionStore.updateConnection(payload.id, updateData)
    } else {
      const createData: ConnectionCreate = { ...payload.data }
      connection = await connectionStore.createConnection(createData)
    }

    if (connection && Object.keys(payload.params).length > 0) {
      await connectionStore.createOrUpdateParamsBulk(connection.id, payload.params)
    }

    showDialog.value = false
    currentConnection.value = null
    currentConnectionParams.value = null
    currentConnectionConfiguredParams.value = []

    await connectionStore.fetchConnections(filterTool.value ?? undefined, filterAgent.value ?? undefined)
    await refreshMailAvailability()
    $q.notify({
      type: 'positive',
      message: payload.id ? t('connection.updated') : t('connection.created')
    })
  } catch (error) {
    console.error('Error saving connection:', error)
    if (isAxiosError(error) && error.response?.status === 409) {
      setDuplicateError(payload.data.agent_id, payload.data.tool_id)
    } else {
      saveError.value = apiErrorDetail(error) || t('connection.saveError')
    }
  }
}

async function onEmbeddedConfigured(): Promise<void> {
  showDialog.value = false
  currentConnection.value = null
  currentConnectionParams.value = null
  currentConnectionConfiguredParams.value = []
  await connectionStore.fetchConnections(filterTool.value ?? undefined, filterAgent.value ?? undefined)
  await loadAllConnectionParams()
  await refreshMailAvailability()
}

function duplicateConnectionMessage(agentId: number, toolId: number): string {
  return t('connection.duplicateError', {
    agent: getAgentName(agentId),
    tool: getToolLabel(toolId)
  })
}

function setDuplicateError(agentId: number, toolId: number): void {
  existingConnectionTarget.value = { agentId, toolId }
  saveError.value = duplicateConnectionMessage(agentId, toolId)
}

function showExistingConnection(): void {
  const target = existingConnectionTarget.value
  if (!target) return
  filterAgent.value = target.agentId
  filterTool.value = target.toolId
  filterState.value = 'all'
  showDialog.value = false
  currentConnection.value = null
  currentConnectionParams.value = null
  currentConnectionConfiguredParams.value = []
}

function apiErrorDetail(error: unknown): string | null {
  if (!isAxiosError(error)) return null
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null

  const messages = detail
    .map(item => {
      if (!item || typeof item !== 'object') return null
      const message = 'message' in item ? item.message : 'msg' in item ? item.msg : null
      return typeof message === 'string' ? message : null
    })
    .filter((message): message is string => Boolean(message))
  return messages.length ? messages.join('\n') : null
}

async function onDelete() {
  if (!canEdit.value) return
  if (connectionToDelete.value) {
    try {
      await connectionStore.deleteConnection(connectionToDelete.value.id)
      await refreshMailAvailability()
      connectionToDelete.value = null
    } catch (error) {
      console.error('Error deleting connection:', error)
    }
  }
}

async function loadAllConnectionParams() {
  await Promise.all(
    connectionStore.connections.map(conn =>
      connectionStore.fetchConnectionParams(conn.id).catch(() => null)
    )
  )
}

async function loadApproverLabels(): Promise<void> {
  try {
    const { data } = await mailService.listApprovers()
    approverLabels.value = new Map(
      data.map((user: MailApproverOption) => [user.id, user.label])
    )
  } catch (error) {
    console.error('Error loading Mail approver labels:', error)
    $q.notify({ type: 'negative', message: t('connection.mail.approversError') })
  }
}

watch([filterAgent, filterTool], async () => {
  saveFiltersToSession()
  await connectionStore.fetchConnections(
    filterTool.value ?? undefined,
    filterAgent.value ?? undefined
  )
  await loadAllConnectionParams()
})

// Apply the status filter client-side without reloading.
watch(filterState, saveFiltersToSession)

onMounted(async () => {
  loadFiltersFromSession()
  await Promise.all([
    connectionStore.fetchConnections(
      filterTool.value ?? undefined,
      filterAgent.value ?? undefined
    ),
    agentStore.fetchAgents(),
    toolStore.fetchTools(),
    loadApproverLabels(),
  ])
  await loadAllConnectionParams()
})
</script>

<style scoped>
.config-table {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  overflow: hidden;
  font-size: 0.85rem;
  max-width: 400px;
}

.connection-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.connection-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 0;
}

.connection-mobile-card,
.connection-mobile-heading {
  min-width: 0;
}

.config-row {
  display: flex;
  border-bottom: 1px solid #f0f0f0;
}

.config-row:last-child {
  border-bottom: none;
}

.config-col-name {
  width: 40%;
  padding: 4px 8px;
  border-right: 1px solid #e0e0e0;
  font-weight: 600;
  color: #424242;
  background-color: #fafafa;
  word-break: break-word;
}

.config-col-value {
  width: 60%;
  padding: 4px 8px;
  word-break: break-word;
  background-color: #ffffff;
}

body.body--dark .config-table {
  border-color: #3a3f47;
}

body.body--dark .config-row {
  border-bottom-color: #2e3238;
}

body.body--dark .config-col-name {
  border-right-color: #3a3f47;
  color: #cfcfcf;
  background-color: #262626;
}

body.body--dark .config-col-value {
  background-color: #1d1d1d;
}

.connection-dialog-card {
  display: flex;
  flex-direction: column;
  width: min(1100px, calc(100vw - 32px));
  max-width: 1100px;
  max-height: 80vh;
}

.connection-dialog-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

@media (max-width: 1023px) {
  .connection-toolbar,
  .connection-filters,
  .connection-actions {
    width: 100%;
  }

  .connection-filters > .q-field {
    flex: 1 1 calc(50% - 16px);
    min-width: 0 !important;
  }

  .connection-filters > .q-btn-group {
    flex: 1 1 100%;
  }

  .connection-actions > .q-btn {
    flex: 1 1 0;
    min-width: 0;
  }
}

@media (max-width: 599px) {
  .connection-filters > .q-field {
    flex-basis: 100%;
  }
}
</style>
