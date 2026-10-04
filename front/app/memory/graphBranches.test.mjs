import { test } from 'node:test'
import assert from 'node:assert/strict'
import { graphBranches, GraphBranchLayout } from './graphBranches.ts'

const node = (id, count = 1, entity_kind = 'memory') => ({ id, relation_count: count, entity_kind })
const edge = (source, target, suggested = false) => ({ source_item_id: source, target_item_id: target, suggested })
const star = () => ({ nodes: [node('anchor', 30), ...Array.from({ length: 30 }, (_, i) => node(`leaf-${i}`))],
  edges: Array.from({ length: 30 }, (_, i) => edge('anchor', `leaf-${i}`)) })

test('only confirmed leaves with a globally unique admissible neighbor fold; duplicate relations count once', () => {
  const { nodes, edges } = star()
  nodes[1].relation_count = 2 // Another neighbor exists beyond the loaded page.
  nodes[2].entity_kind = 'topic'
  edges[2].suggested = true
  edges.push(edge('anchor', 'leaf-3'))
  const [branch] = graphBranches(nodes, edges)
  assert.equal(branch.anchorId, 'anchor')
  assert.equal(branch.memberIds.length, 27)
  assert.equal(new Set(branch.memberIds).size, 27)
  assert(!branch.memberIds.includes('leaf-0'))
  assert(!branch.memberIds.includes('leaf-1'))
  assert(!branch.memberIds.includes('leaf-2'))
})

test('cycles and isolated nodes remain individual; filtered small branches remain accessible', () => {
  const { nodes, edges } = star()
  assert.deepEqual(graphBranches(nodes.slice(0, 5), edges), [])
  assert.deepEqual(graphBranches([node('a', 2), node('b', 2), node('c', 2), node('isolated', 0)],
    [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')]), [])
})

test('linked communities determine the map and stay closer than unrelated communities', () => {
  const nodes = Array.from({ length: 48 }, (_, i) => node(`item-${i}`, 2))
  const edges = []
  for (let group = 0; group < 4; group++) {
    nodes.push(node(`hub-${group}`, 24, 'topic'))
    for (let i = group; i < 48; i += 4) {
      edges.push(edge(`hub-${group}`, `item-${i}`), edge(`item-${i}`, `item-${(i + 4) % 48}`))
    }
  }
  edges.push(edge('hub-0', 'hub-1'), edge('hub-1', 'hub-2'), edge('hub-2', 'hub-3'))
  const layout = new GraphBranchLayout()
  layout.update(nodes, [], edges)
  const disconnected = new GraphBranchLayout()
  disconnected.update(nodes, [], [])
  assert.notDeepEqual(layout.positions, disconnected.positions, 'Relations must influence the layout')
  const distance = (left, right) => Math.hypot(left.x - right.x, left.y - right.y)
  let local = 0, remote = 0
  for (let i = 0; i < 48; i++) {
    const point = layout.positions.get(`item-${i}`)
    local += distance(point, layout.positions.get(`hub-${i % 4}`))
    remote += distance(point, layout.positions.get(`hub-${(i + 2) % 4}`))
  }
  assert(local < remote * 0.6, `Linked items should remain near their community (${local} / ${remote})`)
  for (const point of layout.positions.values()) assert(Number.isFinite(point.x) && Number.isFinite(point.y))
})

test('opening, filtering, adding neighbors and removing items preserve the positions of surviving regions', () => {
  const { nodes, edges } = star()
  nodes.push(node('isolated', 0))
  const layout = new GraphBranchLayout()
  const branches = graphBranches(nodes, edges)
  layout.update(nodes, branches, edges)
  const previous = new Map([...layout.positions].map(([id, point]) => [id, { ...point }]))
  // Visibility and expanded state do not enter the layout.
  layout.update(nodes, branches, edges)
  assert.deepEqual(layout.positions, previous)
  nodes.push(node('new-leaf'), node('new-root', 0))
  edges.push(edge('anchor', 'new-leaf'))
  layout.update(nodes, graphBranches(nodes, edges), edges)
  for (const [id, position] of previous) assert.deepEqual(layout.positions.get(id), position)
  const surviving = nodes.filter(item => item.id !== 'leaf-5')
  layout.update(surviving, graphBranches(surviving, edges), edges)
  assert(!layout.positions.has('leaf-5'))
  assert.deepEqual(layout.positions.get('isolated'), previous.get('isolated'))
  assert.equal(layout.positions.size, surviving.length)
})
