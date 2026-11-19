<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('processes.genericError') }}
      <template #action><q-btn color="primary" outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="run-table" :rows="listRows" :pagination="pagination" :loading="loading" :show-refresh="false"
      @update:pagination="setPagination" @request="request" @refresh="load" @open="openRun" />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ProcessRunList from './ProcessRunList.vue'
import { processService, type ProcessDefinition, type ProcessRun } from '../services/processService'
import { useProcessRunHistory } from '../composables/useProcessRunHistory'

const props = defineProps<{ definition: Pick<ProcessDefinition, 'id'>; revision: number }>()
const emit = defineEmits<{ openRun: [run: ProcessRun] }>()
const { t } = useI18n()
const defaultSort = 'created_at'
const { pagination, result, loading, error, load, setPagination, request } = useProcessRunHistory({
  context: () => props.definition.id,
  navigationKey: () => `external-${props.definition.id}`,
  revision: () => props.revision,
  defaultSort,
}, page => processService.runs({
  processId: props.definition.id, page: page.page, pageSize: page.rowsPerPage,
  sortBy: page.sortBy || defaultSort, descending: page.descending,
}))
const rows = computed(() => result.value?.items ?? [])
const listRows = computed(() => rows.value.map(run => ({ ...run, accessibleLabel: run.summary || run.id, result_preview: resultPreview(run) })))
function resultPreview(run: ProcessRun): string {
  const text = run.error_message || run.error_code || (run.output != null ? JSON.stringify(run.output) : '')
  return text.length > 1200 ? text.slice(0, 1199) + '…' : text
}
function openRun(id: string): void { const run = rows.value.find(item => item.id === id); if (run) emit('openRun', run) }
</script>
