import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { setImmediate } from 'node:timers/promises'

function setup(t, permission, subscription = null, inbox = async () => ({ unread_count: 3 }), listeners = new Map(), room = async () => null) {
  const registered = []
  let queries = 0
  const notification = permission === undefined ? undefined : { permission }
  const worker = new EventTarget()
  worker.getRegistration = async () => undefined
  Object.defineProperty(worker, 'ready', { get() {
    assert.equal(permission, 'granted', 'No platform push access without permission')
    return Promise.resolve({ pushManager: { async getSubscription() { queries++; return subscription } } })
  } })
  const browserWindow = new EventTarget()
  browserWindow.setTimeout = (...args) => setTimeout(...args)
  browserWindow.clearTimeout = timer => clearTimeout(timer)
  browserWindow.PushManager = class {}
  if (notification) browserWindow.Notification = notification
  const storage = new Map()
  for (const [name, value] of Object.entries({ window: browserWindow, navigator: { serviceWorker: worker }, Notification: notification,
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } })) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name)
    Object.defineProperty(globalThis, name, { configurable: true, value })
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original)
      else delete globalThis[name]
    })
  }
  const { useChatInboxStore } = loadTypescript(new URL('./stores/inbox.ts', import.meta.url), {
    pinia, vue,
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => 'test', registerBeforeLogoutHook: () => () => {}, sessionGeneration: () => 'session' },
    '@/core/websocket': { websocket: { createWebsocket() {},
      onEvent(subject, action, callback) { listeners.set(`${subject}.${action}`, callback) },
      offEvent() {}, onConnect(callback) { listeners.set('connect', callback) }, offConnect() {} } },
    '../services/chatService': { chatService: {
      inbox,
      room,
      pushConfiguration: async () => ({ available: true, public_key: 'test' }),
      registerPushSubscription: async payload => registered.push(payload),
    } },
  })
  const store = useChatInboxStore(pinia.createPinia())
  return { store, registered, listeners, queries: () => queries }
}

for (const permission of [undefined, 'default', 'denied']) {
  test(`in-app inbox starts without platform push access when permission is ${permission}`, async t => {
    const { store, queries } = setup(t, permission)
    await store.start()
    assert.equal(store.started, true)
    assert.equal(store.unreadCount, 3)
    assert.equal(store.subscribed, false)
    assert.equal(store.canPrompt, permission === 'default')
    await store.disablePush()
    assert.equal(queries(), 0)
    store.stop()
    store.$dispose()
  })
}

test('an authorized existing subscription is restored and registered', async t => {
  const payload = { endpoint: 'https://push.example.test/subscription', keys: { p256dh: 'key', auth: 'auth' }, expirationTime: null }
  const { store, queries, registered } = setup(t, 'granted', { toJSON: () => payload })
  await store.start()
  assert.equal(queries(), 1)
  assert.equal(store.subscribed, true)
  assert.deepEqual(registered, [{ endpoint: payload.endpoint, expiration_time: null, keys: payload.keys }])
  store.stop()
  store.$dispose()
})

test('granted permission without a subscription keeps the inbox operational', async t => {
  const { store, queries, registered } = setup(t, 'granted')
  await store.start()
  assert.equal(queries(), 1)
  assert.equal(store.subscribed, false)
  assert.equal(store.started, true)
  assert.deepEqual(registered, [])
  store.stop()
  store.$dispose()
})

test('stopping the inbox invalidates a pending unread response', async t => {
  let finish
  const { store } = setup(t, undefined, null, () => new Promise(resolve => { finish = resolve }))
  const starting = store.start()
  store.stop()
  finish({ unread_count: 73 })
  await starting
  assert.equal(store.started, false)
  assert.equal(store.unreadCount, 0)
  store.$dispose()
})

test('inbox signal bursts bound background requests and preserve the latest unread count', async t => {
  const first = deferred(), listeners = new Map()
  let requests = 0, unread = 3, slow = false
  const { store } = setup(t, undefined, null, async () => {
    const captured = unread
    if (slow && ++requests === 1) await first.promise
    return { unread_count: captured }
  }, listeners)
  await store.start()
  slow = true
  listeners.get('chat.message')({ data: {} })
  unread = 9
  for (let index = 0; index < 30; index++) listeners.get('chat.message')({ data: {} })
  first.resolve()
  await setImmediate()
  assert.equal(requests, 2)
  assert.equal(store.unreadCount, 9)
  store.stop()
  store.$dispose()
})

test('reconnection refreshes the inbox without waiting on an obsolete HTTP request', async t => {
  const first = deferred(), listeners = new Map()
  let requests = 0
  const { store } = setup(t, undefined, null, async () => {
    if (++requests === 1) return { unread_count: 0 }
    if (requests === 2) return first.promise
    return { unread_count: 9 }
  }, listeners)
  await store.start()
  listeners.get('chat.message')({ data: {} })
  listeners.get('connect')()
  await setImmediate()
  assert.equal(store.unreadCount, 9)
  first.resolve({ unread_count: 73 })
  await setImmediate()
  assert.equal(store.unreadCount, 9)
  store.stop()
  store.$dispose()
})

for (const stage of ['arrival', 'timer', 'request', 'unseen']) test(`notification fallback respects a conversation viewed at ${stage}`, async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pendingRoom = deferred()
  let requests = 0
  const room = { id: 'room-a', label: 'Synthetic room', unread_count: 1, muted: false, show_last_message: true,
    last_message: { id: 'message-a', text: 'Synthetic message', is_mine: false } }
  const { store, listeners } = setup(t, undefined, null, undefined, undefined, async () => {
    requests++
    return stage === 'request' ? pendingRoom.promise : room
  })
  await store.start()
  if (stage === 'arrival') store.setDisplayedRoom('room-a')
  listeners.get('chat.message')({ data: { room_id: 'room-a', message_id: 'message-a', is_new: true } })
  if (stage === 'timer') store.setDisplayedRoom('room-a')
  if (stage !== 'request') store.setDisplayedRoom(null)
  t.mock.timers.tick(3200)
  await setImmediate()
  if (stage === 'request') {
    assert.equal(requests, 1)
    store.setDisplayedRoom('room-a')
    store.setDisplayedRoom(null)
    pendingRoom.resolve(room)
    await setImmediate()
  }
  assert.equal(store.inAppNotification?.messageId ?? null, stage === 'unseen' ? 'message-a' : null)
  if (stage === 'arrival' || stage === 'timer') assert.equal(requests, 0)
  store.stop()
  store.$dispose()
})

test('displaying a conversation closes only its existing system notifications', async t => {
  const { store } = setup(t, undefined)
  const closed = []
  navigator.serviceWorker.getRegistration = async () => ({ getNotifications: async () => ['room-a', 'room-b'].map(roomId => ({
    data: { roomId }, close() { closed.push(roomId) },
  })) })
  store.setDisplayedRoom('room-a')
  await setImmediate()
  assert.deepEqual(closed, ['room-a'])
  store.$dispose()
})
