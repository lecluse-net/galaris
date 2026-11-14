<template>
  <div v-if="preparing" class="row items-center q-gutter-sm q-pb-sm" role="status"><q-spinner color="primary" />{{ t('documents.classification.preparing') }}</div>
  <TopicFormDialog v-model="topicDialog" :topic="editedTopic" @saved="topicSaved" />
  <q-banner v-if="bulkResult" role="status" class="q-mb-sm">{{ bulkResult }}</q-banner>
  <DocumentBulkDialog v-model="bulkOpen" :entries="bulkEntries" :busy="saving" @apply="runBulk" />
  <q-dialog v-model="dialog">
    <q-card class="classification-dialog">
      <DialogHeader :title="title" />
      <q-form @submit.prevent="confirm">
        <q-card-section class="q-gutter-md">
          <q-banner role="note">{{ help }}</q-banner>
          <div>{{ names }}</div>
          <q-input v-if="operation === 'rename-keyword'" v-model="name" outlined autofocus :label="t('documents.library.name')" maxlength="100" :disable="saving" />
          <TopicSelect v-if="operation === 'merge-topics' || operation === 'move' && mode === 'topics'" v-model="target" outlined :clearable="operation === 'move'" :disable="saving" :label="t('documents.classification.destination')" :hint="operation === 'move' && target === null ? t('documents.library.withoutTopic') : undefined" />
          <q-select v-if="operation === 'merge-keywords'" v-model="name" outlined :options="mergeKeywordOptions" :label="t('documents.classification.destination')" :disable="saving" />
          <q-select v-if="operation === 'move' && mode === 'agents'" v-model="target" outlined emit-value map-options :options="agentOptions" :label="t('documents.classification.destination')" :loading="loadingOwners" :disable="saving" />
          <q-select v-if="operation === 'move'" v-model="keyword" outlined emit-value map-options use-input input-debounce="0" :options="moveKeywords" :label="t('documents.keywords')" :display-value="keyword === undefined ? t('documents.classification.keepKeywords') : keyword === null ? t('documents.library.withoutTag') : keyword" :disable="saving" @new-value="(value, done) => done(value.trim(), 'add-unique')" />
          <q-banner v-if="failure" role="alert">{{ failure }}</q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" :disable="saving" />
          <q-btn type="submit" :color="operation.startsWith('delete') ? 'negative' : 'primary'" :label="t('common.confirm')" :disable="!valid" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { apiErrorDetail, sessionGeneration } from '@/core/api'
import { DialogHeader, type ContextAction } from '@/core/util'
import { TopicFormDialog, TopicSelect, topicService, type Topic } from '@/app/topic'
import { documentService } from '../services/documentService'
import type { DocumentLibraryEntry, DocumentTopicBranch, DocumentLibraryFilters } from '../types'
import type { DocumentClassificationNode, DocumentClassificationContext } from '../classificationTypes'
import DocumentBulkDialog from './DocumentBulkDialog.vue'
import { applyDocumentBulkOperation, applyDocumentOwnerBatch, type DocumentBulkOperation } from '../services/documentBulkService'
import { useDocumentMutations } from '../stores/documentMutations'

const props = withDefaults(defineProps<{ mode?: 'topics' | 'agents'; groups: DocumentTopicBranch[]; busy: boolean }>(), { mode: 'topics' })
const emit = defineEmits<{
  changed: [ids: string[]]; savedTopic: [topic: Topic]; expand: [ids: string[], open: boolean]
  move: [entries: DocumentClassificationContext[], target: string | null, keyword?: string | null]
  deleted: [id: string]; selection: [ids: string[]]; retiredTopic: [id: string]
}>()
const { t } = useI18n(), privilegeStore = usePrivilegeStore()
const $q = useQuasar(), mutations = useDocumentMutations()
const canEditDocuments = computed(() => privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN]))
const canEditTopics = computed(() => privilegeStore.hasPrivilege(privileges.TOPIC_EDIT))
const preparing = ref(false), dialog = ref(false), saving = ref(false), failure = ref('')
const topicDialog = ref(false), editedTopic = shallowRef<Topic | null>(null)
type Operation = 'rename-keyword' | 'merge-keywords' | 'delete-keywords' | 'merge-topics' | 'delete-topics' | 'move'
const operation = ref<Operation>('rename-keyword')
const selected = shallowRef<DocumentClassificationNode[]>([]), documents = shallowRef<DocumentClassificationContext[]>([])
const name = ref(''), target = ref<string | null>(null), keyword = ref<string | null | undefined>()
const mergeKeywordOptions = ref<string[]>([])
const agentOptions = ref<{ label: string; value: string | null }[]>([]), loadingOwners = ref(false)
const bulkOpen = ref(false), bulkEntries = shallowRef<DocumentLibraryEntry[]>([]), bulkResult = ref('')
let disposed = false
onBeforeUnmount(() => { disposed = true })
const keywordOptions = computed(() => [...new Set(props.groups.flatMap(group => group.keywords))].sort())
const moveKeywords = computed(() => [
  { label: t('documents.classification.keepKeywords'), value: undefined },
  { label: t('documents.library.withoutTag'), value: null },
  ...keywordOptions.value.map(value => ({ label: value, value })),
])
const title = computed(() => t(`documents.classification.${operation.value}`))
const help = computed(() => t(operation.value === 'move' ? props.mode === 'agents' ? 'documents.classification.ownerHelp' : 'documents.classification.moveHelp'
  : operation.value.endsWith('topics') ? 'documents.classification.topicHelp' : 'documents.classification.keywordHelp'))
const names = computed(() => operation.value === 'move' ? documents.value.map(({ entry }) => entry.item.title).join(', ') : selected.value.map(node => node.label).join(', '))
const valid = computed(() => !saving.value && (operation.value === 'rename-keyword' ? Boolean(name.value.trim())
  : operation.value === 'merge-keywords' ? mergeKeywordOptions.value.includes(name.value)
  : operation.value === 'merge-topics' ? Boolean(target.value && selected.value.some(node => node.topicId !== target.value))
    : operation.value === 'move' && props.mode === 'agents' ? Boolean(target.value && !loadingOwners.value) : true))
const current = (generation: ReturnType<typeof sessionGeneration>) => !disposed && generation === sessionGeneration()

async function allDocuments(filters: DocumentLibraryFilters): Promise<DocumentLibraryEntry[]> {
  const values: DocumentLibraryEntry[] = []
  const generation = sessionGeneration()
  for (;;) {
    const result = await documentService.browseDocumentLibrary({ ...filters, limit: 500, offset: values.length, include_keywords: false })
    if (!current(generation)) throw new Error(t('documents.classification.sessionChanged'))
    values.push(...result.entries)
    if (!result.has_more || !result.entries.length) return values
  }
}
function open(action: Operation, nodes: DocumentClassificationNode[], destinationKeyword?: string): void {
  if (props.busy || saving.value || preparing.value) return
  selected.value = nodes; operation.value = action
  mergeKeywordOptions.value = [...new Set([
    ...(destinationKeyword === undefined ? [] : [destinationKeyword]),
    ...nodes.flatMap(node => typeof node.keyword === 'string' ? [node.keyword] : []),
  ])]
  name.value = action === 'rename-keyword' ? nodes[0]?.keyword ?? '' : action === 'merge-keywords' ? mergeKeywordOptions.value[0] ?? '' : ''
  target.value = null; failure.value = ''; dialog.value = true
}
async function editTopic(node?: DocumentClassificationNode): Promise<void> {
  const generation = sessionGeneration()
  preparing.value = true
  try {
    const topic = node ? await topicService.get(node.topicId) : null
    if (current(generation)) { editedTopic.value = topic; topicDialog.value = true }
  } finally { if (current(generation)) preparing.value = false }
}
function topicSaved(topic: Topic): void { emit('savedTopic', topic) }
function nodeActions(node: DocumentClassificationNode, selection: DocumentClassificationNode[]): ContextAction[] {
  const nodes = selection.some(value => value.id === node.id) ? selection : [node]
  const groups = nodes.every(value => value.topic), keywords = nodes.every(value => typeof value.keyword === 'string')
  const disabled = props.busy || saving.value || preparing.value
  const actions: ContextAction[] = [
    { key: 'expand', label: t('documents.library.expandAll'), icon: 'unfold_more', run: () => emit('expand', nodes.map(node => node.id), true) },
    { key: 'collapse', label: t('documents.library.collapseAll'), icon: 'unfold_less', run: () => emit('expand', nodes.map(node => node.id), false) },
  ]
  if (groups && props.mode !== 'agents' && canEditTopics.value) actions.push(
    { key: 'new-topic', label: t('topic.createTitle'), icon: 'add', disabled, run: () => editTopic() },
    ...(nodes.length === 1 ? [{ key: 'edit', label: t('common.edit'), icon: 'edit', disabled, shortcut: 'F2', run: () => editTopic(node) }] : []),
    { key: 'merge', label: t('documents.classification.merge-topics'), icon: 'merge', disabled, run: () => open('merge-topics', nodes) },
    { key: 'delete', label: t('common.delete'), icon: 'delete', disabled, negative: true, shortcut: 'Delete', run: () => open('delete-topics', nodes) },
  )
  if (groups && props.mode === 'agents') actions.push(
    ...(canEditDocuments.value ? [{ key: 'move-group', label: t('documents.classification.move'), icon: 'drive_file_move', disabled, run: () => moveGroups(nodes) }] : []),
  )
  if (keywords && canEditDocuments.value) actions.push(
    ...(nodes.length === 1 ? [{ key: 'edit', label: t('documents.library.renameTag'), icon: 'edit', disabled, shortcut: 'F2', run: () => open('rename-keyword', nodes) }] : []),
    { key: 'merge', label: t('documents.classification.merge-keywords'), icon: 'merge', disabled, run: () => open('merge-keywords', nodes) },
    { key: 'delete', label: t('common.delete'), icon: 'delete', disabled, negative: true, shortcut: 'Delete', run: () => open('delete-keywords', nodes) },
  )
  return actions
}
async function requestMove(values: DocumentClassificationContext[]): Promise<void> {
  if (!values.length || !canEditDocuments.value || props.mode !== 'agents' && !canEditTopics.value) return
  documents.value = values; keyword.value = undefined; open('move', [])
  const first = values[0]!.entry.item
  target.value = props.mode === 'agents' ? first.owner_agent_id === null ? 'personal' : String(first.owner_agent_id) : first.topic_id ?? null
  if (props.mode === 'agents') {
    const generation = sessionGeneration()
    loadingOwners.value = true
    try {
      const result = await documentService.listDocumentOwnerOptions()
      if (current(generation)) agentOptions.value = [{ label: t('documents.library.withoutAgent'), value: 'personal' }, ...result.agents.map(agent => ({ label: agent.label, value: String(agent.id) }))]
    } finally { if (current(generation)) loadingOwners.value = false }
  }
}
function documentActions(values: DocumentClassificationContext[]): ContextAction[] {
  const disabled = props.busy || saving.value
  return canEditDocuments.value ? [
    ...(props.mode === 'agents' || canEditTopics.value ? [{ key: 'move-classification', icon: 'drive_file_move', label: t('documents.classification.move'), disabled, run: () => requestMove(values) }] : []),
    { key: 'bulk-actions', icon: 'checklist', label: t('documents.bulk.actions'), disabled, run: () => { bulkEntries.value = values.map(({ entry }) => entry); bulkResult.value = ''; bulkOpen.value = true } },
  ] : []
}
async function moveGroups(nodes: DocumentClassificationNode[], destination?: string): Promise<void> {
  const generation = sessionGeneration()
  preparing.value = true
  try {
    const values = (await Promise.all(nodes.map(node => allDocuments({ owner_kind: 'agent', owner: Number(node.topicId) })))).flat()
    if (!current(generation)) return
    preparing.value = false
    await requestMove([...new Map(values.map(entry => [entry.item.id, { entry, keyword: null }])).values()])
    if (current(generation) && destination) target.value = destination
  } catch (error) { if (current(generation)) $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('documents.library.error') }) }
  finally { if (current(generation)) preparing.value = false }
}
function mergeNodes(sources: DocumentClassificationNode[], destination: DocumentClassificationNode): void {
  if (sources.every(node => node.topic) && destination.topic && props.mode === 'agents' && canEditDocuments.value) {
    void moveGroups(sources.filter(node => node.id !== destination.id), destination.topicId)
    return
  }
  if (sources.every(node => node.topic) && destination.topic && props.mode !== 'agents' && canEditTopics.value) {
    open('merge-topics', sources.filter(node => node.id !== destination.id)); target.value = destination.topicId
  } else if (sources.every(node => typeof node.keyword === 'string') && typeof destination.keyword === 'string' && canEditDocuments.value) {
    open('merge-keywords', sources, destination.keyword)
  }
}
async function runBulk(operation: DocumentBulkOperation): Promise<void> {
  if (saving.value || props.busy) return
  const generation = sessionGeneration(), active = () => current(generation)
  const succeeded: string[] = [], failed: DocumentLibraryEntry[] = []
  const snapshot = [...bulkEntries.value]
  saving.value = true
  try {
    if (operation.kind === 'owner' && snapshot.length > 1) {
      try {
        await applyDocumentOwnerBatch(snapshot, operation)
        if (!active()) return
        succeeded.push(...snapshot.map(entry => entry.item.id))
      } catch { if (active()) failed.push(...snapshot) }
    } else for (const entry of snapshot) {
      if (!active()) return
      const finish = operation.kind === 'delete' ? mutations.beginDeletion(entry.item.id) : undefined
      try {
        if (finish === null) throw new Error('conflict')
        await applyDocumentBulkOperation(entry, operation, active)
        if (!active()) return
        succeeded.push(entry.item.id)
        if (operation.kind === 'delete') emit('deleted', entry.item.id)
      } catch { if (active()) failed.push(entry) }
      finally { finish?.() }
    }
  } finally {
    if (active()) {
      saving.value = false; bulkOpen.value = false; bulkEntries.value = failed
      bulkResult.value = t('documents.bulk.result', { success: succeeded.length, failed: failed.length }) + (failed.length ? ` ${failed.map(entry => entry.item.title).join(', ')}` : '')
      emit('selection', failed.map(entry => entry.item.id)); emit('changed', succeeded)
    }
  }
}
async function confirm(): Promise<void> {
  if (!valid.value || props.busy) return
  if (operation.value === 'move') {
    emit('move', documents.value, target.value === 'personal' ? null : target.value, keyword.value); dialog.value = false; return
  }
  const generation = sessionGeneration(), affected = new Set<string>()
  saving.value = true; failure.value = ''
  try {
    if (operation.value.endsWith('topics')) {
      if (!canEditTopics.value) return
      for (const node of selected.value) {
        if (!current(generation)) return
        if (operation.value === 'merge-topics' && node.topicId === target.value) continue
        for (const entry of await allDocuments({ topic_id: node.topicId })) affected.add(entry.item.id)
        if (!current(generation)) return
        if (operation.value === 'delete-topics') await topicService.remove(node.topicId)
        else await topicService.merge(node.topicId, target.value!)
        if (current(generation)) emit('retiredTopic', node.topicId)
      }
    } else {
      if (!canEditDocuments.value) return
      const keywords = [...new Set(selected.value.map(node => node.keyword!))]
      const values = [...new Map((await Promise.all(keywords.map(keyword => allDocuments({ keyword })))).flat().map(entry => [entry.item.id, entry])).values()]
      if (values.some(entry => !entry.item.access.can_write || entry.item.read_only || entry.item.source_managed)) throw new Error(t('documents.classification.notWritable'))
      for (let offset = 0; offset < values.length; offset += 500) {
        if (!current(generation)) return
        const batch = values.slice(offset, offset + 500)
        for (const entry of batch) affected.add(entry.item.id)
        await documentService.replaceLibraryKeywords({ documents: batch.map(entry => ({ id: entry.item.id, expected_lock_version: entry.item.lock_version })),
          source_keywords: keywords, keyword: operation.value === 'delete-keywords' ? null : name.value.trim() })
      }
    }
    if (current(generation)) dialog.value = false
  } catch (error) {
    if (current(generation)) failure.value = apiErrorDetail(error) ?? (error instanceof Error ? error.message : t('documents.library.error'))
  } finally {
    if (current(generation)) { saving.value = false; emit('changed', [...affected]) }
  }
}
defineExpose({ nodeActions, documentActions, mergeNodes, editTopic })
</script>

<style scoped>
.classification-dialog { width: min(540px, calc(100vw - 24px)); }
</style>
