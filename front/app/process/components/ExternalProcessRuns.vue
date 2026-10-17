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
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ProcessRunList, { type RunListPagination } from './ProcessRunList.vue'
import { processService, type ProcessDefinition, type ProcessRun } from '../services/processService'

const props = defineProps<{ definition: ProcessDefinition; revision: number }>()
const emit = defineEmits<{ openRun: [run: ProcessRun] }>()
const { t } = useI18n()
const rows = ref<ProcessRun[]>([]), loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'created_at', descending: true })
let generation = 0
const listRows = computed(() => rows.value.map(run => ({ ...run, accessibleLabel: run.summary || run.id, result_preview: resultPreview(run) })))
function resultPreview(run: ProcessRun): string {
  const text = run.error_message || run.error_code || (run.output != null ? JSON.stringify(run.output) : '')
  return text.length > 1200 ? text.slice(0, 1199) + '…' : text
}
function openRun(id: string): void { const run = rows.value.find(item => item.id === id); if (run) emit('openRun', run) }
function setPagination(value: RunListPagination): void {
  pagination.value = { ...value, sortBy: value.sortBy || 'created_at', descending: value.descending ?? true }
}
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true; error.value = false
  try {
    const { page, rowsPerPage, sortBy, descending } = pagination.value
    const result = await processService.runs({ processId: props.definition.id, page, pageSize: rowsPerPage, sortBy, descending })
    if (token !== generation) return
    rows.value = result.items; pagination.value.rowsNumber = result.total
  } catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number; sortBy?: string | null; descending?: boolean } }): void {
  pagination.value = { ...pagination.value, ...value.pagination, sortBy: value.pagination.sortBy || 'created_at' }
  void load()
}
watch(() => props.definition.id, () => { rows.value = []; pagination.value.page = 1; void load() }, { immediate: true })
watch(() => props.revision, () => { void load() })
onBeforeUnmount(() => { generation++ })
</script>
