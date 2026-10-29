<template>
  <div>
    <div v-if="!embedded" class="row items-center q-mb-sm">
      <h2 class="text-h6 q-my-none">{{ t('permissions.pendingApprovals') }}</h2>
      <q-space /><q-btn flat color="primary" icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="load" />
    </div>
    <q-banner v-if="error" role="alert">{{ t('permissions.error') }}
      <template #action><q-btn outline color="primary" :label="t('permissions.retry')" @click="load" /></template>
    </q-banner>
    <q-table :rows="rows" :columns="columns" row-key="id" v-model:pagination="pagination"
      :grid="$q.screen.lt.md" :loading="loading" wrap-cells
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('permissions.actionEmpty')" @request="requestPage">
      <template #body-cell-status="props"><q-td :props="props"><PermissionStateBadge state="pending" :label="t(`permissions.actionStatus.${props.row.status}`)" /></q-td></template>
      <template #body-cell-actions="props"><q-td :props="props">
        <q-btn flat color="primary" icon="visibility" :aria-label="t('permissions.inspect')" @click="open(props.row.id)"><q-tooltip>{{ t('permissions.inspect') }}</q-tooltip></q-btn>
      </q-td></template>
      <template #item="props"><div class="col-12 q-pa-xs"><q-card flat bordered>
        <q-card-section>{{ displayPreview(props.row) }}
          <div>{{ t('permissions.agent') }}: {{ agentLabel(props.row.agent_id) }}</div>
          <PermissionStateBadge state="pending" :label="t(`permissions.actionStatus.${props.row.status}`)" />
        </q-card-section>
        <q-card-actions><q-btn flat color="primary" icon="visibility" :aria-label="t('permissions.inspect')" @click="open(props.row.id)"><q-tooltip>{{ t('permissions.inspect') }}</q-tooltip></q-btn></q-card-actions>
      </q-card></div></template>
    </q-table>
    <q-dialog v-model="detailOpen">
      <q-card style="width: 660px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('permissions.oneAction') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('permissions.cancel')" />
        </q-card-section>
        <q-card-section v-if="detailLoading"><q-spinner :aria-label="t('permissions.loading')" /></q-card-section>
        <q-card-section v-if="selected">
          <h3 class="text-h6 q-mt-none q-mb-md">{{ selected.presentation?.title ?? selected.preview }}</h3>
          <dl v-if="selected.presentation" class="action-fields">
            <template v-for="(field, index) in selected.presentation.fields" :key="index">
              <dt class="text-weight-medium">{{ field.label }}</dt>
              <dd>{{ field.value }}</dd>
            </template>
          </dl>
          <div>{{ t(`permissions.actionStatus.${selected.status}`) }}</div>
          <div>{{ t('permissions.expiresAt') }}: {{ selected.expires_at }}</div>
          <p v-if="selected.notification_failed" role="status">{{ t('permissions.notificationFailed') }}</p>
          <q-expansion-item :label="t('permissions.technicalDetails')" dense class="q-mt-md">
            <div class="q-pa-sm">
              <div>{{ selected.capability_name }}</div>
              <div class="action-arguments">{{ selected.preview }}</div>
              <div>{{ t('permissions.approver') }}: {{ selected.approver_user_id }}</div>
              <pre v-if="selected.arguments" class="action-arguments">{{ JSON.stringify(selected.arguments, null, 2) }}</pre>
            </div>
          </q-expansion-item>
          <p v-if="selected.can_remember">{{ t(selected.source === 'runtime' ? 'permissions.runtimeScope' : 'permissions.functionScope', { function: selected.capability_name, runtime: selected.runtime }) }}</p>
          <PermissionToggle v-if="decisionControl" :control="decisionControl" :disabled="answering" class="q-mt-md"
            @change="value => decisionControl?.save(value)" />
        </q-card-section>
        <q-card-section v-if="detailError" role="alert">{{ t('permissions.error') }}
          <q-btn v-if="detailId" outline color="primary" :label="t('permissions.retry')" @click="open(detailId)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('permissions.cancel')" />
          <q-btn v-if="selected?.can_cancel && canCancel" color="primary" :label="t('permissions.cancelAction')"
            :loading="answering" @click="cancel" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onDeactivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { AgentSelectionOption } from '@/app/agent'
import { answerActionAuthorization, cancelActionAuthorization, getActionAuthorization, listActionAuthorizations, type ActionAuthorization } from '../services/permissionService'
import type { PermissionCounts, PermissionState } from '../services/permissionDashboard'
import type { PermissionControl } from '../services/permissionDashboard'
import PermissionToggle from './PermissionToggle.vue'
import PermissionStateBadge from './PermissionStateBadge.vue'
const { agentId = null, agents = [], search = '', state = 'all', revision = 0, embedded = false, customizedOnly = false } = defineProps<{
  agentId?: number | null; agents?: AgentSelectionOption[]; search?: string; state?: PermissionState; revision?: number; embedded?: boolean; customizedOnly?: boolean
}>()
const agentLabel = (id: number) => agents.find(agent => agent.id === id)?.label ?? String(id)
const emit = defineEmits<{ answered: []; counts: [counts: PermissionCounts] }>()
const { t } = useI18n()
const route = useRoute()
const privilegeStore = usePrivilegeStore()
const canAnswer = computed(() => privilegeStore.hasPrivilege(privileges.PERMISSION_DECIDE))
const canCancel = computed(() => privilegeStore.hasPrivilege(privileges.PERMISSION_REVOKE))
const rows = ref<ActionAuthorization[]>([])
const selected = ref<ActionAuthorization | null>(null)
const detailId = ref<string | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const detailOpen = ref(false)
const error = ref(false)
const detailError = ref(false)
const answering = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const decisionControl = computed<PermissionControl | null>(() => {
  const row = selected.value
  if (!row) return null
  const allowed = ['approved', 'executing', 'completed'].includes(row.status)
  const value = row.status === 'pending' ? 'pending' : row.status === 'denied' || allowed
    ? `${allowed ? 'allow' : 'deny'}${row.remembered ? '_always' : ''}` : row.status
  return { id: 'decision', label: t('permissions.oneAction'), value,
    disabled: !row.can_answer || !canAnswer.value,
    options: [{ value: 'pending', label: t('permissions.actionStatus.pending'), disable: true },
      { value: 'allow', label: t('permissions.allowAction') }, { value: 'deny', label: t('permissions.denyAction') },
      ...(row.can_remember || row.remembered ? [
        { value: 'allow_always', label: t(row.source === 'runtime' ? 'permissions.allowRuntimeAction' : 'permissions.allowFunction') },
        { value: 'deny_always', label: t(row.source === 'runtime' ? 'permissions.denyRuntimeAction' : 'permissions.denyFunction') },
      ] : []),
      ...(!['pending', 'allow', 'deny', 'allow_always', 'deny_always'].includes(value)
        ? [{ value, label: t(`permissions.actionStatus.${row.status}`) }] : []),
    ],
    save: async next => {
      if (next !== value && row.can_answer && canAnswer.value && ['allow', 'deny', 'allow_always', 'deny_always'].includes(next)) {
        await answer(next.startsWith('allow'), next.endsWith('_always'))
      }
    } }
})
const displayPreview = (row: ActionAuthorization) => row.source === 'domain' && ['mail_send', 'mail_reply', 'mail_forward'].includes(row.capability_name)
  ? t('permissions.sendMail') : row.preview.split('\n')[0]
const columns = computed<QTableColumn[]>(() => [
  { name: 'agent', field: 'agent_id', label: t('permissions.agent'), align: 'left', format: agentLabel },
  { name: 'preview', field: displayPreview, label: t('permissions.question'), align: 'left' },
  { name: 'status', field: 'status', label: t('permissions.decision'), align: 'left' },
  { name: 'actions', field: 'id', label: t('permissions.actions'), align: 'right' },
])
let listController: AbortController | undefined
let detailController: AbortController | undefined
let generation = 0
let disposed = false
let active = true
async function load() {
  if (disposed || !active) return
  listController?.abort()
  listController = new AbortController()
  const current = ++generation
  loading.value = true
  error.value = false
  if (customizedOnly) {
    rows.value = []; pagination.value.rowsNumber = 0; emit('counts', {}); loading.value = false
    return
  }
  try {
    const result = await listActionAuthorizations({ agent_id: agentId ?? undefined,
      status: 'pending', q: search,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, listController.signal)
    if (current !== generation || disposed) return
    rows.value = state === 'all' || state === 'pending' ? result.items : []
    pagination.value.rowsNumber = state === 'all' || state === 'pending' ? result.total : 0
    emit('counts', { pending: result.total })
  } catch { if (current === generation && !disposed) error.value = true }
  finally { if (current === generation && !disposed) loading.value = false }
}
async function open(id: string, reveal = true) {
  if (disposed || !active || (!reveal && !detailOpen.value)) return
  detailId.value = id
  detailController?.abort()
  const controller = new AbortController()
  detailController = controller
  selected.value = null
  detailLoading.value = true
  if (reveal) detailOpen.value = true
  detailError.value = false
  try {
    const result = await getActionAuthorization(id, controller.signal)
    if (!controller.signal.aborted && !disposed) selected.value = result
  } catch { if (!controller.signal.aborted && !disposed) detailError.value = true }
  finally { if (!controller.signal.aborted && !disposed) detailLoading.value = false }
}
async function answer(approved: boolean, remember = false) {
  const id = selected.value?.id
  if (!id || answering.value) return
  answering.value = true
  try {
    await answerActionAuthorization(id, approved, remember)
    emit('answered')
    if (!disposed && detailOpen.value && selected.value?.id === id) await open(id, false)
    await load()
  } catch { if (selected.value?.id === id) detailError.value = true }
  finally { answering.value = false }
}
async function cancel() {
  const id = selected.value?.id
  if (!id || answering.value) return
  answering.value = true
  try {
    await cancelActionAuthorization(id)
    if (!disposed && detailOpen.value && selected.value?.id === id) await open(id, false)
    if (!disposed) await load()
  } catch { if (!disposed && selected.value?.id === id) detailError.value = true }
  finally { if (!disposed) answering.value = false }
}
const requestPage: NonNullable<QTableProps['onRequest']> = ({ pagination: next }) => {
  pagination.value.page = next.page
  pagination.value.rowsPerPage = next.rowsPerPage
  void load()
}
watch(() => [agentId, search, state, customizedOnly], () => { pagination.value.page = 1; rows.value = []; selected.value = null; detailOpen.value = false; void load() })
watch(() => revision, () => { void load() })
watch(detailOpen, value => { if (!value) { detailController?.abort(); selected.value = null } })
watch(() => route.query.request, value => { if (typeof value === 'string') void open(value) })
onMounted(() => { void load(); if (typeof route.query.request === 'string') void open(route.query.request) })
onDeactivated(() => { active = false; generation++; detailOpen.value = false; listController?.abort(); detailController?.abort() })
onActivated(() => { if (!active) { active = true; void load(); if (typeof route.query.request === 'string') void open(route.query.request) } })
onBeforeUnmount(() => { disposed = true; generation++; listController?.abort(); detailController?.abort() })
</script>

<style scoped>
.action-arguments { white-space: pre-wrap; overflow-wrap: anywhere; }
.action-fields dd { margin: 4px 0 20px; white-space: pre-wrap; overflow-wrap: anywhere; }
.action-fields dt { overflow-wrap: anywhere; }
</style>
