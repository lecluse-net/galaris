<template>
  <div ref="root" class="document-resource-embed">
    <q-banner v-if="recursive" dense>{{ t('documents.embedLimit') }}</q-banner>
    <q-spinner v-else-if="loading" color="primary" />
    <q-banner v-else-if="error || !sessionValid" dense>{{ t('documents.embedUnavailable') }}</q-banner>
    <component :is="contribution.embed" v-else-if="item && contribution?.embed && (full || legacyEmbedFormat(contribution.code))" ref="viewer" :document="item" :source="source" :readonly="true" :resolve-image="resolveImage" :agent-id="agentId" :register-actions="registerActions" />
    <DocumentThumbnail v-else :document-id="documentId" :agent-id="agentId" fill />
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, provide, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { captureElementRendering, queuePreview, type RenderedDocumentCapture } from '@/core/util'
import { onReadSessionChanged, provideDocumentReferencePath, registerDocumentFullscreenToolbarKey, useDocumentReferencePath, type RegisterDocumentReferenceActions } from '@/core/util/facade'
import { sessionGeneration } from '@/core/api'
import { websocket } from '@/core/websocket'
import { documentFormats, findDocumentFormat, type DocumentContentSource } from '../documentFormats'
import { documentService } from '../services/documentService'
import type { DocumentDetail } from '../types'
import DocumentThumbnail from './DocumentThumbnail.vue'
const { documentId, agentId = null, full = false, legacy = false, registerActions } = defineProps<{
  documentId: string; agentId?: number | null; full?: boolean; legacy?: boolean; registerActions?: RegisterDocumentReferenceActions
}>()
const { t } = useI18n()
const ancestors = useDocumentReferencePath()
const path = computed(() => [...ancestors(), documentId])
provideDocumentReferencePath(() => path.value)
provide(registerDocumentFullscreenToolbarKey, null)
function legacyEmbedFormat(code: string): boolean { return legacy && code !== 'text' && code !== 'mindmap' }
const loadContent = computed(() => full || legacy && documentFormats.some(format => format.embed && legacyEmbedFormat(format.code)))
const recursive = computed(() => loadContent.value && (ancestors().includes(documentId) || ancestors().length >= 4))
const item = shallowRef<DocumentDetail | null>(null)
const contribution = computed(() => item.value ? findDocumentFormat(item.value.document_format, item.value.format_version) : undefined)
const source = computed<DocumentContentSource | undefined>(() => {
  const document = item.value
  if (document?.content_type !== 'binary') return
  return { key: `${document.id}:${document.revision}`, revision: document.revision, readonly: true,
    load: signal => documentService.source(document.id, null, signal, document.revision),
    save: () => Promise.reject(new Error('Embedded document is read-only')),
  }
})
const loading = ref(false), error = ref(false)
const sessionValid = ref(true)
const session = sessionGeneration()
const stopSessionWatch = onReadSessionChanged(() => { sessionValid.value = session === sessionGeneration() })
const revalidation = ref(0)
function revalidate(): void { if (loadContent.value && sessionValid.value) revalidation.value++ }
function revalidateDocument(event: { data: { id: string } }): void {
  if (event.data.id === documentId) revalidate()
}
websocket.onEvent('document', 'invalidate', revalidate)
websocket.onEvent('document', 'update', revalidateDocument)
websocket.onEvent('document', 'delete', revalidateDocument)
let request: AbortController | undefined
watch(() => [documentId, agentId, recursive.value, loadContent.value, sessionValid.value, revalidation.value], async () => {
  request?.abort(); item.value = null; error.value = false; loading.value = false
  if (recursive.value || !loadContent.value || !sessionValid.value) return
  const pending = new AbortController(); request = pending; loading.value = true
  const id = documentId, context = full ? null : agentId
  try { const result = await queuePreview(() => documentService.getDocument(id, context, pending.signal), pending.signal); if (!pending.signal.aborted) item.value = result }
  catch { if (!pending.signal.aborted) error.value = true }
  finally { if (request === pending) loading.value = false }
}, { immediate: true })
const root = useTemplateRef<HTMLElement>('root')
const viewer = useTemplateRef<{ capture?: RenderedDocumentCapture }>('viewer')
async function capture(signal: AbortSignal): Promise<string> {
  if (loading.value || error.value) throw new Error('Document embed unavailable')
  if (viewer.value?.capture) return viewer.value.capture(signal)
  if (!root.value) throw new Error('Document embed unavailable')
  return captureElementRendering(root.value, signal)
}
function resolveImage(id: string, attachmentId: string, signal?: AbortSignal): Promise<Blob> {
  return documentService.documentAttachmentBlob(id, attachmentId, full ? null : agentId, signal)
}
onBeforeUnmount(() => {
  request?.abort(); stopSessionWatch()
  websocket.offEvent('document', 'invalidate', revalidate)
  websocket.offEvent('document', 'update', revalidateDocument)
  websocket.offEvent('document', 'delete', revalidateDocument)
})
defineExpose({ capture })
</script>
<style scoped>
.document-resource-embed { width: 100%; height: 100%; overflow: auto; }
</style>
