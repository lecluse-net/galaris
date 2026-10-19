<template>
  <q-page class="documents-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }">
    <PageHeader help-key="documents" :help-text="$t('contextHelpPages.documents')" :icon="navigationIcon('description')" :title="t('nav.documents')" :description="t('nav.documents_desc')">
      <template #title-after>
        <DocumentNavigationButtons :can-go-back="canGoBack" :can-go-forward="canGoForward" @back="navigateHistory(-1)" @forward="navigateHistory(1)" />
      </template>
    </PageHeader>

    <q-card flat bordered class="documents-workspace">
      <q-splitter v-model="splitterModel" :limits="[20, 55]" class="documents-splitter">
        <template #before>
          <DocumentLibraryNavigation ref="navigation" :selected-document-id="selectedDocumentId" @loaded="onLibraryLoaded" @select="selectEntry" @create="openCreateDocument" />
        </template>
        <template #separator>
          <DocumentSplitterHandle />
        </template>
        <template #after>
          <div v-if="!selectedDocumentId" class="documents-placeholder text-grey-7">
            <q-icon name="article" size="48px" />
            <div>{{ t('documents.selectDocument') }}</div>
          </div>
          <DocumentEditor
            v-else-if="!$q.screen.lt.md"
            :key="`${selectedAgentId}:${selectedDocumentId}`"
            ref="documentEditor"
            :document-id="selectedDocumentId" :agent-id="selectedAgentId"
            :initial-document="selectedInitialDocument"
            @updated="onDocumentUpdated" @unavailable="onDocumentUnavailable" @deleted="onDocumentDeleted"
          />
        </template>
      </q-splitter>
    </q-card>

    <q-dialog
      v-model="mobileDocumentOpen"
      allow-focus-outside
      no-route-dismiss
      maximized
      @before-hide="flushMobileDocumentEditor"
      @hide="clearMobileDocument"
    >
      <q-card class="documents-mobile-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <DocumentNavigationButtons class="q-mr-sm" :can-go-back="canGoBack" :can-go-forward="canGoForward" @back="navigateHistory(-1)" @forward="navigateHistory(1)" />
          <DocumentIcon v-if="mobileDocumentId" :document-id="mobileDocumentId" :title="mobileDocumentTitle" size="36px" class="q-mr-sm" />
          <div class="text-h6 ellipsis">{{ mobileDocumentTitle }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <div class="documents-mobile-editor galaris-dialog-body">
          <DocumentEditor
            v-if="$q.screen.lt.md && mobileDocumentId !== null"
            :key="`${mobileDocumentAgentId}:${mobileDocumentId}`"
            ref="mobileDocumentEditor"
            :document-id="mobileDocumentId"
            :agent-id="mobileDocumentAgentId"
            :initial-document="mobileInitialDocument"
            content-min-height="min(42vh, 420px)"
            @updated="onDocumentUpdated"
            @unavailable="onMobileDocumentUnavailable"
            @deleted="onDocumentDeleted"
          />
        </div>
      </q-card>
    </q-dialog>

    <q-dialog v-model="createDocumentOpen">
      <q-card class="documents-create-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="note_add" size="24px" class="q-mr-sm" />
          <div class="text-h6">{{ createDocumentParent ? t('documents.library.newSubdocument', { name: createDocumentParent.item.title }) : createDocumentTag ? t('documents.library.newDocument', { name: createDocumentTag.name }) : t('documents.createDocument') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section class="q-gutter-md galaris-dialog-body">
          <q-select
            v-model="createDocumentOwner"
            :options="filteredCreateOwnerOptions"
            emit-value map-options outlined use-input
            input-debounce="0"
            option-value="value"
            option-label="label"
            option-disable="disable"
            :loading="createOwnerOptionsLoading"
            :label="t('documents.owner')"
            @filter="filterCreateOwnerOptions"
          >
            <template #option="scope">
              <q-item v-if="scope.opt.section" dense>
                <q-item-section>
                  <q-item-label header>{{ scope.opt.label }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-else v-bind="scope.itemProps">
                <q-item-section avatar>
                  <AgentAvatar
                    v-if="scope.opt.kind === 'agent'"
                    :agent-id="scope.opt.id"
                    :name="scope.opt.label"
                    size="32px"
                  />
                  <q-avatar v-else size="32px" color="grey-3" text-color="grey-8">
                    <img v-if="scope.opt.avatarUrl" :src="scope.opt.avatarUrl" alt="" />
                    <q-icon v-else name="person" size="20px" />
                  </q-avatar>
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ scope.opt.label }}</q-item-label>
                  <q-item-label caption>{{ scope.opt.subtitle }}</q-item-label>
                </q-item-section>
              </q-item>
            </template>
            <template #no-option>
              <q-item><q-item-section class="text-grey-7">{{ t('documents.ownerEmpty') }}</q-item-section></q-item>
            </template>
          </q-select>
          <q-input
            v-model="createDocumentTitle"
            outlined autofocus
            :label="t('documents.title')"
            :rules="[value => Boolean(value.trim()) || t('documents.required')]"
            @keyup.enter="createDocument"
          />
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat no-caps :label="t('memory.cancel')" />
          <q-btn
            color="primary" unelevated no-caps icon="add"
            :loading="creatingDocument"
            :disable="!createDocumentTitle.trim() || !selectedCreateDocumentOwner || createDocumentActorAgentId === null"
            :label="t('documents.create')"
            @click="createDocument"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onBeforeUnmount, onMounted, provide, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { AgentAvatar, useAgentStore } from '@/app/agent'
import { documentIdFromRouteQuery, documentNavigationKey, documentResourceHref, DocumentNavigationButtons, PageHeader, useDocumentHistory } from '@/core/util'
import { websocket } from '@/core/websocket'
import { DatasetDocumentRedirect, memoryService } from '../services/memoryService'
import type {
  DocumentTag,
  DocumentLibraryEntry,
  DocumentOwnerKind,
  DocumentOwnerOption,
  DocumentOwnerOptions,
  MemoryItemDetail,
  MemoryNodeKind,
} from '../types'
import DocumentEditor from './DocumentEditor.vue'
import DocumentIcon from './DocumentIcon.vue'
import DocumentLibraryNavigation from './DocumentLibraryNavigation.vue'
import DocumentSplitterHandle from './DocumentSplitterHandle.vue'

interface MemoryRealtimeEvent { data: { id: string; node_kind: MemoryNodeKind } }
interface CreateOwnerChoice {
  value: string
  label: string
  subtitle: string
  kind: DocumentOwnerKind
  id: number
  avatarUrl: string | null
  searchText: string
  disable?: false
  section?: false
}
interface CreateOwnerSection {
  value: string
  label: string
  disable: true
  section: true
}
type CreateOwnerSelectOption = CreateOwnerChoice | CreateOwnerSection

const { t, locale } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const documentEditor = useTemplateRef<InstanceType<typeof DocumentEditor>>('documentEditor')
const mobileDocumentEditor = useTemplateRef<InstanceType<typeof DocumentEditor>>('mobileDocumentEditor')
const navigation = useTemplateRef<InstanceType<typeof DocumentLibraryNavigation>>('navigation')
const entries = ref<DocumentLibraryEntry[]>([])
const splitterModel = ref(30)
const selectedNodeKey = ref<string | null>(null)
const selectedAgentId = ref<number | null>(null)
const selectedInitialDocument = ref<MemoryItemDetail | null>(null)
const mobileDocumentOpen = ref(false)
const mobileDocumentId = ref<string | null>(null)
const mobileDocumentAgentId = ref<number | null>(null)
const mobileInitialDocument = ref<MemoryItemDetail | null>(null)
const history = useDocumentHistory()
const navigatingHistory = ref(false)
const canGoBack = computed(() => !navigatingHistory.value && history.canGoBack.value)
const canGoForward = computed(() => !navigatingHistory.value && history.canGoForward.value)
const createDocumentOpen = ref(false)
const creatingDocument = ref(false)
const createDocumentOwner = ref('')
const createDocumentActorAgentId = ref<number | null>(null)
const createDocumentTitle = ref('')
const createDocumentTag = ref<DocumentTag | null>(null)
const createDocumentParent = ref<DocumentLibraryEntry | null>(null)
const createOwnerOptions = ref<DocumentOwnerOptions>({ agents: [], users: [] })
const filteredCreateOwnerOptions = ref<CreateOwnerSelectOption[]>([])
const createOwnerOptionsLoading = ref(false)
let pageMounted = false
let leavingPage = false
let disposed = false
let selectionGeneration = 0
const removeNavigationObserver = router.afterEach((_to, _from, failure) => {
  // A later guard may cancel leaving; the still-mounted library must stay usable.
  if (failure && !disposed) leavingPage = false
})

const selectedDocumentId = computed(() => {
  const parts = selectedNodeKey.value?.split(':') ?? []
  return parts[0] === 'document' && parts.length >= 3 ? parts.slice(2).join(':') : null
})
const mobileDocumentTitle = computed(() => (
  entries.value.find(entry => entry.item.id === mobileDocumentId.value)?.item.title
  ?? t('nav.documents')
))
const createOwnerChoices = computed<CreateOwnerChoice[]>(() => [
  ...createOwnerOptions.value.agents.map(createOwnerChoice),
  ...createOwnerOptions.value.users.map(createOwnerChoice),
])
const selectedCreateDocumentOwner = computed(() => (
  createOwnerChoices.value.find(option => option.value === createDocumentOwner.value) ?? null
))
function createOwnerValue(kind: DocumentOwnerKind, id: number): string {
  return `${kind}:${id}`
}
function createOwnerChoice(option: DocumentOwnerOption): CreateOwnerChoice {
  const label = option.is_current_user ? t('documents.ownerMe') : option.label
  return {
    value: createOwnerValue(option.kind, option.id),
    label,
    subtitle: option.is_current_user ? option.label : option.subtitle,
    kind: option.kind,
    id: option.id,
    avatarUrl: option.avatar_url,
    searchText: `${label} ${option.label} ${option.subtitle}`.toLocaleLowerCase(locale.value),
  }
}
function sectionCreateOwnerOptions(choices: CreateOwnerChoice[]): CreateOwnerSelectOption[] {
  const agents = choices.filter(choice => choice.kind === 'agent')
  const users = choices.filter(choice => choice.kind === 'user')
  const options: CreateOwnerSelectOption[] = []
  if (agents.length) {
    options.push({ value: 'section:agents', label: t('documents.ownerAgents'), disable: true, section: true })
    options.push(...agents)
  }
  if (users.length) {
    options.push({ value: 'section:users', label: t('documents.ownerUsers'), disable: true, section: true })
    options.push(...users)
  }
  return options
}
function filterCreateOwnerOptions(value: string, update: (callback: () => void) => void): void {
  update(() => {
    const needle = value.trim().toLocaleLowerCase(locale.value)
    const choices = needle
      ? createOwnerChoices.value.filter(option => option.searchText.includes(needle))
      : createOwnerChoices.value
    filteredCreateOwnerOptions.value = sectionCreateOwnerOptions(choices)
  })
}
function preferredAgent(entry: DocumentLibraryEntry): number | null {
  if (entry.user_access?.can_write) return null
  if (entry.item.owner_agent_id !== null && entry.agent_ids.includes(entry.item.owner_agent_id)) return entry.item.owner_agent_id
  return entry.writable_agent_ids[0] ?? entry.agent_ids[0] ?? null
}
function recordNavigation(id: string, position?: number): void {
  history.record(id, position)
  if (documentIdFromRouteQuery(route.query.document_id) !== id) void router.replace(documentResourceHref(id))
}
async function navigateHistory(direction: -1 | 1): Promise<void> {
  if (navigatingHistory.value) return
  const target = history.target(direction)
  if (!target) return
  navigatingHistory.value = true
  try {
    await openRouteDocument(target.id, target.position)
  } finally {
    navigatingHistory.value = false
  }
}
async function selectDocument(id: string, agentId: number | null, initialDocument: MemoryItemDetail | null = null, historyIndex?: number): Promise<void> {
  const selection = ++selectionGeneration
  if (id !== selectedDocumentId.value && documentEditor.value) {
    const saved = await documentEditor.value.flush()
    if (!saved) {
      $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
  }
  if (disposed || leavingPage || selection !== selectionGeneration) return
  selectedInitialDocument.value = initialDocument
  selectedAgentId.value = agentId
  selectedNodeKey.value = `document:${agentId ?? 'user'}:${id}`
  recordNavigation(id, historyIndex)
}
async function openMobileDocument(id: string, agentId: number | null, initialDocument: MemoryItemDetail | null = null, historyIndex?: number): Promise<void> {
  const selection = ++selectionGeneration
  if (id !== mobileDocumentId.value && mobileDocumentEditor.value) {
    const saved = await mobileDocumentEditor.value.flush()
    if (!saved) {
      $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
  }
  if (disposed || leavingPage || selection !== selectionGeneration) return
  mobileInitialDocument.value = initialDocument
  mobileDocumentId.value = id
  mobileDocumentAgentId.value = agentId
  mobileDocumentOpen.value = true
  recordNavigation(id, historyIndex)
}
function onLibraryLoaded(loaded: DocumentLibraryEntry[]): void {
  entries.value = loaded
  if (!selectedDocumentId.value && !documentIdFromRouteQuery(route.query.document_id) && !$q.screen.lt.md && loaded[0]) void selectEntry(loaded[0])
}
async function selectEntry(entry: DocumentLibraryEntry): Promise<void> {
  const actor = preferredAgent(entry)
  if ($q.screen.lt.md) await openMobileDocument(entry.item.id, actor)
  else await selectDocument(entry.item.id, actor)
}
async function openCreateDocument(tag?: DocumentTag, parent?: DocumentLibraryEntry): Promise<void> {
  createDocumentTag.value = tag ?? null
  createDocumentParent.value = parent ?? null
  createDocumentActorAgentId.value = selectedAgentId.value ?? agentStore.sortedAgents[0]?.id ?? null
  createDocumentTitle.value = ''
  createDocumentOwner.value = ''
  createOwnerOptions.value = { agents: [], users: [] }
  filteredCreateOwnerOptions.value = []
  createDocumentOpen.value = true
  createOwnerOptionsLoading.value = true
  try {
    createOwnerOptions.value = await memoryService.listDocumentOwnerOptions()
    createDocumentActorAgentId.value ??= createOwnerOptions.value.agents[0]?.id ?? null
    filteredCreateOwnerOptions.value = sectionCreateOwnerOptions(createOwnerChoices.value)
    const currentUser = createOwnerOptions.value.users.find(option => option.is_current_user)
    if (currentUser) createDocumentOwner.value = createOwnerValue('user', currentUser.id)
  } catch {
    $q.notify({ type: 'negative', message: t('documents.ownerLoadError') })
  } finally {
    createOwnerOptionsLoading.value = false
  }
}
async function createDocument(): Promise<void> {
  const owner = selectedCreateDocumentOwner.value
  const actorAgentId = owner?.kind === 'agent' ? owner.id : createDocumentActorAgentId.value
  const title = createDocumentTitle.value.trim()
  const tag = createDocumentTag.value
  const parent = createDocumentParent.value
  if (!owner || actorAgentId === null || !title || creatingDocument.value) return
  creatingDocument.value = true
  try {
    const document = await memoryService.createDocument({
      document_type: 'html',
      owner_kind: owner.kind,
      owner_id: owner.id,
      actor_agent_id: actorAgentId,
      title,
      folder: '',
    })
    createDocumentOpen.value = false
    let classified = false
    if (tag || parent) {
      try {
        if (parent) await memoryService.moveDocumentUnderDocument(document.id, parent.item.id)
        else if (tag) await memoryService.moveDocumentToTag(document.id, tag.id)
        classified = true
      } catch {
        $q.notify({ type: 'warning', message: parent
          ? t('documents.createdUnnested', { name: parent.item.title })
          : t('documents.createdUnclassified', { name: tag?.name }) })
      }
    }
    navigation.value?.refreshDocuments([document.id], classified ? tag?.id : undefined, classified ? parent?.item.id : undefined)
    const documentActor = owner.kind === 'user' ? null : actorAgentId
    if ($q.screen.lt.md) await openMobileDocument(document.id, documentActor)
    else await selectDocument(document.id, documentActor)
    if ((!tag && !parent) || classified) $q.notify({ type: 'positive', message: t('documents.created') })
  } catch {
    $q.notify({ type: 'negative', message: t('documents.createError') })
  } finally {
    creatingDocument.value = false
  }
}
function onDocumentUpdated(document: MemoryItemDetail): void {
  entries.value = entries.value.map(entry => entry.item.id === document.id ? { ...entry, item: document } : entry)
  navigation.value?.updateDocument(document)
}
function onDocumentDeleted(id: string): void {
  // Deleted visits no longer provide a destination, without shifting an in-flight cursor.
  history.forget(id)
  ++selectionGeneration
  if (selectedDocumentId.value === id) selectedNodeKey.value = null
  if (mobileDocumentId.value === id) mobileDocumentOpen.value = false
  navigation.value?.removeDocument(id)
}
function onDocumentUnavailable(id: string): void {
  // A deletion already removed this row; avoid a second full-library refresh.
  if (entries.value.some(entry => entry.item.id === id)) navigation.value?.refreshDocuments([id])
}
function onMobileDocumentUnavailable(id: string): void {
  mobileDocumentOpen.value = false
  onDocumentUnavailable(id)
}
async function openRouteDocument(id: string, historyIndex?: number): Promise<void> {
  const selection = ++selectionGeneration
  const entry = entries.value.find(value => value.item.id === id)
  const agentId = entry ? preferredAgent(entry) : null
  if (agentId !== null || entry?.user_access?.can_read) {
    if ($q.screen.lt.md) await openMobileDocument(id, agentId, null, historyIndex)
    else await selectDocument(id, agentId, null, historyIndex)
    return
  }
  try {
    const detail = await memoryService.getManagedDocument(id)
    if (disposed || leavingPage || selection !== selectionGeneration) return
    if ($q.screen.lt.md) await openMobileDocument(id, detail.agent_id, detail.item, historyIndex)
    else await selectDocument(id, detail.agent_id, detail.item, historyIndex)
  } catch (error) {
    if (disposed || leavingPage || selection !== selectionGeneration) return
    if (error instanceof DatasetDocumentRedirect) await router.replace(error.href)
    else $q.notify({ type: 'negative', message: t('documents.loadError') })
  }
}

provide(documentNavigationKey, id => openRouteDocument(id))

function flushMobileDocumentEditor(): void {
  void mobileDocumentEditor.value?.flush()
}
function clearMobileDocument(): void {
  if (mobileDocumentOpen.value) return
  mobileDocumentId.value = null
  mobileDocumentAgentId.value = null
}

function realtimeRefresh(response: MemoryRealtimeEvent): void {
  if (response.data.node_kind !== 'document') return
  navigation.value?.refreshDocuments([response.data.id])
}
function realtimeDelete(response: MemoryRealtimeEvent): void {
  if (response.data.node_kind === 'document') onDocumentDeleted(response.data.id)
}

watch(() => $q.screen.lt.md, mobile => {
  if (!mobile) mobileDocumentOpen.value = false
})
watch(createDocumentOwner, value => {
  const owner = createOwnerChoices.value.find(option => option.value === value)
  if (owner?.kind === 'agent') createDocumentActorAgentId.value = owner.id
})
watch(() => route.query.document_id, value => {
  const id = documentIdFromRouteQuery(value)
  const currentId = $q.screen.lt.md ? mobileDocumentId.value : selectedDocumentId.value
  if (pageMounted && id && id !== currentId) void openRouteDocument(id)
})
onBeforeRouteLeave(async () => {
  // An automatic selection must not replace the navigation while its lazy chunk loads.
  leavingPage = true
  try {
    const editor = $q.screen.lt.md ? mobileDocumentEditor.value : documentEditor.value
    const saved = editor ? await editor.flush() : true
    if (!saved) leavingPage = false
    return saved
  } catch (error) {
    leavingPage = false
    throw error
  }
})
onMounted(async () => {
  await agentStore.fetchAgents()
  if (disposed) return
  const routeId = documentIdFromRouteQuery(route.query.document_id)
  if (routeId) await openRouteDocument(routeId)
  if (disposed) return
  pageMounted = true
  websocket.createWebsocket()
  websocket.onEvent('memory', 'create', realtimeRefresh)
  websocket.onEvent('memory', 'update', realtimeRefresh)
  websocket.onEvent('memory', 'delete', realtimeDelete)
})
onBeforeUnmount(() => {
  disposed = true
  pageMounted = false
  removeNavigationObserver()
  websocket.offEvent('memory', 'create', realtimeRefresh)
  websocket.offEvent('memory', 'update', realtimeRefresh)
  websocket.offEvent('memory', 'delete', realtimeDelete)
})
</script>

<style scoped>
.documents-workspace, .documents-splitter { min-height: min(760px, calc(100vh - 260px)); }
.documents-workspace { position: relative; }
.documents-splitter :deep(> .q-splitter__before) { overflow: auto; }
.documents-splitter :deep(> .q-splitter__separator) { background: color-mix(in srgb, var(--q-dark) 10%, transparent); }
.documents-splitter :deep(.q-splitter__separator:hover),
.documents-splitter :deep(.q-splitter__separator:focus-visible) { background: color-mix(in srgb, var(--q-primary) 28%, transparent); }
.documents-placeholder { min-height: min(680px, calc(100vh - 320px)); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.document-tree-row { min-width: 0; min-height: 28px; border-radius: 6px; padding: 1px 4px; transition: background-color 120ms ease, box-shadow 120ms ease; }
.document-tree-row[draggable='true'] { cursor: grab; }
.document-tree-row--drop { background: color-mix(in srgb, var(--q-primary) 16%, transparent); box-shadow: inset 0 0 0 1px var(--q-primary); }
.document-tree-row--moving { opacity: .55; }
.document-recent-badge { width: 8px; min-width: 8px; height: 8px; padding: 0; }
.documents-create-dialog { width: min(560px, calc(100vw - 32px)); }
.documents-mobile-dialog { display: flex; min-width: 0; flex-direction: column; }
.documents-mobile-editor { min-height: 0; flex: 1 1 auto; overflow-y: auto; }
@media (min-width: 1024px) {
  .documents-page {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding-bottom: 0;
  }

  .documents-page > :not(.documents-workspace) {
    flex-shrink: 0;
  }

  .documents-workspace {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .documents-splitter {
    height: 100%;
    min-height: 0;
  }

  .documents-splitter :deep(> .q-splitter__before),
  .documents-splitter :deep(> .q-splitter__after) {
    min-height: 0;
    overflow: auto;
  }

  .documents-placeholder {
    height: 100%;
    min-height: 0;
  }
}
@media (max-width: 1023.98px) {
  .documents-splitter { height: calc(100dvh - 170px); min-height: 420px; }
  .documents-splitter :deep(> .q-splitter__before) { width: 100% !important; }
  .documents-splitter :deep(> .q-splitter__separator),
  .documents-splitter :deep(> .q-splitter__after) { display: none; }
}
</style>
