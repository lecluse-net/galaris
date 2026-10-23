import { onBeforeUnmount, onMounted } from 'vue'
import { websocket } from '@/core/websocket'
import { chatService } from './services/chatService'

// The timeline keeps invalidation alive even when a cached message is unmounted.
const readers = new Set<() => void>()
export function invalidateMessagePreviewReaders(): void {
  chatService.invalidateMessagePreviews()
  for (const refresh of readers) refresh()
}

export function useMessagePreviewFreshness(refresh: () => void = () => undefined): void {
  onMounted(() => {
    if (!readers.size) {
      websocket.createWebsocket()
      websocket.onEvent('document', 'update', invalidateMessagePreviewReaders)
      websocket.onEvent('document', 'delete', invalidateMessagePreviewReaders)
      websocket.onConnect(invalidateMessagePreviewReaders)
    }
    readers.add(refresh)
  })
  onBeforeUnmount(() => {
    readers.delete(refresh)
    if (!readers.size) {
      websocket.offEvent('document', 'update', invalidateMessagePreviewReaders)
      websocket.offEvent('document', 'delete', invalidateMessagePreviewReaders)
      websocket.offConnect(invalidateMessagePreviewReaders)
      chatService.invalidateMessagePreviews()
    }
  })
}
