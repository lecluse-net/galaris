import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup({ deferProfile = false } = {}) {
  const previous = { window: globalThis.window, localStorage: globalThis.localStorage }
  const storage = new Map()
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  globalThis.window = new EventTarget()
  let generation = 'initial'
  const requests = []
  const localeLoads = []
  const profileWrites = []
  const profileResponses = []
  const authService = {
    saveToken(token) {
      generation = `next-${token}`
      storage.set('access_token', token)
      window.dispatchEvent(new CustomEvent('token', { detail: token }))
    },
    getCurrentUser() { const pending = deferred(); requests.push(pending); return pending.promise },
    getToken: () => storage.get('access_token'),
    async updateProfile(value) {
      profileWrites.push(value)
      if (deferProfile) { const pending = deferred(); profileResponses.push(pending); return pending.promise }
      return { id: 1, ...value }
    },
  }
  const { useAuthStore } = loadTypescript(new URL('./stores/authStore.ts', import.meta.url), {
    vue, pinia,
    '../services/authService': { authService },
    '@/core/api': { sessionGeneration: () => generation, AUTH_TOKEN_CHANGED_EVENT: 'token', SupersededSessionError: class extends Error {} },
    '@/core/i18n': { applyUserLocale: async () => true,
      setLocale(locale, isCurrent) {
        const pending = deferred()
        localeLoads.push({ locale, pending })
        return pending.promise.then(() => isCurrent())
      },
      i18n: { global: { t: key => key } } },
  })
  const store = useAuthStore(pinia.createPinia())
  return { store, requests, localeLoads, profileWrites, profileResponses, storage, changeGeneration() { generation = 'changed' }, close() {
    store.$dispose(); globalThis.window = previous.window; globalThis.localStorage = previous.localStorage
  } }
}

test('document view preferences serialize rapid tab choices and keep the latest tab visible', async () => {
  const state = setup({ deferProfile: true })
  try {
    state.store.user = { id: 1, document_library_mode: 'folders' }
    const topics = state.store.setDocumentLibraryMode('topics')
    const agents = state.store.setDocumentLibraryMode('agents')
    assert.equal(state.store.documentLibraryMode, 'agents')
    await setImmediate()
    assert.equal(state.profileWrites.length, 1)
    state.profileResponses[0].resolve({ id: 1, document_library_mode: 'topics' })
    await topics
    assert.equal(state.store.documentLibraryMode, 'agents')
    await setImmediate()
    state.profileResponses[1].resolve({ id: 1, document_library_mode: 'agents' })
    await agents
    assert.deepEqual(state.profileWrites, [{ document_library_mode: 'topics' }, { document_library_mode: 'agents' }])
    assert.equal(JSON.parse(state.storage.get('user')).document_library_mode, 'agents')
  } finally { state.close() }
})

test('a rejected document view choice restores the last confirmed preference and can retry', async () => {
  const state = setup({ deferProfile: true })
  try {
    state.store.user = { id: 1, document_library_mode: 'folders' }
    const topics = state.store.setDocumentLibraryMode('topics')
    const agents = state.store.setDocumentLibraryMode('agents')
    const denied = assert.rejects(agents, /synthetic failure/)
    await setImmediate()
    state.profileResponses[0].resolve({ document_library_mode: 'topics' })
    await topics; await setImmediate()
    state.profileResponses[1].reject(new Error('synthetic failure'))
    await denied
    assert.equal(state.store.documentLibraryMode, 'topics')
    const retry = state.store.setDocumentLibraryMode('agents')
    await setImmediate()
    state.profileResponses[2].resolve({ document_library_mode: 'agents' })
    await retry
    assert.equal(state.store.documentLibraryMode, 'agents')
  } finally { state.close() }
})

test('a former account view save cannot overwrite a new account and its queue does not block it', async () => {
  const state = setup({ deferProfile: true })
  try {
    state.store.user = { id: 1, document_library_mode: 'folders' }
    const old = state.store.setDocumentLibraryMode('topics')
    await setImmediate()
    state.changeGeneration()
    state.store.user = { id: 2, document_library_mode: 'folders' }
    const current = state.store.setDocumentLibraryMode('agents')
    await setImmediate()
    state.profileResponses[1].resolve({ document_library_mode: 'agents' })
    await current
    state.profileResponses[0].resolve({ document_library_mode: 'topics' })
    await old
    assert.equal(state.store.user.id, 2)
    assert.equal(state.store.documentLibraryMode, 'agents')
    assert.equal(JSON.parse(state.storage.get('user')).id, 2)
  } finally { state.close() }
})

for (const reply of ['before save', 'after save']) test(`a profile read replying ${reply} cannot restore the tab preceding a document view change`, async () => {
  const state = setup({ deferProfile: true })
  try {
    state.store.token = 'active'
    state.store.user = { id: 1, document_library_mode: 'folders' }
    const read = state.store.fetchCurrentUser()
    const save = state.store.setDocumentLibraryMode('agents')
    await setImmediate()
    if (reply === 'after save') {
      state.profileResponses[0].resolve({ document_library_mode: 'agents' })
      await save
    }
    state.requests[0].resolve({ id: 1, document_library_mode: 'folders', display_name: 'Synthetic updated name' })
    await read
    assert.equal(state.store.documentLibraryMode, 'agents')
    if (reply === 'before save') {
      state.profileResponses[0].resolve({ document_library_mode: 'agents' })
      await save
    }
    assert.equal(state.store.user.display_name, 'Synthetic updated name')
  } finally { state.close() }
})

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

test('a language download from a former session cannot write the current profile', async () => {
  const state = setup()
  try {
    const pending = state.store.setLanguage('fr')
    state.changeGeneration()
    state.localeLoads[0].pending.resolve()
    await pending
    assert.deepEqual(state.profileWrites, [])
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
