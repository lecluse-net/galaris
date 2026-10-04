import type { MemoryGraphEdge, MemoryGraphNode } from './types'
import type { GraphBranch, GraphPoint } from './graphBranches'

interface Body extends GraphPoint {
  id: string
  mass: number
  radius: number
  fixed: boolean
  fx: number
  fy: number
}
interface Cell extends GraphPoint {
  mass: number
  radius: number
  width: number
  bodies: Body[]
  children: Cell[]
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

// Barnes–Hut approximation: distant regions exert one aggregated repulsion.
// Buckets and a depth limit also handle coincident points without infinite subdivision.
function cellFor(bodies: Body[], left: number, top: number, width: number, depth = 0): Cell {
  let mass = 0, x = 0, y = 0, radius = 0
  for (const body of bodies) {
    mass += body.mass
    x += body.x * body.mass
    y += body.y * body.mass
    radius = Math.max(radius, body.radius)
  }
  const cell: Cell = { mass, x: x / mass, y: y / mass, radius, width, bodies, children: [] }
  if (bodies.length <= 4 || depth >= 20) return cell
  const half = width / 2
  const groups: Body[][] = [[], [], [], []]
  for (const body of bodies) groups[(body.x >= left + half ? 1 : 0) + (body.y >= top + half ? 2 : 0)]!.push(body)
  cell.bodies = []
  for (let i = 0; i < 4; i++) if (groups[i]!.length) {
    cell.children.push(cellFor(groups[i]!, left + (i % 2) * half, top + Math.floor(i / 2) * half, half, depth + 1))
  }
  return cell
}

function repel(body: Body, other: GraphPoint, mass: number, radius: number): void {
  const dx = body.x - other.x, dy = body.y - other.y
  const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
  const separation = body.radius + radius + 65
  const force = 12_000 * mass * body.mass / (distance * distance)
    + Math.max(0, separation - distance) * 0.3
  body.fx += dx / distance * force
  body.fy += dy / distance * force
}

function repulsion(body: Body, cell: Cell): void {
  if (!cell.children.length) {
    for (const other of cell.bodies) if (body !== other) repel(body, other, other.mass, other.radius)
    return
  }
  const dx = body.x - cell.x, dy = body.y - cell.y
  const distanceSquared = dx * dx + dy * dy
  // Do not approximate near large branches: their reserved discs must remain separate.
  if (distanceSquared > (cell.width * 1.5 + body.radius + cell.radius) ** 2) {
    repel(body, cell, cell.mass, 0)
  } else for (const child of cell.children) repulsion(body, child)
}

/** Settle the backbone once; expanding, filtering and changing theme never run a force layout.
 * Later pages/mutations place only newcomers, with surviving coordinates pinned.
 * Exclusive leaves are laid out separately and never enter the force simulation. */
export function placeGraphRegions(
  nodes: readonly MemoryGraphNode[],
  edges: readonly MemoryGraphEdge[],
  branches: readonly GraphBranch[],
  positions: ReadonlyMap<string, GraphPoint>,
): Map<string, GraphPoint> {
  const leaves = new Set(branches.flatMap(branch => branch.memberIds))
  const radii = new Map(branches.map(branch => [branch.anchorId, 120 + Math.sqrt(branch.memberIds.length - 1) * 28]))
  const regions = nodes.filter(node => !leaves.has(node.id)).sort((a, b) => a.id.localeCompare(b.id))
  if (regions.every(node => positions.has(node.id))) return new Map()
  const byId = new Map(regions.map((node, index) => [node.id, index]))
  const neighbors = new Map<string, Set<string>>()
  const links: { source: number; target: number; suggested: boolean }[] = []
  const pairs = new Set<string>()
  // Confirmed edges win over duplicate suggestions; each neighbor attracts only once.
  for (const edge of [...edges].sort((a, b) => Number(a.suggested) - Number(b.suggested))) {
    const source = byId.get(edge.source_item_id), target = byId.get(edge.target_item_id)
    if (source === undefined || target === undefined || source === target) continue
    const key = `${Math.min(source, target)}:${Math.max(source, target)}`
    if (pairs.has(key)) continue
    pairs.add(key)
    links.push({ source, target, suggested: edge.suggested })
    for (const [id, other] of [[edge.source_item_id, edge.target_item_id], [edge.target_item_id, edge.source_item_id]]) {
      if (!neighbors.has(id!)) neighbors.set(id!, new Set())
      neighbors.get(id!)!.add(other!)
    }
  }
  const bodies: Body[] = regions.map((node, index) => {
    const existing = positions.get(node.id)
    const radius = Math.sqrt(index + 0.5) * 100
    const angle = index * GOLDEN_ANGLE
    const adjacent = [...(neighbors.get(node.id) ?? [])].flatMap(id => {
      const point = positions.get(id)
      return point ? [point] : []
    })
    const center = adjacent.length ? {
      x: adjacent.reduce((sum, point) => sum + point.x, 0) / adjacent.length,
      y: adjacent.reduce((sum, point) => sum + point.y, 0) / adjacent.length,
    } : { x: 0, y: 0 }
    return {
      id: node.id,
      x: existing?.x ?? center.x + Math.cos(angle) * (adjacent.length ? 140 : radius),
      y: existing?.y ?? center.y + Math.sin(angle) * (adjacent.length ? 140 : radius),
      mass: Math.min(5, Math.sqrt(node.relation_count + 1)), radius: radii.get(node.id) ?? 0,
      fixed: !!existing, fx: 0, fy: 0,
    }
  })
  const isHub = (index: number): boolean => {
    const node = regions[index]!
    return node.relation_count >= 8 || (['topic', 'contact', 'conversation', 'folder', 'directory'].includes(node.entity_kind)
      && node.relation_count >= 2)
  }
  // Match the previous graph's weak attraction between hubs, so cross-cutting contacts
  // do not pull every subject into the same ball. The links remain visible.
  const springs = links.map(link => ({ ...link,
    strength: link.suggested ? 0.012 : isHub(link.source) && isHub(link.target) ? 0.004 : 0.08,
  }))
  // Bound initial CPU work for a dense 3,000-node backbone as well as folded stars.
  const iterations = positions.size ? 60 : Math.min(180, Math.max(60, Math.floor(90_000 / bodies.length)))
  for (let step = 0; step < iterations; step++) {
    const left = Math.min(...bodies.map(body => body.x)), top = Math.min(...bodies.map(body => body.y))
    const width = Math.max(1, Math.max(...bodies.map(body => body.x)) - left, Math.max(...bodies.map(body => body.y)) - top)
    const tree = cellFor(bodies, left, top, width)
    for (const body of bodies) {
      body.fx = -body.x * 0.008
      body.fy = -body.y * 0.008
      if (!body.fixed) repulsion(body, tree)
    }
    for (const spring of springs) {
      const source = bodies[spring.source]!, target = bodies[spring.target]!
      const dx = target.x - source.x, dy = target.y - source.y
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const force = (distance - 140 - source.radius - target.radius) * spring.strength
      source.fx += dx / distance * force
      source.fy += dy / distance * force
      target.fx -= dx / distance * force
      target.fy -= dy / distance * force
    }
    const maxStep = 70 * (1 - step / iterations) + 2
    for (const body of bodies) if (!body.fixed) {
      const scale = Math.min(1, maxStep / Math.max(1, Math.sqrt(body.fx * body.fx + body.fy * body.fy)))
      body.x += body.fx * scale
      body.y += body.fy * scale
    }
  }
  return new Map(bodies.filter(body => !body.fixed).map(body => [body.id, { x: body.x, y: body.y }]))
}
