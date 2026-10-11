import type { MemoryGraphEdge, MemoryGraphNode } from './types'

export interface GraphRecords {
  nodes: Map<string, MemoryGraphNode>
  edges: Map<string, MemoryGraphEdge>
}

/** Reconcile a complete authorized snapshot without replacing unchanged records
 * or discarding pages/edits received while the background read was in flight. */
export function reconcileGraph(current: GraphRecords, baseline: GraphRecords, snapshot: GraphRecords, truncated = false): GraphRecords {
  let nodes = current.nodes, edges = current.edges
  for (const [id, before] of baseline.nodes) {
    if (!snapshot.nodes.has(id) && current.nodes.get(id) === before) {
      if (nodes === current.nodes) nodes = new Map(nodes)
      nodes.delete(id)
    }
  }
  for (const [id, node] of snapshot.nodes) {
    const existing = current.nodes.get(id)
    if (!existing && baseline.nodes.has(id)) continue
    if (existing && (existing !== baseline.nodes.get(id) || JSON.stringify(existing) === JSON.stringify(node))) continue
    if (nodes === current.nodes) nodes = new Map(nodes)
    nodes.set(id, node)
  }
  for (const [id, edge] of current.edges) {
    const absent = !truncated && baseline.edges.get(id) === edge && !snapshot.edges.has(id)
      && baseline.nodes.has(edge.source_item_id) && baseline.nodes.has(edge.target_item_id)
    if (absent || !nodes.has(edge.source_item_id) || !nodes.has(edge.target_item_id)) {
      if (edges === current.edges) edges = new Map(edges)
      edges.delete(id)
    }
  }
  for (const [id, edge] of snapshot.edges) {
    if (!nodes.has(edge.source_item_id) || !nodes.has(edge.target_item_id)) continue
    const existing = current.edges.get(id)
    if (!existing && baseline.edges.has(id)) continue
    if (existing && (existing !== baseline.edges.get(id) || JSON.stringify(existing) === JSON.stringify(edge))) continue
    if (edges === current.edges) edges = new Map(edges)
    edges.set(id, edge)
  }
  return { nodes, edges }
}
