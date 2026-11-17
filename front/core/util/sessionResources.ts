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

const imageCaches = new Map<string, ReturnType<typeof createSessionReadCache<Blob | null>>>()

/** Share image bytes among readers of the same authorized endpoint. Callers own their object URLs. */
export function readSessionImage(
  group: string, key: string, path: string, signal?: AbortSignal, version?: string,
): Promise<Blob | null> {
  let cache = imageCaches.get(group)
  if (!cache) {
    cache = createSessionReadCache<Blob | null>({
      sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, group,
      maxAgeMs: (_key, blob) => blob ? 300_000 : 60_000,
      maxEntries: 64, maxBytes: 16 * 1024 * 1024, size: blob => blob?.size ?? 0,
    })
    imageCaches.set(group, cache)
  }
  return cache.read(key, sharedSignal => queuePreview(async () => {
    const { data, status } = await api.get<Blob>(path, {
      responseType: 'blob',
      signal: sharedSignal,
      validateStatus: status => (status >= 200 && status < 300) || status === 404,
    })
    return status === 404 ? null : data
  }, sharedSignal), signal, version)
}

export function onReadSessionChanged(listener: (authenticated: boolean) => void): () => void {
  const handler = (event: Event): void => listener(Boolean((event as CustomEvent<string | null>).detail))
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
  return () => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
}
