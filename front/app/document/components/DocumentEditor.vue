<template>
  <span ref="editorOrigin" hidden />
  <Teleport :to="fullscreenTarget" :disabled="!fullscreen">
  <div ref="focusContainer" v-bind="$attrs" class="document-editor"
    :class="{ 'document-editor--summary': summaryOpen, 'document-editor--fullscreen editorial-fullscreen': fullscreen }"
    tabindex="-1" @keydown.esc="exitFullscreenOnEscape" @keyup.esc="finishFullscreenEscape">
    <DocumentToolbarFrame v-if="fullscreen && !fullscreenToolbars" :label="t('nav.documents')">
      <DocumentToolbarNavigation fullscreen-exit />
    </DocumentToolbarFrame>
    <div v-if="loading" class="document-editor-state">
      <q-spinner color="primary" size="36px" />
    </div>
    <div v-else-if="!currentDocument" class="document-editor-state document-editor-error" :class="{ 'document-editor-error--dark': $q.dark.isActive }" role="alert">
      <q-icon name="warning" size="36px" />
      <span>{{ t('documents.loadError') }}</span>
      <q-btn outline color="primary"  :label="t('documents.retry')" @click="loadDocument" />
    </div>
    <template v-else>
      <q-banner v-if="refreshError" role="alert">
        {{ t('documents.loadError') }}
        <q-btn outline color="primary"  :label="t('documents.retry')" @click="onWebsocketConnect" />
      </q-banner>
      <q-toolbar v-show="!fullscreen" class="document-editor-toolbar" :class="{ 'document-editor-toolbar--dialog': headingInDialog }">
        <q-toolbar-title>
          <Teleport :to="headingTarget ?? 'body'" :disabled="!headingInDialog || fullscreen">
            <div class="document-editor-heading" :class="{ 'document-editor-heading--dialog': headingInDialog }">
              <DocumentIcon class="document-editor-heading-icon" :document-id="currentDocument.id" :document-format="currentDocument.document_format" :title="editorTitle || currentDocument.title" :size="headingInDialog ? '32px' : '64px'" plain />
              <q-input
                ref="titleInput"
                v-model="editorTitle"
                class="document-editor-title col"
                input-class="text-h6"
                :input-style="{ lineHeight: '1.4' }"
                :type="headingInDialog ? 'text' : 'textarea'"
                :autogrow="!headingInDialog"
                :rows="1"
                :outlined="!headingInDialog"
                :borderless="headingInDialog"
                dense
                hide-bottom-space
                :aria-label="t('documents.title')"
                :readonly="historyOpen || summaryOpen || !canEditDocument || isGoalDocument(currentDocument)"
                :rules="[requiredRule]"
              />
            </div>
          </Teleport>
          <div class="document-editor-details row items-center text-caption text-grey-7">
            <div class="document-editor-reference row items-center">
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
                <span class="ellipsis">{{ currentDocument.id }}</span>
                <q-tooltip>{{ t('documents.copyUrl') }}</q-tooltip>
              </q-badge>
              <ResourceTopicBadge :key="currentDocument.id" :topic-id="currentDocument.topic_id ?? null"
                kind="document" :id="currentDocument.id"
                :editable="canEditDocument && !historyOpen && !summaryOpen && !topicChangeInFlight"
                :reassign-topic="changeDocumentTopic" />
              <q-btn flat round dense size="sm" color="primary" icon="short_text"
                :aria-label="t('resourceSummary.open')" @click="openDocumentSummary">
                <q-tooltip>{{ t('resourceSummary.open') }}</q-tooltip>
              </q-btn>
              <q-btn outline

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
              <time
                :datetime="currentDocument.updated_at ?? currentDocument.created_at"
                :title="t('documents.lastModified', { date: lastModifiedDate })"
              >{{ lastModifiedDate }}</time>
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
              color="solaire-violet-light"
              text-color="solaire-violet"
              icon="lock"
            >
              {{ t('document.protected') }}
            </q-chip>
          </div>
        </q-toolbar-title>
        <div class="document-editor-live-status column items-center no-wrap q-gutter-y-xs">
          <q-btn v-if="!editorProvidesFullscreen && !historyOpen && !summaryOpen" flat dense icon="fullscreen"
            :aria-label="t('fullscreenPreview.fullscreen')" @click="fullscreen = true">
            <q-tooltip>{{ t('fullscreenPreview.fullscreen') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="currentDocument.document_format !== 'text' && currentDocument.document_format !== 'mindmap'" flat round dense icon="picture_as_pdf" :loading="formatExportBusy" :aria-label="t('documents.exportFormatPdf')" @click="exportFormatPdf"><q-tooltip>{{ t('documents.exportFormatPdf') }}</q-tooltip></q-btn>
          <q-btn v-if="exchangeExports.length" flat round dense icon="download" :loading="formatExportBusy" :aria-label="t('documents.downloadSource')">
            <q-tooltip>{{ t('documents.downloadSource') }}</q-tooltip>
            <q-menu>
              <q-list>
                <q-item v-close-popup clickable @click="downloadFormatSource"><q-item-section>{{ t('documents.downloadSource') }}</q-item-section></q-item>
                <q-item v-for="target in exchangeExports" :key="target.code" v-close-popup clickable
                  @click="runFormatExport(false, target)"><q-item-section>{{ target.label }}</q-item-section></q-item>
              </q-list>
            </q-menu>
          </q-btn>
          <q-btn v-else flat round dense icon="download" :loading="formatExportBusy" :aria-label="t('documents.downloadSource')" @click="downloadFormatSource"><q-tooltip>{{ t('documents.downloadSource') }}</q-tooltip></q-btn>
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
          <q-btn outline color="primary"  :label="t('richEditor.keepDraft')" @click="resolveConflict(true)" />
          <q-btn outline color="primary"  :label="t('richEditor.useRemote')" @click="resolveConflict(false)" />
        </template>
      </q-banner>
      <q-separator v-show="!fullscreen" />

      <q-card-section
        v-if="!historyOpen && !summaryOpen"
        class="row q-col-gutter-xs document-editor-fields q-pa-xs"
      >
        <div v-show="!fullscreen" class="document-editor-owner-cell">
          <OwnerSelect v-model="editorOwner" class="document-editor-owner-field"
            :options="ownerChoices" :current="selectedOwnerChoice"
            :readonly="!canManageOwner || isGoalDocument(currentDocument)" @open="loadOwnerOptions">
          </OwnerSelect>
        </div>
        <div v-show="!fullscreen" class="document-editor-sharing-cell">
          <DocumentSharingPanel :item-id="documentId" resource-kind="document" :editable="canManageSharing" :lock-version="currentDocument?.lock_version" @permission="sharingPermission = $event" @changed="onSharingChanged" />
        </div>
        <div v-show="!fullscreen" class="col-12 document-editor-metadata-cell">
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
        <div class="col-12 document-editor-content">
          <component :is="documentFormat(currentDocument.document_format, currentDocument.format_version).editor"
            :source="currentDocument.content_type === 'binary' ? formatContentSource : undefined"
            ref="richEditor"
            :key="documentId + ':' + agentId"
            v-model="editorContent"
            toolbar-mode="full"
            :attachments="documentResources"
            :resource-agent-id="requestAgentId"
            :pick-resources="isGoalDocument(currentDocument) ? undefined : pickInternalResources"
            :create-link-card="createLinkCard"
            :upload-file="uploadDocumentFile"
            :export-bundle="exportCurrentBundle"
            @open-attachment="openAttachment"
            @export-document-pdf="exportFormatPdf"
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
          </component>
        </div>
        <div v-show="!fullscreen" class="col-12 document-editor-attachments">
          <DocumentAttachments
            @insert="insertAttachment"
            :allow-insertion="['text', 'mindmap'].includes(currentDocument.document_format)"
            ref="attachmentPanel"
            :content="editorContent"
            :content-media-type="currentDocument.media_type"
            :document-id="currentDocument.id"
            :agent-id="requestAgentId"
            :attachments="listedAttachments"
            :editable="canEditDocument && !isGoalDocument(currentDocument)"
            :loading="attachmentsLoading"
            @added="onAttachmentAdded"
            @removed="onAttachmentRemoved"
            @renamed="onAttachmentRenamed"
          />
          <DocumentResourceReferences v-if="canEditDocument && !isGoalDocument(currentDocument)" :key="currentDocument.id + ':' + agentId"
            v-model:picker-open="internalPickerOpen" @picked="finishInternalPick"
            :document-id="currentDocument.id" :agent-id="requestAgentId" :editable="canEditDocument"
            :host="currentDocument.document_format === 'mindmap' ? 'mindmap' : 'text'" />
        </div>
      </q-card-section>
      <DocumentSummaryPanel v-else-if="summaryOpen" ref="summaryPanel"
        :key="currentDocument.id + ':' + requestAgentId"
        :document-id="currentDocument.id" :agent-id="requestAgentId" :editable="canEditDocument"
        @close="closeDocumentSummary" @updated="onSummaryUpdated" />
      <DocumentHistoryDialog
        v-else
        ref="historyPanel"
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
    <q-dialog data-confirmation v-model="deleteDialogOpen">
      <q-card class="galaris-dialog-card" style="width: 440px; max-width: 90vw">
        <DialogHeader :title="t('documents.deleteDocument')" :close-label="t('common.close')" />
        <q-card-section class="galaris-dialog-body">{{ t('documents.deleteConfirm', { title: editorTitle || currentDocument?.title }) }}</q-card-section>
        <q-card-section v-if="deletionError" role="alert" class="text-negative">
          {{ deletionError }}
        </q-card-section>
        <q-card-actions align="right" class="galaris-dialog-actions">
          <q-btn outline color="primary" v-close-popup  :label="t('common.cancel')" />
          <q-btn data-autofocus color="negative" :label="t('documents.deleteDocument')" :loading="deletingDocument" :disable="!canDeleteDocument" @click="deleteDocument" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
  </Teleport>
</template>

<script setup lang="ts">
import { DialogHeader, documentFullscreenKey, documentWorkspaceViewKey } from '@/core/util'
import DocumentIcon from '@/app/document/components/DocumentIcon.vue'
import DocumentApplicationBlock from '@/app/document/components/DocumentApplicationBlock.vue'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, provide, ref, useTemplateRef, watch } from 'vue'
import { isAxiosError } from 'axios'
import { apiErrorDetail, AUTH_TOKEN_CHANGED_EVENT, registerBeforeLogoutHook, sessionGeneration } from '@/core/api'
import { useAuthStore } from '@/core/user'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar, type QInput } from 'quasar'
import type { DocumentRowAction } from '@/app/document/libraryShortcuts'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { richLinkHref, documentResourceHtml, documentResourceHref, useDocumentFocus, saveBlobAsResource, type DocumentFocus } from '@/core/util'
import { websocket } from '@/core/websocket'
import { useAgentChoices } from '@/app/agent'
import { OwnerSelect, type OwnerOption } from '@/app/share'
import { ResourceTopicBadge, reassignResourceTopic } from '@/core/util'
import { documentFormat, findDocumentFormat, type DocumentContentSource, type DocumentExchangeExport, type DocumentFormatEditorHandle } from '../documentFormats'
import { DatasetDocumentRedirect, documentService } from '../services/documentService'
import { useDocumentMutations } from '@/app/document/stores/documentMutations'
import { reconcileLibrarySnapshot } from '@/app/document/librarySnapshot'
import type { DocumentDraft } from '../documentDraft'
import { useDocumentAutosave } from '../composables/useDocumentAutosave'
import type {
  DocumentAttachment,
  DocumentGlobalAccess,
  DocumentOwnerKind,
  DocumentOwnerOption,
  DocumentOwnerOptions,
  DocumentRecord,
  DocumentDetail,
  DocumentNodeKind,
} from '../types'
import DocumentSharingPanel from './DocumentSharingPanel.vue'
import DocumentAttachments from '@/app/document/components/DocumentAttachments.vue'
import { DocumentResourceReferences, richLinkTarget, richLinkCard, useReferenceFormatting } from '@/core/util'
import { DocumentToolbarFrame, DocumentToolbarNavigation, provideDocumentReferencePath, registerDocumentFullscreenToolbarKey } from '@/core/util/facade'
import DocumentHistoryDialog from '@/app/document/components/DocumentHistoryDialog.vue'
import DocumentSummaryPanel from './DocumentSummaryPanel.vue'

type DocumentShareAccess = 'none' | 'read' | 'edit'

type OwnerChoice = OwnerOption & { value: string }

interface MemoryRealtimeEvent {
  data: {
    id: string
    owner_agent_id: number | null
    owner_user_id: number | null
    node_kind: DocumentNodeKind
    revision: number
    lock_version?: number
  }
}

type NewKeywordDone = (value?: string, mode?: 'add' | 'add-unique' | 'toggle') => void

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  documentId: string
  agentId: number | null
  initialDocument?: DocumentDetail | null
  editable?: boolean
  contentMinHeight?: string
  contentMaxHeight?: string
  headingTarget?: HTMLElement | null
}>(), {
  editable: true,
  contentMinHeight: '520px',
})
provideDocumentReferencePath(() => [props.documentId])

const emit = defineEmits<{
  loaded: [document: DocumentDetail]
  updated: [document: DocumentDetail]
  unavailable: [documentId: string]
  deleted: [documentId: string]
}>()

const { t, locale } = useI18n()
const referenceFormatting = useReferenceFormatting()
const $q = useQuasar()
const headingInDialog = computed(() => $q.screen.lt.md && !!props.headingTarget)
const agentStore = useAgentChoices()
const authStore = useAuthStore()
// This editor and its pending work always belong to the account that opened it.
const draftUserId = authStore.user?.id ?? null
const editorSession = sessionGeneration()
const sessionActive = ref(true)
function isCurrentEditorSession(): boolean {
  return sessionActive.value && editorSession === sessionGeneration()
    && (draftUserId === null || authStore.user?.id === draftUserId)
}
const documentMutations = useDocumentMutations()
const privilegeStore = usePrivilegeStore()
const loading = ref(true)
const focusContainer = useTemplateRef<HTMLElement>('focusContainer')
const editorOrigin = useTemplateRef<HTMLElement>('editorOrigin')
const workspaceView = inject(documentWorkspaceViewKey, null)
const fullscreen = workspaceView?.fullscreen ?? ref(false)
const fullscreenTarget = computed(() => editorOrigin.value?.closest('.q-dialog__inner') ?? 'body')
provide(documentFullscreenKey, fullscreen)
const fullscreenToolbars = ref(0)
provide(registerDocumentFullscreenToolbarKey, () => {
  fullscreenToolbars.value++
  return () => { fullscreenToolbars.value-- }
})
const editorProvidesFullscreen = computed(() => {
  const item = currentDocument.value
  return !historyOpen.value && !summaryOpen.value && !!item
    && ['text', 'mindmap'].includes(documentFormat(item.document_format, item.format_version).code)
})
let exitingWithEscape = false
function exitFullscreenOnEscape(event: KeyboardEvent): void {
  if (!fullscreen.value || event.defaultPrevented || event.isComposing) return
  event.preventDefault()
  event.stopPropagation()
  exitingWithEscape = true
  fullscreen.value = false
}
function finishFullscreenEscape(event: KeyboardEvent): void {
  if (!exitingWithEscape) return
  exitingWithEscape = false
  event.stopPropagation()
}
watch(fullscreen, async active => {
  const container = focusContainer.value
  const focused = container?.ownerDocument.activeElement
  await nextTick()
  if (active !== fullscreen.value || !container?.isConnected) return
  if (focused instanceof HTMLElement && container.contains(focused) && focused.getClientRects().length) focused.focus({ preventScroll: true })
  if ((active || exitingWithEscape) && !container.contains(container.ownerDocument.activeElement)) container.focus({ preventScroll: true })
}, { flush: 'sync' })
onMounted(async () => {
  if (!fullscreen.value) return
  await nextTick()
  if (fullscreen.value) focusContainer.value?.focus({ preventScroll: true })
})
const documentFocus = useDocumentFocus(focusContainer)
watch(() => [props.documentId, props.agentId], () => documentFocus.reset(), { flush: 'sync' })
const titleInput = useTemplateRef<QInput>('titleInput')
const requestedRowAction = ref<DocumentRowAction | null>(null)
const ownerOptionsReady = ref(false)
const deleteDialogOpen = ref(false)
const deletingDocument = ref(false)
const deletionError = ref('')
watch(deleteDialogOpen, () => { deletionError.value = '' })
const refreshing = ref(false)
const refreshError = ref(false)
const currentDocument = ref<DocumentDetail | null>(null)
const lastModifiedDate = computed(() => {
  const document = currentDocument.value
  if (!document) return ''
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(document.updated_at ?? document.created_at))
})
const topicChangeInFlight = ref(false)
async function changeDocumentTopic(topicId: string): Promise<number> {
  if (!canEditDocument.value || topicChangeInFlight.value) throw new Error(t('topic.assignmentAudit.changeError'))
  topicChangeInFlight.value = true
  const generation = loadGeneration
  try {
    cancelAutosave()
    await waitForActiveSave()
    const current = currentDocument.value
    if (!current || disposed || generation !== loadGeneration) throw new Error(t('topic.assignmentAudit.changeError'))
    const result = await reassignResourceTopic('document', current.id, topicId, current.topic_id ?? null, current.lock_version)
    if (!disposed && generation === loadGeneration && currentDocument.value?.id === current.id) {
      currentDocument.value = { ...currentDocument.value, ...result }
      emit('updated', currentDocument.value)
    }
    return 1
  } finally {
    topicChangeInFlight.value = false
    if (!disposed && generation === loadGeneration) scheduleAutosave()
  }
}
const editorTitle = ref('')
const editorOwner = ref('')
const editorContent = ref('')
const editorKeywords = ref<string[]>([])
const keywordOptions = ref<string[]>([])
const filteredKeywordOptions = ref<string[]>([])
const ownerOptions = ref<DocumentOwnerOptions>({ agents: [], users: [] })
const attachments = ref<DocumentAttachment[]>([])
const listedAttachments = computed(() => {
  const retained: unknown = currentDocument.value?.metadata.retained_document_attachments
  const identifiers = new Set(Array.isArray(retained) ? retained.flatMap((entry: unknown) =>
    entry && typeof entry === 'object' && 'id' in entry && typeof entry.id === 'string' ? [entry.id] : []) : [])
  return attachments.value.filter(attachment => !identifiers.has(attachment.id))
})
const route = useRoute(), router = useRouter()
const richEditor = ref<DocumentFormatEditorHandle>()
function insertAttachment(attachment: DocumentAttachment): void {
  richEditor.value?.insertResource?.(documentResourceHtml({ uri: 'document://' + props.documentId + '/attachments/' + attachment.id, name: attachment.name, size: attachment.size_bytes, mediaType: attachment.media_type }))
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
const documentResources = computed(() => listedAttachments.value.map(value => ({ uri: 'document://' + props.documentId + '/attachments/' + value.id, name: value.name, size: value.size_bytes, mediaType: value.media_type })))
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
  const result = await documentService.createDocumentLinkCard(documentId, requestAgentId.value, url)
  if (props.documentId !== documentId) throw new Error('Document changed')
  if (result.attachment) onAttachmentAdded(result.attachment)
  return result.html
}
async function uploadDocumentFile(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const documentId = props.documentId
  const attachment = await documentService.addDocumentAttachment(documentId, requestAgentId.value, file, signal, progress)
  if (props.documentId !== documentId) throw new Error('Document changed')
  onAttachmentAdded(attachment)
  return 'document://' + documentId + '/attachments/' + attachment.id
}
async function importPastedImage(url: string, signal: AbortSignal): Promise<string> {
  const documentId = props.documentId, agentId = requestAgentId.value
  const attachment = await documentService.importDocumentImage(documentId, agentId, url, signal)
  if (signal.aborted || props.documentId !== documentId || requestAgentId.value !== agentId) throw new Error('Document changed')
  onAttachmentAdded(attachment)
  return 'document://' + documentId + '/attachments/' + attachment.id
}
async function exportCurrentBundle(html: string, signal: AbortSignal): Promise<Blob> {
  return documentService.exportDocumentBundle(props.documentId, requestAgentId.value, html, signal)
}
const attachmentsLoading = ref(false)
const historyOpen = ref(false)
const summaryOpen = ref(false)
const summaryPanel = useTemplateRef<InstanceType<typeof DocumentSummaryPanel>>('summaryPanel')
const historyPanel = useTemplateRef<InstanceType<typeof DocumentHistoryDialog>>('historyPanel')
const switchingView = ref(false)
watch(() => [props.documentId, props.agentId], () => { summaryOpen.value = false; historyOpen.value = false })
const editorGlobalAccess = ref<DocumentGlobalAccess>(0)
const sharingAccessByAgentId = ref<Record<number, DocumentShareAccess>>({})
const realtimeConnected = computed(() => websocket.isConnected.value && !loading.value && !refreshing.value)
const pending = { revision: 0, lockVersion: 0 }
let realtimeTimer: ReturnType<typeof setTimeout> | undefined
let loadGeneration = 0
let ownerLoadGeneration = 0
let keywordLoadGeneration = 0
let disposed = false
let initialDocument = props.initialDocument

const agentOptions = computed(() => agentStore.sortedAgents.map(agent => ({
  value: agent.id,
  label: agent.label,
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
  && isCurrentEditorSession()
  && currentDocument.value?.access.can_write
  && findDocumentFormat(currentDocument.value.document_format, currentDocument.value.format_version)
  && !currentDocument.value.read_only
  && !currentDocument.value.source_managed
  && privilegeStore.hasPrivilege(privileges.DOCUMENT_EDIT),
))
const sharingPermission = ref<boolean | null>(null)
watch(() => props.documentId, () => { sharingPermission.value = null })
const canManageSharing = computed(() => Boolean(
  props.editable
  && isCurrentEditorSession()
  && currentDocument.value
  && !currentDocument.value.source_managed
  && (
    privilegeStore.hasPrivilege(privileges.DOCUMENT_ADMIN)
    || (
      (sharingPermission.value ?? (selectedAgentOwnsDocument.value || currentUserOwnsDocument.value))
      && privilegeStore.hasPrivilege(privileges.DOCUMENT_EDIT)
    )
  ),
))
const canManageOwner = computed(() => canEditDocument.value && canManageSharing.value)
const canDeleteDocument = computed(() => Boolean(
  props.editable
  && currentDocument.value
  && !currentDocument.value.deletion_protected
  && !currentDocument.value.source_managed
  && privilegeStore.hasPrivilege(privileges.DOCUMENT_EDIT)
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

function fallbackOwnerChoice(document: DocumentRecord | null): OwnerChoice | null {
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
function isGoalDocument(document: DocumentRecord): boolean {
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

function documentSharing(document: DocumentDetail): Record<number, DocumentShareAccess> {
  // The saved draft must not depend on whether the owner catalogue has arrived.
  return Object.fromEntries(document.grants.map(grant => [grant.agent_id, grant.can_write ? 'edit' : 'read']))
}

function draftFromDocument(document: DocumentDetail): DocumentDraft {
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

function readEditorDraft(): DocumentDraft {
  return {
    owner: editorOwner.value,
    title: editorTitle.value.trim(),
    content: editorContent.value,
    keywords: normalizedKeywords(editorKeywords.value),
    globalAccess: editorGlobalAccess.value,
    sharing: Object.fromEntries(Object.entries(sharingAccessByAgentId.value).filter(([, access]) => access !== 'none')),
  }
}

const editorDraft = computed(readEditorDraft)

function applyEditorDraft(draft: DocumentDraft): void {
  editorOwner.value = draft.owner
  editorTitle.value = draft.title
  editorContent.value = draft.content
  editorKeywords.value = [...draft.keywords]
  editorGlobalAccess.value = draft.globalAccess
  sharingAccessByAgentId.value = { ...draft.sharing }
}

const {
  autosaveState, conflictDocument, hasUnsavedChanges, acceptDocument, resolveConflict, clearConflict,
  cancelAutosave, isSaving, scheduleAutosave, waitForActiveSave, flushAutosave,
  mergeDocument, mergeLatestDocument, commitBeforeContentRefresh, discardDraft: discardAutosaveDraft,
  draftKey, preserveDraft, preserveClosingDraft, preserveHiddenDraft,
} = useDocumentAutosave({
  identity: props,
  currentDocument,
  editorDraft,
  draftFromDocument,
  applyEditorDraft,
  session: { userId: draftUserId, active: sessionActive, isCurrent: isCurrentEditorSession },
  permissions: { edit: canEditDocument, share: canManageSharing, manageOwner: canManageOwner, requestAgentId },
  isGoalDocument,
  sharingAgents: sharingAgentOptions,
  isBlocked: () => topicChangeInFlight.value || deletingDocument.value,
  realtime: { pending, generation: () => loadGeneration, refresh: refreshFromRealtime, schedule: scheduleRealtimeRefresh },
  commitEditor: () => richEditor.value?.commitDraft?.(),
  onUpdated: document => emit('updated', document),
  onReloaded: document => applyDocument(document, 'updated'),
})

function applyDocument(document: DocumentDetail, event: 'loaded' | 'updated'): void {
  acceptDocument(document, event)
  keywordOptions.value = [...new Set([...keywordOptions.value, ...document.keywords])]
    .sort((left, right) => left.localeCompare(right, locale.value, { sensitivity: 'base' }))
  filteredKeywordOptions.value = keywordOptions.value
  if (event === 'updated') emit('updated', document)
  else emit('loaded', document)
}

async function loadKeywords(): Promise<void> {
  const generation = ++keywordLoadGeneration
  try {
    const incoming = await documentService.listDocumentKeywords(requestAgentId.value)
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
  pending.revision = Math.max(pending.revision, currentDocument.value?.revision ?? 0)
  await refreshFromRealtime()
}

async function loadAttachments(): Promise<void> {
  const generation = loadGeneration
  attachmentsLoading.value = attachments.value.length === 0
  try {
    const incoming = await documentService.listDocumentAttachments(props.documentId, requestAgentId.value)
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
  await switchDocumentView('history')
}

async function openDocumentSummary(): Promise<void> { await switchDocumentView('summary') }
async function switchDocumentView(view: 'history' | 'summary'): Promise<void> {
  if (switchingView.value) return
  switchingView.value = true
  const id = props.documentId, agentId = props.agentId
  try {
    if (!await flushEditor() || id !== props.documentId || agentId !== props.agentId) return
    historyOpen.value = view === 'history'
    summaryOpen.value = view === 'summary'
  } finally { switchingView.value = false }
}
function onSummaryUpdated(summary: DocumentDetail): void {
  const current = currentDocument.value
  if (current?.id === summary.id && current.revision === summary.revision) {
    currentDocument.value = { ...current, lock_version: summary.lock_version, updated_at: summary.updated_at }
    emit('updated', currentDocument.value)
  }
}
async function closeDocumentSummary(): Promise<void> {
  try {
    await mergeLatestDocument(props.documentId)
    summaryOpen.value = false
  } catch { refreshError.value = true }
}
async function flushEditor(): Promise<boolean> {
  richEditor.value?.commitDraft?.()
  if (currentDocument.value?.content_type === 'binary' && richEditor.value?.flush && !await richEditor.value.flush()) return false
  return flushMetadata()
}
async function flushMetadata(): Promise<boolean> {
  preserveDraft()
  if (summaryPanel.value && !await summaryPanel.value.flush()) return false
  return await flushAutosave()
}

function closeDocumentHistory(): void {
  historyOpen.value = false
}

async function onHistoryRestored(): Promise<void> {
  historyOpen.value = false
  await loadDocument()
}

async function loadDocument(): Promise<void> {
  if (!isCurrentEditorSession()) return
  const generation = ++loadGeneration
  loading.value = !currentDocument.value
  refreshError.value = false
  try {
    const seed = initialDocument
    initialDocument = null
    const document = seed?.id === props.documentId ? seed : await documentService.getDocument(props.documentId, requestAgentId.value)
    if (generation !== loadGeneration) return
    if (document.document_format === 'dataset') throw new DatasetDocumentRedirect(`data://${document.id}`)
    if (document.document_format === 'process') throw new Error('Process definitions belong to Process.')
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
  if (!privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN])) {
    ownerOptions.value = { agents: [], users: [] }
    ownerOptionsReady.value = true
    return
  }
  try {
    const incoming = await documentService.listDocumentOwnerOptions()
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

async function deleteDocument(): Promise<void> {
  const document = currentDocument.value
  const agentId = requestAgentId.value
  const storageKey = draftKey()
  if (!document || !canDeleteDocument.value || deletingDocument.value) return
  const finishDeletion = documentMutations.beginDeletion(document.id)
  if (!finishDeletion) return
  deletingDocument.value = true
  deletionError.value = ''
  cancelAutosave()
  if (realtimeTimer) clearTimeout(realtimeTimer)
  try {
    await waitForActiveSave()
    if (disposed || currentDocument.value?.id !== document.id || requestAgentId.value !== agentId || !canDeleteDocument.value) return
    await documentService.deleteDocument(document.id, agentId)
    try { if (storageKey) sessionStorage.removeItem(storageKey) } catch { /* Storage may be unavailable. */ }
    if (disposed || currentDocument.value?.id !== document.id || requestAgentId.value !== agentId) return
    loadGeneration += 1
    currentDocument.value = null
    deleteDialogOpen.value = false
    $q.notify({ type: 'positive', message: t('documents.deleted') })
    emit('deleted', document.id)
    emit('unavailable', document.id)
  } catch (error) {
    if (!disposed && currentDocument.value?.id === document.id) {
      deletionError.value = apiErrorDetail(error) || t('documents.deleteError')
      $q.notify({ type: 'negative', message: t('documents.deleteError'), caption: deletionError.value })
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
  if (!document || isSaving()) return
  if (pending.revision < document.revision && pending.lockVersion <= document.lock_version) {
    pending.revision = 0
    pending.lockVersion = 0
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
      const latest = await documentService.getDocument(document.id, requestAgentId.value)
      if (generation === loadGeneration && currentDocument.value?.id === document.id) {
        commitBeforeContentRefresh(latest)
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
    preserveClosingDraft()
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
  pending.revision = Math.max(pending.revision, event.revision)
  pending.lockVersion = Math.max(pending.lockVersion, event.lock_version ?? 0)
  if (!isSaving()) { ++loadGeneration; scheduleRealtimeRefresh() }
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
  pending.revision = Math.max(pending.revision, currentDocument.value.revision + 1)
  scheduleRealtimeRefresh()
}

onMounted(async () => {
  window.addEventListener('pagehide', preserveClosingDraft)
  document.addEventListener('visibilitychange', preserveHiddenDraft)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeEditorSession)
  // Labels are optional: their catalogue must not block document loading or realtime setup.
  void agentStore.fetchAgents().catch(() => { /* Agent labels retain their ID fallback. */ })
  await loadDocument()
  if (disposed || !sessionActive.value) return
  websocket.createWebsocket()
  websocket.onEvent('document', 'update', onMemoryRealtime)
  websocket.onEvent('document', 'delete', onMemoryDelete)
  websocket.onEvent('document', 'invalidate', onWebsocketConnect)
  websocket.onConnect(onWebsocketConnect)
})

onBeforeUnmount(() => {
  richEditor.value?.commitDraft?.()
  disposed = true
  loadGeneration += 1
  cancelAutosave()
  if (realtimeTimer) clearTimeout(realtimeTimer)
  window.removeEventListener('pagehide', preserveClosingDraft)
  document.removeEventListener('visibilitychange', preserveHiddenDraft)
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeEditorSession)
  removeLogoutHook()
  websocket.offEvent('document', 'update', onMemoryRealtime)
  websocket.offEvent('document', 'delete', onMemoryDelete)
  websocket.offEvent('document', 'invalidate', onWebsocketConnect)
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
  } else if (canEditDocument.value && !isGoalDocument(currentDocument.value) && !historyOpen.value && !summaryOpen.value) {
    titleInput.value?.focus()
    titleInput.value?.select()
  }
}, { flush: 'post' })
function captureFocus(): DocumentFocus | null {
  const current = currentDocument.value
  if (loading.value || summaryOpen.value || current?.id !== props.documentId) return null
  const empty = { selection: null, cursor: null, viewport: null }
  if (historyOpen.value) {
    const historical = historyPanel.value?.displayedRevision()
    return historical ? { ...empty, surface: 'history', revision: historical.revision,
      document_format: historical.document_format ?? current.document_format } : null
  }
  const anchor = richEditor.value?.captureFocus?.()
  if (anchor) return { ...empty, surface: 'format', revision: current.revision, document_format: current.document_format, anchor }
  return documentFocus.capture(current.revision) ?? {
    ...empty, surface: 'format', revision: current.revision, document_format: current.document_format,
  }
}
async function discardDraft(): Promise<void> {
  await richEditor.value?.discardDraft?.()
  await discardAutosaveDraft()
}

const canEditMindMap = computed(() => canEditDocument.value && currentDocument.value?.document_format === 'mindmap')
const canAppendHtml = computed(() => canEditDocument.value && currentDocument.value?.document_format === 'text'
  && !historyOpen.value && !summaryOpen.value && !conflictDocument.value && Boolean(richEditor.value?.appendHtml))
function appendHtml(html: string): boolean {
  return canAppendHtml.value && (richEditor.value?.appendHtml?.(html) ?? false)
}
defineExpose({ flush: flushEditor, discardDraft, requestRowAction, captureFocus, canEditMindMap, canAppendHtml, appendHtml })

async function resolveInlineImage(documentId: string, attachmentId: string, signal?: AbortSignal): Promise<Blob> {
  return documentService.documentAttachmentBlob(documentId, attachmentId, requestAgentId.value, signal)
}
async function exportCurrentDocumentPdf(html: string, signal: AbortSignal): Promise<Blob> {
  const document = currentDocument.value
  if (!document) throw new Error('Document unavailable')
  return documentService.exportDocumentPdf(document.id, html, signal)
}
const formatExportBusy = ref(false)
const exchangeExports = computed(() => {
  const document = currentDocument.value
  return document ? documentFormat(document.document_format, document.format_version).exchangeExports ?? [] : []
})
const formatContentSource = computed<DocumentContentSource | null>(() => {
  const document = currentDocument.value, agent = requestAgentId.value
  if (!document) return null
  return {
    key: `${document.id}:${document.revision}:${agent}`, revision: document.revision, readonly: !canEditDocument.value,
    load: signal => documentService.source(document.id, agent, signal, document.revision),
    save: async (content, expectedRevision, signal) => {
      if (!canEditDocument.value || currentDocument.value?.id !== document.id || requestAgentId.value !== agent || !isCurrentEditorSession()) throw new Error('Document changed')
      if (!await flushMetadata()) throw new Error('Unsaved document metadata')
      signal.throwIfAborted()
      if (currentDocument.value?.id !== document.id || requestAgentId.value !== agent || !isCurrentEditorSession()) throw new Error('Document changed')
      const bytes = new Uint8Array(await content.arrayBuffer())
      let binary = ''
      for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
      const updated = await documentService.updateDocument(document.id, agent, {
        payload: { base64: btoa(binary) }, expected_revision: expectedRevision,
      }, signal)
      if (currentDocument.value?.id === document.id && requestAgentId.value === agent && isCurrentEditorSession()) await mergeLatestDocument(document.id)
      return updated.revision
    },
  }
})
let formatExportRequest: AbortController | undefined
async function runFormatExport(pdf: boolean, target?: DocumentExchangeExport): Promise<void> {
  const original = currentDocument.value
  const agent = requestAgentId.value
  if (!original || formatExportBusy.value) return
  richEditor.value?.commitDraft?.()
  if (target && hasUnsavedChanges.value) {
    if (!await flushAutosave()) {
      $q.notify({ type: 'negative', message: t('documents.formatExportFailed') })
      return
    }
  }
  const document = currentDocument.value
  if (document?.id !== original.id || requestAgentId.value !== agent || !isCurrentEditorSession() || formatExportBusy.value) return
  const request = new AbortController(); formatExportRequest = request
  formatExportBusy.value = true
  try {
    const blob = pdf
      ? await documentService.exportDocumentPdf(document.id, await documentFormat(document.document_format, document.format_version).snapshot(editorContent.value, editorTitle.value, request.signal, resolveInlineImage, undefined,
        { key: `${document.id}:${document.revision}:${agent}`, revision: document.revision, readonly: true,
          load: signal => documentService.source(document.id, agent, signal, document.revision),
          save: async () => { throw new Error('Document snapshots are read-only') } }), request.signal)
      : await documentService.source(document.id, agent, request.signal, target ? document.revision : undefined, target?.code)
    if (!request.signal.aborted && currentDocument.value?.id === document.id && requestAgentId.value === agent) {
      const extension = target?.extension ?? (pdf ? '.pdf' : document.document_format === 'data' ? '.json' : document.document_format === 'text' ? '.html'
        : documentFormat(document.document_format, document.format_version).nativeExtension ?? '')
      saveBlobAsResource(blob, document.title.replace(/[\\/:*?"<>|]/g, '-') + extension)
    }
  } catch { if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('documents.formatExportFailed') }) }
  finally { if (formatExportRequest === request) { formatExportBusy.value = false; formatExportRequest = undefined } }
}
function exportFormatPdf(): void { void runFormatExport(true) }
function downloadFormatSource(): void { void runFormatExport(false) }
watch(() => [props.documentId, currentDocument.value?.revision, requestAgentId.value, editorContent.value, editorTitle.value, sessionActive.value], () => { formatExportRequest?.abort(); formatExportRequest = undefined; formatExportBusy.value = false })
onBeforeUnmount(() => formatExportRequest?.abort())
async function uploadInlineImage(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const document = currentDocument.value
  const agentId = requestAgentId.value
  if (!document || isGoalDocument(document)) throw new Error('Images unavailable')
  const attachment = await documentService.addDocumentAttachment(document.id, agentId, file, signal, progress)
  if (signal.aborted || props.documentId !== document.id || requestAgentId.value !== agentId) throw new Error('Document changed')
  await onAttachmentAdded(attachment)
  return 'document://' + document.id + '/attachments/' + attachment.id
}

function invalidateEditorSession(): void {
  if (!sessionActive.value) return
  preserveClosingDraft()
  sessionActive.value = false
  ++loadGeneration; ++ownerLoadGeneration; ++keywordLoadGeneration
  cancelAutosave()
  if (realtimeTimer) clearTimeout(realtimeTimer)
  currentDocument.value = null
  clearConflict()
  deleteDialogOpen.value = false
  loading.value = false
  emit('unavailable', props.documentId)
}
function changeEditorSession(event: Event): void {
  if ((event as CustomEvent<string | null>).detail === null || editorSession !== sessionGeneration()) invalidateEditorSession()
}
watch(() => authStore.user?.id, id => { if (draftUserId !== null && id !== draftUserId) invalidateEditorSession() }, { flush: 'sync' })
const removeLogoutHook = registerBeforeLogoutHook(async () => { preserveClosingDraft() })
</script>

<style scoped>
.document-editor { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; overflow: auto; }
.document-editor > :not(.document-editor-fields) { flex-shrink: 0; }
.document-editor--fullscreen { height: 100dvh; max-height: none; overflow: hidden; }
.document-editor--fullscreen > .document-editor-fields { flex: 1 1 auto; min-height: 0; overflow: auto; display: block; margin: 0; padding: 0; }
.document-editor--fullscreen > .document-editor-fields > .document-editor-content { min-height: 100%; padding: 0; }
.document-editor--summary :deep(> .document-summary-panel) { flex: 1 1 auto; min-height: 0; }
.document-editor-state { min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.document-editor-error { color: var(--solaire-red-accent); background: var(--solaire-red-light); }
.document-editor-error--dark { background: var(--solaire-red-dark); }
.document-editor-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; min-height: 72px; align-items: center; padding-top: 8px; padding-bottom: 8px; }
.document-editor-toolbar > .q-toolbar__title { display: grid; grid-template-columns: 64px minmax(0, 1fr); align-items: center; column-gap: 12px; padding: 0; }
.document-editor-heading { display: contents; }
.document-editor-heading-icon { grid-column: 1; grid-row: 1 / 3; }
.document-editor-title, .document-editor-details { grid-column: 2; }
.document-editor-heading--dialog { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; }
.document-editor-heading--dialog .document-editor-heading-icon { grid-row: auto; }
.document-editor-heading--dialog :deep(.q-field__native) { color: white; text-overflow: ellipsis; }
.document-editor-toolbar--dialog { min-height: 0; padding: 4px; }
.document-editor-toolbar--dialog > .q-toolbar__title { display: block; }
.document-editor-toolbar--dialog .document-editor-details { margin-top: 0; }
.document-editor-heading-icon { align-self: center; }
.document-editor-title { min-width: 0; }
.document-editor-details { gap: 4px; margin-top: 4px; }
.document-editor-reference { min-width: 0; max-width: 100%; gap: 4px; }
.document-editor-detail-control { height: 24px; min-height: 24px; }
.document-editor-live-status { flex: 0 0 auto; padding-left: 12px; }
.document-editor-fields { display: grid; grid-template-columns: 40% 60%; grid-template-rows: auto auto minmax(min-content, 1fr) auto; flex: 1 0 auto; min-width: 0; }
.document-editor-fields > .col-12 { grid-column: 1 / -1; width: auto; }
.document-editor-content { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.document-editor-content :deep(> .tiptap-galaris-editor:not(.editorial-fullscreen)) { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.document-editor-content :deep(.tiptap-galaris-editor:not(.editorial-fullscreen) > :not(.editorial-workspace)) { flex-shrink: 0; }
/* Grow the document into free space; long content and attachments scroll together. */
.document-editor-content :deep(.tiptap-galaris-editor:not(.editorial-fullscreen) > .editorial-workspace) { flex: 1 0 auto; min-height: 0; align-items: stretch; }
.document-editor-content :deep(.tiptap-galaris-editor:not(.editorial-fullscreen) .editorial-body) { display: flex; flex-direction: column; min-height: 0; }
.document-editor-content :deep(.tiptap-galaris-editor:not(.editorial-fullscreen) .editorial-body > div) { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.document-editor-content :deep(.tiptap-galaris-editor:not(.editorial-fullscreen) [data-editor-surface]) { flex: 1; min-height: 0; max-height: none; }
.document-editor-owner-cell { display: flex; min-width: 0; }
.document-editor-sharing-cell { min-width: 0; }
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
@media (max-width: 1023px) {
  .document-editor-content { padding-top: 0; }
  .document-editor-content :deep(.editorial-toolbar) { border-top: 0; }
}
@media (max-width: 599.98px) {
  .document-editor-sharing-row { align-items: flex-start; }
  .document-editor-sharing-label { padding-top: 5px; }
}
</style>
