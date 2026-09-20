<template>
  <div class="document-application" :aria-label="app.title">
    <div v-if="error" role="alert" class="text-negative q-mb-sm">{{ error }}</div>
    <iframe v-if="running" ref="frame" :srcdoc="source" sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer" :title="app.title" class="document-application-frame" :style="{ height: height + 'px' }" @load="connect" />
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch, useTemplateRef } from 'vue'
import { websocket } from '@/core/websocket'
import { useI18n } from 'vue-i18n'
import type { RegisterDocumentCapture } from '@/core/util'
import { memoryService } from '../services/memoryService'
import { appSandboxDocument } from '../documentAppSandbox'
import type { AppDatasetRequest, DocumentApp } from '../documentApps'

const { app, documentId, revision, ready = true, registerSnapshot } = defineProps<{ app: DocumentApp; documentId: string; revision: number; ready?: boolean; registerSnapshot?: RegisterDocumentCapture }>()
const { t } = useI18n()
const frame = useTemplateRef('frame')
const running = ref(false), source = ref(''), error = ref('')
const height = ref(240)
let channel: MessageChannel | null = null
let controller = new AbortController()
let generation = 0, pending = 0, requests = 0, started = 0
const ids = new Set<string>()
async function capture(signal: AbortSignal): Promise<string> {
  signal.throwIfAborted()
  const target = frame.value?.contentWindow
  if (!running.value || !target) throw new Error('Document rendering unavailable')
  const lifecycle = controller.signal
  return new Promise((resolve, reject) => {
    const reply = new MessageChannel()
    const cleanup = () => {
      clearTimeout(timer); reply.port1.close(); reply.port2.close()
      signal.removeEventListener('abort', abort); lifecycle.removeEventListener('abort', abort)
    }
    const abort = () => { cleanup(); reject(new Error('Document capture cancelled')) }
    const timer = setTimeout(() => { cleanup(); reject(new Error('Document capture timed out')) }, 10000)
    signal.addEventListener('abort', abort, { once: true }); lifecycle.addEventListener('abort', abort, { once: true })
    reply.port1.onmessage = ({ data }: MessageEvent<unknown>) => {
      cleanup()
      const html = data && typeof data === 'object' && 'html' in data ? data.html : undefined
      if (typeof html !== 'string' || html.length > 12_000_000) reject(new Error('Invalid document capture'))
      else resolve(html)
    }
    target.postMessage('galaris-app-snapshot', '*', [reply.port2])
  })
}
function stop(): void {
  ++generation
  running.value = false
  controller.abort()
  channel?.port1.close(); channel?.port2.close(); channel = null
  source.value = ''
  ids.clear(); pending = 0
}
function start(): void {
  if (!ready) return
  stop()
  controller = new AbortController()
  error.value = ''; requests = 0; started = Date.now()
  source.value = appSandboxDocument(app)
  running.value = true
}
function connect(): void {
  if (!running.value || !frame.value?.contentWindow || channel) return
  const current = generation
  channel = new MessageChannel()
  const port = channel.port1
  port.onmessage = async (event: MessageEvent<unknown>) => {
    if (current !== generation || !running.value || !event.data || typeof event.data !== 'object') return
    const message = event.data as Record<string, unknown>
    const { id, alias, operation, expected_revision, value } = message
    if (typeof id !== 'string' || id.length > 80 || typeof alias !== 'string' || !/^[a-z][a-z0-9_-]{0,39}$/.test(alias)) return
    if (ids.has(id)) return
    if (Date.now() - started > 60000) { started = Date.now(); requests = 0 }
    if (++requests > 120 || pending >= 8 || ids.size >= 10000) { port.postMessage({ id, error: 'Application request limit exceeded', code: 'limit' }); return }
    const binding = Object.hasOwn(app.datasets ?? {}, alias) ? app.datasets?.[alias] : undefined
    if (!binding || !['read', 'replace', 'append'].includes(String(operation)) || (operation !== 'read' && binding.access !== 'write')) {
      port.postMessage({ id, error: 'Dataset operation not declared', code: 'denied' }); return
    }
    try {
      if (JSON.stringify(message).length > 2_000_000) throw new Error('size')
    } catch { port.postMessage({ id, error: 'Invalid or oversized Dataset request', code: 'limit' }); return }
    ids.add(id); ++pending
    try {
      const request: AppDatasetRequest = { operation: operation as AppDatasetRequest['operation'] }
      if (operation !== 'read') {
        if (!Number.isSafeInteger(expected_revision) || Number(expected_revision) < 1) throw new Error('revision')
        request.expected_revision = Number(expected_revision); request.value = value
      }
      const result = await memoryService.appDataset(documentId, revision, app.id, alias, request, controller.signal)
      if (current === generation) { error.value = ''; port.postMessage({ id, result }) }
    } catch (caught) {
      if (current !== generation) return
      const response = (caught as { response?: { status?: number; data?: { detail?: { code?: string } } } }).response
      const status = response?.status
      const code = response?.data?.detail?.code === 'permission_required' ? 'permission_required'
        : status === 429 ? 'limit' : status === 409 ? 'conflict' : [401, 403, 404].includes(status ?? 0) ? 'denied' : 'failed'
      error.value = t(`documents.apps.${code}`)
      port.postMessage({ id, error: error.value, code })
      if (code === 'denied') stop()
    } finally { if (current === generation) --pending }
  }
  frame.value.contentWindow.postMessage('galaris-host-connect', '*', [channel.port2])
}
watch(() => [documentId, revision, app, ready] as const, () => { stop(); if (ready) start() })
function navigated(event: MessageEvent): void {
  if (event.source !== frame.value?.contentWindow) return
  if (event.data === 'galaris-app-navigated') stop()
  const data = event.data as { type?: string; height?: unknown } | null
  if (data?.type === 'galaris-app-height' && typeof data.height === 'number' && Number.isFinite(data.height)) height.value = Math.max(40, Math.min(3000, data.height))
}
onMounted(() => {
  registerSnapshot?.(capture)
  if (ready) start()
  window.addEventListener('message', navigated)
  websocket.onEvent('memory', 'invalidate', stop)
})
onBeforeUnmount(() => {
  registerSnapshot?.(undefined)
  stop()
  window.removeEventListener('message', navigated)
  websocket.offEvent('memory', 'invalidate', stop)
})
</script>
<style scoped>
.document-application-frame { width: 100%; border: 0; display: block; }
</style>
