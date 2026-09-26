<template>
  <section class="conversation-documents-panel">
    <header v-if="canRead" class="conversation-documents-toolbar row items-center q-px-sm q-py-xs">
      <span class="text-caption text-weight-medium">{{ t('chat.workingDocuments') }}</span>
      <q-space />
      <q-btn
        v-if="documentEditable"
        flat round dense color="primary" icon="add"
        :aria-label="t('chat.createDocument')"
        @click="openCreateDocument"
      >
        <q-tooltip>{{ t('chat.createDocument') }}</q-tooltip>
      </q-btn>
    </header>
    <div v-if="!canRead" class="conversation-work-state text-grey-7">
      <q-icon name="lock" size="28px" />
      <span>{{ t('chat.documentsUnavailable') }}</span>
    </div>
    <div v-else-if="loading && !documents.length" class="conversation-work-state text-grey-7">
      <q-spinner color="primary" size="28px" />
    </div>
    <div v-else-if="error && !documents.length" class="conversation-work-state text-negative">
      <q-icon name="warning" size="28px" />
      <span>{{ error }}</span>
      <q-btn flat dense color="negative" :label="t('chat.retryDocuments')" @click="load(true)" />
    </div>
    <div v-else-if="!documents.length" class="conversation-work-state text-grey-7">
      <q-icon name="description" size="28px" />
      <span>{{ t('chat.noWorkingDocuments') }}</span>
    </div>
    <q-list ref="documentList" v-else separator class="conversation-work-list" @scroll.passive="onScroll">
      <q-item
        v-for="document in documents"
        :key="document.id"
        class="conversation-document"
        clickable
        v-ripple
        :active="document.id === activeDocumentId"
        active-class="conversation-document--selected"
        :aria-current="document.id === activeDocumentId ? 'true' : undefined"
        :aria-label="t('chat.openDocument', { label: documentLabel(document) })"
        @click="openDocument(document)"
      >
        <q-item-section avatar class="conversation-document-preview">
          <span class="conversation-document-thumbnail">
            <WorkingDocumentThumbnail fill :document-id="document.id" :revision="document.revision" :updated-at="document.updated_at" :agent-id="documentAgentId" />
          </span>
        </q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-medium"><DocumentIcon readonly :document-id="document.id" :title="documentLabel(document)" /> {{ documentLabel(document) }}</q-item-label>
          <q-item-label caption>
            <span v-if="document.revision">{{ t('chat.documentRevision', { revision: document.revision }) }}</span>
            <span v-if="document.updated_at"> · {{ formatDate(document.updated_at) }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-btn
            flat round dense icon="open_in_new"
            :aria-label="t('chat.openDocumentInDialog', { label: documentLabel(document) })"
            @click.stop="openDocumentInDialog(document)"
          >
            <q-tooltip>{{ t('chat.openDocumentInDialog', { label: documentLabel(document) }) }}</q-tooltip>
          </q-btn>
        </q-item-section>
      </q-item>
      <div v-if="loadingMore" class="conversation-work-loader"><q-spinner color="primary" size="20px" /></div>
      <div v-if="error && documents.length" class="conversation-work-inline-error text-negative"><q-icon name="warning" size="14px" /> {{ error }}</div>
    </q-list>

    <ConversationDocumentDialog
      v-model="dialogOpen"
      :document-id="selectedReference?.id ?? null"
      :agent-id="documentAgentId"
      :title="selectedTitle"
      :editable="documentEditable"
      @changed="onDocumentChanged"
      @unavailable="onDocumentUnavailable"
    />

    <q-dialog v-model="createOpen">
      <q-card class="conversation-document-create-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="note_add" size="24px" class="q-mr-sm" />
          <div class="text-h6">{{ t('chat.createDocument') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="createTitle"
            outlined autofocus
            :label="t('chat.documentTitle')"
            :rules="[value => Boolean(value.trim()) || t('chat.documentTitleRequired')]"
            @keyup.enter="createDocument"
          />
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat no-caps :label="t('common.cancel')" />
          <q-btn
            color="primary" unelevated no-caps icon="add"
            :loading="creating"
            :disable="!createTitle.trim()"
            :label="t('chat.createDocument')"
            @click="createDocument"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon, WorkingDocumentThumbnail } from '@/core/util'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import type { WorkingDocumentSnapshot } from '@/core/util'
import { websocket } from '@/core/websocket'
import { chatService } from '../services/chatService'
import type { ConversationDocumentReference } from '../types'
import ConversationDocumentDialog from './ConversationDocumentDialog.vue'

const props = withDefaults(defineProps<{
  embedded?: boolean
  displayedDocumentId?: string | null
  roomId: string
  fromMessageId?: string | null
  conversationAgentId?: number | null
  viewerAgentId?: number | null
  canRead?: boolean
  canEdit?: boolean
}>(), {
  fromMessageId: null,
  conversationAgentId: null,
  viewerAgentId: null,
  canRead: false,
  canEdit: false,
})

const emit = defineEmits<{ open: [document: ConversationDocumentReference] }>()

const { t, locale } = useI18n()
const $q = useQuasar()
const documents = ref<ConversationDocumentReference[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const dialogDocumentId = ref<string | null>(null)
const activeDocumentId = computed(() => dialogOpen.value ? dialogDocumentId.value : props.displayedDocumentId)
const selectedReference = ref<ConversationDocumentReference | null>(null)
const selectedDocumentTitle = ref('')
const createOpen = ref(false)
const creating = ref(false)
const createTitle = ref('')
let requestSequence = 0
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let scrollFrame: number | null = null
let scrollResizeObserver: ResizeObserver | null = null
let pendingBottomScroll = false
let subscribed = false
const DOCUMENT_PAGE_SIZE = 50
const UUID_LABEL_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const hasMore = computed(() => documents.value.length < total.value)

const documentAgentId = computed(() => props.viewerAgentId ?? props.conversationAgentId)
const documentEditable = computed(() => Boolean(
  props.canEdit
  && props.viewerAgentId === null
  && props.conversationAgentId !== null
))
const selectedTitle = computed(() => (
  selectedDocumentTitle.value
  || (selectedReference.value ? documentLabel(selectedReference.value) : t('chat.workingDocument'))
))
const documentList = useTemplateRef<{ $el: HTMLElement }>('documentList')

function documentLabel(document: ConversationDocumentReference): string {
  const label = document.label.trim()
  if (!label || label === document.id || label === document.uri || UUID_LABEL_PATTERN.test(label)) {
    return t('chat.workingDocument')
  }
  return label
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

async function load(reset = true, scrollAfterLoad = false): Promise<void> {
  const sequence = ++requestSequence
  if (!props.canRead || !props.fromMessageId) {
    documents.value = []
    total.value = 0
    page.value = 1
    error.value = ''
    return
  }
  if (reset) loadingMore.value = false
  loading.value = true
  try {
    const knownIds = new Set(documents.value.map(document => document.id))
    const requestedPageSize = reset
      ? DOCUMENT_PAGE_SIZE
      : Math.max(DOCUMENT_PAGE_SIZE, page.value * DOCUMENT_PAGE_SIZE)
    const result = await chatService.documents(
      props.roomId,
      props.fromMessageId,
      1,
      requestedPageSize,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    documents.value = result.items
    total.value = result.total
    if (reset) page.value = 1
    error.value = ''
    if (scrollAfterLoad || result.items.some(document => !knownIds.has(document.id))) {
      scrollDocumentsToBottom()
    }
  } catch (caught) {
    if (sequence === requestSequence) {
      error.value = apiErrorDetail(caught) ?? t('chat.documentsLoadError')
    }
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (loading.value || loadingMore.value || !hasMore.value || !props.fromMessageId) return
  const sequence = requestSequence
  loadingMore.value = true
  try {
    const nextPage = page.value + 1
    const result = await chatService.documents(
      props.roomId,
      props.fromMessageId,
      nextPage,
      DOCUMENT_PAGE_SIZE,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    const knownIds = new Set(documents.value.map(document => document.id))
    documents.value = [...documents.value, ...result.items.filter(document => !knownIds.has(document.id))]
    total.value = result.total
    page.value = nextPage
    error.value = ''
  } catch (caught) {
    if (sequence === requestSequence) error.value = apiErrorDetail(caught) ?? t('chat.documentsLoadError')
  } finally {
    if (sequence === requestSequence) loadingMore.value = false
  }
}

function onScroll(event: Event): void {
  const target = event.currentTarget as HTMLElement
  if (target.scrollHeight - target.scrollTop - target.clientHeight <= 80) void loadMore()
}

function disconnectScrollResizeObserver(): void {
  scrollResizeObserver?.disconnect()
  scrollResizeObserver = null
}

function observeScrollResize(): void {
  if (scrollResizeObserver) return
  const target = documentList.value?.$el
  if (!target) return
  scrollResizeObserver = new ResizeObserver(() => {
    if (pendingBottomScroll) scrollDocumentsToBottom()
  })
  scrollResizeObserver.observe(target)
}

function scrollDocumentsToBottom(): void {
  pendingBottomScroll = true
  void nextTick(() => {
    observeScrollResize()
    if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
    scrollFrame = window.requestAnimationFrame(() => {
      const target = documentList.value?.$el
      if (!target || target.clientHeight === 0) {
        scrollFrame = null
        return
      }
      target.scrollTop = target.scrollHeight
      scrollFrame = window.requestAnimationFrame(() => {
        const currentTarget = documentList.value?.$el
        if (currentTarget) currentTarget.scrollTop = currentTarget.scrollHeight
        pendingBottomScroll = false
        disconnectScrollResizeObserver()
        scrollFrame = null
      })
    })
  })
}

defineExpose({ scrollToBottom: scrollDocumentsToBottom })

function scheduleRefresh(): void {
  if (!props.canRead) return
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { void load(false) }, 250)
}

function subscribe(): void {
  if (subscribed) return
  websocket.createWebsocket()
  websocket.onEvent('memory', 'create', scheduleRefresh)
  websocket.onEvent('memory', 'update', scheduleRefresh)
  websocket.onEvent('memory', 'delete', scheduleRefresh)
  websocket.onConnect(scheduleRefresh)
  subscribed = true
}

function unsubscribe(): void {
  if (!subscribed) return
  websocket.offEvent('memory', 'create', scheduleRefresh)
  websocket.offEvent('memory', 'update', scheduleRefresh)
  websocket.offEvent('memory', 'delete', scheduleRefresh)
  websocket.offConnect(scheduleRefresh)
  subscribed = false
}

function openDocument(reference: ConversationDocumentReference): void {
  if (props.embedded) {
    emit('open', reference)
    return
  }
  openDocumentInDialog(reference)
}

function openDocumentInDialog(reference: ConversationDocumentReference): void {
  dialogDocumentId.value = null
  selectedReference.value = reference
  selectedDocumentTitle.value = documentLabel(reference)
  dialogOpen.value = true
}

function openCreateDocument(): void {
  createTitle.value = ''
  createOpen.value = true
}

async function createDocument(): Promise<void> {
  const title = createTitle.value.trim()
  if (!title || creating.value || !documentEditable.value) return
  creating.value = true
  const roomId = props.roomId
  const viewerAgentId = props.viewerAgentId
  try {
    const created = await chatService.createDocument(roomId, title)
    if (props.roomId !== roomId || props.viewerAgentId !== viewerAgentId || !props.canRead) return
    documents.value = [created, ...documents.value.filter(item => item.id !== created.id)]
    total.value += 1
    scrollDocumentsToBottom()
    if (createOpen.value) openDocument(created)
    createOpen.value = false
    $q.notify({ type: 'positive', message: t('chat.documentCreated') })
  } catch (caught) {
    $q.notify({
      type: 'negative',
      message: apiErrorDetail(caught) ?? t('chat.documentCreateError'),
    })
  } finally {
    creating.value = false
  }
}

function onDocumentChanged(document: WorkingDocumentSnapshot): void {
  if (selectedReference.value?.id !== document.id) return
  dialogDocumentId.value = document.id
  selectedDocumentTitle.value = document.title
  documents.value = documents.value.map(item => item.id === document.id
      ? { ...item, label: document.title, revision: document.revision, updated_at: document.updated_at }
      : item)
}

function onDocumentUnavailable(documentId: string): void {
  if (selectedReference.value?.id !== documentId) return
  dialogDocumentId.value = null
  void load(true)
}

watch(
  () => [props.roomId, props.fromMessageId, props.viewerAgentId, props.canRead] as const,
  ([, , , canRead]) => {
    createOpen.value = false
    dialogOpen.value = false
    selectedReference.value = null
    selectedDocumentTitle.value = ''
    if (canRead) subscribe()
    else unsubscribe()
    page.value = 1
    void load(true, true)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  requestSequence += 1
  if (refreshTimer) window.clearTimeout(refreshTimer)
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  disconnectScrollResizeObserver()
  unsubscribe()
})
</script>

<style scoped>
.conversation-documents-panel { display: flex; height: 100%; min-width: 0; min-height: 0; flex-direction: column; color: var(--chat-text, #252b36); background: var(--chat-surface, #fff); }
.conversation-documents-toolbar { min-height: 36px; flex: 0 0 auto; border-bottom: 1px solid var(--chat-border, rgba(0, 0, 0, .12)); }
.conversation-work-state { display: flex; min-height: 120px; align-items: center; justify-content: center; flex-direction: column; gap: 8px; padding: 18px; text-align: center; font-size: .78rem; }
.conversation-work-list { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
.conversation-document { min-height: 78px; padding: 1px 16px 1px 4px; }
.conversation-document-preview { padding-right: 8px; }
.conversation-document-thumbnail { position: relative; width: 108px; height: 76px; }
.conversation-document--selected { color: inherit; background: var(--solaire-blue-light); box-shadow: inset 3px 0 var(--solaire-blue-accent); }
:global(.body--dark) .conversation-document--selected { background: var(--solaire-blue-dark); }
.conversation-work-loader { display: flex; min-height: 36px; align-items: center; justify-content: center; }
.conversation-work-inline-error { padding: 7px 10px; font-size: .75rem; }
.conversation-document-create-dialog { width: min(520px, calc(100vw - 32px)); }
</style>
