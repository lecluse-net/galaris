<template>
  <q-page class="datasets-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }">
    <PageHeader icon="data_object" :title="t('datasets.title')" :description="t('datasets.description')" />
    <q-card flat bordered class="datasets-workspace">
      <q-splitter v-model="splitter" :limits="[20, 55]" :disable="$q.screen.lt.md" class="datasets-splitter"
        :class="{ 'datasets-splitter--selected': selectedId }">
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
            <AgentSelect v-model="ownerAgentId" :options="agentOptions" :load-agents="false" outlined dense
              class="q-mx-md q-mb-md" :label="t('datasets.agentFilter')" :loading="agentsLoading" :error="agentsError"
              :error-message="agentsError ? t('datasets.agentFilterError') : undefined" hide-bottom-space
              @popup-show="loadAgents" @update:model-value="search" />
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
                        <span class="dataset-link-details text-caption text-grey-7">
                          <time v-if="slot.row.updated_at || slot.row.created_at" :datetime="slot.row.updated_at ?? slot.row.created_at"
                            :title="t('datasets.lastModified', { date: formatDate(slot.row.updated_at ?? slot.row.created_at) })">
                            {{ formatDate(slot.row.updated_at ?? slot.row.created_at) }}
                          </time>
                          <span>{{ t('datasets.revision') }} {{ slot.row.revision }}</span>
                        </span>
                      </span>
                    </router-link>
                  </q-td>
                </q-tr>
              </template>
              <template #bottom>
                <div class="dataset-pagination row items-center justify-center q-pa-xs">
                  <span class="text-caption">{{ t('datasets.resultRange', { from: rows.length ? (pagination.page - 1) * pagination.rowsPerPage + 1 : 0, to: rows.length ? (pagination.page - 1) * pagination.rowsPerPage + rows.length : 0, total: pagination.rowsNumber }) }}</span>
                  <q-select :model-value="pagination.rowsPerPage" :options="[10, 20, 50, 100, 500]" dense borderless
                    :aria-label="t('datasets.perPage')" :disable="loading" @update:model-value="setPageSize">
                    <template #selected>{{ t('datasets.itemsPerPage', { count: pagination.rowsPerPage }) }}</template>
                  </q-select>
                  <q-pagination :model-value="pagination.page" :max="Math.max(1, Math.ceil(pagination.rowsNumber / pagination.rowsPerPage))"
                    :max-pages="3" direction-links boundary-numbers size="sm" :disable="loading" @update:model-value="changePage" />
                </div>
              </template>
            </q-table>
          </nav>
        </template>
        <template #separator>
          <span class="dataset-splitter-handle" role="separator" tabindex="0" aria-orientation="vertical"
            :aria-label="t('datasets.resizeList')" :aria-valuenow="splitter" :aria-valuemin="20" :aria-valuemax="55"
            @keydown="resizeList">
            <q-icon name="drag_indicator" size="16px" aria-hidden="true" />
          </span>
        </template>
        <template #after>
          <template v-if="selectedId">
            <div class="q-pa-sm">
              <q-btn outline no-caps icon="arrow_back" :label="t('datasets.backToList')" to="/dataset" />
            </div>
            <DatasetEditor :key="selectedId" :id="selectedId" @updated="load" @deleted="removed" />
          </template>
          <div v-else class="dataset-placeholder text-grey-7">
            <q-icon name="data_object" size="48px" aria-hidden="true" />
            <div>{{ t('datasets.selectDataset') }}</div>
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
import { AgentSelect, getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import DatasetEditor from '../components/DatasetEditor.vue'
import { datasetService } from '../services/datasetService'
import type { Dataset } from '../types'

const { t, locale } = useI18n(), route = useRoute(), router = useRouter(), auth = usePrivilegeStore()
const selectedId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const splitter = ref(30)
const canEdit = computed(() => auth.hasPrivilege('DATASET_EDIT') || auth.hasPrivilege('DATASET_ADMIN'))
const rows = ref<Dataset[]>([]), query = ref<string | null>(''), title = ref('')
const error = ref(''), loading = ref(false), creating = ref(false), creatingBusy = ref(false), createError = ref('')
const ownerAgentId = ref<number | null>(null), agents = ref<AgentSelectionOption[]>([]), agentsLoading = ref(false), agentsError = ref(false)
const agentOptions = computed(() => [{ label: t('datasets.allAgents'), value: null }, ...agents.value.map(agent => ({ label: agent.label, value: agent.id, hasAvatar: agent.has_avatar }))])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const columns = computed<QTableProps['columns']>(() => [{ name: 'title', field: 'title', label: t('datasets.titleField'), align: 'left' }])
let generation = 0, mounted = true
function resizeList(event: KeyboardEvent): void {
  const values: Record<string, number> = { ArrowLeft: splitter.value - 2, ArrowRight: splitter.value + 2, Home: 20, End: 55 }
  const value = values[event.key]
  if (value === undefined) return
  event.preventDefault(); splitter.value = Math.min(55, Math.max(20, value))
}
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true
  error.value = ''
  try {
    const page = await datasetService.list(pagination.value.page, pagination.value.rowsPerPage, query.value ?? '', ownerAgentId.value)
    if (token !== generation) return
    const lastPage = Math.max(1, Math.ceil(page.total / pagination.value.rowsPerPage))
    if (pagination.value.page > lastPage) { pagination.value.page = lastPage; await load(); return }
    rows.value = page.items
    pagination.value.rowsNumber = page.total
  } catch { if (token === generation) error.value = t('datasets.error') }
  finally { if (token === generation) loading.value = false }
}
async function loadAgents(): Promise<void> {
  if (agentsLoading.value) return
  agentsLoading.value = true
  agentsError.value = false
  try {
    const options = await getAgentSelection('management')
    if (mounted) agents.value = options
  } catch { if (mounted) { agents.value = []; agentsError.value = true } }
  finally { if (mounted) agentsLoading.value = false }
}
function request({ pagination: value }: { pagination: { page: number; rowsPerPage: number } }): void { Object.assign(pagination.value, value); void load() }
function setPageSize(value: number): void { pagination.value.rowsPerPage = value; search() }
function changePage(page: number): void { pagination.value.page = page; void load() }
function search(): void { pagination.value.page = 1; void load() }
function formatDate(value: string): string { return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) }
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
onMounted(() => { void load(); void loadAgents() })
onBeforeUnmount(() => { mounted = false; generation++ })
</script>
<style scoped>
.datasets-workspace { overflow: hidden; }
.datasets-splitter { min-height: min(760px, calc(100vh - 260px)); }
.datasets-splitter :deep(> .q-splitter__after) { overflow: auto; }
.datasets-splitter :deep(> .q-splitter__separator) { background: color-mix(in srgb, var(--q-dark) 10%, transparent); }
.dataset-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.dataset-splitter-handle:hover, .dataset-splitter-handle:focus-visible { color: var(--solaire-blue-accent); }
.dataset-splitter-handle:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
:global(body.body--dark) .dataset-splitter-handle { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
.dataset-placeholder { height: 100%; min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 16px; }
.dataset-list { min-width: 0; }
.dataset-list-table :deep(.q-table__middle) { overflow: auto; }
.dataset-list-table :deep(td) { padding: 0; }
.dataset-link { display: flex; align-items: center; gap: 12px; padding: 14px 16px; color: inherit; text-decoration: none; }
.dataset-link:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: -2px; }
.dataset-link-icon { flex-shrink: 0; color: var(--solaire-blue-accent); }
.dataset-link-copy { display: flex; flex-direction: column; min-width: 0; }
.dataset-link-title { overflow-wrap: anywhere; font-weight: 500; }
.dataset-link-details { display: flex; flex-wrap: wrap; gap: 0 12px; }
.dataset-link-details > * { white-space: nowrap; }
.dataset-row--selected { background: var(--solaire-blue-light); box-shadow: inset 3px 0 var(--solaire-blue-accent); }
:global(body.body--dark) .dataset-row--selected { background: var(--solaire-blue-dark); }
.dataset-pagination { flex-shrink: 0; gap: 4px 12px; width: 100%; }
@media (min-width: 1024px) {
  .datasets-page { display: flex; flex-direction: column; overflow: hidden; padding-bottom: 0; }
  .datasets-page > :not(.datasets-workspace) { flex-shrink: 0; }
  .datasets-workspace { flex: 1; min-height: 0; }
  .datasets-splitter { height: 100%; min-height: 0; }
  .datasets-splitter :deep(> .q-splitter__before),
  .datasets-splitter :deep(> .q-splitter__after) { min-height: 0; }
  .dataset-list { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .dataset-list-table { flex: 1; min-height: 0; }
}
@media (max-width: 1023.98px) {
  .datasets-splitter :deep(> .q-splitter__before) { width: 100% !important; }
  .datasets-splitter :deep(> .q-splitter__separator),
  .datasets-splitter :deep(> .q-splitter__after) { display: none; }
  .datasets-splitter--selected :deep(> .q-splitter__before) { display: none; }
  .datasets-splitter--selected :deep(> .q-splitter__after) { display: block; width: 100% !important; }
}
</style>
