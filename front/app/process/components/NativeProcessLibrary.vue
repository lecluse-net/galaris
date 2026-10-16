<template>
  <section class="q-mb-lg">
    <div class="row items-center q-mb-sm"><div class="text-h6">{{ t('nativeProcesses.title') }}</div><q-space />
      <q-btn v-if="canEdit" color="primary" icon="add" :label="t('nativeProcesses.newProcess')" to="/process/new-internal" />
      <q-btn flat round icon="refresh" :aria-label="t('nativeProcesses.refresh')" @click="load" /></div>
    <q-banner v-if="error" role="alert">{{ t('nativeProcesses.error') }}<template #action><q-btn flat :label="t('nativeProcesses.retry')" @click="load" /></template></q-banner>
    <q-table :rows="rows" :columns="columns" :loading="loading" row-key="code" :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('nativeProcesses.empty')"
      v-model:pagination="pagination" @request="request" @row-click="open">
      <template #body-cell-title="scope"><q-td :props="scope"><q-btn flat no-caps :label="scope.row.title" :to="`/process/internal/${scope.row.code}`" /></q-td></template>
    </q-table>
    <NativeRunsTable class="q-mt-md" />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { QTableColumn } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import { nativeProcessService as service, type NativeDefinitionSummary } from '../services/nativeProcessService'
import NativeRunsTable from './NativeRunsTable.vue'
const { t } = useI18n(), router = useRouter(), privileges = usePrivilegeStore()
const rows = ref<NativeDefinitionSummary[]>([]), loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const canEdit = computed(() => privileges.hasPrivilege('PROCESS_EDIT') || privileges.hasPrivilege('PROCESS_ADMIN'))
const columns = computed<QTableColumn[]>(() => [
  { name: 'title', label: t('nativeProcesses.titleField'), field: 'title', align: 'left' },
  { name: 'code', label: t('nativeProcesses.code'), field: 'code', align: 'left' },
  { name: 'archived', label: t('nativeProcesses.archive'), field: 'archived', align: 'left' },
])
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true; error.value = false
  try { const page = await service.list(pagination.value.page, pagination.value.rowsPerPage); if (token !== generation) return;
    rows.value = page.items; pagination.value.rowsNumber = page.total
  } catch { if (token === generation) error.value = true } finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void load() }
function open(_event: Event, row: NativeDefinitionSummary): void { void router.push(`/process/internal/${row.code}`) }
onMounted(load); onBeforeUnmount(() => { generation++ })
</script>
