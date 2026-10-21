<template>
  <q-splitter v-model="split" horizontal :limits="[15, 65]" class="dataset-navigation">
    <template #before>
      <div class="q-pa-sm">
        <q-banner v-if="tagError" dense role="alert">{{ t('datasets.library.tagError') }}<q-btn outline :label="t('datasets.reload')" @click="loadTags" /></q-banner>
        <q-tree v-model:expanded="expanded" :nodes="tree" node-key="id" dense no-transition>
          <template #default-header="{ node }">
            <div class="full-width" :class="{ 'dataset-drop': dropTarget === node.id }"
              @dragstart.stop="startDrag($event, 'tag', node.id)" @dragend="clearDrag"
              @dragover.stop="overFolder($event, node.tag)" @drop.prevent.stop="drop">
              <DatasetFolderRow :tag="node.tag" :selected="expanded.includes(node.id)" :busy="busy" :can-create="canEdit" :save="saveFolder" :create="createFolder"
                :rename-on-create="renameId === node.id" @renamed="renameId = null" @create-document="emit('create', node.id)"
                @browse="browse(node.tag)" @delete="deleteFolder(node.tag)" @confirm-delete="deleting = node.tag"
                @sort="sortFolder(node.id, $event)" @expand="expandFolder(node.id, true)" @collapse="expandFolder(node.id, false)" />
            </div>
          </template>
          <template #header-dataset="{ node }">
            <DatasetLibraryRow compact class="full-width" :class="{ 'dataset-drop': dropTarget === node.id }" :item="node.item" :selected-id="selectedId" :busy="busy"
              @action="rowAction" @drag="(event, id) => startDrag(event, 'dataset', id)" @dragend="clearDrag"
              @dragover="(event, id) => overDataset(event, id, node.folderId)" @drop="drop" />
          </template>
          <template #header-status="{ node }">
            <q-spinner v-if="branchLoading[node.folderId]" size="16px" />
            <q-banner v-else-if="branchErrors[node.folderId]" dense role="alert">{{ t('datasets.library.error') }}<q-btn outline dense :label="t('datasets.reload')" @click.stop="loadBranch(node.folderId)" /></q-banner>
            <q-btn v-else-if="(branches[node.folderId]?.items.length ?? 0) < (branches[node.folderId]?.total ?? 0)" outline dense :label="t('datasets.library.openFolderAction')" @click.stop="browse(node.tag)" />
            <span v-else class="text-caption">{{ t('datasets.library.emptyFolder') }}</span>
          </template>
        </q-tree>
        <div v-if="!folders.length && !tagError" class="text-caption q-pa-sm">{{ t('datasets.library.emptyTags') }}</div>
        <div class="row justify-end" :class="{ 'dataset-drop': dropTarget === 'root' }" @dragover="overRoot" @drop.prevent="drop">
          <q-btn flat round dense icon="add" :disable="busy" :aria-label="t('datasets.library.newTag')" @click="createFolder(t('datasets.library.newFolderName'), null)" />
        </div>
      </div>
    </template>
    <template #separator>
      <LibrarySplitterHandle horizontal role="separator" tabindex="0" aria-orientation="horizontal" :aria-label="t('datasets.library.resize')"
        :aria-valuenow="split" aria-valuemin="15" aria-valuemax="65" @keydown.up.prevent="split = Math.max(15, split - 5)" @keydown.down.prevent="split = Math.min(65, split + 5)" />
    </template>
    <template #after>
      <div class="dataset-list-panel" :class="{ 'dataset-drop': dropTarget === 'root' }" @dragover="overRoot" @drop.prevent="drop">
        <div class="row no-wrap items-center q-pa-sm q-gutter-xs">
          <q-input v-model="query" dense outlined clearable debounce="350" class="col" :label="t('datasets.filter')" @update:model-value="search">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <DatasetLibraryFilters v-model="filters" v-model:only-unclassified="onlyUnclassified" :owners="owners" :keywords="keywords" :current-user-id="currentUserId" />
          <q-btn flat round dense icon="filter_alt_off" :disable="!hasFilters" :aria-label="t('datasets.library.reset')" @click="reset" />
          <q-btn v-if="canEdit" flat round dense icon="add" :aria-label="t('datasets.new')" @click="emit('create', activeFolder?.id)" />
        </div>
        <div v-if="activeFolder" class="row items-center q-px-sm"><span class="col ellipsis">{{ activeFolder.name }}</span>
          <q-btn flat round dense icon="close" :aria-label="t('datasets.backToList')" @click="activeFolder = null; search()" />
        </div>
        <q-banner v-if="loadError" dense role="alert">{{ t('datasets.error') }}<q-btn outline :label="t('datasets.reload')" @click="load" /></q-banner>
        <q-banner v-if="facetsError" dense role="alert">{{ t('datasets.library.error') }}<q-btn outline :label="t('datasets.reload')" @click="loadFacets" /></q-banner>
        <q-linear-progress v-if="loading" indeterminate />
        <q-list separator class="dataset-list-scroll" :aria-busy="loading" :aria-label="t(onlyUnclassified ? 'datasets.library.orphans' : 'datasets.library.all')">
          <DatasetLibraryRow v-for="item in rows" :key="item.id" :item="item" :selected-id="selectedId" :busy="busy"
            :class="{ 'dataset-drop': dropTarget === `dataset:${item.id}` }" @action="rowAction"
            @drag="(event, id) => startDrag(event, 'dataset', id)" @dragend="clearDrag"
            @dragover="(event, id) => overDataset(event, id, activeFolder?.id ?? null)" @drop="drop" />
          <div v-if="!loading && !loadError && !rows.length" class="q-pa-md text-caption">{{ t('datasets.empty') }}</div>
        </q-list>
        <div class="dataset-pagination row items-center justify-center q-pa-xs">
          <span class="text-caption">{{ t('datasets.resultRange', { from: rows.length ? (page - 1) * pageSize + 1 : 0, to: rows.length ? (page - 1) * pageSize + rows.length : 0, total }) }}</span>
          <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" dense borderless :aria-label="t('datasets.perPage')" :disable="loading">
            <template #selected>{{ t('datasets.itemsPerPage', { count: pageSize }) }}</template>
          </q-select>
          <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="3" direction-links boundary-numbers size="sm" :disable="loading" />
        </div>
      </div>
    </template>
  </q-splitter>
  <q-dialog :model-value="!!deleting" @update:model-value="!$event && (deleting = null)">
    <q-card class="galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center"><span class="text-h6">{{ t('datasets.library.deleteTag') }}</span><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" /></q-card-section>
      <q-card-section>{{ t('datasets.library.deleteExplanation', { name: deleting?.name }) }}</q-card-section>
      <q-card-actions align="right"><q-btn v-close-popup outline :label="t('datasets.cancel')" /><q-btn color="negative" :loading="busy" :label="t('datasets.library.deleteTag')" @click="deleting && deleteFolder(deleting, true)" /></q-card-actions>
    </q-card>
  </q-dialog>
  <q-dialog :model-value="!!moving" @update:model-value="!$event && (moving = null)">
    <q-card class="galaris-dialog-card" style="width: 440px; max-width: 95vw">
      <q-card-section class="galaris-dialog-title row items-center"><span class="text-h6">{{ t('datasets.library.moveToTag') }}</span><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" /></q-card-section>
      <q-card-section><q-select v-model="destination" outlined emit-value map-options :options="folderOptions" :label="t('datasets.library.parent')" /></q-card-section>
      <q-card-actions align="right"><q-btn v-close-popup outline :label="t('datasets.cancel')" /><q-btn color="primary" :loading="busy" :label="t('datasets.apply')" @click="moveSelected" /></q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { LibrarySplitterHandle } from '@/core/util'
import type { OwnerOption } from '@/app/share'
import { datasetService as service } from '../services/datasetService'
import { defaultLibraryFilters, libraryRequestFilters } from '../libraryFilterState'
import type { Dataset, DatasetFolder, DatasetMove, Page } from '../types'
import DatasetLibraryFilters from './DatasetLibraryFilters.vue'
import DatasetFolderRow from './DatasetFolderRow.vue'
import DatasetLibraryRow from './DatasetLibraryRow.vue'
defineProps<{ selectedId: string }>()
const emit = defineEmits<{ create: [folderId?: string]; action: [item: Dataset, action: 'rename' | 'delete'] }>()
const { t } = useI18n(), $q = useQuasar(), auth = usePrivilegeStore()
const canEdit = computed(() => auth.hasPrivilege('DATASET_EDIT') || auth.hasPrivilege('DATASET_ADMIN'))
const split = ref(35), folders = ref<DatasetFolder[]>([]), expanded = ref<string[]>([]), renameId = ref<string | null>(null)
const branches = ref<Record<string, Page<Dataset>>>({}), branchErrors = ref<Record<string, boolean>>({}), branchLoading = ref<Record<string, boolean>>({})
const rows = ref<Dataset[]>([]), query = ref<string | null>(''), filters = ref(defaultLibraryFilters()), onlyUnclassified = ref(true)
const owners = ref<OwnerOption[]>([]), keywords = ref<string[]>([]), currentUserId = ref<number>(), facetsError = ref(false)
const page = ref(1), pageSize = ref(50), total = ref(0), loading = ref(false), loadError = ref(false), tagError = ref(false), busy = ref(false)
const activeFolder = ref<DatasetFolder | null>(null), deleting = ref<DatasetFolder | null>(null), moving = ref<Dataset | null>(null), destination = ref<string | null>(null)
const dropTarget = ref<string | null>(null)
let drag: { kind: 'tag' | 'dataset'; id: string } | null = null, pendingMove: DatasetMove | null = null
let generation = 0, epoch = 0, disposed = false, tagGeneration = 0, facetsGeneration = 0
let authSession = sessionGeneration()
const branchGenerations = new Map<string, number>()
interface TreeNode { id: string; label: string; tag: DatasetFolder; folderId: string; header?: string; item?: Dataset; children?: TreeNode[] }
const tree = computed(() => {
  const nodes = new Map<string, TreeNode>(folders.value.map(tag => [tag.id, { id: tag.id, label: tag.name, tag, folderId: tag.id, children: [] }]))
  const roots: TreeNode[] = []
  for (const tag of folders.value) { const node = nodes.get(tag.id)!; const parent = tag.parent_id ? nodes.get(tag.parent_id) : undefined; (parent?.children ?? roots).push(node) }
  const compare = (a: TreeNode, b: TreeNode) => folders.value.find(tag => tag.id === a.id)!.position - folders.value.find(tag => tag.id === b.id)!.position || a.label.localeCompare(b.label)
  roots.sort(compare)
  for (const node of nodes.values()) {
    node.children!.sort(compare)
    const branch = branches.value[node.id]
    node.children!.push(...(branch?.items ?? []).map(item => ({ id: `dataset:${node.id}:${item.id}`, label: item.title, tag: node.tag, folderId: node.id, item, header: 'dataset' })))
    if (!branch || branchErrors.value[node.id] || !node.children!.length || branch.items.length < branch.total) node.children!.push({ id: `status:${node.id}`, label: '', tag: node.tag, folderId: node.id, header: 'status' })
  }
  return roots
})
const hasFilters = computed(() => activeFolder.value || query.value || !onlyUnclassified.value || JSON.stringify(filters.value) !== JSON.stringify(defaultLibraryFilters()))
const folderOptions = computed(() => [{ label: t('datasets.library.unclassified'), value: null }, ...folders.value.map(folder => {
  const names = [folder.name]; let parent = folders.value.find(tag => tag.id === folder.parent_id)
  while (parent) { names.unshift(parent.name); parent = folders.value.find(tag => tag.id === parent?.parent_id) }
  return { label: names.join(' / '), value: folder.id }
})])
async function load(): Promise<void> {
  const token = ++generation; loading.value = true; loadError.value = false
  try {
    const result = await service.list(page.value, pageSize.value, query.value ?? '', null, { ...libraryRequestFilters(filters.value),
      classification: activeFolder.value ? 'all' : onlyUnclassified.value ? 'unclassified' : 'all', tag_id: activeFolder.value?.id })
    if (disposed || token !== generation) return
    const last = Math.max(1, Math.ceil(result.total / pageSize.value))
    if (page.value > last) { page.value = last; return }
    rows.value = result.items; total.value = result.total
  } catch { if (!disposed && token === generation) { loadError.value = true; rows.value = []; total.value = 0 } }
  finally { if (!disposed && token === generation) loading.value = false }
}
async function loadTags(): Promise<void> {
  const token = ++tagGeneration
  try { const result = await service.folders(); if (!disposed && token === tagGeneration) { folders.value = result; tagError.value = false; if (activeFolder.value) activeFolder.value = result.find(tag => tag.id === activeFolder.value?.id) ?? null } }
  catch { if (!disposed && token === tagGeneration) tagError.value = true }
}
async function loadFacets(): Promise<void> {
  const token = ++facetsGeneration
  try { const result = await service.facets(); if (!disposed && token === facetsGeneration) { owners.value = result.owners.filter((owner): owner is typeof owner & OwnerOption => owner.kind !== 'team'); keywords.value = result.keywords; currentUserId.value = result.current_user_id; facetsError.value = false } }
  catch { if (!disposed && token === facetsGeneration) facetsError.value = true }
}
async function loadBranch(id: string): Promise<void> {
  const token = (branchGenerations.get(id) ?? 0) + 1, session = epoch; branchGenerations.set(id, token); branchLoading.value[id] = true; branchErrors.value[id] = false
  try { const result = await service.list(1, 500, '', null, { tag_id: id, sort_by: 'position', sort_desc: false }); if (!disposed && session === epoch && token === branchGenerations.get(id)) branches.value[id] = result }
  catch { if (!disposed && session === epoch && token === branchGenerations.get(id)) { branchErrors.value[id] = true; delete branches.value[id] } }
  finally { if (!disposed && session === epoch && token === branchGenerations.get(id)) branchLoading.value[id] = false }
}
function search(): void { if (page.value === 1) void load(); else page.value = 1 }
function reset(): void { query.value = ''; filters.value = defaultLibraryFilters(); onlyUnclassified.value = true; activeFolder.value = null; search() }
function browse(folder: DatasetFolder): void { activeFolder.value = folder; search() }
async function refresh(): Promise<void> { await loadTags(); if (disposed) return; await Promise.all([load(), loadFacets(), ...expanded.value.filter(id => folders.value.some(tag => tag.id === id)).map(loadBranch)]) }
async function mutate(action: () => Promise<void>): Promise<boolean> {
  if (busy.value) return false
  const session = epoch; busy.value = true
  try { await action(); if (disposed || session !== epoch) return false; await refresh(); return !disposed && session === epoch }
  catch { if (!disposed && session === epoch) $q.notify({ type: 'negative', message: t('datasets.library.error') }); return false }
  finally { if (!disposed && session === epoch) busy.value = false }
}
async function saveFolder(folder: DatasetFolder): Promise<boolean> { return mutate(() => service.saveFolder(folder)) }
async function createFolder(name: string, parent: string | null, after?: string): Promise<boolean> {
  let created: DatasetFolder | undefined
  const session = epoch
  const saved = await mutate(async () => {
    created = await service.createFolder(name, parent)
    if (after && !disposed && session === epoch) {
      try { await service.move({ kind: 'tag', identity: created.id, parent_id: parent, anchor_kind: 'tag', anchor_id: after, after: true }) }
      catch { if (!disposed && session === epoch) $q.notify({ type: 'warning', message: t('datasets.libraryPositionError') }) }
    }
  })
  if (saved && created) { renameId.value = created.id; if (parent && !expanded.value.includes(parent)) expanded.value = [...expanded.value, parent] }
  return saved
}
async function deleteFolder(folder: DatasetFolder, confirmed = false): Promise<void> {
  let deleted = false
  if (await mutate(async () => { deleted = (await service.removeFolder(folder.id, confirmed)).deleted })) deleting.value = deleted ? null : folder
}
async function sortFolder(id: string, descending: boolean): Promise<void> { await mutate(() => service.sortFolder(id, descending)) }
function isDescendant(id: string, ancestor: string): boolean {
  let folder = folders.value.find(tag => tag.id === id)
  while (folder) { if (folder.id === ancestor) return true; folder = folders.value.find(tag => tag.id === folder?.parent_id) }
  return false
}
function expandFolder(id: string, open: boolean): void { const ids = folders.value.filter(tag => isDescendant(tag.id, id)).map(tag => tag.id); expanded.value = open ? [...new Set([...expanded.value, ...ids])] : expanded.value.filter(id => !ids.includes(id)) }
function rowAction(item: Dataset, action: 'rename' | 'delete' | 'move'): void { if (action === 'move') { moving.value = item; destination.value = item.tag_ids?.[0] ?? null } else emit('action', item, action) }
async function moveSelected(): Promise<void> { const identity = moving.value?.id, parent_id = destination.value; if (identity && await mutate(() => service.move({ kind: 'dataset', identity, parent_id }))) moving.value = null }
function clearDrag(): void { drag = null; pendingMove = null; dropTarget.value = null }
function startDrag(event: DragEvent, kind: 'tag' | 'dataset', id: string): void { if (busy.value) { event.preventDefault(); return } drag = { kind, id }; event.dataTransfer?.setData('text/plain', id); if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move' }
function overFolder(event: DragEvent, folder: DatasetFolder): void {
  if (!drag || busy.value || (drag.kind === 'tag' && isDescendant(folder.id, drag.id))) return
  event.preventDefault(); dropTarget.value = folder.id
  const bounds = event.currentTarget instanceof Element ? event.currentTarget.getBoundingClientRect() : null
  const ratio = bounds ? (event.clientY - bounds.top) / bounds.height : .5
  pendingMove = ratio < .25 || ratio > .75 ? { kind: drag.kind, identity: drag.id, parent_id: folder.parent_id, anchor_kind: 'tag', anchor_id: folder.id, after: ratio > .75 }
    : { kind: drag.kind, identity: drag.id, parent_id: folder.id }
}
function overDataset(event: DragEvent, id: string, parent: string | null): void {
  if (!drag || busy.value || drag.id === id) return
  if (drag.kind === 'tag' && parent && isDescendant(parent, drag.id)) return
  event.preventDefault(); dropTarget.value = `dataset:${id}`
  const bounds = event.currentTarget instanceof Element ? event.currentTarget.getBoundingClientRect() : null
  pendingMove = { kind: drag.kind, identity: drag.id, parent_id: parent, anchor_kind: 'dataset', anchor_id: id, after: bounds ? event.clientY > bounds.top + bounds.height / 2 : true }
}
function overRoot(event: DragEvent): void { if (!drag || busy.value) return; event.preventDefault(); dropTarget.value = 'root'; pendingMove = { kind: drag.kind, identity: drag.id, parent_id: null } }
async function drop(): Promise<void> { const move = pendingMove; clearDrag(); if (move) await mutate(() => service.move(move)) }
function sessionChanged(event: Event): void {
  const current = sessionGeneration()
  if ((event as CustomEvent<string | null>).detail !== null && current === authSession) return
  authSession = current
  ++epoch; ++generation; ++tagGeneration; ++facetsGeneration; branchGenerations.clear()
  folders.value = []; branches.value = {}; rows.value = []; owners.value = []; keywords.value = []; expanded.value = []
  branchErrors.value = {}; branchLoading.value = {}; total.value = 0; currentUserId.value = undefined
  activeFolder.value = null; moving.value = null; deleting.value = null; busy.value = false
  reset(); void loadTags(); void loadFacets()
}
watch(expanded, (next, previous) => { for (const id of next) if (!previous.includes(id) && folders.value.some(tag => tag.id === id)) void loadBranch(id) }, { deep: true })
watch([filters, onlyUnclassified, pageSize], search, { deep: true })
watch(page, () => { void load() })
onMounted(() => { void refresh(); window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
onBeforeUnmount(() => { disposed = true; ++generation; ++epoch; ++tagGeneration; ++facetsGeneration; window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
defineExpose({ refresh })
</script>
<style scoped>
.dataset-navigation { height: 100%; min-height: 420px; }
.dataset-navigation :deep(> .q-splitter__before) { overflow: auto; }
.dataset-navigation :deep(> .q-splitter__after) { display: flex; min-height: 0; }
.dataset-list-panel { display: flex; flex-direction: column; width: 100%; min-height: 0; }
.dataset-list-scroll { flex: 1; min-height: 0; overflow: auto; }
.dataset-pagination { flex-shrink: 0; gap: 4px 12px; }
.dataset-drop { background: var(--solaire-blue-light); box-shadow: inset 0 0 0 1px var(--solaire-blue-accent); }
:global(body.body--dark) .dataset-drop { background: var(--solaire-blue-dark); }
</style>
