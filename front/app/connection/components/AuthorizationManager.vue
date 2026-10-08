<template>
  <div>
    <q-banner class="bg-grey-2 text-grey-8 q-mb-md" dense rounded>
      <template v-slot:avatar>
        <q-icon name="shield" color="primary" />
      </template>
      {{ $t('connection.auth.intro') }}
    </q-banner>

    <!-- Row 1: filters. -->
    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="col-auto">
        <span class="text-subtitle2 text-primary text-weight-bold section-label">
          <q-icon name="filter_alt" size="xs" class="q-mr-xs" />
          {{ $t('connection.auth.filters') }}
        </span>
      </div>
      <div class="col-12 col-md-3">
        <AgentSelect
          v-model="filterAgent"
          :options="agentFilterOptions"
          :label="$t('connection.filterAgent')"
          clearable
          dense
          outlined
          emit-value
          map-options
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filterTool"
          :options="toolFilterOptions"
          :label="$t('connection.filterTool')"
          clearable
          dense
          outlined
          emit-value
          map-options
        />
      </div>
    </div>

    <!-- Row 2: connection selection -->
    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="col-auto">
        <span class="text-subtitle2 text-primary text-weight-bold section-label">
          <q-icon name="account_tree" size="xs" class="q-mr-xs" />
          {{ $t('connection.auth.connection') }}
        </span>
      </div>
      <div class="col-12 col-md-grow">
        <q-select
          v-model="selectedConnectionId"
          :options="connectionOptions"
          :label="$t('connection.auth.selectConnection')"
          clearable
          dense
          outlined
          emit-value
          map-options
          :loading="connectionsLoading"
          :disable="connectionOptions.length === 0"
        />
      </div>
    </div>

    <q-banner
      v-if="connectionsError"
      class="bg-negative text-white q-mb-md"
      dense
      rounded
    >
      <template #avatar><q-icon name="error" /></template>
      {{ connectionsError }}
      <template #action>
        <q-btn
          flat
          color="white"
          icon="refresh"
          :label="$t('common.retry')"
          @click="loadConnections"
        />
      </template>
    </q-banner>

    <q-banner
      v-else-if="!connectionsLoading && connectionOptions.length === 0"
      class="bg-orange-1 text-warning q-mb-md"
      dense
      rounded
    >
      <template #avatar><q-icon name="filter_alt_off" /></template>
      {{ $t(activeConnections.length === 0
        ? 'connection.auth.noActiveConnections'
        : 'connection.auth.noMatchingConnections') }}
      <template #action>
        <q-btn
          v-if="hasConnectionFilters"
          flat
          color="primary"
          icon="filter_alt_off"
          :label="$t('connection.auth.resetFilters')"
          @click="resetConnectionFilters"
        />
      </template>
    </q-banner>

    <!-- No selected connection -->
    <div
      v-if="!connectionsLoading && !connectionsError && connectionOptions.length > 0 && selectedConnectionId === null"
      class="full-width row flex-center text-grey-7 q-gutter-sm q-pa-lg"
    >
      <q-icon size="2em" name="rule" />
      <span>{{ $t('connection.auth.noConnectionSelected') }}</span>
    </div>

    <!-- Row 3: connection functions and actions -->
    <template v-if="selectedConnectionId !== null">
      <p v-if="systemConnection"><SystemToolIcon /> {{ $t('tools.systemServiceHint') }}</p>
      <div class="row items-center q-mb-xs justify-between authorization-function-toolbar">
        <q-input
          v-model="search"
          :label="$t('connection.auth.search')"
          dense
          outlined
          clearable
          style="min-width: 240px"
          class="authorization-search"
        >
          <template v-slot:prepend><q-icon name="search" /></template>
        </q-input>
        <q-select outlined emit-value map-options
          v-model="filterState"
          :aria-label="$t('connection.auth.colEffective')"
          :options="stateFilterOptions"
          dense
        />
      </div>

      <q-banner v-if="loadError" class="bg-negative text-white q-mb-md" dense rounded>
        <template v-slot:avatar><q-icon name="error" /></template>
        {{ loadError }}
      </q-banner>

      <q-table
        :rows="filteredFunctions"
        :columns="columns"
        :grid="$q.screen.lt.md"
        row-key="key"
        :loading="loading"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :pagination="{ rowsPerPage: 50 }"
        flat
        bordered
        class="authorization-table"
      >
        <template #no-data>
          <div class="full-width row flex-center text-grey-7 q-gutter-sm q-pa-lg">
            <q-icon size="2em" name="rule" />
            <span>
              {{ functions.length > 0
                ? $t('connection.auth.noMatchingFunctions')
                : $t('connection.auth.noFunctions') }}
            </span>
            <q-btn
              v-if="functions.length > 0"
              flat
              dense
              color="primary"
              icon="filter_alt_off"
              :label="$t('connection.auth.resetFunctionFilters')"
              @click="resetFunctionFilters"
            />
          </div>
        </template>
        <template v-slot:body-cell-name="props">
          <q-td :props="props">
            <span class="text-weight-medium">{{ props.row.name }}</span>
            <div class="text-caption">{{ $t(`connection.auth.kind.${props.row.capability_kind}`) }}</div>
          </q-td>
        </template>
        <template v-slot:body-cell-description="props">
          <q-td :props="props">
            <span class="text-grey-8">{{ props.row.description || '—' }}</span>
          </q-td>
        </template>
        <template v-slot:body-cell-global="props">
          <q-td :props="props" class="text-center">
            <FunctionPolicyToggle
              v-if="canEdit && canManageAllAgents"
              :aria-label="$t('connection.auth.colGlobal') + ': ' + props.row.name"
              :model-value="props.row.connection_state === 'default' ? globalPolicyState(props.row) : null"
              :aria-busy="savingRows.has(props.row)"
              @update:model-value="onGlobalState(props.row, $event)"
            />
            <span v-else>{{ policyLabel(globalPolicyState(props.row)) }}</span>
          </q-td>
        </template>
        <template v-slot:body-cell-connection="props">
          <q-td :props="props" class="text-center">
            <FunctionPolicyToggle
              v-if="canEdit"
              :aria-label="$t('connection.auth.colConnection') + ': ' + props.row.name"
              :model-value="props.row.connection_state === 'default' ? null : props.row.connection_state"
              :aria-busy="savingRows.has(props.row)"
              @update:model-value="onConnectionState(props.row, $event)"
            />
            <span v-else>{{ policyLabel(props.row.connection_state) }}</span>
          </q-td>
        </template>
        <template v-slot:body-cell-effective="props">
          <q-td :props="props" class="text-center">
            <span>{{ policyLabel(props.row.effective_state) }}</span>
          </q-td>
        </template>

        <template #item="props">
          <div class="q-table__grid-item col-12">
            <q-card flat bordered class="authorization-mobile-card">
              <q-card-section class="q-pa-md">
                <div class="row items-start no-wrap q-gutter-sm">
                  <div class="col authorization-mobile-heading">
                    <div class="text-weight-medium authorization-function-name">
                      {{ props.row.name }}
                    </div>
                    <div v-if="props.row.description" class="text-caption text-grey-7 q-mt-xs authorization-description">
                      {{ props.row.description }}
                    </div>
                  </div>
                  <q-icon
                    :name="props.row.effective_state === 'ask' ? 'pending_actions' : props.row.effective ? 'check_circle' : 'block'"
                    :color="props.row.effective ? 'positive' : 'grey-5'"
                    size="sm"
                    :aria-label="policyLabel(props.row.effective_state)"
                  >
                    <q-tooltip>{{ policyLabel(props.row.effective_state) }}</q-tooltip>
                  </q-icon>
                </div>

                <div class="text-caption q-mt-sm">
                  {{ policyLabel(props.row.effective_state) }}
                </div>

                <div class="authorization-mobile-settings q-mt-md">
                  <div>
                    <div class="text-caption text-grey-7 q-mb-xs">
                      {{ $t('connection.auth.colGlobal') }}
                    </div>
                    <FunctionPolicyToggle
                      v-if="canEdit && canManageAllAgents"
                      :aria-label="$t('connection.auth.colGlobal') + ': ' + props.row.name"
                      :model-value="props.row.connection_state === 'default' ? globalPolicyState(props.row) : null"
                      :aria-busy="savingRows.has(props.row)"
                      @update:model-value="onGlobalState(props.row, $event)"
                    />
                    <span v-else>{{ policyLabel(globalPolicyState(props.row)) }}</span>
                  </div>
                  <div>
                    <div class="text-caption text-grey-7 q-mb-xs">
                      {{ $t('connection.auth.colConnection') }}
                    </div>
                    <FunctionPolicyToggle
                      v-if="canEdit"
                      :aria-label="$t('connection.auth.colConnection') + ': ' + props.row.name"
                      :model-value="props.row.connection_state === 'default' ? null : props.row.connection_state"
                      :aria-busy="savingRows.has(props.row)"
                      @update:model-value="onConnectionState(props.row, $event)"
                    />
                    <span v-else>{{ policyLabel(props.row.connection_state) }}</span>
                  </div>
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onActivated, onMounted, onUnmounted, watch } from 'vue'
import type { QTableProps } from 'quasar'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { toolMessageKey } from '@/app/tools/presentation'
import { AgentSelect } from '@/app/agent'
import { SystemToolIcon } from '@/app/tools'
import connectionService, {
  saveFunctionPolicy,
  waitForFunctionPolicyWrites,
  type Connection,
  type ConnectionFunctionInfo,
  type EffectiveFunctionState,
  type FunctionState,
  type FunctionStateResolved,
  type FunctionPolicyChange,
} from '../services/connectionService'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { useToolStore } from '@/app/tools/stores/toolStore'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import FunctionPolicyToggle from './FunctionPolicyToggle.vue'

const SESSION_FILTER_AGENT_KEY = 'authorization_filter_agent_id'
const SESSION_FILTER_TOOL_KEY = 'authorization_filter_tool_id'
const SESSION_FILTER_STATE_KEY = 'authorization_filter_state'
const CONNECTION_PAGE_SIZE = 500

type FilterState = 'active' | 'inactive' | 'all'

const $q = useQuasar()
const { t } = useI18n()
const agentStore = useAgentStore()
const toolStore = useToolStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))
const canManageAllAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))

const filterAgent = ref<number | null>(null)
const filterTool = ref<number | null>(null)
const filterState = ref<FilterState>('all')
const selectedConnectionId = ref<number | null>(null)

const connections = ref<Connection[]>([])
const systemConnection = computed(() => {
  const connection = connections.value.find(item => item.id === selectedConnectionId.value)
  return toolStore.tools.find(tool => tool.id === connection?.tool_id)?.can_disable === false
})
const connectionsLoading = ref(true)
const connectionsError = ref<string | null>(null)
const functions = ref<ConnectionFunctionInfo[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const search = ref('')
let initialized = false
let connectionRequestId = 0
let functionRequestId = 0
const savingRows = ref(new Set<ConnectionFunctionInfo>())
const policySaves = new Map<ConnectionFunctionInfo, {
  confirmed: FunctionStateResolved
  pending: FunctionPolicyChange[]
}>()
let disposed = false

// Display the software policy; every button click saves an explicit rule,
// including choosing that same policy when no global rule exists yet.
function globalPolicyState(row: ConnectionFunctionInfo): EffectiveFunctionState {
  return row.global_state === 'default' ? row.default_state : row.global_state
}

const policyLabel = (state: FunctionState) => t(`connection.auth.${state === 'ask' ? 'stateAsk' : state === 'disabled' ? 'stateDisabled' : state === 'enabled' ? 'stateEnabled' : 'stateDefault'}`)

const agentFilterOptions = computed(() =>
  agentStore.agents.map(a => ({ label: `${a.first_name} ${a.last_name}`, value: a.id }))
)

const toolFilterOptions = computed(() =>
  toolStore.tools.map(tool => ({ label: localizedToolLabel(tool), value: tool.id }))
)

function localizedToolLabel(tool: { code: string; label: string; can_edit?: boolean }): string {
  const key = toolMessageKey(tool.code, 'label')
  return key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
}

const stateFilterOptions = computed(() => [
  { label: t('connection.stateActive'), value: 'active' as FilterState },
  { label: t('connection.stateInactive'), value: 'inactive' as FilterState },
  { label: t('connection.stateAll'), value: 'all' as FilterState },
])

function getAgentName(agentId: number): string {
  const a = agentStore.agents.find(e => e.id === agentId)
  return a ? `${a.first_name} ${a.last_name}` : `#${agentId}`
}

function getToolLabel(toolId: number): string {
  const tool = toolStore.tools.find(e => e.id === toolId)
  return tool ? localizedToolLabel(tool) : `#${toolId}`
}

// Only active connections can expose MCP functions and therefore be selected.
const activeConnections = computed(() => connections.value.filter(connection => connection.active))
const hasConnectionFilters = computed(() => filterAgent.value !== null || filterTool.value !== null)

const connectionOptions = computed(() =>
  activeConnections.value
    .filter(c => filterAgent.value === null || c.agent_id === filterAgent.value)
    .filter(c => filterTool.value === null || c.tool_id === filterTool.value)
    .map(c => ({
      label: `${getAgentName(c.agent_id)} — ${getToolLabel(c.tool_id)}`,
      value: c.id,
    }))
)

async function loadConnections(): Promise<void> {
  const requestId = ++connectionRequestId
  connectionsLoading.value = true
  connectionsError.value = null
  try {
    const loadedConnections: Connection[] = []
    let skip = 0
    while (true) {
      const { data } = await connectionService.getConnections(
        undefined,
        undefined,
        true,
        skip,
        CONNECTION_PAGE_SIZE
      )
      if (requestId !== connectionRequestId) return
      loadedConnections.push(...data)
      if (data.length < CONNECTION_PAGE_SIZE) break
      skip += data.length
    }
    connections.value = loadedConnections
  } catch (error) {
    if (requestId !== connectionRequestId) return
    console.error('Error loading authorization connections:', error)
    connections.value = []
    connectionsError.value = t('connection.auth.loadConnectionsError')
  } finally {
    if (requestId === connectionRequestId) connectionsLoading.value = false
  }
}

// Filter MCP functions by effective state after global/connection cascading, then by search text.
const filteredFunctions = computed(() => {
  let result = functions.value
  if (filterState.value !== 'all') {
    const wantActive = filterState.value === 'active'
    result = result.filter(f => f.effective === wantActive)
  }
  const q = search.value?.trim().toLowerCase() ?? ''
  if (q) {
    result = result.filter(
      f => f.name.toLowerCase().includes(q) || f.description.toLowerCase().includes(q)
    )
  }
  return result
})

const columns = computed<QTableProps['columns']>(() => [
  {
    name: 'name',
    label: t('connection.auth.colFunction'),
    field: 'name',
    align: 'left',
    sortable: true,
    style: 'white-space: normal; word-break: break-word; vertical-align: top; width: 220px;',
    headerStyle: 'width: 220px;',
  },
  {
    name: 'description',
    label: t('connection.auth.colDescription'),
    field: 'description',
    align: 'left',
    style: 'white-space: normal; word-break: break-word; vertical-align: top; max-width: 0;',
  },
  {
    name: 'global',
    label: t('connection.auth.colGlobal'),
    field: 'global_state',
    align: 'center',
    style: 'vertical-align: top; width: 180px;',
    headerStyle: 'width: 180px;',
  },
  {
    name: 'connection',
    label: t('connection.auth.colConnection'),
    field: 'connection_state',
    align: 'center',
    style: 'vertical-align: top; width: 230px;',
    headerStyle: 'width: 230px;',
  },
  {
    name: 'effective',
    label: t('connection.auth.colEffective'),
    field: 'effective',
    align: 'center',
    sortable: true,
    style: 'vertical-align: middle; width: 90px;',
    headerStyle: 'width: 90px;',
  },
])

async function loadFunctions(): Promise<void> {
  const connectionId = selectedConnectionId.value
  const requestId = ++functionRequestId
  if (connectionId === null) {
    functions.value = []
    loadError.value = null
    loading.value = false
    return
  }
  loading.value = true
  loadError.value = null
  functions.value = []
  try {
    const connection = connections.value.find(item => item.id === connectionId)
    if (connection) await waitForFunctionPolicyWrites(connection.tool_id)
    if (disposed || requestId !== functionRequestId || selectedConnectionId.value !== connectionId) return
    const { data } = await connectionService.getConnectionFunctions(connectionId)
    if (disposed || requestId !== functionRequestId || selectedConnectionId.value !== connectionId) return
    functions.value = data.functions
    if (!data.success) loadError.value = data.message
  } catch (error) {
    if (disposed || requestId !== functionRequestId || selectedConnectionId.value !== connectionId) return
    console.error('Error loading functions:', error)
    loadError.value = t('connection.auth.loadError')
    functions.value = []
  } finally {
    if (requestId === functionRequestId) loading.value = false
  }
}

function resetConnectionFilters(): void {
  filterAgent.value = null
  filterTool.value = null
}

function resetFunctionFilters(): void {
  search.value = ''
  filterState.value = 'all'
}

function applyResolved(row: ConnectionFunctionInfo, resolved: FunctionStateResolved): void {
  row.connection_state = resolved.connection_state
  row.global_state = resolved.global_state
  row.effective = resolved.effective
  row.effective_state = resolved.effective_state
  row.default_state = resolved.default_state
  row.state_source = resolved.state_source
}

function applyPendingPolicies(row: ConnectionFunctionInfo): void {
  const save = policySaves.get(row)
  if (!save) return
  applyResolved(row, save.confirmed)
  for (const change of save.pending) {
    if (change.scope === 'global') {
      row.global_state = change.state
      row.connection_state = 'default'
      row.state_source = 'tool'
    } else {
      row.connection_state = change.state
      row.state_source = 'connection'
    }
  }
  row.effective_state = row.connection_state === 'default' ? globalPolicyState(row) : row.connection_state
  row.effective = row.effective_state !== 'disabled'
}

// Update the selection immediately and serialize its durable effects. A response
// rebases the remaining choices so it never replaces a more recent click.
async function changePolicy(row: ConnectionFunctionInfo, change: FunctionPolicyChange): Promise<void> {
  if (!canEdit.value || (change.scope === 'global' && !canManageAllAgents.value)) return
  if (!functions.value.includes(row)) return
  const connection = connections.value.find(item => item.id === selectedConnectionId.value)
  if (!connection) return
  let save = policySaves.get(row)
  if (!save) {
    save = { confirmed: { ...row }, pending: [] }
    policySaves.set(row, save)
  }
  save.pending.push(change)
  savingRows.value.add(row)
  applyPendingPolicies(row)
  const isVisible = () => !disposed && selectedConnectionId.value === connection.id && functions.value.includes(row)
  try {
    const { data } = await saveFunctionPolicy(connection, row, change)
    save.confirmed = data
    save.pending.shift()
    if (isVisible()) {
      applyPendingPolicies(row)
      if (save.pending.length === 0) {
        $q.notify({ type: 'positive', message: change.scope === 'global'
          ? t('connection.auth.globalExceptions', { count: data.local_override_count ?? 0 })
          : t('connection.auth.updated') })
      }
    }
  } catch (error) {
    save.pending.shift()
    console.error('Error updating function policy:', error)
    if (!disposed) $q.notify({ type: 'negative', message: t('connection.auth.updateError') })
    if (isVisible()) {
      applyPendingPolicies(row)
      // A failed transport can hide a committed write. Reconcile once the last
      // queued choice has finished, without interrupting newer pending choices.
      if (save.pending.length === 0) void loadFunctions()
    }
  } finally {
    if (save.pending.length === 0) {
      policySaves.delete(row)
      savingRows.value.delete(row)
    }
  }
}

function onConnectionState(row: ConnectionFunctionInfo, state: EffectiveFunctionState): void {
  void changePolicy(row, { scope: 'connection', state })
}

function onGlobalState(row: ConnectionFunctionInfo, state: EffectiveFunctionState): void {
  void changePolicy(row, { scope: 'global', state })
}

onUnmounted(() => {
  disposed = true
  ++functionRequestId
  ++connectionRequestId
})

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
  if (filterAgent.value !== null) sessionStorage.setItem(SESSION_FILTER_AGENT_KEY, String(filterAgent.value))
  else sessionStorage.removeItem(SESSION_FILTER_AGENT_KEY)
  if (filterTool.value !== null) sessionStorage.setItem(SESSION_FILTER_TOOL_KEY, String(filterTool.value))
  else sessionStorage.removeItem(SESSION_FILTER_TOOL_KEY)
  sessionStorage.setItem(SESSION_FILTER_STATE_KEY, filterState.value)
}

watch(selectedConnectionId, () => {
  void loadFunctions()
}, { flush: 'sync' })

// Clear the selection when it no longer belongs to the filtered options.
watch([filterAgent, filterTool, filterState], () => {
  saveFiltersToSession()
})

watch(connectionOptions, options => {
  if (
    selectedConnectionId.value !== null &&
    !options.some(o => o.value === selectedConnectionId.value)
  ) {
    selectedConnectionId.value = null
  }
  if (selectedConnectionId.value === null && options.length === 1) {
    selectedConnectionId.value = options[0]?.value ?? null
  }
})

onMounted(async () => {
  loadFiltersFromSession()
  await Promise.all([
    loadConnections(),
    agentStore.fetchAgents(),
    toolStore.fetchTools(),
  ])
  if (
    filterAgent.value !== null
    && !agentStore.agents.some(agent => agent.id === filterAgent.value)
  ) {
    filterAgent.value = null
  }
  if (
    filterTool.value !== null
    && !toolStore.tools.some(tool => tool.id === filterTool.value)
  ) {
    filterTool.value = null
  }
  saveFiltersToSession()
  initialized = true
})

onActivated(() => {
  if (initialized) void loadConnections()
})
</script>

<style scoped>
.section-label {
  display: inline-flex;
  align-items: center;
  min-width: 110px;
}

.authorization-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.authorization-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px;
}

.authorization-mobile-card,
.authorization-mobile-heading {
  min-width: 0;
}

.authorization-function-name,
.authorization-description {
  overflow-wrap: anywhere;
}

.authorization-mobile-settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

/* Wrap long descriptions and prevent horizontal table overflow. */
:deep(.q-table) {
  table-layout: fixed;
  width: 100%;
}

:deep(.q-table th),
:deep(.q-table td) {
  white-space: normal;
  word-break: break-word;
}

@media (max-width: 1023px) {
  .authorization-function-toolbar {
    align-items: stretch;
    gap: 8px;
  }

  .authorization-search,
  .authorization-function-toolbar > .q-btn-group {
    width: 100%;
    min-width: 0 !important;
  }
}

@media (max-width: 599px) {
  .authorization-mobile-settings {
    grid-template-columns: 1fr;
  }
}
</style>
