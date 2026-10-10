import { GraphBranchLayout, type GraphPoint } from './graphBranches.ts'
import type { GraphBranch } from './graphBranches.ts'
import type { MemoryGraphEdge, MemoryGraphNode } from './types'
import { graphNodeLevel, GRAPH_DEPTH_STEP } from './graph3dHierarchy.ts'

export interface GraphPoint3d extends GraphPoint { z: number }
export interface Graph3dLayoutRequest {
  generation: number
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  branches: GraphBranch[]
  positions: [string, GraphPoint][]
  depths?: [string, number][]
  points?: [string, GraphPoint3d][]
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

/** Retain the established lateral map and give the 3D display its own depth.
 * Entry points face the camera; real children and knowledge details follow. */
export function layoutGraph3d(request: Graph3dLayoutRequest): Graph3dLayoutResult {
  const layout = new GraphBranchLayout()
  for (const [id, point] of request.positions) layout.positions.set(id, point)
  layout.update(request.nodes, request.branches, request.edges)
  const retainedDepths = new Map(request.depths)
  const byId = new Map(request.nodes.map(node => [node.id, node]))
  const points = new Map<string, GraphPoint3d>()
  const retained = new Map(request.points)
  for (const node of request.nodes) {
    const point = layout.positions.get(node.id)!
    points.set(node.id, retained.get(node.id) ?? { x: point.x, y: -point.y,
      z: retainedDepths.get(node.id) ?? -graphNodeLevel(node) * GRAPH_DEPTH_STEP
        + depthSeed(node.id) * (100 + graphNodeLevel(node) * 50) })
  }
  // Follow confirmed resource parentage without treating the whole graph as a
  // tree. Cycles and multiple parents are resolved deterministically for display.
  const children = new Map<string, string[]>()
  const parents = new Map<string, string>()
  const candidates = [...request.edges].filter(edge => !edge.suggested && edge.source_item_id !== edge.target_item_id
    && byId.has(edge.source_item_id) && byId.has(edge.target_item_id))
    .sort((a, b) => Number(b.relation_type === 'parent_of') - Number(a.relation_type === 'parent_of')
      || graphNodeLevel(byId.get(a.source_item_id)!) - graphNodeLevel(byId.get(b.source_item_id)!)
      || a.source_item_id.localeCompare(b.source_item_id))
  for (const edge of candidates) {
    const source = byId.get(edge.source_item_id)!, target = byId.get(edge.target_item_id)!
    if (parents.has(target.id) || edge.relation_type !== 'parent_of' && graphNodeLevel(source) >= graphNodeLevel(target)) continue
    if (!children.has(edge.source_item_id)) children.set(edge.source_item_id, [])
    children.get(edge.source_item_id)!.push(edge.target_item_id)
    parents.set(edge.target_item_id, edge.source_item_id)
  }
  const queue = request.nodes.filter(node => !parents.has(node.id)).map(node => node.id).sort()
  const placed = new Set(queue)
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index]!
    for (const child of children.get(id) ?? []) if (!placed.has(child)) {
      placed.add(child); queue.push(child)
      if (retained.has(child)) continue
      const parent = points.get(id)!, source = byId.get(id)!, node = byId.get(child)!
      const point = points.get(child)!, seed = depthSeed(child)
      const distance = Math.hypot(point.x - parent.x, point.y - parent.y)
      // Keep the previous file distribution. Only depth changes, following the
      // actual link's lateral length, rather than a spiral or fixed planes.
      const gap = Math.max(180, Math.min(560, distance * 0.7))
        * (1 + Math.max(0, graphNodeLevel(node) - graphNodeLevel(source) - 1) * 0.15)
      points.set(child, { ...point, z: retainedDepths.get(child) ?? parent.z - gap * (1 + seed * 0.2) })
    }
  }
  return { generation: request.generation, positions: [...layout.positions],
    points: [...points] }
}
