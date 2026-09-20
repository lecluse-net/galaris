import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup() {
  const previous = { window: globalThis.window, localStorage: globalThis.localStorage }
  const storage = new Map()
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  globalThis.window = new EventTarget()
  let generation = 'initial'
  const requests = []
  const authService = {
    saveToken(token) {
      generation = `next-${token}`
      storage.set('access_token', token)
      window.dispatchEvent(new CustomEvent('token', { detail: token }))
    },
    getCurrentUser() { const pending = deferred(); requests.push(pending); return pending.promise },
    getToken: () => storage.get('access_token'),
  }
  const { useAuthStore } = loadTypescript(new URL('./stores/authStore.ts', import.meta.url), {
    vue, pinia,
    '../services/authService': { authService },
    '@/core/api': { sessionGeneration: () => generation, AUTH_TOKEN_CHANGED_EVENT: 'token', SupersededSessionError: class extends Error {} },
    '@/core/i18n': { applyUserLocale() {}, i18n: { global: { t: key => key } } },
  })
  const store = useAuthStore(pinia.createPinia())
  return { store, requests, changeGeneration() { generation = 'changed' }, close() {
    store.$dispose(); globalThis.window = previous.window; globalThis.localStorage = previous.localStorage
  } }
}

test('a changed role token reloads identity before completing the switch', async () => {
  const state = setup()
  try {
    state.store.user = { id: 1, email: 'one@example.com' }
    const pending = state.store.setToken('role-two')
    assert.equal(state.store.user, null)
    state.requests[0].resolve({ id: 1, email: 'one@example.com', language: 'fr' })
    await pending
    assert.equal(state.store.isAuthenticated, true)
    assert.equal(state.store.user.email, 'one@example.com')
  } finally { state.close() }
})

test('an identity response from the former session cannot populate the store', async () => {
  const state = setup()
  try {
    state.store.token = 'old'
    const pending = state.store.fetchCurrentUser()
    state.changeGeneration()
    state.store.user = { id: 2, email: 'two@example.com' }
    state.requests[0].resolve({ id: 1, email: 'one@example.com' })
    await pending
    assert.equal(state.store.user.id, 2)
    assert.equal(localStorage.getItem('user'), null)
  } finally { state.close() }
})
