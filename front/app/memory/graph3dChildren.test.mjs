import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Graph3dChildren } from './graph3dChildren.ts'

test('region loading bounds concurrency, deduplicates stationary cameras, resumes cursors and discards late contexts', async () => {
  const requests = [], merged = [], errors = []
  const loader = new Graph3dChildren((id, cursor, signal) => new Promise(resolve => requests.push({ id, cursor, signal, resolve })),
    async page => { merged.push(page) }, error => errors.push(error))
  loader.update(['a', 'b', 'c'], 'pose-1')
  loader.update(['a', 'b', 'c'], 'pose-1')
  assert.deepEqual(requests.map(request => request.id), ['a', 'b'])
  const cursor = { id: 'page-2', activity_at: '2026-01-01T00:00:00Z', role_rank: 1 }
  requests[0].resolve({ nodes: [], edges: [], has_more: true, next_cursor: cursor })
  requests[1].resolve({ nodes: [], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  loader.update(['a'], 'pose-1')
  assert.equal(requests.length, 2, 'a static camera does not download the entire subtree')
  loader.update(['a'], 'pose-2')
  assert.deepEqual(requests[2].cursor, cursor)
  assert.deepEqual(loader.expanded, { a: 1, b: 1 })
  requests[2].resolve({ nodes: [], edges: [], has_more: true, next_cursor: { ...cursor, id: 'page-3' } })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(loader.expanded, { a: 2, b: 1 }, 'reopening retains the number of pages already reached')
  loader.update(['a'], 'pose-3')
  loader.dispose()
  assert(requests[3].signal.aborted)
  requests[3].resolve({ nodes: [{ id: 'late' }], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(merged.length, 3)
  assert.deepEqual(errors, [])
})

test('failed regions can retry on another movement and do not save an unopened branch', async () => {
  let attempts = 0
  const errors = []
  const loader = new Graph3dChildren(async () => {
    if (++attempts === 1) throw new Error('Synthetic temporary failure')
    return { nodes: [], edges: [], has_more: false }
  }, async () => {}, error => errors.push(error))
  await loader.load('a', 'first')
  assert.equal(errors.length, 1)
  assert.deepEqual(loader.expanded, {})
  await loader.load('a', 'retry')
  assert.deepEqual(loader.expanded, { a: 1 })
  loader.dispose()
})
