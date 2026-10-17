<template>
  <ResourceAttachments ref="list" :resource-id="documentId" :agent-id="agentId" :attachments="attachments"
    :editable="editable" :loading="loading" :content="content" :allow-insertion="allowInsertion"
    :preview-only="previewOnly" :show-heading="showHeading" :resource-source="source"
    :heading="t(resourceSource ? 'memory.fileLocations' : 'documents.attachments')"
    :empty-label="t(resourceSource ? 'memory.noFileLocations' : 'documents.noAttachments')"
    @insert="emit('insert', $event)" @added="emit('added', $event)" @removed="emit('removed', $event)" />
</template>

<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ResourceAttachments, type AttachmentSource } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { DocumentAttachment } from '../types'

const props = withDefaults(defineProps<{
  documentId: string
  agentId: number | null
  attachments: (DocumentAttachment & { uri?: string })[]
  editable?: boolean
  loading?: boolean
  content?: string
  allowInsertion?: boolean
  previewOnly?: boolean
  showHeading?: boolean
  resourceSource?: AttachmentSource<DocumentAttachment>
}>(), { editable: false, loading: false, content: '', allowInsertion: false, previewOnly: false, showHeading: true })
const emit = defineEmits<{
  insert: [attachment: DocumentAttachment]
  added: [attachment: DocumentAttachment]
  removed: [attachmentId: string]
}>()
const { t } = useI18n()
const list = useTemplateRef<{ openById: (id: string) => Promise<void> }>('list')
const source = computed<AttachmentSource<DocumentAttachment>>(() => {
  const id = props.documentId, agent = props.agentId
  return {
    ...props.resourceSource ?? {
      content: (attachment, _preview, signal) => memoryService.documentAttachmentBlob(id, attachment.id, agent, signal),
      thumbnail: (attachment, signal) => memoryService.documentAttachmentThumbnailBlob(id, attachment.id, agent, signal),
    },
    add: (file, signal, progress) => memoryService.addDocumentAttachment(id, agent, file, signal, progress),
    remove: attachment => memoryService.deleteDocumentAttachment(id, attachment.id, agent),
    info: attachmentId => memoryService.documentAttachmentInfo(id, attachmentId, agent),
  }
})
defineExpose({ openById: (id: string) => list.value?.openById(id) })
</script>
