import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { loadTypescript, deferred } from './test-support/load-typescript.mjs'

const late = deferred()
const storage = new Map([['access_token', 'account-a']])
const http = { interceptors: { request: { use() {} }, response: { use() {} } } }
const axios = { create: () => http, post: () => late.promise }
const output = ts.transpileModule(readFileSync('core/api.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const api = {}
new Function('require', 'exports', 'localStorage', 'window', 'CustomEvent', output)(
  () => ({ __esModule: true, default: axios }), api,
  { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
  { dispatchEvent() {} }, class {},
)
const refreshing = api.refreshAccessToken()
api.clearStoredSession()
api.saveAccessToken('account-b')
late.resolve({ data: { access_token: 'renewed-account-a' } })
await refreshing
assert.equal(api.getStoredAccessToken(), 'renewed-account-a')
console.log('CONFIRMED: late refresh from account A overwrites new account B token')

const pendingInbox = deferred()
const windowStub = new EventTarget()
Object.defineProperty(globalThis, 'window', { configurable: true, value: windowStub })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {} })
const { useChatInboxStore } = loadTypescript(new URL('./app/chat/stores/inbox.ts', `file://${process.cwd()}/`), {
  pinia, vue,
  '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => 'fake', registerBeforeLogoutHook: () => () => {} },
  '@/core/websocket': { websocket: { createWebsocket() {}, onEvent() {}, offEvent() {}, onConnect() {}, offConnect() {} } },
  '../services/chatService': { chatService: { inbox: () => pendingInbox.promise, pushConfiguration: async () => ({ available: false }) } },
})
const store = useChatInboxStore(pinia.createPinia())
const starting = store.start()
store.stop()
pendingInbox.resolve({ unread_count: 73 })
await starting
assert.equal(store.started, false)
assert.equal(store.unreadCount, 73)
console.log('CONFIRMED: late inbox response repopulates unread count after stop/logout')
store.$dispose()

const first = deferred()
const second = deferred()
const { useGoalStore } = loadTypescript(new URL('./app/goal/stores/goalStore.ts', `file://${process.cwd()}/`), {
  pinia, vue,
  '@/core/websocket': { websocket: {} },
  '@/core/user/stores/authStore': { useAuthStore: () => ({}) },
  '../services/goalService': { goalService: {
    get: id => id === 'first' ? first.promise : second.promise,
    listCycles: async id => ({ items: [{ id: `${id}-cycle` }], total: 1, page: 1, page_size: 50 }),
  } },
})
const goals = useGoalStore(pinia.createPinia())
const oldSelection = goals.fetchGoal('first')
const newSelection = goals.fetchGoal('second')
second.resolve({ id: 'second', revision: 1 })
await newSelection
assert.equal(goals.currentGoal.id, 'second')
first.resolve({ id: 'first', revision: 1 })
await oldSelection
assert.equal(goals.currentGoal.id, 'first')
assert.equal(goals.cycles[0].id, 'first-cycle')
console.log('CONFIRMED: late Goal detail response replaces more recent selection and cycles')
goals.$dispose()
