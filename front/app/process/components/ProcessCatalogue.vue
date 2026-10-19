<template>
  <div>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <q-table
      class="process-table" :rows="rows" :columns="columns" :loading="loading"
      row-key="key" :grid="$q.screen.lt.md" v-model:pagination="pagination"
      v-model:expanded="expanded"
      :rows-per-page-options="[10, 20, 50, 100, 500]" @request="request"
    >
      <template #no-data>
        <div v-if="!loading && !error" class="column items-start q-gutter-sm q-pa-sm" role="status">
          <div>{{ t(hasFilters ? 'processes.catalogue.noMatches' : 'processes.catalogue.empty') }}</div>
          <q-btn v-if="hasFilters" outline :label="t('processes.catalogue.clearFilters')" @click="clearFilters" />
        </div>
      </template>
      <template #body="scope">
        <q-tr :props="scope" class="process-row" tabindex="0"
          :aria-label="scope.row.label" @click="router.push(scope.row.editorUrl)"
          @keydown.enter.self="router.push(scope.row.editorUrl)" @keydown.space.self.prevent="router.push(scope.row.editorUrl)">
          <q-td key="expand" :props="scope" auto-width @click.stop="scope.expand = !scope.expand">
            <q-btn flat round dense :icon="scope.expand ? 'expand_less' : 'expand_more'"
              :aria-expanded="scope.expand" :aria-label="t('processes.executions') + ': ' + scope.row.label"
              @click.stop="scope.expand = !scope.expand" />
          </q-td>
          <q-td key="label" :props="scope">
            <span class="text-weight-medium">{{ scope.row.label }}</span>
            <q-badge v-if="scope.row.archived" outline class="process-archive q-ml-sm">{{ t('nativeProcesses.archived') }}</q-badge>
          </q-td>
          <q-td key="tool" :props="scope">{{ scope.row.tool }}</q-td>
          <q-td key="agent" :props="scope">{{ scope.row.agent }}</q-td>
          <q-td key="description" :props="scope" class="process-description">{{ scope.row.description }}</q-td>
          <q-td key="monitoring" :props="scope"><ProcessCatalogueStatus :item="scope.row" /></q-td>
          <q-td key="actions" :props="scope">
            <router-link :to="scope.row.editorUrl" class="process-action" :aria-label="t('processes.edit') + ': ' + scope.row.label" @click.stop>
              <q-icon name="edit" color="primary" size="20px" />
              <q-tooltip>{{ t('processes.edit') }}</q-tooltip>
            </router-link>
          </q-td>
        </q-tr>
        <q-tr v-if="scope.expand" :props="scope" :key="`${scope.row.key}-runs`">
          <q-td colspan="100%" class="process-runs-cell">
            <NativeRunsTable v-if="scope.row.code" :code="scope.row.code" :navigation-key="scope.row.key" :refresh-revision="runsRevision" />
            <ExternalProcessRuns v-else :definition="scope.row" :revision="runsRevision" @open-run="emit('openRun', $event)" />
          </q-td>
        </q-tr>
      </template>
      <template #item="scope">
        <div class="col-12 q-py-xs">
          <q-card flat bordered>
            <q-card-section class="process-row row items-start no-wrap q-gutter-sm" tabindex="0" role="button"
              :aria-label="scope.row.label"
              @click="router.push(scope.row.editorUrl)" @keydown.enter.self="router.push(scope.row.editorUrl)"
              @keydown.space.self.prevent="router.push(scope.row.editorUrl)">
              <div class="self-stretch" @click.stop="scope.expand = !scope.expand">
                <q-btn flat round dense :icon="scope.expand ? 'expand_less' : 'expand_more'"
                  :aria-expanded="scope.expand" :aria-label="t('processes.executions') + ': ' + scope.row.label"
                  @click.stop="scope.expand = !scope.expand" />
              </div>
              <div class="col process-identity">
                <div class="text-subtitle2">{{ scope.row.label }}</div>
                <q-badge v-if="scope.row.archived" outline class="process-archive">{{ t('nativeProcesses.archived') }}</q-badge>
                <div class="text-caption q-mt-sm">{{ scope.row.tool }}<span v-if="scope.row.agent"> · {{ scope.row.agent }}</span></div>
                <div v-if="scope.row.description" class="process-description q-mt-sm">{{ scope.row.description }}</div>
                <ProcessCatalogueStatus class="q-mt-sm" :item="scope.row" />
              </div>
              <router-link :to="scope.row.editorUrl" class="process-action" :aria-label="t('processes.edit') + ': ' + scope.row.label" @click.stop>
                <q-icon name="edit" color="primary" size="20px" />
                <q-tooltip>{{ t('processes.edit') }}</q-tooltip>
              </router-link>
            </q-card-section>
            <template v-if="scope.expand">
              <q-separator />
              <q-card-section class="process-runs-cell">
                <NativeRunsTable v-if="scope.row.code" :code="scope.row.code" :navigation-key="scope.row.key" :refresh-revision="runsRevision" />
                <ExternalProcessRuns v-else :definition="scope.row" :revision="runsRevision" @open-run="emit('openRun', $event)" />
              </q-card-section>
            </template>
          </q-card>
        </div>
      </template>
    </q-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import type { QTableColumn } from 'quasar'
import { catalogueService, type CatalogueItem, type CatalogueSort } from '../services/catalogueService'
import type { ProcessRun } from '../services/processService'
import NativeRunsTable from './NativeRunsTable.vue'
import ExternalProcessRuns from './ExternalProcessRuns.vue'
import { useProcessCatalogueStore } from '../stores/catalogueStore'
import ProcessCatalogueStatus from './ProcessCatalogueStatus.vue'
import { useProcessRunRefresh } from '../composables/useProcessRunRefresh'

defineProps<{
  runsRevision: number
}>()
const emit = defineEmits<{ openRun: [run: ProcessRun] }>()
const { t } = useI18n()
const router = useRouter()
const items = ref<CatalogueItem[]>([])
const loading = ref(false), error = ref(false)
const view = useProcessCatalogueStore()
const { pagination, expanded } = storeToRefs(view)
let generation = 0
const rows = computed(() => items.value.map(item => ({ ...item, key: `${item.code ? 'native' : 'external'}-${item.id}`,
  editorUrl: item.code ? `/process/internal/${item.code}` : `/process/external/${item.id}` })))
const hasFilters = computed(() => !!view.filter || view.agentFilter !== null || view.kind !== 'all' || view.archive !== 'active')
function clearFilters(): void { view.$patch({ filter: '', agentFilter: null, kind: 'all', archive: 'active' }) }
const columns = computed<QTableColumn[]>(() => [
  { name: 'expand', label: '', field: 'key', align: 'left' },
  { name: 'label', label: t('processes.label'), field: 'label', align: 'left', sortable: true },
  { name: 'tool', label: t('processes.tool'), field: 'tool', align: 'left', sortable: true },
  { name: 'agent', label: t('processes.agent'), field: 'agent', align: 'left', sortable: true },
  { name: 'description', label: t('processes.description'), field: 'description', align: 'left', sortable: true },
  { name: 'monitoring', label: t('processes.catalogue.monitoring'), field: 'latest_run', align: 'left' },
  { name: 'actions', label: t('processes.actions'), field: 'key', align: 'right' },
])
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true; error.value = false
  try {
    const sortBy = pagination.value.sortBy
    const sort: CatalogueSort = sortBy === 'tool' || sortBy === 'agent' || sortBy === 'description' ? sortBy : 'label'
    const result = await catalogueService.list({ page: pagination.value.page, page_size: pagination.value.rowsPerPage,
      sort_by: sort, descending: pagination.value.descending ?? false, search: view.filter ?? '',
      kind: view.kind, archive: view.archive, agent_id: view.agentFilter })
    if (token !== generation) return
    items.value = result.items
    pagination.value = { ...pagination.value, page: result.page, rowsPerPage: result.page_size, rowsNumber: result.total }
  } catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
function request(value: { pagination: { page: number; rowsPerPage: number; sortBy?: string | null; descending?: boolean } }): void {
  pagination.value = { ...pagination.value, ...value.pagination }; void load()
}
watch(() => [view.filter, view.agentFilter, view.kind, view.archive, view.sessionRevision] as const, (current, previous) => {
  // A debounced input flushes on blur. Keep row targets stable through that click;
  // only a session change must immediately discard the previous resource data.
  if (current[4] !== previous[4]) items.value = []
  pagination.value.page = 1; void load()
})
useProcessRunRefresh(load, loading)
onMounted(load)
onBeforeUnmount(() => { generation++ })
defineExpose({ reload: load })
</script>

<style scoped>
.process-row { cursor: pointer; }
.process-action { display: inline-flex; text-decoration: none; }
.process-action:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 3px; }
.process-row:focus-visible { outline: 2px solid var(--q-primary); outline-offset: -2px; }
.process-identity { min-width: 0; overflow-wrap: anywhere; }
.process-description { white-space: normal; overflow-wrap: anywhere; max-width: 480px; }
.process-archive { color: inherit; }
.process-runs-cell { padding: 16px; white-space: normal; background: var(--solaire-gray-light); }
body.body--dark .process-runs-cell { background: var(--solaire-gray-dark); }
@media (max-width: 1023px) { .process-runs-cell { padding: 8px; } }
</style>
