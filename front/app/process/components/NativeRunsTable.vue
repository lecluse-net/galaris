<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="native-runs-table" :rows="listRows" v-model:pagination="pagination" :loading="loading"
      @request="request" @refresh="load" @open="selectedRunId = $event" />
    <q-dialog :model-value="selectedRunId !== null" :aria-label="selectedRun?.process_label || t('nativeProcesses.runs')" :maximized="$q.screen.lt.md" @update:model-value="value => { if (!value) selectedRunId = null }">
      <q-card class="native-run-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title native-run-header">
          <q-icon name="account_tree" />
          <div class="native-run-header-content">
            <div class="native-run-heading">
              <div class="text-h6 native-run-title">{{ selectedRun?.process_label || t('nativeProcesses.runs') }}</div>
              <ProcessRunStatusBadge v-if="loadedRun || selectedRun" :status="loadedRun?.status ?? selectedRun!.status" variant="diagram" />
              <q-badge v-if="loadedRun?.paused" outline>{{ t('nativeProcesses.paused') }}</q-badge>
            </div>
            <div class="native-run-metadata">
              <q-badge v-if="loadedRun?.operational" outline class="native-run-metadata-badge" tabindex="0"
                :aria-label="t('nativeProcesses.lastActivity', { date: formatDate(loadedRun.operational.last_activity_at) })">
                <q-icon name="update" size="14px" />
                <span>{{ formatDate(loadedRun.operational.last_activity_at) }}</span>
                <q-tooltip>{{ t('nativeProcesses.lastActivity', { date: formatDate(loadedRun.operational.last_activity_at) }) }}</q-tooltip>
              </q-badge>
              <q-badge v-if="loadedRun" outline class="native-run-metadata-badge" tabindex="0"
                :aria-label="`${t('nativeProcesses.duration')}: ${duration}`">
                <q-icon name="timer" size="14px" />
                <span>{{ duration }}</span>
                <q-tooltip>{{ t('nativeProcesses.duration') }}</q-tooltip>
              </q-badge>
              <q-badge outline class="native-run-cost native-run-metadata-badge" tabindex="0"
                :aria-label="`${t('nativeProcesses.inclusiveCost')}: ${totalCost}`">
                <q-icon name="attach_money" size="14px" />
                <span>{{ costAmount }}</span>
                <q-icon v-if="loadedMetrics?.partial || loadedMetrics?.inclusive.estimated_calls" name="info_outline" size="14px" />
                <q-tooltip>
                  <div>{{ t('nativeProcesses.inclusiveCost') }}</div>
                  <div v-if="loadedMetrics?.partial">{{ t('nativeProcesses.partial') }}</div>
                  <div v-if="loadedMetrics?.inclusive.estimated_calls">{{ t('nativeProcesses.estimated', { count: loadedMetrics.inclusive.estimated_calls }) }}</div>
                </q-tooltip>
              </q-badge>
            </div>
          </div>
          <q-btn flat round dense icon="close" class="self-start" :aria-label="t('processes.close')" @click="selectedRunId = null" />
        </q-card-section>
        <q-card-section class="galaris-dialog-body q-pa-none"><NativeRunPanel v-if="selectedRunId" :key="selectedRunId" :run-id="selectedRunId" embedded summary-in-header @loaded="loadedRun = $event" @metrics-loaded="loadedMetrics = $event" /></q-card-section>
      </q-card>
    </q-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '@/core/util'
import ProcessRunList from './ProcessRunList.vue'
import ProcessRunStatusBadge from './ProcessRunStatusBadge.vue'
import { nativeProcessService as service, type NativeChildren, type NativeRun, type NativeMetrics } from '../services/nativeProcessService'
const NativeRunPanel = defineAsyncView(() => import('./NativeRunPanel.vue'))
const props = defineProps<{ code?: string; refreshRevision?: number }>()
const { t, locale } = useI18n()
const selectedRunId = ref<string | null>(null)
const result = ref<NativeChildren | null>(null), loading = ref(false), error = ref(false)
const loadedRun = shallowRef<NativeRun | null>(null)
const loadedMetrics = shallowRef<NativeMetrics | null>(null)
const totalCost = computed(() => loadedMetrics.value?.inclusive.cost == null ? t('nativeProcesses.unknown') : new Intl.NumberFormat(locale.value, {
  style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 6,
}).format(loadedMetrics.value.inclusive.cost))
const costAmount = computed(() => loadedMetrics.value?.inclusive.cost == null ? t('nativeProcesses.unknown') : new Intl.NumberFormat(locale.value, {
  minimumFractionDigits: 2, maximumFractionDigits: 6,
}).format(loadedMetrics.value.inclusive.cost))
const duration = computed(() => loadedRun.value?.duration_seconds == null ? t('nativeProcesses.unknown') : `${new Intl.NumberFormat(locale.value, {
  maximumFractionDigits: 1,
}).format(loadedRun.value.duration_seconds)} s`)
const selectedRun = computed(() => result.value?.items.find(item => item.id === selectedRunId.value))
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const listRows = computed(() => (result.value?.items ?? []).map(run => ({ ...run, accessibleLabel: run.process_label })))
function formatDate(value: string): string { return new Date(value).toLocaleString(locale.value) }
async function load(): Promise<void> { const token = ++generation; loading.value = true; error.value = false;
  try { const next = await service.runs(props.code, pagination.value.page, pagination.value.rowsPerPage); if (token === generation) { result.value = next; pagination.value.rowsNumber = next.total } }
  catch { if (token === generation) error.value = true } finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
watch(() => props.code, () => { selectedRunId.value = null; result.value = null; pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }; void load() }, { immediate: true })
watch(() => props.refreshRevision, () => { void load() })
watch(selectedRunId, () => { loadedRun.value = null; loadedMetrics.value = null }, { flush: 'sync' })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.native-run-dialog { width: 1400px; max-width: 96vw; max-height: calc(100vh - 32px); }
.native-run-header-content { display: flex; flex: 1; flex-wrap: wrap; align-items: center; gap: 6px 16px; min-width: 0; }
.native-run-heading { display: flex; flex: 1 1 240px; align-items: center; gap: 8px; min-width: 0; }
.native-run-title { min-width: 0; }
.native-run-heading > .q-badge { flex-shrink: 0; }
.native-run-metadata { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0; }
.native-run-metadata-badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 6px; border-radius: 4px; font-size: 12px; font-weight: normal; line-height: 16px; }
.native-run-cost :deep(.q-icon) { color: inherit !important; }
</style>
