<template>
  <div class="q-mt-md">
    <q-banner v-if="failed" rounded class="bg-negative text-white" role="alert">
      {{ t('documents.attachmentError') }}
      <template #action><q-btn flat :label="t('chat.resourcePreview.retryFile')" @click="load" /></template>
    </q-banner>
    <DocumentAttachments v-else-if="agentId !== null" :key="generation" :document-id="itemId" :agent-id="agentId"
      :attachments="resources" :loading="loading" :resource-source="resourceSource" />
    <q-list v-if="resources.length" dense class="q-mt-sm">
      <q-item v-for="resource in resources" :key="resource.id">
        <q-item-section avatar><q-icon name="link" color="primary" /></q-item-section>
        <q-item-section><q-item-label class="memory-file-uri">{{ resource.uri }}</q-item-label></q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import DocumentAttachments from './DocumentAttachments.vue'
import { memoryService } from '../services/memoryService'
import type { CatalogueResource } from '../types'

const { itemId, agentId } = defineProps<{ itemId: string; agentId: number | null }>()
const { t } = useI18n()
const resources = ref<CatalogueResource[]>([])
const loading = ref(false)
const failed = ref(false)
const generation = ref(0)
let request: AbortController | undefined
const resourceSource = computed(() => {
  const id = itemId, agent = agentId
  return {
    content: (attachment: { id: string }, preview: boolean) => memoryService.fileResourceBlob(id, attachment.id, agent!, preview),
    thumbnail: (attachment: { id: string }) => memoryService.fileResourceThumbnail(id, attachment.id, agent!),
  }
})

async function load(): Promise<void> {
  request?.abort()
  generation.value++
  resources.value = []
  failed.value = false
  loading.value = false
  if (agentId === null) return
  const current = new AbortController()
  request = current
  loading.value = true
  try {
    const result = await memoryService.fileResources(itemId, agentId, current.signal)
    if (!current.signal.aborted) resources.value = result
  } catch {
    if (!current.signal.aborted) failed.value = true
  } finally {
    if (request === current) loading.value = false
  }
}
function sessionChanged(event: Event): void {
  request?.abort()
  generation.value++
  resources.value = []
  loading.value = false
  if ((event as CustomEvent<string | null>).detail) void load()
}
watch(() => [itemId, agentId], () => { void load() }, { immediate: true })
onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
onBeforeUnmount(() => { request?.abort(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
</script>

<style scoped>
.memory-file-uri { overflow-wrap: anywhere; font-size: 12px; }
</style>
