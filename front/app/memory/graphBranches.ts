import type { MemoryGraphEdge, MemoryGraphNode } from './types'
import { placeGraphRegions } from './graphLayout.ts'

export interface GraphPoint { x: number; y: number }
export interface GraphBranch { anchorId: string; memberIds: string[]; neighborIds?: string[] }

export const MIN_BRANCH_SIZE = 8
export const BRANCH_OPEN_ZOOM = 1.8
export const BRANCH_CLOSE_ZOOM = 1.35

/** The server's distinct-neighbor count covers all admissible pages, including suggestions.
 * A locally observed edge alone never establishes exclusive membership. */
export function graphBranches(nodes: readonly MemoryGraphNode[], edges: readonly MemoryGraphEdge[]): GraphBranch[] {
  const byId = new Map(nodes.map(node => [node.id, node]))
  const neighbors = new Map<string, Set<string>>()
  const confirmed = new Map<string, Set<string>>()
  const signatures = new Map<string, Set<string>>()
  const suggestedIds = new Set<string>()
  for (const edge of edges) {
    if (edge.source_item_id === edge.target_item_id) continue
    for (const [id, other] of [[edge.source_item_id, edge.target_item_id], [edge.target_item_id, edge.source_item_id]]) {
      if (!id || !other || !byId.has(id) || !byId.has(other)) continue
      if (!neighbors.has(id)) neighbors.set(id, new Set())
      neighbors.get(id)!.add(other)
      if (!signatures.has(id)) signatures.set(id, new Set())
      signatures.get(id)!.add(JSON.stringify([other, edge.relation_type, edge.source_item_id === id, edge.suggested]))
      if (edge.suggested) suggestedIds.add(id)
      if (!edge.suggested) {
        if (!confirmed.has(id)) confirmed.set(id, new Set())
        confirmed.get(id)!.add(other)
      }
    }
  }
  const members = new Map<string, string[]>()
  for (const node of nodes) {
    if (node.relation_count !== 1 || ['topic', 'contact', 'conversation', 'folder', 'directory'].includes(node.entity_kind)) continue
    const adjacent = neighbors.get(node.id)
    if (adjacent?.size !== 1) continue
    const anchorId = adjacent.values().next().value
    if (!anchorId || !confirmed.get(node.id)?.has(anchorId)) continue
    const anchor = byId.get(anchorId)
    if (!anchor || anchor.relation_count <= 1) continue
    if (!members.has(anchorId)) members.set(anchorId, [])
    members.get(anchorId)!.push(node.id)
  }
  const branches: GraphBranch[] = [...members].filter(([, ids]) => ids.length >= MIN_BRANCH_SIZE)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([anchorId, memberIds]) => ({ anchorId, memberIds: memberIds.sort() }))
  // A memory can belong to a topic AND a contact. Group identical, complete
  // neighborhoods using one real member as representative: its edges preserve
  // every connection, rather than falsely assigning the group to a single hub.
  const shared = new Map<string, string[]>()
  for (const node of nodes) {
    const adjacent = neighbors.get(node.id)
    if (node.entity_kind !== 'memory' || !adjacent || adjacent.size < 2
      || adjacent.size !== node.relation_count || confirmed.get(node.id)?.size !== adjacent.size
      || [...adjacent].some(id => !['topic', 'contact', 'conversation', 'folder', 'directory'].includes(byId.get(id)!.entity_kind))
      || suggestedIds.has(node.id)) continue
    const signature = JSON.stringify([...(signatures.get(node.id) ?? [])].sort())
    if (!shared.has(signature)) shared.set(signature, [])
    shared.get(signature)!.push(node.id)
  }
  for (const ids of shared.values()) {
    if (ids.length <= MIN_BRANCH_SIZE) continue
    ids.sort()
    const anchorId = ids[0]!
    branches.push({ anchorId, memberIds: ids.slice(1), neighborIds: [...neighbors.get(anchorId)!].sort() })
  }
  return branches.sort((left, right) => left.anchorId.localeCompare(right.anchorId))
}

/** Stable positions for one loaded window. Hidden leaves retain their reserved space.
 * Opening a branch changes its representation, never its placement or map bounds. */
export class GraphBranchLayout {
  readonly positions = new Map<string, GraphPoint>()
  private readonly slots = new Map<string, Map<string, number>>()

  clear(): void {
    this.positions.clear()
    this.slots.clear()
  }

  update(nodes: readonly MemoryGraphNode[], branches: readonly GraphBranch[], edges: readonly MemoryGraphEdge[]): void {
    const liveIds = new Set(nodes.map(node => node.id))
    for (const id of this.positions.keys()) if (!liveIds.has(id)) this.positions.delete(id)
    for (const [anchor, slots] of this.slots) {
      if (!liveIds.has(anchor)) this.slots.delete(anchor)
      else for (const id of slots.keys()) if (!liveIds.has(id)) slots.delete(id)
    }
    for (const [id, point] of placeGraphRegions(nodes, edges, branches, this.positions)) this.positions.set(id, point)
    for (const branch of branches) {
      const center = this.positions.get(branch.anchorId)
      if (!center) continue
      let slots = this.slots.get(branch.anchorId)
      if (!slots) { slots = new Map(); this.slots.set(branch.anchorId, slots) }
      // Recover reserved spiral slots when coordinates came from a previous visit.
      for (const id of branch.memberIds) if (!slots.has(id)) {
        const point = this.positions.get(id)
        if (point) slots.set(id, Math.max(0, Math.round(((Math.hypot(point.x - center.x, point.y - center.y) - 120) / 28) ** 2)))
      }
      const occupiedLeaves = new Set(slots.values())
      let nextLeaf = 0
      for (const id of branch.memberIds) {
        if (this.positions.has(id)) continue
        while (occupiedLeaves.has(nextLeaf)) nextLeaf++
        const slot = nextLeaf++
        occupiedLeaves.add(slot)
        slots.set(id, slot)
        const angle = slot * Math.PI * (3 - Math.sqrt(5))
        const radius = 120 + Math.sqrt(slot) * 28
        this.positions.set(id, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius })
      }
    }
  }
}
