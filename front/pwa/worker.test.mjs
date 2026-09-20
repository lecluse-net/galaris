import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../test-support/load-typescript.mjs'

function worker(t, { manifest = [], clients = [], pathname = '/dev-sw.js', cacheEnabled = false, cacheKeys = [] } = {}) {
  const handlers = {}, routes = [], notifications = [], badges = [], opened = [], precaches = [], deletedCaches = []
  const self = {
    __WB_MANIFEST: manifest, location: { origin: 'https://galaris.example.test', pathname }, setTimeout, clearTimeout,
    addEventListener: (name, handler) => { handlers[name] = handler }, skipWaiting() {},
    clients: { matchAll: async () => clients, claim: async () => {}, openWindow: async url => opened.push(url) },
    registration: { scope: 'https://galaris.example.test/', showNotification: async (...args) => notifications.push(args), setAppBadge: async count => badges.push(count), clearAppBadge: async () => badges.push(0) },
    caches: { keys: async () => cacheKeys, delete: async name => { deletedCaches.push(name); return true } },
  }
  loadTypescript(new URL('./sw.ts', import.meta.url), {
    './cachePolicy': { pwaCacheEnabled: cacheEnabled },
    'workbox-core': { cacheNames: { prefix: 'workbox' } },
    'workbox-precaching': { precacheAndRoute: entries => precaches.push(entries), cleanupOutdatedCaches() {}, createHandlerBoundToURL(url) { assert.ok(manifest.some(entry => entry.url.replace(/^\//, '') === url)); return url } },
    'workbox-routing': { NavigationRoute: class { constructor(handler, options) { this.handler = handler; this.options = options } }, registerRoute: route => routes.push(route) },
  }, { self })
  return { routes, precaches, deletedCaches, notifications, badges, opened, async emit(name, event) { let pending; handlers[name]({ ...event, waitUntil: value => { pending = value } }); await pending } }
}

test('development never installs cache routes, even with a manifest, while production caches its shell', t => {
  const manifest = [{ url: 'index.html', revision: 'example' }]
  for (const entries of [[], manifest]) {
    const development = worker(t, { manifest: entries })
    assert.deepEqual(development.routes, [])
    assert.deepEqual(development.precaches, [])
  }
  const production = worker(t, { manifest, cacheEnabled: true })
  assert.deepEqual(production.precaches, [manifest])
  assert.equal(production.routes[0].handler, 'index.html')
  for (const path of ['/api/chat', '/socket.io/', '/ws/chat', '/openapi.json']) assert.ok(production.routes[0].options.denylist.some(pattern => pattern.test(path)))
})

test('development deletes only PWA caches for its scope and production preserves them', async t => {
  const own = ['workbox-precache-v2-https://galaris.example.test/', 'workbox-runtime-https://galaris.example.test/']
  const cacheKeys = [...own, 'user-content', 'workbox-precache-v2-https://galaris.example.test/another-app/']
  for (const cacheEnabled of [false, true]) {
    const runtime = worker(t, { cacheEnabled, cacheKeys })
    await runtime.emit('activate', {})
    assert.deepEqual(runtime.deletedCaches, cacheEnabled ? [] : own)
  }
})

test('push without an open client displays the notification and updates the badge', async t => {
  const runtime = worker(t)
  await runtime.emit('push', { data: { json: () => ({ title: 'Alice', body: 'New message', unreadCount: 4, data: { roomId: 'room-a' } }) } })
  assert.equal(runtime.notifications[0][0], 'Alice')
  assert.equal(runtime.notifications[0][1].body, 'New message')
  assert.equal(runtime.notifications[0][1].data.url, '/chat')
  assert.deepEqual(runtime.badges, [4])
})

test('only the legacy development worker reopens clients, tolerating a closed tab', async t => {
  for (const [pathname, manifest, reload] of [
    ['/sw.js', [], true],
    ['/dev-sw.js', [], false],
    ['/sw.js', [{ url: 'index.html', revision: 'production' }], false],
  ]) {
    const navigations = []
    const runtime = worker(t, { pathname, manifest, cacheEnabled: manifest.length > 0, clients: [
      { url: 'https://galaris.example.test/chat?room=existing', navigate: async url => navigations.push(url) },
      { url: 'https://galaris.example.test/closed', navigate: async () => { throw new Error('Tab closed') } },
    ] })
    await runtime.emit('activate', {})
    assert.deepEqual(navigations, reload ? ['https://galaris.example.test/chat?room=existing'] : [])
  }
})

test('only a visible client displaying the same room suppresses push', async t => {
  for (const [visible, displayed, suppressed] of [[true, 'room-a', true], [true, 'room-b', false], [false, 'room-a', false]]) {
    const runtime = worker(t, { clients: [{ visibilityState: visible ? 'visible' : 'hidden', postMessage(_query, [port]) { port.postMessage({ type: 'galaris:chat-displayed-room-response', roomId: displayed }); port.close() } }] })
    await runtime.emit('push', { data: { json: () => ({ data: { roomId: 'room-a' }, unreadCount: 0 }) } })
    assert.equal(runtime.notifications.length, suppressed ? 0 : 1)
    assert.deepEqual(runtime.badges, [0])
  }
})

test('notification click focuses an existing client or opens the target conversation', async t => {
  const calls = []
  const existing = worker(t, { clients: [{ url: 'https://galaris.example.test/task', navigate: async url => calls.push(['navigate', url]), focus: async () => calls.push(['focus']) }] })
  const event = { notification: { data: { url: '/chat?room=room-a' }, close: () => calls.push(['close']) } }
  await existing.emit('notificationclick', event)
  assert.deepEqual(calls, [['close'], ['navigate', 'https://galaris.example.test/chat?room=room-a'], ['focus']])
  const absent = worker(t)
  await absent.emit('notificationclick', event)
  assert.deepEqual(absent.opened, ['https://galaris.example.test/chat?room=room-a'])
})
