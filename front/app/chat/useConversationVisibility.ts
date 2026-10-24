import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatInboxStore } from './stores/inbox'

interface ConversationVisibility {
  roomId: () => string | null
  visible: () => boolean
  canRead: () => boolean
  markRead: (messageId: string) => Promise<boolean>
  setDisplayedRoom: (roomId: string | null) => void
}

/** One presence contract for every surface displaying an internal conversation. */
export function useConversationVisibility(options: ConversationVisibility) {
  const inbox = useChatInboxStore()
  const mounted = ref(false)
  const pageVisible = ref(document.visibilityState === 'visible')
  const pageFocused = ref(document.hasFocus())
  const displayedRoomId = computed(() => mounted.value && pageVisible.value && options.visible() ? options.roomId() : null)
  const canRead = computed(() => displayedRoomId.value !== null && pageFocused.value && options.canRead())
  let latestMessageId: string | null = null

  watch(options.roomId, () => { latestMessageId = null }, { flush: 'sync' })
  watch(displayedRoomId, roomId => {
    inbox.setDisplayedRoom(roomId)
    options.setDisplayedRoom(roomId)
  }, { immediate: true, flush: 'sync' })

  async function markVisibleMessageRead(messageId: string): Promise<void> {
    latestMessageId = messageId
    if (!canRead.value) return
    try {
      if (await options.markRead(messageId)) await inbox.refreshSummary()
    } catch {
      // A new visible message, focus or visibility transition retries the acknowledgement.
    }
  }
  watch(canRead, readable => {
    if (readable && latestMessageId) void markVisibleMessageRead(latestMessageId)
  })

  function updateVisibility(): void { pageVisible.value = document.visibilityState === 'visible' }
  function updateFocus(): void { pageFocused.value = document.hasFocus() }
  onMounted(() => {
    updateVisibility()
    updateFocus()
    document.addEventListener('visibilitychange', updateVisibility)
    window.addEventListener('focus', updateFocus)
    window.addEventListener('blur', updateFocus)
    mounted.value = true
  })
  onBeforeUnmount(() => {
    mounted.value = false
    document.removeEventListener('visibilitychange', updateVisibility)
    window.removeEventListener('focus', updateFocus)
    window.removeEventListener('blur', updateFocus)
  })
  return { markVisibleMessageRead }
}
