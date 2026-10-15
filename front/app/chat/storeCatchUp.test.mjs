import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

async function setup(t, service, canCall = false, listeners = new Map()) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: new Date('2026-09-06T00:00:00Z') })
  const originalWindow = globalThis.window
  globalThis.window = new EventTarget()
  const liveState = loadTypescript(new URL('./liveState.ts', import.meta.url), {
    '../task/facade.ts': { currentAIResponse: result => result.result },
  })
  const { useChatStore } = loadTypescript(new URL('./stores/chat.ts', import.meta.url), {
    pinia, vue,
    axios: { isAxiosError: () => false },
    '@/core/authorize': { usePrivilegeStore: () => ({ hasPrivilege: () => canCall }) },
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => 'test' },
    '@/core/websocket': { BaseRoom: class {}, websocket: {
      createWebsocket() {},
      onEvent(subject, action, callback) { listeners.set(`${subject}.${action}`, callback) },
      offEvent() {}, onConnect(callback) { listeners.set('connect', callback) }, offConnect() {}, joinRoom() {}, leaveRoom() {},
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

test('opening a room displays its messages while commands are still loading and ignores stale commands', async t => {
  let release
  const room = { id: 'room', writable: true }
  const store = await setup(t, {
    room: async id => ({ ...room, id }),
    messages: async () => ({ items: [{ id: 'message', text: 'Hello' }], total: 1 }),
    activity: async () => ({ items: [], total: 0 }),
    commands: id => id === 'room' ? new Promise(resolve => { release = resolve }) : Promise.resolve({ commands: [] }),
  })
  const opening = store.selectRoom(room)
  await setImmediate()
  assert.equal(store.messages[0]?.text, 'Hello')
  assert.equal(store.loadingSelectedRoom, false)
  await opening
  await store.selectRoom({ ...room, id: 'other' })
  release({ commands: [{ name: 'stale' }] })
  await setImmediate()
  assert.deepEqual(store.commands, [])
})

test('an unavailable command catalog does not hide the conversation or reject opening', async t => {
  const room = { id: 'room', writable: true }
  const store = await setup(t, {
    room: async () => room,
    messages: async () => ({ items: [{ id: 'message', text: 'Hello' }], total: 1 }),
    activity: async () => ({ items: [], total: 0 }),
    commands: async () => { throw Error('Temporary failure') },
  })
  await store.selectRoom(room)
  await setImmediate()
  assert.equal(store.messages[0]?.text, 'Hello')
  assert.equal(store.loadingSelectedRoom, false)
  assert.deepEqual(store.commands, [])
})

test('call controls wait for the current call while messages are already readable', async t => {
  let release
  const room = { id: 'room', writable: false, kind: 'direct', source: null }
  const store = await setup(t, {
    room: async () => room,
    messages: async () => ({ items: [{ id: 'message', text: 'Hello' }], total: 1 }),
    activity: async () => ({ items: [], total: 0 }),
    activeCall: () => new Promise(resolve => { release = resolve }),
    callStatus: async () => ({ available: true }),
  }, true)
  await store.selectRoom(room)
  await setImmediate()
  assert.equal(store.messages[0]?.text, 'Hello')
  assert.equal(store.callAvailable, false)
  release({ call_id: 'existing-call' })
  await setImmediate()
  assert.equal(store.activeCall.call_id, 'existing-call')
  assert.equal(store.callAvailable, true)
})

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

test('a burst of conversation signals bounds HTTP work and retains a newer invalidation', async t => {
  const listeners = new Map(), first = deferred(), roomsLoaded = deferred()
  let requests = 0, active = 0, peak = 0, revision = 1
  const store = await setup(t, {
    room: async () => {
      const captured = revision
      requests++; peak = Math.max(peak, ++active)
      try {
        if (requests === 1) await first.promise
        return { id: 'room', label: `Revision ${captured}` }
      } finally { active-- }
    },
    messages: async () => ({ items: [], total: 0 }),
    activity: async () => ({ items: [], total: 0 }),
    rooms: async () => {
      if (requests >= 2) roomsLoaded.resolve()
      return { items: [{ id: 'room', label: `Revision ${revision}` }], total: 1 }
    },
  }, false, listeners)
  store.liveRound = null
  listeners.get('chat.activity')({ data: { room_id: 'room' } })
  await setImmediate()
  revision = 2
  for (let index = 0; index < 30; index++) {
    listeners.get('chat.activity')({ data: { room_id: 'room' } })
  }
  first.resolve()
  await roomsLoaded.promise
  await setImmediate()
  assert.equal(peak, 1, 'only one signal refresh may read the room at a time')
  assert.equal(requests, 2, 'the burst must converge with one follow-up read')
  assert.equal(store.selectedRoom.label, 'Revision 2')
})

test('signal refresh retries an invalidation after a failed read', async t => {
  const listeners = new Map(), first = deferred()
  let requests = 0
  const store = await setup(t, {
    room: async () => {
      if (++requests === 1) await first.promise
      return { id: 'room', label: 'Recovered' }
    },
    messages: async () => ({ items: [], total: 0 }),
    activity: async () => ({ items: [], total: 0 }),
    rooms: async () => ({ items: [], total: 0 }),
  }, false, listeners)
  store.liveRound = null
  listeners.get('chat.activity')({ data: { room_id: 'room' } })
  listeners.get('chat.activity')({ data: { room_id: 'room' } })
  first.reject(Error('Temporary failure'))
  await setImmediate()
  assert.equal(requests, 2)
  assert.equal(store.selectedRoom.label, 'Recovered')
})

test('a blocked signal refresh cannot delay navigation or overwrite the new room', async t => {
  const listeners = new Map(), first = deferred()
  const store = await setup(t, {
    room: async id => {
      if (id === 'room') await first.promise
      return { id, label: id }
    },
    messages: async id => ({ items: [{ id, text: id }], total: 1 }),
    activity: async () => ({ items: [], total: 0 }),
    rooms: async () => ({ items: [], total: 0 }),
  }, false, listeners)
  store.liveRound = null
  listeners.get('chat.activity')({ data: { room_id: 'room' } })
  await store.selectRoom({ id: 'other' })
  listeners.get('chat.activity')({ data: { room_id: 'other' } })
  await setImmediate()
  assert.equal(store.selectedRoom.id, 'other')
  assert.equal(store.messages[0].text, 'other')
  first.resolve()
  await setImmediate()
  assert.equal(store.selectedRoom.id, 'other')
})

test('reconnection starts a fresh projection while the previous HTTP request is blocked', async t => {
  const listeners = new Map(), first = deferred()
  let requests = 0
  const store = await setup(t, {
    room: async () => {
      if (++requests === 1) {
        await first.promise
        return { id: 'room', label: 'Obsolete connection' }
      }
      return { id: 'room', label: 'Reconnected' }
    },
    messages: async () => ({ items: [], total: 0 }),
    activity: async () => ({ items: [], total: 0 }),
    rooms: async () => ({ items: [], total: 0 }),
  }, false, listeners)
  store.liveRound = null
  listeners.get('chat.activity')({ data: { room_id: 'room' } })
  listeners.get('connect')()
  await setImmediate()
  assert.equal(store.selectedRoom.label, 'Reconnected')
  first.resolve()
  await setImmediate()
  assert.equal(store.selectedRoom.label, 'Reconnected')
})
