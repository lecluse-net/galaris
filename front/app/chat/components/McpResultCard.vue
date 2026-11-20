<template>
  <section class="mcp-result q-my-sm">
    <q-markup-table flat bordered dense separator="horizontal" class="mcp-result-table">
      <caption class="text-left text-weight-medium q-pa-sm">{{ table.title }}</caption>
      <thead><tr><th v-for="(column, index) in table.columns" :key="index" scope="col" class="text-left">{{ column }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in table.rows" :key="index">
          <td v-for="(cell, column) in row" :key="column">{{ cell }}</td>
        </tr>
        <tr v-if="!table.rows.length"><td :colspan="table.columns.length">{{ t('chat.mcpResult.empty') }}</td></tr>
      </tbody>
    </q-markup-table>
    <div class="text-caption q-mt-xs">{{ presentation.source }}</div>
    <div class="row q-gutter-sm q-mt-xs">
      <q-btn v-if="canFilter && presentation.resource_uri" outline color="primary" dense no-caps
        :label="t(frameSource ? 'chat.mcpResult.closeFilters' : 'chat.mcpResult.openFilters')"
        :loading="opening" @click="toggleFilters" />
      <q-btn v-if="canInsert" outline color="primary" dense no-caps icon="post_add"
        :label="t('chat.mcpResult.insert')" :disable="working" @click="emit('insert', tableHtml(table, presentation.source))" />
    </div>
    <div v-if="error" role="alert" class="text-negative q-mt-xs">{{ error }}</div>
    <iframe v-if="frameSource && canFilter" ref="frame" class="mcp-result-frame q-mt-sm"
      :title="t('chat.mcpResult.form')" :srcdoc="frameSource" sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer"
      :style="{ height: height + 'px' }" @load="startFrame" />
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { sandboxMcpApp, tableHtml, type McpPresentation, type McpTable } from '../mcpApps'
import { chatService } from '../services/chatService'

const { roomId, messageId, presentation, canFilter, canInsert } = defineProps<{
  roomId: string
  messageId: string
  presentation: McpPresentation
  canFilter: boolean
  canInsert: boolean
}>()
const emit = defineEmits<{ insert: [html: string] }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const table = shallowRef(presentation.table)
const frame = useTemplateRef<HTMLIFrameElement>('frame')
const frameSource = ref('')
const height = ref(140)
const error = ref('')
const opening = ref(false)
const working = ref(false)
let request: AbortController | null = null
let ready = false

function closeFilters(): void {
  ready = false
  request?.abort()
  request = null
  frameSource.value = ''
  opening.value = false
  working.value = false
}

watch(() => [roomId, messageId, presentation.id, canFilter], () => {
  closeFilters()
  table.value = presentation.table
  error.value = ''
})

async function toggleFilters(): Promise<void> {
  if (frameSource.value) {
    closeFilters()
    return
  }
  if (request || !canFilter) return
  const current = new AbortController()
  request = current
  opening.value = true
  error.value = ''
  try {
    const html = await chatService.openMcpApp(roomId, messageId, presentation.id, current.signal)
    if (current.signal.aborted) return
    height.value = 140
    frameSource.value = sandboxMcpApp(html)
  } catch {
    if (!current.signal.aborted) error.value = t('chat.mcpResult.unavailable')
  } finally {
    if (request === current) {
      request = null
      opening.value = false
    }
  }
}

function post(data: unknown): void {
  frame.value?.contentWindow?.postMessage(data, '*')
}

function startFrame(): void { post('start') }

function toolResult(value: McpTable) {
  const snapshot = { title: value.title, columns: [...value.columns], rows: value.rows.map(row => [...row]) }
  return { content: [{ type: 'text', text: value.title }], structuredContent: { table: snapshot } }
}

interface RpcMessage {
  jsonrpc?: string
  id?: string | number
  method?: string
  closed?: boolean
  params?: { name?: string; arguments?: Record<string, unknown>; height?: number; protocolVersion?: string }
}

async function onMessage(event: MessageEvent<RpcMessage>): Promise<void> {
  if (!canFilter || !frame.value || event.source !== frame.value.contentWindow) return
  const data = event.data
  if (!data || typeof data !== 'object') return
  if (data.closed) {
    closeFilters()
    error.value = t('chat.mcpResult.unavailable')
    return
  }
  if (data.jsonrpc !== '2.0') return
  const { id, method, params } = data
  const reply = (result: unknown) => post({ jsonrpc: '2.0', id, result })
  const reject = (code: number, message: string) => post({ jsonrpc: '2.0', id, error: { code, message } })
  if (method === 'ui/initialize' && id !== undefined) {
    reply({
      protocolVersion: '2026-01-26', hostInfo: { name: 'Galaris', version: '1.0.0' },
      hostCapabilities: { serverTools: {} }, hostContext: { locale: locale.value, theme: $q.dark.isActive ? 'dark' : 'light' },
    })
  } else if (method === 'ui/notifications/initialized' && !ready) {
    ready = true
    post({ jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: { arguments: {} } })
    post({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: toolResult(table.value) })
  } else if (method === 'ui/notifications/size-changed' && typeof params?.height === 'number' && Number.isFinite(params.height)) {
    height.value = Math.max(80, Math.min(480, Math.ceil(params.height)))
  } else if (id !== undefined && method === 'tools/call') {
    if (!ready || request || params?.name !== presentation.tool_name) {
      reject(-32602, 'Tool unavailable')
      return
    }
    const args = params.arguments ?? {}
    if (typeof args !== 'object' || Array.isArray(args)) {
      reject(-32602, 'Invalid tool arguments')
      return
    }
    const current = new AbortController()
    request = current
    working.value = true
    error.value = ''
    try {
      const result = await chatService.filterMcpApp(roomId, messageId, presentation.id, args, current.signal)
      if (current.signal.aborted) return
      table.value = result
      reply(toolResult(result))
    } catch {
      if (current.signal.aborted) return
      error.value = t('chat.mcpResult.unavailable')
      reject(-32000, error.value)
    } finally {
      if (request === current) {
        request = null
        working.value = false
      }
    }
  } else if (id !== undefined) {
    reject(-32601, 'Method unavailable')
  }
}

function onWindowMessage(event: MessageEvent<RpcMessage>): void {
  void onMessage(event)
}

onMounted(() => window.addEventListener('message', onWindowMessage))
onBeforeUnmount(() => {
  window.removeEventListener('message', onWindowMessage)
  closeFilters()
})
</script>

<style scoped>
.mcp-result { min-width: 0; }
.mcp-result-table td, .mcp-result-table th { white-space: normal; overflow-wrap: anywhere; }
.mcp-result-frame { width: 100%; border: 0; display: block; }
</style>
