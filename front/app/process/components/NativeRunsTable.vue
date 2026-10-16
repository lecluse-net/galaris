<template>
  <section>
    <div class="row items-center"><div class="text-h6">{{ t('nativeProcesses.runs') }}</div><q-space /><q-btn flat round icon="refresh" :aria-label="t('nativeProcesses.refresh')" @click="load" /></div>
    <q-banner v-if="error" role="alert">{{ t('nativeProcesses.error') }}<template #action><q-btn flat :label="t('nativeProcesses.retry')" @click="load" /></template></q-banner>
    <q-table class="native-runs-table" :rows="result?.items ?? []" :columns="columns" row-key="id" :loading="loading" v-model:pagination="pagination" :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('processes.noRows')" @request="request">
      <template #body="scope">
        <q-tr :props="scope" class="native-run-row" tabindex="0" :aria-label="t('processes.showDetails') + ': ' + scope.row.process_label"
          @click="selectedRunId = scope.row.id" @keydown.enter.self="selectedRunId = scope.row.id" @keydown.space.self.prevent="selectedRunId = scope.row.id">
          <q-td key="label" :props="scope" class="native-run-title">{{ scope.row.process_label }}</q-td>
          <q-td key="id" :props="scope">
            <a class="native-run-id" :href="service.runUrl(scope.row.id)" :aria-label="t('nativeProcesses.copyRunUrl') + ': ' + scope.row.id" @click.stop.prevent="copyRunUrl(scope.row.id)">{{ scope.row.id }}<q-tooltip>{{ t('nativeProcesses.copyRunUrl') }}</q-tooltip></a>
          </q-td>
          <q-td key="status" :props="scope"><q-badge class="native-run-status" :class="`native-run-status--${statusColor(scope.row.status)}`">{{ statusLabel(scope.row.status) }}</q-badge></q-td>
          <q-td key="result" :props="scope"><div class="native-run-result" :class="{ 'native-run-result--error': scope.row.status === 'error' }">{{ scope.row.result_preview || t('nativeProcesses.execution.noResult') }}</div></q-td>
        </q-tr>
      </template>
      <template #item="scope">
        <div class="col-12 q-pa-xs">
          <q-card bordered flat class="native-run-row q-pa-md" tabindex="0" :aria-label="t('processes.showDetails') + ': ' + scope.row.process_label"
            @click="selectedRunId = scope.row.id" @keydown.enter.self="selectedRunId = scope.row.id" @keydown.space.self.prevent="selectedRunId = scope.row.id">
            <div class="text-subtitle2 q-mb-sm">{{ scope.row.process_label }}</div>
            <a class="native-run-id" :href="service.runUrl(scope.row.id)" :aria-label="t('nativeProcesses.copyRunUrl') + ': ' + scope.row.id" @click.stop.prevent="copyRunUrl(scope.row.id)">{{ scope.row.id }}</a>
            <div class="q-my-sm"><q-badge class="native-run-status" :class="`native-run-status--${statusColor(scope.row.status)}`">{{ statusLabel(scope.row.status) }}</q-badge></div>
            <div class="native-run-result" :class="{ 'native-run-result--error': scope.row.status === 'error' }">{{ scope.row.result_preview || t('nativeProcesses.execution.noResult') }}</div>
          </q-card>
        </div>
      </template>
    </q-table>
    <q-dialog :model-value="selectedRunId !== null" :aria-label="t('nativeProcesses.run')" :maximized="$q.screen.lt.md" @update:model-value="value => { if (!value) selectedRunId = null }">
      <q-card class="native-run-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="account_tree" class="q-mr-sm" /><div class="text-h6">{{ result?.items.find(item => item.id === selectedRunId)?.process_label || t('nativeProcesses.run') }}</div><q-space />
          <q-btn flat round dense icon="close" :aria-label="t('processes.close')" @click="selectedRunId = null" />
        </q-card-section>
        <q-card-section class="galaris-dialog-body"><NativeRunPanel v-if="selectedRunId" :key="selectedRunId" :run-id="selectedRunId" /></q-card-section>
      </q-card>
    </q-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar'
import { defineAsyncView, type SolaireColor } from '@/core/util'
import { nativeProcessService as service, type NativeChildren } from '../services/nativeProcessService'
const NativeRunPanel = defineAsyncView(() => import('./NativeRunPanel.vue'))
const props = defineProps<{ code?: string }>()
const { t, te } = useI18n()
const $q = useQuasar(), selectedRunId = ref<string | null>(null)
const result = ref<NativeChildren | null>(null), loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const columns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('nativeProcesses.processTitle'), field: 'process_label', align: 'left' },
  { name: 'id', label: t('nativeProcesses.runId'), field: 'id', align: 'left' },
  { name: 'status', label: t('processes.status'), field: 'status', align: 'left' },
  { name: 'result', label: t('nativeProcesses.runResult'), field: 'result_preview', align: 'left' },
])
function statusLabel(status: string): string {
  const key = `processes.statuses.${status}`
  return te(key) ? t(key) : status
}
function statusColor(status: string): SolaireColor {
  return ({ success: 'green', error: 'red', running: 'blue', waiting: 'orange', cancelling: 'orange', queued: 'cyan' } as Record<string, SolaireColor>)[status] ?? 'gray'
}
async function copyRunUrl(id: string): Promise<void> {
  try { await copyToClipboard(service.runUrl(id)); $q.notify({ type: 'positive', message: t('common.copied'), timeout: 1500 }) }
  catch { $q.notify({ type: 'negative', message: t('common.copyError') }) }
}
async function load(): Promise<void> { const token = ++generation; loading.value = true; error.value = false;
  try { const next = await service.runs(props.code, pagination.value.page, pagination.value.rowsPerPage); if (token === generation) { result.value = next; pagination.value.rowsNumber = next.total } }
  catch { if (token === generation) error.value = true } finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
watch(() => props.code, () => { selectedRunId.value = null; result.value = null; pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.native-run-dialog { width: 1400px; max-width: 96vw; max-height: 96vh; }
.native-run-row { cursor: pointer; }
.native-run-row:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: -2px; }
.native-run-title { white-space: normal; min-width: 160px; max-width: 280px; }
.native-run-id { color: var(--q-primary); font-family: monospace; overflow-wrap: anywhere; }
.native-run-result { white-space: pre-line; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden; line-height: 1.5; }
.native-runs-table :deep(td:last-child) { width: 45%; min-width: 240px; max-width: 560px; }
.native-run-result--error { color: var(--solaire-red-accent); }
.native-run-status { padding: 5px 8px; border: 1px solid var(--run-accent); background: var(--run-light); color: inherit; font-weight: 600; }
.native-run-status--green { --run-accent: var(--solaire-green-accent); --run-light: var(--solaire-green-light); --run-dark: var(--solaire-green-dark); }
.native-run-status--red { --run-accent: var(--solaire-red-accent); --run-light: var(--solaire-red-light); --run-dark: var(--solaire-red-dark); }
.native-run-status--blue { --run-accent: var(--solaire-blue-accent); --run-light: var(--solaire-blue-light); --run-dark: var(--solaire-blue-dark); }
.native-run-status--orange { --run-accent: var(--solaire-orange-accent); --run-light: var(--solaire-orange-light); --run-dark: var(--solaire-orange-dark); }
.native-run-status--cyan { --run-accent: var(--solaire-cyan-accent); --run-light: var(--solaire-cyan-light); --run-dark: var(--solaire-cyan-dark); }
.native-run-status--gray { --run-accent: var(--solaire-gray-accent); --run-light: var(--solaire-gray-light); --run-dark: var(--solaire-gray-dark); }
body.body--dark .native-run-status { background: var(--run-dark); }
</style>
