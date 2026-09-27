import { computed, ref, shallowRef, watch, type ComputedRef, type Ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { onSessionReadInvalidation } from '@/core/util/facade'
import { chatService } from './services/chatService'

interface AvatarEntry {
  users: number
  url: Ref<string>
  blob: Blob | null
  request: AbortController | null
}

// Bound by mounted consumers, never retained across a visit to another page.
const avatars = new Map<number, AvatarEntry>()
let unsubscribe: (() => void) | undefined

function clear(entry: AvatarEntry): void {
  entry.request?.abort()
  entry.request = null
  if (entry.url.value) URL.revokeObjectURL(entry.url.value)
  entry.url.value = ''
  entry.blob = null
}

async function load(id: number, entry: AvatarEntry, keepImage = false): Promise<void> {
  if (!keepImage) clear(entry)
  const request = new AbortController()
  entry.request = request
  try {
    const blob = await chatService.agentAvatarBlob(id, request.signal)
    if (!request.signal.aborted && avatars.get(id) === entry && entry.blob !== blob) {
      if (entry.url.value) URL.revokeObjectURL(entry.url.value)
      entry.url.value = URL.createObjectURL(blob)
      entry.blob = blob
    }
  } catch {
    // Initials remain available; a new visit retries absent or unavailable images.
    if (!request.signal.aborted && avatars.get(id) === entry) {
      if (entry.url.value) URL.revokeObjectURL(entry.url.value)
      entry.url.value = ''
      entry.blob = null
    }
  } finally {
    if (entry.request === request) entry.request = null
  }
}

function onSessionChanged(event: Event): void {
  for (const [id, entry] of avatars) {
    clear(entry)
    if ((event as CustomEvent<string | null>).detail) void load(id, entry)
  }
}

function acquire(id: number): AvatarEntry {
  let entry = avatars.get(id)
  if (!entry) {
    if (!avatars.size) {
      window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
      unsubscribe = onSessionReadInvalidation('agent-avatar', key => {
        for (const [id, current] of avatars) if (key === undefined || key === String(id)) void load(id, current)
      })
    }
    entry = { users: 0, url: ref(''), blob: null, request: null }
    avatars.set(id, entry)
    void load(id, entry)
  } else if (!entry.request) {
    // A newly displayed bubble consults the short-lived, endpoint-specific blob cache.
    void load(id, entry, true)
  }
  entry.users++
  return entry
}

function release(id: number, entry: AvatarEntry): void {
  if (--entry.users) return
  clear(entry)
  avatars.delete(id)
  if (!avatars.size) {
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onSessionChanged)
    unsubscribe?.()
    unsubscribe = undefined
  }
}

export function useChatAvatar(agentId: () => number): ComputedRef<string> {
  const current = shallowRef<AvatarEntry>()
  watch(agentId, (id, _previous, onCleanup) => {
    const entry = acquire(id)
    current.value = entry
    onCleanup(() => release(id, entry))
  }, { immediate: true })
  return computed(() => current.value?.url.value ?? '')
}
