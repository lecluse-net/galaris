<template>
  <q-splitter v-model="split" horizontal :limits="[15, 65]" class="library-navigation" :class="{ 'library-navigation--dark': $q.dark.isActive }">
    <template #before>
      <div class="q-pa-sm">
        <q-banner v-if="tagError" dense class="library-error" role="alert">{{ t('documents.library.tagError') }}<q-btn flat :label="t('documents.retry')" @click="loadTags" /></q-banner>
        <q-tree v-model:expanded="treeExpanded" :nodes="tree" node-key="id" dense no-transition class="document-tree">
          <template #default-header="{ node }">
            <div class="tag-row row items-center no-wrap full-width"
              :class="dropClass(node.id)"
              @dragstart.stop="startTagDrag($event, node.id)" @dragend="clearDrag"
              @dragover.stop="dragOverNode($event, { kind: 'tag', id: node.id }, node.tag.parent_id)" @dragleave="dropTarget = null" @drop.prevent.stop="dropNode">
              <DocumentTagRow :key="`${userId}:${node.id}`" :tag="node.tag" :selected="expanded.includes(node.id)" :busy="busy" :save="saveTag" :create="createTag"
                :rename-on-create="renameTagId === node.id" @renamed="renameTagId === node.id && (renameTagId = null)"
                @sort="sortFolder(node.id, $event)" @expand="expandFolder(node.id, true)" @collapse="expandFolder(node.id, false)"
                @browse="emit('browse', node.tag)" @create-document="emit('create', node.tag)" @delete="requestDelete(node.tag)" @confirm-delete="confirmDelete(node.tag)" />
            </div>
          </template>
          <template #header-document="{ node }">
            <div class="full-width" :aria-label="node.parentDocumentId ? t('documents.library.subdocuments', { name: node.parentDocumentTitle }) : t('documents.library.tagDocuments', { name: node.tag.name })">
              <DocumentLibraryDocument :entry="node.entry" compact tree-row :tag-id="node.parentDocumentId ? null : node.tag.id" :parent-document-id="node.parentDocumentId" :selected-document-id="selectedDocumentId" :busy="busy"
                :children="branchEntries" :loading="branches.loading.value" :errors="branchErrors" :expanded="expandedDocuments" :drop-target="dropTarget" :drop-placement="dropPlacement"
                @select="emit('select', $event)" @create="emit('create', undefined, $event)" @action="(entry, action) => emit('action', entry, action)"
                @toggle="toggleDocument" @retry="id => branches.refresh(`doc:${id}`)" @dragstart="startDocumentDrag" @dragend="clearDrag"
                @dragover="dragOverDocument" @dragleave="dropTarget = null" @drop="dropNode" />
            </div>
          </template>
          <template #header-document-status="{ node }">
            <div class="full-width text-caption" @click.stop>
              <q-spinner v-if="branches.loading.value[node.branchKey]" size="16px" />
              <q-banner v-else-if="branchErrors[node.branchKey]" dense role="alert">{{ t('documents.loadError') }}
                <q-btn flat dense :label="t('documents.retry')" @click="branches.refresh(node.branchKey)" />
              </q-banner>
              <span v-else-if="branchSnapshots[node.branchKey] && !branches.loading.value[node.branchKey]">{{ t('documents.library.noSubdocuments') }}</span>
            </div>
          </template>
          <template #header-status="{ node }">
            <div class="full-width text-caption" @click.stop>
              <div v-if="branchErrors[node.tag.id]" class="library-error q-pa-sm" role="alert">{{ t('documents.loadError') }} <q-btn flat dense :label="t('documents.retry')" @click="branches.load(node.tag.id)" /></div>
              <span v-else-if="branchSnapshots[node.tag.id]">{{ t('documents.library.emptyFolder') }}</span>
            </div>
          </template>
        </q-tree>
        <div v-if="!tags.length && !tagError" class="text-caption q-pa-sm">{{ t('documents.library.emptyTags') }}</div>
        <div class="row items-center justify-end" :class="{ 'tag-row--drop': dropTarget === 'root' }"
          @dragover="dragOver($event, 'root')" @dragleave="dropTarget = null" @drop.prevent="drop(null)">
          <DocumentTagCreateButton :key="userId ?? 'session'" :parent-id="null" :busy="busy" :save="createTag" />
        </div>
      </div>
    </template>
    <template #separator>
      <DocumentSplitterHandle horizontal role="separator" tabindex="0" aria-orientation="horizontal" :aria-label="t('documents.library.resize')"
        :aria-valuenow="split" aria-valuemin="15" aria-valuemax="65" @keydown.up.prevent="split = Math.max(15, split - 5)" @keydown.down.prevent="split = Math.min(65, split + 5)" />
    </template>
    <template #after>
      <div class="document-list-panel" :class="{ 'tag-row--drop': dropTarget === 'root' }"
        @dragover="dragOver($event, 'root')" @dragleave="dropTarget = null" @drop.prevent="drop(null)">
        <div class="row no-wrap items-center q-pa-sm q-gutter-xs">
          <q-input v-model="query" dense outlined clearable debounce="350" class="col" :placeholder="t('documents.search')" :aria-label="t('documents.search')">
            <template #prepend><q-icon name="search" size="18px" /></template>
          </q-input>
          <DocumentLibraryFilters v-model="filters" v-model:only-unclassified="onlyUnclassified" :owners="owners" :keywords="keywords" :current-user-id="userId ?? undefined" />
          <q-btn v-if="hasFilters" flat round dense icon="filter_alt_off" :aria-label="t('documents.library.reset')" @click="reset"><q-tooltip>{{ t('documents.library.reset') }}</q-tooltip></q-btn>
          <q-btn flat round dense icon="add" :aria-label="t('documents.createDocument')" @click="emit('create')"><q-tooltip>{{ t('documents.createDocument') }}</q-tooltip></q-btn>
          <q-btn flat round dense icon="view_list" :aria-label="t('documents.bulk.openUnclassified')" @click="emit('browse', null)"><q-tooltip>{{ t('documents.bulk.openUnclassified') }}</q-tooltip></q-btn>
        </div>
        <q-banner v-if="loadError" dense class="library-error" role="alert">{{ t('documents.loadError') }}<q-btn flat :label="t('documents.retry')" @click="reload" /></q-banner>
        <q-list class="document-list-scroll" separator :aria-busy="loading" :aria-label="t(onlyUnclassified ? 'documents.library.orphans' : 'documents.library.all')">
          <DocumentLibraryDocument v-for="entry in visibleEntries" :key="entry.item.id" :entry="entry" list-only :selected-document-id="selectedDocumentId" :busy="busy"
            :children="branchEntries" :loading="branches.loading.value" :errors="branchErrors" :expanded="expandedDocuments" :drop-target="dropTarget" :drop-placement="dropPlacement"
            @select="emit('select', $event)" @create="emit('create', undefined, $event)" @action="(entry, action) => emit('action', entry, action)"
            @toggle="toggleDocument" @retry="id => branches.refresh(`doc:${id}`)" @dragstart="startDocumentDrag" @dragend="clearDrag"
            @dragover="dragOverDocument" @dragleave="dropTarget = null" @drop="dropNode" />
          <div v-if="!loading && !loadError && !visibleEntries.length" class="q-pa-md text-caption">{{ t('documents.empty') }}</div>
        </q-list>
        <div class="library-pagination row items-center justify-center q-pa-xs">
          <span class="text-caption">{{ t('documents.library.pageRange', { first: visibleEntries.length ? (page - 1) * pageSize + 1 : 0, last: visibleEntries.length ? (page - 1) * pageSize + visibleEntries.length : 0, total: visibleTotal }) }}</span>
          <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" dense borderless :aria-label="t('documents.library.pageSize')">
            <template #selected>{{ t('documents.library.perPage', { count: pageSize }) }}</template>
          </q-select>
          <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="3" direction-links boundary-numbers size="sm" />
        </div>
      </div>
    </template>
  </q-splitter>
  <q-dialog v-model="deleteDialog">
    <q-card class="tag-dialog galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center"><span class="text-h6">{{ t('documents.library.deleteTag') }}</span><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section class="galaris-dialog-body">{{ t('documents.library.deleteExplanation', { name: editingTag?.name }) }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup outline :label="t('documents.library.cancel')" /><q-btn color="negative" :loading="busy" :label="t('documents.library.deleteTag')" @click="editingTag && requestDelete(editingTag, true)" /></q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { websocket } from '@/core/websocket'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration as authSessionGeneration } from '@/core/api'
import type { DocumentLibraryEntry, DocumentLibraryFilters as LibraryRequest, DocumentOwnerOption, DocumentTag, DocumentOrderNode, DocumentOrderMove, MemoryItem } from '../types'
import { memoryService } from '../services/memoryService'
import { defaultLibraryFilters, libraryRequestFilters } from '../libraryFilterState'
import DocumentLibraryFilters from './DocumentLibraryFilters.vue'
import DocumentTagCreateButton from './DocumentTagCreateButton.vue'
import DocumentTagRow from './DocumentTagRow.vue'
import { useDocumentBranches } from '../useDocumentBranches'
import { reconcileLibrarySnapshot } from '../librarySnapshot'
import { useDocumentMutations } from '../stores/documentMutations'
import DocumentLibraryDocument from './DocumentLibraryDocument.vue'
import DocumentSplitterHandle from './DocumentSplitterHandle.vue'
import type { DocumentRowAction } from '../libraryShortcuts'
defineProps<{ selectedDocumentId: string | null }>()
const emit = defineEmits<{ action: [entry: DocumentLibraryEntry, action: DocumentRowAction]; browse: [folder: DocumentTag | null]; select: [entry: DocumentLibraryEntry]; loaded: [entries: DocumentLibraryEntry[]]; create: [tag?: DocumentTag, parent?: DocumentLibraryEntry] }>()
const { t } = useI18n()
const $q = useQuasar()
const userId = ref<number | null>(null)
const split = ref(35)
const tags = ref<DocumentTag[]>([])
const expanded = ref<string[]>([])
const expandedDocuments = ref<string[]>([])
const renameTagId = ref<string | null>(null)
const onlyUnclassified = ref(true)
const entries = shallowRef<DocumentLibraryEntry[]>([])
const owners = ref<DocumentOwnerOption[]>([])
const keywords = ref<string[]>([])
const total = ref(0)
const query = ref<string | null>('')
const page = ref(1)
const pageSize = ref(50)
const filters = ref(defaultLibraryFilters())
const loading = ref(false)
const loadError = ref(false)
const tagError = ref(false)
const busy = ref(false)
const deleteDialog = ref(false)
const editingTag = ref<DocumentTag | null>(null)
const branches = useDocumentBranches(publishEntries)
const { entries: branchSnapshots, errors: branchErrors } = branches
const documentMutations = useDocumentMutations()
// One current item per document; list/folder entries retain only their placement and access context.
const libraryItems = shallowRef<Record<string, MemoryItem>>({})
function rememberItems(incoming: MemoryItem[]): void {
  const next = { ...libraryItems.value }
  let changed = false
  for (const item of incoming) {
    const current = next[item.id]
    if (current && (item.lock_version ?? item.revision) < (current.lock_version ?? current.revision)) continue
    if (current === item || (current && JSON.stringify(current) === JSON.stringify(item))) continue
    next[item.id] = item
    changed = true
  }
  if (changed) libraryItems.value = next
}
function projectEntries(values: DocumentLibraryEntry[], includePending = false): DocumentLibraryEntry[] {
  return values.filter(entry => includePending || documentMutations.deleting[entry.item.id] === undefined).map(entry => {
    const item = libraryItems.value[entry.item.id]
    return item && item !== entry.item ? { ...entry, item } : entry
  })
}
const visibleEntries = computed(() => projectEntries(entries.value))
const visibleTotal = computed(() => Math.max(0, total.value - (entries.value.length - visibleEntries.value.length)))
const branchEntries = computed(() => Object.fromEntries(Object.entries(branchSnapshots.value).map(([key, values]) => [key,
  projectEntries(values)])))
const dropTarget = ref<string | null>(null)
const dropPlacement = ref<'inside' | 'before' | 'after'>('inside')
let pendingDrop: Omit<DocumentOrderMove, 'node'> | null = null
let drag: { kind: 'tag' | 'document'; id: string } | null = null
let documentFromTree = false
let generation = 0
let accessGeneration = 0
let tagGeneration = 0
let disposed = false
let ready = false
let sessionGeneration = 0
let authSession = authSessionGeneration()
let listController: AbortController | undefined
let facetsGeneration = 0
let loadedFacetsGeneration = -1
let refreshInFlight: Promise<void> | undefined
interface ClassificationChange { tag_ids?: string[]; document_ids?: string[]; content_ids?: string[]; tags_changed?: boolean; list_changed?: boolean }
let pendingChanges: ClassificationChange[] = []
let refreshTimer: ReturnType<typeof setTimeout> | undefined
interface TagNode {
  id: string; label: string; tag: DocumentTag; position: number; entry?: DocumentLibraryEntry
  parentDocumentId?: string; parentDocumentTitle?: string; branchKey?: string
  children?: TagNode[]; header?: string; selectable?: boolean
}
function documentTreeNode(entry: DocumentLibraryEntry, tag: DocumentTag, ancestors: string[] = [], parent?: DocumentLibraryEntry): TagNode {
  const branchKey = `doc:${entry.item.id}`
  const node: TagNode = { id: `document:${tag.id}:${entry.item.id}`, label: entry.item.title, tag, entry,
    parentDocumentId: parent?.item.id, parentDocumentTitle: parent?.item.title, branchKey,
    position: entry.position ?? 0, header: 'document', selectable: false }
  const cached = branchEntries.value[branchKey]
  if (entry.children_count || cached?.length || expandedDocuments.value.includes(branchKey)) {
    const path = [...ancestors, entry.item.id]
    node.children = (cached ?? []).filter(child => !path.includes(child.item.id)).map(child => documentTreeNode(child, tag, path, entry))
    if (!cached || branchErrors.value[branchKey] || !node.children.length) {
      node.children.push({ id: `status:${node.id}`, label: '', tag, branchKey, position: 0, header: 'document-status', selectable: false })
    }
  }
  return node
}
const tree = computed<TagNode[]>(() => {
  const nodes = new Map<string, TagNode>(tags.value.map(tag => [tag.id, { id: tag.id, label: tag.name, tag, position: tag.position ?? 0, children: [] }]))
  const roots: TagNode[] = []
  for (const tag of tags.value) {
    const node = nodes.get(tag.id)!
    const parent = tag.parent_id ? nodes.get(tag.parent_id) : null
    if (parent) parent.children!.push(node)
    else roots.push(node)
  }
  const compare = (a: TagNode, b: TagNode) => Number(Boolean(a.entry)) - Number(Boolean(b.entry)) || a.position - b.position || a.label.toLowerCase().localeCompare(b.label.toLowerCase()) || a.id.localeCompare(b.id)
  for (const node of nodes.values()) {
    const documents = branchEntries.value[node.id]
    node.children!.push(...(documents ?? []).map(entry => documentTreeNode(entry, node.tag)))
    node.children!.sort(compare)
    // Keep empty folders expandable: QTree otherwise turns them into leaves after loading.
    if (!documents || branchErrors.value[node.id] || node.children!.length === 0) {
      node.children!.push({ id: `status:${node.id}`, label: '', tag: node.tag, position: 0, header: 'status', selectable: false })
    }
  }
  roots.sort(compare)
  return roots
})
const treeDocumentKeys = computed(() => {
  const keys = new Map<string, string>()
  const visit = (nodes: TagNode[]): void => {
    for (const node of nodes) {
      if (node.entry && node.branchKey) keys.set(node.id, node.branchKey)
      if (node.children) visit(node.children)
    }
  }
  visit(tree.value)
  return keys
})
const treeExpanded = computed({
  get: () => [...expanded.value, ...[...treeDocumentKeys.value].filter(([, key]) => expandedDocuments.value.includes(key)).map(([id]) => id)],
  set: (value: string[]) => {
    const keys = treeDocumentKeys.value
    const present = new Set(keys.values())
    const next = [...new Set([...expandedDocuments.value.filter(key => !present.has(key)),
      ...value.flatMap(id => keys.has(id) ? [keys.get(id)!] : [])])]
    for (const key of expandedDocuments.value) if (!next.includes(key)) branches.close(key)
    for (const key of next) if (!expandedDocuments.value.includes(key)) void branches.load(key)
    expandedDocuments.value = next
    expanded.value = value.filter(id => tags.value.some(tag => tag.id === id))
  },
})
const listFilters = computed(() => ({ ...libraryRequestFilters(filters.value), query: query.value ?? '' }))
function publishEntries(incoming?: DocumentLibraryEntry[]): void {
  if (incoming) rememberItems(incoming.map(entry => entry.item))
  const snapshots = [...entries.value, ...Object.values(branchSnapshots.value).flat()]
  const retained = new Set(snapshots.map(entry => entry.item.id))
  if (Object.keys(libraryItems.value).some(id => !retained.has(id))) {
    libraryItems.value = Object.fromEntries(Object.entries(libraryItems.value).filter(([id]) => retained.has(id)))
  }
  emit('loaded', [...new Map(projectEntries(snapshots, true).map(entry => [entry.item.id, entry])).values()])
}
function isDescendant(id: string, ancestor: string): boolean {
  let tag = tags.value.find(value => value.id === id)
  const seen = new Set<string>()
  while (tag && !seen.has(tag.id)) {
    if (tag.id === ancestor) return true
    seen.add(tag.id); tag = tags.value.find(value => value.id === tag?.parent_id)
  }
  return false
}
const hasFilters = computed(() => Boolean(!onlyUnclassified.value || query.value || JSON.stringify(filters.value) !== JSON.stringify(defaultLibraryFilters())))
async function reload(): Promise<void> {
  const current = ++generation
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  const facets = facetsGeneration
  const includeFacets = loadedFacetsGeneration !== facets
  const request: LibraryRequest = {
    ...listFilters.value, include_owners: includeFacets, include_keywords: includeFacets,
    classification: onlyUnclassified.value ? 'unclassified' : 'all',
    tag_id: null, limit: pageSize.value, offset: (page.value - 1) * pageSize.value,
  }
  loading.value = true; loadError.value = false
  try {
    const result = await memoryService.browseDocumentLibrary(request, controller.signal)
    if (disposed || current !== generation) return
    total.value = result.total
    if (includeFacets) {
      owners.value = result.owners ?? []
      keywords.value = result.keywords
      loadedFacetsGeneration = facets
    }
    if (page.value > Math.max(1, Math.ceil(result.total / pageSize.value))) {
      page.value = Math.max(1, Math.ceil(result.total / pageSize.value)); return
    }
    entries.value = reconcileLibrarySnapshot(entries.value, result.entries, entry => entry.item.id)
    publishEntries(result.entries)
  } catch {
    if (!disposed && current === generation) {
      loadError.value = true
    }
  }
  finally { if (!disposed && current === generation) loading.value = false }
}
async function loadTags(): Promise<void> {
  const current = ++tagGeneration
  try {
    const result = await memoryService.listDocumentTags()
    if (disposed || current !== tagGeneration) return
    if (userId.value !== result.user_id) { userId.value = result.user_id; restoreSplit() }
    tags.value = reconcileLibrarySnapshot(tags.value, result.tags, tag => tag.id); tagError.value = false
    expanded.value = expanded.value.filter(id => result.tags.some(tag => tag.id === id))
    for (const id of Object.keys(branchSnapshots.value)) if (!id.startsWith('doc:') && !result.tags.some(tag => tag.id === id)) branches.forget(id)
  } catch { if (!disposed && current === tagGeneration) tagError.value = true }
}
async function refreshTree(ids = [...expanded.value, ...expandedDocuments.value]): Promise<void> {
  await Promise.all([...new Set(ids)].map(id => {
    if (!expanded.value.includes(id) && !expandedDocuments.value.includes(id)) { branches.forget(id); return }
    return branches.refresh(id)
  }))
}
async function refresh(): Promise<void> { await Promise.all([reload(), refreshTree()]) }
function documentFolders(ids: string[]): string[] {
  return Object.entries(branchSnapshots.value).filter(([, values]) => values.some(entry => ids.includes(entry.item.id))).map(([id]) => id)
}
function supersedeReads(ids: string[]): void {
  // Reads started before a confirmed write cannot restore its previous placement.
  ++generation
  listController?.abort()
  if (loading.value) { loading.value = false; queueChange({ list_changed: true }) }
  branches.invalidate(ids)
}
function applyDocumentMove(move: DocumentOrderMove): void {
  const id = move.node.id
  const entry = [...entries.value, ...Object.values(branchSnapshots.value).flat()].find(value => value.item.id === id)
  if (!entry) return
  const target = move.parent_document_id ? `doc:${move.parent_document_id}` : move.parent_id
  const affected = move.list_only ? [] : [...new Set([...documentFolders([id]), ...(target ? [target] : [])])]
  supersedeReads(affected)
  if (!move.list_only && target) {
    if (move.parent_document_id) {
      if (!expandedDocuments.value.includes(target)) expandedDocuments.value.push(target)
    } else {
      let tag = tags.value.find(value => value.id === target)
      while (tag) {
        if (!expanded.value.includes(tag.id)) expanded.value.push(tag.id)
        tag = tags.value.find(value => value.id === tag?.parent_id)
      }
    }
  }
  const place = (values: DocumentLibraryEntry[], value: DocumentLibraryEntry): DocumentLibraryEntry[] => {
    const siblings = values.filter(candidate => candidate.item.id !== id)
    const anchor = move.anchor?.kind === 'document' ? siblings.findIndex(candidate => candidate.item.id === move.anchor?.id) : -1
    siblings.splice(anchor < 0 ? siblings.length : anchor + Number(Boolean(move.after)), 0, value)
    return siblings.map((candidate, index) => ({ ...candidate, position: index + 1 }))
  }
  if (move.list_only) entries.value = place(entries.value, entry)
  else {
    const moved: DocumentLibraryEntry = { ...entry, parent_document_id: move.parent_document_id ?? null,
      tags: move.parent_id ? tags.value.filter(tag => tag.id === move.parent_id) : [] }
    for (const key of affected) {
      const values = branchSnapshots.value[key] ?? []
      branchSnapshots.value[key] = key === target ? place(values, moved) : values.filter(candidate => candidate.item.id !== id)
    }
    const inList = entries.value.some(candidate => candidate.item.id === id)
    const classified = Boolean(target)
    if (onlyUnclassified.value && classified) {
      entries.value = entries.value.filter(candidate => candidate.item.id !== id)
      if (inList) total.value = Math.max(0, total.value - 1)
    } else if (onlyUnclassified.value && !classified && !inList && page.value === 1 && !hasFilters.value) {
      entries.value = place(entries.value, moved).slice(0, pageSize.value)
      total.value += 1
    } else {
      entries.value = entries.value.map(candidate => candidate.item.id === id ? { ...moved, position: candidate.position } : candidate)
    }
    const parentIds = new Set([entry.parent_document_id, moved.parent_document_id].filter(Boolean))
    const updateCounts = (values: DocumentLibraryEntry[]) => values.map(candidate => {
      if (!parentIds.has(candidate.item.id) || entry.parent_document_id === moved.parent_document_id) return candidate
      const delta = candidate.item.id === moved.parent_document_id ? 1 : -1
      return { ...candidate, children_count: Math.max(0, (candidate.children_count ?? 0) + delta) }
    })
    entries.value = updateCounts(entries.value)
    for (const key of Object.keys(branchSnapshots.value)) branchSnapshots.value[key] = updateCounts(branchSnapshots.value[key] ?? [])
  }
  // Preserve the source locations before removing their rows from the local snapshot.
  queueChange({ tag_ids: affected })
  publishEntries()
}
function removeDocument(id: string): void {
  const affected = documentFolders([id])
  supersedeReads([...affected, `doc:${id}`])
  if (entries.value.some(entry => entry.item.id === id)) total.value = Math.max(0, total.value - 1)
  entries.value = entries.value.filter(entry => entry.item.id !== id)
  for (const key of affected) branchSnapshots.value[key] = (branchSnapshots.value[key] ?? []).filter(entry => entry.item.id !== id)
  branches.forget(`doc:${id}`)
  expandedDocuments.value = expandedDocuments.value.filter(key => key !== `doc:${id}`)
  queueChange({ tag_ids: affected, list_changed: true })
  publishEntries()
}
function updateDocument(document: MemoryItem): void {
  const affected = documentFolders([document.id])
  supersedeReads(affected)
  rememberItems([document])
  const update = (values: DocumentLibraryEntry[]) => values.map(entry => {
    if (entry.item.id !== document.id || entry.item.lock_version > document.lock_version) return entry
    return { ...entry, item: document }
  })
  entries.value = update(entries.value)
  for (const key of affected) branchSnapshots.value[key] = update(branchSnapshots.value[key] ?? [])
  publishEntries()
  queueChange({ content_ids: [document.id], list_changed: true })
}
function queueChange(change: ClassificationChange): void {
  if (change.list_changed) ++facetsGeneration
  pendingChanges.push(change)
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { refreshTimer = undefined; if (!busy.value) void flushChanges() }, 100)
}
async function flushChanges(): Promise<void> {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = undefined
  // A burst during a slow read gets one trailing reconciliation, never parallel copies.
  if (refreshInFlight) {
    await refreshInFlight
    if (pendingChanges.length) await flushChanges()
    return
  }
  const changes = pendingChanges.splice(0)
  if (!changes.length || disposed) return
  const refresh = applyChanges(changes)
  refreshInFlight = refresh
  try { await refresh } finally { if (refreshInFlight === refresh) refreshInFlight = undefined }
}
async function applyChanges(changes: ClassificationChange[]): Promise<void> {
  const session = sessionGeneration
  const access = accessGeneration
  const ids = [...new Set(changes.flatMap(change => [...(change.tag_ids ?? []), ...documentFolders([...(change.document_ids ?? []), ...(change.content_ids ?? [])]),
    ...(change.document_ids ?? []).map(id => `doc:${id}`)]))]
  if (changes.some(change => change.tags_changed)) await loadTags()
  if (disposed || session !== sessionGeneration || access !== accessGeneration) return
  await Promise.all([refreshTree(ids), ...(changes.some(change => change.list_changed) ? [reload()] : [])])
  if (disposed || session !== sessionGeneration || access !== accessGeneration) return
  // A completed list read is authoritative; a failed folder refresh must not overwrite it.
  if (changes.some(change => change.list_changed)) return
  const refreshed = new Map(ids.flatMap(id => branchSnapshots.value[id] ?? []).map(entry => [entry.item.id, entry]))
  entries.value = reconcileLibrarySnapshot(entries.value, entries.value.map(entry => {
    const current = refreshed.get(entry.item.id)
    return current ? { ...current, position: entry.position } : entry
  }), entry => entry.item.id)
  publishEntries()
}
function classificationChanged(event: { data: ClassificationChange & { user_id: number } }): void {
  if (event.data.user_id === userId.value) queueChange(event.data)
}
function refreshDocuments(ids: string[], tagId?: string, parentDocumentId?: string): void {
  if (parentDocumentId && !expandedDocuments.value.includes(`doc:${parentDocumentId}`)) expandedDocuments.value.push(`doc:${parentDocumentId}`)
  if (tagId) {
    const open = new Set(expanded.value)
    let tag = tags.value.find(value => value.id === tagId)
    const seen = new Set<string>()
    while (tag && !seen.has(tag.id)) {
      seen.add(tag.id); open.add(tag.id)
      tag = tags.value.find(value => value.id === tag?.parent_id)
    }
    expanded.value = [...open]
  }
  queueChange({ content_ids: ids, document_ids: parentDocumentId ? [parentDocumentId] : [], tag_ids: tagId ? [tagId] : [], list_changed: true })
}
function toggleDocument(id: string): void {
  const key = `doc:${id}`
  if (expandedDocuments.value.includes(key)) {
    expandedDocuments.value = expandedDocuments.value.filter(value => value !== key)
    branches.close(key)
  } else { expandedDocuments.value.push(key); void branches.load(key) }
}
function invalidateAccess(): void {
  ++facetsGeneration
  ++accessGeneration
  pendingChanges = []
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = undefined
  ++generation
  branches.invalidate()
  reconnect()
}
function reconnect(): void {
  // Access changes and reconnects reconcile authoritative snapshots in place.
  // Identity changes use changeSession to discard the previous user's data.
  const session = sessionGeneration
  ++facetsGeneration
  void loadTags().then(() => {
    if (!disposed && session === sessionGeneration) return refresh()
  })
}
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'invalidate', invalidateAccess)
  websocket.onEvent('memory', 'classification', classificationChanged)
  websocket.onConnect(reconnect)
})
onBeforeUnmount(() => {
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offEvent('memory', 'classification', classificationChanged)
  websocket.offConnect(reconnect)
  if (refreshTimer) clearTimeout(refreshTimer)
})
function reset(): void { query.value = ''; filters.value = defaultLibraryFilters(); onlyUnclassified.value = true }
async function mutate(action: () => Promise<unknown>, change: ClassificationChange = { tags_changed: true }, confirmed?: () => void): Promise<boolean> {
  if (busy.value) return false
  const session = sessionGeneration
  busy.value = true
  try {
    await action()
    if (disposed || session !== sessionGeneration) return false
    confirmed?.()
    queueChange(change)
    if (!confirmed) await flushChanges()
    return !disposed && session === sessionGeneration
  }
  catch { if (!disposed && session === sessionGeneration) $q.notify({ type: 'negative', message: t('documents.library.error') }); return false }
  finally { if (session === sessionGeneration) { busy.value = false; if (pendingChanges.length) void flushChanges() } }
}
async function saveTag(tag: DocumentTag): Promise<boolean> {
  return mutate(() => memoryService.saveDocumentTag({ name: tag.name, parent_id: tag.parent_id, icon: tag.icon }, tag.id))
}
async function sortFolder(id: string, descending: boolean): Promise<void> {
  await mutate(() => memoryService.sortDocumentFolder(id, descending), { tags_changed: true, tag_ids: [id] })
}
function expandFolder(id: string, expand: boolean): void {
  const branch = tags.value.filter(tag => isDescendant(tag.id, id)).map(tag => tag.id)
  expanded.value = expand ? [...new Set([...expanded.value, ...branch])] : expanded.value.filter(value => !branch.includes(value))
}
async function createTag(name: string, parentId: string | null, afterTagId?: string): Promise<boolean> {
  const creation: { tag?: DocumentTag } = {}
  const session = sessionGeneration
  const saved = await mutate(async () => {
    creation.tag = await memoryService.saveDocumentTag({ name, parent_id: parentId })
    if (afterTagId && !disposed && session === sessionGeneration) {
      try {
        await memoryService.reorderDocuments({ node: { kind: 'tag', id: creation.tag.id }, parent_id: parentId,
          anchor: { kind: 'tag', id: afterTagId }, after: true })
      } catch {
        if (!disposed && session === sessionGeneration) $q.notify({ type: 'warning', message: t('documents.library.folderPositionError') })
      }
    }
  }, { tags_changed: true, tag_ids: afterTagId && parentId ? [parentId] : [] })
  if (saved && parentId && !expanded.value.includes(parentId)) expanded.value.push(parentId)
  if (saved && creation.tag) renameTagId.value = creation.tag.id
  return saved
}
function confirmDelete(tag: DocumentTag): void {
  if (busy.value) return
  editingTag.value = tag
  deleteDialog.value = true
}
async function requestDelete(tag: DocumentTag, confirmed = false): Promise<void> {
  if (busy.value) return
  const session = sessionGeneration
  busy.value = true
  try {
    const result = await memoryService.deleteDocumentTag(tag.id, confirmed)
    if (disposed || session !== sessionGeneration) return
    if (!result.deleted) { editingTag.value = tag; deleteDialog.value = true; return }
    deleteDialog.value = false; editingTag.value = null
    const removed = tags.value.filter(value => isDescendant(value.id, tag.id)).map(value => value.id)
    const documents = Object.values(branchSnapshots.value).flat().filter(entry => entry.tags?.some(value => removed.includes(value.id))).map(entry => entry.item.id)
    queueChange({ tags_changed: true, document_ids: documents, list_changed: result.document_count > 0 })
    await flushChanges()
  } catch { if (!disposed && session === sessionGeneration) $q.notify({ type: 'negative', message: t('documents.library.error') }) }
  finally { if (session === sessionGeneration) { busy.value = false; if (pendingChanges.length) void flushChanges() } }
}
function startTagDrag(event: DragEvent, id: string): void {
  if (busy.value) { event.preventDefault(); return }
  documentFromTree = false
  drag = { kind: 'tag', id }; event.dataTransfer?.setData('text/plain', id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function startDocumentDrag(event: DragEvent, id: string): void {
  if (busy.value) { event.preventDefault(); return }
  drag = { kind: 'document', id }
  documentFromTree = event.target instanceof Element && Boolean(event.target.closest('.document-tree, .document-children'))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copyMove'
}
async function moveDocument(documentId: string, tagId: string | null): Promise<void> {
  const entry = [...entries.value, ...Object.values(branchSnapshots.value).flat()].find(value => value.item.id === documentId)
  const change = { document_ids: [documentId], tag_ids: tagId ? [tagId] : [], list_changed: !entry || Boolean(entry.parent_document_id) || Boolean(entry.tags?.length) !== Boolean(tagId) }
  if (await mutate(() => memoryService.moveDocumentToTag(documentId, tagId), change,
    () => applyDocumentMove({ node: { kind: 'document', id: documentId }, parent_id: tagId })) && tagId) {
    let tag = tags.value.find(value => value.id === tagId)
    while (tag) {
      if (!expanded.value.includes(tag.id)) expanded.value.push(tag.id)
      tag = tags.value.find(value => value.id === tag?.parent_id)
    }
  }
}
function dragOver(event: DragEvent, target: string): void {
  if (!drag || busy.value || (drag.kind === 'tag' && isDescendant(target, drag.id))) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTarget.value = target
  dropPlacement.value = 'inside'; pendingDrop = null
}
function dragOverNode(event: DragEvent, anchor: DocumentOrderNode, parentId: string | null, listOnly = false, key = anchor.id): void {
  pendingDrop = null; dropTarget.value = null
  if (!drag || busy.value || (drag.kind === anchor.kind && drag.id === anchor.id) || (listOnly && drag.kind === 'tag')) return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = (event.clientY - bounds.top) / bounds.height
  const inside = anchor.kind === 'tag' && ratio >= 0.25 && ratio <= 0.75
  // Root documents belong to the lower list, not beside root folders in the tree.
  if (!inside && anchor.kind === 'tag' && parentId === null && drag.kind === 'document') return
  const parent = inside ? anchor.id : parentId
  if (drag.kind === 'tag' && parent && isDescendant(parent, drag.id)) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTarget.value = key
  dropPlacement.value = inside ? 'inside' : ratio < 0.5 ? 'before' : 'after'
  pendingDrop = { parent_id: parent, list_only: listOnly && !documentFromTree, ...(inside ? {} : { anchor, after: ratio >= 0.5 }) }
}
function dragOverDocument(event: DragEvent, entry: DocumentLibraryEntry, parentDocumentId?: string | null, tagId?: string | null, listOnly = false): void {
  pendingDrop = null; dropTarget.value = null
  if (!drag || busy.value || drag.kind !== 'document' || drag.id === entry.item.id) return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = (event.clientY - bounds.top) / bounds.height
  const inside = ratio >= 0.25 && ratio <= 0.75
  const parent = inside ? entry.item.id : parentDocumentId
  // Known descendants are rejected immediately; the server checks the entire stored hierarchy.
  let ancestor = parent
  const seen = new Set<string>()
  const known = [...entries.value, ...Object.values(branchSnapshots.value).flat()]
  while (ancestor && !seen.has(ancestor)) {
    if (ancestor === drag.id) return
    seen.add(ancestor); ancestor = known.find(value => value.item.id === ancestor)?.parent_document_id
  }
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTarget.value = `doc:${entry.item.id}`
  dropPlacement.value = inside ? 'inside' : ratio < 0.5 ? 'before' : 'after'
  pendingDrop = {
    parent_id: parent ? null : tagId ?? null,
    ...(parent ? { parent_document_id: parent } : {}),
    list_only: !inside && !parent && listOnly && !documentFromTree,
    ...(inside ? {} : { anchor: { kind: 'document', id: entry.item.id }, after: ratio >= 0.5 }),
  }
}
function dropClass(key: string): Record<string, boolean> {
  return { 'tag-row--drop': dropTarget.value === key && dropPlacement.value === 'inside',
    'node-drop-before': dropTarget.value === key && dropPlacement.value === 'before',
    'node-drop-after': dropTarget.value === key && dropPlacement.value === 'after' }
}
async function dropNode(): Promise<void> {
  const node = drag; const target = pendingDrop; clearDrag()
  if (!node || !target) return
  if (target.parent_document_id) {
    await mutate(() => memoryService.reorderDocuments({ node, ...target }), {
      document_ids: [node.id, target.parent_document_id], list_changed: true,
    }, () => applyDocumentMove({ node, ...target }))
    return
  }
  if (!target.anchor && !target.list_only) {
    if (node.kind === 'document') { await moveDocument(node.id, target.parent_id); return }
    const tag = tags.value.find(value => value.id === node.id)
    if (tag) await mutate(() => memoryService.saveDocumentTag({ name: tag.name, parent_id: target.parent_id }, tag.id))
  } else if (await mutate(() => memoryService.reorderDocuments({ node, ...target }), {
    tags_changed: !target.list_only,
    tag_ids: target.list_only || !target.parent_id ? [] : [target.parent_id],
    document_ids: node.kind === 'document' && !target.list_only ? [node.id] : [],
    list_changed: target.list_only || (node.kind === 'document' && (!target.parent_id || !documentFolders([node.id]).length)),
  }, node.kind === 'document' ? () => applyDocumentMove({ node, ...target }) : undefined)) {
    if (target.parent_id === null && node.kind === 'document' && (filters.value.sort_by !== 'position' || filters.value.sort_desc)) filters.value = { ...filters.value, sort_by: 'position', sort_desc: false }
  }
  if (target.parent_id && !expanded.value.includes(target.parent_id)) expanded.value.push(target.parent_id)
}
function clearDrag(): void { drag = null; documentFromTree = false; dropTarget.value = null; pendingDrop = null }
async function drop(parentId: string | null): Promise<void> {
  const value = drag; clearDrag()
  if (!value) return
  if (value.kind === 'document') { await moveDocument(value.id, parentId); return }
  const tag = tags.value.find(tag => tag.id === value.id)
  if (!tag || (parentId && isDescendant(parentId, tag.id))) return
  await mutate(() => memoryService.saveDocumentTag({ name: tag.name, parent_id: parentId }, tag.id))
}
watch([query, filters, pageSize, onlyUnclassified], () => { if (!ready) return; if (page.value !== 1) page.value = 1; else void reload() })
watch(page, () => { if (ready) void reload() })
watch(() => [...expanded.value], (value, previous) => {
  for (const id of previous) if (!value.includes(id)) branches.close(id)
  for (const id of value) if (!previous.includes(id)) void branches.load(id)
})
const storageKey = computed(() => `galaris:document-library-split:${userId.value ?? 'session'}`)
function restoreSplit(): void { try { const value = Number(localStorage.getItem(storageKey.value)); split.value = value >= 15 && value <= 65 ? value : 35 } catch { split.value = 35 } }
watch(split, value => { try { localStorage.setItem(storageKey.value, String(value)) } catch { /* Storage may be unavailable. */ } })
async function changeSession(event: Event): Promise<void> {
  const currentSession = authSessionGeneration()
  if ((event as CustomEvent<string | null>).detail !== null && currentSession === authSession) return
  authSession = currentSession
  const session = ++sessionGeneration
  ++facetsGeneration
  listController?.abort()
  pendingChanges = []
  if (refreshTimer) clearTimeout(refreshTimer)
  ++generation; ++tagGeneration; entries.value = []; libraryItems.value = {}; tags.value = []; owners.value = []; keywords.value = []; total.value = 0
  deleteDialog.value = false; editingTag.value = null; renameTagId.value = null; userId.value = null; busy.value = false; expanded.value = []; branches.reset(); clearDrag()
  expandedDocuments.value = []
  ready = false; reset(); page.value = 1; await loadTags()
  if (disposed || session !== sessionGeneration) return
  ready = true; await reload()
}
onMounted(async () => {
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession)
  ready = true
  await Promise.all([loadTags(), reload()])
})
onBeforeUnmount(() => { disposed = true; ++generation; ++tagGeneration; listController?.abort(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession) })
defineExpose({ reload: refresh, refreshDocuments, removeDocument, updateDocument })
</script>
<style scoped>
.library-navigation { height: 100%; min-height: 0; }
.library-error { color: var(--solaire-red-accent); background: var(--solaire-red-light); }
.library-navigation--dark .library-error { background: var(--solaire-red-dark); }
.library-navigation :deep(.q-splitter__panel) { min-height: 0; overflow: auto; }
.library-navigation :deep(.q-splitter__separator) { background: var(--solaire-gray-light); }
.tag-row { min-width: 0; }
.tag-row--drop { background: var(--solaire-blue-light); }
.node-drop-before { box-shadow: inset 0 2px var(--solaire-blue-accent); }
.node-drop-after { box-shadow: inset 0 -2px var(--solaire-blue-accent); }
.document-tree :deep(.q-tree__arrow), .document-tree :deep(.q-tree__spinner) { color: var(--solaire-gray-accent); }
.document-tree :deep(.q-tree__node-header) { min-height: 28px; }
.document-tree :deep(.q-tree__node-header :is(.tag-actions, .document-actions)) { opacity: 0; pointer-events: none; }
.document-tree :deep(.q-tree__node-header:hover :is(.tag-actions, .document-actions)),
.document-tree :deep(.q-tree__node-header:has(:focus-visible) :is(.tag-actions, .document-actions)) { opacity: 1; pointer-events: auto; }
@media (hover: none) {
  .document-tree :deep(.q-tree__node-header :is(.tag-actions, .document-actions)) { opacity: 1; pointer-events: auto; }
}
.document-list-panel { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.document-list-scroll { flex: 1; min-height: 0; overflow: auto; }
.library-pagination { flex-shrink: 0; gap: 4px 12px; }
.tag-dialog { width: min(440px, calc(100vw - 24px)); }
.library-navigation--dark :deep(.q-splitter__separator) { background: var(--solaire-gray-dark); }
.library-navigation--dark .tag-row--drop { background: var(--solaire-blue-dark); }
</style>
