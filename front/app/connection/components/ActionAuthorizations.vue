<template>
  <div>
    <div class="row items-center q-mb-sm">
      <h2 class="text-h6 q-my-none">{{ t('permissions.oneAction') }}</h2>
      <q-space /><q-btn flat icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="load" />
    </div>
    <q-select v-model="statusFilter" :options="statusOptions" emit-value map-options clearable
      :label="t('permissions.requestStatus')" class="q-mb-sm" />
    <q-banner v-if="error" role="alert">{{ t('permissions.error') }}
      <template #action><q-btn flat :label="t('permissions.retry')" @click="load" /></template>
    </q-banner>
    <q-table :rows="rows" :columns="columns" row-key="id" v-model:pagination="pagination"
      :grid="$q.screen.lt.md" :loading="loading" wrap-cells
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('permissions.actionEmpty')" @request="requestPage">
      <template #body-cell-status="props"><q-td :props="props">{{ t(`permissions.actionStatus.${props.row.status}`) }}</q-td></template>
      <template #body-cell-actions="props"><q-td :props="props">
        <q-btn flat icon="visibility" :aria-label="t('permissions.inspect')" @click="open(props.row.id)" />
      </q-td></template>
      <template #item="props"><div class="col-12 q-pa-xs"><q-card flat bordered>
        <q-card-section>{{ props.row.preview }}<div>{{ t(`permissions.actionStatus.${props.row.status}`) }}</div></q-card-section>
        <q-card-actions><q-btn flat :label="t('permissions.inspect')" @click="open(props.row.id)" /></q-card-actions>
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
          <div>{{ selected.preview }}</div>
          <div>{{ t(`permissions.actionStatus.${selected.status}`) }}</div>
          <div>{{ t('permissions.expiresAt') }}: {{ selected.expires_at }}</div>
          <p v-if="selected.notification_failed" role="status">{{ t('permissions.notificationFailed') }}</p>
          <div>{{ selected.decision_source === 'agent_yolo' ? t('permissions.automaticYolo') : t('permissions.approver') + ': ' + selected.approver_user_id }}</div>
          <pre v-if="selected.arguments" class="action-arguments">{{ JSON.stringify(selected.arguments, null, 2) }}</pre>
          <p v-if="selected.can_remember">{{ t('permissions.functionScope', { function: selected.capability_name }) }}</p>
        </q-card-section>
        <q-card-section v-if="detailError" role="alert">{{ t('permissions.error') }}
          <q-btn v-if="detailId" flat :label="t('permissions.retry')" @click="open(detailId)" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('permissions.cancel')" />
          <q-btn v-if="selected?.can_cancel && canAnswer" :label="t('permissions.cancelAction')"
            :loading="answering" @click="cancel" />
          <template v-if="selected?.can_answer && canAnswer">
            <q-btn :label="t('permissions.denyAction')" :loading="answering" @click="answer(false)" />
            <q-btn :label="t('permissions.allowAction')" :loading="answering" @click="answer(true)" />
            <q-btn v-if="selected.can_remember" :label="t('permissions.allowFunction')" :loading="answering" @click="answer(true, true)" />
          </template>
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
import { answerActionAuthorization, cancelActionAuthorization, getActionAuthorization, listActionAuthorizations, type ActionAuthorization } from '../services/permissionService'
const { agentId = null } = defineProps<{ agentId?: number | null }>()
const { t } = useI18n()
const route = useRoute()
const privilegeStore = usePrivilegeStore()
const canAnswer = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))
const rows = ref<ActionAuthorization[]>([])
const selected = ref<ActionAuthorization | null>(null)
const detailId = ref<string | null>(null)
const statusFilter = ref<ActionAuthorization['status'] | null>(null)
const statusOptions = computed(() => ['pending', 'approved', 'denied', 'expired', 'invalidated', 'executing', 'completed', 'failed', 'outcome_unknown']
  .map(value => ({ value, label: t(`permissions.actionStatus.${value}`) })))
const loading = ref(false)
const detailLoading = ref(false)
const detailOpen = ref(false)
const error = ref(false)
const detailError = ref(false)
const answering = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = computed<QTableColumn[]>(() => [
  { name: 'preview', field: 'preview', label: t('permissions.question'), align: 'left' },
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
  try {
    const result = await listActionAuthorizations({ agent_id: agentId ?? undefined,
      status: statusFilter.value ?? undefined,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage }, listController.signal)
    if (current !== generation || disposed) return
    rows.value = result.items
    pagination.value.rowsNumber = result.total
  } catch { if (current === generation && !disposed) error.value = true }
  finally { if (current === generation && !disposed) loading.value = false }
}
async function open(id: string) {
  if (disposed || !active) return
  detailId.value = id
  detailController?.abort()
  const controller = new AbortController()
  detailController = controller
  selected.value = null
  detailLoading.value = true
  detailOpen.value = true
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
    if (!disposed && detailOpen.value && selected.value?.id === id) await open(id)
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
    if (!disposed && detailOpen.value && selected.value?.id === id) await open(id)
    if (!disposed) await load()
  } catch { if (!disposed && selected.value?.id === id) detailError.value = true }
  finally { if (!disposed) answering.value = false }
}
const requestPage: NonNullable<QTableProps['onRequest']> = ({ pagination: next }) => {
  pagination.value.page = next.page
  pagination.value.rowsPerPage = next.rowsPerPage
  void load()
}
watch(() => agentId, () => { pagination.value.page = 1; selected.value = null; detailOpen.value = false; void load() })
watch(statusFilter, () => { pagination.value.page = 1; void load() })
watch(detailOpen, value => { if (!value) { detailController?.abort(); selected.value = null } })
watch(() => route.query.request, value => { if (typeof value === 'string') void open(value) })
onMounted(() => { void load(); if (typeof route.query.request === 'string') void open(route.query.request) })
onDeactivated(() => { active = false; generation++; detailOpen.value = false; listController?.abort(); detailController?.abort() })
onActivated(() => { if (!active) { active = true; void load(); if (typeof route.query.request === 'string') void open(route.query.request) } })
onBeforeUnmount(() => { disposed = true; generation++; listController?.abort(); detailController?.abort() })
</script>

<style scoped>
.action-arguments { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
