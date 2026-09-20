<template>
  <q-splitter v-model="split" horizontal :limits="[15, 65]" class="library-navigation" :class="{ 'library-navigation--dark': $q.dark.isActive }">
    <template #before>
      <div class="q-pa-sm">
        <q-banner v-if="tagError" dense class="library-error" role="alert">{{ t('documents.library.tagError') }}<q-btn flat :label="t('documents.retry')" @click="loadTags" /></q-banner>
        <q-tree v-model:expanded="expanded" :nodes="tree" node-key="id" dense no-transition class="document-tree">
          <template #default-header="{ node }">
            <div class="tag-row row items-center no-wrap full-width"
              :class="dropClass(node.id)"
              @dragstart.stop="startTagDrag($event, node.id)" @dragend="clearDrag"
              @dragover.stop="dragOverNode($event, { kind: 'tag', id: node.id }, node.tag.parent_id)" @dragleave="dropTarget = null" @drop.prevent.stop="dropNode">
              <DocumentTagRow :key="`${userId}:${node.id}`" :tag="node.tag" :selected="expanded.includes(node.id)" :busy="busy" :save="saveTag" :create="createTag"
                :rename-on-create="renameTagId === node.id" @renamed="renameTagId === node.id && (renameTagId = null)"
                @sort="sortFolder(node.id, $event)" @expand="expandFolder(node.id, true)" @collapse="expandFolder(node.id, false)"
                @delete="requestDelete(node.tag)" />
            </div>
          </template>
          <template #header-document="{ node }">
            <div class="full-width" :class="dropClass(node.id)" :aria-label="t('documents.library.tagDocuments', { name: node.tag.name })"
              @dragover.stop="dragOverNode($event, { kind: 'document', id: node.entry.item.id }, node.tag.id, false, node.id)"
              @dragleave="dropTarget = null" @drop.prevent.stop="dropNode">
              <DocumentLibraryEntryRow :selected-document-id="selectedDocumentId" :entry="node.entry" :loading="false" compact @select="emit('select', $event)"
                @dragstart="startDocumentDrag" @dragend="clearDrag" />
            </div>
          </template>
          <template #header-status="{ node }">
            <div class="full-width text-caption" @click.stop>
              <div v-if="branchErrors[node.tag.id]" class="library-error q-pa-sm" role="alert">{{ t('documents.loadError') }} <q-btn flat dense :label="t('documents.retry')" @click="branches.load(node.tag.id)" /></div>
              <span v-else-if="branchEntries[node.tag.id]">{{ t('documents.library.emptyFolder') }}</span>
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
          <DocumentLibraryFilters v-model="filters" v-model:only-unclassified="onlyUnclassified" :owners="owners" :keywords="keywords" />
          <q-btn v-if="hasFilters" flat round dense icon="filter_alt_off" :aria-label="t('documents.library.reset')" @click="reset" />
          <q-btn flat round dense icon="add" :aria-label="t('documents.createDocument')" @click="emit('create')" />
        </div>
        <q-banner v-if="loadError" dense class="library-error" role="alert">{{ t('documents.loadError') }}<q-btn flat :label="t('documents.retry')" @click="reload" /></q-banner>
        <q-list class="document-list-scroll" separator :aria-busy="loading" :aria-label="t(onlyUnclassified ? 'documents.library.orphans' : 'documents.library.all')">
          <DocumentLibraryEntryRow v-for="entry in entries" :key="entry.item.id" :selected-document-id="selectedDocumentId" :entry="entry" :loading="false"
            :class="dropClass(`list:${entry.item.id}`)" @dragover.stop="dragOverNode($event, { kind: 'document', id: entry.item.id }, null, true, `list:${entry.item.id}`)"
            @dragleave="dropTarget = null" @drop.prevent.stop="dropNode"
            @select="emit('select', $event)" @dragstart="startDocumentDrag" @dragend="clearDrag" />
          <div v-if="!loading && !loadError && !entries.length" class="q-pa-md text-caption">{{ t('documents.empty') }}</div>
        </q-list>
        <div class="library-pagination row items-center justify-center q-pa-xs">
          <span class="text-caption">{{ t('documents.library.pageRange', { first: entries.length ? (page - 1) * pageSize + 1 : 0, last: entries.length ? (page - 1) * pageSize + entries.length : 0, total }) }}</span>
          <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" dense borderless :aria-label="t('documents.library.pageSize')">
            <template #selected>{{ t('documents.library.perPage', { count: pageSize }) }}</template>
          </q-select>
          <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="3" direction-links boundary-numbers size="sm" />
        </div>
      </div>
    </template>
  </q-splitter>
  <q-dialog v-model="deleteDialog">
    <q-card class="tag-dialog">
      <q-card-section class="galaris-dialog-title row items-center"><span class="text-h6">{{ t('documents.library.deleteTag') }}</span><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section>{{ t('documents.library.deleteExplanation', { name: editingTag?.name }) }}</q-card-section>
      <q-card-actions align="right"><q-btn v-close-popup flat :label="t('documents.library.cancel')" /><q-btn color="primary" :loading="busy" :label="t('documents.library.deleteTag')" @click="editingTag && requestDelete(editingTag, true)" /></q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { websocket } from '@/core/websocket'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import type { DocumentLibraryEntry, DocumentOwnerOption, DocumentTag, DocumentOrderNode, DocumentOrderMove } from '../types'
import { memoryService } from '../services/memoryService'
import { defaultLibraryFilters, libraryRequestFilters } from '../libraryFilterState'
import DocumentLibraryFilters from './DocumentLibraryFilters.vue'
import DocumentTagCreateButton from './DocumentTagCreateButton.vue'
import DocumentTagRow from './DocumentTagRow.vue'
import { useDocumentBranches } from '../useDocumentBranches'
import DocumentLibraryEntryRow from './DocumentLibraryEntryRow.vue'
import DocumentSplitterHandle from './DocumentSplitterHandle.vue'
defineProps<{ selectedDocumentId: string | null }>()
const emit = defineEmits<{ select: [entry: DocumentLibraryEntry]; loaded: [entries: DocumentLibraryEntry[]]; create: [] }>()
const { t } = useI18n()
const $q = useQuasar()
const userId = ref<number | null>(null)
const split = ref(35)
const tags = ref<DocumentTag[]>([])
const expanded = ref<string[]>([])
const renameTagId = ref<string | null>(null)
const onlyUnclassified = ref(true)
const entries = ref<DocumentLibraryEntry[]>([])
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
const { entries: branchEntries, errors: branchErrors } = branches
const dropTarget = ref<string | null>(null)
const dropPlacement = ref<'inside' | 'before' | 'after'>('inside')
let pendingDrop: Omit<DocumentOrderMove, 'node'> | null = null
let drag: { kind: 'tag' | 'document'; id: string } | null = null
let documentFromTree = false
let generation = 0
let tagGeneration = 0
let disposed = false
let ready = false
let sessionGeneration = 0
interface ClassificationChange { tag_ids?: string[]; document_ids?: string[]; tags_changed?: boolean; list_changed?: boolean }
let pendingChanges: ClassificationChange[] = []
let refreshTimer: ReturnType<typeof setTimeout> | undefined
interface TagNode { id: string; label: string; tag: DocumentTag; position: number; entry?: DocumentLibraryEntry; children?: TagNode[]; header?: string; selectable?: boolean }
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
    node.children!.push(...(documents ?? []).map(entry => ({ id: `document:${node.id}:${entry.item.id}`, label: entry.item.title,
      tag: node.tag, entry, position: entry.position ?? 0, header: 'document', selectable: false })))
    node.children!.sort(compare)
    // Keep empty folders expandable: QTree otherwise turns them into leaves after loading.
    if (!documents || branchErrors.value[node.id] || node.children!.length === 0) {
      node.children!.push({ id: `status:${node.id}`, label: '', tag: node.tag, position: 0, header: 'status', selectable: false })
    }
  }
  roots.sort(compare)
  return roots
})
const listFilters = computed(() => ({ ...libraryRequestFilters(filters.value), query: query.value ?? '' }))
function publishEntries(): void {
  emit('loaded', [...new Map([...entries.value, ...Object.values(branchEntries.value).flat()].map(entry => [entry.item.id, entry])).values()])
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
  loading.value = true; loadError.value = false
  try {
    const result = await memoryService.browseDocumentLibrary({ ...listFilters.value, include_owners: true, classification: onlyUnclassified.value ? 'unclassified' : 'all', tag_id: null, limit: pageSize.value, offset: (page.value - 1) * pageSize.value })
    if (disposed || current !== generation) return
    total.value = result.total
    owners.value = result.owners ?? []
    keywords.value = result.keywords
    if (page.value > Math.max(1, Math.ceil(result.total / pageSize.value))) {
      page.value = Math.max(1, Math.ceil(result.total / pageSize.value)); return
    }
    entries.value = result.entries
    publishEntries()
  } catch { if (!disposed && current === generation) { loadError.value = true; entries.value = [] } }
  finally { if (!disposed && current === generation) loading.value = false }
}
async function loadTags(): Promise<void> {
  const current = ++tagGeneration
  try {
    const result = await memoryService.listDocumentTags()
    if (disposed || current !== tagGeneration) return
    if (userId.value !== result.user_id) { userId.value = result.user_id; restoreSplit() }
    tags.value = result.tags; tagError.value = false
    expanded.value = expanded.value.filter(id => result.tags.some(tag => tag.id === id))
    for (const id of Object.keys(branchEntries.value)) if (!result.tags.some(tag => tag.id === id)) branches.forget(id)
  } catch { if (!disposed && current === tagGeneration) tagError.value = true }
}
async function refreshTree(ids = expanded.value): Promise<void> {
  await Promise.all([...new Set(ids)].map(id => {
    if (!expanded.value.includes(id)) { branches.forget(id); return }
    return branches.refresh(id)
  }))
}
async function refresh(): Promise<void> { await Promise.all([reload(), refreshTree()]) }
function documentFolders(ids: string[]): string[] {
  return Object.entries(branchEntries.value).filter(([, values]) => values.some(entry => ids.includes(entry.item.id))).map(([id]) => id)
}
function queueChange(change: ClassificationChange): void {
  pendingChanges.push(change)
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { refreshTimer = undefined; if (!busy.value) void flushChanges() }, 100)
}
async function flushChanges(): Promise<void> {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = undefined
  const changes = pendingChanges.splice(0)
  if (!changes.length || disposed) return
  const session = sessionGeneration
  const ids = [...new Set(changes.flatMap(change => [...(change.tag_ids ?? []), ...documentFolders(change.document_ids ?? [])]))]
  if (changes.some(change => change.tags_changed)) await loadTags()
  if (disposed || session !== sessionGeneration) return
  await Promise.all([refreshTree(ids), ...(changes.some(change => change.list_changed) ? [reload()] : [])])
  if (disposed || session !== sessionGeneration) return
  const refreshed = new Map(ids.flatMap(id => branchEntries.value[id] ?? []).map(entry => [entry.item.id, entry]))
  entries.value = entries.value.map(entry => {
    const current = refreshed.get(entry.item.id)
    return current ? { ...current, position: entry.position } : entry
  })
  publishEntries()
}
function classificationChanged(event: { data: ClassificationChange & { user_id: number } }): void {
  if (event.data.user_id === userId.value) queueChange(event.data)
}
function refreshDocuments(ids: string[]): void {
  queueChange({ document_ids: ids, list_changed: true })
}
function invalidateAccess(): void {
  pendingChanges = []
  ++generation
  entries.value = []; owners.value = []; keywords.value = []; total.value = 0
  branches.reset()
  publishEntries()
  const session = sessionGeneration
  void loadTags().then(() => {
    if (!disposed && session === sessionGeneration) return refresh()
  })
}
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'invalidate', invalidateAccess)
  websocket.onEvent('memory', 'classification', classificationChanged)
  websocket.onConnect(invalidateAccess)
})
onBeforeUnmount(() => {
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offEvent('memory', 'classification', classificationChanged)
  websocket.offConnect(invalidateAccess)
  if (refreshTimer) clearTimeout(refreshTimer)
})
function reset(): void { query.value = ''; filters.value = defaultLibraryFilters(); onlyUnclassified.value = true }
async function mutate(action: () => Promise<unknown>, change: ClassificationChange = { tags_changed: true }): Promise<boolean> {
  if (busy.value) return false
  const session = sessionGeneration
  busy.value = true
  try {
    await action()
    if (disposed || session !== sessionGeneration) return false
    queueChange(change)
    await flushChanges()
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
    const documents = Object.values(branchEntries.value).flat().filter(entry => entry.tags?.some(value => removed.includes(value.id))).map(entry => entry.item.id)
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
  drag = { kind: 'document', id }; event.dataTransfer?.setData('text/plain', id)
  documentFromTree = event.target instanceof Element && Boolean(event.target.closest('.document-tree'))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
async function moveDocument(documentId: string, tagId: string | null): Promise<void> {
  const entry = [...entries.value, ...Object.values(branchEntries.value).flat()].find(value => value.item.id === documentId)
  const change = { document_ids: [documentId], tag_ids: tagId ? [tagId] : [], list_changed: !entry || Boolean(entry.tags?.length) !== Boolean(tagId) }
  if (await mutate(() => memoryService.moveDocumentToTag(documentId, tagId), change) && tagId) {
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
function dropClass(key: string): Record<string, boolean> {
  return { 'tag-row--drop': dropTarget.value === key && dropPlacement.value === 'inside',
    'node-drop-before': dropTarget.value === key && dropPlacement.value === 'before',
    'node-drop-after': dropTarget.value === key && dropPlacement.value === 'after' }
}
async function dropNode(): Promise<void> {
  const node = drag; const target = pendingDrop; clearDrag()
  if (!node || !target) return
  if (!target.anchor && !target.list_only) {
    if (node.kind === 'document') { await moveDocument(node.id, target.parent_id); return }
    const tag = tags.value.find(value => value.id === node.id)
    if (tag) await mutate(() => memoryService.saveDocumentTag({ name: tag.name, parent_id: target.parent_id }, tag.id))
  } else if (await mutate(() => memoryService.reorderDocuments({ node, ...target }), {
    tags_changed: !target.list_only,
    tag_ids: target.list_only || !target.parent_id ? [] : [target.parent_id],
    document_ids: node.kind === 'document' && !target.list_only ? [node.id] : [],
    list_changed: target.list_only || (node.kind === 'document' && (!target.parent_id || !documentFolders([node.id]).length)),
  })) {
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
async function changeSession(): Promise<void> {
  const session = ++sessionGeneration
  pendingChanges = []
  if (refreshTimer) clearTimeout(refreshTimer)
  ++generation; ++tagGeneration; entries.value = []; tags.value = []; owners.value = []; keywords.value = []; total.value = 0
  deleteDialog.value = false; editingTag.value = null; renameTagId.value = null; userId.value = null; busy.value = false; expanded.value = []; branches.reset(); clearDrag()
  ready = false; reset(); page.value = 1; await loadTags()
  if (disposed || session !== sessionGeneration) return
  ready = true; await reload()
}
onMounted(async () => { window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession); await loadTags(); if (!disposed) { ready = true; await reload() } })
onBeforeUnmount(() => { disposed = true; ++generation; ++tagGeneration; window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession) })
defineExpose({ reload: refresh, refreshDocuments })
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
.document-tree :deep(.q-tree__children) { padding-left: 40px; }
.document-tree :deep(.q-tree__node-header) { min-height: 28px; padding-top: 1px; padding-bottom: 1px; }
.document-tree :deep(.q-tree__node:after) { left: -9px; }
.document-tree :deep(.q-tree__node-header:before) { left: -9px; width: 9px; }
.document-tree :deep(.q-tree__node--child) { padding-left: 0; }
.document-tree :deep(.q-tree__node--child > .q-tree__node-header:before) { left: -9px; width: 9px; }
.document-list-panel { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.document-list-scroll { flex: 1; min-height: 0; overflow: auto; }
.library-pagination { flex-shrink: 0; gap: 4px 12px; }
.tag-dialog { width: min(440px, calc(100vw - 24px)); }
.library-navigation--dark :deep(.q-splitter__separator) { background: var(--solaire-gray-dark); }
.library-navigation--dark .tag-row--drop { background: var(--solaire-blue-dark); }
</style>
