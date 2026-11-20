import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import { websocket } from '@/core/websocket'
import { chatService } from './services/chatService'
import type { DeepEvent, DeepRoom } from './types'

export function useDeepConversation(currentRoom: () => string | null) {
  const room = shallowRef<DeepRoom | null>(null)
  const events = shallowRef<Record<string, DeepEvent[]>>({})
  const error = shallowRef(false)
  const opened = new Set<string>()
  let controller = new AbortController()
  let refreshTimer: ReturnType<typeof setTimeout> | undefined
  let catchUpTimer: ReturnType<typeof setInterval> | undefined
  let loading = false
  let pending = false

  async function refresh() {
    const roomId = currentRoom()
    const signal = controller.signal
    if (!roomId || signal.aborted) return
    if (loading) {
      pending = true
      return
    }
    loading = true
    try {
      const result = await chatService.deepRoom(roomId, signal)
      if (signal.aborted) return
      room.value = result
      const requested = result.submissions.filter(item =>
        item.sequence && (opened.has(item.id) || item.state === 'running' || !item.response_message_id),
      )
      await Promise.all(requested.map(async item => {
        const previous = events.value[item.id] ?? []
        const cursor = previous.at(-1)?.sequence ?? 0
        if (cursor >= item.sequence) return
        const batch = await chatService.deepEvents(roomId, item.id, cursor, signal)
        if (signal.aborted || !batch.length) return
        events.value = { ...events.value, [item.id]: [...previous, ...batch] }
        if (batch[batch.length - 1]!.sequence < item.sequence) pending = true
      }))
      if (!signal.aborted) error.value = false
    } catch {
      if (!signal.aborted) error.value = true
    } finally {
      loading = false
      if (pending) {
        pending = false
        scheduleRefresh()
      }
    }
  }

  function scheduleRefresh() {
    if (!currentRoom()) return
    refreshTimer ??= setTimeout(() => {
      refreshTimer = undefined
      void refresh()
    }, 180)
  }

  function onActivity(event: { data?: { room_id?: string } }) {
    if (event.data?.room_id === currentRoom()) scheduleRefresh()
  }

  function openActivity(id: string) {
    opened.add(id)
    scheduleRefresh()
  }

  watch(currentRoom, () => {
    controller.abort()
    controller = new AbortController()
    room.value = null
    events.value = {}
    error.value = false
    opened.clear()
    void refresh()
  }, { immediate: true })

  onMounted(() => {
    websocket.onEvent('chat', 'deep', onActivity)
    websocket.onConnect(scheduleRefresh)
    catchUpTimer = setInterval(() => {
      if (room.value?.enabled || room.value?.submissions.some(item => item.state === 'running')) scheduleRefresh()
    }, 5000)
  })
  onBeforeUnmount(() => {
    controller.abort()
    clearTimeout(refreshTimer)
    clearInterval(catchUpTimer)
    websocket.offEvent('chat', 'deep', onActivity)
    websocket.offConnect(scheduleRefresh)
  })
  return { room, events, error, refresh, scheduleRefresh, openActivity }
}
