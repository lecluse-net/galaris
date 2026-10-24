<template>
  <q-page class="documents-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }">
    <PageHeader help-key="documents" :help-text="$t('contextHelpPages.documents')" :icon="navigationIcon('description')" :title="t('nav.documents')" :description="t('nav.documents_desc')">
      <template #title-after>
        <div class="row items-center q-gutter-xs">
          <DocumentNavigationButtons :can-go-back="canGoBack" :can-go-forward="canGoForward" @back="navigateHistory(-1)" @forward="navigateHistory(1)" />
          <q-btn v-if="!$q.screen.lt.md" flat round icon="folder_open" :aria-label="t('documents.toggleLibrary')" :aria-expanded="libraryOpen" @click="libraryOpen = !libraryOpen"><q-tooltip>{{ t('documents.toggleLibrary') }}</q-tooltip></q-btn>
        </div>
      </template>
    </PageHeader>

    <q-card flat bordered class="documents-workspace">
      <q-splitter v-model="splitterModel" :limits="[15, 55]" class="documents-splitter" :class="{ 'documents-splitter--list': listingOpen, 'documents-splitter--collapsed': !libraryOpen }">
        <template #before>
          <DocumentLibraryNavigation ref="navigation" :selected-document-id="selectedDocumentId" @action="documentRowAction" @browse="openListing" @loaded="onLibraryLoaded" @select="selectEntry" @create="openCreateDocument" />
        </template>
        <template #separator>
          <DocumentSplitterHandle />
        </template>
        <template #after>
          <q-splitter v-model="conversationSplitterModel" :limits="conversationSplitterLimits" :disable="!chatOpen || $q.screen.lt.md"
            class="documents-conversation-splitter" :class="{ 'documents-conversation-splitter--closed': !chatOpen || $q.screen.lt.md }">
            <template #before>
              <DocumentBulkList v-if="listingOpen" :folder="listingFolder" @action="documentRowAction" @create="entry => openCreateDocument(undefined, entry)" @close="listingOpen = false" @select="selectEntry" @deleted="onDocumentDeleted" @changed="ids => navigation?.refreshDocuments(ids)" />
              <div v-else-if="!selectedDocumentId" class="documents-placeholder text-grey-7">
                <q-icon name="article" size="48px" />
                <div>{{ t('documents.selectDocument') }}</div>
              </div>
              <DocumentEditor
                v-else-if="!$q.screen.lt.md"
                :key="`${selectedAgentId}:${selectedDocumentId}`"
                ref="documentEditor"
                :document-id="selectedDocumentId" :agent-id="selectedAgentId"
                :initial-document="selectedInitialDocument"
                @loaded="loadedDocumentId = $event.id"
                @updated="onDocumentUpdated" @unavailable="onDocumentUnavailable" @deleted="onDocumentDeleted"
              >
                <template v-if="canAccessChat" #toolbar-actions="{ exitFullscreen }">
                  <q-btn flat dense icon="forum" :aria-label="t('documents.conversation')" :aria-expanded="chatOpen" :color="chatOpen ? 'primary' : undefined" @click="exitFullscreen(); chatOpen = !chatOpen"><q-tooltip>{{ t('documents.conversation') }}</q-tooltip></q-btn>
                </template>
              </DocumentEditor>
            </template>
            <template #separator>
              <DocumentSplitterHandle role="separator" tabindex="0" aria-orientation="vertical"
                :aria-label="t('documents.resizeConversation')" :aria-valuenow="conversationSplitterModel"
                :aria-valuemin="conversationSplitterLimits[0]" :aria-valuemax="conversationSplitterLimits[1]" @keydown="resizeConversationWithKeyboard" />
            </template>
            <template #after>
              <aside v-if="chatStarted && canAccessChat" class="documents-chat-pane">
                <Teleport :to="mobileChatHost ?? 'body'" :disabled="!$q.screen.lt.md || !mobileChatHost">
                  <DocumentConversationPanel :document-id="displayedDocumentId" :before-send="prepareChatMessage" :capture-document-focus="captureChatDocumentFocus" :visible="chatOpen"
                    @close="chatOpen = false" @open-document="openChatDocument" />
                </Teleport>
              </aside>
            </template>
          </q-splitter>
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
            @loaded="loadedMobileDocumentId = $event.id"
            content-min-height="min(42vh, 420px)"
            @updated="onDocumentUpdated"
            @unavailable="onMobileDocumentUnavailable"
            @deleted="onDocumentDeleted"
          >
            <template v-if="canAccessChat" #toolbar-actions="{ exitFullscreen }">
              <q-btn flat dense icon="forum" :aria-label="t('documents.conversation')" :aria-expanded="chatOpen" @click="exitFullscreen(); chatOpen = true"><q-tooltip>{{ t('documents.conversation') }}</q-tooltip></q-btn>
            </template>
          </DocumentEditor>
        </div>
      </q-card>
    </q-dialog>

    <q-dialog v-if="$q.screen.lt.md && canAccessChat" v-model="chatOpen" maximized>
      <q-card class="documents-mobile-chat galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('documents.conversation') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <div ref="mobileChatHost" class="documents-mobile-chat-host" />
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
          <OwnerSelect v-model="createDocumentOwner" :options="createOwnerChoices" :loading="createOwnerOptionsLoading" @open="refreshCreateOwners">
          </OwnerSelect>
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
          <q-btn v-close-popup flat no-caps :label="t('document.cancel')" />
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
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useAgentStore } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { AgentConversationPanel as DocumentConversationPanel, conversationPanel, type DocumentFocus } from '@/core/util'
import { OwnerSelect } from '@/app/share'
import { documentIdFromRouteQuery, documentNavigationKey, documentResourceHref, DocumentNavigationButtons, PageHeader, useDocumentHistory } from '@/core/util'
import { websocket } from '@/core/websocket'
import { DatasetDocumentRedirect, documentService } from '../services/documentService'
import type { DocumentRowAction } from '@/app/document/libraryShortcuts'
import type {
  DocumentTag,
  DocumentLibraryEntry,
  DocumentOwnerKind,
  DocumentOwnerOptions,
  DocumentDetail,
  DocumentNodeKind,
} from '../types'
import DocumentEditor from '@/app/document/components/DocumentEditor.vue'
import DocumentIcon from '@/app/document/components/DocumentIcon.vue'
import DocumentLibraryNavigation from '@/app/document/components/DocumentLibraryNavigation.vue'
import DocumentSplitterHandle from '@/app/document/components/DocumentSplitterHandle.vue'
import DocumentBulkList from '@/app/document/components/DocumentBulkList.vue'

interface MemoryRealtimeEvent { data: { id: string; node_kind: DocumentNodeKind } }

const { t } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const canAccessChat = computed(() => Boolean(conversationPanel) && privilegeStore.hasPrivilege(privileges.CHAT_ACCESS))
const chatOpen = ref(false), chatStarted = ref(false), libraryOpen = ref(true)
const loadedDocumentId = ref<string | null>(null), loadedMobileDocumentId = ref<string | null>(null)
watch(chatOpen, open => { if (open) chatStarted.value = true })
watch(canAccessChat, allowed => { if (!allowed) { chatOpen.value = false; chatStarted.value = false } })
const documentEditor = useTemplateRef<InstanceType<typeof DocumentEditor>>('documentEditor')
const mobileChatHost = useTemplateRef<HTMLElement>('mobileChatHost')
const mobileDocumentEditor = useTemplateRef<InstanceType<typeof DocumentEditor>>('mobileDocumentEditor')
const navigation = useTemplateRef<InstanceType<typeof DocumentLibraryNavigation>>('navigation')
const entries = ref<DocumentLibraryEntry[]>([])
const splitterModel = ref(30)
const conversationSplitterModel = ref(60)
const conversationSplitterLimits: [number, number] = [30, 80]
function resizeConversationWithKeyboard(event: KeyboardEvent): void {
  const [minimum, maximum] = conversationSplitterLimits
  const value = event.key === 'Home' ? minimum : event.key === 'End' ? maximum
    : event.key === 'ArrowLeft' ? conversationSplitterModel.value - 2
      : event.key === 'ArrowRight' ? conversationSplitterModel.value + 2 : null
  if (value === null) return
  event.preventDefault()
  conversationSplitterModel.value = Math.min(maximum, Math.max(minimum, value))
}
const listingOpen = ref(false)
const listingFolder = ref<DocumentTag | null>(null)
const selectedNodeKey = ref<string | null>(null)
const selectedAgentId = ref<number | null>(null)
const selectedInitialDocument = ref<DocumentDetail | null>(null)
const mobileDocumentOpen = ref(false)
const mobileDocumentId = ref<string | null>(null)
const mobileDocumentAgentId = ref<number | null>(null)
const mobileInitialDocument = ref<DocumentDetail | null>(null)
const history = useDocumentHistory({
  active: () => !disposed,
  href: documentResourceHref,
  navigate: async (id, position) => {
    await openRouteDocument(id, position)
    return ($q.screen.lt.md ? mobileDocumentId.value : selectedDocumentId.value) === id
  },
})
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
const displayedDocumentId = computed(() => {
  if ($q.screen.lt.md) return mobileDocumentOpen.value && loadedMobileDocumentId.value === mobileDocumentId.value ? loadedMobileDocumentId.value : null
  return !listingOpen.value && loadedDocumentId.value === selectedDocumentId.value ? loadedDocumentId.value : null
})
watch(() => [selectedDocumentId.value, selectedAgentId.value], () => { loadedDocumentId.value = null }, { flush: 'sync' })
watch(() => [mobileDocumentId.value, mobileDocumentAgentId.value], () => { loadedMobileDocumentId.value = null }, { flush: 'sync' })
async function prepareChatMessage(): Promise<boolean> {
  const generation = selectionGeneration, id = displayedDocumentId.value
  const editor = $q.screen.lt.md ? mobileDocumentEditor.value : documentEditor.value
  if (editor && !await editor.flush()) {
    $q.notify({ type: 'negative', message: t('documents.autosaveError') })
    return false
  }
  return !disposed && generation === selectionGeneration && displayedDocumentId.value === id
}
function captureChatDocumentFocus(): DocumentFocus | null {
  if (!displayedDocumentId.value) return null
  const editor = $q.screen.lt.md ? mobileDocumentEditor.value : documentEditor.value
  return editor?.captureFocus() ?? null
}
async function openChatDocument(id: string): Promise<void> {
  await openRouteDocument(id)
  if ($q.screen.lt.md && mobileDocumentId.value === id) chatOpen.value = false
}
const mobileDocumentTitle = computed(() => (
  entries.value.find(entry => entry.item.id === mobileDocumentId.value)?.item.title
  ?? t('nav.documents')
))
const createOwnerChoices = computed(() => [...createOwnerOptions.value.users, ...createOwnerOptions.value.agents])
const selectedCreateDocumentOwner = computed(() => createOwnerChoices.value.find(option => createOwnerValue(option.kind, option.id) === createDocumentOwner.value) ?? null)
function createOwnerValue(kind: DocumentOwnerKind, id: number): string { return `${kind}:${id}` }
function preferredAgent(entry: DocumentLibraryEntry): number | null {
  if (entry.user_access?.can_write) return null
  if (entry.item.owner_agent_id !== null && entry.agent_ids.includes(entry.item.owner_agent_id)) return entry.item.owner_agent_id
  return entry.writable_agent_ids[0] ?? entry.agent_ids[0] ?? null
}
function recordNavigation(id: string, position?: number): void {
  history.record(id, position)
}
async function navigateHistory(direction: -1 | 1): Promise<void> {
  if (navigatingHistory.value) return
  const target = history.target(direction)
  if (!target) return
  navigatingHistory.value = true
  try {
    await history.go(direction)
  } finally {
    navigatingHistory.value = false
  }
}
async function selectDocument(id: string, agentId: number | null, initialDocument: DocumentDetail | null = null, historyIndex?: number): Promise<void> {
  const selection = ++selectionGeneration
  if (id !== selectedDocumentId.value && documentEditor.value) {
    const saved = await documentEditor.value.flush()
    if (!saved) {
      $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
  }
  if (disposed || leavingPage || selection !== selectionGeneration) return
  listingOpen.value = false
  selectedInitialDocument.value = initialDocument
  selectedAgentId.value = agentId
  selectedNodeKey.value = `document:${agentId ?? 'user'}:${id}`
  recordNavigation(id, historyIndex)
}
async function openMobileDocument(id: string, agentId: number | null, initialDocument: DocumentDetail | null = null, historyIndex?: number): Promise<void> {
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
  if (!listingOpen.value && !selectedDocumentId.value && !documentIdFromRouteQuery(route.query.document_id) && !$q.screen.lt.md && loaded[0]) void selectEntry(loaded[0])
}
async function openListing(folder: DocumentTag | null): Promise<void> {
  const selection = ++selectionGeneration
  if (documentEditor.value && !await documentEditor.value.flush()) {
    $q.notify({ type: 'negative', message: t('documents.autosaveError') })
    return
  }
  if (disposed || leavingPage || selection !== selectionGeneration) return
  listingFolder.value = folder
  listingOpen.value = true
}
async function selectEntry(entry: DocumentLibraryEntry): Promise<void> {
  const actor = preferredAgent(entry)
  if ($q.screen.lt.md) await openMobileDocument(entry.item.id, actor)
  else await selectDocument(entry.item.id, actor)
}
async function documentRowAction(entry: DocumentLibraryEntry, action: DocumentRowAction): Promise<void> {
  await selectEntry(entry)
  await nextTick()
  const editor = $q.screen.lt.md ? mobileDocumentEditor.value : documentEditor.value
  editor?.requestRowAction(action, entry.item.id)
}
async function openCreateDocument(tag?: DocumentTag, parent?: DocumentLibraryEntry): Promise<void> {
  createDocumentTag.value = tag ?? null
  createDocumentParent.value = parent ?? null
  createDocumentActorAgentId.value = selectedAgentId.value ?? agentStore.sortedAgents[0]?.id ?? null
  createDocumentTitle.value = ''
  createDocumentOwner.value = ''
  createOwnerOptions.value = { agents: [], users: [] }
  createDocumentOpen.value = true
  createOwnerOptionsLoading.value = true
  try {
    createOwnerOptions.value = await documentService.listDocumentOwnerOptions()
    createDocumentActorAgentId.value ??= createOwnerOptions.value.agents[0]?.id ?? null
    const currentUser = createOwnerOptions.value.users.find(option => option.is_current_user)
    if (currentUser) createDocumentOwner.value = createOwnerValue('user', currentUser.id)
  } catch {
    $q.notify({ type: 'negative', message: t('documents.ownerLoadError') })
  } finally {
    createOwnerOptionsLoading.value = false
  }
}
async function refreshCreateOwners(): Promise<void> {
  try {
    const owners = await documentService.listDocumentOwnerOptions()
    if (!disposed && createDocumentOpen.value) createOwnerOptions.value = owners
  } catch { if (!disposed) $q.notify({ type: 'negative', message: t('documents.ownerLoadError') }) }
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
    const document = await documentService.createDocument({
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
        if (parent) await documentService.moveDocumentUnderDocument(document.id, parent.item.id)
        else if (tag) await documentService.moveDocumentToTag(document.id, tag.id)
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
function onDocumentUpdated(document: DocumentDetail): void {
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
  if (loadedDocumentId.value === id) loadedDocumentId.value = null
  if (loadedMobileDocumentId.value === id) loadedMobileDocumentId.value = null
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
    const detail = await documentService.getManagedDocument(id)
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
  const owner = createOwnerChoices.value.find(option => createOwnerValue(option.kind, option.id) === value)
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
  websocket.onEvent('document', 'create', realtimeRefresh)
  websocket.onEvent('document', 'update', realtimeRefresh)
  websocket.onEvent('document', 'delete', realtimeDelete)
})
onBeforeUnmount(() => {
  disposed = true
  pageMounted = false
  removeNavigationObserver()
  websocket.offEvent('document', 'create', realtimeRefresh)
  websocket.offEvent('document', 'update', realtimeRefresh)
  websocket.offEvent('document', 'delete', realtimeDelete)
})
</script>

<style scoped>
.documents-workspace, .documents-splitter { min-height: min(760px, calc(100vh - 260px)); }
.documents-workspace { position: relative; display: flex; }
.documents-splitter { flex: 1; min-width: 0; }
.documents-conversation-splitter { height: 100%; min-width: 0; min-height: 0; }
.documents-conversation-splitter :deep(> .q-splitter__panel) { min-height: 0; }
.documents-conversation-splitter :deep(> .q-splitter__before) { overflow: auto; }
.documents-conversation-splitter :deep(> .q-splitter__after) { display: flex; flex-direction: column; align-self: stretch; height: auto; overflow: hidden; }
.documents-conversation-splitter :deep(> .q-splitter__separator) { background: color-mix(in srgb, var(--q-dark) 10%, transparent); }
.documents-conversation-splitter--closed :deep(> .q-splitter__before) { width: 100% !important; }
.documents-conversation-splitter--closed :deep(> .q-splitter__after), .documents-conversation-splitter--closed :deep(> .q-splitter__separator) { display: none; }
.documents-chat-pane { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; }
.documents-chat-pane :deep(> .document-conversation) { flex: 1; height: auto; }
.documents-mobile-chat { display: flex; flex-direction: column; }
.documents-mobile-chat-host { flex: 1; min-height: 0; }
.documents-splitter--collapsed :deep(> .q-splitter__before), .documents-splitter--collapsed :deep(> .q-splitter__separator) { display: none; }
.documents-splitter--collapsed :deep(> .q-splitter__after) { width: 100% !important; }
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
  .documents-splitter :deep(> .q-splitter__after) { overflow: hidden; }

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
  .documents-splitter--list :deep(> .q-splitter__before) { display: none; }
  .documents-splitter--list :deep(> .q-splitter__after) { display: block; width: 100% !important; overflow: auto; }
}
</style>
