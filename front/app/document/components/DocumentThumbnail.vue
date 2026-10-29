<template>
  <span ref="container" class="document-thumbnail" :class="{ 'document-thumbnail--fill': fill }" :aria-busy="loading" aria-hidden="true">
    <img v-if="url" :src="url" alt="" @error="clearImage" />
    <q-spinner v-else-if="loading" color="primary" size="22px" />
    <q-icon v-else :name="getDocumentType(props.documentType).icon" size="28px" />
  </span>
</template>

<script setup lang="ts">
import type { DocumentType } from '../types'
import { documentType as getDocumentType } from '../documentTypes'
import { onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { queuePreview } from '@/core/util'
import { websocket } from '@/core/websocket'
import { documentService } from '../services/documentService'
import { onThumbnailReady } from '@/core/util'

const props = defineProps<{
  documentId: string
  documentType?: DocumentType
  revision?: number | null
  updatedAt?: string | null
  agentId?: number | null
  fill?: boolean
}>()
const container = useTemplateRef<HTMLElement>('container')
const url = ref('')
const loading = ref(false)
let visible = false
let sessionAvailable = true
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
  if (!visible || !sessionAvailable) return
  const request = new AbortController()
  controller = request
  loading.value = true
  try {
    const blob = await queuePreview(
      () => documentService.documentThumbnail(props.documentId, props.agentId ?? null, request.signal),
      request.signal,
    )
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

const unsubscribeThumbnailReady = onThumbnailReady(ready => {
  if (ready.itemId !== props.documentId || ready.agentId !== (props.agentId ?? null)) return
  resetSession()
  if (visible && sessionAvailable) url.value = URL.createObjectURL(ready.blob)
})

function onDocumentUpdate(event: { data?: { id?: string } }): void {
  if (event.data?.id === props.documentId) invalidate()
}

function onDocumentDelete(event: { data?: { id?: string } }): void {
  if (event.data?.id === props.documentId) resetSession()
}

function onSessionChanged(event: Event): void {
  sessionAvailable = Boolean((event as CustomEvent<string | null>).detail)
  resetSession()
  if (sessionAvailable) void load()
}

watch(() => [props.documentId, props.revision, props.updatedAt, props.agentId], invalidate)
onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('document', 'update', onDocumentUpdate)
  websocket.onEvent('document', 'delete', onDocumentDelete)
  websocket.onConnect(invalidate)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
  observer = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting)
    if (visible && !url.value) void load()
    else if (!visible) { controller?.abort(); loading.value = false }
  }, { rootMargin: '160px' })
  if (container.value) observer.observe(container.value)
})
onBeforeUnmount(() => {
  unsubscribeThumbnailReady()
  websocket.offEvent('document', 'update', onDocumentUpdate)
  websocket.offEvent('document', 'delete', onDocumentDelete)
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
