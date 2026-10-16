<template>
  <q-page class="datasets-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }">
    <PageHeader icon="data_object" :title="t('datasets.title')" :description="t('datasets.description')" />
    <q-card flat bordered class="datasets-workspace" :class="{ 'datasets-workspace--selected': selectedId }">
      <q-splitter v-model="splitter" :limits="[25, 50]" :disable="$q.screen.lt.md" class="datasets-splitter">
        <template #before>
          <nav class="dataset-list" :aria-label="t('datasets.title')">
            <div class="row items-center q-gutter-sm q-pa-md">
              <q-input v-model="query" outlined dense clearable class="col" :label="t('datasets.filter')" debounce="250" @update:model-value="search">
                <template #prepend><q-icon name="search" /></template>
              </q-input>
              <q-btn v-if="canEdit" color="primary" icon="add" :aria-label="t('datasets.new')" @click="createError = ''; creating = true">
                <q-tooltip>{{ t('datasets.new') }}</q-tooltip>
              </q-btn>
            </div>
            <q-banner v-if="error" class="q-mx-md q-mb-sm" role="alert">
              {{ error }} <q-btn flat :label="t('datasets.reload')" @click="load" />
            </q-banner>
            <q-table v-model:pagination="pagination" flat hide-header wrap-cells class="dataset-list-table"
              :rows="rows" :columns="columns" row-key="id" :loading="loading"
              :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('datasets.empty')" @request="request">
              <template #body="slot">
                <q-tr :props="slot" :class="{ 'dataset-row--selected': slot.row.id === selectedId }">
                  <q-td key="title" :props="slot" class="q-pa-none">
                    <router-link :to="`/dataset/${slot.row.id}`" class="dataset-link" :aria-label="slot.row.title" :aria-current="slot.row.id === selectedId ? 'page' : undefined">
                      <q-icon name="data_object" size="22px" class="dataset-link-icon" aria-hidden="true" />
                      <span class="dataset-link-copy">
                        <span class="dataset-link-title">{{ slot.row.title }}</span>
                        <span class="text-caption text-grey-7">{{ t('datasets.revision') }} {{ slot.row.revision }}</span>
                      </span>
                    </router-link>
                  </q-td>
                </q-tr>
              </template>
              <template #bottom>
                <div class="dataset-pagination">
                  <q-select :model-value="pagination.rowsPerPage" :options="[10, 20, 50, 100, 500]" dense outlined
                    :label="t('datasets.perPage')" class="dataset-page-size" @update:model-value="setPageSize" />
                  <div class="row items-center justify-between no-wrap">
                    <span class="text-caption">{{ t('datasets.resultRange', { from: pagination.rowsNumber ? (pagination.page - 1) * pagination.rowsPerPage + 1 : 0, to: Math.min(pagination.page * pagination.rowsPerPage, pagination.rowsNumber), total: pagination.rowsNumber }) }}</span>
                    <div class="row no-wrap">
                      <q-btn flat round dense icon="chevron_left" :aria-label="t('datasets.previousPage')" :disable="loading || pagination.page <= 1" @click="changePage(-1)" />
                      <q-btn flat round dense icon="chevron_right" :aria-label="t('datasets.nextPage')" :disable="loading || pagination.page * pagination.rowsPerPage >= pagination.rowsNumber" @click="changePage(1)" />
                    </div>
                  </div>
                </div>
              </template>
            </q-table>
          </nav>
        </template>
        <template #separator><span class="dataset-splitter-handle"><q-icon name="drag_indicator" size="16px" /></span></template>
        <template #after>
          <q-btn v-if="selectedId" flat icon="arrow_back" :label="t('datasets.backToList')" class="lt-md q-ma-sm" to="/dataset" />
          <DatasetEditor v-if="selectedId" :key="selectedId" :id="selectedId" @updated="load" @deleted="removed" />
          <div v-else class="dataset-placeholder">
            <q-icon name="data_object" size="48px" aria-hidden="true" />
            <p>{{ t('datasets.selectDataset') }}</p>
          </div>
        </template>
      </q-splitter>
    </q-card>
    <q-dialog v-model="creating">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('datasets.new') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" />
        </q-card-section>
        <q-card-section>
          <q-banner v-if="createError" role="alert" class="q-mb-md">{{ createError }}</q-banner>
          <q-input v-model="title" outlined autofocus :label="t('datasets.titleField')" :disable="creatingBusy" @keyup.enter="create" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('datasets.cancel')" />
          <q-btn color="primary" :disable="!title.trim()" :loading="creatingBusy" :label="t('datasets.new')" @click="create" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { QTableProps } from 'quasar'
import { PageHeader } from '@/core/util'
import { usePrivilegeStore } from '@/core/authorize'
import DatasetEditor from '../components/DatasetEditor.vue'
import { datasetService } from '../services/datasetService'
import type { Dataset } from '../types'

const { t } = useI18n(), route = useRoute(), router = useRouter(), auth = usePrivilegeStore()
const selectedId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const canEdit = computed(() => auth.hasPrivilege('DATASET_EDIT') || auth.hasPrivilege('DATASET_ADMIN'))
const splitter = ref(30), rows = ref<Dataset[]>([]), query = ref<string | null>(''), title = ref('')
const error = ref(''), loading = ref(false), creating = ref(false), creatingBusy = ref(false), createError = ref('')
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = computed<QTableProps['columns']>(() => [{ name: 'title', field: 'title', label: t('datasets.titleField'), align: 'left' }])
let generation = 0, mounted = true
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true
  error.value = ''
  try {
    const page = await datasetService.list(pagination.value.page, pagination.value.rowsPerPage, query.value ?? '')
    if (token !== generation) return
    const lastPage = Math.max(1, Math.ceil(page.total / pagination.value.rowsPerPage))
    if (pagination.value.page > lastPage) { pagination.value.page = lastPage; await load(); return }
    rows.value = page.items
    pagination.value.rowsNumber = page.total
  } catch { if (token === generation) error.value = t('datasets.error') }
  finally { if (token === generation) loading.value = false }
}
function request({ pagination: value }: { pagination: { page: number; rowsPerPage: number } }): void { Object.assign(pagination.value, value); void load() }
function setPageSize(value: number): void { pagination.value.rowsPerPage = value; search() }
function changePage(delta: number): void { pagination.value.page += delta; void load() }
function search(): void { pagination.value.page = 1; void load() }
async function create(): Promise<void> {
  if (!title.value.trim() || creatingBusy.value) return
  creatingBusy.value = true
  createError.value = ''
  const path = route.fullPath
  try {
    const item = await datasetService.create(title.value.trim())
    if (!mounted) return
    creating.value = false
    title.value = ''
    void load()
    if (route.fullPath === path) await router.push(`/dataset/${item.id}`)
  } catch { if (mounted) createError.value = t('datasets.error') }
  finally { if (mounted) creatingBusy.value = false }
}
async function removed(id: string): Promise<void> {
  void load()
  if (selectedId.value === id) await router.push('/dataset')
}
onMounted(load)
onBeforeUnmount(() => { mounted = false; generation++ })
</script>
<style scoped>
.datasets-workspace { overflow: hidden; }
.datasets-splitter { min-height: 540px; }
.datasets-splitter :deep(> .q-splitter__before),
.datasets-splitter :deep(> .q-splitter__after) { min-width: 0; overflow: auto; }
.datasets-splitter :deep(> .q-splitter__separator) { z-index: 2; width: 8px; background: color-mix(in srgb, var(--solaire-gray-accent) 4%, transparent); }
.datasets-splitter :deep(> .q-splitter__separator)::before { position: absolute; inset: 0 auto 0 3px; width: 2px; background: color-mix(in srgb, var(--solaire-gray-accent) 28%, transparent); content: ""; transition: background-color .15s ease; }
.datasets-splitter :deep(> .q-splitter__separator:hover)::before,
.datasets-splitter :deep(> .q-splitter__separator:focus-within)::before,
.datasets-splitter.q-splitter--active :deep(> .q-splitter__separator)::before { background: var(--q-primary); }
.dataset-list { min-width: 0; }
.dataset-list-table :deep(.q-table__middle) { overflow: visible; }
.dataset-list-table :deep(td) { padding: 0; }
.dataset-link { display: flex; align-items: center; gap: 12px; padding: 14px 16px; color: inherit; text-decoration: none; }
.dataset-link:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: -2px; }
.dataset-link-icon { flex-shrink: 0; color: var(--solaire-blue-accent); }
.dataset-link-copy { display: flex; flex-direction: column; min-width: 0; }
.dataset-link-title { overflow-wrap: anywhere; font-weight: 500; }
.dataset-row--selected { background: var(--solaire-blue-light); box-shadow: inset 3px 0 var(--solaire-blue-accent); }
:global(body.body--dark) .dataset-row--selected { background: var(--solaire-blue-dark); }
.dataset-pagination { display: flex; flex-direction: column; gap: 8px; width: 100%; padding: 8px 0; }
.dataset-page-size { max-width: 190px; }
.dataset-splitter-handle { position: absolute; top: 50%; left: 50%; z-index: 1; display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; transform: translate(-50%, -50%); border: 1px solid color-mix(in srgb, var(--solaire-gray-accent) 28%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--solaire-gray-light); box-shadow: 0 2px 8px color-mix(in srgb, var(--solaire-gray-accent) 24%, transparent); }
:global(body.body--dark) .dataset-splitter-handle { background: var(--solaire-gray-dark); }
.dataset-placeholder { display: flex; min-height: 420px; height: 100%; flex-direction: column; align-items: center; justify-content: center; gap: 16px; padding: 24px; text-align: center; color: var(--solaire-gray-accent); }
@media (min-width: 1024px) {
  .datasets-page { display: flex; flex-direction: column; overflow: hidden; padding-bottom: 0; }
  .datasets-page > :not(.datasets-workspace) { flex-shrink: 0; }
  .datasets-workspace { flex: 1; min-height: 0; }
  .datasets-splitter { height: 100%; min-height: 0; }
}
@media (max-width: 1023.98px) {
  .datasets-splitter { min-height: 0; }
  .datasets-splitter :deep(> .q-splitter__before) { width: 100% !important; }
  .datasets-splitter :deep(> .q-splitter__separator),
  .datasets-splitter :deep(> .q-splitter__after) { display: none; }
  .datasets-workspace--selected .datasets-splitter :deep(> .q-splitter__before) { display: none; }
  .datasets-workspace--selected .datasets-splitter :deep(> .q-splitter__after) { display: block; width: 100% !important; }
}
</style>
