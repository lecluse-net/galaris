import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as axios from 'axios'
import { loadTypescript, deferred } from '../../../test-support/load-typescript.mjs'

const row = (id, host = 'synthetic.example.test') => ({ id, agent_id: id, tool_id: 9, active: true,
  params: { host, token: null }, configured_params: ['token'] })

function setup() {
  let generation = 'one'
  const requests = []
  const service = Object.fromEntries(['getConnectionOverviews', 'getConnectionParams', 'updateConnection', 'createOrUpdateParamsBulk'].map(method => [method, (...args) => {
    const pending = deferred()
    requests.push({ method, args, ...pending })
    return pending.promise
  }]))
  const { useConnectionStore } = loadTypescript(new URL('./connectionStore.ts', import.meta.url), {
    pinia, axios,
    '@/core/api': { sessionGeneration: () => generation },
    '../services/connectionService': { __esModule: true, default: service },
    '../events': { CONNECTIONS_CHANGED_EVENT: 'connections-changed' },
  })
  return { store: useConnectionStore(pinia.createPinia()), requests, switchSession: () => { generation = 'two' } }
}

test('overview loads beyond 500 rows and publishes parameters atomically, including removals', async () => {
  const { store, requests } = setup()
  const pending = store.fetchConnectionOverview()
  requests[0].resolve({ data: Array.from({ length: 500 }, (_, i) => row(i + 1)) })
  await Promise.resolve()
  assert.equal(store.connections.length, 0)
  assert.equal(store.loading, true)
  assert.deepEqual(requests[1].args, [500, 500])
  requests[1].resolve({ data: [row(501)] })
  await pending
  assert.equal(store.connections.length, 501)
  assert.equal(store.getParamsForConnection(501).host, 'synthetic.example.test')
  const refresh = store.fetchConnectionOverview()
  requests[2].resolve({ data: [{ ...row(501, 'updated.example.test'), configured_params: [] }] })
  await refresh
  assert.deepEqual(store.connections.map(connection => connection.id), [501])
  assert.equal(store.getParamsForConnection(1), null)
  assert.equal(store.getParamsForConnection(501).host, 'updated.example.test')
  assert.deepEqual(store.getConfiguredParamsForConnection(501), [])
})

test('late overview responses and failures cannot replace a newer snapshot or session', async () => {
  const { store, requests, switchSession } = setup()
  const old = store.fetchConnectionOverview()
  const current = store.fetchConnectionOverview()
  requests[1].resolve({ data: [row(2)] })
  await current
  requests[0].resolve({ data: [row(1)] })
  await old
  assert.deepEqual(store.connections.map(connection => connection.id), [2])
  const previousSession = store.fetchConnectionOverview()
  switchSession()
  const newSession = store.fetchConnectionOverview()
  requests[3].resolve({ data: [row(3)] })
  await newSession
  requests[2].reject(new Error('Old session failure'))
  await previousSession
  assert.deepEqual(store.connections.map(connection => connection.id), [3])
  assert.equal(store.error, null)
  assert.equal(store.loading, false)
})

test('a failed page preserves the complete previous snapshot and allows retry', async () => {
  const { store, requests } = setup()
  const initial = store.fetchConnectionOverview()
  requests[0].resolve({ data: [row(1)] })
  await initial
  const failed = store.fetchConnectionOverview()
  requests[1].resolve({ data: Array.from({ length: 500 }, (_, i) => row(i + 2)) })
  await Promise.resolve()
  requests[2].reject(new Error('Synthetic page failure'))
  await assert.rejects(failed, /Synthetic page failure/)
  assert.deepEqual(store.connections.map(connection => connection.id), [1])
  const retry = store.fetchConnectionOverview()
  requests[3].resolve({ data: [] })
  await retry
  assert.equal(store.error, null)
  assert.deepEqual(store.connections, [])
  assert.equal(store.getParamsForConnection(1), null)
})

test('saving parameters supersedes older list and editor reads', async () => {
  const { store, requests } = setup()
  const overview = store.fetchConnectionOverview()
  const oldParams = store.fetchConnectionParams(1)
  const save = store.createOrUpdateParamsBulk(1, { host: 'saved.example.test' })
  requests[2].resolve({ data: [] })
  await Promise.resolve()
  requests[3].resolve({ data: { params: { host: 'saved.example.test' }, configured_params: [] } })
  await save
  requests[0].resolve({ data: [row(1, 'old.example.test')] })
  requests[1].resolve({ data: { params: { host: 'old.example.test' }, configured_params: ['token'] } })
  await Promise.all([overview, oldParams])
  assert.equal(store.getParamsForConnection(1).host, 'saved.example.test')
  assert.deepEqual(store.getConfiguredParamsForConnection(1), [])
})

test('revoked access clears the previously displayed parameters', async () => {
  const { store, requests } = setup()
  const initial = store.fetchConnectionOverview()
  requests[0].resolve({ data: [row(1)] })
  await initial
  const denied = store.fetchConnectionOverview()
  requests[1].reject(new axios.AxiosError('Forbidden', undefined, undefined, undefined, { status: 403 }))
  await assert.rejects(denied, /Forbidden/)
  assert.deepEqual(store.connections, [])
  assert.equal(store.getParamsForConnection(1), null)
})
