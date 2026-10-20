<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('processes.genericError') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="run-table" :rows="listRows" :pagination="pagination" :loading="loading" :show-refresh="false"
      @update:pagination="setPagination" @request="request" @refresh="load" @open="openRun" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePaginatedQuery } from '@/core/util'
import ProcessRunList, { type RunListPagination } from './ProcessRunList.vue'
import { processService, type ProcessDefinition, type ProcessRun } from '../services/processService'
import { useProcessCatalogueStore } from '../stores/catalogueStore'
import { useProcessRunRefresh } from '../composables/useProcessRunRefresh'

const props = defineProps<{ definition: Pick<ProcessDefinition, 'id'>; revision: number }>()
const emit = defineEmits<{ openRun: [run: ProcessRun] }>()
const { t } = useI18n()
const navigation = useProcessCatalogueStore()
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'created_at', descending: true })
const { result, loading, error, load, reset } = usePaginatedQuery(pagination, page => processService.runs({
  processId: props.definition.id, page: page.page, pageSize: page.rowsPerPage,
  sortBy: page.sortBy || 'created_at', descending: page.descending,
}))
const rows = computed(() => result.value?.items ?? [])
const listRows = computed(() => rows.value.map(run => ({ ...run, accessibleLabel: run.summary || run.id, result_preview: resultPreview(run) })))
function resultPreview(run: ProcessRun): string {
  const text = run.error_message || run.error_code || (run.output != null ? JSON.stringify(run.output) : '')
  return text.length > 1200 ? text.slice(0, 1199) + '…' : text
}
function openRun(id: string): void { const run = rows.value.find(item => item.id === id); if (run) emit('openRun', run) }
function setPagination(value: RunListPagination): void {
  pagination.value = { ...value, sortBy: value.sortBy || 'created_at', descending: value.descending ?? true }
}
function request(value: { pagination: { page: number; rowsPerPage: number; sortBy?: string | null; descending?: boolean } }): void {
  pagination.value = { ...pagination.value, ...value.pagination, sortBy: value.pagination.sortBy || 'created_at' }
  void load()
}
watch(() => props.definition.id, () => {
  const saved = navigation.runPages[`external-${props.definition.id}`]
  reset()
  pagination.value = { page: saved?.page ?? 1, rowsPerPage: saved?.rowsPerPage ?? 50, sortBy: saved?.sortBy || 'created_at', descending: saved?.descending ?? true, rowsNumber: 0 }
  void load()
}, { immediate: true })
watch(pagination, value => {
  navigation.runPages[`external-${props.definition.id}`] = { page: value.page, rowsPerPage: value.rowsPerPage, sortBy: value.sortBy, descending: value.descending }
}, { deep: true })
watch(() => props.revision, () => { void load() })
useProcessRunRefresh(load, loading)
</script>
