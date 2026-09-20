import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { jwtDecode } from 'jwt-decode'

const output = ts.transpileModule(readFileSync(new URL('./websocket.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function setup(initialToken = 'token', recover = async () => {}) {
  let token = initialToken
  const listeners = new Map()
  const socketListeners = new Map()
  let authenticate = () => {}
  let authPayload
  const socket = {
    active: false,
    connected: false,
    connections: 0,
    emissions: [],
    connect() { this.active = true; this.connections++; authenticate(data => { authPayload = data }); return this },
    disconnect() { this.active = false; this.connected = false; return this },
    on(name, listener) {
      if (!socketListeners.has(name)) socketListeners.set(name, new Set())
      socketListeners.get(name).add(listener)
      return this
    },
    off(name, listener) {
      if (listener) socketListeners.get(name)?.delete(listener)
      else socketListeners.delete(name)
      return this
    },
    emit(...args) { this.emissions.push(args); return this },
  }
  const modules = {
    vue: { ref: value => ({ value }) },
    'socket.io-client': { io: options => { authenticate = options.auth; return socket } },
    'jwt-decode': { jwtDecode },
    './api': { api: { get: recover }, AUTH_TOKEN_CHANGED_EVENT: 'token-changed', getStoredAccessToken: () => token },
  }
  const loaded = { exports: {} }
  new Function('require', 'module', 'exports', 'window', output)(
    name => {
      assert.ok(name in modules, `Unexpected dependency: ${name}`)
      return modules[name]
    }, loaded, loaded.exports,
    { addEventListener: (name, listener) => listeners.set(name, listener) },
  )
  return {
    websocket: loaded.exports.websocket,
    socket,
    get authPayload() { return authPayload },
    receive(name, payload) { socketListeners.get(name)?.forEach(listener => listener(payload)) },
    serverDisconnect(reason = 'io server disconnect') {
      socket.active = false
      socket.connected = false
      socketListeners.get('disconnect').forEach(listener => listener(reason))
    },
    finishHandshake() {
      socket.connected = true
      socketListeners.get('connect').forEach(listener => listener())
    },
    changeToken(value) {
      token = value
      listeners.get('token-changed')({ detail: value })
    },
  }
}

test('concurrent consumers and token refresh do not restart a pending handshake', () => {
  const { websocket, socket, changeToken } = setup()
  assert.equal(websocket.createWebsocket(), socket)
  assert.equal(socket.connected, false)
  assert.equal(socket.active, true)
  assert.equal(websocket.createWebsocket(), socket)
  changeToken('refreshed-token')
  websocket.createWebsocket()
  assert.equal(socket.connections, 1)
})

test('automatic reconnection is not restarted by consumers or token refresh', () => {
  const { websocket, socket, changeToken } = setup()
  websocket.createWebsocket()
  socket.connected = true
  websocket.createWebsocket()
  // Socket.IO keeps active=true while its Manager reconnects after network loss.
  socket.connected = false
  changeToken('refreshed-token')
  websocket.createWebsocket()
  assert.equal(socket.connections, 1)
})

test('login starts an idle socket and logout allows a subsequent login', () => {
  const { websocket, socket, changeToken } = setup(null)
  websocket.createWebsocket()
  assert.equal(socket.connections, 0)
  changeToken('login-token')
  assert.equal(socket.connections, 1)
  changeToken(null)
  assert.equal(socket.active, false)
  websocket.createWebsocket()
  assert.equal(socket.connections, 1)
  changeToken('next-login-token')
  assert.equal(socket.connections, 2)
})

test('an inactive socket can be explicitly reconnected by a consumer', () => {
  const { websocket, socket } = setup()
  websocket.createWebsocket()
  socket.disconnect()
  websocket.createWebsocket()
  assert.equal(socket.connections, 2)
})

function tokenFor(role, expiry = 1) {
  return `header.${Buffer.from(JSON.stringify({ sub: 'user', role_id: role, exp: expiry })).toString('base64url')}.signature`
}

test('refreshing the same identity preserves the connection; changing roles reauthenticates', () => {
  const { websocket, socket, changeToken, finishHandshake } = setup(tokenFor(1))
  websocket.createWebsocket()
  finishHandshake()
  changeToken(tokenFor(1, 2))
  assert.equal(socket.connections, 1)
  changeToken(tokenFor(2, 3))
  assert.equal(socket.connections, 2)
  finishHandshake()
  assert.equal(socket.connections, 2)
})

test('a role change during a handshake reauthenticates after that handshake finishes', () => {
  const { websocket, socket, changeToken, finishHandshake } = setup(tokenFor(1))
  websocket.createWebsocket()
  changeToken(tokenFor(2))
  assert.equal(socket.connections, 1)
  finishHandshake()
  assert.equal(socket.connections, 2)
  finishHandshake()
  assert.equal(socket.connections, 2)
})

test('server expiry refreshes authentication before reconnecting an idle socket', async () => {
  let checks = 0
  const { websocket, socket, serverDisconnect } = setup('token', async path => {
    assert.equal(path, '/auth/me')
    checks++
  })
  websocket.createWebsocket()
  serverDisconnect()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(checks, 1)
  assert.equal(socket.connections, 2)
})

test('revoked sessions do not enter a reconnection loop', async () => {
  const { websocket, socket, serverDisconnect } = setup('token', async () => {
    throw new Error('session revoked')
  })
  websocket.createWebsocket()
  serverDisconnect()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(socket.connections, 1)
  assert.equal(socket.active, false)
})

test('network disconnections leave retries to the Socket.IO manager', async () => {
  let checks = 0
  const { websocket, serverDisconnect } = setup('token', async () => { checks++ })
  websocket.createWebsocket()
  serverDisconnect('transport close')
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(checks, 0)
})

test('offline room intentions reconcile once and are discarded on leave and logout', () => {
  const { websocket, socket, finishHandshake, changeToken, serverDisconnect } = setup()
  websocket.createWebsocket()
  websocket.joinRoom('old')
  websocket.leaveRoom('old')
  websocket.joinRoom('current')
  websocket.joinRoom('current')
  finishHandshake()
  assert.deepEqual(socket.emissions.filter(item => item[0] === 'room.join'), [['room.join', { room: 'current' }]])
  serverDisconnect('transport close')
  finishHandshake()
  assert.equal(socket.emissions.filter(item => item[0] === 'room.join').length, 2)
  changeToken(null)
  changeToken('new-token')
  finishHandshake()
  assert.equal(socket.emissions.filter(item => item[0] === 'room.join').length, 2)
})

test('the displayed page is restored on reconnect and cleared on leave or logout', () => {
  const { websocket, socket, finishHandshake, changeToken, serverDisconnect } = setup()
  const displayed = () => socket.emissions.filter(item => item[0] === 'room.display').at(-1)
  websocket.createWebsocket()
  websocket.setDisplayedRoom('DreamRoom:monitoring')
  finishHandshake()
  assert.deepEqual(displayed(), ['room.display', { room: 'DreamRoom:monitoring' }])
  serverDisconnect('transport close')
  finishHandshake()
  assert.deepEqual(displayed(), ['room.display', { room: 'DreamRoom:monitoring' }])
  websocket.setDisplayedRoom(null)
  assert.deepEqual(displayed(), ['room.display', { room: null }])
  serverDisconnect('transport close')
  websocket.setDisplayedRoom('DreamRoom:monitoring')
  websocket.setDisplayedRoom(null)
  finishHandshake()
  assert.deepEqual(displayed(), ['room.display', { room: null }])
  websocket.setDisplayedRoom('DreamRoom:monitoring')
  changeToken(null)
  changeToken('new-token')
  finishHandshake()
  assert.deepEqual(displayed(), ['room.display', { room: null }])
})

test('only events with active consumers are requested, preserving shared and global listeners', () => {
  const fixture = setup()
  const { websocket, socket, finishHandshake, receive } = fixture
  websocket.createWebsocket()
  finishHandshake()
  const subscriptions = () => socket.emissions.filter(item => item[0] === 'events.subscribe').at(-1)?.[1].events
  let calls = 0
  const pageA = () => { calls++ }
  const pageB = () => { calls++ }
  const inbox = () => { calls++ }
  websocket.onEvent('chat', 'message', inbox)
  websocket.onEvent('llm_call', 'update', pageA)
  websocket.onEvent('llm_call', 'update', pageB)
  assert.deepEqual(subscriptions(), ['chat.message', 'llm_call.update'])
  receive('llm_call.update', { data: {} })
  assert.equal(calls, 2)
  const count = socket.emissions.length
  websocket.offEvent('llm_call', 'update', pageA)
  assert.equal(socket.emissions.length, count)
  receive('llm_call.update', { data: {} })
  assert.equal(calls, 3)
  websocket.offEvent('llm_call', 'update', pageB)
  assert.deepEqual(subscriptions(), ['chat.message'])
  websocket.onEvent('llm_call', 'update', pageA)
  assert.deepEqual(subscriptions(), ['chat.message', 'llm_call.update'])
  websocket.offEvent('llm_call', 'update')
  assert.deepEqual(subscriptions(), ['chat.message'])
})

test('reconnection authenticates with current subscriptions after offline navigation', () => {
  const fixture = setup()
  const { websocket, socket, finishHandshake, changeToken, serverDisconnect } = fixture
  websocket.createWebsocket()
  const listener = () => {}
  websocket.onEvent('task', 'update', listener)
  finishHandshake()
  serverDisconnect('transport close')
  websocket.offEvent('task', 'update', listener)
  websocket.onEvent('memory', 'update', listener)
  socket.connect()
  assert.deepEqual(fixture.authPayload.events, ['memory.update'])
  finishHandshake()
  assert.deepEqual(socket.emissions.at(-2), ['events.subscribe', { events: ['memory.update'] }])
  changeToken(null)
  websocket.offEvent('memory', 'update', listener)
  changeToken('another-user-token')
  assert.deepEqual(fixture.authPayload.events, [])
})
