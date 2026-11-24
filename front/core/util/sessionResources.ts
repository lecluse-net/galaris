import { api, AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken, sessionGeneration } from '@/core/api'
import { createSessionReadCache, invalidateSessionReads } from './sessionReadCache'
import { queuePreview } from './previewQueue'
import { discardStoredImage, readStoredImage, removeStoredImages, saveStoredImage } from './sessionImageStorage'

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

function watchStoredSession(): void {
  let session = getStoredAccessToken() ? sessionGeneration() : null
  function synchronizeSession(authenticated: boolean): void {
    const next = authenticated ? sessionGeneration() : null
    if (next !== session && session !== null) void removeStoredImages(session)
    session = next
  }
  onReadSessionChanged(synchronizeSession)
  window.addEventListener('storage', event => {
    if (event.key === null || event.key === 'access_token' || event.key === 'galaris:session-generation') {
      synchronizeSession(Boolean(getStoredAccessToken()))
    }
  })
}

if (typeof window !== 'undefined') watchStoredSession()

/** Reuse image bytes across reloads for this session and authorized endpoint. */
export function readSessionImage(
  group: string, key: string, path: string,
  { signal, version, endpoint = 'default' }: { signal?: AbortSignal; version?: string; endpoint?: string } = {},
): Promise<Blob | null> {
  const scope = JSON.stringify([group, endpoint])
  let cache = imageCaches.get(scope)
  if (!cache) {
    cache = createSessionReadCache<Blob | null>({
      sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, group,
      maxAgeMs: (_key, blob) => blob ? Infinity : 60_000,
      maxEntries: 64, maxBytes: 16 * 1024 * 1024, size: blob => blob?.size ?? 0,
    })
    imageCaches.set(scope, cache)
  }
  const generation = getStoredAccessToken() ? sessionGeneration() : null
  return cache.read(key, async sharedSignal => {
    if (generation !== null) {
      const stored = await readStoredImage(scope, key)
      sharedSignal.throwIfAborted()
      if (stored?.session === generation) {
        if (version === undefined || stored.version === version) return stored.blob
        await discardStoredImage(stored)
      }
    }
    const { data, status } = await queuePreview(() => api.get<Blob>(path, {
      responseType: 'blob',
      signal: sharedSignal,
      headers: { 'Cache-Control': 'no-cache' },
      validateStatus: status => (status >= 200 && status < 300) || status === 404,
    }), sharedSignal)
    if (status === 404) return null
    if (generation !== null) {
      await saveStoredImage({ group, scope, key, session: generation, version, blob: data }, () =>
        !sharedSignal.aborted && generation === sessionGeneration() && Boolean(getStoredAccessToken()))
    }
    return data
  }, signal, version)
}

export async function invalidateSessionImages(group: string, key: string): Promise<void> {
  // Queue the disk deletion before listeners start reading the replacement.
  const removed = getStoredAccessToken() ? removeStoredImages(sessionGeneration(), { group, key }) : undefined
  invalidateSessionReads(group, key)
  await removed
}

export function onReadSessionChanged(listener: (authenticated: boolean) => void): () => void {
  const handler = (event: Event): void => listener(Boolean((event as CustomEvent<string | null>).detail))
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
  return () => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, handler)
}
