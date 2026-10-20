import { api, AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { createSessionReadCache } from './sessionReadCache'
import { queuePreview } from './previewQueue'

/** Small JSON catalogues, scoped to the current authenticated session. */
export function createSessionCatalogueCache<T>(group: string, maxAgeMs: number) {
  const cache = createSessionReadCache<T>({
    sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, group,
    maxAgeMs, maxEntries: 16, maxBytes: 8 * 1024 * 1024,
    size: value => JSON.stringify(value).length * 2,
  })
  return {
    async read(key: string, load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
      return structuredClone(await cache.read(key, load, signal))
    },
  }
}

/** Cache authenticated image bytes; mounted consumers own and revoke their object URLs. */
export function createSessionImageCache(group: string, maxAgeMs: number) {
  const cache = createSessionReadCache<Blob>({
    sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, group,
    maxAgeMs, maxEntries: 64, maxBytes: 16 * 1024 * 1024, size: blob => blob.size,
  })
  return {
    read(path: string, signal: AbortSignal): Promise<Blob> {
      return cache.read(path, sharedSignal => queuePreview(async () => (
        await api.get<Blob>(path, { responseType: 'blob', signal: sharedSignal })
      ).data, sharedSignal), signal)
    },
  }
}

export function onReadSessionChanged(listener: (authenticated: boolean) => void): () => void {
  const handler = (event: Event): void => listener(Boolean((event as CustomEvent<string | null>).detail))
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
  return () => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
}
