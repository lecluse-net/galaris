<template>
  <span ref="container" class="document-thumbnail" :class="{ 'document-thumbnail--fill': fill }" :aria-busy="loading" aria-hidden="true">
    <img v-if="url" :src="url" alt="" @error="clearImage" />
    <q-spinner v-else-if="loading" color="primary" size="22px" />
    <q-icon v-else name="description" size="28px" />
  </span>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { websocket } from '@/core/websocket'
import { memoryService } from '../services/memoryService'

const props = defineProps<{
  documentId: string
  revision?: number | null
  updatedAt?: string | null
  agentId?: number | null
  fill?: boolean
}>()
const container = useTemplateRef<HTMLElement>('container')
const url = ref('')
const loading = ref(false)
let visible = false
let controller: AbortController | undefined
let observer: IntersectionObserver | undefined
let refreshTimer: ReturnType<typeof setTimeout> | undefined

function clearImage(): void {
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
}

async function load(): Promise<void> {
  controller?.abort()
  clearImage()
  loading.value = false
  if (!visible) return
  const request = new AbortController()
  controller = request
  loading.value = true
  try {
    const blob = await memoryService.documentThumbnail(props.documentId, props.agentId ?? null, request.signal)
    if (!request.signal.aborted && blob) url.value = URL.createObjectURL(blob)
  } catch {
    // The document remains usable when the optional renderer is unavailable.
  } finally {
    if (controller === request) loading.value = false
  }
}

function resetSession(): void {
  clearTimeout(refreshTimer)
  controller?.abort()
  clearImage()
  loading.value = false
}

function invalidate(): void {
  resetSession()
  if (visible) refreshTimer = setTimeout(() => { void load() }, 180)
}

function onDocumentUpdate(event: { data?: { id?: string } }): void {
  if (event.data?.id === props.documentId) invalidate()
}

function onDocumentDelete(event: { data?: { id?: string } }): void {
  if (event.data?.id === props.documentId) resetSession()
}

function onSessionChanged(event: Event): void {
  resetSession()
  if ((event as CustomEvent<string | null>).detail) void load()
}

watch(() => [props.documentId, props.revision, props.updatedAt, props.agentId], invalidate)
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'update', onDocumentUpdate)
  websocket.onEvent('memory', 'delete', onDocumentDelete)
  websocket.onConnect(invalidate)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      visible = true
      observer?.disconnect()
      void load()
    }
  }, { rootMargin: '160px' })
  if (container.value) observer.observe(container.value)
})
onBeforeUnmount(() => {
  websocket.offEvent('memory', 'update', onDocumentUpdate)
  websocket.offEvent('memory', 'delete', onDocumentDelete)
  websocket.offConnect(invalidate)
  observer?.disconnect()
  resetSession()
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
})
</script>

<style scoped>
.document-thumbnail { display: inline-flex; width: 88px; height: 62px; flex: 0 0 auto; align-items: center; justify-content: center; overflow: hidden; color: var(--solaire-gray-accent); }
.document-thumbnail img { display: block; width: 100%; height: 100%; object-fit: contain; }
.document-thumbnail.document-thumbnail--fill { position: absolute; inset: 0; width: 100%; height: 100%; }
</style>
