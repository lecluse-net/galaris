<template>
  <DocumentThumbnail v-if="item.node_kind === 'document'" :document-id="item.id"
    :revision="item.revision" :updated-at="item.updated_at" :agent-id="agentId" />
  <span v-else-if="item.node_kind === 'file' || item.node_kind === 'attachment'"
    v-show="!unavailable" ref="container" class="memory-item-thumbnail" :aria-busy="loading" aria-hidden="true">
    <img v-if="url" :src="url" alt="" @error="imageFailed" />
    <q-spinner v-else-if="loading" color="primary" size="22px" />
  </span>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { attachmentReference, browserResourceKind, queuePreview } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { MemoryItem } from '../types'
import DocumentThumbnail from './DocumentThumbnail.vue'
import { onThumbnailReady } from '../thumbnailEvents'

const props = defineProps<{ item: MemoryItem & { primary_url?: string | null }; agentId: number | null }>()
const container = useTemplateRef<HTMLElement>('container')
const url = ref('')
const loading = ref(false)
const unavailable = ref(false)
let visible = false
let sessionAvailable = true
let controller: AbortController | undefined
let observer: IntersectionObserver | undefined

function reset(): void {
  controller?.abort()
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  loading.value = false
  unavailable.value = false
}

function imageFailed(): void {
  reset()
  unavailable.value = true
}

const unsubscribeThumbnailReady = onThumbnailReady(ready => {
  if (ready.agentId !== props.agentId || props.item.node_kind === 'document') return
  const uri = props.item.primary_url ?? props.item.metadata.resource_uri
  if (ready.itemId !== props.item.id && (!ready.resourceUri || ready.resourceUri !== uri)) return
  reset()
  if (visible && sessionAvailable) url.value = URL.createObjectURL(ready.blob)
})

async function load(): Promise<void> {
  if (!visible || !sessionAvailable || props.agentId === null || loading.value || url.value || unavailable.value) return
  const request = new AbortController()
  controller = request
  const item = props.item
  const agentId = props.agentId
  loading.value = true
  try {
    const blob = await queuePreview(async () => {
      if (item.node_kind === 'attachment') {
        const uri = item.primary_url ?? item.metadata.resource_uri
        const reference = typeof uri === 'string' ? attachmentReference(uri) : null
        return reference ? memoryService.documentAttachmentThumbnailBlob(reference[0], reference[1], agentId, request.signal) : null
      }
      if (item.node_kind !== 'file') return null
      const resource = (await memoryService.fileResources(item.id, agentId, request.signal, 1))[0]
      if (!resource || browserResourceKind(resource.media_type, resource.name) === 'audio') return null
      return memoryService.fileResourceThumbnail(item.id, resource.id, agentId, request.signal)
    }, request.signal)
    if (request.signal.aborted) return
    if (blob?.size && blob.type.startsWith('image/')) url.value = URL.createObjectURL(blob)
    else unavailable.value = true
  } catch {
    // Optional thumbnails must not prevent opening the memory item.
    if (!request.signal.aborted) unavailable.value = true
  } finally {
    if (controller === request) loading.value = false
  }
}

function onSessionChanged(event: Event): void {
  sessionAvailable = Boolean((event as CustomEvent<string | null>).detail)
  reset()
  void load()
}

watch(() => [props.item.id, props.item.node_kind, props.item.revision, props.item.updated_at,
  props.item.primary_url, props.item.metadata.resource_uri, props.agentId], () => {
  reset()
  void load()
})
onMounted(() => {
  if (!container.value) return
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
  observer = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting)
    if (visible) void load()
    else { controller?.abort(); loading.value = false }
  }, { rootMargin: '160px' })
  observer.observe(container.value)
})
onBeforeUnmount(() => {
  unsubscribeThumbnailReady()
  observer?.disconnect()
  reset()
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
})
</script>

<style scoped>
.memory-item-thumbnail { display: inline-flex; width: 88px; height: 62px; flex: 0 0 auto; align-items: center; justify-content: center; overflow: hidden; }
.memory-item-thumbnail img { display: block; width: 100%; height: 100%; object-fit: contain; }
</style>
