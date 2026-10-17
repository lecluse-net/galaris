<template>
  <section class="native-run-panel q-gutter-y-md">
    <div v-if="!embedded" class="row items-center q-gutter-sm">
      <div class="text-h6">{{ t('nativeProcesses.run') }}</div><q-badge>{{ run ? t(`processes.statuses.${run.status}`, t('nativeProcesses.unknown')) : t('nativeProcesses.unknown') }}</q-badge>
      <q-badge v-if="run?.paused" outline>{{ t('nativeProcesses.paused') }}</q-badge>
      <q-btn flat round icon="refresh" :loading="loading" :aria-label="t('nativeProcesses.refresh')" @click="refresh" />
    </div>
    <q-btn v-if="run?.parent_run_id" outline icon="arrow_upward" :label="t('nativeProcesses.parent')" :to="`/process/internal/run/${run.parent_run_id}`" />
    <q-input v-if="!summaryInHeader" :model-value="runUrl" outlined dense readonly :label="t('nativeProcesses.runUrl')">
      <template #append><q-btn outline dense color="primary" icon="content_copy" :aria-label="t('nativeProcesses.copyRunUrl')" @click="copyRunUrl" /></template>
    </q-input>
    <q-badge v-else-if="!displayGraph" outline color="primary" class="native-run-id"><ProcessRunReference :id="runId" /></q-badge>
    <q-banner v-if="error || metricsError" role="alert">{{ error || metricsError }}<template #action><q-btn flat :label="t('nativeProcesses.retry')" @click="refresh" /></template></q-banner>
    <q-spinner v-if="loading && !run" />
    <template v-if="run">
      <q-card v-if="run.operational && (!summaryInHeader || run.paused || run.operational.blocker?.requires_reconciliation || run.operational.activities.length || run.operational.activities_truncated)" bordered flat>
        <q-card-section v-if="!summaryInHeader || run.paused">
          <div v-if="!summaryInHeader" class="row items-center q-gutter-sm"><div class="text-subtitle1">{{ t('nativeProcesses.followUp') }}</div>
            <q-badge>{{ t(`nativeProcesses.phases.${run.operational.phase}`, run.operational.phase) }}</q-badge></div>
          <div v-if="!summaryInHeader">{{ t('nativeProcesses.progressOccurrences', run.operational.progress) }}</div>
          <div v-if="!summaryInHeader" class="text-caption">{{ t('nativeProcesses.lastActivity', { date: formatDate(run.operational.last_activity_at) }) }}</div>
          <div v-if="run.paused" class="q-mt-sm">{{ t('nativeProcesses.pauseExplanation') }}</div>
        </q-card-section>
        <q-banner v-if="run.operational.blocker?.requires_reconciliation" role="alert">{{ t('nativeProcesses.reconciliationRequired') }}</q-banner>
        <q-list v-if="run.operational.activities.length" separator>
          <q-item v-for="activity in run.operational.activities" :key="activity.occurrence_id" clickable @click="inspectActivity(activity)">
            <q-item-section>
              <q-item-label>{{ activityTitle(activity) }}</q-item-label>
              <q-item-label caption>{{ t(`nativeProcesses.waitKinds.${activity.kind}`, activity.kind) }}</q-item-label>
              <div v-if="activity.question" class="q-mt-xs">{{ activity.question }}</div>
              <div v-for="(wait, index) in activity.task?.waits.filter(wait => wait.question)" :key="index" class="q-mt-xs">{{ wait.question }}</div>
              <div v-if="activity.task?.last_error" class="q-mt-xs">{{ t('nativeProcesses.lastTaskError', { error: activity.task.last_error }) }}</div>
            </q-item-section>
          </q-item>
        </q-list>
        <q-card-section v-if="run.operational.activities_truncated">{{ t('nativeProcesses.moreActivities') }}</q-card-section>
      </q-card>
      <div v-if="canControl && !terminal" class="row q-gutter-sm">
        <q-btn v-if="available('pause')" outline color="warning" icon="pause" :label="t('nativeProcesses.pause')" :disable="mutating" @click="command('pause')" />
        <q-btn v-if="available('resume')" color="positive" icon="play_arrow" :label="t('nativeProcesses.resume')" :disable="mutating" @click="command('resume')" />
        <q-btn v-if="available('step')" outline color="primary" icon="skip_next" :label="t('nativeProcesses.step')" :disable="mutating" @click="command('step')" />
        <q-btn v-if="available('cancel')" color="negative" icon="stop" :label="t('nativeProcesses.cancel')" :disable="mutating" @click="requestCancel" />
      </div>
      <q-breadcrumbs v-if="bodyPath.length"><q-breadcrumbs-el :label="t('nativeProcesses.root')" @click="bodyPath = []" />
        <q-breadcrumbs-el v-for="(key, index) in bodyPath" :key="key" :label="key" @click="bodyPath = bodyPath.slice(0, index + 1)" /></q-breadcrumbs>
      <BpmnCanvas v-if="displayGraph" ref="canvas" :key="bodyPath.join('/')" :model-value="displayGraph" readonly auto-fit
        :inspector-label="t('nativeProcesses.execution.details')" :selected="selectedNode" :statuses="statuses" :overlays="overlays"
        @select="selectNode" @dismiss="dismissInspection">
        <template v-if="summaryInHeader" #toolbar-leading>
          <q-badge outline color="primary" class="native-run-id"><ProcessRunReference :id="runId" /></q-badge>
        </template>
        <template #inspector>
          <NativeActivityDetails v-if="selectedNode" :title="selectedTitle" :detail="nodeDetail" :occurrences="activityPage"
            :selected-occurrence="selectedOccurrence" :page-size="activitySize" :loading="activityLoading || nodeLoading" :error="nodeError"
            @select="selectExecution" @page="requestActivityPage" @retry="retryInspection" @close="clearInspection">
            <q-btn v-if="selectedBody" outline icon="open_in_new" :label="t('nativeProcesses.openBody')" @click="bodyPath = [...bodyPath, selectedNode!]" />
            <q-checkbox v-if="canControl && !terminal" :model-value="run.breakpoints.includes(selectedNode)" :label="t('nativeProcesses.breakpoint')"
              :disable="mutating" @update:model-value="toggleBreakpoint" />
          </NativeActivityDetails>
        </template>
      </BpmnCanvas>
      <div v-if="!summaryInHeader" class="row q-gutter-sm">
        <q-chip>{{ t('nativeProcesses.duration') }}: {{ run.duration_seconds == null ? t('nativeProcesses.unknown') : `${run.duration_seconds.toFixed(1)} s` }}</q-chip>
        <q-chip>{{ t('nativeProcesses.directCost') }}: {{ cost(metrics?.direct.cost) }}</q-chip>
        <q-chip>{{ t('nativeProcesses.inclusiveCost') }}: {{ cost(metrics?.inclusive.cost) }}</q-chip>
        <q-chip>{{ t('nativeProcesses.inferenceCost') }}: {{ cost(metrics?.inclusive.inference_cost) }}</q-chip>
        <q-chip v-if="metrics?.partial" icon="info">{{ t('nativeProcesses.partial') }}</q-chip>
        <q-chip v-if="metrics?.inclusive.estimated_calls" icon="info">{{ t('nativeProcesses.estimated', { count: metrics.inclusive.estimated_calls }) }}</q-chip>
      </div>
      <div v-if="run.dataset_uri" class="row items-center q-gutter-sm"><span>{{ t('nativeProcesses.dataset') }}</span>
        <q-btn flat no-caps icon="description" :label="run.dataset_uri" :to="datasetLink" /></div>
      <q-banner v-if="run.error || run.error_code" role="alert"><strong v-if="run.error_code">{{ run.error_code }}</strong><div v-if="run.error">{{ run.error }}</div></q-banner>
      <q-expansion-item v-if="!summaryInHeader" :label="t('nativeProcesses.children')" icon="account_tree" @show="loadChildren">
        <q-list bordered><q-item v-for="child in childPage?.items" :key="child.id" clickable :to="child.engine_code === 'galaris' ? `/process/internal/run/${child.id}` : undefined">
          <q-item-section>{{ child.process_label }}<q-item-label caption>{{ child.id }} · {{ child.status }}</q-item-label></q-item-section></q-item>
          <q-item v-if="!childPage?.items.length"><q-item-section>{{ t('processes.noRows') }}</q-item-section></q-item>
        </q-list>
        <q-select v-model="childSize" :options="[10, 20, 50, 100, 500]" :label="t('nativeProcesses.children')" @update:model-value="childNumber = 1; loadChildren()" />
        <q-pagination v-if="childPage && childPage.total > childSize" v-model="childNumber" :max="Math.ceil(childPage.total / childSize)" @update:model-value="loadChildren" />
      </q-expansion-item>
      <q-table v-if="!summaryInHeader" :title="t('nativeProcesses.occurrences')" :rows="run.nodes" :columns="columns" row-key="id" :loading="loading"
        v-model:pagination="pagination" :rows-per-page-options="[10, 20, 50, 100, 500]" @request="requestPage" @row-click="selectOccurrence">
        <template #body-cell-cost="scope"><q-td :props="scope">{{ cost(metrics?.occurrences?.[scope.row.id]?.inclusive.cost) }}</q-td></template>
        <template #body-cell-inference="scope"><q-td :props="scope">{{ cost(metrics?.occurrences?.[scope.row.id]?.inclusive.inference_cost) }}</q-td></template>
      </q-table>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar'
import { richLinkHref, showConfirmationDialog } from '@/core/util'
import { usePrivilegeStore } from '@/core/authorize'
import { websocket } from '@/core/websocket'
import BpmnCanvas from './BpmnCanvas.vue'
import NativeActivityDetails from './NativeActivityDetails.vue'
import ProcessRunReference from './ProcessRunReference.vue'
import { nativeProcessService as service, type NativeRun, type NativeMetrics, type NativeChildren, type NodeOccurrence, type NodeExecutionDetail, type NodeOccurrencePage, type RunActivity } from '../services/nativeProcessService'
const props = defineProps<{ runId: string; embedded?: boolean; summaryInHeader?: boolean }>()
const emit = defineEmits<{ loaded: [run: NativeRun]; metricsLoaded: [metrics: NativeMetrics] }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const runUrl = computed(() => service.runUrl(props.runId))
const privileges = usePrivilegeStore()
const run = shallowRef<NativeRun | null>(null), metrics = ref<NativeMetrics | null>(null), childPage = ref<NativeChildren | null>(null)
const loading = ref(false), mutating = ref(false), error = ref(''), selectedNode = ref<string | null>(null), selectedOccurrence = ref<string | null>(null)
const metricsError = ref('')
const nodeDetail = shallowRef<NodeExecutionDetail | null>(null), childNumber = ref(1)
const activityPage = shallowRef<NodeOccurrencePage | null>(null), activitySize = ref(50)
const activityLoading = ref(false), activityPending = ref(false), nodeLoading = ref(false), nodeError = ref(false)
const canvas = useTemplateRef<InstanceType<typeof BpmnCanvas>>('canvas')
const childSize = ref(50), bodyPath = ref<string[]>([])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined, nodeGeneration = 0, activityGeneration = 0
let eventTimer: ReturnType<typeof setTimeout> | undefined, refreshPending = false, inspectionRefreshPending = false
let metricsLoading = false, metricsPending = false
const pendingCommands = new Map<string, { key: string; revision: number }>()
const canControl = computed(() => Boolean(run.value?.can_control) && (privileges.hasPrivilege('PROCESS_LAUNCH') || privileges.hasPrivilege('PROCESS_ADMIN')))
const terminal = computed(() => ['success', 'error', 'cancelled'].includes(run.value?.status ?? ''))
const datasetLink = computed(() => richLinkHref(run.value?.dataset_uri ?? '') ?? '')
const statuses = computed(() => Object.fromEntries(Object.entries(run.value?.node_statuses ?? {}).map(([key, value]) => [key, value === 'ready' ? 'queued' : value])))
const displayGraph = computed(() => { let graph = run.value?.graph; for (const key of bodyPath.value) { const body = graph?.nodes.find(node => node.id === key)?.body; if (!body) break; graph = body }; return graph })
const selectedBody = computed(() => displayGraph.value?.nodes.find(node => node.id === selectedNode.value)?.body)
const selectedTitle = computed(() => { const node = displayGraph.value?.nodes.find(node => node.id === selectedNode.value); return node?.title || (node ? t('nativeProcesses.kinds.' + node.kind) : '') })
const overlays = computed(() => Object.fromEntries((displayGraph.value?.nodes ?? [])
  .filter(node => node.kind !== 'start' && node.kind !== 'end' && statuses.value[node.id])
  .map(node => [node.id, `${metrics.value?.nodes[node.id]?.duration_seconds?.toFixed(1) ?? '…'} s · ${cost(metrics.value?.nodes[node.id]?.cost)}`])))
const columns = computed<QTableColumn[]>(() => [
  { name: 'node', label: t('nativeProcesses.nodeDetails'), field: 'node_key', align: 'left' },
  { name: 'status', label: t('processes.status'), field: 'status', align: 'left' },
  { name: 'started', label: t('processes.startedAt'), field: 'started_at', align: 'left' },
  { name: 'cost', label: t('nativeProcesses.inclusiveCost'), field: 'id', align: 'right' },
  { name: 'inference', label: t('nativeProcesses.inferenceCost'), field: 'id', align: 'right' },
])
function cost(value: number | null | undefined): string { return value == null ? t('nativeProcesses.unknown') : new Intl.NumberFormat(locale.value, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 6 }).format(value) }
function formatDate(value: string): string { return new Date(value).toLocaleString(locale.value) }
async function copyRunUrl(): Promise<void> {
  try { await copyToClipboard(runUrl.value); $q.notify({ type: 'positive', message: t('common.copied'), timeout: 1500 }) }
  catch { $q.notify({ type: 'negative', message: t('common.copyError') }) }
}
function available(action: 'pause' | 'resume' | 'step' | 'cancel'): boolean { return run.value?.operational?.available_actions.includes(action) ?? true }
function activityTitle(activity: RunActivity): string {
  if (activity.title) return activity.title
  let graph = run.value?.graph
  for (const key of activity.body_path) graph = graph?.nodes.find(node => node.id === key)?.body ?? undefined
  return graph?.nodes.find(node => node.id === activity.node_key)?.title || activity.node_key
}
function inspectActivity(activity: RunActivity): void {
  bodyPath.value = [...activity.body_path]
  selectNode(activity.node_key, activity.occurrence_id)
}
function message(value: unknown): string { return value instanceof Error ? value.message : t('nativeProcesses.error') }
async function refresh(): Promise<void> {
  if (loading.value) { refreshPending = true; return }
  clearTimeout(timer)
  const token = generation, id = props.runId
  loading.value = true
  void refreshMetrics()
  try {
    const next = await service.run(id, pagination.value.page, pagination.value.rowsPerPage, run.value?.event_cursor ?? 0)
    if (token !== generation || id !== props.runId) return
    run.value = next; pagination.value.rowsNumber = next.total
    emit('loaded', next)
    error.value = ''
    if (selectedNode.value) { inspectionRefreshPending = true; refreshInspection() }
  } catch (cause) { if (token === generation) error.value = message(cause) }
  finally {
    if (token === generation) {
      loading.value = false
      if (refreshPending) { refreshPending = false; void refresh() }
      else if (!terminal.value) timer = setTimeout(() => void refresh(), 2000)
    }
  }
}
async function refreshMetrics(): Promise<void> {
  if (metricsLoading) { metricsPending = true; return }
  const token = generation, id = props.runId
  metricsLoading = true
  try {
    const next = await service.metrics(id)
    if (token === generation && id === props.runId) { metrics.value = next; metricsError.value = ''; emit('metricsLoaded', next) }
  } catch (cause) { if (token === generation) metricsError.value = message(cause) }
  finally {
    if (token === generation) {
      metricsLoading = false
      if (metricsPending) { metricsPending = false; void refreshMetrics() }
    }
  }
}
function runChanged(payload: unknown): void {
  if (!payload || typeof payload !== 'object' || !('data' in payload)) return
  const data = payload.data
  if (!data || typeof data !== 'object' || !('id' in data) || data.id !== props.runId) return
  // Coalesce a burst without postponing refresh indefinitely during busy runs.
  if (eventTimer !== undefined) return
  eventTimer = setTimeout(() => { eventTimer = undefined; void refresh() }, 100)
}
function reconnect(): void { void refresh() }
function refreshInspection(): void {
  if (!inspectionRefreshPending || !selectedNode.value || activityPending.value || nodeLoading.value) return
  inspectionRefreshPending = false
  void loadActivity(activityPage.value?.page ?? 1, selectedOccurrence.value, true)
}
async function command(action: 'pause' | 'resume' | 'step'): Promise<void> {
  const token = generation, id = props.runId
  mutating.value = true
  try { await sendCommand(id, action); if (token === generation) await refresh() } catch (cause) { if (token === generation) error.value = message(cause) }
  finally { if (token === generation) mutating.value = false }
}
async function sendCommand(id: string, action: 'pause' | 'resume' | 'step' | 'breakpoints', nodes: string[] = []): Promise<void> {
  const signature = JSON.stringify([id, action, nodes])
  const command = pendingCommands.get(signature) ?? { key: crypto.randomUUID(), revision: run.value?.debugger_revision ?? 0 }
  pendingCommands.set(signature, command)
  try { await service.control(id, action, nodes, command.key, command.revision) }
  catch (cause) {
    if (isAxiosError(cause) && cause.response?.status && cause.response.status >= 400 && cause.response.status < 500) pendingCommands.delete(signature)
    throw cause
  }
  pendingCommands.delete(signature)
}
function requestCancel(): void {
  const token = generation
  showConfirmationDialog({ title: t('nativeProcesses.cancel'), message: t('nativeProcesses.confirmStop'), focus: 'cancel',
    ok: { label: t('nativeProcesses.cancel'), color: 'negative', flat: false },
    cancel: { label: t('common.cancel'), color: 'primary', flat: false, outline: true },
  }).onOk(() => { if (token === generation && canControl.value && !terminal.value) void cancel() })
}
async function cancel(): Promise<void> { const token = generation, id = props.runId; mutating.value = true; try { await service.cancel(id); if (token === generation) await refresh() } catch (cause) { if (token === generation) error.value = message(cause) } finally { if (token === generation) mutating.value = false } }
async function toggleBreakpoint(value: unknown): Promise<void> {
  if (!selectedNode.value || !run.value) return
  const token = generation, id = props.runId
  const nodes = run.value.breakpoints.filter(id => id !== selectedNode.value)
  if (value) nodes.push(selectedNode.value)
  mutating.value = true
  try { await sendCommand(id, 'breakpoints', nodes); if (token === generation) await refresh() } catch (cause) { if (token === generation) error.value = message(cause) } finally { if (token === generation) mutating.value = false }
}
function clearInspection(): void {
  inspectionRefreshPending = false
  activityGeneration++; nodeGeneration++; selectedNode.value = null; selectedOccurrence.value = null
  activityPage.value = null; nodeDetail.value = null; activityLoading.value = false; activityPending.value = false; nodeLoading.value = false; nodeError.value = false
}
function dismissInspection(kind: 'node' | 'flow', id: string): void { if (kind === 'node' && selectedNode.value === id) clearInspection() }
function selectNode(id: string, occurrenceId: string | null = null): void {
  clearInspection(); selectedNode.value = id; activitySize.value = 50
  void loadActivity(1, occurrenceId)
}
function selectOccurrence(_event: Event, node: NodeOccurrence): void {
  bodyPath.value = [...(node.body_path ?? [])]
  selectNode(node.node_key, node.id)
  void nextTick(() => canvas.value?.focusNode(node.node_key))
}
async function loadActivity(page: number, preferred: string | null = null, background = false): Promise<void> {
  if (!selectedNode.value) return
  const request = ++activityGeneration, token = generation, id = props.runId, node = selectedNode.value
  const path = [...bodyPath.value]
  if (!background) activityLoading.value = true
  activityPending.value = true
  nodeError.value = false
  try {
    const result = await service.activityOccurrences(id, node, path, page, activitySize.value)
    if (token !== generation || request !== activityGeneration) return
    activityPage.value = result
    selectedOccurrence.value = preferred ?? result.items[0]?.id ?? null
    await loadNode(background)
  } catch { if (token === generation && request === activityGeneration) nodeError.value = true }
  finally { if (token === generation && request === activityGeneration) { activityLoading.value = false; activityPending.value = false } }
}
function selectExecution(id: string): void { activityGeneration++; activityPending.value = false; activityLoading.value = false; selectedOccurrence.value = id; void loadNode() }
function requestActivityPage(page: number, size: number): void { activitySize.value = size; nodeGeneration++; nodeDetail.value = null; nodeLoading.value = false; void loadActivity(page) }
function retryInspection(): void { void loadActivity(activityPage.value?.page ?? 1, selectedOccurrence.value) }
async function loadNode(background = false): Promise<void> {
  const token = ++nodeGeneration, id = selectedOccurrence.value, runId = props.runId
  if (!background) nodeDetail.value = null
  nodeError.value = false; nodeLoading.value = false
  if (!id) return
  if (!background) nodeLoading.value = true
  try { const detail = await service.node(runId, id); if (token === nodeGeneration && runId === props.runId) nodeDetail.value = detail }
  catch { if (token === nodeGeneration) nodeError.value = true }
  finally { if (token === nodeGeneration) nodeLoading.value = false }
}
async function loadChildren(): Promise<void> {
  const token = generation, id = props.runId
  try { const next = await service.children(id, childNumber.value, childSize.value); if (token === generation && id === props.runId) childPage.value = next }
  catch (cause) { if (token === generation) error.value = message(cause) }
}
function requestPage(value: { pagination: { page: number; rowsPerPage: number } }): void {
  pagination.value = { ...pagination.value, ...value.pagination }; void refresh()
}
watch(bodyPath, clearInspection, { flush: 'sync' })
watch([activityPending, nodeLoading], refreshInspection)
watch(() => props.runId, () => { generation++; clearInspection(); clearTimeout(timer); clearTimeout(eventTimer); eventTimer = undefined; refreshPending = false; loading.value = false; mutating.value = false; run.value = null; bodyPath.value = []; childSize.value = 50;
  pendingCommands.clear();
  metricsLoading = false; metricsPending = false; metricsError.value = '';
  metrics.value = null; childPage.value = null; nodeDetail.value = null; selectedNode.value = null; selectedOccurrence.value = null;
  pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }; childNumber.value = 1; void refresh() }, { immediate: true })
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('process_run', 'update', runChanged)
  websocket.onEvent('process_run', 'delete', runChanged)
  websocket.onConnect(reconnect)
})
onBeforeUnmount(() => {
  generation++; clearInspection(); clearTimeout(timer); clearTimeout(eventTimer); refreshPending = false; metricsPending = false
  websocket.offEvent('process_run', 'update', runChanged)
  websocket.offEvent('process_run', 'delete', runChanged)
  websocket.offConnect(reconnect)
})
defineExpose({ refresh })
</script>

<style scoped>
.native-run-panel :deep(.diagram-editor) { border-radius: 0; }
.native-run-id { max-width: 100%; padding: 3px 6px; border-radius: 4px; font-size: 12px; font-weight: normal; line-height: 16px; white-space: normal; }
</style>
