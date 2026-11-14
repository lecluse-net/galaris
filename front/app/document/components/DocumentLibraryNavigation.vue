<template>
  <q-splitter v-model="split" horizontal :limits="[0, 100]" class="library-navigation" :class="{ 'library-navigation--dark': $q.dark.isActive }">
    <template #before>
      <q-tabs v-model="treeMode" dense inline-label align="left" :breakpoint="0" active-color="primary" indicator-color="primary" class="document-library-tabs text-primary" :aria-label="t('documents.library.treeMode')">
        <q-tab name="folders" icon="folder" :label="t('documents.library.folderMode')" @dragenter="hoverTreeMode('folders')" @dragover.prevent @dragleave="cancelModeHover" />
        <q-tab name="topics" :icon="navigationIcon('folder_copy')" :label="t('documents.library.topicsTags')" @dragenter="hoverTreeMode('topics')" @dragover.prevent @dragleave="cancelModeHover" />
        <q-tab name="agents" :icon="navigationIcon('people')" :label="t('documents.library.agents')" @dragenter="hoverTreeMode('agents')" @dragover.prevent @dragleave="cancelModeHover" />
      </q-tabs>
      <q-separator />
      <DocumentTopicNavigation v-for="mode in visitedClassifications" v-show="treeMode === mode" :key="`${treeSession}:${mode}`" :ref="instance => setClassificationNavigation(mode, instance)" :mode="mode" :selected-document-id="selectedDocumentId" :selected-document-ids="selectedDocumentIds" :busy="busy" :can-drop="treeMode === mode && topicDragActive && canMoveClassification"
        @select="selectClassifiedDocument" @action="(entry, action) => emit('action', entry, action)" @loaded="values => onTopicEntries(values, mode)"
        @dragstart="startTopicDrag" @dragend="clearDrag" @drop="moveTopicDocuments"
        @changed="ids => queueChange({ content_ids: ids, classification_catalog: true, list_changed: true })" @move="moveClassificationSelection" @deleted="removeDocument" @selection="ids => selectedDocumentIds = ids" />
      <div v-show="treeMode === 'folders'" class="q-pa-sm" @dragover.self="dragOver($event, 'root')" @drop.prevent.self="drop(null, true, $event)">
        <q-banner v-if="tagError" dense class="library-error" role="alert">{{ t('documents.library.tagError') }}<q-btn flat :label="t('documents.retry')" @click="loadTags" /></q-banner>
        <q-tree v-model:expanded="treeExpanded" :nodes="displayTree" node-key="id" dense no-transition class="document-tree">
          <template #default-header="{ node }">
            <div class="tag-row row items-center no-wrap full-width"
              :class="[dropClass(node.id), { 'document-create-menu-open': creationTagId === node.id }]"
              @dragstart.stop="startTagDrag($event, node.id)" @dragend="clearDrag"
              @dragover.stop="dragOverNode($event, { kind: 'tag', id: node.id }, node.tag.parent_id)" @dragleave="dropTarget = null" @drop.prevent.stop="dropNode">
              <DocumentTagRow :key="`${userId}:${node.id}`" :tag="node.tag" :selected="expanded.includes(node.id)" :busy="busy" :save="saveTag" :create="createTag"
                :rename-on-create="renameTagId === node.id" @renamed="renameTagId === node.id && (renameTagId = null)"
                @sort="sortFolder(node.id, $event)" @expand="expandFolder(node.id, true)" @collapse="expandFolder(node.id, false)"
                @browse="emit('browse', node.tag)" @create-document="(type, event) => emit('create', node.tag, undefined, false, type, event)" @delete="requestDelete(node.tag)" @confirm-delete="confirmDelete(node.tag)" />
            </div>
          </template>
          <template #header-document="{ node }">
            <div class="full-width" :class="{ 'document-create-menu-open': creationDocumentId === node.entry.item.id }" :aria-label="node.parentDocumentId ? t('documents.library.subdocuments', { name: node.parentDocumentTitle }) : node.tag ? t('documents.library.tagDocuments', { name: node.tag.name }) : t('documents.folderRoot')">
              <DocumentLibraryDocument :entry="node.entry" compact tree-row :tag-id="node.parentDocumentId ? null : node.tag?.id" :parent-document-id="node.parentDocumentId" :selected-document-id="selectedDocumentId" :selected-document-ids="selectedDocumentIds" :busy="busy"
                :children="branchEntries" :loading="branches.loading.value" :errors="branchErrors" :expanded="expandedDocuments" :drop-target="dropTarget" :drop-placement="dropPlacement"
                :totals="branches.totals.value" :ranges="branches.ranges.value" :load-page="branches.load" @page="toggleDocumentPage"
                @select="(entry, event) => selectDocument(entry, 'tree', node.id, event)" @create="(entry, type, event) => emit('create', undefined, entry, false, type, event)" @action="(entry, action) => emit('action', entry, action)"
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
          <template #header-virtual-range="{ node }">
            <TreePageHeader :page="node.page" :total="node.total" :titles="node.titles" :loading="branches.loading.value[treePageDataKey(node.id)]" />
          </template>
          <template #header-status="{ node }">
            <div class="full-width text-caption" @click.stop>
              <div v-if="branchErrors[node.tag.id]" class="library-error q-pa-sm" role="alert">{{ t('documents.loadError') }} <q-btn flat dense :label="t('documents.retry')" @click="branches.load(node.tag.id)" /></div>
              <span v-else-if="branchSnapshots[node.tag.id]">{{ t('documents.library.emptyFolder') }}</span>
            </div>
          </template>
        </q-tree>
        <q-spinner v-if="branches.loading.value.root" size="16px" />
        <q-banner v-else-if="branchErrors.root" dense role="alert">{{ t('documents.loadError') }}<q-btn outline color="primary" :label="t('documents.retry')" @click="branches.refresh('root')" /></q-banner>
        <div v-if="!tree.length && !tagError && !branchErrors.root && !branches.loading.value.root" class="text-caption q-pa-sm">{{ t('documents.empty') }}</div>
        <div role="group" :aria-label="t('documents.library.root')" class="row no-wrap q-gutter-x-sm q-mt-sm" :class="{ 'tag-row--drop': dropTarget === 'root' }"
          @dragover="dragOver($event, 'root')" @dragleave="dropTarget = null" @drop.prevent="drop(null, true, $event)">
          <q-btn v-if="canCreateDocument" class="col" outline dense no-caps icon="note_add" :label="t('documents.library.newDocumentAction')" :disable="busy" :aria-label="t('documents.library.newRootDocument')" @click="emit('create', undefined, undefined, true, undefined, $event)"><q-tooltip>{{ t('documents.library.newRootDocument') }}</q-tooltip></q-btn>
          <DocumentTagCreateButton :key="userId ?? 'session'" class="col" :parent-id="null" :busy="busy" :save="createTag" />
        </div>
      </div>
    </template>
    <template #separator>
      <DocumentSplitterHandle horizontal role="separator" tabindex="0" aria-orientation="horizontal" :aria-label="t('documents.library.resize')"
        :aria-valuenow="split" aria-valuemin="0" aria-valuemax="100" @keydown.up.prevent="split = Math.max(0, split - 5)" @keydown.down.prevent="split = Math.min(100, split + 5)" />
    </template>
    <template #after>
      <div class="document-list-panel" :class="{ 'tag-row--drop': dropTarget === 'root' }"
        @dragover="dragOver($event, 'root')" @dragleave="dropTarget = null" @drop.prevent="drop(null, false, $event)">
        <div class="row no-wrap items-center q-pa-sm q-gutter-xs">
          <q-input v-model="query" dense outlined clearable debounce="350" class="col" :placeholder="t('documents.search')" :aria-label="t('documents.search')">
            <template #prepend><q-icon name="search" size="18px" /></template>
          </q-input>
          <DocumentLibraryFilters v-model="filters" v-model:only-unclassified="onlyUnclassified" :owners="owners" :keywords="keywords" :current-user-id="userId ?? undefined" />
          <q-btn v-if="hasFilters" flat round dense icon="filter_alt_off" :aria-label="t('documents.library.reset')" @click="reset"><q-tooltip>{{ t('documents.library.reset') }}</q-tooltip></q-btn>
          <q-btn v-if="treeMode === 'folders'" flat round dense icon="view_list" :aria-label="t('documents.bulk.openUnclassified')" @click="emit('browse', null)"><q-tooltip>{{ t('documents.bulk.openUnclassified') }}</q-tooltip></q-btn>
        </div>
        <div v-if="treeMode === 'topics' && onlyUnclassified" class="text-caption q-px-sm q-pb-xs">{{ t('documents.library.withoutTopic') }}</div>
        <div v-if="treeMode === 'agents' && onlyUnclassified" class="text-caption q-px-sm q-pb-xs">{{ t('documents.library.withoutAgent') }}</div>
        <q-banner v-if="loadError" dense class="library-error" role="alert">{{ t('documents.loadError') }}<q-btn flat :label="t('documents.retry')" @click="reload" /></q-banner>
        <div v-if="selectedDocumentIds.length > 1" class="row items-center q-px-sm">
          <span class="col text-caption" role="status">{{ t('documents.bulk.selected', { count: selectedDocumentIds.length }) }}</span>
          <q-btn flat round dense icon="deselect" :aria-label="t('documents.bulk.clearSelection')" @click="selection.clear" />
        </div>
        <q-list class="document-list-scroll" separator :aria-busy="loading" :aria-label="t(onlyUnclassified ? 'documents.library.orphans' : 'documents.library.all')">
          <DocumentLibraryDocument v-for="entry in visibleEntries" :key="entry.item.id" :entry="entry" list-only :selected-document-id="selectedDocumentId" :selected-document-ids="selectedDocumentIds" :busy="busy"
            :children="branchEntries" :loading="branches.loading.value" :errors="branchErrors" :expanded="expandedDocuments" :drop-target="dropTarget" :drop-placement="dropPlacement"
            :totals="branches.totals.value" :ranges="branches.ranges.value" :load-page="branches.load" @page="toggleDocumentPage"
            @select="(entry, event) => selectDocument(entry, 'list', entry.item.id, event)" @create="(entry, type, event) => emit('create', undefined, entry, false, type, event)" @action="(entry, action) => emit('action', entry, action)"
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
import { TreePageHeader, TREE_PAGE_SIZE, treePages, treePageKey, treePageFromKey, treePageDataKey, virtualTreeNodes, type TreePage } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, watch, type ComponentPublicInstance, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useAuthStore, type DocumentLibraryMode } from '@/core/user'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration as authSessionGeneration } from '@/core/api'
import type { DocumentLibraryEntry, DocumentLibraryFilters as LibraryRequest, DocumentOwnerOption, DocumentTag, DocumentOrderNode, DocumentOrderMove, DocumentRecord } from '../types'
import { documentService } from '../services/documentService'
import type { DocumentCreationMode } from '../documentFormats'
import { defaultLibraryFilters, libraryRequestFilters } from '@/app/document/libraryFilterState'
import DocumentLibraryFilters from '@/app/document/components/DocumentLibraryFilters.vue'
import DocumentTagCreateButton from '@/app/document/components/DocumentTagCreateButton.vue'
import DocumentTagRow from '@/app/document/components/DocumentTagRow.vue'
import { useDocumentBranches } from '@/app/document/useDocumentBranches'
import { reconcileLibrarySnapshot, reconcileLibraryTree } from '@/app/document/librarySnapshot'
import { useDocumentMutations } from '@/app/document/stores/documentMutations'
import DocumentLibraryDocument from '@/app/document/components/DocumentLibraryDocument.vue'
import DocumentSplitterHandle from '@/app/document/components/DocumentSplitterHandle.vue'
import DocumentTopicNavigation from './DocumentTopicNavigation.vue'
import type { DocumentRowAction } from '@/app/document/libraryShortcuts'
import { documentSelectionModifiers, useDocumentSelection, type DocumentSelectionItem } from '@/app/document/useDocumentSelection'
import { documentDragSelection, setDocumentDragData } from '../documentDrag'
const props = defineProps<{ selectedDocumentId: string | null; creationTagId?: string | null; creationDocumentId?: string | null; importingFiles?: boolean }>()
const selection = useDocumentSelection()
const { selected: selectedDocumentIds } = selection
let requestedDocumentId: string | undefined
watch(() => props.selectedDocumentId, id => {
  // Opening the editor is asynchronous; its acknowledgement must not undo newer Ctrl/Shift clicks.
  if (id === requestedDocumentId) { requestedDocumentId = undefined; return }
  if (id && selectedDocumentIds.value.includes(id)) return
  selection.clear(); selectedDocumentIds.value = id ? [id] : []
}, { immediate: true })
const emit = defineEmits<{ filesDropped: [files: File[], tag?: DocumentTag, parent?: DocumentLibraryEntry, atRoot?: boolean]; action: [entry: DocumentLibraryEntry, action: DocumentRowAction]; browse: [folder: DocumentTag | null]; select: [entry: DocumentLibraryEntry]; loaded: [entries: DocumentLibraryEntry[]]; create: [tag?: DocumentTag, parent?: DocumentLibraryEntry, atRoot?: boolean, type?: DocumentCreationMode, event?: Event] }>()
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canCreateDocument = computed(() => privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN]))
const canClassify = computed(() => canCreateDocument.value && privilegeStore.hasPrivilege(privileges.TOPIC_EDIT))
const canMoveClassification = computed(() => treeMode.value === 'agents' ? canCreateDocument.value : canClassify.value)
const authStore = useAuthStore()
let viewOperation = 0
const treeMode = computed<DocumentLibraryMode>({
  get: () => authStore.documentLibraryMode,
  set: mode => {
    const operation = ++viewOperation
    void authStore.setDocumentLibraryMode(mode).catch(() => {
      if (!disposed && operation === viewOperation) $q.notify({ type: 'negative', message: t('documents.library.viewSaveError') })
    })
  },
})
type ClassificationMode = 'topics' | 'agents'
const visitedClassifications = ref<ClassificationMode[]>([])
const treeSession = ref(0)
const classificationNavigations = new Map<ClassificationMode, InstanceType<typeof DocumentTopicNavigation>>()
function setClassificationNavigation(mode: ClassificationMode, instance: Element | ComponentPublicInstance | null): void {
  if (instance) classificationNavigations.set(mode, instance as InstanceType<typeof DocumentTopicNavigation>)
  else classificationNavigations.delete(mode)
}
watch(treeMode, mode => {
  if (mode !== 'folders' && !visitedClassifications.value.includes(mode)) visitedClassifications.value.push(mode)
}, { immediate: true })
async function reconcileClassifications(ids?: string[]): Promise<void> {
  await Promise.all([...classificationNavigations.values()].map(navigation => navigation.reload(ids)))
}
const topicEntries = shallowRef<DocumentLibraryEntry[]>([])
const classificationEntries = new Map<ClassificationMode, DocumentLibraryEntry[]>()
const topicDragActive = ref(false)
let sourceKeyword: string | null = null
let sourceKeywords = new Map<string, string | null>()
let modeHoverTimer: ReturnType<typeof setTimeout> | undefined
function cancelModeHover(): void { if (modeHoverTimer) clearTimeout(modeHoverTimer); modeHoverTimer = undefined }
function hoverTreeMode(mode: DocumentLibraryMode): void {
  cancelModeHover()
  if (!drag || drag.kind !== 'document' || busy.value || treeMode.value === mode) return
  modeHoverTimer = setTimeout(() => {
    modeHoverTimer = undefined
    if (!drag || busy.value || disposed) return
    treeMode.value = mode
    topicDragActive.value = mode !== 'folders' && canMoveClassification.value
  }, 350)
}
const userId = ref<number | null>(null)
const split = ref(35)
const tags = ref<DocumentTag[]>([])
const expanded = ref<string[]>([])
const expandedDocuments = ref<string[]>([])
const virtualExpanded = ref<string[]>([])
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
let preserveSelectionOnSort = false
const initialType = new URLSearchParams(window.location.search).get('type')
if (initialType === 'text' || initialType === 'data') filters.value.document_format = initialType
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
const libraryItems = shallowRef(shallowReactive<Record<string, DocumentRecord>>({}))
function rememberItems(incoming: DocumentRecord[]): void {
  for (const item of incoming) {
    const current = libraryItems.value[item.id]
    if (current && (item.lock_version ?? item.revision) < (current.lock_version ?? current.revision)) continue
    if (current === item || (current && JSON.stringify(current) === JSON.stringify(item))) continue
    libraryItems.value[item.id] = item
  }
}
function projectEntries(values: DocumentLibraryEntry[], includePending = false): DocumentLibraryEntry[] {
  return values.filter(entry => includePending || documentMutations.deleting[entry.item.id] === undefined).map(entry => {
    const item = libraryItems.value[entry.item.id]
    return item && item !== entry.item ? { ...entry, item } : entry
  })
}
const visibleEntries = computed(() => projectEntries(entries.value))
const visibleTotal = computed(() => Math.max(0, total.value - (entries.value.length - visibleEntries.value.length)))
const branchProjections = computed<Map<string, ComputedRef<DocumentLibraryEntry[]>>>(previous => new Map(
  Object.keys(branchSnapshots.value).map(key => [key, previous?.get(key) ?? computed<DocumentLibraryEntry[]>(values =>
    reconcileLibrarySnapshot(values ?? [], projectEntries(branchSnapshots.value[key] ?? []).slice(0, TREE_PAGE_SIZE), entry => entry.item.id))]),
))
const branchEntries = computed<Record<string, DocumentLibraryEntry[]>>(previous => {
  const next = Object.fromEntries([...branchProjections.value].map(([key, values]) => [key, values.value]))
  return previous && Object.keys(previous).length === Object.keys(next).length
    && Object.keys(next).every(key => next[key] === previous[key]) ? previous : next
})
const knownEntries = computed(() => [...entries.value, ...Object.values(branchSnapshots.value).flat()])
const knownEntryIndex = computed(() => {
  const index = new Map<string, DocumentLibraryEntry>()
  // A document can occur in several folders; retain the first placement, as in the list.
  for (const entry of knownEntries.value) if (!index.has(entry.item.id)) index.set(entry.item.id, entry)
  return index
})
const dropTarget = ref<string | null>(null)
const dropPlacement = ref<'inside' | 'before' | 'after'>('inside')
let pendingDrop: Omit<DocumentOrderMove, 'node'> | null = null
let drag: { kind: 'tag' | 'document'; id: string } | null = null
let draggedDocuments: DocumentLibraryEntry[] = []
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
interface ClassificationChange { tag_ids?: string[]; document_ids?: string[]; content_ids?: string[]; tags_changed?: boolean; list_changed?: boolean; classification_catalog?: boolean }
let pendingChanges: ClassificationChange[] = []
let refreshTimer: ReturnType<typeof setTimeout> | undefined
interface TagNode {
  id: string; label: string; tag?: DocumentTag; position: number; entry?: DocumentLibraryEntry
  parentDocumentId?: string; parentDocumentTitle?: string; branchKey?: string
  page?: TreePage; total?: number; titles?: { first_title: string; last_title: string }
  children?: TagNode[]; header?: string; selectable?: boolean
}
function documentTreeNode(entry: DocumentLibraryEntry, tag?: DocumentTag, ancestors: string[] = [], parent?: DocumentLibraryEntry, occurrence?: string): TagNode {
  const branchKey = `doc:${entry.item.id}`
  const node: TagNode = { id: `document:${occurrence ?? tag?.id ?? 'root'}:${entry.item.id}`, label: entry.item.title, tag, entry,
    parentDocumentId: parent?.item.id, parentDocumentTitle: parent?.item.title, branchKey,
    position: entry.position ?? 0, header: 'document', selectable: false }
  const cached = branchEntries.value[branchKey]
  if (entry.children_count || cached?.length || expandedDocuments.value.includes(branchKey)) {
    const path = [...ancestors, entry.item.id]
    node.children = directoryChildren(branchKey, tag, path, entry)
    if (!cached || branchErrors.value[branchKey] || !node.children.length) {
      node.children.push({ id: `status:${node.id}`, label: '', tag, branchKey, position: 0, header: 'document-status', selectable: false })
    }
  }
  return node
}
function directoryChildren(key: string, tag?: DocumentTag, ancestors: string[] = [], parent?: DocumentLibraryEntry, page?: TreePage): TagNode[] {
  const total = branches.totals.value[key] ?? (parent?.children_count || branchEntries.value[key]?.length || 0)
  if (total > TREE_PAGE_SIZE && (!page || page.size > TREE_PAGE_SIZE)) {
    const nodes: TagNode[] = treePages(key, total, page).map(range => {
      const id = treePageKey(range)
      const titles = branches.ranges.value[page ? treePageKey(page) : key]?.find(value => value.offset === range.offset && value.size === range.size)
      return { id, label: titles ? t('common.treePageNames', { first: titles.first_title, last: titles.last_title }) : t('common.treePage', { first: range.offset + 1, last: Math.min(total, range.offset + range.size) }),
        page: range, total, tag, titles, branchKey: treePageDataKey(id), position: range.offset, selectable: false, header: 'virtual-range',
        children: virtualExpanded.value.includes(id) ? directoryChildren(key, tag, ancestors, parent, range)
          : [{ id: id + ':status', label: '', branchKey: treePageDataKey(id), position: 0, header: 'document-status', selectable: false }] }
    })
    if (page && branchErrors.value[treePageKey(page)]) nodes.push({ id: treePageKey(page) + ':status', label: '', branchKey: treePageKey(page), position: 0, header: 'document-status', selectable: false })
    return nodes
  }
  const dataKey = page ? treePageDataKey(treePageKey(page)) : key
  const values = branchEntries.value[dataKey]
  const result = (values ?? []).filter(child => !ancestors.includes(child.item.id)).map(child => documentTreeNode(child, tag, ancestors, parent, page ? treePageKey(page) : undefined))
  if (page && (!result.length || branchErrors.value[dataKey])) result.push({ id: treePageKey(page) + ':status', label: '', branchKey: dataKey, position: 0, header: 'document-status', selectable: false })
  return result
}
const tree = computed<TagNode[]>(previous => {
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
    node.children!.push(...directoryChildren(node.id, node.tag))
    node.children!.sort(compare)
    // Keep empty folders expandable: QTree otherwise turns them into leaves after loading.
    if (!documents || branchErrors.value[node.id] || node.children!.length === 0) {
      node.children!.push({ id: `status:${node.id}`, label: '', tag: node.tag, position: 0, header: 'status', selectable: false })
    }
  }
  roots.push(...directoryChildren('root'))
  roots.sort(compare)
  return reconcileLibraryTree(previous ?? [], roots)
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
  get: () => [...expanded.value, ...virtualExpanded.value, ...[...treeDocumentKeys.value].filter(([, key]) => expandedDocuments.value.includes(key)).map(([id]) => id)],
  set: (value: string[]) => {
    const ranges = value.filter(id => treePageFromKey(id))
    for (const id of virtualExpanded.value) if (!ranges.includes(id)) branches.close(id)
    for (const id of ranges) if (!virtualExpanded.value.includes(id)) void branches.load(id)
    virtualExpanded.value = ranges
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
const visibleTreeDocuments = computed(() => {
  const items: DocumentSelectionItem[] = []
  const open = new Set(treeExpanded.value)
  const visit = (nodes: TagNode[]): void => {
    for (const node of nodes) {
      if (node.entry) items.push({ key: node.id, id: node.entry.item.id })
      if (node.children && open.has(node.id)) visit(node.children)
    }
  }
  visit(displayTree.value as TagNode[])
  return items
})
const displayTree = computed(() => virtualTreeNodes(tree.value, 'id', treeExpanded.value))
watch([treeExpanded, displayTree], () => {
  const visible = new Set(['root', ...expandedDocuments.value.filter(key => treePageFromKey(key))])
  const visibleRanges = new Set<string>()
  for (const item of visibleListDocuments.value) visible.add(`doc:${item.id}`)
  const open = new Set(treeExpanded.value)
  const visit = (nodes: TagNode[]): void => {
    for (const node of nodes) {
      if (node.page) visibleRanges.add(node.id)
      if (node.tag && !node.entry) visible.add(node.tag.id)
      if (node.branchKey) visible.add(node.branchKey)
      if (node.children && open.has(node.id)) visit(node.children)
    }
  }
  visit(displayTree.value as TagNode[])
  branches.cancelHidden(visible)
  for (const key of virtualExpanded.value) {
    const page = treePageFromKey(key)
    const dataKey = treePageDataKey(key)
    if (page && visibleRanges.has(key) && !branchErrors.value[dataKey]) void branches.load(key)
  }
}, { flush: 'post' })
const visibleListDocuments = computed(() => {
  const items: DocumentSelectionItem[] = []
  const visit = (values: DocumentLibraryEntry[], ancestors: string[] = []): void => {
    for (const entry of values) {
      if (ancestors.includes(entry.item.id)) continue
      items.push({ key: entry.item.id, id: entry.item.id })
      const key = `doc:${entry.item.id}`
      if (expandedDocuments.value.includes(key)) visit(listChildren(key), [...ancestors, entry.item.id])
    }
  }
  function listChildren(key: string, page?: TreePage): DocumentLibraryEntry[] {
    const total = branches.totals.value[key] ?? 0
    if (total <= TREE_PAGE_SIZE) return branchEntries.value[key] ?? []
    return treePages(key, total, page).flatMap(range => {
      const id = treePageKey(range)
      if (!expandedDocuments.value.includes(id)) return []
      return range.size > TREE_PAGE_SIZE ? listChildren(key, range) : branchEntries.value[treePageDataKey(id)] ?? []
    })
  }
  visit(visibleEntries.value)
  return items
})
function toggleDocumentPage(key: string, open: boolean): void {
  expandedDocuments.value = open ? [...new Set([...expandedDocuments.value, key])] : expandedDocuments.value.filter(id => id !== key)
  if (!open) branches.close(key)
}
function selectDocument(entry: DocumentLibraryEntry, scope: 'tree' | 'list', key: string, event?: Event): void {
  if (busy.value) return
  const items = scope === 'tree' ? visibleTreeDocuments.value : visibleListDocuments.value
  selection.select(scope, scope === 'list' ? entry.item.id : key, items, event)
  const modifiers = documentSelectionModifiers(event)
  if (!modifiers?.ctrlKey && !modifiers?.metaKey && !modifiers?.shiftKey) {
    requestedDocumentId = props.selectedDocumentId === entry.item.id ? undefined : entry.item.id
    emit('select', entry)
  }
}
watch([visibleTreeDocuments, visibleListDocuments], ([treeItems, listItems]) => {
  if (busy.value || drag) return
  const visible = new Set([...treeItems, ...listItems, ...topicEntries.value.map(entry => ({ id: entry.item.id }))].map(item => item.id))
  selectedDocumentIds.value = selectedDocumentIds.value.filter(id => visible.has(id))
})
const listFilters = computed(() => ({ ...libraryRequestFilters(filters.value), query: query.value ?? '' }))
function publishEntries(incoming?: DocumentLibraryEntry[]): void {
  if (incoming) rememberItems(incoming.map(entry => entry.item))
  const snapshots = [...entries.value, ...Object.values(branchSnapshots.value).flat(), ...topicEntries.value]
  const retained = new Set(snapshots.map(entry => entry.item.id))
  for (const id of Object.keys(libraryItems.value)) if (!retained.has(id)) delete libraryItems.value[id]
  emit('loaded', [...new Map(projectEntries(snapshots, true).map(entry => [entry.item.id, entry])).values()])
}
function onTopicEntries(values: DocumentLibraryEntry[], mode: ClassificationMode): void {
  classificationEntries.set(mode, values)
  topicEntries.value = [...classificationEntries.values()].flat()
  publishEntries(values)
}
function selectClassifiedDocument(entry: DocumentLibraryEntry, event?: Event, key?: string, items?: DocumentSelectionItem[]): void {
  selection.select(treeMode.value, key ?? entry.item.id, items ?? [{ key: entry.item.id, id: entry.item.id }], event)
  const modifiers = documentSelectionModifiers(event)
  if (!modifiers?.ctrlKey && !modifiers?.metaKey && !modifiers?.shiftKey) {
    requestedDocumentId = props.selectedDocumentId === entry.item.id ? undefined : entry.item.id
    emit('select', entry)
  }
}
function startTopicDrag(event: DragEvent, contexts: { entry: DocumentLibraryEntry; keyword: string | null }[]): void {
  if (treeMode.value === 'folders' || busy.value || !canMoveClassification.value || contexts.some(({ entry }) => !entry.item.access.can_write || entry.item.read_only || entry.item.source_managed)) { event.preventDefault(); return }
  clearDrag()
  draggedDocuments = contexts.map(({ entry }) => entry); sourceKeywords = new Map(contexts.map(({ entry, keyword }) => [entry.item.id, keyword]))
  drag = { kind: 'document', id: draggedDocuments[0]!.item.id }; topicDragActive.value = true
  if (!selectedDocumentIds.value.includes(drag.id)) selectedDocumentIds.value = [drag.id]
  setDocumentDragData(event, draggedDocuments)
}
async function moveTopicDocuments(topicId: string | null, keyword?: string | null): Promise<void> {
  const values = draggedDocuments
  const sources = sourceKeywords, mode = treeMode.value
  const source = keyword === undefined ? null : sourceKeyword
  const authSnapshot = authSessionGeneration()
  clearDrag()
  if (!canMoveClassification.value || busy.value || !values.length) return
  const session = sessionGeneration
  busy.value = true
  const failed: string[] = []
  const dismiss = values.length > 1 ? $q.notify({ type: 'ongoing', timeout: 0, group: false, message: t('documents.bulk.moving', { count: values.length }) }) : undefined
  try {
    if (values.length > 1) {
      try {
        if (mode === 'agents') await documentService.changeOwnerBatch(values.map(({ item }) => {
          const previous = sources.get(item.id) ?? source
          return { document_id: item.id, expected_revision: item.revision, expected_lock_version: item.lock_version,
            kind: topicId === null ? 'user' : 'agent', id: topicId === null ? authStore.user!.id : Number(topicId),
            keywords: keyword === undefined ? item.keywords : keyword === null ? [] : [...new Set([...item.keywords.filter(value => value !== previous), keyword])] }
        }))
        else await documentService.moveClassificationBatch(values.map(({ item }) => ({ id: item.id, topic_id: topicId,
          expected_topic_id: item.topic_id ?? null, expected_lock_version: item.lock_version,
          source_keyword: keyword === undefined ? null : sources.get(item.id) ?? source, keyword: keyword ?? null, clear_keywords: keyword === null })))
      } catch { failed.push(...values.map(entry => entry.item.id)) }
    } else for (const entry of values) {
      if (disposed || session !== sessionGeneration) return
      try {
        if (mode === 'agents') {
          const previous = sources.get(entry.item.id) ?? source
          const keywords = keyword === undefined ? entry.item.keywords : keyword === null ? []
            : [...new Set([...entry.item.keywords.filter(value => value !== previous), keyword])]
          await documentService.changeDocumentOwner(entry.item.id, entry.item.revision, entry.item.lock_version,
            topicId === null ? 'user' : 'agent', topicId === null ? authStore.user!.id : Number(topicId), keywords)
        } else await documentService.moveDocumentClassification(entry.item.id, { topic_id: topicId,
          expected_topic_id: entry.item.topic_id ?? null, expected_lock_version: entry.item.lock_version,
          source_keyword: keyword === undefined ? null : sources.get(entry.item.id) ?? source, keyword: keyword ?? null, clear_keywords: keyword === null })
      } catch { failed.push(entry.item.id) }
    }
    if (disposed || session !== sessionGeneration) return
    if (failed.length && values.length === 1) $q.notify({ type: 'negative', message: t('documents.library.error') })
    selectedDocumentIds.value = failed
    queueChange({ document_ids: values.map(entry => entry.item.id), list_changed: true })
    await flushChanges()
  } finally {
    dismiss?.()
    if (values.length > 1 && authSessionGeneration() === authSnapshot) $q.notify({ type: failed.length ? 'negative' : 'positive',
      message: failed.length ? t('documents.bulk.moveFailed') : t('documents.bulk.moved', { count: values.length }) })
    if (session === sessionGeneration) busy.value = false
  }
}
async function moveClassificationSelection(contexts: { entry: DocumentLibraryEntry; keyword: string | null }[], target: string | null, keyword?: string | null): Promise<void> {
  draggedDocuments = contexts.map(({ entry }) => entry)
  sourceKeywords = new Map(contexts.map(({ entry, keyword }) => [entry.item.id, keyword]))
  await moveTopicDocuments(target, keyword)
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
    classification: treeMode.value === 'folders' && onlyUnclassified.value ? 'unclassified' : 'all',
    topic_classification: treeMode.value === 'topics' && onlyUnclassified.value ? 'unclassified' : 'all',
    agent_classification: treeMode.value === 'agents' && onlyUnclassified.value ? 'unclassified' : 'all',
    tag_id: null, limit: pageSize.value, offset: (page.value - 1) * pageSize.value,
  }
  loading.value = true; loadError.value = false
  try {
    const result = await documentService.browseDocumentLibrary(request, controller.signal)
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
    const result = await documentService.listDocumentTags()
    if (disposed || current !== tagGeneration) return
    if (userId.value !== result.user_id) { userId.value = result.user_id; restoreSplit() }
    tags.value = reconcileLibrarySnapshot(tags.value, result.tags, tag => tag.id); tagError.value = false
    expanded.value = expanded.value.filter(id => result.tags.some(tag => tag.id === id))
    for (const id of Object.keys(branchSnapshots.value)) if (id !== 'root' && !id.startsWith('doc:') && !result.tags.some(tag => tag.id === id)) branches.forget(id)
  } catch { if (!disposed && current === tagGeneration) tagError.value = true }
}
async function refreshTree(ids = ['root', ...expanded.value, ...expandedDocuments.value]): Promise<void> {
  await Promise.all([...new Set(ids)].map(id => {
    const page = treePageFromKey(id)
    const parent = page?.parent ?? id
    if (parent !== 'root' && !expanded.value.includes(parent) && !expandedDocuments.value.includes(parent)
      || page && !virtualExpanded.value.includes(id)) { branches.forget(id); return }
    return branches.refresh(id)
  }))
}
async function refresh(): Promise<void> { await Promise.all([reload(), refreshTree(), reconcileClassifications()]) }
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
function applyDocumentMove(move: DocumentOrderMove, source?: DocumentLibraryEntry): void {
  const id = move.node.id
  const entry = [...entries.value, ...Object.values(branchSnapshots.value).flat()].find(value => value.item.id === id) ?? source
  if (!entry) return
  const target = move.parent_document_id ? `doc:${move.parent_document_id}` : move.parent_id ?? (move.at_root ? 'root' : null)
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
  for (const navigation of classificationNavigations.values()) navigation.removeDocument(id)
  topicEntries.value = topicEntries.value.filter(entry => entry.item.id !== id)
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
function updateDocument(document: DocumentRecord): void {
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
  const rootChanged = changes.some(change => change.list_changed || change.document_ids?.length || change.content_ids?.length)
  const ids = [...new Set([...(rootChanged ? ['root'] : []), ...changes.flatMap(change => [...(change.tag_ids ?? []), ...documentFolders([...(change.document_ids ?? []), ...(change.content_ids ?? [])]),
    ...(change.document_ids ?? []).map(id => `doc:${id}`)])])]
  if (changes.some(change => change.tags_changed)) await loadTags()
  if (disposed || session !== sessionGeneration || access !== accessGeneration) return
  await Promise.all([refreshTree(ids), ...(changes.some(change => change.list_changed) ? [reload()] : [])])
  if (rootChanged) {
    const changedDocuments = [...new Set(changes.flatMap(change => [...(change.document_ids ?? []), ...(change.content_ids ?? [])]))]
    await reconcileClassifications(changedDocuments.length || changes.every(change => change.classification_catalog) ? changedDocuments : undefined)
  }
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
  websocket.onEvent('document', 'invalidate', invalidateAccess)
  websocket.onEvent('document', 'classification', classificationChanged)
  websocket.onConnect(reconnect)
})
onBeforeUnmount(() => {
  websocket.offEvent('document', 'invalidate', invalidateAccess)
  websocket.offEvent('document', 'classification', classificationChanged)
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
  return mutate(() => documentService.saveDocumentTag({ name: tag.name, parent_id: tag.parent_id, icon: tag.icon }, tag.id))
}
async function sortFolder(id: string, descending: boolean): Promise<void> {
  await mutate(() => documentService.sortDocumentFolder(id, descending), { tags_changed: true, tag_ids: [id] })
}
function expandFolder(id: string, expand: boolean): void {
  const branch = tags.value.filter(tag => isDescendant(tag.id, id)).map(tag => tag.id)
  expanded.value = expand ? [...new Set([...expanded.value, ...branch])] : expanded.value.filter(value => !branch.includes(value))
}
async function createTag(name: string, parentId: string | null, afterTagId?: string): Promise<boolean> {
  const creation: { tag?: DocumentTag } = {}
  const session = sessionGeneration
  const saved = await mutate(async () => {
    creation.tag = await documentService.saveDocumentTag({ name, parent_id: parentId })
    if (afterTagId && !disposed && session === sessionGeneration) {
      try {
        await documentService.reorderDocuments({ node: { kind: 'tag', id: creation.tag.id }, parent_id: parentId,
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
    const result = await documentService.deleteDocumentTag(tag.id, confirmed)
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
  clearDrag()
  documentFromTree = false
  drag = { kind: 'tag', id }; event.dataTransfer?.setData('text/plain', id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function startDocumentDrag(event: DragEvent, id: string): void {
  if (busy.value) { event.preventDefault(); return }
  sourceKeyword = null
  topicDragActive.value = treeMode.value !== 'folders' && canMoveClassification.value
  documentFromTree = event.target instanceof Element && Boolean(event.target.closest('.document-tree, .document-children'))
  const known = knownEntries.value
  const ordered = (documentFromTree ? visibleTreeDocuments.value : visibleListDocuments.value)
    .flatMap(value => { const entry = knownEntryIndex.value.get(value.id); return entry ? [entry] : [] })
  draggedDocuments = treeMode.value !== 'folders'
    ? ordered.filter(entry => selectedDocumentIds.value.includes(id) ? selectedDocumentIds.value.includes(entry.item.id) : entry.item.id === id)
    : documentDragSelection(id, selectedDocumentIds.value, ordered, known)
  if (!selectedDocumentIds.value.includes(id)) { selection.clear(); selectedDocumentIds.value = [id] }
  drag = { kind: 'document', id }
  setDocumentDragData(event, draggedDocuments)
}
function startDocumentSelectionDrag(event: DragEvent, values: DocumentLibraryEntry[]): void {
  if (busy.value || !values.length) { event.preventDefault(); return }
  clearDrag()
  const known = [...entries.value, ...Object.values(branchSnapshots.value).flat(), ...values]
  draggedDocuments = treeMode.value !== 'folders' ? values : documentDragSelection(values[0]!.item.id, values.map(entry => entry.item.id), values, known)
  drag = { kind: 'document', id: values[0]!.item.id }
  documentFromTree = true
  topicDragActive.value = treeMode.value !== 'folders' && canMoveClassification.value
  selectedDocumentIds.value = values.map(entry => entry.item.id)
  setDocumentDragData(event, draggedDocuments)
}
async function moveDocuments(values: DocumentLibraryEntry[], target: Omit<DocumentOrderMove, 'node'>): Promise<void> {
  if (busy.value || !values.length) return
  const session = sessionGeneration
  // Moving into a shared folder can invalidate access through our own writes.
  // Each request is authorized afresh; only a new session stops the batch.
  const active = () => !disposed && session === sessionGeneration
  const failed: string[] = []
  let anchor = target.anchor
  busy.value = true
  const authSession = authSessionGeneration()
  const dismiss = values.length > 1 ? $q.notify({ type: 'ongoing', timeout: 0, group: false, message: t('documents.bulk.moving', { count: values.length }) }) : undefined
  try {
    if (values.length > 1) {
      try {
        await documentService.moveDocumentBatch(values.map(entry => entry.item.id), target)
        if (!active()) return
        for (const entry of values) {
          const move: DocumentOrderMove = { ...target, anchor, node: { kind: 'document', id: entry.item.id } }
          applyDocumentMove(move, entry)
          if (anchor && target.after) anchor = move.node
        }
        queueChange({ document_ids: values.map(entry => entry.item.id), list_changed: true })
      } catch {
        failed.push(...values.map(entry => entry.item.id))
        if (!active()) return
      }
    } else for (const entry of values) {
      if (!active()) return
      const move: DocumentOrderMove = { ...target, anchor, node: { kind: 'document', id: entry.item.id } }
      try {
        if (!move.anchor && !move.list_only && !move.parent_document_id) await documentService.moveDocumentToTag(entry.item.id, move.parent_id, move.at_root)
        else await documentService.reorderDocuments(move)
        if (!active()) return
        applyDocumentMove(move, entry)
        queueChange({ document_ids: [entry.item.id, ...(move.parent_document_id ? [move.parent_document_id] : [])], list_changed: true })
        // Inserting repeatedly after the original anchor would reverse the group.
        if (anchor && target.after) anchor = move.node
      } catch {
        if (!active()) return
        failed.push(entry.item.id)
      }
    }
    if (failed.length) {
      selectedDocumentIds.value = failed
      if (values.length === 1) $q.notify({ type: 'negative', message: t('documents.library.error') })
    }
    if (target.list_only && (filters.value.sort_by !== 'position' || filters.value.sort_desc)) {
      preserveSelectionOnSort = true
      filters.value = { ...filters.value, sort_by: 'position', sort_desc: false }
    }
  } finally {
    dismiss?.()
    if (values.length > 1 && authSessionGeneration() === authSession) $q.notify({ type: failed.length ? 'negative' : 'positive',
      message: failed.length ? t('documents.bulk.moveFailed') : t('documents.bulk.moved', { count: values.length }) })
    if (!disposed && session === sessionGeneration) {
      busy.value = false
      if (pendingChanges.length) void flushChanges()
    }
  }
}
function dragOver(event: DragEvent, target: string): void {
  if (treeMode.value !== 'folders') {
    if (busy.value || !topicDragActive.value || !canMoveClassification.value) return
    event.preventDefault(); dropTarget.value = target
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
    return
  }
  if (fileDragOver(event, target)) return
  if (!drag || busy.value || (drag.kind === 'tag' && isDescendant(target, drag.id))) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTarget.value = target
  dropPlacement.value = 'inside'; pendingDrop = null
}
function dragOverNode(event: DragEvent, anchor: DocumentOrderNode, parentId: string | null, listOnly = false, key = anchor.id): void {
  pendingDrop = null; dropTarget.value = null
  if (fileDragOver(event, key)) {
    pendingDrop = { parent_id: anchor.id }
    return
  }
  if (!drag || busy.value || (drag.kind === anchor.kind && drag.id === anchor.id) || (listOnly && drag.kind === 'tag')) return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = (event.clientY - bounds.top) / bounds.height
  const inside = anchor.kind === 'tag' && ratio >= 0.25 && ratio <= 0.75
  // Folders precede root documents; only their center accepts a document.
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
  if (treeMode.value !== 'folders') { dragOver(event, 'root'); return }
  pendingDrop = null; dropTarget.value = null
  if (fileDragOver(event, `doc:${entry.item.id}`)) {
    pendingDrop = { parent_id: null, parent_document_id: entry.item.id }
    return
  }
  if (!drag || busy.value || drag.kind !== 'document' || draggedDocuments.some(value => value.item.id === entry.item.id)) return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = (event.clientY - bounds.top) / bounds.height
  const inside = ratio >= 0.25 && ratio <= 0.75
  const parent = inside ? entry.item.id : parentDocumentId
  // Known descendants are rejected immediately; the server checks the entire stored hierarchy.
  let ancestor = parent
  const seen = new Set<string>()
  while (ancestor && !seen.has(ancestor)) {
    if (draggedDocuments.some(value => value.item.id === ancestor)) return
    seen.add(ancestor); ancestor = knownEntryIndex.value.get(ancestor)?.parent_document_id
  }
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropTarget.value = `doc:${entry.item.id}`
  dropPlacement.value = inside ? 'inside' : ratio < 0.5 ? 'before' : 'after'
  pendingDrop = {
    parent_id: parent ? null : tagId ?? null,
    ...(parent ? { parent_document_id: parent } : {}),
    list_only: !inside && !parent && listOnly && !documentFromTree,
    ...(!inside && !parent && !tagId && !listOnly ? { at_root: true } : {}),
    ...(inside ? {} : { anchor: { kind: 'document', id: entry.item.id }, after: ratio >= 0.5 }),
  }
}
function dropClass(key: string): Record<string, boolean> {
  return { 'tag-row--drop': dropTarget.value === key && dropPlacement.value === 'inside',
    'node-drop-before': dropTarget.value === key && dropPlacement.value === 'before',
    'node-drop-after': dropTarget.value === key && dropPlacement.value === 'after' }
}
function fileDragOver(event: DragEvent, key: string): boolean {
  if (!event.dataTransfer?.types.includes('Files')) return false
  event.preventDefault()
  const allowed = canCreateDocument.value && !busy.value && !props.importingFiles
  event.dataTransfer.dropEffect = allowed ? 'copy' : 'none'
  dropTarget.value = allowed ? key : null
  dropPlacement.value = 'inside'
  pendingDrop = null
  return true
}
function dropFiles(event: DragEvent, target: Omit<DocumentOrderMove, 'node'> | null): boolean {
  if (!event.dataTransfer?.types.includes('Files')) return false
  const files = [...event.dataTransfer.files]
  const allowed = canCreateDocument.value && !busy.value && !props.importingFiles
  clearDrag()
  if (allowed && files.length && target) {
    const tag = tags.value.find(tag => tag.id === target.parent_id)
    const parent = target.parent_document_id ? knownEntryIndex.value.get(target.parent_document_id) : undefined
    emit('filesDropped', files, tag, parent, target.at_root)
  }
  return true
}
async function dropNode(event: DragEvent): Promise<void> {
  if (treeMode.value !== 'folders') { await moveTopicDocuments(null); return }
  if (dropFiles(event, pendingDrop)) return
  const node = drag; const target = pendingDrop; const documents = draggedDocuments; clearDrag()
  if (!node || !target) return
  if (node.kind === 'document') { await moveDocuments(documents, target); return }
  if (!target.anchor && !target.list_only) {
    const tag = tags.value.find(value => value.id === node.id)
    if (tag) await mutate(() => documentService.saveDocumentTag({ name: tag.name, parent_id: target.parent_id }, tag.id))
  } else await mutate(() => documentService.reorderDocuments({ node, ...target }), {
    tags_changed: !target.list_only,
    tag_ids: target.list_only || !target.parent_id ? [] : [target.parent_id],
    list_changed: target.list_only,
  })
  if (target.parent_id && !expanded.value.includes(target.parent_id)) expanded.value.push(target.parent_id)
}
function clearDrag(): void { cancelModeHover(); drag = null; draggedDocuments = []; sourceKeyword = null; sourceKeywords = new Map(); topicDragActive.value = false; documentFromTree = false; dropTarget.value = null; pendingDrop = null }
async function drop(parentId: string | null, atRoot = false, event?: DragEvent): Promise<void> {
  if (treeMode.value !== 'folders') { await moveTopicDocuments(null); return }
  if (event && dropFiles(event, { parent_id: parentId, at_root: atRoot })) return
  const value = drag; const documents = draggedDocuments; clearDrag()
  if (!value) return
  if (value.kind === 'document') { await moveDocuments(documents, { parent_id: parentId, at_root: atRoot }); return }
  const tag = tags.value.find(tag => tag.id === value.id)
  if (!tag || (parentId && isDescendant(parentId, tag.id))) return
  await mutate(() => documentService.saveDocumentTag({ name: tag.name, parent_id: parentId }, tag.id))
}
watch(treeMode, () => { if (!drag) clearDrag(); onlyUnclassified.value = true })
watch([query, filters, pageSize, onlyUnclassified, treeMode], () => {
  if (!preserveSelectionOnSort) selection.clear()
  preserveSelectionOnSort = false
  if (!ready) return
  if (page.value !== 1) page.value = 1
  else void reload()
})
watch(page, () => { selection.clear(); if (ready) void reload() })
watch(() => [...expanded.value], (value, previous) => {
  for (const id of previous) if (!value.includes(id)) branches.close(id)
  for (const id of value) if (!previous.includes(id)) void branches.load(id)
})
const storageKey = computed(() => `galaris:document-library-split:${userId.value ?? 'session'}`)
function restoreSplit(): void {
  try {
    const stored = localStorage.getItem(storageKey.value)
    const value = stored === null ? NaN : Number(stored)
    split.value = value >= 0 && value <= 100 ? value : 35
  } catch { split.value = 35 }
}
watch(split, value => { try { localStorage.setItem(storageKey.value, String(value)) } catch { /* Storage may be unavailable. */ } })
async function changeSession(event: Event): Promise<void> {
  const currentSession = authSessionGeneration()
  if ((event as CustomEvent<string | null>).detail !== null && currentSession === authSession) return
  authSession = currentSession
  selection.clear()
  const session = ++sessionGeneration
  classificationEntries.clear()
  ++treeSession.value
  ++facetsGeneration
  listController?.abort()
  pendingChanges = []
  if (refreshTimer) clearTimeout(refreshTimer)
  ++generation; ++tagGeneration; entries.value = []; topicEntries.value = []; libraryItems.value = shallowReactive<Record<string, DocumentRecord>>({}); tags.value = []; owners.value = []; keywords.value = []; total.value = 0
  deleteDialog.value = false; editingTag.value = null; renameTagId.value = null; userId.value = null; busy.value = false; expanded.value = []; branches.reset(); clearDrag()
  expandedDocuments.value = []; virtualExpanded.value = []; requestedDocumentId = undefined
  ready = false; reset(); page.value = 1; await loadTags()
  if (disposed || session !== sessionGeneration) return
  ready = true; await Promise.all([reload(), branches.load('root')])
}
onMounted(async () => {
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession)
  ready = true
  await Promise.all([loadTags(), reload(), branches.load('root')])
})
onBeforeUnmount(() => { disposed = true; ++generation; ++tagGeneration; listController?.abort(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession) })
defineExpose({ reload: refresh, refreshDocuments, removeDocument, updateDocument, startDocumentSelectionDrag, clearDrag })
</script>
<style scoped>
.library-navigation { height: 100%; min-height: 0; }
.document-library-tabs { background: var(--solaire-gray-light); }
.library-navigation--dark .document-library-tabs { background: var(--solaire-gray-dark); }
/* Outrank shell tab sizing, including its mobile min-height !important. */
.library-navigation .document-library-tabs.q-tabs :deep(.q-tab) { min-height: 0 !important; padding: 0 12px; }
.library-navigation .document-library-tabs.q-tabs :deep(.q-tab__content) { padding: 7px 0; gap: 8px; }
.library-navigation .document-library-tabs.q-tabs :deep(.q-tab__icon) { width: 18px; height: 18px; font-size: 18px; margin: 0; color: var(--solaire-blue-accent); }
.document-library-tabs :deep(.q-tab__icon:has(img[src="/menu-icons/folder_copy.svg"])) { background: currentColor; mask: url('/menu-icons/folder_copy.svg') center / contain no-repeat; }
.document-library-tabs :deep(.q-tab__icon:has(img[src="/menu-icons/people.svg"])) { background: currentColor; mask: url('/menu-icons/people.svg') center / contain no-repeat; }
.document-library-tabs :deep(.q-tab__icon img[src^="/menu-icons/"]) { opacity: 0; }
.library-navigation .document-library-tabs.q-tabs :deep(.q-tab__label) { padding-left: 0; font-size: 14px; line-height: 1.2; }
.library-error { color: var(--solaire-red-accent); background: var(--solaire-red-light); }
.library-navigation--dark .library-error { background: var(--solaire-red-dark); }
.library-navigation :deep(.q-splitter__panel) { min-height: 0; overflow: auto; }
.tag-row { min-width: 0; }
.tag-row--drop { background: var(--solaire-blue-light); }
.node-drop-before { box-shadow: inset 0 2px var(--solaire-blue-accent); }
.node-drop-after { box-shadow: inset 0 -2px var(--solaire-blue-accent); }
.document-tree :deep(.q-tree__arrow), .document-tree :deep(.q-tree__spinner) { color: var(--solaire-gray-accent); }
.document-tree :deep(.q-tree__node-header) { min-height: 28px; }
.document-tree :deep(.q-tree__node-header :is(.tag-actions, .document-actions)) { display: none; opacity: 0; pointer-events: none; }
.document-tree :deep(.q-tree__node-header:hover :is(.tag-actions, .document-actions)),
.document-tree :deep(.q-tree__node-header:has(.document-create-menu-open) :is(.tag-actions, .document-actions)),
.document-tree :deep(.q-tree__node-header:has(.document-tag-row--menu-open, .action-context-menu--open) :is(.tag-actions, .document-actions)),
.document-tree :deep(.q-tree__node-header:has(:focus-visible) :is(.tag-actions, .document-actions)) { display: flex; opacity: 1; pointer-events: auto; }
.document-tree :deep(.q-tree__node-header:has(.document-tag-row--menu-open, .action-context-menu--open)) { background: var(--solaire-blue-light); }
.library-navigation--dark .document-tree :deep(.q-tree__node-header:has(.document-tag-row--menu-open, .action-context-menu--open)) { background: var(--solaire-blue-dark); }
@media (hover: none) {
  .document-tree :deep(.q-tree__node-header :is(.tag-actions, .document-actions)) { display: flex; opacity: 1; pointer-events: auto; }
}
.document-list-panel { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.document-list-scroll { flex: 1; min-height: 0; overflow: auto; }
.library-pagination { flex-shrink: 0; gap: 4px 12px; }
.tag-dialog { width: min(440px, calc(100vw - 24px)); }
.library-navigation--dark .tag-row--drop { background: var(--solaire-blue-dark); }
</style>
