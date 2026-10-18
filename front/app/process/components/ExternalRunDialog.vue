<template>
  <q-dialog v-model="runDetailDialog" :maximized="$q.screen.lt.md">
    <q-card class="process-run-detail-dialog galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="account_tree" size="sm" />
        <div class="text-subtitle1 text-weight-medium ellipsis q-ml-sm">{{ t('processes.details') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('processes.close')" />
      </q-card-section>
      <q-separator />
      <div class="galaris-dialog-body galaris-dialog-body--layout">
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
      </div>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { defineAsyncView, showConfirmationDialog } from '@/core/util'
import { useProcessRunActions } from '../composables/useProcessRunActions'
import { useProcessStore } from '../stores/processStore'
import { websocket } from '@/core/websocket'
const ProcessRunDetailContent = defineAsyncView(() => import('./ProcessRunDetailContent.vue'))
const { runId } = defineProps<{ runId: string }>()
const emit = defineEmits<{ close: [] }>()
const store = useProcessStore()
const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canAdmin = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN))
const canLaunch = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_LAUNCH))
const canOperateRuns = computed(() => canLaunch.value || canAdmin.value)
const canAnalyze = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_READ) || canAdmin.value)
const canReadTasks = computed(() => (
  privilegeStore.hasPrivilege(privileges.TASK_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TASK_EDIT)
))
const { runDetailDialog, runDetailLoading, openRun, removeRun, reloadCurrent, refreshCurrent, cancelCurrent, retryCurrent, analyzeCurrent } = useProcessRunActions({
  store,
  canAdmin: () => canAdmin.value,
  canOperate: () => canOperateRuns.value,
  canAnalyze: () => canAnalyze.value,
  notify, errorDetail, translate: key => t(key),
  confirmRemoval: proceed => {
    showConfirmationDialog({ title: t('common.confirm'), message: t('processes.confirmDeleteRun'), cancel: true }).onOk(proceed)
  },
})

function errorDetail(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return t('processes.genericError')
}
function notify(type: 'positive' | 'negative', message: string): void { $q.notify({ type, message }) }
async function copyRunId(id: string): Promise<void> { await copyToClipboard(id); notify('positive', t('processes.copied')) }

watch(() => runId, id => { void openRun({ id }) }, { immediate: true })
watch(runDetailDialog, open => { if (!open) emit('close') })

let eventTimer: ReturnType<typeof setTimeout> | undefined
function runChanged(payload: unknown): void {
  if (!payload || typeof payload !== 'object' || !('data' in payload)) return
  const data = payload.data
  if (!data || typeof data !== 'object' || !('id' in data) || data.id !== runId || eventTimer !== undefined) return
  eventTimer = setTimeout(() => { eventTimer = undefined; void reloadCurrent() }, 100)
}
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('process_run', 'update', runChanged)
  websocket.onEvent('process_run', 'delete', runChanged)
  websocket.onConnect(reloadCurrent)
})
onBeforeUnmount(() => {
  clearTimeout(eventTimer)
  websocket.offEvent('process_run', 'update', runChanged)
  websocket.offEvent('process_run', 'delete', runChanged)
  websocket.offConnect(reloadCurrent)
})
</script>
<style scoped>
.process-run-detail-dialog { display: flex; flex-direction: column; width: 1100px; max-width: 96vw; height: 90vh; max-height: 900px; }
.process-run-detail-content { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
@media (max-width: 1023px) { .process-run-detail-dialog { width: 100%; max-width: none; height: 100%; max-height: none; } }
</style>
