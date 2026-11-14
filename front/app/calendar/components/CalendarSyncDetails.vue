<template>
  <div class="sync-details q-gutter-y-sm">
    <div v-if="active" class="row items-center q-gutter-sm">
      <q-spinner color="primary" size="20px" />
      <strong role="status" aria-live="polite">{{ stateLabel }} · {{ stageLabel(run.stage) }}</strong>
      <span class="text-caption">{{ t('agenda.monitor.elapsed', { seconds: elapsed }) }}</span>
    </div>
    <template v-if="progress">
      <div v-if="active" class="text-caption">{{ t(progress.server_reached ? 'agenda.monitor.reached' : 'agenda.monitor.notReached') }}
        <span v-if="progress.network_phase"> · {{ networkLabel }}</span>
        <span v-if="progress.last_http_status"> · {{ t('agenda.monitor.http', { status: progress.last_http_status }) }}</span>
      </div>
      <q-markup-table flat bordered dense separator="horizontal" class="sync-counters">
        <thead><tr><th class="text-left">{{ t('agenda.monitor.activity') }}</th><th class="text-right">{{ t('agenda.monitor.result') }}</th></tr></thead>
        <tbody><tr v-for="row in counters" :key="row.label">
          <td class="sync-counter-label" role="rowheader">{{ row.label }}
            <q-linear-progress v-if="active && (row.stage === run.stage || row.total !== null)" class="q-mt-xs" color="primary" :indeterminate="row.total === null" :value="row.total ? Math.min(1, row.completed / row.total) : row.total === 0 ? 1 : 0" />
          </td>
          <td class="sync-counter-value"><strong>{{ count(row.completed, row.total) }}</strong></td>
        </tr>
        <tr v-for="row in outcomes" :key="row.label"><td class="sync-counter-label" role="rowheader">{{ row.label }}</td><td class="sync-counter-value">{{ number(row.value) }}</td></tr>
        </tbody>
      </q-markup-table>
      <q-expansion-item dense :label="t('agenda.monitor.technicalDetails')" icon="info_outline">
        <q-markup-table flat dense separator="horizontal" class="sync-counters">
          <tbody><tr v-for="row in technicalDetails" :key="row.label"><td class="sync-counter-label" role="rowheader">{{ row.label }}</td><td class="sync-counter-value">{{ row.value }}</td></tr></tbody>
        </q-markup-table>
      </q-expansion-item>
      <div v-if="active && ['receiving', 'transmitting'].includes(progress.network_phase ?? '')" class="text-caption">
        {{ t('agenda.monitor.transfer', { completed: number(progress.transfer_completed / 1000), total: progress.transfer_total === null ? t('agenda.monitor.unknown') : number(progress.transfer_total / 1000) }) }}
      </div>
      <q-list v-if="active && progress.steps.length" dense bordered separator>
        <q-item v-for="(step, index) in progress.steps" :key="`${step.stage}:${step.started_at}`">
          <q-item-section avatar><q-icon :name="index === progress.steps.length - 1 && run.state !== 'success' ? active ? 'sync' : 'error_outline' : 'done'" :color="index === progress.steps.length - 1 && !active && run.state !== 'success' ? 'negative' : 'primary'" /></q-item-section>
          <q-item-section><q-item-label>{{ stageLabel(step.stage) }}</q-item-label><q-item-label caption>{{ time(step.started_at) }}<template v-if="step.finished_at"> – {{ time(step.finished_at) }}</template></q-item-label></q-item-section>
        </q-item>
      </q-list>
    </template>
    <q-banner v-if="run.error_category || ['error', 'interrupted', 'conflict'].includes(run.state)" role="alert">
      {{ t('agenda.monitor.failure', { stage: stageLabel(run.stage), reason: run.error_category || stateLabel }) }}
      <span v-if="run.http_status"> · {{ t('agenda.monitor.http', { status: run.http_status }) }}</span>
    </q-banner>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SyncRun } from '../services/calendarService'
const { run, now = Date.now() } = defineProps<{ run: SyncRun; now?: number }>()
const { t, te, locale } = useI18n()
const active = computed(() => ['queued', 'running'].includes(run.state))
const progress = computed(() => run.progress)
const elapsed = computed(() => Math.max(0, Math.floor(((run.finished_at ? Date.parse(run.finished_at) : now) - Date.parse(run.started_at)) / 1000)))
const stateLabel = computed(() => te(`agenda.monitor.states.${run.state}`) ? t(`agenda.monitor.states.${run.state}`) : run.state)
const stageLabel = (stage: string) => te(`agenda.monitor.stages.${stage}`) ? t(`agenda.monitor.stages.${stage}`) : stage
const networkLabel = computed(() => t(`agenda.monitor.network.${progress.value?.network_phase ?? 'connecting'}`))
const number = (value: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 2 }).format(value)
const count = (completed: number, total: number | null) => `${number(completed)}/${total === null ? t('agenda.monitor.unknown') : number(total)}`
const time = (value: string) => new Intl.DateTimeFormat(locale.value, { timeStyle: 'medium' }).format(new Date(value))
const counters = computed(() => progress.value ? [
  { label: t('agenda.monitor.download'), stage: 'read', completed: progress.value.downloaded, total: progress.value.download_total },
  { label: t('agenda.monitor.apply'), stage: 'apply', completed: progress.value.applied, total: progress.value.apply_total },
  { label: t('agenda.monitor.upload'), stage: 'push', completed: progress.value.uploaded, total: progress.value.upload_total },
] : [])
const outcomes = computed(() => progress.value ? [
  { label: t('agenda.monitor.calendars'), value: progress.value.calendars },
  { label: t('agenda.monitor.deletions'), value: progress.value.deleted },
  { label: t('agenda.monitor.conflicts'), value: progress.value.conflicts },
] : [])
const technicalDetails = computed(() => progress.value ? [
  { label: t('agenda.monitor.verifiedUploads'), value: number(progress.value.upload_succeeded) },
  { label: t('agenda.monitor.requests'), value: number(progress.value.http_requests) },
  { label: t('agenda.monitor.receivedBytes'), value: t('agenda.monitor.kilobytes', { count: number(progress.value.bytes_received / 1000) }) },
  { label: t('agenda.monitor.sentBytes'), value: t('agenda.monitor.kilobytes', { count: number(progress.value.bytes_sent / 1000) }) },
] : [])
</script>
<style scoped>
.sync-details { min-width: 0; overflow-wrap: anywhere; }
.sync-counters :deep(.sync-counter-label) { text-align: left; white-space: normal; }
.sync-counters :deep(.sync-counter-value) { width: 1%; text-align: right; white-space: nowrap; }
</style>
