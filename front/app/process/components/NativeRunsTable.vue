<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn color="primary" outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="native-runs-table" :rows="listRows" :pagination="pagination" :loading="loading"
      @update:pagination="setPagination" @request="request" @refresh="load" @open="selectedRunId = $event" />
    <NativeRunDialog v-if="selectedRunId" :run-id="selectedRunId" :title="selectedRun?.process_label" @close="selectedRunId = null" />
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '@/core/util'
import ProcessRunList from './ProcessRunList.vue'
import { nativeProcessService as service } from '../services/nativeProcessService'
import { useProcessRunHistory } from '../composables/useProcessRunHistory'
const NativeRunDialog = defineAsyncView(() => import('./NativeRunDialog.vue'))
const props = defineProps<{ code?: string; refreshRevision?: number; navigationKey?: string }>()
const { t } = useI18n()
const selectedRunId = ref<string | null>(null)
const { pagination, result, loading, error, load, setPagination, request } = useProcessRunHistory({
  context: () => props.code,
  navigationKey: () => props.navigationKey,
  revision: () => props.refreshRevision,
  onContextReset: () => { selectedRunId.value = null },
}, page => service.runs(props.code, page.page, page.rowsPerPage))
const selectedRun = computed(() => result.value?.items.find(item => item.id === selectedRunId.value))
const listRows = computed(() => (result.value?.items ?? []).map(run => ({ ...run, accessibleLabel: run.process_label })))
</script>
