<template>
  <q-page class="documents-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }">
    <PageHeader help-key="documents" :help-text="$t('contextHelpPages.documents')" :icon="navigationIcon('description')" :title="t('nav.documents')" :description="t('nav.documents_desc')" />

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
            @updated="onDocumentUpdated" @unavailable="onDocumentUnavailable" @deleted="selectedNodeKey = null"
          />
        </template>
      </q-splitter>
    </q-card>

    <q-dialog
      v-model="mobileDocumentOpen"
      allow-focus-outside
      maximized
      @before-hide="flushMobileDocumentEditor"
      @hide="clearMobileDocument"
    >
      <q-card class="documents-mobile-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <DocumentIcon v-if="mobileDocumentId" :document-id="mobileDocumentId" :title="mobileDocumentTitle" size="36px" class="q-mr-sm" />
          <div class="text-h6 ellipsis">{{ mobileDocumentTitle }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <div class="documents-mobile-editor">
          <DocumentEditor
            v-if="$q.screen.lt.md && mobileDocumentId !== null"
            :key="`${mobileDocumentAgentId}:${mobileDocumentId}`"
            ref="mobileDocumentEditor"
            :document-id="mobileDocumentId"
            :agent-id="mobileDocumentAgentId"
            content-min-height="min(42vh, 420px)"
            @updated="onDocumentUpdated"
            @unavailable="onMobileDocumentUnavailable"
          />
        </div>
      </q-card>
    </q-dialog>

    <q-dialog v-model="createDocumentOpen">
      <q-card class="documents-create-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="note_add" size="24px" class="q-mr-sm" />
          <div class="text-h6">{{ t('documents.createDocument') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section class="q-gutter-md">
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
          <q-select v-model="createDocumentType" outlined emit-value map-options :label="t('documents.documentType')" :options="documentTypeOptions" />
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
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { AgentAvatar, useAgentStore } from '@/app/agent'
import { documentIdFromRouteQuery, documentResourceHref, PageHeader } from '@/core/util'
import { websocket } from '@/core/websocket'
import { memoryService } from '../services/memoryService'
import type {
  DocumentType,
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
const mobileDocumentOpen = ref(false)
const mobileDocumentId = ref<string | null>(null)
const mobileDocumentAgentId = ref<number | null>(null)
const createDocumentOpen = ref(false)
const creatingDocument = ref(false)
const createDocumentOwner = ref('')
const createDocumentActorAgentId = ref<number | null>(null)
const createDocumentTitle = ref('')
const createDocumentType = ref<DocumentType>('html')
const documentTypeOptions = computed(() => ['html', 'dataset'].map(value => ({ value, label: t(`documents.types.${value}`) })))
const createOwnerOptions = ref<DocumentOwnerOptions>({ agents: [], users: [] })
const filteredCreateOwnerOptions = ref<CreateOwnerSelectOption[]>([])
const createOwnerOptionsLoading = ref(false)
let pageMounted = false
let leavingPage = false
let disposed = false
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
async function selectDocument(id: string, agentId: number | null): Promise<void> {
  if (id !== selectedDocumentId.value && documentEditor.value) {
    const saved = await documentEditor.value.flush()
    if (!saved) {
      $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
  }
  if (disposed || leavingPage) return
  selectedAgentId.value = agentId
  selectedNodeKey.value = `document:${agentId ?? 'user'}:${id}`
}
function openMobileDocument(id: string, agentId: number | null): void {
  mobileDocumentId.value = id
  mobileDocumentAgentId.value = agentId
  mobileDocumentOpen.value = true
}
async function loadDocuments(): Promise<void> { await navigation.value?.reload() }
function onLibraryLoaded(loaded: DocumentLibraryEntry[]): void {
  entries.value = loaded
  if (!selectedDocumentId.value && !documentIdFromRouteQuery(route.query.document_id) && !$q.screen.lt.md && loaded[0]) void selectEntry(loaded[0])
}
async function selectEntry(entry: DocumentLibraryEntry): Promise<void> {
  const actor = preferredAgent(entry)
  if ($q.screen.lt.md) openMobileDocument(entry.item.id, actor)
  else await selectDocument(entry.item.id, actor)
}
async function openCreateDocument(): Promise<void> {
  createDocumentActorAgentId.value = selectedAgentId.value ?? agentStore.sortedAgents[0]?.id ?? null
  createDocumentTitle.value = ''
  createDocumentType.value = 'html'
  createDocumentOwner.value = ''
  createOwnerOptions.value = { agents: [], users: [] }
  filteredCreateOwnerOptions.value = []
  createDocumentOpen.value = true
  createOwnerOptionsLoading.value = true
  try {
    createOwnerOptions.value = await memoryService.listDocumentOwnerOptions()
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
  if (!owner || actorAgentId === null || !title || creatingDocument.value) return
  creatingDocument.value = true
  try {
    const document = await memoryService.createDocument({
      document_type: createDocumentType.value,
      owner_kind: owner.kind,
      owner_id: owner.id,
      actor_agent_id: actorAgentId,
      title,
      folder: '',
    })
    createDocumentOpen.value = false
    navigation.value?.refreshDocuments([document.id])
    const documentActor = owner.kind === 'user' ? null : actorAgentId
    if ($q.screen.lt.md) openMobileDocument(document.id, documentActor)
    else await selectDocument(document.id, documentActor)
    $q.notify({ type: 'positive', message: t('documents.created') })
  } catch {
    $q.notify({ type: 'negative', message: t('documents.createError') })
  } finally {
    creatingDocument.value = false
  }
}
function onDocumentUpdated(document: MemoryItemDetail): void {
  entries.value = entries.value.map(entry => entry.item.id === document.id ? { ...entry, item: document } : entry)
  navigation.value?.refreshDocuments([document.id])
}
function onDocumentUnavailable(): void { void loadDocuments() }
function onMobileDocumentUnavailable(): void {
  mobileDocumentOpen.value = false
  void loadDocuments()
}
async function openRouteDocument(id: string): Promise<void> {
  const entry = entries.value.find(value => value.item.id === id)
  const agentId = entry ? preferredAgent(entry) : null
  if (agentId !== null || entry?.user_access?.can_read) {
    if ($q.screen.lt.md) openMobileDocument(id, agentId)
    else await selectDocument(id, agentId)
    return
  }
  try {
    const detail = await memoryService.getManagedDocument(id)
    if ($q.screen.lt.md) openMobileDocument(id, detail.agent_id)
    else await selectDocument(id, detail.agent_id)
  } catch { $q.notify({ type: 'negative', message: t('documents.loadError') }) }
}

function flushMobileDocumentEditor(): void {
  void mobileDocumentEditor.value?.flush()
}
function clearMobileDocument(): void {
  mobileDocumentId.value = null
  mobileDocumentAgentId.value = null
}

function realtimeRefresh(response: MemoryRealtimeEvent): void {
  if (response.data.node_kind !== 'document') return
  navigation.value?.refreshDocuments([response.data.id])
}

watch(() => $q.screen.lt.md, mobile => {
  if (!mobile) mobileDocumentOpen.value = false
})
watch(createDocumentOwner, value => {
  const owner = createOwnerChoices.value.find(option => option.value === value)
  if (owner?.kind === 'agent') createDocumentActorAgentId.value = owner.id
})
watch(selectedNodeKey, value => {
  if (disposed || leavingPage) return
  const parts = value?.split(':') ?? []
  if (parts[0] !== 'document' || parts.length < 3) return
  const agentId = parts[1] === 'user' ? null : Number(parts[1])
  const id = parts.slice(2).join(':')
  if (agentId !== null && (!Number.isInteger(agentId) || agentId <= 0)) return
  selectedAgentId.value = agentId
  if (documentIdFromRouteQuery(route.query.document_id) !== id) void router.replace(documentResourceHref(id))
})
watch(() => route.query.document_id, value => {
  const id = documentIdFromRouteQuery(value)
  if (pageMounted && id && id !== selectedDocumentId.value) void openRouteDocument(id)
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
  websocket.onEvent('memory', 'delete', realtimeRefresh)
})
onBeforeUnmount(() => {
  disposed = true
  pageMounted = false
  removeNavigationObserver()
  websocket.offEvent('memory', 'create', realtimeRefresh)
  websocket.offEvent('memory', 'update', realtimeRefresh)
  websocket.offEvent('memory', 'delete', realtimeRefresh)
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
