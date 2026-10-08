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

  <q-dialog v-model="documentOpen" allow-focus-outside :maximized="$q.screen.lt.md"
    @before-hide="flushDocument" @hide="selectedDocumentId = null">
    <q-card class="memory-document-dialog column no-wrap galaris-dialog-card">
      <q-toolbar class="galaris-dialog-title">
        <q-toolbar-title>{{ documentTitle }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-toolbar>
      <div class="memory-document-body col galaris-dialog-body">
        <DocumentEditor v-if="selectedDocumentId" ref="documentEditor" :key="`${agentId}:${selectedDocumentId}`"
          :document-id="selectedDocumentId" :agent-id="agentId" content-min-height="min(42vh, 440px)"
          @loaded="documentTitle = $event.title" @updated="documentTitle = $event.title"
          @unavailable="documentOpen = false" @deleted="documentOpen = false" />
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { attachmentReference, ResourcePreviewBlock } from '@/core/util'
import type { MemoryItem } from '../types'
import DocumentEditor from './DocumentEditor.vue'
import DocumentThumbnail from './DocumentThumbnail.vue'
import MemoryAttachmentButton from './MemoryAttachmentButton.vue'
import MemoryFileResources from './MemoryFileResources.vue'

const { item, agentId } = defineProps<{ item: MemoryItem; agentId: number | null }>()
const { t } = useI18n()
const $q = useQuasar()
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
const documentEditor = useTemplateRef<InstanceType<typeof DocumentEditor>>('documentEditor')

function openDocument(id: string): void {
  selectedDocumentId.value = id
  documentTitle.value = item.title || t('memory.graph.roles.document')
  documentOpen.value = true
}
function flushDocument(): void {
  void documentEditor.value?.flush()
}
watch(() => [item.id, agentId], () => { documentOpen.value = false })
</script>

<style scoped>
.memory-content-previews { display: grid; gap: 12px; min-width: 0; }
.memory-document-dialog { width: 980px; max-width: 96vw; height: min(860px, 92vh); }
.memory-document-body { min-height: 0; overflow-y: auto; }
</style>
