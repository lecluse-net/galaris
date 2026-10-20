<template>
  <div class="document-editor">
    <div v-if="loading" class="document-editor-state">
      <q-spinner color="primary" size="36px" />
    </div>
    <div v-else-if="!currentDocument" class="document-editor-state document-editor-error" :class="{ 'document-editor-error--dark': $q.dark.isActive }" role="alert">
      <q-icon name="warning" size="36px" />
      <span>{{ t('documents.loadError') }}</span>
      <q-btn flat :label="t('documents.retry')" @click="loadDocument" />
    </div>
    <template v-else>
      <q-banner v-if="refreshError" role="alert">
        {{ t('documents.loadError') }}
        <q-btn flat :label="t('documents.retry')" @click="onWebsocketConnect" />
      </q-banner>
      <q-toolbar class="document-editor-toolbar">
        <DocumentIcon class="document-editor-heading-icon" :document-id="currentDocument.id" :title="editorTitle || currentDocument.title" size="64px" plain />
        <q-toolbar-title>
          <div class="row items-center no-wrap">
            <q-input
              ref="titleInput"
              v-model="editorTitle"
              class="document-editor-title col"
              input-class="text-h6"
              :input-style="{ lineHeight: '1.4' }"
              type="textarea"
              autogrow
              :rows="1"
              outlined
              dense
              hide-bottom-space
              :aria-label="t('documents.title')"
              :readonly="historyOpen || !canEditDocument || isGoalDocument(currentDocument)"
              :rules="[requiredRule]"
            />
          </div>
          <div class="document-editor-details row items-center text-caption text-grey-7">
            <div class="document-editor-reference row items-center no-wrap">
              <q-badge
                outline
                color="primary"
                class="document-editor-uri-badge document-editor-detail-control cursor-pointer"
                role="button"
                tabindex="0"
                :aria-label="t('documents.copyUrl')"
                @click="copyDocumentUri"
                @keyup.enter="copyDocumentUri"
                @keyup.space.prevent="copyDocumentUri"
              >
                <q-icon name="link" size="13px" class="q-mr-xs" />
                <span class="ellipsis">{{ documentUri }}</span>
                <q-tooltip>{{ t('documents.copyUrl') }}</q-tooltip>
              </q-badge>
              <q-btn
                flat
                dense
                no-caps
                icon="history"
                :color="historyOpen ? 'primary' : 'grey-7'"
                class="document-editor-revision-button document-editor-detail-control"
                :label="t('documents.revision', { revision: currentDocument.revision })"
                :aria-label="t('documents.historyOpen')"
                @click="openDocumentHistory"
              >
                <q-tooltip>{{ t('documents.historyOpen') }}</q-tooltip>
              </q-btn>
            </div>
            <q-btn
              v-if="canDeleteDocument"
              dense
              no-caps
              size="12px"
              padding="0 6px"
              color="negative"
              icon="delete_outline"
              class="document-editor-detail-control q-ml-auto"
              :loading="deletingDocument"
              :label="t('documents.deleteDocument')"
              @click="deleteDialogOpen = true"
            />
            <q-chip
              v-if="currentDocument.deletion_protected"
              dense
              color="purple-1"
              text-color="purple-10"
              icon="lock"
            >
              {{ t('memory.protected') }}
            </q-chip>
          </div>
        </q-toolbar-title>
        <div class="document-editor-live-status column items-center no-wrap q-gutter-y-xs">
          <div class="row items-center" :class="realtimeStatusClass" role="status" tabindex="0"
            :aria-label="t(realtimeConnected ? 'documents.realtimeActive' : 'documents.realtimeConnecting')">
            <q-icon :name="realtimeConnected ? 'wifi' : 'wifi_off'" size="16px" />
            <q-tooltip>{{ t(realtimeConnected ? 'documents.realtimeActive' : 'documents.realtimeConnecting') }}</q-tooltip>
          </div>
          <div class="row items-center" :class="autosaveStatus.colorClass" role="status" tabindex="0"
            :aria-label="t(autosaveStatus.labelKey)">
            <q-spinner v-if="autosaveState === 'saving'" size="16px" />
            <q-icon v-else :name="autosaveStatus.icon" size="16px" />
            <q-tooltip>{{ t(autosaveStatus.labelKey) }}</q-tooltip>
          </div>
        </div>
      </q-toolbar>
      <q-banner v-if="conflictDocument" class="bg-warning text-dark">
        {{ t("richEditor.conflict") }}
        <template #action>
          <q-btn flat :label="t('richEditor.keepDraft')" @click="resolveConflict(true)" />
          <q-btn flat :label="t('richEditor.useRemote')" @click="resolveConflict(false)" />
        </template>
      </q-banner>
      <q-separator />

      <q-card-section
        v-if="!historyOpen"
        class="row q-col-gutter-xs document-editor-fields q-pa-xs"
      >
        <div class="document-editor-owner-cell">
          <OwnerSelect v-model="editorOwner" class="document-editor-owner-field"
            :options="ownerChoices" :current="selectedOwnerChoice"
            :readonly="!canManageOwner || isGoalDocument(currentDocument)" @open="loadOwnerOptions">
          </OwnerSelect>
        </div>
        <div class="document-editor-sharing-cell">
          <MemorySharingPanel :item-id="documentId" resource-kind="document" :editable="canManageSharing" :lock-version="currentDocument?.lock_version" @permission="sharingPermission = $event" @changed="onSharingChanged" />
        </div>
        <div class="col-12 document-editor-metadata-cell">
          <q-select
            v-model="editorKeywords"
            class="document-editor-metadata-field document-editor-keywords-field"
            outlined
            dense
            stack-label
            hide-bottom-space
            multiple
            use-input
            use-chips
            input-debounce="0"
            :options="filteredKeywordOptions"
            :max-values="50"
            :readonly="!canEditDocument"
            :label="t('documents.keywords')"
            @filter="filterKeywordOptions"
            @new-value="addKeyword"
          >
            <template #no-option>
              <q-item><q-item-section class="text-grey-7">{{ t('documents.keywordsEmpty') }}</q-item-section></q-item>
            </template>
          </q-select>
        </div>
        <div class="col-12">
          <q-banner v-if="currentDocument.content_type !== 'text'" dense>{{ t('memory.binaryContent') }}</q-banner>
          <q-input v-else-if="!currentDocument.media_type.startsWith('text/')"
            :model-value="editorContent" type="textarea" outlined readonly autogrow :label="t('documents.content')" />
          <RichTextEditor
            v-else-if="currentDocument.content_type === 'text' && currentDocument.media_type.startsWith('text/')"
            ref="richEditor"
            :key="documentId + ':' + agentId"
            v-model="editorContent"
            :attachments="documentResources"
            :resource-agent-id="requestAgentId"
            :pick-resources="isGoalDocument(currentDocument) ? undefined : pickInternalResources"
            :create-link-card="createLinkCard"
            :upload-file="uploadDocumentFile"
            :export-bundle="exportCurrentBundle"
            @open-attachment="openAttachment"
            :media-type="currentDocument.media_type"
            :profile="currentDocument.content_profile ?? (isGoalDocument(currentDocument) ? 'rich-text' : 'document')"
            :upload-image="isGoalDocument(currentDocument) ? undefined : uploadInlineImage"
            :import-image="isGoalDocument(currentDocument) ? undefined : importPastedImage"
            :resolve-image="resolveInlineImage"
            :document-title="editorTitle"
            :document-url="documentShareUrl"
            :export-pdf="exportCurrentDocumentPdf"
            auto-grow
            :aria-label="t('documents.content')"
            :readonly="!canEditDocument"
            :min-height="contentMinHeight"
            :max-height="contentMaxHeight"
          >
            <template #embedded-code="{ source, language, registerSnapshot }">
              <DocumentApplicationBlock :source="source" :language="language" :register-snapshot="registerSnapshot" :resolve-media="resolveInlineImage" :document-id="currentDocument.id" :revision="currentDocument.revision" :ready="!hasUnsavedChanges && !conflictDocument && (autosaveState === 'saved' || !canEditDocument)" />
            </template>
          </RichTextEditor>
        </div>
        <div class="col-12 document-editor-attachments">
          <DocumentAttachments
            @insert="insertAttachment"
            allow-insertion
            ref="attachmentPanel"
            :content="editorContent"
            :document-id="currentDocument.id"
            :agent-id="requestAgentId"
            :attachments="attachments"
            :editable="canEditDocument && !isGoalDocument(currentDocument)"
            :loading="attachmentsLoading"
            @added="onAttachmentAdded"
            @removed="onAttachmentRemoved"
            @renamed="onAttachmentRenamed"
          />
          <DocumentResourceReferences v-if="canEditDocument && !isGoalDocument(currentDocument)" :key="currentDocument.id + ':' + agentId"
            v-model:picker-open="internalPickerOpen" @picked="finishInternalPick"
            :document-id="currentDocument.id" :agent-id="requestAgentId" :editable="canEditDocument" />
        </div>
      </q-card-section>
      <DocumentHistoryDialog
        v-else
        :document-id="currentDocument.id"
        :current-revision="currentDocument.revision"
        :agent-id="requestAgentId"
        :can-restore="canEditDocument"
        :min-height="contentMinHeight"
        :max-height="contentMaxHeight"
        @close="closeDocumentHistory"
        @restored="onHistoryRestored"
      />
    </template>
    <q-dialog v-model="deleteDialogOpen">
      <q-card class="galaris-dialog-card" style="width: 440px; max-width: 90vw">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('documents.deleteDocument') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section class="galaris-dialog-body">{{ t('documents.deleteConfirm', { title: editorTitle || currentDocument?.title }) }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="negative" :label="t('documents.deleteDocument')" :loading="deletingDocument" :disable="!canDeleteDocument" @click="deleteDocument" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import DocumentApplicationBlock from './DocumentApplicationBlock.vue'
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { isAxiosError } from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar, type QInput } from 'quasar'
import type { DocumentRowAction } from '../libraryShortcuts'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { RichTextEditor, richLinkHref, documentResourceHtml, documentResourceHref } from '@/core/util'
import { websocket } from '@/core/websocket'
import { useAgentStore } from '@/app/agent'
import { OwnerSelect, type OwnerOption } from '@/app/share'
import { DatasetDocumentRedirect, memoryService } from '../services/memoryService'
import { useDocumentMutations } from '../stores/documentMutations'
import { reconcileLibrarySnapshot } from '../librarySnapshot'
import type {
  DocumentAttachment,
  DocumentGlobalAccess,
  DocumentOwnerKind,
  DocumentOwnerOption,
  DocumentOwnerOptions,
  MemoryItem,
  MemoryItemDetail,
  MemoryItemUpdate,
  MemoryNodeKind,
} from '../types'
import MemorySharingPanel from './MemorySharingPanel.vue'
import DocumentAttachments from './DocumentAttachments.vue'
import { DocumentResourceReferences, richLinkTarget, richLinkCard, useReferenceFormatting } from '@/core/util'
import DocumentHistoryDialog from './DocumentHistoryDialog.vue'

type DocumentShareAccess = 'none' | 'read' | 'edit'
type AutosaveState = 'saved' | 'pending' | 'saving' | 'invalid' | 'error'

interface DocumentDraft {
  owner: string
  title: string
  content: string
  keywords: string[]
  globalAccess: DocumentGlobalAccess
  sharing: Record<number, DocumentShareAccess>
}

type OwnerChoice = OwnerOption & { value: string }

interface MemoryRealtimeEvent {
  data: {
    id: string
    owner_agent_id: number | null
    owner_user_id: number | null
    node_kind: MemoryNodeKind
    revision: number
    lock_version?: number
  }
}

type NewKeywordDone = (value?: string, mode?: 'add' | 'add-unique' | 'toggle') => void

const props = withDefaults(defineProps<{
  documentId: string
  agentId: number | null
  initialDocument?: MemoryItemDetail | null
  editable?: boolean
  contentMinHeight?: string
  contentMaxHeight?: string
}>(), {
  editable: true,
  contentMinHeight: '520px',
})

const emit = defineEmits<{
  loaded: [document: MemoryItemDetail]
  updated: [document: MemoryItemDetail]
  unavailable: [documentId: string]
  deleted: [documentId: string]
}>()

const { t, locale } = useI18n()
const referenceFormatting = useReferenceFormatting()
const $q = useQuasar()
const agentStore = useAgentStore()
const documentMutations = useDocumentMutations()
const privilegeStore = usePrivilegeStore()
const loading = ref(true)
const titleInput = useTemplateRef<QInput>('titleInput')
const requestedRowAction = ref<DocumentRowAction | null>(null)
const ownerOptionsReady = ref(false)
const deleteDialogOpen = ref(false)
const deletingDocument = ref(false)
const refreshing = ref(false)
const refreshError = ref(false)
const currentDocument = ref<MemoryItemDetail | null>(null)
const autosaveState = ref<AutosaveState>('saved')
const editorTitle = ref('')
const editorOwner = ref('')
const editorContent = ref('')
const editorKeywords = ref<string[]>([])
const keywordOptions = ref<string[]>([])
const filteredKeywordOptions = ref<string[]>([])
const ownerOptions = ref<DocumentOwnerOptions>({ agents: [], users: [] })
const attachments = ref<DocumentAttachment[]>([])
const route = useRoute(), router = useRouter()
const richEditor = ref<InstanceType<typeof RichTextEditor>>()
function insertAttachment(attachment: DocumentAttachment): void {
  richEditor.value?.insertResource(documentResourceHtml({ uri: 'document://' + props.documentId + '/attachments/' + attachment.id, name: attachment.name, size: attachment.size_bytes, mediaType: attachment.media_type }))
}
const attachmentPanel = ref<InstanceType<typeof DocumentAttachments>>()
const internalPickerOpen = ref(false)
let resolveInternalPick: ((html: string) => void) | undefined
function finishInternalPick(html: string): void { resolveInternalPick?.(html); resolveInternalPick = undefined }
function pickInternalResources(): Promise<string> {
  finishInternalPick(''); internalPickerOpen.value = true
  return new Promise(resolve => { resolveInternalPick = resolve })
}
onBeforeUnmount(() => finishInternalPick(''))
watch(() => [props.documentId, props.agentId], () => { internalPickerOpen.value = false; finishInternalPick('') })
const documentResources = computed(() => attachments.value.map(value => ({ uri: 'document://' + props.documentId + '/attachments/' + value.id, name: value.name, size: value.size_bytes, mediaType: value.media_type })))
async function openAttachment(documentId: string, attachmentId: string): Promise<void> {
  if (documentId === props.documentId) await attachmentPanel.value?.openById(attachmentId)
  else { const href = richLinkHref('document://' + documentId + '/attachments/' + attachmentId); if (href) await router.push(href) }
}
watch(() => [route.query.attachment_id, attachmentPanel.value, attachments.value] as const, ([id]) => {
  if (typeof id === 'string' && route.query.document_id === props.documentId) void openAttachment(props.documentId, id)
}, { flush: 'post' })
async function createLinkCard(url: string): Promise<string> {
  const documentId = props.documentId
  if (richLinkTarget(url)) {
    const html = await richLinkCard(url, requestAgentId.value, referenceFormatting())
    if (props.documentId !== documentId) throw new Error('Document changed')
    return html
  }
  const result = await memoryService.createDocumentLinkCard(documentId, requestAgentId.value, url)
  if (props.documentId !== documentId) throw new Error('Document changed')
  if (result.attachment) onAttachmentAdded(result.attachment)
  return result.html
}
async function uploadDocumentFile(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const documentId = props.documentId
  const attachment = await memoryService.addDocumentAttachment(documentId, requestAgentId.value, file, signal, progress)
  if (props.documentId !== documentId) throw new Error('Document changed')
  onAttachmentAdded(attachment)
  return 'document://' + documentId + '/attachments/' + attachment.id
}
async function importPastedImage(url: string, signal: AbortSignal): Promise<string> {
  const documentId = props.documentId, agentId = requestAgentId.value
  const attachment = await memoryService.importDocumentImage(documentId, agentId, url, signal)
  if (signal.aborted || props.documentId !== documentId || requestAgentId.value !== agentId) throw new Error('Document changed')
  onAttachmentAdded(attachment)
  return 'document://' + documentId + '/attachments/' + attachment.id
}
async function exportCurrentBundle(html: string, signal: AbortSignal): Promise<Blob> {
  return memoryService.exportDocumentBundle(props.documentId, requestAgentId.value, html, signal)
}
const attachmentsLoading = ref(false)
const historyOpen = ref(false)
const editorGlobalAccess = ref<DocumentGlobalAccess>(0)
const sharingAccessByAgentId = ref<Record<number, DocumentShareAccess>>({})
const lastSavedDraft = ref<DocumentDraft | null>(null)
const realtimeConnected = computed(() => websocket.isConnected.value && !loading.value && !refreshing.value)
let applyingDocument = false
let saveInFlight = false
let saveQueued = false
let saveWaiters: Array<() => void> = []
let autosaveTimer: ReturnType<typeof setTimeout> | undefined
let realtimeTimer: ReturnType<typeof setTimeout> | undefined
let pendingExternalRevision = 0
let pendingExternalLockVersion = 0
let loadGeneration = 0
let ownerLoadGeneration = 0
let keywordLoadGeneration = 0
let disposed = false
let initialDocument = props.initialDocument

const agentOptions = computed(() => agentStore.sortedAgents.map(agent => ({
  value: agent.id,
  label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
})))
const ownerChoices = computed<OwnerChoice[]>(() => choicesFromOwnerOptions(ownerOptions.value))
const selectedOwnerChoice = computed(() => (
  ownerChoices.value.find(option => option.value === editorOwner.value)
  ?? fallbackOwnerChoice(currentDocument.value)
))
const sharingAgentOptions = computed(() => ownerOptions.value.agents.flatMap(option => (
  option.id === currentDocument.value?.owner_agent_id
    ? []
    : [{ value: option.id, label: option.label }]
)))
const selectedAgentOwnsDocument = computed(() => (
  props.agentId !== null && currentDocument.value?.owner_agent_id === props.agentId
))
const currentUserOwnsDocument = computed(() => Boolean(
  currentDocument.value?.owner_user_id !== null
  && ownerOptions.value.users.some(option => (
    option.is_current_user
    && option.id === currentDocument.value?.owner_user_id
  )),
))
// An open editor can outlive its original Agent's grant after an ownership transfer.
const requestAgentId = computed(() => currentUserOwnsDocument.value ? null : props.agentId)
const canEditDocument = computed(() => Boolean(
  props.editable
  && currentDocument.value?.access.can_write
  && !currentDocument.value.read_only
  && !currentDocument.value.source_managed
  && privilegeStore.hasPrivilege(privileges.MEMORY_EDIT),
))
const sharingPermission = ref<boolean | null>(null)
watch(() => props.documentId, () => { sharingPermission.value = null })
const canManageSharing = computed(() => Boolean(
  props.editable
  && currentDocument.value
  && !currentDocument.value.source_managed
  && (
    privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN)
    || (
      (sharingPermission.value ?? (selectedAgentOwnsDocument.value || currentUserOwnsDocument.value))
      && privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)
    )
  ),
))
const canManageOwner = computed(() => canEditDocument.value && canManageSharing.value)
const canDeleteDocument = computed(() => Boolean(
  props.editable
  && currentDocument.value
  && !currentDocument.value.deletion_protected
  && !currentDocument.value.source_managed
  && privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)
  && (requestAgentId.value === null ? currentUserOwnsDocument.value : selectedAgentOwnsDocument.value),
))
watch([() => props.documentId, () => props.agentId, canDeleteDocument], () => {
  deleteDialogOpen.value = false
})
const canSaveDocument = computed(() => canEditDocument.value || canManageSharing.value)
const realtimeStatusClass = computed(() => realtimeConnected.value ? 'text-positive' : 'text-grey-7')
const autosaveStatus = computed(() => {
  if (!canSaveDocument.value) {
    return { labelKey: 'documents.autosaveReadOnly', icon: 'lock', colorClass: 'text-grey-7' }
  }
  return {
    saved: { labelKey: 'documents.autosaveSaved', icon: 'cloud_done', colorClass: 'text-positive' },
    pending: { labelKey: 'documents.autosavePending', icon: 'schedule', colorClass: 'text-grey-7' },
    saving: { labelKey: 'documents.autosaveSaving', icon: 'cloud_upload', colorClass: 'text-primary' },
    invalid: { labelKey: 'documents.autosaveInvalid', icon: 'warning', colorClass: 'text-warning' },
    error: { labelKey: 'documents.autosaveError', icon: 'cloud_off', colorClass: 'text-negative' },
  }[autosaveState.value]
})
const documentUri = computed(() => `document://${props.documentId}`)
const documentShareUrl = computed(() => new URL(documentResourceHref(props.documentId), window.location.href).href)

function ownerValue(kind: DocumentOwnerKind, id: number): string {
  return `${kind}:${id}`
}

function ownerOptionToChoice(option: DocumentOwnerOption): OwnerChoice {
  return { ...option, value: ownerValue(option.kind, option.id) }
}

function choicesFromOwnerOptions(options: DocumentOwnerOptions): OwnerChoice[] {
  return [
    ...options.agents.map(ownerOptionToChoice),
    ...options.users.map(ownerOptionToChoice),
  ]
}

function fallbackOwnerChoice(document: MemoryItem | null): OwnerChoice | null {
  if (!document) return null
  const value = document.owner_agent_id !== null
    ? ownerValue('agent', document.owner_agent_id)
    : document.owner_user_id !== null
      ? ownerValue('user', document.owner_user_id)
      : ''
  const known = ownerChoices.value.find(option => option.value === value)
  if (known) return known
  if (document.owner_agent_id !== null) {
    return {
      value,
      label: agentLabel(document.owner_agent_id),
      subtitle: '',
      kind: 'agent',
      id: document.owner_agent_id,
      avatar_url: null,
    }
  }
  if (document.owner_user_id !== null) {
    return {
      value,
      label: t('documents.ownerUser'),
      subtitle: '',
      kind: 'user',
      id: document.owner_user_id,
      avatar_url: null,
    }
  }
  return null
}

const requiredRule = (value: unknown): true | string => Boolean(String(value ?? '').trim()) || t('documents.required')
function isGoalDocument(document: MemoryItem): boolean {
  return document.metadata.goal_document_kind === 'description'
    || document.metadata.goal_document_kind === 'tracking'
}

function agentLabel(agentId: number | null): string {
  if (agentId === null) return '—'
  return agentOptions.value.find(option => option.value === agentId)?.label ?? `#${agentId}`
}

function normalizedKeywords(values: string[]): string[] {
  return [...new Set(values.map(value => value.trim().slice(0, 100)).filter(Boolean))].slice(0, 50)
}

function documentSharing(document: MemoryItemDetail): Record<number, DocumentShareAccess> {
  // The saved draft must not depend on whether the owner catalogue has arrived.
  return Object.fromEntries(document.grants.map(grant => [grant.agent_id, grant.can_write ? 'edit' : 'read']))
}

function draftFromDocument(document: MemoryItemDetail): DocumentDraft {
  const owner = document.owner_agent_id !== null
    ? ownerValue('agent', document.owner_agent_id)
    : document.owner_user_id !== null
      ? ownerValue('user', document.owner_user_id)
      : ''
  return {
    owner,
    title: document.title.trim(),
    content: document.payload.text ?? '',
    keywords: normalizedKeywords(document.keywords),
    globalAccess: document.global_access,
    sharing: documentSharing(document),
  }
}

function draftFromEditor(): DocumentDraft {
  return {
    owner: editorOwner.value,
    title: editorTitle.value.trim(),
    content: editorContent.value,
    keywords: normalizedKeywords(editorKeywords.value),
    globalAccess: editorGlobalAccess.value,
    sharing: Object.fromEntries(Object.entries(sharingAccessByAgentId.value).filter(([, access]) => access !== 'none')),
  }
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function sameDraft(left: DocumentDraft | null, right: DocumentDraft | null): boolean {
  return left !== null && right !== null && sameValue(left, right)
}

const hasUnsavedChanges = computed(() => currentDocument.value !== null && !sameDraft(lastSavedDraft.value, draftFromEditor()))

function cloneDraft(draft: DocumentDraft): DocumentDraft {
  return { ...draft, keywords: [...draft.keywords],
    sharing: Object.fromEntries(Object.entries(draft.sharing).filter(([, access]) => access !== 'none')) }
}

function applyEditorDraft(draft: DocumentDraft): void {
  editorOwner.value = draft.owner
  editorTitle.value = draft.title
  editorContent.value = draft.content
  editorKeywords.value = [...draft.keywords]
  editorGlobalAccess.value = draft.globalAccess
  sharingAccessByAgentId.value = { ...draft.sharing }
}

function applyDocument(document: MemoryItemDetail, event: 'loaded' | 'updated'): void {
  if (currentDocument.value?.id !== document.id) conflictDocument.value = null
  applyingDocument = true
  currentDocument.value = document
  const draft = draftFromDocument(document)
  applyEditorDraft(draft)
  lastSavedDraft.value = draft
  autosaveState.value = 'saved'
  if (event === 'loaded' && props.editable) restoreDraft(document)
  if (event !== 'loaded') { pendingExternalRevision = 0; pendingExternalLockVersion = 0 }
  applyingDocument = false
  keywordOptions.value = [...new Set([...keywordOptions.value, ...document.keywords])]
    .sort((left, right) => left.localeCompare(right, locale.value, { sensitivity: 'base' }))
  filteredKeywordOptions.value = keywordOptions.value
  if (event === 'updated') emit('updated', document)
  else emit('loaded', document)
}

function applyPublicDocument(document: MemoryItem): void {
  const current = currentDocument.value
  if (current?.id !== document.id) return
  const merged: MemoryItemDetail = {
    ...current,
    ...document,
    payload: current.payload,
    source_refs: current.source_refs,
  }
  currentDocument.value = merged
  emit('updated', merged)
}

async function loadKeywords(): Promise<void> {
  const generation = ++keywordLoadGeneration
  try {
    const incoming = await memoryService.listDocumentKeywords(requestAgentId.value)
    if (disposed || generation !== keywordLoadGeneration) return
    keywordOptions.value = [...new Set([...incoming, ...(currentDocument.value?.keywords ?? [])])]
    filteredKeywordOptions.value = keywordOptions.value
  } catch {
    if (disposed || generation !== keywordLoadGeneration) return
    keywordOptions.value = [...(currentDocument.value?.keywords ?? [])]
    filteredKeywordOptions.value = keywordOptions.value
  }
}

async function onSharingChanged(): Promise<void> {
  pendingExternalRevision = Math.max(pendingExternalRevision, currentDocument.value?.revision ?? 0)
  await refreshFromRealtime()
}

async function loadAttachments(): Promise<void> {
  const generation = loadGeneration
  attachmentsLoading.value = attachments.value.length === 0
  try {
    const incoming = await memoryService.listDocumentAttachments(props.documentId, requestAgentId.value)
    if (generation === loadGeneration) attachments.value = reconcileLibrarySnapshot(attachments.value, incoming, attachment => attachment.id)
  } catch {
    // A temporary failure must not remove already displayed attachments.
  } finally {
    if (generation === loadGeneration) attachmentsLoading.value = false
  }
}

async function copyDocumentUri(): Promise<void> {
  try {
    await copyToClipboard(documentUri.value)
    $q.notify({ type: 'positive', icon: 'content_copy', message: t('documents.urlCopied'), timeout: 1600 })
  } catch {
    $q.notify({ type: 'negative', icon: 'error', message: t('documents.urlCopyError') })
  }
}

function onAttachmentAdded(attachment: DocumentAttachment): void {
  attachments.value = [...attachments.value, attachment]
}

function onAttachmentRemoved(attachmentId: string): void {
  attachments.value = attachments.value.filter(value => value.id !== attachmentId)
}

function onAttachmentRenamed(attachment: DocumentAttachment): void {
  attachments.value = attachments.value.map(value => value.id === attachment.id ? attachment : value)
}

function filterKeywordOptions(value: string, update: (callback: () => void) => void): void {
  update(() => {
    const needle = value.trim().toLocaleLowerCase(locale.value)
    filteredKeywordOptions.value = needle
      ? keywordOptions.value.filter(option => option.toLocaleLowerCase(locale.value).includes(needle))
      : keywordOptions.value
  })
}

function addKeyword(value: string, done: NewKeywordDone): void {
  const normalized = value.trim().slice(0, 100)
  done(normalized || undefined, normalized ? 'add-unique' : undefined)
}

async function openDocumentHistory(): Promise<void> {
  if (hasUnsavedChanges.value) await persistAutosave()
  historyOpen.value = true
}

function closeDocumentHistory(): void {
  historyOpen.value = false
}

async function onHistoryRestored(): Promise<void> {
  historyOpen.value = false
  await loadDocument()
}

async function loadDocument(): Promise<void> {
  const generation = ++loadGeneration
  loading.value = !currentDocument.value
  refreshError.value = false
  try {
    const seed = initialDocument
    initialDocument = null
    const document = seed?.id === props.documentId ? seed : await memoryService.getDocument(props.documentId, requestAgentId.value)
    if (generation !== loadGeneration) return
    if (document.document_type === 'dataset') throw new DatasetDocumentRedirect(`data://${document.id}`)
    if (document.document_type !== 'html') throw new Error('This resource is not an HTML Document.')
    if (document.node_kind !== 'document') throw new Error('The resource is not a document.')
    applyDocument(document, 'loaded')
    // Ancillary catalogues must not keep the current document behind a loading screen.
    loading.value = false
    void Promise.all([loadOwnerOptions(), loadKeywords(), loadAttachments()])
  } catch (error) {
    if (generation !== loadGeneration) return
    if (error instanceof DatasetDocumentRedirect) { await router.replace(error.href); return }
    handleRefreshError(error)
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function loadOwnerOptions(): Promise<void> {
  const generation = ++ownerLoadGeneration
  try {
    const incoming = await memoryService.listDocumentOwnerOptions()
    if (disposed || generation !== ownerLoadGeneration) return
    ownerOptions.value = incoming
  } catch {
    if (disposed || generation !== ownerLoadGeneration) return
    ownerOptions.value = {
      agents: [],
      users: [],
    }
  } finally {
    if (!disposed && generation === ownerLoadGeneration) ownerOptionsReady.value = true
  }
}

function propertyUpdate(document: MemoryItemDetail, base: DocumentDraft, draft: DocumentDraft): MemoryItemUpdate | null {
  const update: MemoryItemUpdate = {
    expected_revision: document.revision,
    expected_lock_version: document.lock_version,
  }
  let changed = false
  if (!isGoalDocument(document) && draft.title !== base.title) {
    update.title = draft.title
    changed = true
  }
  if (draft.content !== base.content) { update.payload = { text: draft.content }; changed = true }
  if (!sameValue(draft.keywords, base.keywords)) { update.keywords = [...draft.keywords]; changed = true }
  return changed ? update : null
}

async function persistSharingChange(
  document: MemoryItemDetail,
  targetAgentId: number,
  access: DocumentShareAccess,
): Promise<MemoryItem> {
  if (access === 'none') {
    return memoryService.removeManagedDocumentGrant(
      document.id,
      targetAgentId,
      currentDocument.value?.lock_version ?? document.lock_version,
    )
  }
  return memoryService.setManagedDocumentGrant(
    document.id,
    targetAgentId,
    access === 'edit',
    currentDocument.value?.lock_version ?? document.lock_version,
  )
}

function scheduleAutosave(delay = 700): void {
  if (deletingDocument.value) return
  if (conflictDocument.value) return
  if (applyingDocument || !canSaveDocument.value || !currentDocument.value) return
  if (!editorTitle.value.trim() || !editorOwner.value) {
    autosaveState.value = 'invalid'
    return
  }
  if (!hasUnsavedChanges.value) {
    autosaveState.value = 'saved'
    return
  }
  if (saveInFlight) {
    saveQueued = true
    return
  }
  autosaveState.value = 'pending'
  if (autosaveTimer) clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    autosaveTimer = undefined
    void persistAutosave()
  }, delay)
}

const conflictDocument = ref<MemoryItemDetail | null>(null)

function resolveConflict(keepDraft: boolean): void {
  const latest = conflictDocument.value
  if (!latest) return
  const draft = draftFromEditor()
  applyingDocument = true
  currentDocument.value = latest
  lastSavedDraft.value = draftFromDocument(latest)
  applyEditorDraft(keepDraft ? draft : lastSavedDraft.value)
  conflictDocument.value = null
  applyingDocument = false
  pendingExternalRevision = 0
  preserveDraft()
  scheduleAutosave(150)
}

async function mergeLatestDocument(documentId: string, generation = loadGeneration): Promise<void> {
  const latest = await memoryService.getDocument(documentId, requestAgentId.value)
  if (generation !== loadGeneration || currentDocument.value?.id !== documentId) return
  mergeDocument(latest)
}

function mergeDocument(latest: MemoryItemDetail): void {
  const previousBase = lastSavedDraft.value
  if (!previousBase) return
  // Include edits made while the request was pending.
  const local = draftFromEditor()
  const remote = draftFromDocument(latest)
  const overlapping = (Object.keys(local) as (keyof DocumentDraft)[]).some(key => !sameValue(local[key], previousBase[key]) && !sameValue(remote[key], previousBase[key]) && !sameValue(local[key], remote[key]))
  if (overlapping) {
    conflictDocument.value = latest
    autosaveState.value = "error"
    pendingExternalRevision = 0
    preserveDraft()
    return
  }
  const choose = <T>(localValue: T, previousValue: T, remoteValue: T): T => (
    sameValue(localValue, previousValue) ? remoteValue : localValue
  )
  const sharing: Record<number, DocumentShareAccess> = {}
  for (const key of new Set([...Object.keys(local.sharing), ...Object.keys(previousBase.sharing), ...Object.keys(remote.sharing)])) {
    const id = Number(key)
    const access = choose(
      local.sharing[id] ?? 'none',
      previousBase.sharing[id] ?? 'none',
      remote.sharing[id] ?? 'none',
    )
    if (access !== 'none') sharing[id] = access
  }
  const merged: DocumentDraft = {
    owner: choose(local.owner, previousBase.owner, remote.owner),
    title: choose(local.title, previousBase.title, remote.title),
    content: choose(local.content, previousBase.content, remote.content),
    keywords: choose(local.keywords, previousBase.keywords, remote.keywords),
    globalAccess: choose(
      local.globalAccess,
      previousBase.globalAccess,
      remote.globalAccess,
    ),
    sharing,
  }
  applyingDocument = true
  currentDocument.value = latest
  applyEditorDraft(merged)
  lastSavedDraft.value = remote
  applyingDocument = false
  pendingExternalRevision = 0
  autosaveState.value = sameDraft(merged, remote) ? 'saved' : 'pending'
  emit('updated', latest)
}

async function persistAutosave(): Promise<void> {
  if (deletingDocument.value) return
  if (conflictDocument.value) return
  if (pendingExternalRevision > 0) { await refreshFromRealtime(); return }
  const document = currentDocument.value
  const base = lastSavedDraft.value
  if (!document || !base || !canSaveDocument.value) return
  if (!editorTitle.value.trim() || !editorOwner.value) {
    autosaveState.value = 'invalid'
    return
  }
  if (saveInFlight) {
    saveQueued = true
    return
  }
  const draft = draftFromEditor()
  if (sameDraft(base, draft)) {
    autosaveState.value = 'saved'
    return
  }

  saveInFlight = true
  autosaveState.value = 'saving'
  let persisted = cloneDraft(base)
  try {
    const update = canEditDocument.value ? propertyUpdate(document, base, draft) : null
    if (update) {
      if (update.payload) update.media_type = 'text/html'
      const updated = await memoryService.updateDocument(document.id, requestAgentId.value, update)
      applyPublicDocument(updated)
      persisted = {
        ...cloneDraft(draft),
        globalAccess: base.globalAccess,
        sharing: { ...base.sharing },
      }
      lastSavedDraft.value = cloneDraft(persisted)
    }
    if (canManageSharing.value && persisted.globalAccess !== draft.globalAccess) {
      const revision = currentDocument.value?.revision ?? document.revision
      const updated = await memoryService.setDocumentGlobalAccess(
        document.id,
        revision,
        currentDocument.value?.lock_version ?? document.lock_version,
        draft.globalAccess,
      )
      applyPublicDocument(updated)
      persisted.globalAccess = draft.globalAccess
      lastSavedDraft.value = cloneDraft(persisted)
    }
    if (canManageSharing.value) {
      for (const agent of sharingAgentOptions.value) {
        const initial = persisted.sharing[agent.value] ?? 'none'
        const desired = draft.sharing[agent.value] ?? 'none'
        if (initial === desired) continue
        const updated = await persistSharingChange(document, agent.value, desired)
        applyPublicDocument(updated)
        persisted.sharing[agent.value] = desired
        lastSavedDraft.value = cloneDraft(persisted)
      }
    }
    if (
      canManageOwner.value
      && !isGoalDocument(document)
      && draft.owner !== base.owner
    ) {
      const [kind, rawId] = draft.owner.split(':')
      const ownerId = Number(rawId)
      if ((kind !== 'agent' && kind !== 'user') || !Number.isInteger(ownerId) || ownerId <= 0) {
        throw new Error('Invalid document owner selection.')
      }
      const revision = currentDocument.value?.revision ?? document.revision
      const updated = await memoryService.changeDocumentOwner(
        document.id,
        revision,
        currentDocument.value?.lock_version ?? document.lock_version,
        kind,
        ownerId,
      )
      applyPublicDocument(updated)
      const latest = await memoryService.getDocument(document.id, requestAgentId.value)
      if (currentDocument.value?.id === document.id) applyDocument(latest, 'updated')
      return
    }
    autosaveState.value = sameDraft(lastSavedDraft.value, draftFromEditor()) ? 'saved' : 'pending'
  } catch (caught) {
    const status = (caught as { response?: { status?: unknown } }).response?.status
    if (status === 409) {
      try {
        await mergeLatestDocument(document.id)
        saveQueued = true
      } catch {
        autosaveState.value = 'error'
      }
    } else {
      autosaveState.value = 'error'
    }
  } finally {
    saveInFlight = false
    preserveDraft()
    const waiters = saveWaiters
    saveWaiters = []
    for (const resolve of waiters) resolve()
    const mustRefreshExternal = pendingExternalRevision > (currentDocument.value?.revision ?? 0)
      || pendingExternalLockVersion > (currentDocument.value?.lock_version ?? 0)
    const mustSaveAgain = saveQueued || (autosaveState.value === 'pending' && hasUnsavedChanges.value)
    if (!mustRefreshExternal) { pendingExternalRevision = 0; pendingExternalLockVersion = 0 }
    saveQueued = false
    if (mustRefreshExternal) scheduleRealtimeRefresh()
    if (mustSaveAgain) scheduleAutosave(150)
  }
}

function waitForActiveSave(): Promise<void> {
  if (!saveInFlight) return Promise.resolve()
  return new Promise(resolve => saveWaiters.push(resolve))
}

async function flushAutosave(): Promise<boolean> {
  if (autosaveTimer) {
    clearTimeout(autosaveTimer)
    autosaveTimer = undefined
  }
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await waitForActiveSave()
    await persistAutosave()
    await waitForActiveSave()
    if (!hasUnsavedChanges.value) return true
    if (autosaveState.value === 'error' || autosaveState.value === 'invalid') return false
    if (autosaveTimer) {
      clearTimeout(autosaveTimer)
      autosaveTimer = undefined
    }
  }
  return !hasUnsavedChanges.value
}

async function deleteDocument(): Promise<void> {
  const document = currentDocument.value
  const agentId = requestAgentId.value
  const storageKey = draftKey()
  if (!document || !canDeleteDocument.value || deletingDocument.value) return
  const finishDeletion = documentMutations.beginDeletion(document.id)
  if (!finishDeletion) return
  deletingDocument.value = true
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (realtimeTimer) clearTimeout(realtimeTimer)
  try {
    await waitForActiveSave()
    if (disposed || currentDocument.value?.id !== document.id || requestAgentId.value !== agentId || !canDeleteDocument.value) return
    await memoryService.deleteDocument(document.id, agentId)
    try { sessionStorage.removeItem(storageKey) } catch { /* Storage may be unavailable. */ }
    if (disposed || currentDocument.value?.id !== document.id || requestAgentId.value !== agentId) return
    loadGeneration += 1
    currentDocument.value = null
    deleteDialogOpen.value = false
    $q.notify({ type: 'positive', message: t('documents.deleted') })
    emit('deleted', document.id)
    emit('unavailable', document.id)
  } catch {
    if (!disposed && currentDocument.value?.id === document.id) {
      $q.notify({ type: 'negative', message: t('documents.deleteError') })
    }
  } finally {
    finishDeletion()
    deletingDocument.value = false
    if (!disposed) scheduleAutosave()
  }
}

async function refreshFromRealtime(): Promise<void> {
  if (deletingDocument.value) return
  const document = currentDocument.value
  if (!document || saveInFlight) return
  if (pendingExternalRevision < document.revision && pendingExternalLockVersion <= document.lock_version) {
    pendingExternalRevision = 0
    pendingExternalLockVersion = 0
    return
  }
  const generation = ++loadGeneration
  loading.value = false
  refreshing.value = true
  refreshError.value = false
  try {
    if (hasUnsavedChanges.value) {
      await mergeLatestDocument(document.id, generation)
      if (generation === loadGeneration) scheduleAutosave(150)
    } else {
      const latest = await memoryService.getDocument(document.id, requestAgentId.value)
      if (generation === loadGeneration && currentDocument.value?.id === document.id) {
        // A clean editor may have acquired a draft during the read.
        if (hasUnsavedChanges.value) {
          mergeDocument(latest)
          scheduleAutosave(150)
        } else applyDocument(latest, 'updated')
        await loadAttachments()
      }
    }
  } catch (error) {
    if (generation !== loadGeneration) return
    handleRefreshError(error)
  } finally {
    if (generation === loadGeneration) refreshing.value = false
  }
}

function handleRefreshError(error: unknown): void {
  const status = isAxiosError(error) ? error.response?.status : undefined
  if (!currentDocument.value || status === 401 || status === 403 || status === 404) {
    preserveDraft()
    currentDocument.value = null
    emit('unavailable', props.documentId)
  } else refreshError.value = true
}

function scheduleRealtimeRefresh(): void {
  if (realtimeTimer) clearTimeout(realtimeTimer)
  realtimeTimer = setTimeout(() => {
    realtimeTimer = undefined
    void refreshFromRealtime()
  }, 200)
}

function onMemoryRealtime(response: MemoryRealtimeEvent): void {
  const event = response.data
  if (event.node_kind !== 'document' || event.id !== props.documentId) return
  if (event.revision <= 0) {
    onWebsocketConnect()
    return
  }
  if (currentDocument.value && event.revision < currentDocument.value.revision) return
  if (currentDocument.value && event.lock_version && event.lock_version <= currentDocument.value.lock_version
    && event.revision <= currentDocument.value.revision) return
  pendingExternalRevision = Math.max(pendingExternalRevision, event.revision)
  pendingExternalLockVersion = Math.max(pendingExternalLockVersion, event.lock_version ?? 0)
  if (!saveInFlight) { ++loadGeneration; scheduleRealtimeRefresh() }
}

function onMemoryDelete(response: MemoryRealtimeEvent): void {
  if (response.data.node_kind !== 'document' || response.data.id !== props.documentId) return
  loadGeneration += 1
  currentDocument.value = null
  deleteDialogOpen.value = false
  emit('deleted', response.data.id)
  emit('unavailable', response.data.id)
}

function onWebsocketConnect(): void {
  ++loadGeneration
  refreshError.value = false
  if (!currentDocument.value) { refreshing.value = false; void loadDocument(); return }
  refreshing.value = true
  pendingExternalRevision = Math.max(pendingExternalRevision, currentDocument.value.revision + 1)
  scheduleRealtimeRefresh()
}

watch(
  [
    editorOwner,
    editorTitle,
    editorContent,
    editorKeywords,
    editorGlobalAccess,
    sharingAccessByAgentId,
  ],
  () => { preserveDraft(); scheduleAutosave() },
  { deep: true, flush: 'sync' },
)

onMounted(async () => {
  await agentStore.fetchAgents()
  if (disposed) return
  await loadDocument()
  if (disposed) return
  websocket.createWebsocket()
  websocket.onEvent('memory', 'update', onMemoryRealtime)
  websocket.onEvent('memory', 'delete', onMemoryDelete)
  websocket.onEvent('memory', 'invalidate', onWebsocketConnect)
  websocket.onConnect(onWebsocketConnect)
})

onBeforeUnmount(() => {
  disposed = true
  loadGeneration += 1
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (realtimeTimer) clearTimeout(realtimeTimer)
  websocket.offEvent('memory', 'update', onMemoryRealtime)
  websocket.offEvent('memory', 'delete', onMemoryDelete)
  websocket.offEvent('memory', 'invalidate', onWebsocketConnect)
  websocket.offConnect(onWebsocketConnect)
  preserveDraft()
  if (hasUnsavedChanges.value) void flushAutosave()
})

function requestRowAction(action: DocumentRowAction, documentId: string): void {
  if (documentId === props.documentId) requestedRowAction.value = action
}
watch([requestedRowAction, loading, ownerOptionsReady], () => {
  const action = requestedRowAction.value
  if (!action || loading.value) return
  if (!currentDocument.value) { requestedRowAction.value = null; return }
  if (action === 'delete' && !ownerOptionsReady.value) return
  requestedRowAction.value = null
  if (action === 'delete') {
    if (canDeleteDocument.value) deleteDialogOpen.value = true
  } else if (canEditDocument.value && !isGoalDocument(currentDocument.value) && !historyOpen.value) {
    titleInput.value?.focus()
    titleInput.value?.select()
  }
}, { flush: 'post' })
defineExpose({ flush: flushAutosave, requestRowAction })

async function resolveInlineImage(documentId: string, attachmentId: string, signal?: AbortSignal): Promise<Blob> {
  return memoryService.documentAttachmentBlob(documentId, attachmentId, requestAgentId.value, signal)
}
async function exportCurrentDocumentPdf(html: string, signal: AbortSignal): Promise<Blob> {
  const document = currentDocument.value
  if (!document) throw new Error('Document unavailable')
  return memoryService.exportDocumentPdf(document.id, html, signal)
}
async function uploadInlineImage(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const document = currentDocument.value
  const agentId = requestAgentId.value
  if (!document || isGoalDocument(document)) throw new Error('Images unavailable')
  const attachment = await memoryService.addDocumentAttachment(document.id, agentId, file, signal, progress)
  if (signal.aborted || props.documentId !== document.id || requestAgentId.value !== agentId) throw new Error('Document changed')
  await onAttachmentAdded(attachment)
  return 'document://' + document.id + '/attachments/' + attachment.id
}

function draftKey(): string { return 'galaris:document-draft:' + props.agentId + ':' + props.documentId }
function preserveDraft(): void {
  if (!props.editable || applyingDocument || !currentDocument.value || !lastSavedDraft.value) return
  try {
    if (hasUnsavedChanges.value) sessionStorage.setItem(draftKey(), JSON.stringify({ revision: currentDocument.value.revision, base: lastSavedDraft.value, draft: draftFromEditor() }))
    else sessionStorage.removeItem(draftKey())
  } catch { autosaveState.value = 'error' }
}
function restoreDraft(document: MemoryItemDetail): void {
  try {
    const raw = sessionStorage.getItem(draftKey())
    if (!raw) return
    const saved = JSON.parse(raw) as { revision?: number; base?: DocumentDraft; draft?: DocumentDraft }
    if (!saved.draft || !saved.base || typeof saved.draft.content !== 'string' || !Array.isArray(saved.draft.keywords)) return
    applyEditorDraft(saved.draft)
    lastSavedDraft.value = cloneDraft(saved.base)
    if (saved.revision !== document.revision) {
      conflictDocument.value = document
      autosaveState.value = 'error'
      pendingExternalRevision = document.revision
    } else autosaveState.value = 'pending'
  } catch { autosaveState.value = 'error' }
}
</script>

<style scoped>
.document-editor { min-width: 0; }
.document-editor-state { min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.document-editor-error { color: var(--solaire-red-accent); background: var(--solaire-red-light); }
.document-editor-error--dark { background: var(--solaire-red-dark); }
.document-editor-toolbar { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; min-height: 72px; align-items: center; padding-top: 8px; padding-bottom: 8px; }
.document-editor-heading-icon { align-self: center; }
.document-editor-title { min-width: 0; }
.document-editor-details { gap: 4px; margin-top: 4px; }
.document-editor-reference { min-width: 0; max-width: 100%; gap: 4px; }
.document-editor-detail-control { height: 24px; min-height: 24px; }
.document-editor-live-status { flex: 0 0 auto; padding-left: 12px; }
.document-editor-fields { min-width: 0; }
.document-editor-owner-cell { display: flex; width: 40%; min-width: 0; }
.document-editor-sharing-cell { width: 60%; min-width: 0; }
.document-editor-owner-field { flex: 1; min-width: 0; }
.document-editor-owner-field :deep(.q-field__inner),
.document-editor-owner-field :deep(.q-field__control) { height: 100%; }
.document-editor-owner-field :deep(.q-field__native) { flex-wrap: nowrap; }
.document-editor-fields :deep(.q-field--dense .q-field__control) { min-height: 40px; }
.document-editor-fields :deep(.q-field--dense .q-field__marginal) { height: 40px; }
.document-editor-fields :deep(.q-field__bottom) { display: none; }
.document-editor-fields :deep(.q-expansion-item__container > .q-item) { min-height: 48px; }
.document-editor-metadata-cell { display: flex; }
.document-editor-metadata-field { width: 100%; }
.document-editor-metadata-field :deep(.q-field__inner),
.document-editor-metadata-field :deep(.q-field__control) { height: 100%; }
.document-editor-keywords-field :deep(.q-field__native) { align-content: flex-start; align-items: flex-start; }
.document-editor-uri-badge { min-width: 0; max-width: min(100%, 360px); padding: 4px 7px; font-weight: 400; }
.document-editor-uri-badge:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 2px; }
.document-editor-revision-button { flex-shrink: 0; padding: 1px 5px; font-size: inherit; }
.document-editor-sharing-card { min-height: 40px; }
.document-editor-sharing-row { min-width: 0; gap: 8px; }
.document-editor-sharing-label { gap: 5px; flex: 0 0 auto; }
.document-editor-sharing-badges { min-width: 0; flex: 1 1 auto; gap: 4px; }
.document-editor-sharing-badges :deep(.q-chip) { margin: 0; }
.document-editor-sharing-menu { width: min(340px, calc(100vw - 32px)); }
.document-editor-sharing-options { max-height: 260px; overflow-y: auto; }
@media (max-width: 599.98px) {
  .document-editor-sharing-row { align-items: flex-start; }
  .document-editor-sharing-label { padding-top: 5px; }
}
</style>
