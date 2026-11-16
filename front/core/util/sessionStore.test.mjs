import assert from 'node:assert/strict'
import test from 'node:test'
import { defineStore, createPinia } from 'pinia'
import { watchEffect, nextTick } from 'vue'
import { deferred } from '../../test-support/load-typescript.mjs'
import { sessionStoreScope } from '../../test-support/session-store.mjs'

test('independent and nested requests retain their aggregate loading and individual errors', async () => {
  const { withSessionScope, storeRequests } = sessionStoreScope()
  const a = deferred(), b = deferred()
  const definition = defineStore('requests', {
    state: () => ({ loading: false, data: [] }),
    actions: {
      async readA() { this.loading = true; try { await a.promise } finally { this.loading = false } },
      async readB() { this.loading = true; try { await b.promise } finally { this.loading = false } },
      async nested() { this.loading = true; try { await this.readA() } finally { this.loading = false } },
    },
  })
  const store = withSessionScope(definition, { flags: { readA: 'loading', readB: 'loading', nested: 'loading' } })(createPinia())
  const state = storeRequests(store), observed = []
  const stop = watchEffect(() => observed.push(state.readA?.pending ?? 0))
  const first = store.nested(), second = store.readB()
  await nextTick()
  assert.equal(state.readA.pending, 1)
  a.resolve(); await first
  assert.equal(store.loading, true)
  const failure = Error('Synthetic read failure')
  b.reject(failure); await assert.rejects(second, failure)
  assert.equal(store.loading, false)
  assert.equal(state.readB.error, failure)
  assert.equal(state.readA.error, null)
  await nextTick()
  assert.ok(observed.includes(1), 'request diagnostics must themselves be reactive')
  stop(); store.$dispose()
})

test('scope changes clear snapshots immediately while renewal and disposed stores preserve them', async () => {
  const window = new EventTarget()
  let session = 'first'
  const { withSessionScope } = sessionStoreScope(window, () => session)
  const store = withSessionScope(defineStore('scope', { state: () => ({ rows: [], loading: false }) }))(createPinia())
  store.rows = ['Synthetic previous role']
  window.dispatchEvent(new CustomEvent('auth', { detail: 'renewed-token' }))
  assert.equal(store.rows.length, 1)
  session = 'second'; window.dispatchEvent(new Event('storage'))
  assert.deepEqual(store.rows, [])
  store.rows = ['Synthetic second role']
  window.dispatchEvent(new CustomEvent('auth', { detail: null }))
  assert.deepEqual(store.rows, [])
  store.rows = ['Synthetic retained after disposal']
  store.$dispose(); session = 'third'; window.dispatchEvent(new Event('auth'))
  assert.equal(store.rows.length, 1)
})

test('an obsolete request cannot clear a new session loading flag or publish its error', async () => {
  const window = new EventTarget(), old = deferred(), current = deferred()
  let session = 'first'
  const { withSessionScope } = sessionStoreScope(window, () => session)
  const store = withSessionScope(defineStore('pending-scope', {
    state: () => ({ rows: [], error: null, loading: false }),
    actions: { async read(request) {
      this.loading = true
      try { this.rows = await request }
      catch (error) { this.error = error; throw error }
      finally { this.loading = false }
    } },
  }), { flags: { read: 'loading' } })(createPinia())
  const previous = store.read(old.promise)
  session = 'second'; window.dispatchEvent(new Event('storage'))
  const next = store.read(current.promise)
  const error = Error('Synthetic obsolete HTTP session')
  old.reject(error); await assert.rejects(previous, error)
  assert.equal(store.loading, true); assert.equal(store.error, null)
  current.resolve(['Synthetic current row']); await next
  assert.equal(store.loading, false); assert.deepEqual(store.rows, ['Synthetic current row'])
  store.$dispose()
})

test('synchronous query actions used by a reactive view never create request state or rerender loops', async () => {
  const { withSessionScope, storeRequests } = sessionStoreScope()
  const store = withSessionScope(defineStore('render-query', {
    state: () => ({ rows: ['Synthetic value'], loading: false }),
    actions: {
      label(index) { return this.rows[index] },
      async load() { this.loading = true; try { this.rows = ['Synthetic refreshed value'] } finally { this.loading = false } },
    },
  }), { flags: { load: 'loading' } })(createPinia())
  const rendered = []
  const stop = watchEffect(() => rendered.push(store.label(0)))
  await store.load(); await nextTick()
  assert.deepEqual(rendered, ['Synthetic value', 'Synthetic refreshed value'])
  assert.equal(storeRequests(store).label, undefined)
  stop(); store.$dispose()
})

test('the latest request owns its error, including absorbed failures, while unrelated success preserves it', async () => {
  const { withSessionScope, storeRequests, storeRequestFailure } = sessionStoreScope()
  const store = withSessionScope(defineStore('request-errors', {
    state: () => ({ loading: false }),
    actions: {
      async read(request) { await request },
      async optional(request) { const failure = storeRequestFailure(new Proxy(this, {}), 'optional'); try { await request } catch (error) { failure(error) } },
    },
  }), { flags: { read: 'loading', optional: 'loading' } })(createPinia())
  const state = storeRequests(store), old = deferred(), current = deferred()
  const previous = store.read(old.promise), next = store.read(current.promise)
  current.resolve(); await next
  old.reject(Error('Synthetic obsolete failure')); await assert.rejects(previous)
  assert.equal(state.read.error, null)
  const absorbed = Error('Synthetic optional catalogue failure')
  await store.optional(Promise.reject(absorbed))
  assert.equal(state.optional.error, absorbed)
  await store.read(Promise.resolve())
  assert.equal(state.optional.error, absorbed)
  await store.optional(Promise.resolve())
  assert.equal(state.optional.error, null)
  store.$dispose()
})
