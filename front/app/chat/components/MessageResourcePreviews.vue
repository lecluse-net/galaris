<template>
  <div v-if="loading" class="resource-preview-loading" aria-live="polite">
    <q-skeleton type="rect" height="86px" animation="fade" />
  </div>
  <div v-else-if="previews.length" class="resource-preview-list resource-preview-grid">
    <ResourcePreviewBlock
      v-for="preview in previews"
      :key="preview.uri"
      placement="below-page"
      :title="preview.title || (preview.deleted ? t('chat.resourcePreview.kinds.document') : '')"
      :disabled="preview.deleted"
      :description="preview.kind === 'document' ? '' : preview.description"
      :subtitle="preview.deleted ? t('chat.resourcePreview.documentDeleted') : [kindLabel(preview.kind), preview.subtitle].filter(Boolean).join(' · ')"
      :uri="preview.uri"
      :image="imageUrls[preview.uri]"
      :icon="kindIcon(preview.kind)"
      :href="preview.open_mode === 'external' ? preview.external_url ?? undefined : undefined"
      :open-label="preview.open_mode === 'external'
        ? t('chat.resourcePreview.openExternal')
        : t('chat.resourcePreview.open', { title: preview.title })"
      @open="handlePreviewClick($event, preview)"
    >
      <template v-if="preview.deleted" #preview>
        <q-icon name="delete_outline" size="32px" style="color: var(--solaire-gray-accent)" />
      </template>
      <template v-else-if="documentId(preview) && canReadDocuments" #preview>
        <WorkingDocumentThumbnail
          :document-id="documentId(preview)!"
          :revision="typeof preview.metadata.revision === 'number' ? preview.metadata.revision : null"
          :updated-at="typeof preview.metadata.updated_at === 'string' ? preview.metadata.updated_at : null"
          :agent-id="documentAgentId"
          fill
        />
      </template>
      <template v-else-if="resourceKind(preview) === 'model3d'" #preview>
        <Model3dThumbnail :source="modelSource(preview)" />
      </template>
      <template v-if="documentId(preview) && !preview.deleted" #title-icon>
        <DocumentIcon :document-id="documentId(preview)!" :title="preview.title" />
      </template>
      <template v-if="!preview.deleted" #actions>
        <q-btn
          v-if="canCoedit(preview)"
          flat
          round
          dense
          size="sm"
          icon="vertical_split"
          class="resource-preview-action"
          :aria-label="t('chat.resourcePreview.coedit')"
          @click="openCoediting(preview)"
        >
          <q-tooltip>{{ t('chat.resourcePreview.coedit') }}</q-tooltip>
        </q-btn>
        <q-btn
          v-if="canOpenStandalone(preview)"
          flat
          round
          dense
          size="sm"
          icon="open_in_new"
          class="resource-preview-action"
          :href="preview.external_url ?? undefined"
          target="_blank"
          rel="noopener noreferrer"
          :loading="openingResourceUri === preview.uri"
          :aria-label="t('chat.resourcePreview.openNewTab')"
          @click="openStandalone($event, preview)"
        >
          <q-tooltip>{{ t('chat.resourcePreview.openNewTab') }}</q-tooltip>
        </q-btn>
        <q-btn
          v-if="preview.download_available"
          flat
          round
          dense
          size="sm"
          icon="download"
          class="resource-preview-action"
          :loading="downloadingUri === preview.uri"
          :aria-label="t('chat.resourcePreview.download')"
          @click="downloadPreview(preview)"
        >
          <q-tooltip>{{ t('chat.resourcePreview.download') }}</q-tooltip>
        </q-btn>
        <q-btn
          v-if="preview.open_mode !== 'external'"
          flat
          round
          dense
          size="sm"
          :icon="preview.kind === 'document' ? 'edit_note' : 'open_in_full'"
          class="resource-preview-action"
          :aria-label="t('chat.resourcePreview.open', { title: preview.title })"
          @click="openPreview(preview)"
        >
          <q-tooltip>{{ t('chat.resourcePreview.open', { title: preview.title }) }}</q-tooltip>
        </q-btn>
      </template>
    </ResourcePreviewBlock>
  </div>

  <FullscreenPreview
    v-model="dialogOpen"
    :immersive="immersivePreview"
    :interactive="inlineResourceKind === 'html' || inlineResourceKind === 'model3d' || inlineResourceKind === 'markdown' || inlineResourceKind === 'text'"
    :spatial="inlineResourceKind === 'model3d'"
    :viewer-label="t('chat.resourcePreview.viewerLabel')"
  >
    <template #actions>
          <q-btn
            v-if="selected?.download_available"
            flat
            round
            dense
            icon="download"
            color="white"
            :loading="downloadingResource"
            :aria-label="t('chat.resourcePreview.download')"
            @click="downloadSelected"
          >
            <q-tooltip>{{ t('chat.resourcePreview.download') }}</q-tooltip>
          </q-btn>
    </template>
    <template v-if="selected" #default="{ fit }">
        <Model3dViewer v-if="inlineResourceKind === 'model3d'" :source="modelSource(selected)" />
        <div
          v-else-if="selected.kind === 'youtube' && selected.embed_url"
          class="resource-preview-video-frame"
          :class="{ 'resource-preview-content--fit': fit }"
        >
          <iframe
            :src="selected.embed_url"
            :title="selected.title"
            allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen
            sandbox="allow-scripts allow-same-origin allow-presentation"
          />
        </div>
        <img
          v-else-if="isInlineImagePreview(selected) && imageUrls[selected.uri]"
          :src="imageUrls[selected.uri]"
          :alt="selected.title"
          class="resource-preview-dialog-image"
          :class="{ 'resource-preview-content--fit': fit }"
        />
        <div
          v-else-if="selected.download_available && inlineResourceKind"
          class="resource-preview-file"
        >
          <div
            v-if="resourceLoading"
            class="resource-preview-file-loading"
            aria-live="polite"
          >
            <q-spinner color="primary" size="32px" />
            <span>{{ t('chat.resourcePreview.loadingFile') }}</span>
          </div>
          <q-banner
            v-else-if="resourceLoadError"
            dense
            rounded
            class="resource-preview-file-error"
          >
            {{ t('chat.resourcePreview.fileLoadError') }}
            <template #action>
              <q-btn
                flat
                dense
                no-caps
                :label="t('chat.resourcePreview.retryFile')"
                @click="retryResource"
              />
            </template>
          </q-banner>
          <TextResourcePreview
            v-else-if="resourceUrl && (inlineResourceKind === 'markdown' || inlineResourceKind === 'text')"
            :content="resourceText"
            :title="selected.title"
            :fit="fit"
            :markdown="inlineResourceKind === 'markdown'"
            :media-type="selected.media_type"
          />
          <img
            v-else-if="resourceUrl && inlineResourceKind === 'image'"
            :src="resourceUrl"
            :alt="selected.title"
            class="resource-preview-dialog-image"
            :class="{ 'resource-preview-content--fit': fit }"
          />
          <iframe
            v-else-if="resourceUrl && inlineResourceKind === 'html'"
            :src="resourceUrl"
            :title="selected.title"
            class="resource-preview-file-frame"
            :class="{ 'resource-preview-content--fit': fit }"
            sandbox="allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads allow-presentation"
            referrerpolicy="no-referrer"
          />
          <iframe
            v-else-if="resourceUrl && inlineResourceKind === 'pdf'"
            :src="resourceUrl"
            :title="selected.title"
            class="resource-preview-file-frame"
            :class="{ 'resource-preview-content--fit': fit }"
          />
          <audio
            v-else-if="resourceUrl && inlineResourceKind === 'audio'"
            :src="resourceUrl"
            controls
            class="resource-preview-file-audio"
          />
          <video
            v-else-if="resourceUrl && inlineResourceKind === 'video'"
            :src="resourceUrl"
            controls
            class="resource-preview-file-video"
            :class="{ 'resource-preview-content--fit': fit }"
          />
        </div>

        <template v-if="selected.kind !== 'document' && !immersivePreview">
          <RichText v-if="selected.content && selected.content_format === 'html'" :content="selected.content" />
          <Markdown
            v-else-if="selected.content && selected.content_format === 'markdown'"
            :content="selected.content"
            class="resource-preview-document"
            :class="{ 'resource-preview-content--fit': fit }"
          />
          <CodeEditor
            v-else-if="selected.content && selected.content_format === 'json'"
            :model-value="prettyJson(selected.content)"
            language="json"
            readonly
            :show-error="false"
            :visible-lines="18"
            class="resource-preview-json"
            :class="{ 'resource-preview-content--fit': fit }"
          />
          <pre
            v-else-if="selected.content && selected.content_format === 'text'"
            class="resource-preview-text"
            :class="{ 'resource-preview-content--fit': fit }"
          >{{ selected.content }}</pre>
          <div
            v-else-if="selected.description"
            class="resource-preview-dialog-description"
            :class="{ 'resource-preview-content--fit': fit }"
          >
            {{ selected.description }}
          </div>

          <q-banner
            v-if="selected.download_available && !inlineResourceKind && selected.kind === 'file'"
            dense
            rounded
            class="resource-preview-file-error"
          >
            {{ t('chat.resourcePreview.noInlinePreview') }}
          </q-banner>

          <q-banner v-if="selected.truncated" dense rounded class="resource-preview-truncated">
            {{ t('chat.resourcePreview.truncated') }}
          </q-banner>
        </template>
    </template>
  </FullscreenPreview>

  <ConversationDocumentDialog
    v-model="documentDialogOpen"
    :document-id="selectedDocumentId"
    :agent-id="documentAgentId"
    :title="selected?.title ?? t('chat.workingDocument')"
    :editable="canEditDocuments && viewerAgentId === null"
    @changed="syncPreviewFromDocument"
    @unavailable="onSelectedDocumentUnavailable"
  />
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon, WorkingDocumentThumbnail } from '@/core/util'
import { RichText, richTextExcerpt } from '@/core/util'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import {
  browserResourceKind,
  CodeEditor,
  FullscreenPreview,
  ResourcePreviewBlock,
  Model3dThumbnail,
  Model3dViewer,
  isolatedBrowserResourceUrl,
  Markdown,
  TextResourcePreview,
  saveBlobAsResource,
} from '@/core/util'
import type { BrowserResourceKind, Model3dSource, WorkingDocumentSnapshot } from '@/core/util'
import { websocket } from '@/core/websocket'
import { useAuthStore } from '@/core/user'
import type { ConversationDocumentReference, MessageResourcePreview, MessageResourcePreviewKind } from '../types'
import { chatService } from '../services/chatService'
import ConversationDocumentDialog from './ConversationDocumentDialog.vue'

const props = withDefaults(defineProps<{
  roomId: string
  messageId: string
  conversationAgentId?: number | null
  viewerAgentId?: number | null
  canReadDocuments?: boolean
  canEditDocuments?: boolean
}>(), {
  conversationAgentId: null,
  viewerAgentId: null,
  canReadDocuments: false,
  canEditDocuments: false,
})

const emit = defineEmits<{
  openDocument: [document: Pick<ConversationDocumentReference, 'id' | 'label'>]
}>()

interface MemoryRealtimeEvent {
  data?: {
    id?: string
    node_kind?: string
    revision?: number
  }
}

const { t } = useI18n()
const $q = useQuasar()
const authStore = useAuthStore()
const loading = ref(false)
const previews = ref<MessageResourcePreview[]>([])
const selected = ref<MessageResourcePreview | null>(null)
const dialogOpen = ref(false)
const documentDialogOpen = ref(false)
const imageUrls = reactive<Record<string, string>>({})
const resourceUrl = ref<string | null>(null)
const resourceBlob = ref<Blob | null>(null)
const resourceText = ref('')
const resourceUri = ref<string | null>(null)
const resourceLoading = ref(false)
const resourceLoadError = ref(false)
const downloadingResource = ref(false)
const downloadingUri = ref<string | null>(null)
const openingResourceUri = ref<string | null>(null)
let generation = 0
let resourceGeneration = 0
let realtimeTimer: ReturnType<typeof setTimeout> | undefined

const iconByKind: Record<MessageResourcePreviewKind, string> = {
  document: 'description',
  memory: 'psychology',
  task: 'task_alt',
  text: 'forum',
  voice: 'record_voice_over',
  goal: 'flag',
  goal_cycle: 'autorenew',
  process: 'account_tree',
  skill: 'auto_awesome',
  file: 'insert_drive_file',
  resource: 'data_object',
  web: 'language',
  youtube: 'smart_display',
}

function kindIcon(kind: MessageResourcePreviewKind): string {
  return iconByKind[kind]
}

function kindLabel(kind: MessageResourcePreviewKind): string {
  return t(`chat.resourcePreview.kinds.${kind}`)
}

const documentAgentId = computed(() => props.viewerAgentId ?? props.conversationAgentId)

function resourceKind(preview: MessageResourcePreview | null): BrowserResourceKind | null {
  if (!preview?.download_available) return null
  return browserResourceKind(preview.media_type, preview.title)
}

function modelSource(preview: MessageResourcePreview): Model3dSource {
  const roomId = props.roomId
  const messageId = props.messageId
  const viewerAgentId = props.viewerAgentId
  return {
    key: `${roomId}:${messageId}:${viewerAgentId ?? 'user'}:${preview.uri}:${String(preview.metadata.revision ?? '')}`,
    name: preview.title,
    mediaType: preview.media_type,
    load: () => chatService.messagePreviewContentBlob(roomId, messageId, preview.uri, viewerAgentId),
  }
}

function isInlineImagePreview(preview: MessageResourcePreview): boolean {
  return resourceKind(preview) === 'image'
}

const inlineResourceKind = computed(() => resourceKind(selected.value))
const immersivePreview = computed(() => Boolean(
  selected.value
  && (
    selected.value.kind === 'youtube'
    || imageUrls[selected.value.uri]
    || inlineResourceKind.value
  ),
))

function clearImages(): void {
  for (const url of Object.values(imageUrls)) URL.revokeObjectURL(url)
  for (const key of Object.keys(imageUrls)) delete imageUrls[key]
}

function resetResource(): void {
  resourceGeneration += 1
  if (resourceUrl.value) URL.revokeObjectURL(resourceUrl.value)
  resourceUrl.value = null
  resourceBlob.value = null
  resourceText.value = ''
  resourceUri.value = null
  resourceLoading.value = false
  resourceLoadError.value = false
}

function documentId(preview: MessageResourcePreview | null): string | null {
  if (preview?.kind !== 'document') return null
  return /^document:\/\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i
    .exec(preview.uri)?.[1] ?? null
}

const selectedDocumentId = computed(() => documentId(selected.value))

function canCoedit(preview: MessageResourcePreview): boolean {
  return !preview.deleted && !$q.screen.lt.md && props.canReadDocuments && props.canEditDocuments && props.viewerAgentId === null && documentId(preview) !== null
}

function openCoediting(preview: MessageResourcePreview): void {
  const id = documentId(preview)
  if (!id || !canCoedit(preview)) return
  emit('openDocument', { id, label: preview.title })
}

function documentPreviewIds(): Set<string> {
  return new Set(previews.value.map(documentId).filter((id): id is string => id !== null))
}

async function load(resetDialog = true): Promise<void> {
  const currentGeneration = ++generation
  const selectedUri = resetDialog ? null : selected.value?.uri ?? null
  if (resetDialog) {
    loading.value = true
    previews.value = []
    selected.value = null
    dialogOpen.value = false
    documentDialogOpen.value = false
    resetResource()
  }
  clearImages()
  try {
    const loaded = await chatService.messagePreviews(
      props.roomId,
      props.messageId,
      props.viewerAgentId,
    )
    if (currentGeneration !== generation) return
    previews.value = loaded
    if (selectedUri) {
      const refreshedSelection = loaded.find(item => item.uri === selectedUri) ?? null
      selected.value = refreshedSelection
      if (!refreshedSelection || refreshedSelection.deleted) {
        dialogOpen.value = false
        documentDialogOpen.value = false
        resetResource()
      }
    }
    for (const item of loaded.filter(
      candidate => resourceKind(candidate) !== 'model3d' && (candidate.image_available || isInlineImagePreview(candidate)),
    )) {
      void loadPreviewImage(item, currentGeneration)
    }
  } catch {
    // A message remains readable even when none of its linked resources can be previewed.
  } finally {
    if (currentGeneration === generation) loading.value = false
  }
}

const thumbnailRetryDelays = [0, 1_000, 2_000, 4_000, 8_000, 16_000, 30_000]

function waitForThumbnail(delay: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, delay))
}

async function loadPreviewImage(
  preview: MessageResourcePreview,
  currentGeneration: number,
): Promise<void> {
  const directImage = isInlineImagePreview(preview)
  const retryDelays = directImage ? [0] : thumbnailRetryDelays
  for (const delay of retryDelays) {
    if (delay > 0) await waitForThumbnail(delay)
    if (currentGeneration !== generation) return
    try {
      const blob = directImage
        ? await chatService.messagePreviewContentBlob(
            props.roomId,
            props.messageId,
            preview.uri,
            props.viewerAgentId,
          )
        : await chatService.messagePreviewImageBlob(
            props.roomId,
            props.messageId,
            preview.uri,
            props.viewerAgentId,
          )
      if (currentGeneration !== generation) return
      if (blob.type && !blob.type.toLowerCase().startsWith('image/')) return
      const previousUrl = imageUrls[preview.uri]
      if (previousUrl) URL.revokeObjectURL(previousUrl)
      imageUrls[preview.uri] = URL.createObjectURL(blob)
      if (preview.open_mode === 'external' && !preview.description) {
        // The capture may have supplied metadata unavailable to the initial fetch.
        void chatService.messagePreviews(props.roomId, props.messageId, props.viewerAgentId).then(updated => {
          if (currentGeneration !== generation) return
          const enriched = updated.find(item => item.uri === preview.uri)
          if (enriched) previews.value = previews.value.map(item => item.uri === preview.uri ? enriched : item)
        }).catch(() => undefined)
      }
      return
    } catch {
      // Generated HTML thumbnails may still be running in the isolated browser.
    }
  }
}

function handlePreviewClick(event: MouseEvent, preview: MessageResourcePreview): void {
  if (preview.open_mode === 'external') return
  event.preventDefault()
  if (authStore.user?.document_open_mode !== 'dialog' && canCoedit(preview)) {
    openCoediting(preview)
    return
  }
  openPreview(preview)
}

function openPreview(preview: MessageResourcePreview): void {
  if (preview.deleted) return
  resetResource()
  selected.value = preview
  if (preview.kind === 'document') {
    dialogOpen.value = false
    documentDialogOpen.value = true
    return
  }
  documentDialogOpen.value = false
  dialogOpen.value = true
  if (resourceKind(preview) && !isInlineImagePreview(preview) && resourceKind(preview) !== 'model3d') void ensureResourceBlob()
}

function canOpenStandalone(preview: MessageResourcePreview): boolean {
  return Boolean(
    preview.external_url
    || (preview.download_available && !['markdown', 'text'].includes(resourceKind(preview) ?? '') && resourceKind(preview)),
  )
}


async function fetchResourceBlob(preview: MessageResourcePreview): Promise<Blob> {
  return chatService.messagePreviewContentBlob(
    props.roomId,
    props.messageId,
    preview.uri,
    props.viewerAgentId,
  )
}

async function openStandalone(event: Event, preview: MessageResourcePreview): Promise<void> {
  if (preview.external_url) return
  event.preventDefault()
  if (!preview.download_available || openingResourceUri.value) return
  const tab = window.open('about:blank', '_blank')
  if (!tab) {
    $q.notify({ type: 'negative', message: t('chat.resourcePreview.openNewTabError') })
    return
  }
  tab.opener = null
  openingResourceUri.value = preview.uri
  try {
    const blob = await fetchResourceBlob(preview)
    const url = resourceKind(preview) === 'html'
      ? await chatService.standaloneHtmlPreview(blob, preview.title)
      : URL.createObjectURL(blob)
    if (tab.closed) {
      if (url.startsWith('blob:')) URL.revokeObjectURL(url)
      return
    }
    tab.location.replace(url)
  } catch {
    tab.close()
    $q.notify({ type: 'negative', message: t('chat.resourcePreview.openNewTabError') })
  } finally {
    if (openingResourceUri.value === preview.uri) openingResourceUri.value = null
  }
}

async function downloadPreview(preview: MessageResourcePreview): Promise<void> {
  if (!preview.download_available || downloadingUri.value) return
  downloadingUri.value = preview.uri
  try {
    saveBlobAsResource(await fetchResourceBlob(preview), preview.title)
  } catch {
    $q.notify({ type: 'negative', message: t('chat.resourcePreview.downloadError') })
  } finally {
    if (downloadingUri.value === preview.uri) downloadingUri.value = null
  }
}

async function downloadSelected(): Promise<void> {
  const preview = selected.value
  if (!preview?.download_available || downloadingResource.value) return
  downloadingResource.value = true
  try {
    const blob = await ensureResourceBlob()
    if (!blob) throw new Error('Resource unavailable')
    saveBlobAsResource(blob, preview.title)
  } catch {
    $q.notify({ type: 'negative', message: t('chat.resourcePreview.downloadError') })
  } finally {
    downloadingResource.value = false
  }
}

async function ensureResourceBlob(force = false): Promise<Blob | null> {
  const preview = selected.value
  if (!preview?.download_available) return null
  if (!force && resourceUri.value === preview.uri && resourceBlob.value) {
    return resourceBlob.value
  }
  const currentGeneration = ++resourceGeneration
  resourceLoading.value = true
  resourceLoadError.value = false
  try {
    const blob = await chatService.messagePreviewContentBlob(
      props.roomId,
      props.messageId,
      preview.uri,
      props.viewerAgentId,
    )
    if (currentGeneration !== resourceGeneration || selected.value?.uri !== preview.uri) return null
    const text = ['markdown', 'text'].includes(resourceKind(preview) ?? '') ? await blob.text() : ''
    const objectUrl = resourceKind(preview) === 'html'
      ? await chatService.standaloneHtmlPreview(blob, preview.title)
      : await isolatedBrowserResourceUrl(blob, preview.media_type, preview.title)
    if (currentGeneration !== resourceGeneration || selected.value?.uri !== preview.uri) {
      URL.revokeObjectURL(objectUrl)
      return null
    }
    if (resourceUrl.value) URL.revokeObjectURL(resourceUrl.value)
    resourceBlob.value = blob
    resourceText.value = text
    resourceUri.value = preview.uri
    resourceUrl.value = objectUrl
    return blob
  } catch {
    if (currentGeneration === resourceGeneration) resourceLoadError.value = true
    return null
  } finally {
    if (currentGeneration === resourceGeneration) resourceLoading.value = false
  }
}

function retryResource(): void {
  void ensureResourceBlob(true)
}

function previewDescription(content: string): string {
  return content.replace(/\s+/g, ' ').trim().slice(0, 500)
}

function syncPreviewFromDocument(document: WorkingDocumentSnapshot): void {
  const uri = `document://${document.id}`
  const apply = (preview: MessageResourcePreview): MessageResourcePreview => (
    preview.uri === uri
      ? {
          ...preview,
          title: document.title,
          description: previewDescription(document.media_type === 'text/html' ? richTextExcerpt(document.payload.text ?? '') : document.payload.text ?? ''),
          content: document.payload.text ?? '',
          content_format: document.media_type === 'text/html' ? 'html' : 'markdown',
          truncated: false,
          metadata: { ...preview.metadata, revision: document.revision },
        }
      : preview
  )
  previews.value = previews.value.map(apply)
  if (selected.value?.uri === uri) selected.value = apply(selected.value)
}

function onSelectedDocumentUnavailable(documentIdValue: string): void {
  if (documentId(selected.value) !== documentIdValue) return
  documentDialogOpen.value = false
  scheduleRealtimeRefresh()
}

function scheduleRealtimeRefresh(): void {
  if (realtimeTimer) clearTimeout(realtimeTimer)
  realtimeTimer = setTimeout(() => {
    realtimeTimer = undefined
    void load(false)
  }, 180)
}

function onMemoryUpdate(response: MemoryRealtimeEvent): void {
  const event = response.data
  if (event?.node_kind !== 'document' || !event.id || !documentPreviewIds().has(event.id)) return
  scheduleRealtimeRefresh()
}

function onMemoryDelete(response: MemoryRealtimeEvent): void {
  const event = response.data
  if (event?.node_kind !== 'document' || !event.id || !documentPreviewIds().has(event.id)) return
  scheduleRealtimeRefresh()
}

function onWebsocketConnect(): void {
  scheduleRealtimeRefresh()
}

function prettyJson(content: string): string {
  try {
    return JSON.stringify(JSON.parse(content) as unknown, null, 2)
  } catch {
    return content
  }
}

watch(
  () => [
    props.roomId,
    props.messageId,
    props.conversationAgentId,
    props.viewerAgentId,
    props.canReadDocuments,
  ] as const,
  () => { void load() },
  { immediate: true },
)
watch(dialogOpen, open => {
  if (!open) {
    resetResource()
  }
})

onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'update', onMemoryUpdate)
  websocket.onEvent('memory', 'delete', onMemoryDelete)
  websocket.onConnect(onWebsocketConnect)
})

onBeforeUnmount(() => {
  generation += 1
  if (realtimeTimer) clearTimeout(realtimeTimer)
  websocket.offEvent('memory', 'update', onMemoryUpdate)
  websocket.offEvent('memory', 'delete', onMemoryDelete)
  websocket.offConnect(onWebsocketConnect)
  clearImages()
  resetResource()
})
</script>

<style scoped>
.resource-preview-loading,.resource-preview-list { margin-top: 8px; }
.resource-preview-video-frame { position: relative; width: 1280px; height: 720px; overflow: hidden; background: #000; }
.resource-preview-video-frame.resource-preview-content--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); min-height: var(--galaris-preview-height, 100dvh); }
.resource-preview-video-frame iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
.resource-preview-dialog-image { display: block; width: auto; max-width: none; max-height: none; margin: 0 auto; object-fit: contain; }
.resource-preview-dialog-image.resource-preview-content--fit { max-width: 100vw; max-height: var(--galaris-preview-height, 100dvh); }
.resource-preview-file { width: 100%; }
.resource-preview-file-loading { display: flex; min-height: 60vh; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: rgba(255, 255, 255, .72); }
.resource-preview-file-error { margin-top: 12px; color: var(--chat-text-muted, #667184); background: var(--chat-surface-soft, #e9edf3); }
.resource-preview-file-frame { display: block; width: 1280px; height: 800px; background: #fff; border: 0; }
.resource-preview-file-frame.resource-preview-content--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); min-height: var(--galaris-preview-height, 100dvh); }
.resource-preview-file-audio { display: block; width: min(100%, 720px); margin: 28px auto; }
.resource-preview-file-video { display: block; width: auto; max-width: none; max-height: none; margin: 0 auto; background: #000; }
.resource-preview-file-video.resource-preview-content--fit { max-width: 100vw; max-height: var(--galaris-preview-height, 100dvh); }
.resource-preview-document,.resource-preview-text,.resource-preview-json,.resource-preview-dialog-description { box-sizing: border-box; width: 960px; min-height: var(--galaris-preview-height, 100dvh); margin: 0; padding: 72px 22px 68px; color: var(--chat-text, #20242c); background: var(--chat-surface-raised, #fff); border: 0; border-radius: 0; }
.resource-preview-document.resource-preview-content--fit,.resource-preview-text.resource-preview-content--fit,.resource-preview-json.resource-preview-content--fit,.resource-preview-dialog-description.resource-preview-content--fit { width: 100vw; }
.resource-preview-text { overflow: auto; font: .8rem/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.resource-preview-json { padding: 72px 0 68px; }
.resource-preview-dialog-description { font-size: .88rem; line-height: 1.55; }
.resource-preview-truncated { margin-top: 12px; color: var(--chat-text-muted, #667184); background: var(--chat-surface-soft, #e9edf3); }

@media (max-width: 599px) {
  .resource-preview-document,.resource-preview-text,.resource-preview-dialog-description { padding: 13px; }
}
</style>
