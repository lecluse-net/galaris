import assert from 'node:assert/strict'
import test from 'node:test'
import { reconcileLibrarySnapshot, reconcileLibraryTree } from './librarySnapshot.ts'

test('incremental library refreshes retain unchanged records while applying order, edits and removals', () => {
  const previous = ['a', 'b', 'c'].map(id => ({ id, title: id, tags: ['original'] }))
  const key = entry => entry.id
  assert.equal(reconcileLibrarySnapshot(previous, [...previous], key), previous)
  assert.equal(reconcileLibrarySnapshot(previous, structuredClone(previous), key), previous)
  const edited = { ...previous[1], tags: ['changed'] }
  const added = { id: 'd', title: 'new', tags: [] }
  const result = reconcileLibrarySnapshot(previous, [edited, { ...previous[0] }, added], key)
  assert.deepEqual(result.map(key), ['b', 'a', 'd'])
  assert.equal(result[0], edited)
  assert.equal(result[1], previous[0])
  assert.equal(result[2], added)
  assert.deepEqual(previous[1].tags, ['original'])
})

test('tree refreshes preserve unchanged subtrees while applying edits, order and removed children', () => {
  const stable = { id: 'stable', children: [{ id: 'child', label: 'original' }] }
  const previous = [stable, { id: 'edited', children: [{ id: 'old-child' }] }]
  assert.equal(reconcileLibraryTree(previous, structuredClone(previous)), previous)
  const incoming = [{ id: 'edited', label: 'renamed' }, stable]
  const result = reconcileLibraryTree(previous, incoming)
  assert.deepEqual(result.map(node => node.id), ['edited', 'stable'])
  assert.equal(result[1], stable)
  assert.equal(result[1].children, stable.children)
  assert.equal(result[0].children, undefined)
  assert.equal(previous[1].children[0].id, 'old-child')
})
