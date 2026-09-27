import type { AxiosResponse } from 'axios'

interface CacheControl { clear: (key?: string) => void; sessionChanged: (event: Event) => void }
const groups = new Map<string, Set<CacheControl>>()
const listeners = new Map<string, Set<(key?: string) => void>>()
const sessionEvents = new Set<string>()

export function invalidateSessionReads(group: string, key?: string): void {
  for (const cache of groups.get(group) ?? []) cache.clear(key)
  for (const listener of listeners.get(group) ?? []) listener(key)
}

export function onSessionReadInvalidation(group: string, listener: (key?: string) => void): () => void {
  const subscribers = listeners.get(group) ?? new Set()
  listeners.set(group, subscribers)
  subscribers.add(listener)
  return () => {
    subscribers.delete(listener)
    if (!subscribers.size) listeners.delete(group)
  }
}

interface CacheOptions<T> {
  sessionEvent: string
  sessionKey?: () => string
  group: string
  maxAgeMs: number
  maxEntries: number
  maxBytes?: number
  size?: (value: T) => number
}

/** Bounded, session-local reads. Callers choose freshness and own mutable copies/URLs. */
export function createSessionReadCache<T>(options: CacheOptions<T>): {
  read: (key: string, load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal) => Promise<T>
} {
  const values = new Map<string, { value: T; expires: number; bytes: number }>()
  const pending = new Map<string, { controller: AbortController; promise: Promise<T>; readers: number }>()
  let bytes = 0
  function remove(key: string): void {
    bytes -= values.get(key)?.bytes ?? 0
    values.delete(key)
  }
  function clear(key?: string): void {
    for (const id of key === undefined ? [...values.keys()] : [key]) remove(id)
    for (const id of key === undefined ? [...pending.keys()] : [key]) {
      const request = pending.get(id)
      pending.delete(id)
      request?.controller.abort()
    }
  }
  const caches = groups.get(options.group) ?? new Set()
  let sessionKey = options.sessionKey?.()
  function synchronizeSession(): void {
    const next = options.sessionKey?.()
    if (next !== sessionKey) clear()
    sessionKey = next
  }
  caches.add({ clear, sessionChanged(event) {
    const next = options.sessionKey?.()
    // Ordinary access-token renewal must not cancel the API request renewing it.
    if (!options.sessionKey || next !== sessionKey || (event as CustomEvent).detail === null) clear()
    sessionKey = next
  } })
  groups.set(options.group, caches)
  if (!sessionEvents.has(options.sessionEvent)) {
    window.addEventListener(options.sessionEvent, event => {
      for (const caches of groups.values()) for (const cache of caches) cache.sessionChanged(event)
    })
    sessionEvents.add(options.sessionEvent)
  }
  function remember(key: string, value: T): void {
    const size = options.size?.(value) ?? 1
    const limit = options.maxBytes ?? Infinity
    if (options.maxAgeMs <= 0 || size > limit) return
    for (const [id, entry] of values) if (entry.expires <= Date.now()) remove(id)
    remove(key)
    values.set(key, { value, expires: Date.now() + options.maxAgeMs, bytes: size })
    bytes += size
    while (values.size > options.maxEntries || bytes > limit) {
      const oldest = values.keys().next().value
      if (oldest === undefined) break
      remove(oldest)
    }
  }
  return {
    async read(key, load, signal) {
      synchronizeSession()
      signal?.throwIfAborted()
      const cached = values.get(key)
      if (cached && cached.expires > Date.now()) {
        await Promise.resolve()
        synchronizeSession()
        signal?.throwIfAborted()
        if (values.get(key) !== cached) throw new DOMException('Read invalidated', 'AbortError')
        values.delete(key)
        values.set(key, cached)
        return cached.value
      }
      remove(key)
      let request = pending.get(key)
      if (!request) {
        const controller = new AbortController()
        const promise = Promise.resolve().then(() => {
          controller.signal.throwIfAborted()
          return load(controller.signal)
        }).then(value => {
          synchronizeSession()
          controller.signal.throwIfAborted()
          remember(key, value)
          return value
        }).finally(() => {
          if (pending.get(key)?.controller === controller) pending.delete(key)
        })
        request = { controller, promise, readers: 0 }
        pending.set(key, request)
      }
      const shared = request
      shared.readers++
      return new Promise<T>((resolve, reject) => {
        let settled = false
        function finish(): boolean {
          if (settled) return false
          settled = true
          signal?.removeEventListener('abort', abort)
          shared.controller.signal.removeEventListener('abort', abort)
          if (--shared.readers === 0 && pending.get(key) === shared) {
            pending.delete(key)
            shared.controller.abort()
          }
          return true
        }
        function abort(): void {
          if (finish()) reject(new DOMException('Read cancelled', 'AbortError'))
        }
        signal?.addEventListener('abort', abort, { once: true })
        shared.controller.signal.addEventListener('abort', abort, { once: true })
        shared.promise.then(value => { if (finish()) resolve(value) }, error => { if (finish()) reject(error) })
      })
    },
  }
}

/** JSON catalogues keep response metadata, but never share editable objects with consumers. */
export function createSessionResponseCache<T>(options: { group: string; sessionEvent: string; sessionKey?: () => string; maxAgeMs: number }): {
  read: (load: (signal: AbortSignal) => Promise<AxiosResponse<T>>, force?: boolean) => Promise<AxiosResponse<T>>
} {
  const cache = createSessionReadCache<AxiosResponse<T>>({
    ...options, maxEntries: 1, maxBytes: 16 * 1024 * 1024,
    size: response => JSON.stringify(response.data).length * 2,
  })
  return {
    async read(load, force = false) {
      if (force) invalidateSessionReads(options.group)
      const response = await cache.read('all', load)
      return { ...response, data: structuredClone(response.data) }
    },
  }
}
