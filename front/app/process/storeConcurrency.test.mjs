import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

function setup(service) {
  const { useProcessStore } = loadTypescript(new URL('./stores/processStore.ts', import.meta.url), {
    pinia, '../services/processService': { processService: service },
  })
  return useProcessStore(pinia.createPinia())
}

test('a late process page cannot replace the latest filter or clear its loading state', async () => {
  const old = deferred(), current = deferred()
  let calls = 0
  const store = setup({ runs: () => ++calls === 1 ? old.promise : current.promise })
  const first = store.loadRuns('old', 2)
  const second = store.loadRuns('new', 1)
  old.resolve({ items: [{ id: 'stale' }], total: 1, page: 2, page_size: 50 })
  await first
  assert.equal(store.loadingRuns, true)
  assert.deepEqual(store.runs, [])
  current.resolve({ items: [{ id: 'current' }], total: 1, page: 1, page_size: 50 })
  await second
  assert.equal(store.runsWorkflowId, 'new')
  assert.equal(store.runs[0].id, 'current')
  assert.equal(store.loadingRuns, false)
})

test('late process details and analysis cannot replace the selected run', async () => {
  const old = deferred(), current = deferred(), analysis = deferred()
  const store = setup({ run: id => id === 'old' ? old.promise : current.promise, analyzeRun: () => analysis.promise })
  const first = store.openRun('old')
  const analyzing = store.analyzeRun('old')
  const second = store.openRun('new')
  current.resolve({ id: 'new' })
  await second
  old.resolve({ id: 'old' })
  analysis.resolve({ text: 'stale analysis' })
  await Promise.all([first, analyzing])
  assert.equal(store.currentRun.id, 'new')
  assert.equal(store.currentAnalysis, null)
})

for (const action of ['refreshRun', 'cancelRun', 'deleteRun']) {
  for (const selection of ['new', null]) {
    test(`${action} cannot replace a newer selection (${selection})`, async () => {
      const pending = deferred()
      const store = setup({
        [action]: () => pending.promise, run: async id => ({ id }),
        runs: async () => ({ items: [], total: 0, page: 1, page_size: 50 }),
      })
      await store.openRun('old')
      const operation = store[action]('old')
      if (selection) await store.openRun(selection)
      else store.closeRun()
      pending.resolve()
      await operation
      assert.equal(store.currentRun?.id ?? null, selection)
    })
  }
}

test('closing a pending detail invalidates its response', async () => {
  const pending = deferred()
  const store = setup({ run: () => pending.promise })
  const operation = store.openRun('old')
  store.closeRun()
  pending.resolve({ id: 'old' })
  await operation
  assert.equal(store.currentRun, null)
})

for (const action of ['refreshRun', 'cancelRun', 'deleteRun', 'analyzeRun']) {
  test(`${action} discards an error for a selection that has been closed`, async () => {
    const pending = deferred()
    const store = setup({
      [action]: () => pending.promise, run: async id => ({ id }),
      runs: async () => ({ items: [], total: 0, page: 1, page_size: 50 }),
    })
    await store.openRun('old')
    const operation = store[action]('old')
    store.closeRun()
    pending.reject(new Error('late failure'))
    await operation
    assert.equal(store.currentRun, null)
  })
}
