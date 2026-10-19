import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { applyConversationRuntimeEvent } from './runtimeState.ts'
import { emptyAIResult } from '../task/facade.ts'
import { reconcileRealtimeCall } from './voiceCall.ts'

async function setup(t, service, canCall = false, listeners = new Map()) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: new Date('2026-09-06T00:00:00Z') })
  const originalWindow = globalThis.window
  globalThis.window = new EventTarget()
  const liveState = loadTypescript(new URL('./liveState.ts', import.meta.url), {
    '../task/facade.ts': { currentAIResponse: result => result.result },
  })
  const { useChatStore } = loadTypescript(new URL('./stores/chat.ts', import.meta.url), {
    pinia, vue,
    axios: { isAxiosError: error => error?.isAxiosError === true },
    '@/core/authorize': { usePrivilegeStore: () => ({ hasPrivilege: () => canCall }) },
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => 'test' },
    '@/core/websocket': { BaseRoom: class {}, websocket: {
      createWebsocket() {},
      onEvent(subject, action, callback) { listeners.set(`${subject}.${action}`, callback) },
      offEvent() {}, onConnect(callback) { listeners.set('connect', callback) }, offConnect() {}, joinRoom() {}, leaveRoom() {},
    } },
    '../services/chatService': { chatService: { status: async () => ({ enabled: false }), ...service } },
    '../liveState': liveState, '../runtimeState': { applyConversationRuntimeEvent }, '../voiceCall': { reconcileRealtimeCall },
  })
  const store = useChatStore(pinia.createPinia())
  t.after(() => { store.$dispose(); globalThis.window = originalWindow })
  await store.initialize()
  store.selectedRoom = { id: 'room' }
  store.liveRound = { room_id: 'room', round_id: 'round', active: true, success: true, ai_result: { result: 'Response' } }
  await vue.nextTick()
  return store
}

test('a burst renders one cumulative response without losing Unicode and discards buffered progress on disconnect', async t => {
  const listeners = new Map()
  const store = await setup(t, {}, false, listeners)
  store.liveRound = { room_id: 'room', round_id: 'round', active: true, success: true,
    last_sequence: 0, ai_result: emptyAIResult() }
  let renders = 0
  const stop = vue.watch(() => store.liveRound, () => { renders++ }, { flush: 'sync' })
  t.after(stop)
  const emit = sequence => listeners.get('chat.runtime')({ data: {
    room_id: 'room', round_id: 'round', kind: 'message', sequence,
    message: { type: 'text', content: 'Été🙂漢字', stream_id: 'answer', stream_mode: 'delta' },
  } })
  for (let sequence = 1; sequence <= 1000; sequence++) emit(sequence)
  assert.equal(renders, 0)
  t.mock.timers.tick(50)
  assert.equal(renders, 1)
  assert.equal(store.liveRound.ai_result.result, 'Été🙂漢字'.repeat(1000))
  emit(1001)
  store.disconnect()
  t.mock.timers.tick(50)
  assert.equal(renders, 1)
  assert.equal(store.liveRound.ai_result.result, 'Été🙂漢字'.repeat(1000))
})

const delta = (sequence, content, overrides = {}) => ({
  room_id: 'room', round_id: 'round', attempt: 1, kind: 'message', sequence,
  message: { type: 'text', stream_id: 'answer', stream_mode: 'delta', content, ...overrides },
})
for (const [scenario, events] of [
  ['Unicode and empty fragments', [delta(1, 'É'), delta(2, ''), delta(3, 'té🙂'), delta(4, '漢字')]],
  ['completion and failure', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'), delta(4, '', { stream_complete: true }),
    delta(5, 'Failure', { success: false }), delta(6, 'D'), delta(7, 'E')]],
  ['cost and duration', [delta(1, 'A', { cost: 0.1, execution_time: 0.2 }), delta(2, 'B'), delta(3, 'C'),
    delta(4, 'D', { cost: 0.2, execution_time: 0.3 }), delta(5, 'E')]],
  ['interleaved reasoning and tools', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'),
    delta(4, 'Think ', { type: 'tool', tool_name: 'thinking', stream_id: 'thought' }),
    delta(5, 'é', { type: 'tool', tool_name: 'thinking', stream_id: 'thought' }),
    delta(6, '🙂', { type: 'tool', tool_name: 'thinking', stream_id: 'thought' }),
    delta(7, 'Read', { type: 'tool', tool_name: 'file_read', stream_id: 'read', tool_call_external_id: 'read-1', stream_mode: 'snapshot' }),
    delta(8, 'D'), delta(9, 'E'), delta(10, 'F')]],
  ['duplicates, late fragments and gaps', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'), delta(2, 'Duplicate'),
    delta(5, 'Missing predecessor'), delta(4, 'D'), delta(5, 'E'), delta(6, 'F')]],
  ['snapshots', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'),
    { ...delta(3, ''), kind: 'snapshot', result: { ...emptyAIResult(), result: 'ABC',
      messages: [{ type: 'text', stream_id: 'answer', content: 'ABC' }] } }, delta(4, 'D'), delta(5, 'E')]],
  ['topic changes', [delta(1, 'A'), { ...delta(2, 'B'), topic_id: 'topic-1' },
    { ...delta(3, 'C'), topic_id: 'topic-1' }, { ...delta(4, 'D'), topic_id: 'topic-2' }, delta(5, 'E'), delta(6, 'F')]],
  ['reset and reused identities', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'),
    { ...delta(4, ''), kind: 'reset' }, delta(5, 'D'), delta(6, 'E'), delta(7, 'F')]],
  ['attempt changes', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'),
    { ...delta(0, ''), kind: 'started', attempt: 2 },
    { ...delta(1, 'New ', { stream_id: 'new-answer' }), attempt: 2 },
    { ...delta(2, 'answer', { stream_id: 'new-answer' }), attempt: 2 }, delta(4, 'Old attempt')]],
  ['terminal delivery', [delta(1, 'A'), delta(2, 'B'), delta(3, 'C'),
    { ...delta(4, ''), kind: 'finished', success: true }, delta(5, 'Late fragment')]],
  ['legacy messages', [delta(1, 'A', { stream_id: undefined }), delta(2, 'B', { stream_id: undefined }),
    delta(3, 'C', { stream_id: undefined })]],
]) {
  test(`buffered runtime preserves sequential semantics for ${scenario}`, async t => {
    const listeners = new Map(), blockedRead = deferred()
    const store = await setup(t, {
      room: () => blockedRead.promise,
      messages: async () => ({ items: [], total: 0 }),
      activity: async () => ({ items: [], total: 0 }),
      rooms: async () => ({ items: [], total: 0 }),
    }, false, listeners)
    const initial = applyConversationRuntimeEvent(null, { ...delta(0, ''), kind: 'started' }).round
    const initialCopy = structuredClone(initial), inputCopy = structuredClone(events)
    store.liveRound = initial
    let expected = initial
    for (const event of events) {
      const update = applyConversationRuntimeEvent(expected, event)
      if (update && !update.needsSnapshot) expected = update.round
      listeners.get('chat.runtime')({ data: event })
    }
    t.mock.timers.tick(50)
    assert.deepEqual(store.liveRound, expected)
    assert.deepEqual(initial, initialCopy, 'published snapshots remain immutable')
    assert.deepEqual(events, inputCopy, 'transport events remain immutable')
  })
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

test('overlapping optional controls share pending reads while every room projection stays fresh', async t => {
  const pending = deferred()
  let denied = false
  const counts = { room: 0, messages: 0, activity: 0, commands: 0, activeCall: 0, callStatus: 0 }
  const room = { id: 'room', writable: true, kind: 'direct', source: null }
  const store = await setup(t, {
    room: async () => { counts.room++; return room },
    messages: async () => {
      counts.messages++
      return { items: [{ id: 'message', text: `Fresh ${counts.messages}` }], total: 1 }
    },
    activity: async () => { counts.activity++; return { items: [], total: 0 } },
    commands: async () => {
      counts.commands++
      await pending.promise
      if (denied) throw { isAxiosError: true, response: { status: 403 } }
      return { commands: [] }
    },
    activeCall: async () => { counts.activeCall++; await pending.promise; return { call_id: 'call' } },
    callStatus: async () => { counts.callStatus++; await pending.promise; return { available: true } },
  }, true)
  try {
    await store.selectRoom(room)
    for (let index = 0; index < 9; index++) await store.refreshSelected()
    assert.equal(store.messages[0].text, 'Fresh 10')
    assert.deepEqual(counts, { room: 10, messages: 10, activity: 10, commands: 1, activeCall: 1, callStatus: 1 })
  } finally { pending.resolve() }
  await setImmediate()
  assert.equal(store.activeCall.call_id, 'call')
  assert.equal(store.callAvailable, true)
  await store.refreshSelected()
  await setImmediate()
  assert.equal(counts.commands, 2, 'settled reads are refreshed rather than cached')
  assert.equal(counts.activeCall, 2)
  assert.equal(counts.callStatus, 2)
  denied = true
  await store.refreshSelected()
  await setImmediate()
  assert.equal(store.selectedRoom, null, 'a current denial still purges protected content')
  assert.deepEqual(store.messages, [])
})

test('a failed call-status read retries without duplicating the pending active-call read', async t => {
  const pending = deferred()
  let activeReads = 0, statusReads = 0
  const room = { id: 'room', writable: false, kind: 'direct', source: null }
  const store = await setup(t, {
    room: async () => room,
    messages: async () => ({ items: [], total: 0 }),
    activity: async () => ({ items: [], total: 0 }),
    activeCall: async () => { activeReads++; await pending.promise; return { call_id: 'call' } },
    callStatus: async () => { if (++statusReads === 1) throw Error('Temporary failure'); return { available: true } },
  }, true)
  await store.selectRoom(room)
  await setImmediate()
  await store.refreshSelected()
  assert.equal(activeReads, 1)
  assert.equal(statusReads, 2)
  pending.resolve()
  await setImmediate()
  assert.equal(store.activeCall.call_id, 'call')
  assert.equal(store.callAvailable, true)
})

test('a call transition cannot hide an access denial for the current selection and session', async t => {
  const pending = deferred()
  const room = { id: 'room', writable: true }
  const store = await setup(t, {
    room: async () => room,
    messages: async () => ({ items: [{ id: 'protected' }], total: 1 }),
    activity: async () => ({ items: [], total: 0 }),
    commands: () => pending.promise,
  })
  await store.selectRoom(room)
  store.prepareCallStart()
  pending.reject({ isAxiosError: true, response: { status: 403 } })
  await setImmediate()
  assert.equal(store.selectedRoom, null)
  assert.deepEqual(store.messages, [])
})

for (const transition of ['reopen', 'room', 'session', 'reconnect', 'call-start', 'call-stop', 'call-event']) {
  test(`pending optional controls are isolated after ${transition}`, async t => {
    const old = deferred(), listeners = new Map()
    const room = { id: 'room', writable: true, kind: 'direct', source: null }
    let commandReads = 0, callReads = 0, statusReads = 0
    const store = await setup(t, {
      room: async id => ({ ...room, id }),
      messages: async () => ({ items: [], total: 0 }),
      activity: async () => ({ items: [], total: 0 }),
      rooms: async () => ({ items: [], total: 0 }),
      commands: async () => {
        const version = ++commandReads
        if (version === 1) await old.promise
        return { commands: [{ name: version === 1 ? 'old' : 'new' }] }
      },
      activeCall: async () => {
        const version = ++callReads
        if (version === 1) await old.promise
        return { call_id: version === 1 ? 'old' : 'new' }
      },
      callStatus: async () => {
        const version = ++statusReads
        if (version === 1) await old.promise
        return { available: version > 1 }
      },
    }, true, listeners)
    await store.selectRoom(room)
    if (transition === 'reopen') await store.selectRoom(room)
    else if (transition === 'room') await store.selectRoom({ ...room, id: 'other' })
    else if (transition === 'reconnect') listeners.get('connect')()
    else if (transition === 'call-event') listeners.get('chat.call')({ data: { room_id: 'room', call_id: 'old', status: 'ended' } })
    else {
      if (transition === 'session') window.dispatchEvent(new Event('auth'))
      if (transition === 'call-start') store.prepareCallStart()
      if (transition === 'call-stop') store.markCallStopping('old')
      await store.refreshSelected()
    }
    await setImmediate()
    assert.equal(commandReads, 2)
    assert.equal(callReads, 2)
    assert.equal(statusReads, 2)
    assert.equal(store.commands[0].name, 'new')
    if (transition === 'session') old.reject({ isAxiosError: true, response: { status: 403 } })
    else old.resolve()
    await setImmediate()
    assert.equal(store.commands[0].name, 'new')
    assert.equal(store.activeCall.call_id, 'new')
    assert.equal(store.callAvailable, true)
    assert.equal(store.selectedRoom.id, transition === 'room' ? 'other' : 'room')
  })
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
