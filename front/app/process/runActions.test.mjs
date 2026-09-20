import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

function setup(service) {
  const { useProcessStore } = loadTypescript(new URL('./stores/processStore.ts', import.meta.url), {
    pinia, '../services/processService': { processService: {
      runs: async () => ({ items: [], total: 0, page: 1, page_size: 50 }),
      run: async id => ({ id, status: 'running' }), ...service,
    } },
  })
  const store = useProcessStore(pinia.createPinia())
  let tick, confirmation, admin = true
  const notices = []
  const { useProcessRunActions } = loadTypescript(new URL('./composables/useProcessRunActions.ts', import.meta.url), {
    vue, quasar: { useInterval: () => ({
      registerInterval: fn => { tick = fn }, removeInterval: () => { tick = undefined },
    }) },
  })
  const scope = vue.effectScope()
  const actions = scope.run(() => useProcessRunActions({
    store, canAdmin: () => admin, canOperate: () => true, canAnalyze: () => true,
    notify: (...args) => notices.push(args), errorDetail: error => error.message,
    translate: key => key, confirmRemoval: proceed => { confirmation = proceed },
  }))
  return { store, actions, notices, scope, tick: () => tick?.(), hasTimer: () => !!tick,
    confirm: () => confirmation(), revokeAdmin: () => { admin = false } }
}

test('closing pending run details clears loading and discards late failures', async t => {
  const pending = deferred()
  const state = setup({ run: () => pending.promise })
  t.after(() => state.scope.stop())
  const loading = state.actions.openRun({ id: 'old' })
  assert.equal(state.actions.runDetailLoading.value, true)
  state.actions.runDetailDialog.value = false
  pending.reject(new Error('late'))
  await loading
  assert.equal(state.actions.runDetailLoading.value, false)
  assert.equal(state.store.currentRun, null)
  assert.deepEqual(state.notices, [])
})

test('late retry failure cannot notify a newer selection', async t => {
  const pending = deferred()
  const state = setup({ retryRun: () => pending.promise })
  t.after(() => state.scope.stop())
  await state.actions.openRun({ id: 'old' })
  const action = state.actions.retryCurrent()
  await state.actions.openRun({ id: 'new' })
  pending.reject(new Error('old retry failed'))
  await action
  assert.equal(state.store.currentRun.id, 'new')
  assert.deepEqual(state.notices, [])
})

test('refresh failure still notifies after its own detail reload', async t => {
  const state = setup({ refreshRun: async () => { throw new Error('refresh failed') } })
  t.after(() => state.scope.stop())
  await state.actions.openRun({ id: 'run' })
  await state.actions.refreshCurrent()
  assert.deepEqual(state.notices, [['negative', 'refresh failed']])
})

test('automatic refresh is single flight and stops when the scope is disposed', async () => {
  const pending = deferred()
  let calls = 0
  const state = setup({ refreshRun: () => { calls++; return pending.promise } })
  await state.actions.openRun({ id: 'run' })
  await vue.nextTick()
  assert.equal(state.hasTimer(), true)
  state.tick(); state.tick()
  assert.equal(calls, 1)
  state.scope.stop()
  assert.equal(state.hasTimer(), false)
  pending.resolve()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.store.currentRun, null)
  assert.equal(state.hasTimer(), false)
})

test('removal rechecks privileges after confirmation', async t => {
  let deletes = 0
  const state = setup({ deleteRun: async () => { deletes++ } })
  t.after(() => state.scope.stop())
  await state.actions.removeRun({ id: 'run', status: 'success' })
  state.revokeAdmin()
  await state.confirm()
  assert.equal(deletes, 0)
})
