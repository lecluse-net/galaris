<template>
  <q-btn v-if="!showThumbnail" :outline="!iconOnly" :flat="iconOnly" :round="iconOnly" dense no-caps icon="attach_file" color="primary"
    :label="iconOnly ? undefined : t('memory.viewLinkedContent')" :aria-label="t('memory.viewLinkedContent')"
    :loading="loading" :disable="agentId === null"
    @click.stop="open">
    <q-tooltip>{{ t('memory.viewLinkedContent') }}</q-tooltip>
  </q-btn>
  <q-skeleton v-if="showThumbnail && loading" type="rect" height="86px" />
  <q-banner v-else-if="showThumbnail && failed" rounded class="bg-negative text-white" role="alert">
    {{ t('documents.attachmentError') }}
    <template #action><q-btn flat :label="t('chat.resourcePreview.retryFile')" @click="load(false)" /></template>
  </q-banner>
  <DocumentAttachments v-if="documentId && attachment" ref="viewer" :preview-only="!showThumbnail"
    :document-id="documentId" :agent-id="agentId" :attachments="[attachment]" />
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { attachmentReference } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { DocumentAttachment } from '../types'
import DocumentAttachments from './DocumentAttachments.vue'

const { itemId, agentId, iconOnly = false, showThumbnail = false, resourceUri } = defineProps<{
  itemId: string
  agentId: number | null
  iconOnly?: boolean
  showThumbnail?: boolean
  resourceUri?: string
}>()
const { t } = useI18n()
const $q = useQuasar()
const viewer = useTemplateRef<InstanceType<typeof DocumentAttachments>>('viewer')
const documentId = ref<string | null>(null)
const attachment = ref<DocumentAttachment | null>(null)
const loading = ref(false)
const failed = ref(false)
let generation = 0

function reset(): void {
  generation++
  documentId.value = null
  attachment.value = null
  loading.value = false
  failed.value = false
}

async function open(): Promise<void> {
  await load(true)
}

async function load(openViewer: boolean): Promise<void> {
  if (agentId === null) return
  reset()
  const request = generation
  loading.value = true
  try {
    let uri = resourceUri
    if (!uri) {
      const item = await memoryService.getItem(itemId, agentId)
      if (request !== generation) return
      const referenceUri = item.primary_url ?? item.metadata.resource_uri
      if (typeof referenceUri === 'string') uri = referenceUri
    }
    const reference = typeof uri === 'string' ? attachmentReference(uri) : null
    if (!reference) throw new Error('Missing document attachment reference')
    const info = await memoryService.documentAttachmentInfo(reference[0], reference[1], agentId)
    if (request !== generation) return
    attachment.value = info
    documentId.value = reference[0]
    await nextTick()
    if (request === generation && openViewer) await viewer.value?.openById(reference[1])
  } catch {
    if (request === generation) {
      failed.value = true
      if (!showThumbnail) $q.notify({ type: 'negative', message: t('documents.attachmentError') })
    }
  } finally {
    if (request === generation) loading.value = false
  }
}

watch(() => [itemId, agentId, showThumbnail, resourceUri], () => { reset(); if (showThumbnail) void load(false) }, { immediate: true })
onBeforeUnmount(reset)
</script>
