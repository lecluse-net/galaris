import type { MemoryGraphEdge, MemoryGraphNode } from './types'

export interface GraphHiddenItems {
  /** Shared items contribute fractional mass, but remain individually countable. */
  mass: Map<string, number>
  count: Map<string, number>
  hiddenCount: number
  unloadedCount: number
}

/** Transfer each hidden item's mass to its nearest displayed representatives.
 * Parentage and folded branches take precedence over other confirmed relations.
 * Multi-source traversal stops at displayed nodes and handles hidden chains/cycles. */
export function graphHiddenItems(
  nodes: readonly (Pick<MemoryGraphNode, 'id' | 'children_count'> & { virtual?: boolean })[],
  edges: readonly Pick<MemoryGraphEdge, 'source_item_id' | 'target_item_id' | 'relation_type' | 'suggested'>[],
  displayed: ReadonlySet<string>,
  representatives: ReadonlyMap<string, string> = new Map(),
): GraphHiddenItems {
  const byId = new Set(nodes.map(node => node.id))
  const virtualIds = new Set(nodes.filter(node => node.virtual).map(node => node.id))
  const neighbors = new Map<string, Set<string>>()
  const parents = new Map<string, Set<string>>()
  const children = new Map<string, Set<string>>()
  const add = (map: Map<string, Set<string>>, id: string, other: string): void => {
    if (!map.has(id)) map.set(id, new Set())
    map.get(id)!.add(other)
  }
  for (const edge of edges) {
    const source = edge.source_item_id, target = edge.target_item_id
    if (edge.suggested || source === target || !byId.has(source) || !byId.has(target)) continue
    add(neighbors, source, target); add(neighbors, target, source)
    if (edge.relation_type === 'parent_of') {
      add(parents, target, source)
      if (!virtualIds.has(source) && !virtualIds.has(target)) add(children, source, target)
    }
  }
  const routes = new Map<string, ReadonlySet<string>>()
  const incoming = new Map<string, Set<string>>()
  for (const node of nodes) {
    if (displayed.has(node.id)) continue
    const representative = representatives.get(node.id)
    const targets = representative && byId.has(representative) ? new Set([representative])
      : parents.get(node.id) ?? neighbors.get(node.id) ?? new Set<string>()
    routes.set(node.id, targets)
    for (const target of targets) add(incoming, target, node.id)
  }
  const distance = new Map<string, number>()
  const recipients = new Map<string, ReadonlySet<string>>()
  const queue: string[] = []
  const visit = (): void => {
    distance.clear(); recipients.clear(); queue.length = 0
    for (const id of displayed) if (byId.has(id)) {
      distance.set(id, 0); recipients.set(id, new Set([id])); queue.push(id)
    }
    for (let index = 0; index < queue.length; index++) {
      const id = queue[index]!
      for (const other of incoming.get(id) ?? []) if (!distance.has(other)) {
        distance.set(other, distance.get(id)! + 1); queue.push(other)
      }
    }
  }
  visit()
  // If no visible ancestor exists (including a parent cycle), fall back to
  // confirmed neighbors instead of losing a connected item's contribution.
  let fallback = false
  for (const [id] of parents) if (!displayed.has(id) && !distance.has(id) && !representatives.has(id)) {
    const targets = neighbors.get(id)!
    routes.set(id, targets)
    for (const target of targets) add(incoming, target, id)
    fallback = true
  }
  if (fallback) visit()
  // BFS order ensures every nearer neighbor already knows all its recipients.
  for (const id of queue) {
    if (displayed.has(id)) continue
    const targets = new Set<string>()
    for (const other of routes.get(id) ?? []) if (distance.get(other) === distance.get(id)! - 1) {
      for (const target of recipients.get(other) ?? []) targets.add(target)
    }
    recipients.set(id, targets)
  }
  const mass = new Map<string, number>(), count = new Map<string, number>()
  let hiddenCount = 0, unloadedCount = 0
  for (const node of nodes) {
    const missing = Math.max(0, (node.children_count ?? 0) - (children.get(node.id)?.size ?? 0))
    const hidden = node.virtual || displayed.has(node.id) ? 0 : 1
    unloadedCount += missing; hiddenCount += hidden + missing
    const targets = recipients.get(node.id)
    if (!targets?.size || !hidden && !missing) continue
    for (const target of targets) {
      mass.set(target, (mass.get(target) ?? 0) + (hidden + missing) / targets.size)
      count.set(target, (count.get(target) ?? 0) + hidden + missing)
    }
  }
  return { mass, count, hiddenCount, unloadedCount }
}

/** Grow visibly from the first hidden item, with diminishing returns and a 4× cap. */
export function graphHiddenDiameter(diameter: number, mass: number): number {
  return diameter * Math.min(4, 1 + 3 * Math.log2(1 + Math.max(0, mass)) / 8)
}
