<template>
  <q-table v-model:pagination="pagination" :rows="entries" :columns="columns" row-key="id" flat bordered wrap-cells
    :class="{ 'permission-functions-table': nested }"
    :loading="loading" :grid="$q.screen.lt.md" :rows-per-page-options="[10, 20, 50, 100, 500]"
    :no-data-label="t(nested ? 'connection.auth.noFunctions' : 'permissions.empty')" @request="emit('request', $event)">
    <template #body-cell-title="props"><q-td :props="props"><div class="text-weight-medium">{{ props.row.title }}</div>
      <div class="text-caption permission-text">{{ props.row.description }}</div></q-td></template>
    <template #body-cell-state="props"><q-td :props="props">
      <PermissionStateBadge :state="props.row.state" :label="t(`permissions.dashboard.states.${props.row.state}`)" />
      <div class="text-caption permission-text">{{ props.row.origin }}</div>
      <div class="text-caption permission-text">{{ props.row.note }}</div></q-td></template>
    <template #body-cell-controls="props"><q-td :props="props" class="permission-controls-cell"><div class="column q-gutter-sm">
      <PermissionToggle v-for="control in props.row.controls" :key="control.id" :control="control" :disabled="busy || loading"
        @change="value => emit('change', props.row, control, value)" />
    </div></q-td></template>
    <template #item="props"><div class="col-12 q-pa-xs"><q-card tag="article" :aria-label="props.row.title" flat bordered>
      <q-card-section class="permission-text"><div class="text-weight-medium">{{ props.row.title }}</div>
        <div>{{ props.row.description }}</div><div v-if="!nested">{{ props.row.scope }}</div><div>{{ props.row.origin }}</div>
        <PermissionStateBadge class="q-mt-sm" :state="props.row.state" :label="t(`permissions.dashboard.states.${props.row.state}`)" />
        <div class="text-caption">{{ props.row.note }}</div>
      </q-card-section>
      <q-card-section class="column q-gutter-sm q-pt-none">
        <PermissionToggle v-for="control in props.row.controls" :key="control.id" :control="control" :disabled="busy || loading"
          @change="value => emit('change', props.row, control, value)" />
      </q-card-section>
    </q-card></div></template>
  </q-table>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import PermissionToggle from './PermissionToggle.vue'
import PermissionStateBadge from './PermissionStateBadge.vue'
import type { PermissionControl, PermissionEntry, PermissionPagination } from '../services/permissionDashboard'
const { entries, loading = false, busy = false, nested = false } = defineProps<{
  entries: PermissionEntry[]; loading?: boolean; busy?: boolean; nested?: boolean
}>()
const pagination = defineModel<PermissionPagination>('pagination', { default: () => ({ page: 1, rowsPerPage: 50 }) })
const emit = defineEmits<{ change: [entry: PermissionEntry, control: PermissionControl, value: string]; request: [request: Parameters<NonNullable<QTableProps['onRequest']>>[0]] }>()
const { t } = useI18n()
const columns = computed<QTableColumn[]>(() => [
  { name: 'title', field: 'title', label: t(nested ? 'connection.auth.colFunction' : 'permissions.question'), align: 'left' },
  ...(!nested ? [{ name: 'scope', field: 'scope', label: t('permissions.dashboard.scope'), align: 'left' as const }] : []),
  { name: 'state', field: 'state', label: t('permissions.decision'), align: 'left' },
  { name: 'controls', field: 'id', label: t('permissions.actions'), align: 'right' },
])
watch(() => entries, () => {
  if (pagination.value.rowsNumber === undefined && (pagination.value.page - 1) * pagination.value.rowsPerPage >= entries.length) pagination.value.page = 1
})
</script>

<style scoped>
.permission-text { overflow-wrap: anywhere; white-space: pre-wrap; }
.permission-controls-cell { width: 1%; min-width: 11rem; }
@media (min-width: 1024px) {
  .permission-functions-table :deep(table) { table-layout: fixed; }
  .permission-functions-table :deep(td:first-child) { overflow-wrap: anywhere; }
  .permission-functions-table :deep(th:nth-child(2)) { width: 25%; }
  .permission-functions-table :deep(th:nth-child(3)) { width: 12rem; }
}
</style>
