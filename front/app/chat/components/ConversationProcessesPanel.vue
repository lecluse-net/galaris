<template>
  <section class="conversation-processes-panel">
    <div v-if="!canRead" class="conversation-work-state text-grey-7">
      <q-icon name="lock" size="28px" />
      <span>{{ t('chat.processesUnavailable') }}</span>
    </div>
    <div v-else-if="loading && !processes.length" class="conversation-work-state text-grey-7">
      <q-spinner color="primary" size="28px" />
    </div>
    <div v-else-if="error && !processes.length" class="conversation-work-state text-negative">
      <q-icon name="warning" size="28px" />
      <span>{{ error }}</span>
      <q-btn flat dense color="negative" :label="t('chat.retryProcesses')" @click="load(true)" />
    </div>
    <div v-else-if="!processes.length" class="conversation-work-state text-grey-7">
      <q-icon name="schema" size="28px" />
      <span>{{ t('chat.noProcesses') }}</span>
    </div>
    <q-list ref="processList" v-else separator class="conversation-work-list" @scroll.passive="onScroll">
      <q-item
        v-for="run in processes"
        :key="run.id"
        clickable
        v-ripple
        :aria-label="t('chat.openProcess', { label: processLabel(run) })"
        @click="openProcess(run)"
      >
        <q-item-section avatar>
          <q-avatar :color="statusColor(run.status)" text-color="white" size="34px">
            <q-spinner v-if="isActive(run.status)" color="white" size="20px" />
            <q-icon v-else :name="statusIcon(run.status)" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-medium">{{ processLabel(run) }}</q-item-label>
          <q-item-label caption>
            {{ formatDate(run.created_at) }} · {{ run.tool_code }}
          </q-item-label>
          <q-item-label v-if="run.error_message" caption class="text-negative ellipsis-2-lines">
            {{ run.error_message }}
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-chip dense :color="statusColor(run.status)" text-color="white">
            <q-spinner v-if="isActive(run.status)" color="white" size="1em" class="q-mr-xs" />
            {{ statusLabel(run.status) }}
          </q-chip>
        </q-item-section>
      </q-item>
      <div v-if="loadingMore" class="conversation-work-loader"><q-spinner color="primary" size="20px" /></div>
      <div v-if="error && processes.length" class="conversation-work-inline-error text-negative"><q-icon name="warning" size="14px" /> {{ error }}</div>
    </q-list>

    <ConversationProcessDialog
      v-model="detailDialogOpen"
      :process="selectedProcess"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { websocket } from '@/core/websocket'
import { chatService } from '../services/chatService'
import type { ConversationProcess, ConversationProcessStatus } from '../types'
import ConversationProcessDialog from './ConversationProcessDialog.vue'

const props = withDefaults(defineProps<{
  roomId: string
  fromMessageId?: string | null
  viewerAgentId?: number | null
  canRead?: boolean
}>(), {
  fromMessageId: null,
  viewerAgentId: null,
  canRead: false,
})

const emit = defineEmits<{ 'has-items': [value: boolean] }>()
const { t, te, locale } = useI18n()
const processes = ref<ConversationProcess[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const detailDialogOpen = ref(false)
const selectedProcessId = ref<string | null>(null)
let requestSequence = 0
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let scrollFrame: number | null = null
let scrollResizeObserver: ResizeObserver | null = null
let pendingBottomScroll = false
let subscribed = false
const PROCESS_PAGE_SIZE = 10
const hasMore = computed(() => processes.value.length < total.value)
const selectedProcess = computed(() => (
  processes.value.find(run => run.id === selectedProcessId.value) ?? null
))
const processList = useTemplateRef<{ $el: HTMLElement }>('processList')

function isActive(status: ConversationProcessStatus): boolean {
  return status === 'queued' || status === 'running'
}

function statusLabel(status: ConversationProcessStatus): string {
  if (isActive(status)) return t('chat.processInProgress')
  const key = `processes.statuses.${status}`
  return te(key) ? t(key) : status
}

function statusColor(status: ConversationProcessStatus): string {
  return ({
    success: 'positive',
    error: 'negative',
    cancelled: 'grey',
    running: 'primary',
    waiting: 'orange',
    queued: 'primary',
    cancelling: 'warning',
    unknown: 'dark',
  } as Record<string, string>)[status] ?? 'grey'
}

function statusIcon(status: ConversationProcessStatus): string {
  return ({
    success: 'check_circle',
    error: 'error',
    cancelled: 'cancel',
    running: 'play_circle',
    waiting: 'hourglass_top',
    queued: 'schedule',
    cancelling: 'pending',
    unknown: 'help',
  } as Record<string, string>)[status] ?? 'help'
}

function processLabel(run: ConversationProcess): string {
  return run.process_label || run.workflow_id || `#${run.process_id}`
}

function openProcess(run: ConversationProcess): void {
  selectedProcessId.value = run.id
  detailDialogOpen.value = true
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

async function load(reset = true, scrollAfterLoad = false): Promise<void> {
  const sequence = ++requestSequence
  if (!props.canRead || !props.fromMessageId) {
    processes.value = []
    total.value = 0
    page.value = 1
    error.value = ''
    return
  }
  if (reset) loadingMore.value = false
  loading.value = true
  try {
    const knownIds = new Set(processes.value.map(run => run.id))
    const requestedPageSize = reset ? PROCESS_PAGE_SIZE : Math.max(PROCESS_PAGE_SIZE, page.value * PROCESS_PAGE_SIZE)
    const result = await chatService.processes(
      props.roomId,
      props.fromMessageId,
      1,
      requestedPageSize,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    processes.value = result.items
    total.value = result.total
    if (reset) page.value = 1
    error.value = ''
    if (scrollAfterLoad || result.items.some(run => !knownIds.has(run.id))) {
      scrollProcessesToBottom()
    }
  } catch (caught) {
    if (sequence === requestSequence) {
      error.value = apiErrorDetail(caught) ?? t('chat.processesLoadError')
    }
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (loading.value || loadingMore.value || !hasMore.value || !props.fromMessageId) return
  const sequence = requestSequence
  loadingMore.value = true
  try {
    const nextPage = page.value + 1
    const result = await chatService.processes(
      props.roomId,
      props.fromMessageId,
      nextPage,
      PROCESS_PAGE_SIZE,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    const knownIds = new Set(processes.value.map(run => run.id))
    processes.value = [...processes.value, ...result.items.filter(run => !knownIds.has(run.id))]
    total.value = result.total
    page.value = nextPage
    error.value = ''
  } catch (caught) {
    if (sequence === requestSequence) error.value = apiErrorDetail(caught) ?? t('chat.processesLoadError')
  } finally {
    if (sequence === requestSequence) loadingMore.value = false
  }
}

function onScroll(event: Event): void {
  const target = event.currentTarget as HTMLElement
  if (target.scrollHeight - target.scrollTop - target.clientHeight <= 80) void loadMore()
}

function disconnectScrollResizeObserver(): void {
  scrollResizeObserver?.disconnect()
  scrollResizeObserver = null
}

function observeScrollResize(): void {
  if (scrollResizeObserver) return
  const target = processList.value?.$el
  if (!target) return
  scrollResizeObserver = new ResizeObserver(() => {
    if (pendingBottomScroll) scrollProcessesToBottom()
  })
  scrollResizeObserver.observe(target)
}

function scrollProcessesToBottom(): void {
  pendingBottomScroll = true
  void nextTick(() => {
    observeScrollResize()
    if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
    scrollFrame = window.requestAnimationFrame(() => {
      const target = processList.value?.$el
      if (!target || target.clientHeight === 0) {
        scrollFrame = null
        return
      }
      target.scrollTop = target.scrollHeight
      scrollFrame = window.requestAnimationFrame(() => {
        const currentTarget = processList.value?.$el
        if (currentTarget) currentTarget.scrollTop = currentTarget.scrollHeight
        pendingBottomScroll = false
        disconnectScrollResizeObserver()
        scrollFrame = null
      })
    })
  })
}

defineExpose({ scrollToBottom: scrollProcessesToBottom })

function scheduleRefresh(): void {
  if (!props.canRead) return
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { void load(false) }, 250)
}

function subscribe(): void {
  if (subscribed) return
  websocket.createWebsocket()
  websocket.onEvent('process_run', 'create', scheduleRefresh)
  websocket.onEvent('process_run', 'update', scheduleRefresh)
  websocket.onEvent('process_run', 'delete', scheduleRefresh)
  websocket.onConnect(scheduleRefresh)
  subscribed = true
}

function unsubscribe(): void {
  if (!subscribed) return
  websocket.offEvent('process_run', 'create', scheduleRefresh)
  websocket.offEvent('process_run', 'update', scheduleRefresh)
  websocket.offEvent('process_run', 'delete', scheduleRefresh)
  websocket.offConnect(scheduleRefresh)
  subscribed = false
}

watch(() => props.canRead && processes.value.length > 0, value => emit('has-items', value), { immediate: true, flush: 'sync' })

watch(
  () => [props.roomId, props.fromMessageId, props.viewerAgentId, props.canRead] as const,
  ([roomId, , viewerAgentId, canRead], previous) => {
    if (roomId !== previous?.[0] || viewerAgentId !== previous?.[2] || canRead !== previous?.[3]) {
      processes.value = []
      total.value = 0
    }
    if (canRead) subscribe()
    else unsubscribe()
    page.value = 1
    void load(true, true)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  requestSequence += 1
  if (refreshTimer) window.clearTimeout(refreshTimer)
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  disconnectScrollResizeObserver()
  unsubscribe()
})
</script>

<style scoped>
.conversation-processes-panel { min-width: 0; color: var(--chat-text, #252b36); background: var(--chat-surface, #fff); }
.conversation-work-state { display: flex; min-height: 120px; align-items: center; justify-content: center; flex-direction: column; gap: 8px; padding: 18px; text-align: center; font-size: .78rem; }
.conversation-work-list { max-height: 280px; overflow-y: auto; }
.conversation-work-loader { display: flex; min-height: 36px; align-items: center; justify-content: center; }
.conversation-work-inline-error { padding: 7px 10px; font-size: .75rem; }
</style>
