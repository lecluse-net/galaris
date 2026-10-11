import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Graph3dChildren } from './graph3dChildren.ts'

test('visible directories finish all pages at rest with bounded concurrency and discard late contexts', async () => {
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
  assert.deepEqual(requests.map(request => request.id), ['a', 'b', 'a', 'c'], 'next pages and queued directories load without another camera event')
  loader.update(['a', 'b', 'c'], 'pose-1')
  assert.equal(requests.length, 4, 'a stationary camera does not duplicate in-flight requests')
  assert.deepEqual(requests[2].cursor, cursor)
  assert.deepEqual(loader.expanded, { a: 1, b: 1 })
  requests[2].resolve({ nodes: [], edges: [], has_more: false })
  requests[3].resolve({ nodes: [], edges: [], has_more: true, next_cursor: { ...cursor, id: 'page-3' } })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(loader.expanded, { a: 2, b: 1, c: 1 }, 'reopening retains the number of pages successfully reached')
  loader.dispose()
  assert(requests[4].signal.aborted)
  requests[4].resolve({ nodes: [{ id: 'late' }], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(merged.length, 4)
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

test('moving away stops subsequent pages and returning resumes the cursor', async () => {
  const requests = []
  const loader = new Graph3dChildren((id, cursor) => new Promise(resolve => requests.push({ id, cursor, resolve })),
    async () => {}, error => { throw error })
  loader.update(['a', 'b', 'c'], 'near')
  loader.update([], 'away')
  const cursor = { id: 'next', activity_at: '2026-01-01T00:00:00Z', role_rank: 1 }
  requests[0].resolve({ nodes: [], edges: [], has_more: true, next_cursor: cursor })
  requests[1].resolve({ nodes: [], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(requests.length, 2, 'neither another page nor queued directories load outside the view')
  loader.update(['a'], 'near')
  assert.deepEqual(requests[2].cursor, cursor)
  requests[2].resolve({ nodes: [], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(loader.expanded, { a: 2, b: 1 })
  loader.dispose()
})

test('failed merges retain their cursor and page count without looping at rest', async () => {
  const cursors = [], errors = [], progress = []
  let rejectMerge = true
  const loader = new Graph3dChildren(async (_id, cursor) => {
    cursors.push(cursor)
    return { nodes: [], edges: [], has_more: false }
  }, async () => { if (rejectMerge) throw new Error('Synthetic render failure') },
  error => errors.push(error), () => progress.push(loader.expanded))
  loader.update(['a'], 'near')
  await new Promise(resolve => setImmediate(resolve))
  loader.update(['a'], 'near')
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(errors.length, 1)
  assert.deepEqual(loader.expanded, {})
  assert.deepEqual(progress, [])
  rejectMerge = false
  loader.update(['a'], 'retry')
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(cursors, [null, null], 'retry fetches the page that failed to merge')
  assert.deepEqual(progress, [{ a: 1 }])
  loader.dispose()
})

test('background region reconciliation never overwrites progress made after its baseline', async () => {
  const cursors = []
  const loader = new Graph3dChildren(async (_id, cursor) => {
    cursors.push(cursor)
    return { nodes: [], edges: [], has_more: false }
  }, async () => {}, error => { throw error })
  await loader.load('a', 'initial')
  assert(loader.completed.has('a'))
  const cursor = { id: 'new-page', activity_at: '2026-01-01T00:00:00Z', role_rank: 1 }
  loader.reconcile('a', 1, cursor, 2)
  loader.update(['a'], 'near')
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(cursors, [null, cursor])
  loader.reconcile('a', 1, null, 1)
  assert.deepEqual(loader.expanded, { a: 3 })
  loader.dispose()
})

test('forgetting a removed directory discards its pending child response', async () => {
  let release
  const merged = []
  const loader = new Graph3dChildren(() => new Promise(resolve => { release = resolve }),
    async page => { merged.push(page) }, error => { throw error })
  loader.update(['a'], 'near')
  loader.forget('a')
  release({ nodes: [{ id: 'late-file' }], edges: [], has_more: false })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(merged, [])
  assert.deepEqual(loader.expanded, {})
  loader.dispose()
})
