import type { MemoryGraphNode } from './types'

export interface GraphThumbnailCandidate {
  node: MemoryGraphNode
  key: string
}

const MAX_THUMBNAIL_BYTES = 512 * 1024
const MAX_UNAVAILABLE_ENTRIES = 3000
const GENERATION_CONCURRENCY = 2
const RECHECK_MILLISECONDS = 5 * 60_000
const GENERATION_POLL_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]

interface CachedThumbnail {
  url: string
  bytes: number
  aspect: number
}

function absent(error: unknown): boolean {
  if (typeof error !== 'object' || error === null || !('response' in error)) return false
  const response = error.response
  return typeof response === 'object' && response !== null && 'status' in response && response.status === 404
}

function pause(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return }
    const abort = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      reject(signal.reason)
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, milliseconds)
    signal.addEventListener('abort', abort, { once: true })
  })
}

/** Per-view cache and separate bounded queues for reads and expensive generation. */
export class GraphThumbnails {
  private desired = new Map<string, GraphThumbnailCandidate>()
  private cache = new Map<string, CachedThumbnail>()
  private pending = new Map<string, AbortController>()
  private generating = new Map<string, AbortController>()
  private generationQueue = new Map<string, GraphThumbnailCandidate>()
  private missing = new Map<string, number>()
  private generation = 0
  private cacheBytes = 0
  private retryTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly load: (node: MemoryGraphNode, signal: AbortSignal, generate: boolean) => Promise<Blob | null>,
    private readonly changed: (missing: boolean) => void,
    private readonly maxEntries = 64,
    private readonly concurrency = 8,
  ) {}

  url(key: string): string | null {
    return this.desired.has(key) ? this.cache.get(key)?.url ?? null : null
  }

  aspect(key: string): number { return this.cache.get(key)?.aspect ?? 1 }

  unavailable(key: string): boolean {
    const expires = this.missing.get(key)
    if (expires === undefined) return false
    if (expires > Date.now()) return true
    this.missing.delete(key)
    return false
  }

  update(candidates: GraphThumbnailCandidate[]): void {
    this.desired = new Map(candidates.map(candidate => [candidate.key, candidate]))
    for (const pending of [this.pending, this.generating]) {
      for (const [key, controller] of pending) {
        if (!this.desired.has(key)) { controller.abort(); pending.delete(key) }
      }
    }
    for (const key of this.generationQueue.keys()) {
      if (!this.desired.has(key)) this.generationQueue.delete(key)
    }
    for (const [key, entry] of [...this.cache]) {
      if (this.desired.has(key)) { this.cache.delete(key); this.cache.set(key, entry) }
    }
    this.pump()
  }

  /** A popover already obtained these authorized bytes: reuse them immediately. */
  accept(candidate: GraphThumbnailCandidate, blob: Blob): void {
    this.missing.delete(candidate.key)
    if (this.cache.has(candidate.key)) { this.changed(true); return }
    this.pending.get(candidate.key)?.abort()
    this.generating.get(candidate.key)?.abort()
    this.generating.delete(candidate.key)
    this.generationQueue.delete(candidate.key)
    const controller = new AbortController()
    const generation = this.generation
    this.pending.set(candidate.key, controller)
    void this.store(blob, candidate.key, controller, generation, true).then(() => {
      if (!controller.signal.aborted && generation === this.generation) this.changed(true)
    }).catch(() => undefined).finally(() => {
      if (this.pending.get(candidate.key) === controller) this.pending.delete(candidate.key)
      this.pump()
    })
  }

  clear(): void {
    this.generation++
    this.desired.clear()
    this.missing.clear()
    this.generationQueue.clear()
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.retryTimer = null
    for (const pending of [this.pending, this.generating]) {
      for (const controller of pending.values()) controller.abort()
      pending.clear()
    }
    for (const key of this.cache.keys()) this.evict(key)
  }

  private evict(key: string): void {
    const entry = this.cache.get(key)
    if (entry) { URL.revokeObjectURL(entry.url); this.cacheBytes -= entry.bytes }
    this.cache.delete(key)
  }

  private pump(): void {
    for (const candidate of this.desired.values()) {
      if (this.pending.size >= this.concurrency) break
      if (this.cache.has(candidate.key) || this.pending.has(candidate.key)
        || this.generating.has(candidate.key) || this.generationQueue.has(candidate.key)
        || this.unavailable(candidate.key)) continue
      // Documents use the existing authorized snapshot endpoint. Preparing a
      // snapshot belongs in the slow queue, even when its server derivative is cached.
      if (candidate.node.node_kind === 'document') {
        this.generationQueue.set(candidate.key, candidate)
        continue
      }
      const controller = new AbortController()
      this.pending.set(candidate.key, controller)
      void this.read(candidate, controller, this.generation)
    }
    for (const candidate of this.generationQueue.values()) {
      if (this.generating.size >= GENERATION_CONCURRENCY) break
      this.generationQueue.delete(candidate.key)
      const controller = new AbortController()
      this.generating.set(candidate.key, controller)
      void this.generate(candidate, controller, this.generation)
    }
  }

  private current(key: string, controller: AbortController, generation: number): boolean {
    return !controller.signal.aborted && generation === this.generation && this.desired.has(key)
  }

  private markMissing(key: string): void {
    this.missing.set(key, Date.now() + RECHECK_MILLISECONDS)
    if (this.missing.size > MAX_UNAVAILABLE_ENTRIES) {
      const oldest = this.missing.keys().next().value
      if (oldest !== undefined) this.missing.delete(oldest)
    }
    this.armRetry()
    this.changed(true)
  }

  private armRetry(): void {
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.retryTimer = null
    if (!this.missing.size) return
    // Retry even when the camera stays still; unavailable symbols must not be permanent.
    const earliest = Math.min(...this.missing.values())
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      for (const [candidate, expires] of this.missing) {
        if (expires <= Date.now()) this.missing.delete(candidate)
      }
      this.changed(true)
      this.pump()
      this.armRetry()
    }, Math.max(0, earliest - Date.now()) + 10)
  }

  private async read(candidate: GraphThumbnailCandidate, controller: AbortController, generation: number): Promise<void> {
    try {
      let blob: Blob | null
      let needsGeneration = false
      try { blob = await this.load(candidate.node, controller.signal, false) }
      catch (error) { if (!absent(error)) throw error; blob = null; needsGeneration = true }
      if (!this.current(candidate.key, controller, generation)) return
      if (blob) await this.store(blob, candidate.key, controller, generation)
      else if (needsGeneration) this.generationQueue.set(candidate.key, candidate)
      else this.markMissing(candidate.key)
    } catch {
      if (this.current(candidate.key, controller, generation)) this.markMissing(candidate.key)
    } finally {
      if (this.pending.get(candidate.key) === controller) this.pending.delete(candidate.key)
      this.pump()
    }
  }

  private async generate(candidate: GraphThumbnailCandidate, controller: AbortController, generation: number): Promise<void> {
    const deadline = setTimeout(() => controller.abort(), 120_000)
    try {
      let blob: Blob | null
      try { blob = await this.load(candidate.node, controller.signal, true) }
      catch (error) { if (!absent(error)) throw error; blob = null }
      // Attachments schedule a server job and return 404 until its derivative is ready.
      // Keep its generation slot until completion so we never enqueue hundreds of jobs.
      for (const delay of candidate.node.node_kind === 'attachment' ? GENERATION_POLL_DELAYS : []) {
        if (blob || !this.current(candidate.key, controller, generation)) break
        await pause(delay, controller.signal)
        try { blob = await this.load(candidate.node, controller.signal, false) }
        catch (error) { if (!absent(error)) throw error; blob = null }
      }
      if (!this.current(candidate.key, controller, generation)) return
      if (blob) await this.store(blob, candidate.key, controller, generation)
      else this.markMissing(candidate.key)
    } catch {
      if (generation === this.generation && this.desired.has(candidate.key)
        && this.generating.get(candidate.key) === controller) this.markMissing(candidate.key)
    } finally {
      clearTimeout(deadline)
      if (this.generating.get(candidate.key) === controller) this.generating.delete(candidate.key)
      this.pump()
    }
  }

  private async store(blob: Blob, key: string, controller: AbortController, generation: number, allowHidden = false): Promise<void> {
    if (blob.size <= 0 || blob.size > MAX_THUMBNAIL_BYTES || !blob.type.startsWith('image/')) throw new Error('Invalid thumbnail')
    const bitmap = await createImageBitmap(blob)
    let small = blob
    let aspect: number
    try {
      aspect = bitmap.width / bitmap.height
      // Already small derivatives need no canvas or re-encoding.
      if (Math.max(bitmap.width, bitmap.height) > 160) {
        const scale = 160 / Math.max(bitmap.width, bitmap.height)
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(bitmap.width * scale))
        canvas.height = Math.max(1, Math.round(bitmap.height * scale))
        aspect = canvas.width / canvas.height
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Missing canvas context')
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
        const encoded = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/webp', 0.85))
        if (!encoded) throw new Error('Thumbnail encoding failed')
        small = encoded
      }
    } finally { bitmap.close() }
    if (controller.signal.aborted || generation !== this.generation || (!allowHidden && !this.desired.has(key))) return
    this.evict(key)
    this.cache.set(key, { url: URL.createObjectURL(small), bytes: small.size, aspect })
    this.cacheBytes += small.size
    this.missing.delete(key)
    const maxBytes = Math.max(8 * 1024 * 1024, this.maxEntries * 128 * 1024)
    while (this.cache.size > this.maxEntries || this.cacheBytes > maxBytes) {
      const oldest = this.cache.keys().next().value
      if (oldest === undefined) break
      this.evict(oldest)
    }
    this.changed(false)
  }
}
