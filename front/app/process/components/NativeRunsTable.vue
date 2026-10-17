<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="native-runs-table" :rows="listRows" v-model:pagination="pagination" :loading="loading"
      @request="request" @refresh="load" @open="selectedRunId = $event" />
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
import { defineAsyncView } from '@/core/util'
import ProcessRunList from './ProcessRunList.vue'
import { nativeProcessService as service, type NativeChildren } from '../services/nativeProcessService'
const NativeRunPanel = defineAsyncView(() => import('./NativeRunPanel.vue'))
const props = defineProps<{ code?: string; refreshRevision?: number }>()
const { t } = useI18n()
const selectedRunId = ref<string | null>(null)
const result = ref<NativeChildren | null>(null), loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const listRows = computed(() => (result.value?.items ?? []).map(run => ({ ...run, accessibleLabel: run.process_label })))
async function load(): Promise<void> { const token = ++generation; loading.value = true; error.value = false;
  try { const next = await service.runs(props.code, pagination.value.page, pagination.value.rowsPerPage); if (token === generation) { result.value = next; pagination.value.rowsNumber = next.total } }
  catch { if (token === generation) error.value = true } finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
watch(() => props.code, () => { selectedRunId.value = null; result.value = null; pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }; void load() }, { immediate: true })
watch(() => props.refreshRevision, () => { void load() })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.native-run-dialog { width: 1400px; max-width: 96vw; max-height: 96vh; }
</style>
