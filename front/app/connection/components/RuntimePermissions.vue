<template>
  <div class="q-mb-lg">
    <div class="row items-center q-mb-sm">
      <h2 class="text-h6 q-my-none">{{ t(kind === 'connection' ? 'permissions.functionPermissions' : 'permissions.runtimePermissions') }}</h2>
      <q-space /><q-btn flat round icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="load" />
    </div>
    <q-banner v-if="error" role="alert">{{ t('permissions.error') }}
      <template #action><q-btn outline :label="t('permissions.retry')" @click="load" /></template>
    </q-banner>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id"
      :loading="loading" :grid="$q.screen.lt.md" wrap-cells
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('permissions.runtimePermissionEmpty')" @request="requestPage">
      <template #body-cell-active="props"><q-td :props="props">{{ statusLabel(props.row.active) }}</q-td></template>
      <template #body-cell-actions="props"><q-td :props="props">
        <q-btn v-if="canEdit && props.row.can_revoke" flat color="negative" icon="delete" :aria-label="t('permissions.revokeRuntimePermission')" @click="selected = props.row" />
      </q-td></template>
      <template #item="props"><div class="col-12 q-pa-xs"><q-card flat bordered>
        <q-card-section>{{ scopeLabel(props.row) }} · {{ props.row.capability_name }}
          <div>{{ t('permissions.agent') }}: {{ agentLabel(props.row.agent_id) }}</div>
          <div>{{ statusLabel(props.row.active) }}</div>
        </q-card-section>
        <q-card-actions><q-btn v-if="canEdit && props.row.can_revoke" color="negative" :label="t('permissions.revokeRuntimePermission')" @click="selected = props.row" /></q-card-actions>
      </q-card></div></template>
    </q-table>
    <q-dialog v-model="confirmOpen">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('permissions.revokeRuntimePermission') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('permissions.cancel')" />
        </q-card-section>
        <q-card-section>{{ selected && scopeLabel(selected) }} · {{ selected?.capability_name }}</q-card-section>
        <q-card-section>{{ t('permissions.runtimeRevokeExplanation') }}</q-card-section>
        <q-card-section v-if="revokeError" role="alert">{{ t('permissions.error') }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline :label="t('permissions.cancel')" />
          <q-btn color="negative" :label="t('permissions.revokeRuntimePermission')" :loading="revoking" @click="revoke" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { AgentSelectionOption } from '@/app/agent'
import { listFunctionPermissions, revokeFunctionPermission, listRuntimePermissions, revokeRuntimePermission, type FunctionPermission, type RuntimePermission } from '../services/permissionService'

const { agentId = null, kind = 'runtime', agents = [] } = defineProps<{ agentId?: number | null; kind?: 'runtime' | 'connection'; agents?: AgentSelectionOption[] }>()
const agentLabel = (id: number) => agents.find(agent => agent.id === id)?.label ?? String(id)
const { t } = useI18n()
const authorize = usePrivilegeStore()
const canEdit = computed(() => authorize.hasPrivilege(privileges.PERMISSION_REVOKE))
type PermanentPermission = RuntimePermission | FunctionPermission
const rows = ref<PermanentPermission[]>([])
const selected = ref<PermanentPermission | null>(null)
const scopeLabel = (row: PermanentPermission) => 'connection_id' in row ? row.tool_label : row.runtime
const loading = ref(false)
const error = ref(false)
const revoking = ref(false)
const revokeError = ref(false)
const confirmOpen = computed({ get: () => selected.value !== null, set: value => { if (!value) selected.value = null } })
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const statusLabel = (active: boolean) => t(active ? 'permissions.allowed' : 'permissions.runtimePermissionStale')
const columns = computed<QTableColumn[]>(() => [
  { name: 'agent_id', field: 'agent_id', label: t('permissions.agent'), align: 'left', format: agentLabel },
  { name: 'runtime', field: scopeLabel, label: t(kind === 'connection' ? 'connection.colTool' : 'permissions.runtime'), align: 'left' },
  { name: 'capability_name', field: 'capability_name', label: t('permissions.key'), align: 'left' },
  { name: 'active', field: 'active', label: t('permissions.decision'), align: 'left' },
  { name: 'actions', field: 'id', label: t('permissions.actions'), align: 'right' },
])
let controller: AbortController | undefined
let generation = 0
let disposed = false
let active = true
async function load() {
  if (disposed || !active) return
  controller?.abort()
  controller = new AbortController()
  const current = ++generation
  loading.value = true
  error.value = false
  try {
    const result = await (kind === 'connection' ? listFunctionPermissions : listRuntimePermissions)({ agent_id: agentId ?? undefined,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, controller.signal)
    if (current !== generation || disposed) return
    rows.value = result.items
    pagination.value.rowsNumber = result.total
  } catch { if (current === generation && !disposed) error.value = true }
  finally { if (current === generation && !disposed) loading.value = false }
}
async function revoke() {
  const id = selected.value?.id
  if (!id || revoking.value) return
  revoking.value = true
  revokeError.value = false
  try {
    if (selected.value && 'connection_id' in selected.value) await revokeFunctionPermission(selected.value)
    else await revokeRuntimePermission(id)
    if (selected.value?.id === id) selected.value = null
    if (!disposed) { pagination.value.page = 1; await load() }
  } catch { if (!disposed && selected.value?.id === id) revokeError.value = true }
  finally { if (!disposed) revoking.value = false }
}
const requestPage: NonNullable<QTableProps['onRequest']> = ({ pagination: next }) => {
  pagination.value.page = next.page
  pagination.value.rowsPerPage = next.rowsPerPage
  void load()
}
watch(() => agentId, () => { pagination.value.page = 1; selected.value = null; rows.value = []; void load() })
watch(selected, () => { revokeError.value = false })
onMounted(load)
onDeactivated(() => { active = false; generation++; selected.value = null; controller?.abort() })
onActivated(() => { if (!active) { active = true; void load() } })
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort() })
</script>
