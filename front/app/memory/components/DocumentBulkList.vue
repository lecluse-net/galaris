<template>
  <section class="bulk-list q-pa-md" :aria-label="heading" :aria-busy="loading || busy">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-btn flat round icon="arrow_back" :aria-label="t('documents.bulk.closeList')" :disable="busy" @click="emit('close')" />
      <h2 class="text-h6 col q-ma-none bulk-heading">{{ heading }}</h2>
      <q-btn flat round icon="refresh" :aria-label="t('documents.retry')" :disable="busy" @click="load" />
    </div>
    <q-card v-if="folder" :key="folder.id" flat bordered class="q-mb-md">
      <q-card-section>
        <h3 class="text-subtitle1 q-mt-none q-mb-xs">{{ t('documents.bulk.folderSharing') }}</h3>
        <p class="text-caption q-mb-sm">{{ t('documents.bulk.folderSharingHint') }}</p>
        <MemorySharingPanel :item-id="folder.id" :editable="!busy && privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)"
          :reader="memoryService.folderSharing" :writer="memoryService.updateFolderSharing" @changed="load" />
      </q-card-section>
    </q-card>
    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-input v-model="query" outlined dense clearable debounce="350" class="bulk-search" :label="t('documents.search')" :disable="busy" />
      <q-checkbox v-if="folder" v-model="recursive" :label="t('documents.bulk.recursive')" :disable="busy" />
    </div>
    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-checkbox :model-value="allSelected" :label="t('documents.bulk.selectPage')" :disable="busy || loading || !selectable.length" @update:model-value="togglePage" />
      <span class="text-caption">{{ t('documents.bulk.selected', { count: selected.length }) }}</span>
      <q-space />
      <q-btn color="primary" icon="checklist" :label="t('documents.bulk.actions')" :disable="busy || loading || !selected.length" @click="dialogOpen = true" />
    </div>
    <q-linear-progress v-if="loading || busy" indeterminate class="q-mb-sm" />
    <div v-if="busy" role="status">{{ t('documents.bulk.progress', { done: processed, total: operationTotal }) }}</div>
    <q-banner v-if="loadError" role="alert" class="q-mb-sm">{{ t('documents.loadError') }}<q-btn outline :label="t('documents.retry')" @click="load" /></q-banner>
    <q-banner v-if="outcome" class="q-mb-sm" role="status">
      {{ t('documents.bulk.result', { success: outcome.success, failed: outcome.failed.length }) }}
      <ul v-if="outcome.failed.length" class="q-my-sm">
        <li v-for="failure in outcome.failed" :key="failure.id">{{ failure.title }} — {{ t(`documents.bulk.errors.${failure.reason}`) }}</li>
      </ul>
    </q-banner>
    <q-list separator>
      <q-item v-for="entry in entries" :key="entry.item.id" v-library-shortcuts="rowShortcuts(entry)" tabindex="0" :title="t('documents.shortcuts.document')" aria-keyshortcuts="F2 F3 F4 F7 Delete">
        <q-item-section side>
          <q-checkbox :model-value="selected.includes(entry.item.id)" :aria-label="t('documents.bulk.selectDocument', { title: entry.item.title })"
            :disable="busy || loading || !canSelect(entry)" @update:model-value="toggle(entry.item.id)" />
        </q-item-section>
        <q-item-section side class="bulk-thumbnail">
          <DocumentThumbnail :document-id="entry.item.id" :revision="entry.item.revision" :updated-at="entry.item.updated_at" :agent-id="documentEntryActor(entry)" />
        </q-item-section>
        <q-item-section>
          <q-item-label><a :href="documentResourceHref(entry.item.id)" class="bulk-document-link" @click.prevent="!busy && emit('select', entry)">{{ entry.item.title }}</a></q-item-label>
          <q-item-label caption>{{ entry.owner_label }}</q-item-label>
          <div class="row q-gutter-xs"><q-chip v-for="keyword in entry.item.keywords" :key="keyword" dense class="bulk-keyword"><span class="ellipsis">{{ keyword }}</span></q-chip></div>
        </q-item-section>
        <q-item-section side><DocumentRowMenu :entry="entry" :busy="busy || loading" target=".q-item" @select="emit('select', entry)" @create="emit('create', entry)" @action="emit('action', entry, $event)" /></q-item-section>
      </q-item>
    </q-list>
    <div v-if="!loading && !loadError && !entries.length" class="q-pa-md">{{ t('documents.empty') }}</div>
    <div class="row items-center justify-center q-gutter-sm q-mt-md">
      <span class="text-caption">{{ t('documents.library.pageRange', { first: entries.length ? (page - 1) * pageSize + 1 : 0, last: entries.length ? (page - 1) * pageSize + entries.length : 0, total }) }}</span>
      <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" dense outlined :aria-label="t('documents.library.pageSize')" :disable="busy" />
      <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="5" direction-links :disable="busy" />
    </div>
    <DocumentBulkDialog v-model="dialogOpen" :entries="selectedEntries" :busy="busy" @apply="run" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { defineAsyncView, documentResourceHref } from '@/core/util'
import { websocket } from '@/core/websocket'
import { memoryService } from '../services/memoryService'
import { applyDocumentBulkOperation, documentEntryActor, type DocumentBulkOperation } from '../services/documentBulkService'
import { useDocumentMutations } from '../stores/documentMutations'
import type { DocumentLibraryEntry, DocumentTag } from '../types'
import DocumentBulkDialog from './DocumentBulkDialog.vue'
import DocumentThumbnail from './DocumentThumbnail.vue'
import DocumentRowMenu from './DocumentRowMenu.vue'
import { documentRowShortcuts, vLibraryShortcuts, type DocumentRowAction } from '../libraryShortcuts'

const props = defineProps<{ folder: DocumentTag | null }>()
const MemorySharingPanel = defineAsyncView(() => import('./MemorySharingPanel.vue'))
const emit = defineEmits<{ action: [entry: DocumentLibraryEntry, action: DocumentRowAction]; create: [entry: DocumentLibraryEntry]; select: [entry: DocumentLibraryEntry]; close: []; changed: [ids: string[]]; deleted: [id: string] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const mutations = useDocumentMutations()
function rowShortcuts(entry: DocumentLibraryEntry) {
  return documentRowShortcuts(entry, busy.value || loading.value,
    () => emit('select', entry), () => emit('create', entry), action => emit('action', entry, action))
}
const heading = computed(() => props.folder?.name ?? t('documents.library.orphans'))
const recursive = ref(false)
const query = ref<string | null>('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const entries = ref<DocumentLibraryEntry[]>([])
const selected = ref<string[]>([])
const selectedEntries = computed(() => entries.value.filter(entry => selected.value.includes(entry.item.id)))
const selectable = computed(() => entries.value.filter(canSelect))
const allSelected = computed(() => !selected.value.length ? false : selectable.value.length === selected.value.length ? true : null)
const loading = ref(false)
const loadError = ref(false)
const busy = ref(false)
const dialogOpen = ref(false)
const processed = ref(0)
const operationTotal = ref(0)
type FailureReason = 'permission' | 'conflict' | 'missing' | 'keywordLimit' | 'other'
interface Failure { id: string; title: string; reason: FailureReason }
const outcome = ref<{ success: number; failed: Failure[] } | null>(null)
let generation = 0
let operationGeneration = 0
let authSession = sessionGeneration()
let disposed = false
let controller: AbortController | undefined
let refreshTimer: ReturnType<typeof setTimeout> | undefined
function canSelect(entry: DocumentLibraryEntry): boolean {
  return privilegeStore.hasPrivilege(privileges.MEMORY_EDIT) && entry.item.access.can_write && !entry.item.read_only && !entry.item.source_managed
}
function toggle(id: string): void { selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id] }
function togglePage(): void { selected.value = allSelected.value === true ? [] : selectable.value.map(entry => entry.item.id) }
async function load(): Promise<void> {
  if (disposed || busy.value) return
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; loadError.value = false
  try {
    const result = await memoryService.browseDocumentLibrary({
      tag_id: props.folder?.id ?? null, classification: props.folder ? 'all' : 'unclassified',
      include_descendants: recursive.value, include_keywords: false, include_owners: false,
      query: query.value ?? '', limit: pageSize.value, offset: (page.value - 1) * pageSize.value, sort_by: 'title',
    }, controller.signal)
    if (disposed || current !== generation) return
    total.value = result.total
    const max = Math.max(1, Math.ceil(total.value / pageSize.value))
    if (page.value > max) { page.value = max; return }
    entries.value = result.entries
    selected.value = selected.value.filter(id => result.entries.some(entry => entry.item.id === id && canSelect(entry)))
  } catch { if (!disposed && current === generation) { loadError.value = true; entries.value = []; selected.value = [] } }
  finally { if (!disposed && current === generation) loading.value = false }
}
function failureReason(error: unknown): FailureReason {
  if (error instanceof Error && error.message === 'keywordLimit') return 'keywordLimit'
  const status = isAxiosError(error) ? error.response?.status : null
  if (status === 403 || (error instanceof Error && error.message === 'permission')) return 'permission'
  if (status === 409 || (error instanceof Error && error.message === 'conflict')) return 'conflict'
  if (status === 404) return 'missing'
  return 'other'
}
async function run(operation: DocumentBulkOperation): Promise<void> {
  if (busy.value) return
  const snapshot = [...selectedEntries.value]
  if (!snapshot.length) return
  const current = ++operationGeneration
  const session = sessionGeneration()
  const active = (): boolean => !disposed && current === operationGeneration && session === sessionGeneration()
  busy.value = true; processed.value = 0; operationTotal.value = snapshot.length; outcome.value = null
  ++generation; controller?.abort(); loading.value = false
  const failed: Failure[] = []
  const succeeded: string[] = []
  try {
    for (const entry of snapshot) {
      if (!active()) break
      const finish = operation.kind === 'delete' ? mutations.beginDeletion(entry.item.id) : undefined
      try {
        if (finish === null) throw new Error('conflict')
        await applyDocumentBulkOperation(entry, operation, active)
        if (!active()) break
        succeeded.push(entry.item.id)
        selected.value = selected.value.filter(id => id !== entry.item.id)
        if (operation.kind === 'delete') emit('deleted', entry.item.id)
      } catch (error) {
        if (!active()) break
        failed.push({ id: entry.item.id, title: entry.item.title, reason: failureReason(error) })
      } finally { finish?.() }
      processed.value++
    }
  } finally {
    if (active()) {
      busy.value = false; dialogOpen.value = false
      outcome.value = { success: succeeded.length, failed }
      emit('changed', succeeded)
      await load()
    }
  }
}
function refresh(): void {
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { if (!busy.value) void load() }, 180)
}
function resetSession(event: Event): void {
  const session = sessionGeneration()
  if ((event as CustomEvent<string | null>).detail !== null && session === authSession) return
  authSession = session
  ++operationGeneration; ++generation; controller?.abort(); clearTimeout(refreshTimer)
  entries.value = []; selected.value = []; outcome.value = null; dialogOpen.value = false; busy.value = false; loading.value = false
  void load()
}
function invalidateAccess(): void {
  // Our own sharing/ownership writes invalidate access too. Every subsequent command
  // is authorized afresh; finish the batch before replacing its selection snapshot.
  if (busy.value) return
  ++generation; controller?.abort()
  entries.value = []; selected.value = []; dialogOpen.value = false
  void load()
}
watch([() => props.folder?.id, recursive, query, pageSize], () => {
  selected.value = []; outcome.value = null
  if (page.value !== 1) page.value = 1
  else void load()
})
watch(page, () => { selected.value = []; void load() })
onMounted(() => {
  void load()
  websocket.createWebsocket()
  for (const event of ['create', 'update', 'delete']) websocket.onEvent('memory', event, refresh)
  websocket.onEvent('memory', 'classification', refresh)
  websocket.onEvent('memory', 'invalidate', invalidateAccess)
  websocket.onConnect(refresh)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, resetSession)
})
onBeforeUnmount(() => {
  disposed = true; ++generation; ++operationGeneration; controller?.abort(); clearTimeout(refreshTimer)
  for (const event of ['create', 'update', 'delete']) websocket.offEvent('memory', event, refresh)
  websocket.offEvent('memory', 'classification', refresh)
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offConnect(refresh)
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, resetSession)
})
</script>

<style scoped>
.bulk-list { min-width: 0; }
.bulk-heading { overflow-wrap: anywhere; }
.bulk-search { flex: 1 1 240px; min-width: 0; max-width: 100%; }
.bulk-keyword { max-width: 100%; }
.bulk-document-link { color: var(--solaire-blue-accent); overflow-wrap: anywhere; }
.bulk-document-link:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
@media (max-width: 599px) { .bulk-thumbnail :deep(.document-thumbnail) { width: 56px; height: 44px; } }
</style>
