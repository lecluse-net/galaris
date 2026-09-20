<template>
  <q-btn :outline="!iconOnly" :flat="iconOnly" :round="iconOnly" dense no-caps icon="open_in_full" color="primary"
    :label="iconOnly ? undefined : t('memory.viewLinkedContent')" :aria-label="t('memory.viewLinkedContent')"
    :loading="loading" :disable="agentId === null"
    @click.stop="open">
    <q-tooltip>{{ t('memory.viewLinkedContent') }}</q-tooltip>
  </q-btn>
  <DocumentAttachments v-if="documentId && attachment" ref="viewer" preview-only
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

const { itemId, agentId, iconOnly = false } = defineProps<{ itemId: string; agentId: number | null; iconOnly?: boolean }>()
const { t } = useI18n()
const $q = useQuasar()
const viewer = useTemplateRef<InstanceType<typeof DocumentAttachments>>('viewer')
const documentId = ref<string | null>(null)
const attachment = ref<DocumentAttachment | null>(null)
const loading = ref(false)
let generation = 0

function reset(): void {
  generation++
  documentId.value = null
  attachment.value = null
  loading.value = false
}

async function open(): Promise<void> {
  if (agentId === null) return
  reset()
  const request = generation
  loading.value = true
  try {
    const item = await memoryService.getItem(itemId, agentId)
    if (request !== generation) return
    const uri = item.metadata.resource_uri
    const reference = typeof uri === 'string' ? attachmentReference(uri) : null
    if (!reference) throw new Error('Missing document attachment reference')
    const info = await memoryService.documentAttachmentInfo(reference[0], reference[1], agentId)
    if (request !== generation) return
    attachment.value = info
    documentId.value = reference[0]
    await nextTick()
    if (request === generation) await viewer.value?.openById(reference[1])
  } catch {
    if (request === generation) $q.notify({ type: 'negative', message: t('documents.attachmentError') })
  } finally {
    if (request === generation) loading.value = false
  }
}

watch(() => [itemId, agentId], reset)
onBeforeUnmount(reset)
</script>
