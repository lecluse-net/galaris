import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

async function setup(t, service) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: new Date('2026-09-06T00:00:00Z') })
  const originalWindow = globalThis.window
  globalThis.window = new EventTarget()
  const liveState = loadTypescript(new URL('./liveState.ts', import.meta.url), {
    '../task/facade.ts': { currentAIResponse: result => result.result },
  })
  const { useChatStore } = loadTypescript(new URL('./stores/chat.ts', import.meta.url), {
    pinia, vue,
    axios: { isAxiosError: () => false },
    '@/core/authorize': { usePrivilegeStore: () => ({ hasPrivilege: () => false }) },
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => 'test' },
    '@/core/websocket': { BaseRoom: class {}, websocket: {
      createWebsocket() {}, onEvent() {}, offEvent() {}, onConnect() {}, offConnect() {},
    } },
    '../services/chatService': { chatService: { status: async () => ({ enabled: false }), ...service } },
    '../liveState': liveState, '../runtimeState': {}, '../voiceCall': {},
  })
  const store = useChatStore(pinia.createPinia())
  t.after(() => { store.$dispose(); globalThis.window = originalWindow })
  await store.initialize()
  store.selectedRoom = { id: 'room' }
  store.liveRound = { room_id: 'room', round_id: 'round', active: true, success: true, ai_result: { result: 'Response' } }
  await vue.nextTick()
  return store
}

test('catch-up retries failed HTTP, then stops after the canonical response is visible', async t => {
  let requests = 0
  const store = await setup(t, {
    messages: async () => {
      if (++requests === 1) throw Error('Temporary network failure')
      return { items: [{ id: 'response', external_id: 'response', created_at: '2026-09-06', text: 'Response' }], total: 1 }
    },
    activity: async () => ({ items: [{ id: 'round', status: 'SUCCEEDED', response_message_id: 'response' }], total: 1 }),
  })
  t.mock.timers.tick(3_000)
  await setImmediate()
  assert.equal(requests, 1)
  t.mock.timers.tick(3_000)
  await setImmediate()
  assert.equal(store.messages[0].id, 'response')
  assert.equal(store.liveRound.active, false)
  t.mock.timers.tick(30_000)
  await setImmediate()
  assert.equal(requests, 2)
})

for (const stop of ['disconnect', '$dispose']) {
  test(`catch-up cancels its timer on ${stop}`, async t => {
    let requests = 0
    const store = await setup(t, { messages: async () => { requests++; throw Error('Should not run') } })
    store[stop]()
    t.mock.timers.tick(30_000)
    await setImmediate()
    assert.equal(requests, 0)
  })
}
