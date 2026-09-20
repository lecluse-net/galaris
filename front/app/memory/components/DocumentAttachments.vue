<template>
  <q-dialog v-if="managerMode" v-model="managerOpen"><q-card style="width: 920px; max-width: 95vw"><q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('documents.attachments') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section><div ref="managerContent" class="q-pa-md" /></q-card></q-dialog>
  <Teleport :to="managerContent || 'body'" :disabled="!managerMode || !managerOpen">
  <section v-if="!previewOnly" v-show="!managerMode || managerOpen || displayedAttachments.length" class="document-attachments" :class="{ 'document-attachments--drag': dragging }" @dragover.prevent="dragging = editable" @dragleave.self="dragging = false" @drop.prevent="dropFiles" :aria-label="attachmentsTitle">
    <div class="row items-center q-mb-sm">
      <div class="text-subtitle2">{{ attachmentsTitle }}</div>
      <q-space />
      <q-btn
        v-if="editable"
        outline
        dense
        no-caps
        color="primary"
        icon="attach_file"
        :label="t('documents.addAttachments')"
        :loading="uploading"
        @click="fileInput?.click()"
      />
      <input
        ref="fileInput"
        type="file"
        multiple
        class="document-attachments__input"
        @change="selectFiles"
      />
    </div>
    <div v-if="uploading && uploadTotal" class="row items-center q-gutter-sm q-mb-sm">
      <q-linear-progress
        rounded
        color="primary"
        :value="(uploadDone + uploadProgress) / uploadTotal"
        class="col"
      />
      <span class="text-caption">{{ uploadName }} · {{ Math.round(uploadProgress * 100) }}% · {{ uploadDone }}/{{ uploadTotal }}</span>
      <q-btn flat dense icon="close" :label="t('documents.cancelUpload')" @click="uploadController?.abort()" />
    </div>
    <div v-if="editable" class="text-caption text-grey-7 q-mb-sm">{{ t('documents.dropAttachments') }}</div>
    <div v-if="loading" class="document-attachments__list">
      <q-skeleton type="rect" width="260px" height="160px" />
    </div>
    <div v-else-if="displayedAttachments.length" class="document-attachments__list resource-preview-grid">
      <ResourcePreviewBlock
        v-for="attachment in displayedAttachments"
        :key="attachment.id"
        :ref="element => registerPreviewElement(attachment.id, element)"
        class="document-attachments__item"
        placement="below-page"
        :title="attachment.name"
        :subtitle="formatSize(attachment.size_bytes)"
        :image="thumbnailUrls[attachment.id]"
        :icon="attachmentIcon(attachment)"
        :open-label="t(canPreview(attachment) ? 'documents.openAttachment' : 'documents.downloadAttachment', { name: attachment.name })"
        @open="attachmentAction(attachment)"
      >
        <template v-if="attachmentKind(attachment) === 'model3d' || thumbnailLoading.has(attachment.id)" #preview>
          <Model3dThumbnail v-if="attachmentKind(attachment) === 'model3d'" :source="modelSource(attachment)" />
          <q-spinner v-else color="primary" size="30px" />
        </template>
        <template #actions>
            <q-btn
              v-if="editable && managerMode && !embeddedAttachmentIds.has(attachment.id.toLowerCase())"
              flat
              round
              dense
              icon="post_add"
              :aria-label="t('richEditor.resources.insertAttachment')"
              @click="emit('insert', attachment); managerOpen = false"
            >
              <q-tooltip>{{ t('richEditor.resources.insertAttachment') }}</q-tooltip>
            </q-btn>
            <q-btn
              flat
              round
              dense
              icon="download"
              :aria-label="t('documents.downloadAttachment', { name: attachment.name })"
              @click="download(attachment)"
            >
              <q-tooltip>{{ t('documents.downloadAttachment', { name: attachment.name }) }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="editable"
              flat
              round
              dense
              icon="close"
              :aria-label="t('documents.removeAttachment', { name: attachment.name })"
              @click="requestRemoval(attachment)"
            >
              <q-tooltip>{{ t('documents.removeAttachment', { name: attachment.name }) }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canPreview(attachment)"
              flat
              round
              dense
              icon="open_in_full"
              :aria-label="t('documents.openAttachment', { name: attachment.name })"
              @click="openPreview(attachment)"
            >
              <q-tooltip>{{ t('documents.openAttachment', { name: attachment.name }) }}</q-tooltip>
            </q-btn>
        </template>
      </ResourcePreviewBlock>
    </div>
    <div v-else class="text-body2 text-grey-7 q-py-sm">{{ t('documents.noAttachments') }}</div>
  </section>
  </Teleport>

  <FullscreenPreview
    v-model="previewOpen"
    :immersive="previewIsImmersive"
    :interactive="previewKind === 'html' || previewKind === 'model3d' || previewKind === 'markdown' || previewKind === 'text'"
    :spatial="previewKind === 'model3d'"
    :viewer-label="previewAttachment
      ? t('documents.openAttachment', { name: previewAttachment.name })
      : t('documents.attachments')"
  >
    <template #actions>
      <q-btn
        v-if="previewAttachment"
        flat
        round
        dense
        icon="download"
        color="white"
        :aria-label="t('documents.downloadAttachment', { name: previewAttachment.name })"
        @click="download(previewAttachment)"
      >
        <q-tooltip>{{ t('documents.downloadAttachment', { name: previewAttachment.name }) }}</q-tooltip>
      </q-btn>
    </template>
    <div v-if="previewLoading" class="q-pa-xl text-center"><q-spinner color="primary" size="48px" /><div>{{ t('documents.loadingAttachment') }}</div></div>
    <template v-if="!previewLoading && previewAttachment && (previewKind === 'model3d' || objectUrls[previewAttachment.id])" #default="{ fit }">
      <Model3dViewer v-if="previewKind === 'model3d'" :source="modelSource(previewAttachment)" />
      <TextResourcePreview
        v-else-if="previewKind === 'markdown' || previewKind === 'text'"
        :content="textContents[previewAttachment.id]"
        :title="previewAttachment.name"
        :fit="fit"
        :markdown="previewKind === 'markdown'"
        :media-type="previewAttachment.media_type"
      />
      <img
        v-else-if="previewKind === 'image'"
        :src="objectUrls[previewAttachment.id]"
        :alt="previewAttachment.name"
        class="document-attachments__fullscreen-media"
        :class="{ 'document-attachments__fullscreen-media--fit': fit }"
      />
      <video
        v-else-if="previewKind === 'video'"
        :src="objectUrls[previewAttachment.id]"
        controls
        playsinline
        class="document-attachments__fullscreen-media"
        :class="{ 'document-attachments__fullscreen-media--fit': fit }"
      />
      <iframe
        v-else-if="previewKind === 'html'"
        :src="objectUrls[previewAttachment.id]"
        :title="previewAttachment.name"
        sandbox="allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads allow-presentation"
        referrerpolicy="no-referrer"
        class="document-attachments__fullscreen-frame"
        :class="{ 'document-attachments__fullscreen-frame--fit': fit }"
      />
      <iframe
        v-else-if="previewKind === 'pdf'"
        :src="objectUrls[previewAttachment.id]"
        :title="previewAttachment.name"
        class="document-attachments__fullscreen-frame"
        :class="{ 'document-attachments__fullscreen-frame--fit': fit }"
      />
      <audio
        v-else-if="previewKind === 'audio'"
        :src="objectUrls[previewAttachment.id]"
        controls
        class="document-attachments__fullscreen-audio"
      />
    </template>
  </FullscreenPreview>

  <q-dialog v-model="removeOpen">
    <q-card class="document-attachments__confirm">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.removeAttachmentTitle') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>{{ t('documents.removeAttachmentConfirm', { name: removalAttachment?.name }) }}<p v-if="removalInUse" class="text-warning q-mt-sm">{{ t('documents.attachmentInUse') }}</p></q-card-section>
      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat :label="t('memory.cancel')" />
        <q-btn color="negative" :label="t('documents.remove')" :loading="removing" @click="confirmRemoval" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import {
  browserResourceKind,
  formatFileSize,
  attachmentReference,
  FullscreenPreview,
  ResourcePreviewBlock,
  Model3dThumbnail,
  Model3dViewer,
  TextResourcePreview,
  isolatedBrowserResourceUrl,
  saveBlobAsResource,
} from '@/core/util'
import type { BrowserResourceKind, Model3dSource } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { DocumentAttachment } from '../types'

const { documentId, agentId, attachments, editable = false, loading = false, content = '', managerMode = false, previewOnly = false } = defineProps<{
  previewOnly?: boolean
  managerMode?: boolean
  documentId: string
  agentId: number | null
  attachments: DocumentAttachment[]
  editable?: boolean
  content?: string
  loading?: boolean
}>()
const emit = defineEmits<{
  insert: [attachment: DocumentAttachment]
  added: [attachment: DocumentAttachment]
  removed: [attachmentId: string]
}>()
const { t, locale } = useI18n()
const $q = useQuasar()
const managerOpen = ref(false)
const attachmentsTitle = computed(() => t(
  managerMode && !managerOpen.value ? 'documents.unembeddedAttachments' : 'documents.attachments',
))
const embeddedAttachmentIds = computed(() => {
  const html = new DOMParser().parseFromString(content, 'text/html')
  const embedded = new Set<string>()
  for (const element of html.querySelectorAll('img[src],a[href]')) {
    if (element.closest('pre,code')) continue
    const reference = attachmentReference(element.getAttribute(element.tagName === 'IMG' ? 'src' : 'href') ?? '')
    if (reference?.[0].toLowerCase() === documentId.toLowerCase()) embedded.add(reference[1].toLowerCase())
  }
  return embedded
})
const displayedAttachments = computed(() => {
  if (!managerMode || managerOpen.value) return attachments
  return attachments.filter(attachment => !embeddedAttachmentIds.value.has(attachment.id.toLowerCase()))
})
const managerContent = ref<HTMLElement>()
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const objectUrls = reactive<Record<string, string>>({})
const thumbnailUrls = reactive<Record<string, string>>({})
const thumbnailLoading = reactive(new Set<string>())
const previewElements = new Map<string, HTMLElement>()
const textContents = reactive<Record<string, string>>({})
const uploading = ref(false), dragging = ref(false), previewLoading = ref(false)
const uploadProgress = ref(0), uploadName = ref('')
let uploadController: AbortController | undefined
let previewGeneration = 0
const removalInUse = computed(() => Boolean(removalAttachment.value && content.includes('document://' + documentId + '/attachments/' + removalAttachment.value.id)))
const uploadDone = ref(0)
const uploadTotal = ref(0)
const previewOpen = ref(false)
const previewAttachment = ref<DocumentAttachment | null>(null)
const removeOpen = ref(false)
const removalAttachment = ref<DocumentAttachment | null>(null)
const removing = ref(false)
let generation = 0
let previewObserver: IntersectionObserver | null = null

const attachmentKind = (attachment: DocumentAttachment): BrowserResourceKind | null => (
  browserResourceKind(attachment.media_type, attachment.name)
)
const canPreview = (attachment: DocumentAttachment): boolean => (
  attachmentKind(attachment) !== null
)
const canThumbnail = (attachment: DocumentAttachment): boolean => {
  if (attachmentKind(attachment) === 'model3d') return false
  const mediaType = attachment.media_type.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  const name = attachment.name.toLowerCase()
  return mediaType.startsWith('image/')
    || mediaType.startsWith('video/')
    || mediaType.startsWith('text/')
    || mediaType === 'application/pdf'
    || name.endsWith('.pdf')
    || name.endsWith('.url')
}
const previewKind = computed(() => previewAttachment.value ? attachmentKind(previewAttachment.value) : null)
const previewIsImmersive = computed(() => previewKind.value !== null && previewKind.value !== 'audio')

function attachmentIcon(attachment: DocumentAttachment): string {
  switch (attachmentKind(attachment)) {
    case 'image': return 'image'
    case 'video': return 'movie'
    case 'audio': return 'audio_file'
    case 'pdf': return 'picture_as_pdf'
    case 'html': return 'html'
    case 'model3d': return 'view_in_ar'
    default: return 'draft'
  }
}

function modelSource(attachment: DocumentAttachment): Model3dSource {
  const currentDocumentId = documentId
  const currentAgentId = agentId
  return {
    key: `${currentDocumentId}:${currentAgentId}:${attachment.id}:${attachment.name}`,
    name: attachment.name,
    mediaType: attachment.media_type,
    size: attachment.size_bytes,
    load: () => memoryService.documentAttachmentBlob(currentDocumentId, attachment.id, currentAgentId),
  }
}

function clearObjectUrls(): void {
  generation += 1
  for (const url of Object.values(objectUrls)) URL.revokeObjectURL(url)
  for (const id of Object.keys(objectUrls)) delete objectUrls[id]
  for (const id of Object.keys(textContents)) delete textContents[id]
  for (const url of Object.values(thumbnailUrls)) URL.revokeObjectURL(url)
  for (const id of Object.keys(thumbnailUrls)) delete thumbnailUrls[id]
}

async function loadPreviewContent(attachment: DocumentAttachment): Promise<string | null> {
  if (objectUrls[attachment.id]) return objectUrls[attachment.id] ?? null
  try {
    const currentGeneration = generation
    const blob = await memoryService.documentAttachmentBlob(documentId, attachment.id, agentId)
    const text = ['markdown', 'text'].includes(attachmentKind(attachment) ?? '') ? await blob.text() : undefined
    if (currentGeneration !== generation) return null
    const url = await isolatedBrowserResourceUrl(blob, attachment.media_type, attachment.name)
    if (currentGeneration !== generation) { URL.revokeObjectURL(url); return null }
    if (text !== undefined) textContents[attachment.id] = text
    objectUrls[attachment.id] = url
    return url
  } catch {
    return null
  }
}

async function loadThumbnail(attachment: DocumentAttachment, currentGeneration: number): Promise<void> {
  if (!canThumbnail(attachment)) return
  if (thumbnailUrls[attachment.id] || thumbnailLoading.has(attachment.id)) return
  thumbnailLoading.add(attachment.id)
  try {
    for (const delay of [0, 750, 1_500, 3_000, 6_000]) {
      if (delay) await new Promise(resolve => window.setTimeout(resolve, delay))
      if (currentGeneration !== generation) return
      try {
        const blob = await memoryService.documentAttachmentThumbnailBlob(
          documentId,
          attachment.id,
          agentId,
        )
        if (currentGeneration !== generation) return
        thumbnailUrls[attachment.id] = URL.createObjectURL(blob)
        return
      } catch {
        // Generation is asynchronous; retry while this document stays mounted.
      }
    }
  } finally {
    thumbnailLoading.delete(attachment.id)
  }
}

function registerPreviewElement(
  attachmentId: string,
  element: Element | ComponentPublicInstance | null,
): void {
  const previous = previewElements.get(attachmentId)
  if (previous) previewObserver?.unobserve(previous)
  const target: unknown = element && '$el' in element ? element.$el : element
  if (!(target instanceof HTMLElement)) {
    previewElements.delete(attachmentId)
    return
  }
  previewElements.set(attachmentId, target)
  previewObserver?.observe(target)
}

function refreshPreviews(): void {
  generation += 1
  const visibleIds = new Set(attachments.map(value => value.id))
  for (const [id, url] of Object.entries(objectUrls)) {
    if (visibleIds.has(id)) continue
    URL.revokeObjectURL(url)
    delete objectUrls[id]
    delete textContents[id]
  }
  for (const [id, url] of Object.entries(thumbnailUrls)) {
    if (visibleIds.has(id)) continue
    URL.revokeObjectURL(url)
    delete thumbnailUrls[id]
  }
  if (previewAttachment.value && !visibleIds.has(previewAttachment.value.id)) {
    previewOpen.value = false
    previewAttachment.value = null
  }
  for (const [id, element] of previewElements) {
    if (visibleIds.has(id)) previewObserver?.observe(element)
    else previewObserver?.unobserve(element)
  }
}

function formatSize(bytes: number): string {
  return formatFileSize(bytes, locale.value)
}

async function openPreview(attachment: DocumentAttachment): Promise<void> {
  if (!canPreview(attachment)) return
  const request = ++previewGeneration
  previewAttachment.value = attachment
  previewLoading.value = attachmentKind(attachment) !== 'model3d'
  previewOpen.value = true
  const loaded = attachmentKind(attachment) === 'model3d' || await loadPreviewContent(attachment)
  if (request !== previewGeneration) return
  previewLoading.value = false
  if (!loaded) { previewOpen.value = false; $q.notify({ type: 'negative', message: t('documents.attachmentError') }) }
}

function attachmentAction(attachment: DocumentAttachment): void {
  if (canPreview(attachment)) void openPreview(attachment)
  else void download(attachment)
}

async function download(attachment: DocumentAttachment): Promise<void> {
  try {
    const blob = await memoryService.documentAttachmentBlob(documentId, attachment.id, agentId)
    saveBlobAsResource(blob, attachment.name)
  } catch (error) {
    $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('documents.attachmentError') })
  }
}

async function selectFiles(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  await uploadFiles(files)
}
function dropFiles(event: DragEvent): void {
  dragging.value = false
  if (editable) void uploadFiles([...(event.dataTransfer?.files ?? [])])
}
async function uploadFiles(files: File[]): Promise<void> {
  if (!files.length || !editable || uploading.value) return
  const currentDocumentId = documentId, currentAgentId = agentId
  const request = new AbortController(); uploadController = request
  uploading.value = true
  uploadDone.value = 0
  uploadTotal.value = files.length
  const failures: string[] = []
  try {
    for (const file of files) {
      if (request.signal.aborted) break
      uploadName.value = file.name; uploadProgress.value = 0
      try {
        const attachment = await memoryService.addDocumentAttachment(currentDocumentId, currentAgentId, file, request.signal, value => { uploadProgress.value = value })
        if (currentDocumentId === documentId && currentAgentId === agentId) emit('added', attachment)
      } catch (error) {
        if (!request.signal.aborted) failures.push(`${file.name}: ${apiErrorDetail(error) ?? t('documents.attachmentError')}`)
      } finally {
        uploadDone.value += 1
      }
    }
    if (failures.length) {
      $q.notify({
        type: 'negative',
        message: t('documents.attachmentsFailed', { count: failures.length }),
        caption: failures.join('\n'),
        multiLine: true,
      })
    }
  } finally {
    uploading.value = false; uploadProgress.value = 0; uploadName.value = ''
  }
}

function requestRemoval(attachment: DocumentAttachment): void {
  removalAttachment.value = attachment
  removeOpen.value = true
}

async function confirmRemoval(): Promise<void> {
  const attachment = removalAttachment.value
  if (!attachment) return
  removing.value = true
  try {
    await memoryService.deleteDocumentAttachment(documentId, attachment.id, agentId)
    emit('removed', attachment.id)
    removeOpen.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('documents.attachmentError') })
  } finally {
    removing.value = false
  }
}

watch(
  () => [documentId, agentId, attachments.map(value => `${value.id}:${value.media_type}`).join('|')] as const,
  refreshPreviews,
  { immediate: true },
)
onMounted(() => {
  previewObserver = new IntersectionObserver(entries => {
    const currentGeneration = generation
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      const attachment = attachments.find(value => previewElements.get(value.id) === entry.target)
      if (attachment) void loadThumbnail(attachment, currentGeneration)
    }
  }, { rootMargin: '160px' })
  for (const element of previewElements.values()) previewObserver.observe(element)
})
watch(() => [documentId, agentId], () => { managerOpen.value = false; uploadController?.abort(); previewGeneration++; previewOpen.value = false; clearObjectUrls() })
watch(previewOpen, value => { if (!value) previewGeneration++ })
async function openById(id: string): Promise<void> {
  const sourceDocument = documentId, sourceAgent = agentId
  try {
    const attachment = attachments.find(value => value.id === id) ?? await memoryService.documentAttachmentInfo(sourceDocument, id, sourceAgent)
    if (sourceDocument === documentId && sourceAgent === agentId) {
      if (canPreview(attachment)) await openPreview(attachment)
      else await download(attachment)
    }
  } catch { $q.notify({ type: 'negative', message: t('documents.attachmentError') }) }
}
defineExpose({ openById, openManager: () => { managerOpen.value = true } })
onBeforeUnmount(() => {
  uploadController?.abort(); previewGeneration++
  previewObserver?.disconnect()
  previewObserver = null
  clearObjectUrls()
})
</script>

<style scoped>
.document-attachments--drag { outline: 2px dashed var(--q-primary); outline-offset: 6px; }
.document-attachments__input { display: none; }
.document-attachments__fullscreen-media { display: block; width: auto; max-width: none; max-height: none; margin: 0 auto; object-fit: contain; background: #000; }
.document-attachments__fullscreen-media--fit { max-width: 100vw; max-height: var(--galaris-preview-height, 100dvh); }
.document-attachments__fullscreen-frame { display: block; width: 1280px; height: 800px; background: #fff; border: 0; }
.document-attachments__fullscreen-frame--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); min-height: var(--galaris-preview-height, 100dvh); }
.document-attachments__fullscreen-audio { display: block; width: min(100%, 720px); margin: 28px auto; }
.document-attachments__confirm { width: min(520px, 92vw); }
</style>
