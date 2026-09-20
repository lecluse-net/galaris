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
      <q-toolbar class="document-editor-toolbar">
        <DocumentIcon :document-id="currentDocument.id" :title="editorTitle || currentDocument.title" size="40px" class="q-mr-sm" />
        <q-toolbar-title>
          <div class="row items-center no-wrap">
            <div class="text-h6 ellipsis">{{ editorTitle || currentDocument.title }}</div>
            <q-btn
              v-if="canDeleteDocument"
              flat round dense size="sm" icon="delete_outline" style="color: var(--solaire-red-accent)"
              class="q-ml-sm" :loading="deletingDocument"
              :aria-label="t('documents.deleteDocument')"
              @click="deleteDialogOpen = true"
            >
              <q-tooltip>{{ t('documents.deleteDocument') }}</q-tooltip>
            </q-btn>
          </div>
          <div class="row items-center q-gutter-xs text-caption text-grey-7">
            <q-badge outline>{{ t(`documents.types.${currentDocument.document_type ?? 'html'}`) }}</q-badge>
            <q-badge
              outline
              color="primary"
              class="document-editor-uri-badge cursor-pointer"
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
              class="document-editor-revision-button"
              :label="t('documents.revision', { revision: currentDocument.revision })"
              :aria-label="t('documents.historyOpen')"
              @click="openDocumentHistory"
            >
              <q-tooltip>{{ t('documents.historyOpen') }}</q-tooltip>
            </q-btn>
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
        <DocumentAppPermissions v-if="!isDataset" :document-id="currentDocument.id" :revision="currentDocument.revision"
          :disabled="hasUnsavedChanges || !!conflictDocument"
          :can-write="privilegeStore.hasPrivilege(privileges.MEMORY_EDIT) || privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN)"
          @changed="appPermissionsGeneration++" />
        <div class="document-editor-live-status column items-end q-gutter-xs">
          <div class="row items-center no-wrap text-caption" :class="realtimeStatusClass">
            <q-icon :name="realtimeConnected ? 'wifi' : 'wifi_off'" size="16px" class="q-mr-xs" />
            {{ t(realtimeConnected ? 'documents.realtimeActive' : 'documents.realtimeConnecting') }}
          </div>
          <div class="row items-center no-wrap text-caption" :class="autosaveStatus.colorClass">
            <q-spinner v-if="autosaveState === 'saving'" size="14px" class="q-mr-xs" />
            <q-icon v-else :name="autosaveStatus.icon" size="16px" class="q-mr-xs" />
            {{ t(autosaveStatus.labelKey) }}
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
        class="row q-col-gutter-sm document-editor-fields q-pa-sm"
      >
        <div class="col-12 col-md-4">
          <q-select
            v-model="editorOwner"
            class="document-editor-owner-field"
            :options="filteredOwnerOptions"
            outlined
            dense
            stack-label
            hide-bottom-space
            use-input
            emit-value
            map-options
            input-debounce="180"
            option-value="value"
            option-label="label"
            option-disable="disable"
            :readonly="!canManageOwner || isGoalDocument(currentDocument)"
            :label="t('documents.owner')"
            @filter="filterOwnerOptions"
          >
            <template #selected>
              <div v-if="selectedOwnerChoice" class="row items-center no-wrap owner-selected">
                <AgentAvatar
                  v-if="selectedOwnerChoice.kind === 'agent'"
                  :agent-id="selectedOwnerChoice.id"
                  :name="selectedOwnerChoice.label"
                  size="22px"
                />
                <q-avatar v-else size="22px" color="grey-3" text-color="grey-8">
                  <img v-if="selectedOwnerChoice.avatarUrl" :src="selectedOwnerChoice.avatarUrl" alt="" />
                  <q-icon v-else name="person" size="16px" />
                </q-avatar>
                <span class="ellipsis q-ml-sm">{{ selectedOwnerChoice.label }}</span>
              </div>
            </template>
            <template #option="scope">
              <q-item v-if="scope.opt.section" dense class="owner-section">
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
        </div>
        <div class="col-12 col-md-8">
          <q-input
            v-model="editorTitle"
            outlined
            dense
            stack-label
            hide-bottom-space
            :readonly="!canEditDocument || isGoalDocument(currentDocument)"
            :label="t('documents.title')"
            :rules="[requiredRule]"
          />
        </div>
        <div class="col-12">
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
          <CodeEditor
            v-if="isDataset"
            :key="documentId + ':' + agentId"
            v-model="editorContent"
            language="json"
            :label="t('documents.content')"
            :readonly="!canEditDocument"
            :min-lines="20"
            :visible-lines="35"
          />
          <div v-if="isDataset && !validDataset" role="alert" class="text-negative q-mt-sm">{{ t('documents.invalidDataset') }}</div>
          <RichTextEditor
            v-else-if="!isDataset"
            ref="richEditor"
            manage-attachments
            @manage-attachments="attachmentPanel?.openManager()"
            :key="documentId + ':' + agentId"
            v-model="editorContent"
            :attachments="documentResources"
            :create-link-card="createLinkCard"
            :upload-file="uploadDocumentFile"
            :export-bundle="exportCurrentBundle"
            @open-attachment="openAttachment"
            :media-type="currentDocument.media_type"
            :profile="currentDocument.content_profile ?? (isGoalDocument(currentDocument) ? 'rich-text' : 'document')"
            :upload-image="isGoalDocument(currentDocument) ? undefined : uploadInlineImage"
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
              <DocumentApplicationBlock :key="appPermissionsGeneration" :source="source" :language="language" :register-snapshot="registerSnapshot" :document-id="currentDocument.id" :revision="currentDocument.revision" :ready="!hasUnsavedChanges && !conflictDocument && (autosaveState === 'saved' || !canEditDocument)" />
            </template>
          </RichTextEditor>
        </div>
        <div class="col-12">
          <DocumentAttachments
            :manager-mode="!isDataset"
            @insert="insertAttachment"
            ref="attachmentPanel"
            :content="isDataset ? '' : editorContent"
            :document-id="currentDocument.id"
            :agent-id="agentId"
            :attachments="attachments"
            :editable="canEditDocument && !isGoalDocument(currentDocument)"
            :loading="attachmentsLoading"
            @added="onAttachmentAdded"
            @removed="onAttachmentRemoved"
          />
        </div>
      </q-card-section>
      <DocumentHistoryDialog
        v-else
        :document-id="currentDocument.id"
        :current-revision="currentDocument.revision"
        :agent-id="agentId"
        :can-restore="canEditDocument"
        :min-height="contentMinHeight"
        :max-height="contentMaxHeight"
        @close="closeDocumentHistory"
        @restored="onHistoryRestored"
      />
    </template>
    <q-dialog v-model="deleteDialogOpen">
      <q-card style="width: 440px; max-width: 90vw">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('documents.deleteDocument') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('documents.deleteConfirm', { title: editorTitle || currentDocument?.title }) }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn flat style="color: var(--solaire-red-accent)" :label="t('documents.deleteDocument')" :loading="deletingDocument" :disable="!canDeleteDocument" @click="deleteDocument" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import DocumentApplicationBlock from './DocumentApplicationBlock.vue'
import DocumentAppPermissions from './DocumentAppPermissions.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CodeEditor, RichTextEditor, richLinkHref, documentResourceHtml, documentResourceHref } from '@/core/util'
import { websocket } from '@/core/websocket'
import { AgentAvatar, useAgentStore } from '@/app/agent'
import { memoryService } from '../services/memoryService'
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

interface OwnerChoice {
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

interface OwnerSection {
  value: string
  label: string
  disable: true
  section: true
}

type OwnerSelectOption = OwnerChoice | OwnerSection

interface MemoryRealtimeEvent {
  data: {
    id: string
    owner_agent_id: number | null
    owner_user_id: number | null
    node_kind: MemoryNodeKind
    revision: number
  }
}

type NewKeywordDone = (value?: string, mode?: 'add' | 'add-unique' | 'toggle') => void

const props = withDefaults(defineProps<{
  documentId: string
  agentId: number | null
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
const $q = useQuasar()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const appPermissionsGeneration = ref(0)
const loading = ref(true)
const deleteDialogOpen = ref(false)
const deletingDocument = ref(false)
const refreshing = ref(false)
const currentDocument = ref<MemoryItemDetail | null>(null)
const autosaveState = ref<AutosaveState>('saved')
const editorTitle = ref('')
const editorOwner = ref('')
const editorContent = ref('')
const isDataset = computed(() => currentDocument.value?.document_type === 'dataset')
const validDataset = computed(() => {
  if (!isDataset.value) return true
  try { JSON.parse(editorContent.value); return true } catch { return false }
})
const editorKeywords = ref<string[]>([])
const keywordOptions = ref<string[]>([])
const filteredKeywordOptions = ref<string[]>([])
const ownerOptions = ref<DocumentOwnerOptions>({ agents: [], users: [] })
const filteredOwnerOptions = ref<OwnerSelectOption[]>([])
const attachments = ref<DocumentAttachment[]>([])
const route = useRoute(), router = useRouter()
const richEditor = ref<InstanceType<typeof RichTextEditor>>()
function insertAttachment(attachment: DocumentAttachment): void {
  richEditor.value?.insertResource(documentResourceHtml({ uri: 'document://' + props.documentId + '/attachments/' + attachment.id, name: attachment.name, size: attachment.size_bytes, mediaType: attachment.media_type }))
}
const attachmentPanel = ref<InstanceType<typeof DocumentAttachments>>()
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
  const result = await memoryService.createDocumentLinkCard(documentId, props.agentId, url)
  if (props.documentId !== documentId) throw new Error('Document changed')
  if (result.attachment) onAttachmentAdded(result.attachment)
  return result.html
}
async function uploadDocumentFile(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const documentId = props.documentId
  const attachment = await memoryService.addDocumentAttachment(documentId, props.agentId, file, signal, progress)
  if (props.documentId !== documentId) throw new Error('Document changed')
  onAttachmentAdded(attachment)
  return 'document://' + documentId + '/attachments/' + attachment.id
}
async function exportCurrentBundle(html: string, signal: AbortSignal): Promise<Blob> {
  return memoryService.exportDocumentBundle(props.documentId, props.agentId, html, signal)
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
let loadGeneration = 0
let ownerFilterGeneration = 0
let disposed = false

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
  && (props.agentId === null ? currentUserOwnsDocument.value : selectedAgentOwnsDocument.value),
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
  const label = option.is_current_user ? t('documents.ownerMe') : option.label
  return {
    value: ownerValue(option.kind, option.id),
    label,
    subtitle: option.is_current_user ? option.label : option.subtitle,
    kind: option.kind,
    id: option.id,
    avatarUrl: option.avatar_url,
    searchText: `${label} ${option.label} ${option.subtitle}`.toLocaleLowerCase(locale.value),
  }
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
      avatarUrl: null,
      searchText: '',
    }
  }
  if (document.owner_user_id !== null) {
    return {
      value,
      label: t('documents.ownerUser'),
      subtitle: '',
      kind: 'user',
      id: document.owner_user_id,
      avatarUrl: null,
      searchText: '',
    }
  }
  return null
}

function sectionedOwnerOptions(choices: OwnerChoice[]): OwnerSelectOption[] {
  const agents = choices.filter(choice => choice.kind === 'agent')
  const users = choices.filter(choice => choice.kind === 'user')
  const options: OwnerSelectOption[] = []
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
  const result: Record<number, DocumentShareAccess> = {}
  for (const agent of sharingAgentOptions.value) {
    const grant = document.grants.find(value => value.agent_id === agent.value)
    result[agent.value] = grant ? (grant.can_write ? 'edit' : 'read') : 'none'
  }
  return result
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
    sharing: Object.fromEntries(sharingAgentOptions.value.map(agent => [
      agent.value,
      sharingAccessByAgentId.value[agent.value] ?? 'none',
    ])),
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
  return { ...draft, keywords: [...draft.keywords], sharing: { ...draft.sharing } }
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
  if (event !== 'loaded') pendingExternalRevision = 0
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
  try {
    keywordOptions.value = await memoryService.listDocumentKeywords(props.agentId)
    filteredKeywordOptions.value = keywordOptions.value
  } catch {
    keywordOptions.value = [...(currentDocument.value?.keywords ?? [])]
    filteredKeywordOptions.value = keywordOptions.value
  }
}

async function onSharingChanged(): Promise<void> {
  await mergeLatestDocument(props.documentId)
  scheduleAutosave()
}

async function loadAttachments(): Promise<void> {
  attachmentsLoading.value = true
  try {
    attachments.value = await memoryService.listDocumentAttachments(props.documentId, props.agentId)
  } catch {
    attachments.value = []
  } finally {
    attachmentsLoading.value = false
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

function filterKeywordOptions(value: string, update: (callback: () => void) => void): void {
  update(() => {
    const needle = value.trim().toLocaleLowerCase(locale.value)
    filteredKeywordOptions.value = needle
      ? keywordOptions.value.filter(option => option.toLocaleLowerCase(locale.value).includes(needle))
      : keywordOptions.value
  })
}

function filterOwnerOptions(
  value: string,
  update: (callback: () => void) => void,
  abort: () => void,
): void {
  const query = value.trim()
  const needle = query.toLocaleLowerCase(locale.value)
  const generation = ++ownerFilterGeneration
  if (!needle) {
    update(() => { filteredOwnerOptions.value = sectionedOwnerOptions(ownerChoices.value) })
    return
  }
  void memoryService.listDocumentOwnerOptions(query).then(options => {
    if (generation !== ownerFilterGeneration) return
    const serverChoices = choicesFromOwnerOptions(options)
    const currentUserChoice = ownerChoices.value.find(option => (
      option.kind === 'user'
      && option.label.toLocaleLowerCase(locale.value).includes(needle)
    ))
    const choices = currentUserChoice
      && !serverChoices.some(option => option.value === currentUserChoice.value)
      ? [...serverChoices, currentUserChoice]
      : serverChoices
    update(() => { filteredOwnerOptions.value = sectionedOwnerOptions(choices) })
  }).catch(() => {
    if (generation !== ownerFilterGeneration) return
    abort()
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
  loading.value = true
  try {
    const document = await memoryService.getItem(props.documentId, props.agentId)
    if (generation !== loadGeneration) return
    if (document.node_kind !== 'document') throw new Error('The resource is not a document.')
    await loadOwnerOptions()
    if (generation !== loadGeneration) return
    applyDocument(document, 'loaded')
    await Promise.all([loadKeywords(), loadAttachments()])
  } catch {
    if (generation !== loadGeneration) return
    currentDocument.value = null
    emit('unavailable', props.documentId)
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function loadOwnerOptions(): Promise<void> {
  try {
    ownerOptions.value = await memoryService.listDocumentOwnerOptions()
  } catch {
    ownerOptions.value = {
      agents: [],
      users: [],
    }
  }
  filteredOwnerOptions.value = sectionedOwnerOptions(ownerChoices.value)
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
  if (!editorTitle.value.trim() || !editorOwner.value || !validDataset.value) {
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

async function mergeLatestDocument(documentId: string): Promise<void> {
  const previousBase = lastSavedDraft.value
  if (!previousBase) return
  const local = draftFromEditor()
  const latest = await memoryService.getItem(documentId, props.agentId)
  if (currentDocument.value?.id !== documentId) return
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
  for (const agent of sharingAgentOptions.value) {
    sharing[agent.value] = choose(
      local.sharing[agent.value] ?? 'none',
      previousBase.sharing[agent.value] ?? 'none',
      remote.sharing[agent.value] ?? 'none',
    )
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
  if (!editorTitle.value.trim() || !editorOwner.value || !validDataset.value) {
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
      if (update.payload) update.media_type = isDataset.value ? 'application/json' : 'text/html'
      const updated = await memoryService.updateItem(document.id, props.agentId, update)
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
      const latest = await memoryService.getItem(document.id, props.agentId)
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
    const mustSaveAgain = saveQueued || (autosaveState.value === 'pending' && hasUnsavedChanges.value)
    if (!mustRefreshExternal) pendingExternalRevision = 0
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
  const agentId = props.agentId
  const storageKey = draftKey()
  if (!document || !canDeleteDocument.value || deletingDocument.value) return
  deletingDocument.value = true
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (realtimeTimer) clearTimeout(realtimeTimer)
  try {
    await waitForActiveSave()
    if (disposed || currentDocument.value?.id !== document.id || props.agentId !== agentId || !canDeleteDocument.value) return
    await memoryService.forgetItem(document.id, agentId)
    try { sessionStorage.removeItem(storageKey) } catch { /* Storage may be unavailable. */ }
    if (disposed || currentDocument.value?.id !== document.id || props.agentId !== agentId) return
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
    deletingDocument.value = false
    if (!disposed) scheduleAutosave()
  }
}

async function refreshFromRealtime(): Promise<void> {
  if (deletingDocument.value) return
  const document = currentDocument.value
  if (!document || saveInFlight) return
  if (pendingExternalRevision < document.revision) {
    pendingExternalRevision = 0
    return
  }
  const generation = ++loadGeneration
  refreshing.value = true
  try {
    if (hasUnsavedChanges.value) {
      await mergeLatestDocument(document.id)
      scheduleAutosave(150)
    } else {
      const latest = await memoryService.getItem(document.id, props.agentId)
      if (generation === loadGeneration && currentDocument.value?.id === document.id) {
        applyDocument(latest, 'updated')
        await loadAttachments()
      }
    }
  } catch {
    if (generation !== loadGeneration) return
    currentDocument.value = null
    emit('unavailable', document.id)
  } finally {
    if (generation === loadGeneration) refreshing.value = false
  }
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
    loadGeneration += 1
    currentDocument.value = null
    emit('unavailable', event.id)
    return
  }
  pendingExternalRevision = Math.max(pendingExternalRevision, event.revision)
  if (!saveInFlight) scheduleRealtimeRefresh()
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
  if (!currentDocument.value) { refreshing.value = false; void loadDocument(); return }
  if (!props.editable) refreshing.value = true
  pendingExternalRevision = currentDocument.value.revision + 1
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
  ownerFilterGeneration += 1
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (realtimeTimer) clearTimeout(realtimeTimer)
  websocket.offEvent('memory', 'update', onMemoryRealtime)
  websocket.offEvent('memory', 'delete', onMemoryDelete)
  websocket.offEvent('memory', 'invalidate', onWebsocketConnect)
  websocket.offConnect(onWebsocketConnect)
  preserveDraft()
  if (hasUnsavedChanges.value) void flushAutosave()
})

defineExpose({ flush: flushAutosave })

async function resolveInlineImage(documentId: string, attachmentId: string): Promise<Blob> {
  return memoryService.documentAttachmentBlob(documentId, attachmentId, props.agentId)
}
async function exportCurrentDocumentPdf(html: string, signal: AbortSignal): Promise<Blob> {
  const document = currentDocument.value
  if (!document) throw new Error('Document unavailable')
  return memoryService.exportDocumentPdf(document.id, html, signal)
}
async function uploadInlineImage(file: File, signal: AbortSignal, progress: (value: number) => void): Promise<string> {
  const document = currentDocument.value
  if (!document || isGoalDocument(document)) throw new Error('Images unavailable')
  const attachment = await memoryService.addDocumentAttachment(document.id, props.agentId, file, signal, progress)
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
    lastSavedDraft.value = saved.base
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
.document-editor-toolbar { min-height: 72px; }
.document-editor-live-status { flex: 0 0 auto; padding-left: 12px; }
.document-editor-fields { min-width: 0; }
.document-editor-owner-field :deep(.q-field__native) { flex-wrap: nowrap; }
.owner-selected { min-width: 0; max-width: 100%; }
.owner-section { min-height: 30px; background: rgba(0, 0, 0, 0.035); }
.owner-section :deep(.q-item__label--header) { padding: 0; color: var(--q-primary); font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.document-editor-fields :deep(.q-field--dense .q-field__control) { min-height: 40px; }
.document-editor-fields :deep(.q-field--dense .q-field__marginal) { height: 40px; }
.document-editor-fields :deep(.q-field__bottom) { display: none; }
.document-editor-fields :deep(.q-expansion-item__container > .q-item) { min-height: 48px; }
.document-editor-metadata-cell { display: flex; }
.document-editor-metadata-field { width: 100%; }
.document-editor-metadata-field :deep(.q-field__inner),
.document-editor-metadata-field :deep(.q-field__control) { height: 100%; }
.document-editor-keywords-field :deep(.q-field__native) { align-content: flex-start; align-items: flex-start; }
.document-editor-uri-badge { max-width: min(100%, 360px); padding: 4px 7px; font-weight: 400; }
.document-editor-uri-badge:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 2px; }
.document-editor-revision-button { min-height: 24px; padding: 1px 5px; font-size: inherit; }
.document-editor-sharing-card { min-height: 40px; }
.document-editor-sharing-row { min-width: 0; gap: 8px; }
.document-editor-sharing-label { gap: 5px; flex: 0 0 auto; }
.document-editor-sharing-badges { min-width: 0; flex: 1 1 auto; gap: 4px; }
.document-editor-sharing-badges :deep(.q-chip) { margin: 0; }
.document-editor-sharing-menu { width: min(340px, calc(100vw - 32px)); }
.document-editor-sharing-options { max-height: 260px; overflow-y: auto; }
@media (max-width: 599.98px) {
  .document-editor-toolbar { align-items: flex-start; flex-wrap: wrap; padding-top: 10px; padding-bottom: 10px; }
  .document-editor-live-status { width: 100%; align-items: flex-start; padding-left: 40px; }
  .document-editor-sharing-row { align-items: flex-start; }
  .document-editor-sharing-label { padding-top: 5px; }
}
</style>
