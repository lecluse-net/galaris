<template>
  <div class="q-pa-sm">
    <DocumentClassificationActions ref="classificationActions" :mode="mode" :groups="topics" :busy="busy" @changed="ids => emit('changed', ids)" @deleted="id => emit('deleted', id)" @selection="ids => emit('selection', ids)" @retired-topic="id => pinnedTopics.delete(id)" @saved-topic="saveTopic" @expand="expandNodes" @move="(values, target, keyword) => emit('move', values, target, keyword)" />
    <q-spinner v-if="loading" color="primary" />
    <q-banner v-if="error" dense role="alert">{{ t('documents.loadError') }}
      <q-btn outline dense color="primary" :label="t('documents.retry')" @click="reload(pendingDocuments.size ? [...pendingDocuments] : undefined)" />
    </q-banner>
    <q-tree v-model:expanded="expanded" :nodes="displayNodes" node-key="id" dense no-transition :aria-busy="busy" :aria-label="t(props.mode === 'agents' ? 'documents.library.agents' : 'documents.library.topicsTags')" class="document-topic-tree">
      <template #default-header="{ node }">
        <div class="row items-center no-wrap full-width topic-target" :class="{ 'topic-target--selected': selectedNodes.length > 1 && nodeSelection.selected.value.includes(node.id), 'topic-target--drop': dropTarget === node.id }"
          :aria-label="node.label" :aria-selected="nodeSelection.selected.value.includes(node.id)" :draggable="canSelectNode(node) && !busy" tabindex="0"
          @click="event => selectNode(node, event)" @mousedown="preventTextSelection" @keydown="event => nodeKeyboard(node, event)" @dragstart.stop="event => startNodeDrag(event, node)" @dragend="finishNodeDrag"
          @dragover.stop="dragOver($event, node)" @dragleave="dropTarget = null" @drop.prevent.stop="drop(node)">
          <AgentAvatar v-if="node.topic && props.mode === 'agents'" :agent-id="Number(node.topicId)" :name="node.label" :has-avatar="node.hasAvatar" size="26px" class="q-mr-xs" />
          <q-icon v-else :name="node.topic ? navigationIcon('folder_copy') : node.special === 'all' ? 'description' : node.special === 'none' ? 'label_off' : 'label'"
            :style="node.special ? { color: node.special === 'all' ? 'var(--solaire-violet-accent)' : 'var(--solaire-orange-accent)' } : undefined" :color="node.special ? undefined : 'primary'" size="26px" class="q-mr-xs" />
          <span class="ellipsis col" :title="node.label">{{ node.label }}</span>
          <ActionContextMenu class="topic-actions" :actions="classificationActions?.nodeActions(node, selectedNodes) ?? []" target=".topic-target" :label="t('documents.classification.actions', { name: node.label })">
            <template #trigger="{ toggle, open }"><q-btn flat dense round color="primary" size="sm" icon="more_horiz" :aria-label="t('documents.classification.actions', { name: node.label })" :aria-expanded="open" @click="toggle" /></template>
          </ActionContextMenu>
        </div>
      </template>
      <template #header-document="{ node }">
        <div class="row items-center no-wrap full-width topic-document-row" @click.stop>
          <DocumentLibraryEntryRow class="col" :entry="node.entry" compact :loading="false" :selected-document-id="selectedDocumentId" :selected="selectedDocumentIds?.includes(node.entry.item.id)"
            @select="(entry, event) => emit('select', entry, event, node.id, visibleDocuments)" @dragstart="event => startDrag(event, node)" @dragend="emit('dragend')" />
          <div class="topic-actions row no-wrap items-center">
            <DocumentRowMenu :entry="node.entry" :busy="busy" target=".topic-document-row" :extra-actions="classificationActions?.documentActions(dragContexts(node)) ?? []" @select="emit('select', node.entry)" @action="emit('action', node.entry, $event)" />
          </div>
        </div>
      </template>
      <template #header-virtual-range="{ node }">
        <TreePageHeader :page="node.page" :total="node.total" :titles="node.titles" :loading="branchLoading[treePageDataKey(node.id)]" />
      </template>
      <template #header-status="{ node }">
        <div class="text-caption" @click.stop>
          <q-spinner v-if="branchLoading[node.branch]" size="16px" />
          <span v-else-if="branchErrors[node.branch]">{{ t('documents.loadError') }}
            <q-btn outline dense color="primary" :label="t('documents.retry')" @click="loadBranch(node.branch, true)" />
          </span>
          <span v-else>{{ t('documents.empty') }}</span>
        </div>
      </template>
    </q-tree>
    <div v-if="!loading && !error && !topics.length" class="text-caption q-pa-sm">{{ t('documents.empty') }}</div>
    <div v-if="mode !== 'agents' && canEditTopics" class="row no-wrap q-gutter-x-sm q-mt-sm">
      <q-btn class="col-6" outline dense no-caps icon="add" :label="t('topic.createTitle')" :disable="busy" @click="classificationActions?.editTopic()" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowReactive, shallowRef, useTemplateRef, watch, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { documentService } from '../services/documentService'
import type { DocumentLibraryEntry, DocumentLibraryRange, DocumentTopicBranch } from '../types'
import type { DocumentRowAction } from '../libraryShortcuts'
import DocumentLibraryEntryRow from './DocumentLibraryEntryRow.vue'
import DocumentRowMenu from './DocumentRowMenu.vue'
import { useDocumentMutations } from '../stores/documentMutations'
import { reconcileLibrarySnapshot, reconcileLibraryTree } from '../librarySnapshot'
import { useDocumentSelection, documentSelectionModifiers, type DocumentSelectionItem } from '../useDocumentSelection'
import { ActionContextMenu, TreePageHeader, TREE_PAGE_SIZE, treePages, treePageKey, treePageFromKey, treePageDataKey, virtualTreeNodes, type TreePage } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { AgentAvatar } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { Topic } from '@/app/topic'
import DocumentClassificationActions from './DocumentClassificationActions.vue'
import type { DocumentClassificationContext } from '../classificationTypes'

const props = defineProps<{ selectedDocumentId: string | null; selectedDocumentIds?: string[]; busy: boolean; canDrop: boolean; mode?: 'topics' | 'agents' }>()
const emit = defineEmits<{
  select: [entry: DocumentLibraryEntry, event?: Event, key?: string, items?: DocumentSelectionItem[]]; action: [entry: DocumentLibraryEntry, action: DocumentRowAction]
  loaded: [entries: DocumentLibraryEntry[]]
  dragstart: [event: DragEvent, entries: { entry: DocumentLibraryEntry; keyword: string | null }[]]; dragend: []
  drop: [topicId: string, keyword?: string | null]
  changed: [ids: string[]]
  move: [values: DocumentClassificationContext[], target: string | null, keyword?: string | null]
  deleted: [id: string]; selection: [ids: string[]]
}>()
const { t } = useI18n()
const mutations = useDocumentMutations()
const privilegeStore = usePrivilegeStore()
const canEditTopics = computed(() => privilegeStore.hasPrivilege(privileges.TOPIC_EDIT))
const classificationActions = useTemplateRef<InstanceType<typeof DocumentClassificationActions>>('classificationActions')
const nodeSelection = useDocumentSelection()
let draggedNodes: TopicNode[] = []
const pinnedTopics = new Map<string, DocumentTopicBranch>()
const topics = shallowRef<DocumentTopicBranch[]>([])
const expanded = ref<string[]>([])
const loading = ref(false), error = ref(false), dropTarget = ref<string | null>(null)
const entries = shallowRef(shallowReactive<Record<string, DocumentLibraryEntry[]>>({}))
const branchLoading = ref<Record<string, boolean>>({}), branchErrors = ref<Record<string, boolean>>({})
const branchTotals = ref<Record<string, number>>({})
const ranges = ref<Record<string, DocumentLibraryRange[]>>({})
let generation = 0
let controller: AbortController | undefined
const branchControllers = new Map<string, AbortController>()
const stale = new Set<string>()
let patchSequence = 0
const patches = new Map<string, { sequence: number; entry: DocumentLibraryEntry | null }>()
const pendingDocuments = new Set<string>()
interface TopicNode {
  id: string; label: string; topicId: string; topic?: boolean; keyword?: string | null; hasAvatar?: boolean
  special?: 'all' | 'none'
  page?: TreePage; total?: number; titles?: DocumentLibraryRange
  header?: string; branch?: string; entry?: DocumentLibraryEntry; children?: TopicNode[]
}
// Catalogue identity depends on topics/owners and locale, never on loaded document pages.
const catalogue = computed<TopicNode[]>(previous => reconcileLibraryTree(previous ?? [], topics.value.map(topic => ({
  id: topic.id, label: topic.title || t('documents.library.noOwner'), topicId: topic.id, topic: true,
  hasAvatar: 'has_avatar' in topic ? Boolean(topic.has_avatar) : undefined,
  children: [
    { id: `${topic.id}:all`, label: t('documents.library.all'), topicId: topic.id, special: 'all' as const },
    ...topic.keywords.map(keyword => ({ id: JSON.stringify([topic.id, keyword]), label: keyword, topicId: topic.id, keyword })),
    { id: `${topic.id}:none`, label: t('documents.library.withoutTag'), topicId: topic.id, keyword: null, special: 'none' as const },
  ],
}))))
const branchIndex = computed(() => new Map(catalogue.value.flatMap(topic => (topic.children ?? []).map(branch => [branch.id, branch] as const))))
// Each branch tracks only its own cache keys; loading one page leaves sibling subtrees intact.
interface BranchTree { branch: TopicNode; node: ComputedRef<TopicNode> }
const branchTrees = computed<Map<string, BranchTree>>(previous => new Map([...branchIndex.value].map(([id, branch]) => {
  const cached = previous?.get(id)
  return [id, cached?.branch === branch ? cached : { branch, node: computed(() => ({ ...branch, children: branchChildren(branch) })) }]
})))
const nodes = computed<TopicNode[]>(previous => reconcileLibraryTree(previous ?? [], catalogue.value.map(topic => ({
  ...topic, children: topic.children?.map(branch => branchTrees.value.get(branch.id)!.node.value),
}))))
function branchChildren(branch: TopicNode, page?: TreePage): TopicNode[] {
  const total = branchTotals.value[branch.id] ?? 0
  if (total > TREE_PAGE_SIZE && (!page || page.size > TREE_PAGE_SIZE)) {
    const nodes: TopicNode[] = treePages(branch.id, total, page).map(range => {
      const id = treePageKey(range)
      const titles = ranges.value[page ? treePageKey(page) : branch.id]?.find(value => value.offset === range.offset && value.size === range.size)
      return { id, label: titles ? t('common.treePageNames', { first: titles.first_title, last: titles.last_title }) : t('common.treePage', { first: range.offset + 1, last: Math.min(total, range.offset + range.size) }),
        topicId: branch.topicId, page: range, total, titles, header: 'virtual-range',
        children: expanded.value.includes(id) ? branchChildren(branch, range)
          : [{ id: id + ':status', label: '', topicId: branch.topicId, header: 'status', branch: treePageDataKey(id) }] }
    })
    if (page && branchErrors.value[treePageKey(page)]) nodes.push({ id: treePageKey(page) + ':status', label: '', topicId: branch.topicId, header: 'status', branch: treePageKey(page) })
    return nodes
  }
  const key = page ? treePageDataKey(treePageKey(page)) : branch.id
  const values = (entries.value[key] ?? []).slice(0, TREE_PAGE_SIZE)
  return [
    ...values.filter(entry => mutations.deleting[entry.item.id] === undefined).map(entry => ({ id: `${key}:${entry.item.id}`, label: entry.item.title,
      topicId: branch.topicId, keyword: branch.keyword ?? null, entry, header: 'document' })),
    ...(!values.length || branchErrors.value[key]
      ? [{ id: `${key}:status`, label: '', topicId: branch.topicId, header: 'status', branch: key }] : []),
  ]
}
function branchNode(id: string): TopicNode | undefined { return branchIndex.value.get(id) }
const displayNodes = computed(() => virtualTreeNodes(nodes.value, 'id', expanded.value) as TopicNode[])
function canSelectNode(node: TopicNode): boolean { return !node.page && !node.special && !(props.mode === 'agents' && node.topic) }
const selectableNodes = computed(() => {
  const values: TopicNode[] = []
  const visit = (nodes: TopicNode[]): void => {
    for (const node of nodes) {
      if (canSelectNode(node) && !node.entry && node.header !== 'status') values.push(node)
      if (node.children && expanded.value.includes(node.id)) visit(node.children)
    }
  }
  visit(displayNodes.value)
  return values
})
const selectedNodes = computed(() => selectableNodes.value.filter(node => nodeSelection.selected.value.includes(node.id)))
function selectNode(node: TopicNode, event: Event): void {
  if (props.busy || !canSelectNode(node) || event.target instanceof Element && event.target.closest('button, .action-context-menu')) return
  const modifiers = documentSelectionModifiers(event)
  if (selectedNodes.value.some(value => Boolean(value.topic) !== Boolean(node.topic))) nodeSelection.clear()
  nodeSelection.select(node.topic ? 'groups' : 'keywords', node.id, selectableNodes.value.filter(value => Boolean(value.topic) === Boolean(node.topic)).map(node => ({ key: node.id, id: node.id })), event)
  if (modifiers?.ctrlKey || modifiers?.metaKey || modifiers?.shiftKey) event.stopPropagation()
}
function preventTextSelection(event: MouseEvent): void {
  if (event.ctrlKey || event.metaKey || event.shiftKey) event.preventDefault()
}
function toggleNode(node: TopicNode): void {
  if (props.busy || !canSelectNode(node)) return
  if (selectedNodes.value.some(value => Boolean(value.topic) !== Boolean(node.topic))) nodeSelection.clear()
  nodeSelection.select(node.topic ? 'groups' : 'keywords', node.id, selectableNodes.value.filter(value => Boolean(value.topic) === Boolean(node.topic)).map(node => ({ key: node.id, id: node.id })), undefined, true)
}
function nodeKeyboard(node: TopicNode, event: KeyboardEvent): void {
  if (event.target instanceof Element && event.target.closest('button, input')) return
  if (event.key === ' ' && !node.special) { event.preventDefault(); event.stopPropagation(); toggleNode(node) }
  const action = classificationActions.value?.nodeActions(node, selectedNodes.value).find(action => action.shortcut === event.key)
  if (action && !action.disabled) { event.preventDefault(); event.stopPropagation(); void action.run() }
}
function expandNodes(ids: string[], open: boolean): void {
  const keys = ids.flatMap(id => { const node = nodes.value.find(node => node.id === id); return node ? [id, ...(node.children ?? []).map(node => node.id)] : [id] })
  expanded.value = open ? [...new Set([...expanded.value, ...keys])] : expanded.value.filter(id => !keys.includes(id))
}
function startNodeDrag(event: DragEvent, node: TopicNode): void {
  if (props.busy || !canSelectNode(node) || event.target instanceof Element && event.target.closest('button')) { event.preventDefault(); return }
  draggedNodes = nodeSelection.selected.value.includes(node.id) ? selectedNodes.value : [node]
  event.dataTransfer?.setData('application/x-galaris-classification', JSON.stringify(draggedNodes.map(node => node.id)))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function finishNodeDrag(): void { draggedNodes = []; dropTarget.value = null }
function saveTopic(topic: Topic): void {
  const existing = topics.value.find(group => group.id === topic.id)
  const value = { ...(existing ?? { id: topic.id, keywords: [], document_count: 0, without_keywords_count: 0 }), title: topic.title }
  if (!existing || pinnedTopics.has(topic.id)) pinnedTopics.set(topic.id, value)
  topics.value = reconcileLibrarySnapshot(topics.value, [...topics.value.filter(group => group.id !== topic.id), value].sort((a, b) => a.title.localeCompare(b.title)), group => group.id)
}
const visibleDocumentNodes = computed(() => {
  const values: TopicNode[] = []
  const visit = (nodes: TopicNode[]): void => {
    for (const node of nodes) {
      if (node.entry) values.push(node)
      if (node.children && expanded.value.includes(node.id)) visit(node.children)
    }
  }
  visit(displayNodes.value)
  return values
})
const visibleDocuments = computed<DocumentSelectionItem[]>(() => visibleDocumentNodes.value.map(node => ({ key: node.id, id: node.entry!.item.id })))
function dragContexts(node: TopicNode): DocumentClassificationContext[] {
  const selected = props.selectedDocumentIds?.includes(node.entry!.item.id) ? props.selectedDocumentIds : [node.entry!.item.id]
  const contexts = new Map(visibleDocumentNodes.value.filter(node => selected.includes(node.entry!.item.id)).map(node => [node.entry!.item.id, { entry: node.entry!, keyword: node.keyword ?? null }]))
  contexts.set(node.entry!.item.id, { entry: node.entry!, keyword: node.keyword ?? null })
  return [...contexts.values()]
}
function startDrag(event: DragEvent, node: TopicNode): void { emit('dragstart', event, dragContexts(node)) }
function matches(entry: DocumentLibraryEntry, branch: TopicNode): boolean {
  const identity = props.mode === 'agents' ? String(entry.item.owner_agent_id) : entry.item.topic_id
  return identity === branch.topicId && (branch.keyword === undefined || (branch.keyword === null ? !entry.item.keywords.length : entry.item.keywords.includes(branch.keyword)))
}
function patched(values: DocumentLibraryEntry[], branch: TopicNode, since = -1): DocumentLibraryEntry[] {
  const changes = [...patches.entries()].filter(([, patch]) => patch.sequence > since)
  const changed = new Set(changes.map(([id]) => id))
  const paged = (branchTotals.value[branch.id] ?? 0) > TREE_PAGE_SIZE
  const present = new Set(values.map(entry => entry.item.id))
  const next = [...values.filter(entry => !changed.has(entry.item.id)), ...changes.flatMap(([, { entry }]) => entry && matches(entry, branch) && (!paged || present.has(entry.item.id)) ? [entry] : [])]
  next.sort((a, b) => a.item.title.toLowerCase().localeCompare(b.item.title.toLowerCase()) || a.item.id.localeCompare(b.item.id))
  return reconcileLibrarySnapshot(values, next, entry => entry.item.id)
}
function publish(): void { emit('loaded', Object.values(entries.value).flat()) }
function patchDocuments(ids: string[], values: DocumentLibraryEntry[]): void {
  const byId = new Map(values.map(entry => [entry.item.id, entry]))
  const sequence = ++patchSequence
  for (const id of ids) patches.set(id, { sequence, entry: byId.get(id) ?? null })
  const refreshPages: string[] = []
  for (const id of Object.keys(entries.value)) {
    const branch = branchNode(treePageFromKey(id)?.parent ?? id)
    if (branch) {
      if ((branchTotals.value[branch.id] ?? 0) > TREE_PAGE_SIZE && (entries.value[id]!.some(entry => byId.has(entry.item.id) || ids.includes(entry.item.id)) || values.some(entry => matches(entry, branch)))) refreshPages.push(id)
      entries.value[id] = patched(entries.value[id]!, branch, sequence - 1)
    }
  }
  publish()
  // Reconcile only ranges already requested by the user, never all remaining pages.
  for (const id of refreshPages) void loadBranch(id, true)
  // Only in-flight branch reads need protection against their earlier snapshots.
  if (!branchControllers.size) patches.clear()
}
async function loadBranch(id: string, force = false): Promise<void> {
  const page = treePageFromKey(id)
  if (page?.parent.startsWith('local-tree:')) return
  const branch = branchNode(page?.parent ?? id)
  id = treePageDataKey(id)
  if (force) { branchControllers.get(id)?.abort(); branchControllers.delete(id) }
  if (!branch || branchControllers.has(id) || (!force && !stale.has(id) && entries.value[id] && !branchErrors.value[id])) return
  const sequence = patchSequence
  const request = new AbortController()
  branchControllers.set(id, request); branchLoading.value[id] = true; branchErrors.value[id] = false
  try {
    const scope = props.mode === 'agents' ? { owner_kind: 'agent' as const, owner: Number(branch.topicId) } : { topic_id: branch.topicId }
    const result = await documentService.browseDocumentLibrary({ ...scope,
      keyword: branch.keyword, without_keywords: branch.keyword === null, include_keywords: false,
      limit: TREE_PAGE_SIZE, offset: page?.offset ?? 0,
      include_tree_ranges: !page || page.offset === 0 || page.size > TREE_PAGE_SIZE,
      tree_range_size: page && page.size > TREE_PAGE_SIZE ? page.size : undefined }, request.signal)
    if (branchControllers.get(id) !== request || request.signal.aborted) return
    const current = branchNode(branch.id)
    if (!current) return
    branchTotals.value[branch.id] = result.total
    ranges.value[id] = result.tree_ranges ?? []
    entries.value[id] = reconcileLibrarySnapshot(entries.value[id] ?? [], patched(result.entries, current, sequence), entry => entry.item.id)
    stale.delete(id); publish()
  } catch { if (branchControllers.get(id) === request && !request.signal.aborted) branchErrors.value[id] = true }
  finally {
    if (branchControllers.get(id) === request) { branchControllers.delete(id); branchLoading.value[id] = false }
    if (!branchControllers.size) patches.clear()
  }
}
async function reload(documentIds?: string[]): Promise<void> {
  for (const id of documentIds ?? []) pendingDocuments.add(id)
  const changedIds = documentIds ? [...pendingDocuments] : undefined
  const current = ++generation
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = !topics.value.length; error.value = false
  try {
    const [result, documents] = await Promise.all([
      props.mode === 'agents'
        ? documentService.documentAgents(request.signal).then(agents => agents.map(agent => ({ ...agent, id: String(agent.id) })))
        : documentService.documentTopics(request.signal),
      changedIds ? readDocuments(changedIds, request.signal) : Promise.resolve([]),
    ])
    if (current !== generation) return
    topics.value = reconcileLibrarySnapshot(topics.value, [...result, ...[...pinnedTopics.values()].filter(topic => !result.some(value => value.id === topic.id))], topic => topic.id)
    const retained = new Set([...catalogue.value.map(node => node.id), ...branchIndex.value.keys()])
    for (const id of new Set([...Object.keys(entries.value), ...branchControllers.keys()])) if (!retained.has(treePageFromKey(id)?.parent ?? id)) {
      branchControllers.get(id)?.abort(); branchControllers.delete(id)
      delete entries.value[id]; delete ranges.value[id]; delete branchErrors.value[id]; delete branchLoading.value[id]; stale.delete(id)
    }
    expanded.value = expanded.value.filter(id => treePageFromKey(id)?.parent.startsWith('local-tree:') || retained.has(treePageFromKey(id)?.parent ?? id))
    if (changedIds) {
      patchDocuments(changedIds, documents)
      for (const id of changedIds) pendingDocuments.delete(id)
    }
    else {
      for (const id of Object.keys(entries.value)) stale.add(id)
      await Promise.all(expanded.value.map(id => loadBranch(id, true)))
      if (current === generation) pendingDocuments.clear()
    }
  } catch { if (current === generation) error.value = true }
  finally { if (current === generation) loading.value = false }
}
async function readDocuments(ids: string[], signal: AbortSignal): Promise<DocumentLibraryEntry[]> {
  const values: DocumentLibraryEntry[] = []
  for (let offset = 0; offset < ids.length; offset += 500) {
    const result = await documentService.browseDocumentLibrary({ document_ids: ids.slice(offset, offset + 500), limit: 500, include_keywords: false }, signal)
    values.push(...result.entries)
  }
  return values
}
function dragOver(event: DragEvent, node: TopicNode): void {
  if (draggedNodes.length) {
    const compatible = draggedNodes.every(source => source.topic) && node.topic && (props.mode === 'agents' || canEditTopics.value)
      || draggedNodes.every(source => typeof source.keyword === 'string') && typeof node.keyword === 'string'
    if (props.busy || !compatible || draggedNodes.some(source => source.id === node.id)) return
    event.preventDefault(); dropTarget.value = node.id; return
  }
  if (!props.canDrop || props.busy) return
  event.preventDefault(); dropTarget.value = node.id
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}
function drop(node: TopicNode): void {
  dropTarget.value = null
  if (draggedNodes.length) { classificationActions.value?.mergeNodes(draggedNodes, node); finishNodeDrag(); return }
  if (props.canDrop && !props.busy) emit('drop', node.topicId, node.keyword)
}
function removeDocument(id: string): void {
  patchDocuments([id], [])
}
watch(expanded, (next, previous) => {
  for (const id of previous) if (!next.includes(id)) {
    const key = treePageDataKey(id)
    branchControllers.get(key)?.abort(); branchControllers.delete(key); branchLoading.value[key] = false
  }
  const visible = new Set<string>()
  const visibleData = new Set<string>()
  const visit = (nodes: TopicNode[]): void => {
    for (const node of nodes) {
      visible.add(node.id)
      visibleData.add(treePageDataKey(node.id))
      if (node.children && next.includes(node.id)) visit(node.children)
    }
  }
  visit(displayNodes.value)
  if (previous.some(id => !next.includes(id))) {
    for (const id of branchControllers.keys()) if (!visibleData.has(id)) {
      branchControllers.get(id)?.abort(); branchControllers.delete(id); branchLoading.value[id] = false
    }
  }
  for (const id of next) if (visible.has(id) && !branchErrors.value[treePageDataKey(id)]) void loadBranch(id)
})
onMounted(() => reload())
onBeforeUnmount(() => { ++generation; controller?.abort(); for (const request of branchControllers.values()) request.abort() })
defineExpose({ reload, removeDocument })
</script>

<style scoped>
.document-topic-tree :deep(.q-tree__arrow), .document-topic-tree :deep(.q-tree__spinner) { color: var(--solaire-gray-accent); }
.document-topic-tree :deep(.q-tree__node-header) { min-height: 28px; }
.topic-target { min-width: 0; min-height: 28px; }
.topic-target > .topic-actions, .topic-document-row > .topic-actions { display: none; }
.document-topic-tree :deep(.q-tree__node-header:hover .topic-actions),
.document-topic-tree :deep(.q-tree__node-header:has(.action-context-menu--open) .topic-actions),
.document-topic-tree :deep(.q-tree__node-header:has(:focus-visible) .topic-actions) { display: inline-flex; }
@media (hover: none) {
  .topic-target > .topic-actions, .topic-document-row > .topic-actions { display: inline-flex; }
}
.topic-target--selected { outline: 1px solid var(--solaire-blue-accent); }
.topic-target--drop { background: var(--solaire-blue-light); }
body.body--dark .topic-target--drop { background: var(--solaire-blue-dark); }
.topic-document-row { min-width: 0; }
</style>
