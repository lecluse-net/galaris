<template>
  <q-table flat bordered dense :title="t('processes.executions')" :rows="rows" :columns="columns" row-key="id"
    :pagination="pagination" :loading="loading" :grid="$q.screen.lt.md" @update:pagination="updatePagination"
    :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('processes.noRuns')" @request="emit('request', $event)">
    <template v-if="showRefresh !== false" #top-right>
      <q-icon name="refresh" color="primary" size="20px" class="run-action" role="button" tabindex="0" :aria-label="t('processes.refresh')"
        @click="emit('refresh')" @keydown.enter.prevent="emit('refresh')" @keydown.space.prevent="emit('refresh')">
        <q-tooltip>{{ t('processes.refresh') }}</q-tooltip>
      </q-icon>
    </template>
    <template #body="scope">
      <q-tr :props="scope" class="run-row" tabindex="0" :aria-label="detailLabel(scope.row)"
        @click="emit('open', scope.row.id)" @keydown.enter.self="emit('open', scope.row.id)" @keydown.space.self.prevent="emit('open', scope.row.id)">
        <q-td key="started_at" :props="scope">{{ formatStart(scope.row.started_at) }}</q-td>
        <q-td key="duration" :props="scope">{{ formatDuration(scope.row) }}</q-td>
        <q-td key="id" :props="scope"><ProcessRunReference :id="scope.row.id" /></q-td>
        <q-td key="status" :props="scope"><ProcessRunStatusBadge :status="scope.row.status" /></q-td>
        <q-td key="result" :props="scope" class="run-result-cell">
          <div class="run-result" :class="{ 'text-negative': scope.row.status === 'error' }">{{ scope.row.result_preview || t('nativeProcesses.execution.noResult') }}</div>
        </q-td>
        <q-td key="actions" :props="scope">
          <q-icon name="visibility" color="primary" size="20px" class="run-action" role="button" tabindex="0" :aria-label="t('processes.showDetails')"
            @click.stop="emit('open', scope.row.id)" @keydown.enter.stop.prevent="emit('open', scope.row.id)" @keydown.space.stop.prevent="emit('open', scope.row.id)">
            <q-tooltip>{{ t('processes.showDetails') }}</q-tooltip>
          </q-icon>
        </q-td>
      </q-tr>
    </template>
    <template #item="scope">
      <div class="col-12 q-py-xs">
        <q-card flat bordered class="run-row" tabindex="0" :aria-label="detailLabel(scope.row)"
          @click="emit('open', scope.row.id)" @keydown.enter.self="emit('open', scope.row.id)" @keydown.space.self.prevent="emit('open', scope.row.id)">
          <q-card-section class="row items-center justify-between q-gutter-sm">
            <ProcessRunReference :id="scope.row.id" /><ProcessRunStatusBadge :status="scope.row.status" />
          </q-card-section>
          <q-separator />
          <q-list dense>
            <q-item><q-item-section><q-item-label caption>{{ t('processes.startedAt') }}</q-item-label><q-item-label>{{ formatStart(scope.row.started_at) }}</q-item-label></q-item-section></q-item>
            <q-item><q-item-section><q-item-label caption>{{ t('processes.duration') }}</q-item-label><q-item-label>{{ formatDuration(scope.row) }}</q-item-label></q-item-section></q-item>
          </q-list>
          <q-separator />
          <q-card-section class="row items-start no-wrap q-gutter-sm">
            <div class="col run-result" :class="{ 'text-negative': scope.row.status === 'error' }">{{ scope.row.result_preview || t('nativeProcesses.execution.noResult') }}</div>
            <q-icon name="visibility" color="primary" size="20px" class="run-action" role="button" tabindex="0" :aria-label="t('processes.showDetails')"
              @click.stop="emit('open', scope.row.id)" @keydown.enter.stop.prevent="emit('open', scope.row.id)" @keydown.space.stop.prevent="emit('open', scope.row.id)" />
          </q-card-section>
        </q-card>
      </div>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { useRunTiming } from '../composables/useRunTiming'
import type { RunTiming } from '../runTiming'
import ProcessRunReference from './ProcessRunReference.vue'
import ProcessRunStatusBadge from './ProcessRunStatusBadge.vue'

interface RunListItem extends RunTiming { id: string; result_preview?: string; accessibleLabel?: string }
export interface RunListPagination { page: number; rowsPerPage: number; rowsNumber: number; sortBy?: string | null; descending?: boolean }
const props = withDefaults(defineProps<{ rows: RunListItem[]; pagination: RunListPagination; loading: boolean; showRefresh?: boolean }>(), { showRefresh: true })
const emit = defineEmits<{ open: [id: string]; refresh: []; request: [value: { pagination: Omit<RunListPagination, 'rowsNumber'> }]; 'update:pagination': [value: RunListPagination] }>()
const { t } = useI18n()
const { formatStart, formatDuration } = useRunTiming(() => props.rows)
const columns = computed<QTableColumn[]>(() => [
  { name: 'started_at', label: t('processes.startedAt'), field: 'started_at', align: 'left' },
  { name: 'duration', label: t('processes.duration'), field: (row: RunListItem) => formatDuration(row), align: 'left' },
  { name: 'id', label: t('nativeProcesses.runId'), field: 'id', align: 'left' },
  { name: 'status', label: t('processes.status'), field: 'status', align: 'left' },
  { name: 'result', label: t('nativeProcesses.runResult'), field: 'result_preview', align: 'left' },
  { name: 'actions', label: t('processes.actions'), field: 'id', align: 'right' },
])
function detailLabel(run: RunListItem): string { return `${t('processes.showDetails')}: ${run.accessibleLabel || run.id}` }
function updatePagination(value: Partial<RunListPagination>): void {
  emit('update:pagination', { ...props.pagination, ...value, rowsNumber: value.rowsNumber ?? props.pagination.rowsNumber })
}
</script>

<style scoped>
.run-row { cursor: pointer; }
.run-action { cursor: pointer; }
.run-action:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 3px; }
.run-row:focus-visible { outline: 2px solid var(--q-primary); outline-offset: -2px; }
.run-result-cell { white-space: normal; }
.run-result { min-width: 0; white-space: pre-line; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
</style>
