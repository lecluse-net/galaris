<template>
  <q-card-section :class="runHeaderClass(run.status)">
    <div class="current-run-header-row">
      <q-icon :name="runStatusIcon(run.status)" :color="statusColor(run.status)" size="md" class="q-mr-sm" />
      <div class="current-run-header-content">
        <div class="current-run-summary text-subtitle1">{{ run.summary }}</div>
        <div class="current-run-toolbar q-mt-xs">
          <span class="text-caption text-grey-7 cursor-pointer" @click="emit('copyId', run.id)">{{ shortId(run.id) }}</span>
          <div class="current-run-actions">
            <q-btn v-if="canOperateRuns" icon="refresh" :label="t('processes.refresh')" @click="emit('refresh')" />
            <q-btn v-if="canAnalyze" color="secondary" icon="analytics" :label="t('processes.analyze')" @click="emit('analyze')" />
            <q-btn v-if="canOperateRuns && ['error', 'cancelled'].includes(run.status)" color="primary" icon="replay" :label="t('processes.retry')" @click="emit('retry')" />
            <q-btn v-if="canOperateRuns && !terminal(run.status)" color="negative" icon="cancel" :label="t('processes.cancel')" @click="emit('cancel')" />
            <span v-if="canAdmin">
              <q-btn color="negative" icon="delete" :label="t('processes.deleteRun')" :disable="!terminal(run.status)" @click="emit('delete', run)" />
              <q-tooltip v-if="!terminal(run.status)">{{ t('processes.runActiveDeleteHint') }}</q-tooltip>
            </span>
          </div>
        </div>
      </div>
    </div>
  </q-card-section>
  <q-separator />
  <q-card-section class="q-gutter-md">
    <q-banner v-if="run.error_message" class="bg-red-1 text-negative">{{ run.error_code }} — {{ run.error_message }}</q-banner>
    <div v-if="run.engine_metadata.failed_node" class="text-caption text-negative">{{ t('processes.failedNode') }} : {{ run.engine_metadata.failed_node }}</div>
    <q-banner v-if="run.engine_metadata.remote_may_continue" class="bg-orange-1 text-warning">{{ t('processes.remoteMayContinue') }}</q-banner>
    <div class="run-data-grid">
      <CodeEditor :model-value="pretty(run.input)" language="json" :label="t('processes.input')" readonly :show-error="false" :visible-lines="10" :min-lines="5" />
      <CodeEditor :model-value="pretty(run.output)" language="json" :label="t('processes.output')" readonly :show-error="false" :visible-lines="10" :min-lines="5" />
    </div>
    <template v-if="analysis">
      <q-separator />
      <div class="text-subtitle2">{{ t('processes.summary') }}</div>
      <p>{{ analysis.summary }}</p>
      <ul><li v-for="item in analysis.recommendations" :key="item">{{ item }}</li></ul>
    </template>
    <template v-if="run.task_ids?.length">
      <q-separator />
      <div class="text-subtitle2">{{ t('processes.linkedTasks') }}</div>
      <div class="linked-task-actions">
        <q-btn v-for="taskId in canReadTasks ? run.task_ids : []" :key="taskId" flat icon="task_alt" :label="taskResourceUri(taskId)" :to="{ path: '/task', query: { task_id: taskId } }" />
      </div>
    </template>
    <template v-if="run.llm_calls?.length">
      <q-separator />
      <div class="text-subtitle2">{{ t('processes.llmCalls') }}</div>
      <q-list bordered separator>
        <q-item v-for="call in run.llm_calls" :key="call.id" class="process-llm-call">
          <q-item-section avatar><q-icon name="psychology" color="secondary" /></q-item-section>
          <q-item-section>
            <q-item-label class="process-llm-title">
              <q-badge color="indigo-7" outline>{{ purposeLabel(call) }}</q-badge>
              <span>{{ call.requested_model }}</span>
            </q-item-label>
            <q-item-label caption>{{ call.provider_name }} · {{ statusLabel(call.status) }} · {{ formatDuration(call.duration) }}</q-item-label>
            <q-item-label v-if="call.error" caption class="text-negative">{{ call.error }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="process-llm-metrics">
              <q-badge
                color="blue-grey-6"
                tabindex="0"
                :title="tokenSummary(call)"
                :aria-label="tokenSummary(call)"
              >
                <q-icon name="title" size="xs" class="q-mr-xs" />
                {{ formatTokenCount(call.output_tokens) }}
              </q-badge>
              <q-badge color="purple">
                <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                {{ formatCost(call.cost) }}
              </q-badge>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </template>
    <q-expansion-item icon="history" :label="`${t('processes.events')} (${run.events?.length || 0})`">
      <q-timeline color="primary" layout="dense" class="q-pa-md">
        <q-timeline-entry v-for="event in run.events" :key="event.id" :title="event.event_type" :subtitle="`${formatDate(event.created_at)} · ${event.source}`">
          <CodeEditor :model-value="pretty(event.payload)" language="json" :label="event.event_type" readonly :show-error="false" :visible-lines="6" :min-lines="3" />
        </q-timeline-entry>
      </q-timeline>
    </q-expansion-item>
  </q-card-section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { taskResourceUri } from '@/app/task'
import { CodeEditor } from '@/core/util'
import type { ProcessAnalysis, ProcessLLMCall, ProcessRun } from '../services/processService'

defineProps<{
  run: ProcessRun
  analysis: ProcessAnalysis | null
  canOperateRuns: boolean
  canAnalyze: boolean
  canAdmin: boolean
  canReadTasks: boolean
}>()

const emit = defineEmits<{
  refresh: []
  analyze: []
  retry: []
  cancel: []
  delete: [run: ProcessRun]
  copyId: [id: string]
}>()

const { t, te, locale } = useI18n()

function pretty(value: unknown): string { return JSON.stringify(value ?? null, null, 2) }
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—' }
function formatDuration(value: number): string { return `${value.toFixed(2)} s` }
function formatCost(value: number): string { return new Intl.NumberFormat(locale.value, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 4 }).format(value) }
function formatTokenCount(value: number): string { return new Intl.NumberFormat(locale.value).format(value) }
function tokenSummary(call: ProcessLLMCall): string {
  return t('processes.tokenSummary', {
    input: formatTokenCount(call.input_tokens),
    inputCache: formatTokenCount(call.cache_read_tokens),
    output: formatTokenCount(call.output_tokens),
  })
}
function shortId(id: string): string { return `${id.slice(0, 8)}…${id.slice(-4)}` }
function purposeLabel(call: ProcessLLMCall): string {
  if (!call.purpose) return '—'
  const key = `llmCalls.purposes.${call.purpose}`
  return te(key) ? t(key) : call.purpose
}
function statusLabel(status: string): string { const key = `processes.statuses.${status}`; return te(key) ? t(key) : status }
function statusColor(status: string): string { return ({ success: 'positive', error: 'negative', cancelled: 'grey', running: 'primary', waiting: 'orange', queued: 'blue-grey', cancelling: 'warning', unknown: 'dark' } as Record<string, string>)[status] || 'grey' }
function runStatusIcon(status: string): string { return ({ success: 'check_circle', error: 'error', cancelled: 'cancel', running: 'play_circle', waiting: 'hourglass_top', queued: 'schedule', cancelling: 'pending', unknown: 'help' } as Record<string, string>)[status] || 'help' }
function runHeaderClass(status: string): string { return ({ success: 'bg-positive-1', error: 'bg-negative-1', running: 'bg-blue-1', waiting: 'bg-orange-1' } as Record<string, string>)[status] || 'bg-grey-1' }
function terminal(status: string): boolean { return ['success', 'error', 'cancelled'].includes(status) }
</script>

<style scoped>
.current-run-actions, .linked-task-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.run-data-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.process-llm-metrics { display: flex; align-items: center; justify-content: flex-end; gap: 4px; flex-wrap: wrap; }
.process-llm-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.current-run-header-row { display: flex; align-items: flex-start; }
.current-run-header-content { flex: 1 1 auto; min-width: 0; }
.current-run-summary { overflow-wrap: anywhere; }
.current-run-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.bg-positive-1 { background-color: rgba(33, 186, 69, 0.1); }
.bg-negative-1 { background-color: rgba(193, 0, 21, 0.1); }
.bg-blue-1 { background-color: rgba(25, 118, 210, 0.1); }
.bg-orange-1 { background-color: rgba(242, 192, 55, 0.15); }
@media (max-width: 1023px) {
  .current-run-toolbar { align-items: flex-start; flex-direction: column; }
  .current-run-actions { justify-content: flex-start; width: 100%; }
  .run-data-grid { grid-template-columns: 1fr; }
  .process-llm-call { align-items: flex-start; flex-wrap: wrap; }
  .process-llm-call > :deep(.q-item__section--side) { width: 100%; align-items: flex-end; padding-left: 56px; }
}
@media (max-width: 599px) {
  .current-run-header-row > .q-icon { margin-top: 2px; }
  .current-run-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .current-run-actions > .q-btn, .current-run-actions > span, .current-run-actions > span > .q-btn { width: 100%; }
  .linked-task-actions { justify-content: flex-start; }
  .linked-task-actions .q-btn { max-width: 100%; }
  .linked-task-actions :deep(.q-btn__content) { min-width: 0; }
  .linked-task-actions :deep(.q-btn__content > span) { overflow: hidden; text-overflow: ellipsis; }
  .process-llm-call > :deep(.q-item__section--avatar) { min-width: 36px; padding-right: 8px; }
  .process-llm-call > :deep(.q-item__section--side) { padding-left: 36px; }
  :deep(.q-timeline) { padding-left: 8px; padding-right: 0; }
}
</style>
