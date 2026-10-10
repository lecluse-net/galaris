import { GraphBranchLayout, type GraphPoint } from './graphBranches.ts'
import type { GraphBranch } from './graphBranches.ts'
import type { MemoryGraphEdge, MemoryGraphNode } from './types'

export interface GraphPoint3d extends GraphPoint { z: number }
export interface Graph3dLayoutRequest {
  generation: number
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  branches: GraphBranch[]
  positions: [string, GraphPoint][]
  depths?: [string, number][]
}
export interface Graph3dLayoutResult {
  generation: number
  positions: [string, GraphPoint][]
  points: [string, GraphPoint3d][]
}

function depthSeed(id: string): number {
  let hash = 2166136261
  for (let i = 0; i < id.length; i++) hash = Math.imul(hash ^ id.charCodeAt(i), 16777619)
  return (hash >>> 0) / 0xffffffff - 0.5
}

/** The saved 2D map remains intact. Depth adds stable space between communities
 * and their leaves without a global force simulation running during navigation. */
export function layoutGraph3d(request: Graph3dLayoutRequest): Graph3dLayoutResult {
  const layout = new GraphBranchLayout()
  for (const [id, point] of request.positions) layout.positions.set(id, point)
  layout.update(request.nodes, request.branches, request.edges)
  const retainedDepths = new Map(request.depths)
  const depths = new Map<string, number>()
  for (const node of request.nodes) depths.set(node.id, depthSeed(node.id) * 700)
  for (const branch of request.branches) {
    const center = depths.get(branch.anchorId) ?? 0
    branch.memberIds.forEach(id => {
      depths.set(id, center + depthSeed(id) * 480)
    })
  }
  // Follow confirmed resource parentage without treating the whole graph as a
  // tree. Cycles and multiple parents are resolved deterministically for display.
  const children = new Map<string, string[]>()
  const parents = new Set<string>()
  for (const edge of [...request.edges].sort((a, b) => a.source_item_id.localeCompare(b.source_item_id))) {
    if (edge.suggested || edge.relation_type !== 'parent_of' || edge.source_item_id === edge.target_item_id) continue
    if (!children.has(edge.source_item_id)) children.set(edge.source_item_id, [])
    children.get(edge.source_item_id)!.push(edge.target_item_id)
    parents.add(edge.target_item_id)
  }
  const queue = [...children.keys()].filter(id => !parents.has(id)).sort()
  const placed = new Set(queue)
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index]!
    for (const child of children.get(id) ?? []) if (!placed.has(child)) {
      placed.add(child); queue.push(child)
      depths.set(child, (depths.get(id) ?? 0) - 240)
    }
  }
  for (const [id, depth] of retainedDepths) if (depths.has(id)) depths.set(id, depth)
  return { generation: request.generation, positions: [...layout.positions],
    points: [...layout.positions].map(([id, point]) => [id, { ...point, y: -point.y, z: depths.get(id) ?? 0 }]) }
}
