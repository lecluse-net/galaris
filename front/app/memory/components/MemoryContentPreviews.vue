<template>
  <section v-if="hasContent" class="memory-content-previews q-pa-md" :aria-label="t('memory.viewLinkedContent')">
    <ResourcePreviewBlock v-for="id in documentIds" :key="id" placement="in-page"
      :title="item.title || t('memory.graph.roles.document')"
      :subtitle="id === item.document_id ? t('memory.documentSynthesis') : undefined"
      :uri="`document://${id}`" :open-label="t('memory.openDocument')" @open="openDocument(id)">
      <template #preview><DocumentThumbnail :document-id="id" :agent-id="agentId" fill /></template>
    </ResourcePreviewBlock>
    <MemoryAttachmentButton v-for="uri in attachmentUris" :key="uri"
      :item-id="item.id" :agent-id="agentId" :resource-uri="uri" show-thumbnail />
    <MemoryAttachmentButton v-if="item.node_kind === 'attachment' && !attachmentUris.length"
      :item-id="item.id" :agent-id="agentId" show-thumbnail />
    <MemoryFileResources v-if="item.node_kind === 'file'" :item-id="item.id" :agent-id="agentId" />
  </section>

  <DocumentDialog v-model="documentOpen" :document-id="selectedDocumentId" :agent-id="agentId"
    :title="documentTitle" editable card-class="memory-document-dialog" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { attachmentReference, ResourcePreviewBlock } from '@/core/util'
import type { MemoryItem } from '../types'
import { DocumentDialog } from '@/app/document'
import { DocumentThumbnail } from '@/app/document'
import MemoryAttachmentButton from './MemoryAttachmentButton.vue'
import MemoryFileResources from './MemoryFileResources.vue'

const { item, agentId } = defineProps<{ item: MemoryItem; agentId: number | null }>()
const { t } = useI18n()
const resourceUris = computed(() => [...new Set([
  item.primary_url, ...(item.urls ?? []), item.metadata.resource_uri,
].filter((uri): uri is string => typeof uri === 'string' && uri.length > 0))])
const documentIds = computed(() => [...new Set([
  item.document_id,
  item.node_kind === 'document' ? item.id : null,
  ...resourceUris.value.map(uri => /^document:\/\/([^/]+)$/.exec(uri)?.[1]),
].filter((id): id is string => Boolean(id)))])
const attachmentUris = computed(() => resourceUris.value.filter(uri => attachmentReference(uri) !== null))
const hasContent = computed(() => documentIds.value.length > 0 || attachmentUris.value.length > 0
  || item.node_kind === 'attachment' || item.node_kind === 'file')
const documentOpen = ref(false)
const selectedDocumentId = ref<string | null>(null)
const documentTitle = ref('')

function openDocument(id: string): void {
  selectedDocumentId.value = id
  documentTitle.value = item.title || t('memory.graph.roles.document')
  documentOpen.value = true
}
watch(() => [item.id, agentId], () => { documentOpen.value = false })
</script>

<style scoped>
.memory-content-previews { display: grid; gap: 12px; min-width: 0; }
</style>
