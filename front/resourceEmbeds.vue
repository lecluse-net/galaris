<template>
  <ProcessPreview v-if="target" ref="process" :uri="uri" :agent-id="agentId" inline />
  <div v-else-if="agent !== null" ref="avatar" class="agent-citation-avatar"><ResourceThumbnail :uri="uri" :title="title" /></div>
  <div v-else-if="documentId" class="document-citation-preview">
    <div ref="documentThumbnail" class="document-citation-thumbnail" aria-hidden="true"><WorkingDocumentThumbnail :document-id="documentId" fill /></div>
    <q-btn flat dense no-caps class="document-citation-identifier" :label="documentId" :aria-label="t('common.copy')" @click.stop.prevent="copyIdentifier"><q-tooltip>{{ t('common.copy') }}</q-tooltip></q-btn>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, useTemplateRef } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { defineAsyncView, ResourceThumbnail, WorkingDocumentThumbnail, documentIdFromResourceUri, captureElementRendering, type RegisterDocumentCapture, type RenderedDocumentCapture } from '@/core/util'
import { agentResourceId } from '@/app/agent'
import { processResourceTarget } from '@/app/process/interface'
const { uri, agentId = null, title = '', registerSnapshot } = defineProps<{ uri: string; agentId?: number | null; title?: string; registerSnapshot?: RegisterDocumentCapture }>()
const ProcessPreview = defineAsyncView(async () => (await import('@/app/process')).ProcessPreview)
const target = computed(() => processResourceTarget(uri))
const agent = computed(() => agentResourceId(uri))
const documentId = computed(() => documentIdFromResourceUri(uri))
const { t } = useI18n(), $q = useQuasar()
const documentThumbnail = useTemplateRef<HTMLElement>('documentThumbnail')
async function copyIdentifier(): Promise<void> {
  if (!documentId.value) return
  try { await copyToClipboard(documentId.value); $q.notify({ type: 'positive', message: t('common.copied') }) }
  catch { $q.notify({ type: 'negative', message: t('common.copyError') }) }
}
const process = useTemplateRef<{ capture: RenderedDocumentCapture }>('process'), avatar = useTemplateRef('avatar')
async function capture(signal: AbortSignal): Promise<string> {
  if (target.value && process.value) return process.value.capture(signal)
  if (documentId.value && documentThumbnail.value) return captureElementRendering(documentThumbnail.value, signal)
  const element = avatar.value?.querySelector<HTMLElement>('.q-avatar')
  if (!element) throw new Error('Agent rendering unavailable')
  return captureElementRendering(element, signal)
}
onMounted(() => registerSnapshot?.(capture))
onBeforeUnmount(() => registerSnapshot?.(undefined))
</script>
<style scoped>
.agent-citation-avatar { display: block; width: 100%; height: 100%; }
.document-citation-thumbnail { position: absolute; inset: 8px auto 8px 8px; width: 100px; }
.document-citation-identifier { max-width: 100%; font-family: monospace; font-size: 10px; color: var(--solaire-gray-accent); opacity: .75; }
.document-citation-identifier :deep(.q-btn__content) { overflow-wrap: anywhere; }
</style>
