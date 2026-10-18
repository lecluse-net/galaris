<template>
  <q-dialog :model-value="true" :aria-label="loadedRun?.label || title || t('nativeProcesses.runs')" :maximized="$q.screen.lt.md" @update:model-value="value => { if (!value) emit('close') }">
    <q-card class="native-run-dialog galaris-dialog-card">
      <q-card-section class="galaris-dialog-title native-run-header">
        <q-icon name="account_tree" />
        <div class="native-run-header-content">
          <div class="native-run-heading">
            <div class="text-h6 native-run-title">{{ loadedRun?.label || title || t('nativeProcesses.runs') }}</div>
            <ProcessRunStatusBadge v-if="loadedRun" :status="loadedRun.status" variant="diagram" />
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
        <q-btn flat round dense icon="close" class="self-start" :aria-label="t('processes.close')" @click="emit('close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body q-pa-none"><NativeRunPanel :key="runId + ':' + agentId" :run-id="runId" :agent-id="agentId" embedded summary-in-header @loaded="loadedRun = $event" @metrics-loaded="loadedMetrics = $event" /></q-card-section>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '@/core/util'
import ProcessRunStatusBadge from './ProcessRunStatusBadge.vue'
import type { NativeRun, NativeMetrics } from '../services/nativeProcessService'
const NativeRunPanel = defineAsyncView(() => import('./NativeRunPanel.vue'))
const { runId, title = '', agentId = null } = defineProps<{ runId: string; title?: string; agentId?: number | null }>()
const emit = defineEmits<{ close: [] }>()
const { t, locale } = useI18n()
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
function formatDate(value: string): string { return new Date(value).toLocaleString(locale.value) }
watch(() => [runId, agentId], () => { loadedRun.value = null; loadedMetrics.value = null }, { flush: 'sync' })
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
