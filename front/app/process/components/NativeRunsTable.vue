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
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '@/core/util'
import ProcessRunList from './ProcessRunList.vue'
import { nativeProcessService as service, type NativeChildren } from '../services/nativeProcessService'
import { useProcessCatalogueStore } from '../stores/catalogueStore'
import { useProcessRunRefresh } from '../composables/useProcessRunRefresh'
const NativeRunDialog = defineAsyncView(() => import('./NativeRunDialog.vue'))
const props = defineProps<{ code?: string; refreshRevision?: number; navigationKey?: string }>()
const navigation = useProcessCatalogueStore()
const { t } = useI18n()
const selectedRunId = ref<string | null>(null)
const result = ref<NativeChildren | null>(null), loading = ref(false), error = ref(false)
const selectedRun = computed(() => result.value?.items.find(item => item.id === selectedRunId.value))
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const listRows = computed(() => (result.value?.items ?? []).map(run => ({ ...run, accessibleLabel: run.process_label })))
async function load(): Promise<void> { const token = ++generation; loading.value = true; error.value = false;
  try {
    const next = await service.runs(props.code, pagination.value.page, pagination.value.rowsPerPage)
    if (token !== generation) return
    const lastPage = Math.max(1, Math.ceil(next.total / pagination.value.rowsPerPage))
    if (pagination.value.page > lastPage) { pagination.value.page = lastPage; await load(); return }
    result.value = next; pagination.value.rowsNumber = next.total
  }
  catch { if (token === generation) error.value = true } finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
watch(() => props.code, () => {
  const saved = props.navigationKey ? navigation.runPages[props.navigationKey] : undefined
  selectedRunId.value = null; result.value = null
  pagination.value = { page: saved?.page ?? 1, rowsPerPage: saved?.rowsPerPage ?? 50, rowsNumber: 0 }
  void load()
}, { immediate: true })
watch(pagination, value => {
  if (props.navigationKey) navigation.runPages[props.navigationKey] = { page: value.page, rowsPerPage: value.rowsPerPage }
}, { deep: true })
watch(() => props.refreshRevision, () => { void load() })
useProcessRunRefresh(load, loading)
onBeforeUnmount(() => { generation++ })
</script>
