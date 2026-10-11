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
  reset_layout?: boolean
  positions: Record<string, GraphPoint>
  preferences: Partial<GraphPreferences>
}
interface Transport {
  readGraphState(context: GraphContext): Promise<GraphState>
  saveGraphState(context: GraphContext, patch: GraphStatePatch): Promise<GraphState>
}

const emptyPreferences = (): GraphPreferences => ({ hidden_entity_kinds: [], expanded_branches: [],
  camera: null, camera_3d: null, resource_branches: {} })
const kinds = new Set(['memory', 'document', 'attachment', 'folder', 'file', 'directory', 'topic', 'contact', 'conversation'])
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const vector = (value: unknown, size: number): boolean => Array.isArray(value) && value.length === size
  && value.every(coordinate => typeof coordinate === 'number' && Number.isFinite(coordinate) && Math.abs(coordinate) <= 1e15)

/** The persisted view is a cache, never a prerequisite for displaying data. */
function compatibleState(state: GraphState): boolean {
  if (!record(state) || state.format_version !== 1 || !Number.isSafeInteger(state.revision) || state.revision < 0) return false
  const preferences = state.preferences
  if (!record(preferences) || !Array.isArray(preferences.hidden_entity_kinds)
    || !preferences.hidden_entity_kinds.every(kind => kinds.has(kind))
    || !Array.isArray(preferences.expanded_branches) || !preferences.expanded_branches.every(id => typeof id === 'string')) return false
  if (Object.keys(preferences).some(key => !['hidden_entity_kinds', 'expanded_branches', 'camera', 'camera_3d', 'resource_branches'].includes(key))) return false
  const legacyCamera = preferences.camera
  if (legacyCamera != null && (!record(legacyCamera) || (legacyCamera.center !== null && !vector(legacyCamera.center, 2))
    || !Number.isFinite(legacyCamera.zoom) || legacyCamera.zoom < 0.2 || legacyCamera.zoom > 1_000_000)) return false
  if (preferences.resource_branches !== undefined && (!record(preferences.resource_branches)
    || !Object.values(preferences.resource_branches).every(pages => Number.isSafeInteger(pages) && pages >= 1 && pages <= 10_000))) return false
  const camera = preferences.camera_3d
  if (camera != null && (!record(camera) || camera.layout_version !== 2 || !vector(camera.position, 3) || !vector(camera.target, 3))) return false
  return record(state.positions) && Object.values(state.positions).every(point => record(point)
    && typeof point.x === 'number' && typeof point.y === 'number' && Number.isFinite(point.x) && Number.isFinite(point.y)
    && Math.abs(point.x) <= 1e15 && Math.abs(point.y) <= 1e15)
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
  private resetLayout = false
  private acceptSavedPositions = true
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
    this.revision = Number.isSafeInteger(state?.revision) && state.revision >= 0 ? state.revision : 0
    const compatible = compatibleState(state)
    if (!compatible) {
      this.resetLayout = true
      this.acceptSavedPositions = false
      this.saved.clear()
      this.preferences = { ...emptyPreferences(), ...this.preferences }
    }
    this.ready = true
    this.onError(null)
    return { ...(compatible ? state.preferences : emptyPreferences()), ...this.preferences }
  }

  get restoresPositions(): boolean { return this.acceptSavedPositions }

  remember(points: Iterable<[string, GraphPoint]>): void {
    if (!this.acceptSavedPositions) return
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
    if (!this.ready) {
      try { await this.load() } catch (error) { this.onError(error); return }
    }
    while (this.resetLayout || this.points.size || Object.keys(this.preferences).length) {
      const batch = [...this.points].slice(0, 500)
      const preferences = this.preferences
      this.preferences = {}
      for (const [key] of batch) this.points.delete(key)
      const patch: GraphStatePatch = { expected_revision: this.revision, positions: Object.fromEntries(batch), preferences,
        ...(this.resetLayout ? { reset_layout: true } : {}) }
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
        this.resetLayout = false
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
