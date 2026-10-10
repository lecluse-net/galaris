import type { MemoryGraphCursor, MemoryGraphPage } from './types'

interface Region { cursor: MemoryGraphCursor | null; done: boolean; pose: string; pages: number }

/** At most two region requests. A stationary camera never drains an entire
 * tree; another movement can fetch its next page. Context disposal aborts all. */
export class Graph3dChildren {
  private readonly controller = new AbortController()
  private readonly regions = new Map<string, Region>()
  private readonly pending = new Set<string>()
  private readonly fetch: (id: string, cursor: MemoryGraphCursor | null, signal: AbortSignal) => Promise<MemoryGraphPage>
  private readonly merge: (page: MemoryGraphPage) => Promise<void>
  private readonly failure: (error: unknown) => void
  constructor(
    fetch: (id: string, cursor: MemoryGraphCursor | null, signal: AbortSignal) => Promise<MemoryGraphPage>,
    merge: (page: MemoryGraphPage) => Promise<void>,
    failure: (error: unknown) => void,
  ) { this.fetch = fetch; this.merge = merge; this.failure = failure }

  get expanded(): Record<string, number> {
    return Object.fromEntries([...this.regions].filter(([, region]) => region.pages).map(([id, region]) => [id, region.pages]))
  }

  update(ids: readonly string[], pose: string): void {
    if (this.controller.signal.aborted) return
    for (const id of ids) {
      if (this.pending.size >= 2) break
      void this.load(id, pose)
    }
  }

  async load(id: string, pose: string): Promise<void> {
    if (this.controller.signal.aborted || this.pending.has(id)) return
    const region = this.regions.get(id) ?? { cursor: null, done: false, pose: '', pages: 0 }
    if (region.done || region.pose === pose) return
    region.pose = pose
    this.regions.set(id, region)
    this.pending.add(id)
    try {
      const page = await this.fetch(id, region.cursor, this.controller.signal)
      if (this.controller.signal.aborted) return
      region.cursor = page.next_cursor ?? null
      region.done = !page.has_more || region.cursor === null
      region.pages++
      await this.merge(page)
    } catch (error) {
      if (!this.controller.signal.aborted) this.failure(error)
    } finally { this.pending.delete(id) }
  }

  dispose(): void { this.controller.abort(); this.regions.clear() }
}
