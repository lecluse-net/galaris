import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layoutGraph3d } from './graph3dLayout.ts'
import { graphBranches } from './graphBranches.ts'

test('3D keeps saved 2D positions and stable depth through additions and branch expansion', () => {
  const nodes = [{ id: 'anchor', entity_kind: 'topic', relation_count: 20 },
    ...Array.from({ length: 20 }, (_, i) => ({ id: `leaf-${i}`, entity_kind: 'memory', relation_count: 1 }))]
  const edges = nodes.slice(1).map(node => ({ source_item_id: 'anchor', target_item_id: node.id, suggested: false }))
  const positions = [['anchor', { x: 700, y: -300 }]]
  const request = { generation: 1, nodes, edges, branches: graphBranches(nodes, edges), positions }
  const first = layoutGraph3d(request)
  assert.deepEqual(first.positions.find(([id]) => id === 'anchor')[1], positions[0][1])
  assert(new Set(first.points.map(([, point]) => point.z)).size > 1)
  const nextNodes = [...nodes, { id: 'a-new-leaf', entity_kind: 'memory', relation_count: 1 }]
  const nextEdges = [...edges, { source_item_id: 'anchor', target_item_id: 'a-new-leaf', suggested: false }]
  const second = layoutGraph3d({ ...request, nodes: nextNodes, edges: nextEdges,
    branches: graphBranches(nextNodes, nextEdges), positions: first.positions })
  for (const [id, point] of first.points) assert.deepEqual(new Map(second.points).get(id), point)
  assert.equal(second.points.length, nextNodes.length)
})

test('confirmed resource parentage gives successive depth without looping on a cycle', () => {
  const nodes = ['root', 'child', 'file', 'cycle-a', 'cycle-b'].map(id => ({ id, entity_kind: 'directory', relation_count: 2 }))
  const edges = [['root', 'child'], ['child', 'file'], ['cycle-a', 'cycle-b'], ['cycle-b', 'cycle-a']]
    .map(([source_item_id, target_item_id]) => ({ source_item_id, target_item_id, relation_type: 'parent_of', suggested: false }))
  const result = layoutGraph3d({ generation: 1, nodes, edges, branches: [], positions: [] })
  const points = new Map(result.points)
  for (const [id, point] of result.positions) {
    assert.equal(points.get(id).x, point.x, 'lateral coordinates keep the established map')
    assert.equal(points.get(id).y, -point.y)
  }
  assert(points.get('root').z > points.get('child').z)
  assert(points.get('child').z > points.get('file').z)
  assert.equal(points.size, nodes.length)
  assert([...points.values()].every(point => Number.isFinite(point.z)))
})

test('entry points precede directories, documents and details, and deep directory traversal preserves reached 3D positions', () => {
  const nodes = [
    { id: 'scheme', entity_kind: 'directory', resource_uri: 'synthetic://', relation_count: 1 },
    { id: 'topic', entity_kind: 'topic', relation_count: 1 },
    { id: 'contact', entity_kind: 'contact', relation_count: 1 },
    { id: 'folder', entity_kind: 'folder', relation_count: 1 },
    { id: 'document', entity_kind: 'document', relation_count: 1 },
    { id: 'memory', entity_kind: 'memory', relation_count: 1 },
  ]
  const first = layoutGraph3d({ generation: 1, nodes, edges: [], branches: [], positions: [] })
  const points = new Map(first.points)
  const foreground = Math.min(...['scheme', 'topic', 'contact'].map(id => points.get(id).z))
  assert(foreground > points.get('folder').z)
  assert(points.get('folder').z > points.get('document').z)
  assert(points.get('document').z > points.get('memory').z)
  const directories = Array.from({ length: 1000 }, (_, i) => ({ id: `dir-${i}`, entity_kind: 'directory', relation_count: 2 }))
  const edges = directories.map((node, i) => ({ source_item_id: i ? directories[i - 1].id : 'scheme',
    target_item_id: node.id, relation_type: 'parent_of', suggested: false }))
  const next = layoutGraph3d({ generation: 2, nodes: [...nodes, ...directories], edges, branches: [],
    positions: first.positions, points: first.points })
  const nextPoints = new Map(next.points)
  for (const [id, point] of first.points) assert.deepEqual(nextPoints.get(id), point)
  let depth = points.get('scheme').z
  for (const directory of directories) {
    assert(nextPoints.get(directory.id).z < depth)
    depth = nextPoints.get(directory.id).z
  }
  assert(next.points.every(([, point]) => Object.values(point).every(Number.isFinite)))
})
