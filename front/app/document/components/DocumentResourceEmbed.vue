<template>
  <div ref="root" class="document-resource-embed">
    <q-banner v-if="recursive" dense>{{ t('documents.embedLimit') }}</q-banner>
    <q-spinner v-else-if="loading" color="primary" />
    <q-banner v-else-if="error" dense>{{ t('documents.embedUnavailable') }}</q-banner>
    <component :is="contribution.embed" v-else-if="item && contribution?.embed" ref="viewer" :document="item" :readonly="true" :resolve-image="resolveImage" />
    <DocumentThumbnail v-else :document-id="documentId" :agent-id="agentId" fill />
  </div>
</template>
<script setup lang="ts">
import { computed, inject, onBeforeUnmount, provide, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { captureElementRendering, type RenderedDocumentCapture } from '@/core/util'
import { documentFormats, findDocumentFormat } from '../documentFormats'
import { documentService } from '../services/documentService'
import type { DocumentDetail } from '../types'
import DocumentThumbnail from './DocumentThumbnail.vue'
const { documentId, agentId = null } = defineProps<{ documentId: string; agentId?: number | null }>()
const { t } = useI18n()
const ancestors = inject<() => readonly string[]>('galaris-document-embed-path', () => [])
const path = computed(() => [...ancestors(), documentId])
provide('galaris-document-embed-path', () => path.value)
const recursive = computed(() => ancestors().includes(documentId) || ancestors().length >= 4)
const item = shallowRef<DocumentDetail | null>(null)
const contribution = computed(() => item.value ? findDocumentFormat(item.value.document_format, item.value.format_version) : undefined)
const hasRichEmbeds = computed(() => documentFormats.some(format => format.embed))
const loading = ref(false), error = ref(false)
let request: AbortController | undefined
watch(() => [documentId, agentId, recursive.value, hasRichEmbeds.value], async () => {
  request?.abort(); item.value = null; error.value = false; loading.value = false
  if (recursive.value || !hasRichEmbeds.value) return
  const pending = new AbortController(); request = pending; loading.value = true
  try { const result = await documentService.getDocument(documentId, agentId, pending.signal); if (!pending.signal.aborted) item.value = result }
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
  return documentService.documentAttachmentBlob(id, attachmentId, agentId, signal)
}
onBeforeUnmount(() => request?.abort())
defineExpose({ capture })
</script>
<style scoped>
.document-resource-embed { width: 100%; height: 100%; overflow: auto; }
</style>
