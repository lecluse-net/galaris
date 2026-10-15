<template>
  <div class="q-gutter-y-md q-pa-md">
    <p class="text-caption">{{ t('datasets.usageScope') }}</p>
    <q-select v-model="kind" :options="kinds" emit-value map-options outlined :label="t('datasets.usageKind')" />
    <q-banner v-if="error" role="alert">{{ t('datasets.error') }} <q-btn flat :label="t('datasets.reload')" @click="load" /></q-banner>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id" :loading="loading" :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('datasets.noUsages')" @request="request">
      <template #body-cell-label="slot"><q-td :props="slot"><router-link :to="slot.row.url">{{ slot.row.label }}</router-link><div v-if="slot.row.uri" class="text-caption">{{ slot.row.uri }}</div></q-td></template>
      <template #body-cell-relation="slot"><q-td :props="slot">{{ t(`datasets.relations.${slot.row.relation}`) }}</q-td></template>
    </q-table>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableProps } from 'quasar'
import { datasetService as service } from '../services/datasetService'
import type { DatasetUsage, UsageKind } from '../types'
const props = defineProps<{ id: string }>()
const { t } = useI18n(), kind = ref<UsageKind>('documents'), rows = ref<DatasetUsage[]>([]), loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const kinds = computed(() => (['documents', 'processes', 'agents'] as const).map(value => ({ value, label: t(`datasets.usageKinds.${value}`) })))
const columns = computed<QTableProps['columns']>(() => [
  { name: 'label', field: 'label', label: t('datasets.usageSource'), align: 'left' },
  { name: 'relation', field: 'relation', label: t('datasets.usageRelation'), align: 'left' },
  { name: 'last_used_at', field: 'last_used_at', label: t('datasets.lastUsed'), align: 'left', format: value => value ? new Date(String(value)).toLocaleString() : '—' },
])
async function load(): Promise<void> {
  const token = ++generation; loading.value = true; error.value = false
  try { const result = await service.usages(props.id, kind.value, pagination.value.page, pagination.value.rowsPerPage); if (token !== generation) return; rows.value = result.items; pagination.value.rowsNumber = result.total }
  catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
function request({ pagination: value }: { pagination: { page: number; rowsPerPage: number } }): void { Object.assign(pagination.value, value); void load() }
watch(() => [props.id, kind.value], () => { rows.value = []; pagination.value.page = 1; pagination.value.rowsNumber = 0; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
