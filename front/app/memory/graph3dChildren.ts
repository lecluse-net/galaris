import type { MemoryGraphCursor, MemoryGraphPage } from './types'

interface Region { cursor: MemoryGraphCursor | null; done: boolean; failedPose: string | null; pages: number }

/** Finish the direct children of nearby directories, at most two pages at a
 * time. Moving away stops subsequent pages; context disposal aborts all. */
export class Graph3dChildren {
  private readonly controller = new AbortController()
  private readonly regions = new Map<string, Region>()
  private readonly pending = new Set<string>()
  private wanted = new Map<string, string>()
  private readonly fetch: (id: string, cursor: MemoryGraphCursor | null, signal: AbortSignal) => Promise<MemoryGraphPage>
  private readonly merge: (page: MemoryGraphPage) => Promise<void>
  private readonly failure: (error: unknown) => void
  private readonly progress: () => void
  constructor(
    fetch: (id: string, cursor: MemoryGraphCursor | null, signal: AbortSignal) => Promise<MemoryGraphPage>,
    merge: (page: MemoryGraphPage) => Promise<void>,
    failure: (error: unknown) => void,
    progress: () => void = () => {},
  ) { this.fetch = fetch; this.merge = merge; this.failure = failure; this.progress = progress }

  get expanded(): Record<string, number> {
    return Object.fromEntries([...this.regions].filter(([, region]) => region.pages).map(([id, region]) => [id, region.pages]))
  }

  get completed(): ReadonlySet<string> {
    return new Set([...this.regions].filter(([, region]) => region.done).map(([id]) => id))
  }

  reconcile(id: string, pagesBefore: number, cursor: MemoryGraphCursor | null, pages: number): void {
    const region = this.regions.get(id)
    if (!region || this.pending.has(id) || region.pages !== pagesBefore) return
    this.regions.set(id, { cursor, done: cursor === null, pages, failedPose: null })
  }

  forget(id: string): void { this.wanted.delete(id); this.regions.delete(id) }

  update(ids: readonly string[], pose: string): void {
    if (this.controller.signal.aborted) return
    this.wanted = new Map(ids.map(id => [id, pose]))
    this.pump()
  }

  private pump(): void {
    if (this.controller.signal.aborted) return
    for (const [id, pose] of this.wanted) {
      if (this.pending.size >= 2) break
      void this.load(id, pose)
    }
  }

  async load(id: string, pose: string): Promise<void> {
    if (this.controller.signal.aborted || this.pending.has(id)) return
    const region = this.regions.get(id) ?? { cursor: null, done: false, failedPose: null, pages: 0 }
    if (region.done || region.failedPose === pose) return
    this.regions.set(id, region)
    this.pending.add(id)
    try {
      const page = await this.fetch(id, region.cursor, this.controller.signal)
      if (this.controller.signal.aborted || this.regions.get(id) !== region) return
      await this.merge(page)
      if (this.controller.signal.aborted) return
      region.cursor = page.next_cursor ?? null
      region.done = !page.has_more || region.cursor === null
      region.pages++
      region.failedPose = null
      this.progress()
    } catch (error) {
      if (!this.controller.signal.aborted) {
        region.failedPose = pose
        this.failure(error)
      }
    } finally { this.pending.delete(id); this.pump() }
  }

  dispose(): void { this.controller.abort(); this.wanted.clear(); this.regions.clear() }
}
