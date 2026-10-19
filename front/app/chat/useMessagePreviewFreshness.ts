import { onBeforeUnmount, onMounted } from 'vue'
import { websocket } from '@/core/websocket'
import { chatService } from './services/chatService'

// The timeline keeps invalidation alive even when a cached message is unmounted.
const readers = new Set<() => void>()
export function invalidateMessagePreviewReaders(): void {
  chatService.invalidateMessagePreviews()
  for (const refresh of readers) refresh()
}
function onMemoryChange(event: { data?: { node_kind?: string } }): void {
  if (event.data?.node_kind === 'document') invalidateMessagePreviewReaders()
}

export function useMessagePreviewFreshness(refresh: () => void = () => undefined): void {
  onMounted(() => {
    if (!readers.size) {
      websocket.createWebsocket()
      websocket.onEvent('memory', 'update', onMemoryChange)
      websocket.onEvent('memory', 'delete', onMemoryChange)
      websocket.onConnect(invalidateMessagePreviewReaders)
    }
    readers.add(refresh)
  })
  onBeforeUnmount(() => {
    readers.delete(refresh)
    if (!readers.size) {
      websocket.offEvent('memory', 'update', onMemoryChange)
      websocket.offEvent('memory', 'delete', onMemoryChange)
      websocket.offConnect(invalidateMessagePreviewReaders)
      chatService.invalidateMessagePreviews()
    }
  })
}
