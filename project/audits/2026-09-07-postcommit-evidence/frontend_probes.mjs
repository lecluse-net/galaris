import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { loadTypescript, deferred } from './test-support/load-typescript.mjs'

const refresh = deferred()
const { useProcessStore } = loadTypescript(new URL('./app/process/stores/processStore.ts', `file://${process.cwd()}/`), {
  pinia,
  '../services/processService': { processService: {
    refreshRun: () => refresh.promise,
    run: async id => ({ id }),
    runs: async () => ({ items: [], total: 0, page: 1, page_size: 50 }),
  } },
})
const store = useProcessStore(pinia.createPinia())
await store.openRun('A')
const operation = store.refreshRun('A')
await store.openRun('B')
assert.equal(store.currentRun.id, 'B')
refresh.resolve({})
await operation
assert.equal(store.currentRun.id, 'A')
console.log('CONFIRMED: finishing refresh A replaces the later selection B')
store.$dispose()

globalThis.window = new EventTarget()
const events = new EventEmitter()
const emitted = []
const socket = {
  connected: false, active: false,
  on: (...args) => events.on(...args), once: (...args) => events.once(...args),
  off: (...args) => events.off(...args),
  emit: (...args) => emitted.push(args), connect() { return this }, disconnect() { return this },
}
const { websocket, BaseRoom } = loadTypescript(new URL('./core/websocket.ts', `file://${process.cwd()}/`), {
  vue, 'socket.io-client': { io: () => socket }, 'jwt-decode': { jwtDecode: () => ({}) },
  './api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => null, api: {} },
})
class Room extends BaseRoom { className = 'TestRoom' }
websocket.createWebsocket()
websocket.joinRoom(new Room('old'))
websocket.leaveRoom(new Room('old'))
socket.connected = true
events.emit('connect')
assert(emitted.some(([event, data]) => event === 'room.join' && data.room === 'TestRoom:old'))
console.log('CONFIRMED: leaving an offline room does not cancel its delayed join')
