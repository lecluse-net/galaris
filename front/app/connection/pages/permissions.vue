<template>
  <q-page class="q-pa-md">
    <PageHeader icon="verified_user" :title="t('permissions.title')" :description="t('permissions.description')" />
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col">
        <q-select v-model="agentId" :options="agents" option-label="label" option-value="id"
          emit-value map-options clearable outlined dense :label="t('permissions.agent')" />
      </div>
      <div class="col-auto">
        <q-btn flat round icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="refresh" />
      </div>
    </div>
    <q-banner v-if="error || agentsError" class="q-mb-md" role="alert">
      {{ t('permissions.error') }}
      <template #action><q-btn outline :label="t('permissions.retry')" @click="initialize" /></template>
    </q-banner>
    <q-tabs v-model="tab" align="left" class="q-mb-md">
      <q-tab name="pending" :label="t('permissions.pendingApprovals')" />
      <q-tab name="granted" :label="t('permissions.permanentPermissions')" />
    </q-tabs>
    <ActionAuthorizations v-if="tab === 'pending'" :key="permissionsVersion" :agent-id="agentId" :agents="agents" class="q-mb-lg" @answered="load" />
    <template v-else>
      <RuntimePermissions :key="`functions-${permissionsVersion}`" kind="connection" :agent-id="agentId" :agents="agents" />
      <RuntimePermissions :key="`runtime-${permissionsVersion}`" :agent-id="agentId" :agents="agents" />
    </template>
    <h2 class="text-h6">{{ t(tab === 'pending' ? 'permissions.pendingNetwork' : 'permissions.networkPermissions') }}</h2>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id"
      :grid="$q.screen.lt.md"
      :loading="loading" :rows-per-page-options="[10, 20, 50, 100, 500]"
      :no-data-label="t('permissions.empty')" wrap-cells @request="requestPage">
      <template #body-cell-allowed="props">
        <q-td :props="props">{{ decisionLabel(props.row.allowed) }}</q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <template v-if="tab === 'pending' && canDelete && props.row.can_answer">
            <q-btn v-for="option in props.row.options" :key="option.id" outline :label="option.label"
              :loading="answering === props.row.id" :disable="answering !== null" @click="answer(props.row.id, option.id)" class="q-ma-xs" />
          </template>
          <q-btn v-else-if="tab === 'granted' && canDelete" flat color="negative" icon="delete" :aria-label="t('permissions.delete')" @click="selected = props.row" />
        </q-td>
      </template>
      <template #item="props"><div class="col-12 q-pa-xs"><q-card flat bordered>
        <q-card-section>{{ props.row.question }}<div>{{ agentLabel(props.row.agent_id) }}</div></q-card-section>
        <q-card-actions v-if="canDelete">
          <template v-if="tab === 'pending' && props.row.can_answer">
            <q-btn v-for="option in props.row.options" :key="option.id" outline :label="option.label"
              :loading="answering === props.row.id" :disable="answering !== null" @click="answer(props.row.id, option.id)" />
          </template>
          <q-btn v-else-if="tab === 'granted'" color="negative" :label="t('permissions.delete')" @click="selected = props.row" />
        </q-card-actions>
      </q-card></div></template>
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
          <q-btn v-close-popup outline :label="t('permissions.cancel')" />
          <q-btn color="negative" :label="t('permissions.delete')" :loading="deleting" @click="remove" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import { PageHeader } from '@/core/util'
import { usePrivilegeStore, privileges } from '@/core/authorize'
import { getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { answerPermission, listPermissions, deletePermission, type RememberedPermission } from '../services/permissionService'
import ActionAuthorizations from '../components/ActionAuthorizations.vue'
import RuntimePermissions from '../components/RuntimePermissions.vue'

const { t } = useI18n()
const authorize = usePrivilegeStore()
const canDelete = computed(() => authorize.hasPrivilege(privileges.CONNECTION_EDIT))
const agents = ref<AgentSelectionOption[]>([])
const agentId = ref<number | null>(null)
const permissionsVersion = ref(0)
const tab = ref<'pending' | 'granted'>('pending')
const answering = ref<string | null>(null)
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
const agentLabel = (id: number) => agents.value.find(agent => agent.id === id)?.label ?? String(id)
const columns = computed<QTableColumn[]>(() => [
  { name: 'agent_id', field: 'agent_id', label: t('permissions.agent'), align: 'left', format: agentLabel },
  { name: 'question', field: 'question', label: t('permissions.question'), align: 'left' },
  { name: 'permission_key', field: 'permission_key', label: t('permissions.key'), align: 'left' },
  { name: 'allowed', field: 'allowed', label: t('permissions.decision'), align: 'left' },
  { name: 'date', field: tab.value === 'pending' ? 'created_at' : 'answered_at', label: t(tab.value === 'pending' ? 'mailJournal.requestedAt' : 'permissions.date'), align: 'left', format: value => value ? new Date(value).toLocaleString() : '—' },
  { name: 'approver_label', field: 'approver_label', label: t('permissions.approver'), align: 'left' },
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
    const result = await listPermissions({ agent_id: agentId.value ?? undefined,
      ...(tab.value === 'pending' ? { pending: true } : { allowed: true }),
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, controller.signal)
    if (current !== generation) return
    rows.value = result.items
    pagination.value.rowsNumber = result.total
  } catch {
    if (current === generation) { error.value = true; rows.value = [] }
  } finally { if (current === generation) loading.value = false }
}
function refresh() {
  permissionsVersion.value++
  void load()
}
async function answer(id: string, optionId: string) {
  if (answering.value) return
  answering.value = id
  error.value = false
  try {
    await answerPermission(id, optionId)
    await load()
  } catch { if (!disposed) error.value = true }
  finally { if (!disposed) answering.value = null }
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
watch([agentId, tab], () => { pagination.value.page = 1; rows.value = []; void load() })
watch(selected, () => { deleteError.value = false })
async function initialize() {
  agentsError.value = false
  try { agents.value = await getAgentSelection('management') } catch { agentsError.value = true }
  await load()
}
onMounted(initialize)
onDeactivated(() => { active = false; generation++; controller?.abort() })
onActivated(() => { if (!active) { active = true; refresh() } })
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort() })
</script>
