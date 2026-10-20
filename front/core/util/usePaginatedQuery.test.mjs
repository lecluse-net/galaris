import assert from 'node:assert/strict'
import { test } from 'node:test'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

const { usePaginatedQuery } = loadTypescript(new URL('./usePaginatedQuery.ts', import.meta.url), { vue })

function query(fetchPage, initial = {}) {
  const scope = vue.effectScope()
  const pagination = vue.ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, ...initial })
  const state = scope.run(() => usePaginatedQuery(pagination, fetchPage))
  return { ...state, pagination, stop: () => scope.stop() }
}

test('paginated queries retain rows on refresh failure and recover on retry', async () => {
  const requests = []
  const state = query(() => { const request = deferred(); requests.push(request); return request.promise })
  try {
    const initial = state.load()
    requests[0].resolve({ items: ['saved'], total: 73 })
    await initial
    const refresh = state.load()
    assert.equal(state.loading.value, true)
    assert.deepEqual(state.result.value.items, ['saved'])
    requests[1].reject(new Error('Synthetic outage'))
    await refresh
    assert.equal(state.loading.value, false)
    assert.equal(state.error.value, true)
    assert.equal(state.pagination.value.rowsNumber, 73)
    assert.deepEqual(state.result.value.items, ['saved'])
    const retry = state.load()
    requests[2].resolve({ items: ['current'], total: 1 })
    await retry
    assert.equal(state.error.value, false)
    assert.deepEqual(state.result.value.items, ['current'])
  } finally { state.stop() }
})

test('only the latest query can publish rows, errors and loading across context changes and disposal', async () => {
  const requests = []
  const state = query(() => { const request = deferred(); requests.push(request); return request.promise })
  const old = state.load()
  state.reset()
  const current = state.load()
  requests[0].reject(new Error('Obsolete context'))
  await old
  assert.equal(state.loading.value, true)
  assert.equal(state.error.value, false)
  requests[1].resolve({ items: ['current context'], total: 1 })
  await current
  const slow = state.load()
  const fast = state.load()
  requests[3].resolve({ items: ['newer'], total: 1 })
  await fast
  requests[2].resolve({ items: ['older'], total: 1 })
  await slow
  assert.deepEqual(state.result.value.items, ['newer'])
  const pending = state.load()
  state.stop()
  requests[4].resolve({ items: ['disposed'], total: 1 })
  await pending
  await state.load()
  assert.equal(state.result.value, null)
  assert.equal(state.loading.value, false)
  assert.equal(requests.length, 5)
})

test('page recovery preserves size and sorting and stops when totals keep shrinking', async () => {
  const pages = []
  const responses = [{ items: [], total: 55 }, { items: ['last page'], total: 55 },
    { items: [], total: 21 }, { items: [], total: 0 }, { items: [], total: 0 }]
  const state = query(async page => { pages.push(page); return responses.shift() },
    { page: 9, rowsPerPage: 20, sortBy: 'created_at', descending: true })
  try {
    await state.load()
    assert.deepEqual(pages.map(page => page.page), [9, 3])
    assert.ok(pages.every(page => page.rowsPerPage === 20 && page.sortBy === 'created_at' && page.descending))
    assert.equal(state.pagination.value.page, 3)
    assert.deepEqual(state.result.value.items, ['last page'])
    await state.load()
    assert.equal(pages.length, 4)
    assert.equal(state.error.value, true)
    assert.equal(state.pagination.value.page, 1)
    assert.deepEqual(state.result.value.items, ['last page'])
    await state.load()
    assert.equal(state.error.value, false)
    assert.equal(state.pagination.value.rowsNumber, 0)
    assert.deepEqual(state.result.value.items, [])
  } finally { state.stop() }
})
