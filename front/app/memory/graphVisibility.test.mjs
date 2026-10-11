import { test } from 'node:test'
import assert from 'node:assert/strict'
import { graphHiddenItems, graphHiddenDiameter } from './graphVisibility.ts'

const node = (id, children_count = 0) => ({ id, children_count })
const edge = (source_item_id, target_item_id, relation_type = 'related_to', suggested = false) =>
  ({ source_item_id, target_item_id, relation_type, suggested })
const sum = map => [...map.values()].reduce((total, value) => total + value, 0)

test('hidden shared items split their mass between distinct visible neighbors; duplicate edges count once', () => {
  const nodes = ['a', 'b', 'hidden', 'isolated'].map(id => node(id))
  const edges = [edge('a', 'hidden'), edge('b', 'hidden'), edge('hidden', 'a')]
  const result = graphHiddenItems(nodes, edges, new Set(['a', 'b']))
  assert.deepEqual(result.mass, new Map([['a', 0.5], ['b', 0.5]]))
  assert.deepEqual(result.count, new Map([['a', 1], ['b', 1]]))
  assert.equal(result.hiddenCount, 2, 'An isolated hidden item still contributes to the global indicator')
  assert.equal(sum(result.mass), 1)
  assert.deepEqual(graphHiddenItems(nodes.toReversed(), edges.toReversed(), new Set(['a', 'b'])).mass, result.mass)
})

test('folded members transfer only to their representative and give their mass back when displayed', () => {
  const nodes = ['topic', 'contact', 'representative', 'leaf', 'selected'].map(id => node(id))
  const edges = [edge('leaf', 'topic'), edge('leaf', 'contact'), edge('selected', 'topic')]
  const representatives = new Map([['leaf', 'representative'], ['selected', 'representative']])
  const closed = graphHiddenItems(nodes, edges, new Set(['topic', 'contact', 'representative', 'selected']), representatives)
  assert.deepEqual(closed.mass, new Map([['representative', 1]]))
  const opened = graphHiddenItems(nodes, edges, new Set(nodes.map(item => item.id)), representatives)
  assert.equal(opened.hiddenCount, 0)
  assert.equal(opened.mass.size, 0)
})

test('hidden chains and cycles stop at their nearest visible nodes without duplicating mass through multiple paths', () => {
  const nodes = ['a', 'b', 'x', 'y', 'z', 'remote', 'far'].map(id => node(id))
  const edges = [edge('a', 'x'), edge('a', 'y'), edge('b', 'y'), edge('x', 'z'), edge('y', 'z'),
    edge('x', 'y'), edge('z', 'remote'), edge('remote', 'far')]
  const result = graphHiddenItems(nodes, edges, new Set(['a', 'b', 'far']))
  assert.equal(sum(result.mass), 4)
  // z is equally near a, b and far; two paths to a still give it only one share.
  assert(Math.abs(result.mass.get('a') - 11 / 6) < 1e-12)
  assert(Math.abs(result.mass.get('b') - 5 / 6) < 1e-12)
  assert(Math.abs(result.mass.get('far') - 4 / 3) < 1e-12)
})

test('unloaded children follow their parent, including across hidden levels, and loaded/hidden children are not counted twice', () => {
  const nodes = [node('root', 3), node('directory', 2), node('leaf'), node('unrelated')]
  const edges = [edge('root', 'directory', 'parent_of'), edge('directory', 'leaf', 'parent_of'),
    edge('root', 'directory', 'parent_of'), edge('leaf', 'unrelated')]
  const closed = graphHiddenItems(nodes, edges, new Set(['root', 'unrelated']))
  assert.equal(closed.unloadedCount, 3)
  assert.equal(closed.hiddenCount, 5)
  assert.deepEqual(closed.mass, new Map([['root', 5]]))
  const opened = graphHiddenItems(nodes, edges, new Set(nodes.map(item => item.id)))
  assert.equal(opened.hiddenCount, 3)
  assert.deepEqual(opened.mass, new Map([['root', 2], ['directory', 1]]))
})

test('suggestions, unknown endpoints and self links never invent representatives or child membership', () => {
  const nodes = [node('a', 1), node('hidden')]
  const edges = [edge('a', 'hidden', 'parent_of', true), edge('hidden', 'unknown'), edge('hidden', 'hidden')]
  const result = graphHiddenItems(nodes, edges, new Set(['a']))
  assert.equal(result.hiddenCount, 2)
  assert.deepEqual(result.mass, new Map([['a', 1]]))
  assert.equal(graphHiddenItems(nodes, edges, new Set()).mass.size, 0)
})

test('virtual spatial representatives receive the full hidden population, including folded descendants', () => {
  const nodes = [node('a'), node('b'), node('leaf'), { id: 'group', virtual: true }]
  const representatives = new Map([['a', 'group'], ['b', 'group'], ['leaf', 'a']])
  const result = graphHiddenItems(nodes, [], new Set(['group']), representatives)
  assert.equal(result.mass.get('group'), 3)
  assert.equal(result.hiddenCount, 3, 'The virtual symbol is never counted as an additional item')
  assert.equal(graphHiddenItems(nodes, [], new Set(), representatives).hiddenCount, 3)
})

test('hidden parent cycles and offscreen spatial groups can still reach a confirmed visible neighbor', () => {
  const nodes = [node('a'), node('b'), node('visible')]
  const cyclic = graphHiddenItems(nodes, [edge('a', 'b', 'parent_of'), edge('b', 'a', 'parent_of'), edge('a', 'visible')], new Set(['visible']))
  assert.equal(cyclic.mass.get('visible'), 2)
  const spatial = graphHiddenItems([...nodes, { id: 'group', virtual: true }],
    [edge('a', 'visible'), edge('group', 'visible')], new Set(['visible']), new Map([['a', 'group'], ['b', 'group']]))
  assert.equal(spatial.mass.get('visible'), 2)
  assert.equal(spatial.hiddenCount, 2)
})

test('large folded populations preserve all mass and grow monotonically up to exactly four times the normal diameter', () => {
  const nodes = [node('root'), ...Array.from({ length: 10000 }, (_, index) => node(`leaf-${index}`))]
  const edges = nodes.slice(1).map(item => edge('root', item.id))
  const result = graphHiddenItems(nodes, edges, new Set(['root']))
  assert.equal(result.mass.get('root'), 10000)
  assert.equal(result.hiddenCount, 10000)
  assert.equal(graphHiddenDiameter(20, 0), 20)
  let previous = 20
  for (const mass of [0.5, 1, 5, 50, 255, 10000]) {
    const diameter = graphHiddenDiameter(20, mass)
    assert(diameter > 20 && diameter >= previous && diameter <= 80)
    previous = diameter
  }
  assert.equal(previous, 80)
})
