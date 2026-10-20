<template>
  <section>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <ProcessRunList class="native-runs-table" :rows="listRows" v-model:pagination="pagination" :loading="loading"
      @request="request" @refresh="load" @open="selectedRunId = $event" />
    <NativeRunDialog v-if="selectedRunId" :run-id="selectedRunId" :title="selectedRun?.process_label" @close="selectedRunId = null" />
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView, usePaginatedQuery } from '@/core/util'
import ProcessRunList from './ProcessRunList.vue'
import { nativeProcessService as service } from '../services/nativeProcessService'
import { useProcessCatalogueStore } from '../stores/catalogueStore'
import { useProcessRunRefresh } from '../composables/useProcessRunRefresh'
const NativeRunDialog = defineAsyncView(() => import('./NativeRunDialog.vue'))
const props = defineProps<{ code?: string; refreshRevision?: number; navigationKey?: string }>()
const navigation = useProcessCatalogueStore()
const { t } = useI18n()
const selectedRunId = ref<string | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const { result, loading, error, load, reset } = usePaginatedQuery(pagination,
  page => service.runs(props.code, page.page, page.rowsPerPage))
const selectedRun = computed(() => result.value?.items.find(item => item.id === selectedRunId.value))
const listRows = computed(() => (result.value?.items ?? []).map(run => ({ ...run, accessibleLabel: run.process_label })))
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
watch(() => props.code, () => {
  const saved = props.navigationKey ? navigation.runPages[props.navigationKey] : undefined
  selectedRunId.value = null; reset()
  pagination.value = { page: saved?.page ?? 1, rowsPerPage: saved?.rowsPerPage ?? 50, rowsNumber: 0 }
  void load()
}, { immediate: true })
watch(pagination, value => {
  if (props.navigationKey) navigation.runPages[props.navigationKey] = { page: value.page, rowsPerPage: value.rowsPerPage }
}, { deep: true })
watch(() => props.refreshRevision, () => { void load() })
useProcessRunRefresh(load, loading)
</script>
