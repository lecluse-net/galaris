<template>
  <div class="room-discussion">
    <q-banner v-if="error" class="q-ma-sm">
      {{ error }}
      <template #action><q-btn flat :label="t('common.retry')" @click="loadMessages(failedDirection, true)" /></template>
    </q-banner>
    <q-scroll-area ref="scrollArea" class="col" tabindex="0" @scroll="onScroll"
      @wheel.passive="onWheel" @touchstart.passive="beginNavigation" @pointerdown="beginNavigation"
      @keydown="onKeydown">
      <MessageTimeline :room-id="room.id" :messages="messages" :agent-id="room.agent_id"
        :agent-name="room.agent_name" :activity="[]" :live-round="null" :allow-reply="false"
        :loading="loading" @block-rendered="keepReadingPosition" @layout-changed="keepReadingPosition" />
    </q-scroll-area>
    <div v-if="loading" class="room-discussion__loading" role="status" :aria-label="t('chat.loadingRoom')">
      <q-spinner color="primary" size="24px" />
    </div>
    <ScrollToBottomButton :visible="showScrollToBottom" @click="goToBottom" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QScrollArea } from 'quasar'
import MessageTimeline from './MessageTimeline.vue'
import ScrollToBottomButton from './ScrollToBottomButton.vue'
import { chatService } from '../services/chatService'
import type { MessengerMessage, MessengerRoom } from '../types'

const props = defineProps<{ room: MessengerRoom }>()
const { t } = useI18n()
const scrollArea = useTemplateRef<QScrollArea>('scrollArea')
const messages = ref<MessengerMessage[]>([])
const loading = ref(false)
const error = ref('')
const showScrollToBottom = ref(false)
type Direction = 'older' | 'recent'
type ScrollInfo = ReturnType<QScrollArea['getScroll']>
const failedDirection = ref<Direction>('recent')
let generation = 0
let historyPage = 1
let historyCursor: string | null = null
let hasOlder = false
let initialized = false
let restoring = false
let followingBottom = true
let navigating = false
let navigationRevision = 0
let lastEdge: Direction | null = null
let lastRecentLoad = 0
let recentRequested = false
let layoutFrame: number | null = null
let anchor: { id: string; offset: number } | null = null
const frame = (): Promise<void> => new Promise(resolve => requestAnimationFrame(() => resolve()))
const atBottom = (info: ScrollInfo): boolean => info.verticalSize - info.verticalContainerSize - info.verticalPosition <= 48

function captureAnchor(): void {
  const container = scrollArea.value?.getScrollTarget()
  if (!container) return
  const top = container.getBoundingClientRect().top
  const row = [...container.querySelectorAll<HTMLElement>('[data-message-id]')]
    .find(element => element.getBoundingClientRect().bottom > top)
  anchor = row ? { id: row.dataset.messageId!, offset: row.getBoundingClientRect().top - top } : null
}

function restoreReadingPosition(): void {
  const scroll = scrollArea.value
  if (!scroll) return
  const container = scroll.getScrollTarget()
  if (followingBottom) scroll.setScrollPosition('vertical', container.scrollHeight, 0)
  else if (anchor) {
    const row = [...container.querySelectorAll<HTMLElement>('[data-message-id]')]
      .find(element => element.dataset.messageId === anchor?.id)
    if (row) scroll.setScrollPosition('vertical', container.scrollTop
      + row.getBoundingClientRect().top - container.getBoundingClientRect().top - anchor.offset, 0)
  }
}

function keepReadingPosition(): void {
  if (layoutFrame !== null) cancelAnimationFrame(layoutFrame)
  layoutFrame = requestAnimationFrame(() => {
    layoutFrame = null
    if (!restoring) restoreReadingPosition()
  })
}

async function loadMessages(direction: Direction, force = false): Promise<void> {
  if (loading.value) {
    if (direction === 'recent' && force) recentRequested = true
    return
  }
  if (direction === 'older' && !hasOlder) return
  if (direction === 'recent' && !force && initialized && Date.now() - lastRecentLoad < 1500) return
  const current = generation
  const initial = !initialized
  const pageNumber = direction === 'older' ? historyPage + 1 : 1
  if (direction === 'older') captureAnchor()
  loading.value = true
  error.value = ''
  failedDirection.value = direction
  if (direction === 'recent') lastRecentLoad = Date.now()
  try {
    const page = await chatService.messages(props.room.id, pageNumber, 50, null,
      direction === 'older' ? historyCursor : null)
    if (current !== generation) return
    if (!followingBottom) captureAnchor()
    const revision = navigationRevision
    messages.value = [...new Map([...messages.value, ...page.items].map(item => [item.id, item])).values()]
      .sort((left, right) => left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id))
    if (initial || direction === 'older' || historyPage === 1) {
      hasOlder = page.provider_history ? page.history_has_more : pageNumber * 50 < page.total || page.history_has_more
      historyPage = pageNumber
      historyCursor = page.history_next_cursor
    }
    restoring = true
    await nextTick()
    if (current !== generation) return
    if (revision === navigationRevision) restoreReadingPosition()
    await frame()
    if (current === generation) {
      if (revision === navigationRevision) restoreReadingPosition()
      initialized = true
    }
  } catch {
    if (current === generation) error.value = t('chat.error')
  } finally {
    if (current === generation) {
      loading.value = false
      restoring = false
      if (recentRequested) { recentRequested = false; void loadMessages('recent', true) }
    }
  }
}

function beginNavigation(): void {
  navigationRevision++
  navigating = true
  lastEdge = null
  followingBottom = false
  restoring = false
  captureAnchor()
}

function onScroll(info: ScrollInfo): void {
  if (!initialized || restoring) return
  const bottom = atBottom(info)
  if (!navigating && followingBottom) {
    if (!bottom) keepReadingPosition()
    return
  }
  followingBottom = bottom
  showScrollToBottom.value = !bottom
  if (!bottom) captureAnchor()
  if (!navigating || error.value) return
  const edge = bottom && info.verticalPosition > 120 ? 'recent' : info.verticalPosition <= 120 && hasOlder ? 'older' : null
  if (edge && edge !== lastEdge) { lastEdge = edge; void loadMessages(edge) }
  else if (!edge) lastEdge = null
}

function onWheel(event: WheelEvent): void {
  beginNavigation()
  const info = scrollArea.value?.getScroll()
  if (!initialized || !info) return
  if (event.deltaY > 0 && atBottom(info)) { followingBottom = true; void loadMessages('recent') }
  else if (event.deltaY < 0 && info.verticalPosition <= 120) void loadMessages('older')
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target
  if (target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select, button, a'))) return
  const scroll = scrollArea.value
  if (!scroll) return
  const container = scroll.getScrollTarget()
  const page = Math.max(40, container.clientHeight - 48)
  const positions: Record<string, number> = {
    ArrowUp: container.scrollTop - 40, ArrowDown: container.scrollTop + 40,
    PageUp: container.scrollTop - page, PageDown: container.scrollTop + page,
    Home: 0, End: container.scrollHeight,
    ' ': container.scrollTop + (event.shiftKey ? -page : page),
  }
  const position = positions[event.key]
  if (position === undefined) return
  event.preventDefault()
  beginNavigation()
  scroll.setScrollPosition('vertical', position, 0)
  captureAnchor()
  if (event.key === 'End') { followingBottom = true; void loadMessages('recent') }
}

function goToBottom(): void {
  followingBottom = true
  navigating = false
  anchor = null
  showScrollToBottom.value = false
  keepReadingPosition()
  void loadMessages('recent', true)
}

watch(() => props.room.id, () => {
  generation++
  messages.value = []
  loading.value = false
  error.value = ''
  showScrollToBottom.value = false
  initialized = false
  restoring = false
  followingBottom = true
  navigating = false
  lastEdge = null
  anchor = null
  historyPage = 1
  historyCursor = null
  hasOlder = false
  lastRecentLoad = 0
  recentRequested = false
  void loadMessages('recent')
}, { immediate: true })

onBeforeUnmount(() => {
  generation++
  if (layoutFrame !== null) cancelAnimationFrame(layoutFrame)
})
</script>

<style scoped>
.room-discussion { display: flex; flex-direction: column; position: relative; height: min(72dvh, 800px); min-height: 0; }
.room-discussion__loading { position: absolute; top: 8px; left: 50%; transform: translateX(-50%); pointer-events: none; }
@media (max-width: 1023px) { .room-discussion { height: calc(100dvh - 57px); } }
</style>
