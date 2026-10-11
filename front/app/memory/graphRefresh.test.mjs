import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reconcileGraph } from './graphRefresh.ts'

const node = (id, title = id) => ({ id, title })
const edge = (id, source, target) => ({ id, source_item_id: source, target_item_id: target })
const records = (nodes, edges = []) => ({ nodes: new Map(nodes.map(node => [node.id, node])), edges: new Map(edges.map(edge => [edge.id, edge])) })

test('unchanged background snapshots preserve records and map identities', () => {
  const current = records([node('a'), node('b')], [edge('ab', 'a', 'b')])
  const next = reconcileGraph(current, current, records([node('a'), node('b')], [edge('ab', 'a', 'b')]))
  assert.equal(next.nodes, current.nodes)
  assert.equal(next.edges, current.edges)
})

test('background changes update only affected records and remove absent nodes and relations', () => {
  const current = records([node('a'), node('b'), node('c')], [edge('ab', 'a', 'b'), edge('ac', 'a', 'c')])
  const next = reconcileGraph(current, current, records([node('a', 'Renamed'), node('c'), node('d')], [edge('ad', 'a', 'd')]))
  assert.deepEqual([...next.nodes.keys()], ['a', 'c', 'd'])
  assert.equal(next.nodes.get('a').title, 'Renamed')
  assert.equal(next.nodes.get('c'), current.nodes.get('c'))
  assert.deepEqual([...next.edges.keys()], ['ad'])
})

test('pages and edits received during a refresh survive late snapshots', () => {
  const baseline = records([node('a'), node('b')], [edge('ab', 'a', 'b')])
  const current = records([node('a', 'Newer foreground edit'), baseline.nodes.get('b'), node('late')],
    [baseline.edges.get('ab'), edge('late-edge', 'a', 'late')])
  const next = reconcileGraph(current, baseline, records([node('a', 'Older background edit'), node('b')], [edge('ab', 'a', 'b')]))
  assert.equal(next.nodes, current.nodes)
  assert.equal(next.edges, current.edges)
})

test('truncated edge pages retain unconfirmed relations but never dangling endpoints', () => {
  const current = records([node('a'), node('b'), node('c')], [edge('ab', 'a', 'b'), edge('ac', 'a', 'c')])
  const next = reconcileGraph(current, current, records([node('a'), node('b')]), true)
  assert.deepEqual([...next.edges.keys()], ['ab'])
})

test('foreground deletions are not resurrected by a late snapshot', () => {
  const baseline = records([node('a'), node('b')], [edge('ab', 'a', 'b')])
  const current = records([baseline.nodes.get('a')])
  const next = reconcileGraph(current, baseline, baseline)
  assert.equal(next.nodes, current.nodes)
  assert.equal(next.edges, current.edges)
})
