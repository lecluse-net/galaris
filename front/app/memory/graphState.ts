import type { MemoryGraphEntityKind } from './types'
import type { GraphPoint } from './graphBranches'

export interface GraphContext {
  agent_id: number
  query: string
  topic_item_id: string | null
  contact_item_id: string | null
}
export interface GraphCamera { center: [number, number] | null; zoom: number }
export interface GraphCamera3d { position: [number, number, number]; target: [number, number, number]; layout_version?: number }
export interface GraphPreferences {
  hidden_entity_kinds: MemoryGraphEntityKind[]
  expanded_branches: string[]
  camera: GraphCamera | null
  camera_3d?: GraphCamera3d | null
  resource_branches?: Record<string, number>
}
export interface GraphState {
  format_version: 1
  revision: number
  preferences: GraphPreferences
  positions: Record<string, GraphPoint>
}
export interface GraphStatePatch {
  expected_revision: number
  positions: Record<string, GraphPoint>
  preferences: Partial<GraphPreferences>
}
interface Transport {
  readGraphState(context: GraphContext): Promise<GraphState>
  saveGraphState(context: GraphContext, patch: GraphStatePatch): Promise<GraphState>
}

/** One immutable graph context, even when its component changes agent or unmounts.
 * Only changed fields are sent; failed/in-flight changes never replace newer edits. */
export class GraphStatePersistence {
  private revision = 0
  private ready = false
  private running: Promise<void> | null = null
  private points = new Map<string, GraphPoint>()
  private saved = new Set<string>()
  private preferences: Partial<GraphPreferences> = {}
  readonly context: GraphContext
  private readonly transport: Transport
  private readonly onSaved: (positions: Record<string, GraphPoint>) => void
  private readonly onError: (error: unknown | null) => void

  constructor(
    context: GraphContext,
    transport: Transport,
    onSaved: (positions: Record<string, GraphPoint>) => void,
    onError: (error: unknown | null) => void,
  ) {
    this.context = { ...context }
    this.transport = transport
    this.onSaved = onSaved
    this.onError = onError
  }

  async load(): Promise<GraphPreferences> {
    const state = await this.transport.readGraphState(this.context)
    if (state.format_version !== 1) throw new Error('Unsupported graph view format')
    this.revision = state.revision
    this.ready = true
    this.onError(null)
    return { ...state.preferences, ...this.preferences }
  }

  remember(points: Iterable<[string, GraphPoint]>): void {
    for (const [key] of points) { this.saved.add(key); this.points.delete(key) }
  }

  stagePositions(points: Iterable<[string, GraphPoint]>): void {
    for (const [key, point] of points) if (!this.saved.has(key) && Number.isFinite(point.x) && Number.isFinite(point.y)) {
      this.points.set(key, { ...point })
    }
  }

  stagePreferences(patch: Partial<GraphPreferences>): void {
    this.preferences = { ...this.preferences, ...structuredClone(patch) }
  }

  flush(): Promise<void> {
    if (this.running) return this.running
    this.running = this.drain().finally(() => { this.running = null })
    return this.running
  }

  private async drain(): Promise<void> {
    if (!this.ready) return
    while (this.points.size || Object.keys(this.preferences).length) {
      const batch = [...this.points].slice(0, 500)
      const preferences = this.preferences
      this.preferences = {}
      for (const [key] of batch) this.points.delete(key)
      const patch = { expected_revision: this.revision, positions: Object.fromEntries(batch), preferences }
      try {
        let result: GraphState
        try {
          result = await this.transport.saveGraphState(this.context, patch)
        } catch (error) {
          if (typeof error !== 'object' || error === null
            || !('response' in error) || (error.response as { status?: number })?.status !== 409) throw error
          // Rebase only this patch. Never send a stale complete preference snapshot.
          const current = await this.transport.readGraphState(this.context)
          patch.expected_revision = current.revision
          result = await this.transport.saveGraphState(this.context, patch)
        }
        this.revision = result.revision
        for (const [key] of batch) this.saved.add(key)
        this.onSaved(result.positions)
        this.onError(null)
      } catch (error) {
        for (const [key, point] of batch) if (!this.points.has(key)) this.points.set(key, point)
        this.preferences = { ...preferences, ...this.preferences }
        this.onError(error)
        return
      }
    }
  }
}
