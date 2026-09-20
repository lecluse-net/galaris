import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup() {
  const auth = vue.reactive({ isAuthenticated: true, user: { id: 1 } })
  const authorize = vue.reactive({ activeRole: { id: 1 } })
  const requests = []
  const { usePrivilegeStore } = loadTypescript(new URL('./stores/privilegeStore.ts', import.meta.url), {
    vue, pinia,
    '@/core/user/stores/authStore': { useAuthStore: () => auth },
    '@/core/authorize/stores/authorizeStore': { useAuthorizeStore: () => authorize },
    '@/core/authorize/services/privilege.service': { privilegeService: {
      getMyPrivileges() { const pending = deferred(); requests.push(pending); return pending.promise },
    } },
  })
  const store = usePrivilegeStore(pinia.createPinia())
  return { store, auth, authorize, requests, close: () => store.$dispose() }
}

test('concurrent consumers wait for the same privilege response', async () => {
  const state = setup()
  try {
    const first = state.store.loadPrivileges()
    let secondFinished = false
    const second = state.store.loadPrivileges().then(() => { secondFinished = true })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(secondFinished, false, 'page must wait until permissions are available')
    assert.equal(state.requests.length, 1)
    state.requests[0].resolve(['agent.view'])
    await Promise.all([first, second])
    assert.equal(state.store.hasPrivilege('agent.view'), true)
  } finally { state.close() }
})

test('a role change during loading starts its own request and ignores the old response', async () => {
  const state = setup()
  try {
    state.store.init()
    state.authorize.activeRole = { id: 2 }
    await vue.nextTick()
    assert.equal(state.requests.length, 2)
    state.requests[1].resolve(['memory.view'])
    await state.store.loadPrivileges()
    state.requests[0].resolve(['agent.delete'])
    await vue.nextTick()
    assert.equal(state.store.hasPrivilege('memory.view'), true)
    assert.equal(state.store.hasPrivilege('agent.delete'), false)
  } finally { state.close() }
})

test('a failed privilege request cannot cause a render-driven request storm; explicit refresh recovers', async () => {
  const state = setup()
  let stop
  try {
    stop = vue.watchEffect(() => state.store.hasPrivilege('agent.view'))
    state.requests[0].reject(new Error('Network Error'))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(state.requests.length, 1, 'rendering denied controls must not retry the request')
    const retry = state.store.refreshPrivileges()
    state.requests[1].resolve(['agent.view'])
    await retry
    assert.equal(state.store.hasPrivilege('agent.view'), true)
  } finally { stop?.(); state.close() }
})

test('logout discards an outstanding privilege response', async () => {
  const state = setup()
  try {
    state.store.init()
    state.auth.isAuthenticated = false
    state.auth.user = null
    await vue.nextTick()
    state.requests[0].resolve(['agent.delete'])
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(state.store.hasPrivilege('agent.delete'), false)
    assert.deepEqual([...state.store.privileges], ['guest'])
  } finally { state.close() }
})
