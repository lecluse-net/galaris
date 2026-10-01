<template>
  <q-page class="q-pa-md">
    <PageHeader icon="verified_user" :title="t('permissions.title')" :description="t('permissions.description')" />
    <ActionAuthorizations :agent-id="agentId" class="q-mb-lg" />
    <h2 class="text-h6">{{ t('permissions.remembered') }}</h2>
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-6">
        <q-select v-model="agentId" :options="agents" option-label="label" option-value="id"
          emit-value map-options clearable outlined dense :label="t('permissions.agent')" />
      </div>
      <div class="col-12 col-md-5">
        <q-select v-model="decision" :options="decisionOptions" emit-value map-options clearable
          outlined dense :label="t('permissions.decision')" />
      </div>
      <div class="col-12 col-md-1">
        <q-btn flat round icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="load" />
      </div>
    </div>
    <q-banner v-if="error || agentsError" class="q-mb-md" role="alert">
      {{ t('permissions.error') }}
      <template #action><q-btn flat :label="t('permissions.retry')" @click="initialize" /></template>
    </q-banner>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id"
      :loading="loading" :rows-per-page-options="[10, 20, 50, 100, 500]"
      :no-data-label="t('permissions.empty')" wrap-cells @request="requestPage">
      <template #body-cell-allowed="props">
        <q-td :props="props">{{ decisionLabel(props.row.allowed) }}</q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn v-if="canDelete" flat icon="delete" :aria-label="t('permissions.delete')" @click="selected = props.row" />
        </q-td>
      </template>
    </q-table>
    <q-dialog v-model="confirmOpen">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('permissions.delete') }}</div>
          <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('permissions.cancel')" />
        </q-card-section>
        <q-card-section>{{ selected?.question }}</q-card-section>
        <q-card-section>{{ t('permissions.deleteExplanation') }}</q-card-section>
        <q-card-section v-if="deleteError" role="alert">{{ t('permissions.error') }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('permissions.cancel')" />
          <q-btn :label="t('permissions.delete')" :loading="deleting" @click="remove" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import { PageHeader } from '@/core/util'
import { usePrivilegeStore, privileges } from '@/core/authorize'
import { getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { listPermissions, deletePermission, type RememberedPermission } from '../services/permissionService'
import ActionAuthorizations from '../components/ActionAuthorizations.vue'

const { t } = useI18n()
const authorize = usePrivilegeStore()
const canDelete = computed(() => authorize.hasPrivilege(privileges.CONNECTION_EDIT))
const agents = ref<AgentSelectionOption[]>([])
const agentId = ref<number | null>(null)
const decision = ref<boolean | null>(null)
const rows = ref<RememberedPermission[]>([])
const loading = ref(false)
const error = ref(false)
const agentsError = ref(false)
const deleting = ref(false)
const deleteError = ref(false)
const selected = ref<RememberedPermission | null>(null)
const confirmOpen = computed({ get: () => selected.value !== null, set: value => { if (!value) selected.value = null } })
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'created_at', descending: true })
const decisionLabel = (value: boolean | null) => t(value === null ? 'permissions.pending' : value ? 'permissions.allowed' : 'permissions.denied')
const decisionOptions = computed(() => [true, false].map(value => ({ value, label: decisionLabel(value) })))
const columns = computed<QTableColumn[]>(() => [
  { name: 'agent_id', field: 'agent_id', label: t('permissions.agent'), align: 'left', format: value => agents.value.find(agent => agent.id === value)?.label ?? String(value) },
  { name: 'question', field: 'question', label: t('permissions.question'), align: 'left' },
  { name: 'permission_key', field: 'permission_key', label: t('permissions.key'), align: 'left' },
  { name: 'allowed', field: 'allowed', label: t('permissions.decision'), align: 'left' },
  { name: 'answered_at', field: 'answered_at', label: t('permissions.date'), align: 'left', format: value => value ? new Date(value).toLocaleString() : '—' },
  { name: 'approver_label', field: 'approver_label', label: t('permissions.approver'), align: 'left' },
  { name: 'actions', field: 'id', label: t('permissions.actions'), align: 'right' },
])
let controller: AbortController | undefined
let generation = 0
let disposed = false
async function load() {
  if (disposed) return
  controller?.abort()
  controller = new AbortController()
  const current = ++generation
  loading.value = true
  error.value = false
  try {
    const result = await listPermissions({ agent_id: agentId.value ?? undefined, allowed: decision.value ?? undefined,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, controller.signal)
    if (current !== generation) return
    rows.value = result.items
    pagination.value.rowsNumber = result.total
  } catch {
    if (current === generation) { error.value = true; rows.value = [] }
  } finally { if (current === generation) loading.value = false }
}
const requestPage: NonNullable<QTableProps['onRequest']> = ({ pagination: next }) => {
  pagination.value.page = next.page
  pagination.value.rowsPerPage = next.rowsPerPage
  void load()
}
async function remove() {
  if (!selected.value) return
  const id = selected.value.id
  deleting.value = true
  deleteError.value = false
  try {
    await deletePermission(id)
    if (selected.value?.id === id) selected.value = null
    pagination.value.page = 1
    await load()
  } catch { if (selected.value?.id === id) deleteError.value = true }
  finally { deleting.value = false }
}
watch([agentId, decision], () => { pagination.value.page = 1; void load() })
watch(selected, () => { deleteError.value = false })
async function initialize() {
  agentsError.value = false
  try { agents.value = await getAgentSelection('management') } catch { agentsError.value = true }
  await load()
}
onMounted(initialize)
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort() })
</script>
