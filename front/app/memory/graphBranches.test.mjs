import { test } from 'node:test'
import assert from 'node:assert/strict'
import { graphBranches, GraphBranchLayout } from './graphBranches.ts'

const node = (id, count = 1, entity_kind = 'memory') => ({ id, relation_count: count, entity_kind })
const edge = (source, target, suggested = false) => ({ source_item_id: source, target_item_id: target, suggested })
const star = () => ({ nodes: [node('anchor', 30), ...Array.from({ length: 30 }, (_, i) => node(`leaf-${i}`))],
  edges: Array.from({ length: 30 }, (_, i) => edge('anchor', `leaf-${i}`)) })

test('restored hidden leaf coordinates reserve their slots for later additions', () => {
  const { nodes, edges } = star()
  const first = new GraphBranchLayout()
  first.update(nodes, graphBranches(nodes, edges), edges)
  const restored = new GraphBranchLayout()
  for (const [key, point] of first.positions) restored.positions.set(key, { ...point })
  nodes.push(node('new-leaf'))
  edges.push(edge('anchor', 'new-leaf'))
  restored.update(nodes, graphBranches(nodes, edges), edges)
  for (const [key, point] of first.positions) assert.deepEqual(restored.positions.get(key), point)
  const added = restored.positions.get('new-leaf')
  assert([...first.positions.values()].every(point => point.x !== added.x || point.y !== added.y))
})

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

test('memories with the same complete topic/contact relations fold without losing either connection', () => {
  const nodes = [node('subject', 30, 'topic'), node('person', 30, 'contact'),
    ...Array.from({ length: 30 }, (_, i) => node(`shared-${i}`, 2))]
  const edges = nodes.slice(2).flatMap(item => [edge('subject', item.id), edge('person', item.id)])
  nodes[2].relation_count = 3 // A third neighbor is outside the loaded window.
  edges[2].suggested = true // A suggestion cannot establish shared membership.
  const branches = graphBranches(nodes, edges)
  assert.equal(branches.length, 1)
  const [branch] = branches
  assert.equal(branch.memberIds.length, 27)
  assert.deepEqual(branch.neighborIds, ['person', 'subject'])
  assert(![branch.anchorId, ...branch.memberIds].includes('shared-0'))
  assert(![branch.anchorId, ...branch.memberIds].includes('shared-1'))
  assert.deepEqual(edges.filter(item => item.target_item_id === branch.anchorId).map(item => item.source_item_id).sort(),
    ['person', 'subject'])
  const allIds = [branch.anchorId, ...branch.memberIds]
  assert.equal(new Set(allIds).size, allIds.length)
  assert.deepEqual(graphBranches([...nodes].reverse(), [...edges].reverse()), branches)
})

test('shared grouping preserves relation kinds, direction and entity nature', () => {
  const nodes = [node('topic', 40, 'topic'), node('contact', 40, 'contact'),
    ...Array.from({ length: 12 }, (_, i) => node(`same-${i}`, 2)),
    node('different-kind', 2), node('reversed', 2), node('document', 2, 'document')]
  const edges = nodes.slice(2).flatMap(item => [
    { ...edge('topic', item.id), relation_type: 'topic_contains' },
    { ...edge('contact', item.id), relation_type: 'contact_contains' },
  ])
  edges.find(item => item.target_item_id === 'different-kind').relation_type = 'related_to'
  const reversed = edges.find(item => item.target_item_id === 'reversed')
  ;[reversed.source_item_id, reversed.target_item_id] = [reversed.target_item_id, reversed.source_item_id]
  const [branch] = graphBranches(nodes, edges)
  assert.deepEqual([branch.anchorId, ...branch.memberIds].sort(), nodes.filter(item => item.id.startsWith('same-')).map(item => item.id).sort())
})

for (const count of [48, 4800]) test(`linked communities of ${count} items determine the map and stay closer than unrelated communities`, () => {
  const nodes = Array.from({ length: count }, (_, i) => node(`item-${i}`, 2))
  const edges = []
  for (let group = 0; group < 4; group++) {
    nodes.push(node(`hub-${group}`, count / 4, 'topic'))
    for (let i = group; i < count; i += 4) {
      edges.push(edge(`hub-${group}`, `item-${i}`), edge(`item-${i}`, `item-${(i + 4) % count}`))
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
  for (let i = 0; i < count; i++) {
    const point = layout.positions.get(`item-${i}`)
    local += distance(point, layout.positions.get(`hub-${i % 4}`))
    remote += distance(point, layout.positions.get(`hub-${(i + 2) % 4}`))
  }
  assert(local < remote * 0.6, `Linked items should remain near their community (${local} / ${remote})`)
  for (const point of layout.positions.values()) assert(Number.isFinite(point.x) && Number.isFinite(point.y))
  const previous = new Map(layout.positions)
  layout.update(nodes, [], edges)
  assert.deepEqual(layout.positions, previous, 'Presentation updates must not reposition communities')
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
