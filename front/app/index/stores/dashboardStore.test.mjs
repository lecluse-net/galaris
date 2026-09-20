import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../../test-support/load-typescript.mjs'

function setup(t) {
  const auth = vue.reactive({ isAuthenticated: true, user: { id: 1 } })
  const authorize = vue.reactive({ activeRole: { id: 1 } })
  const access = vue.reactive({ privileges: ['TASK_ACCESS'] })
  const window = new EventTarget()
  let session = 'first'
  const requests = []
  const { useDashboardStore } = loadTypescript(new URL('./dashboardStore.ts', import.meta.url), {
    vue, pinia,
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'token', sessionGeneration: () => session },
    '@/core/user': { useAuthStore: () => auth },
    '@/core/authorize': { useAuthorizeStore: () => authorize, usePrivilegeStore: () => access,
      privileges: { TASK_ACCESS: 'TASK_ACCESS', TASK_EDIT: 'TASK_EDIT' } },
    '../services/dashboardService': { dashboardService: { getDashboard(month) {
      const response = deferred(); requests.push({ month, ...response }); return response.promise
    } } },
  }, { window })
  const store = useDashboardStore(pinia.createPinia())
  t.after(() => store.$dispose())
  return { store, auth, authorize, access, requests,
    switchSession() { session = 'second'; window.dispatchEvent(new Event('token')) } }
}
const payload = (month, tasks = 1) => ({ month, totals: { tasks }, available_months: [month], agents: [], daily_usage: [] })

async function finish(state, index, tasks = 1) {
  state.requests[index].resolve(payload(state.requests[index].month, tasks))
  await vue.nextTick()
}

test('dashboard consumers share requests and reuse a visited month; refresh reads fresh data', async t => {
  const s = setup(t)
  const first = s.store.selectMonth('2026-07')
  const second = s.store.selectMonth('2026-07')
  assert.equal(s.requests.length, 1)
  assert.equal(s.store.loading, true)
  await finish(s, 0)
  await Promise.all([first, second])
  const august = s.store.selectMonth('2026-08'); await finish(s, 1); await august
  await s.store.selectMonth('2026-07')
  assert.equal(s.requests.length, 2)
  assert.equal(s.store.data.month, '2026-07')
  const refresh = s.store.fetchDashboard(); await finish(s, 2, 9); await refresh
  assert.equal(s.store.data.totals.tasks, 9)
})

test('dashboard cache expires and evicts the least recently visited month', async t => {
  const s = setup(t)
  const now = Date.now()
  t.mock.method(Date, 'now', () => now)
  for (let month = 1; month <= 7; month++) {
    const request = s.store.selectMonth(`2026-0${month}`); await finish(s, month - 1); await request
  }
  await s.store.selectMonth('2026-02')
  assert.equal(s.requests.length, 7)
  const evicted = s.store.selectMonth('2026-01'); await finish(s, 7); await evicted
  t.mock.method(Date, 'now', () => now + 30_001)
  const expired = s.store.selectMonth('2026-01'); await finish(s, 8); await expired
  assert.equal(s.requests.length, 9)
})

test('late month responses and errors cannot overwrite the current selection, including A-B-A', async t => {
  const s = setup(t)
  const a = s.store.selectMonth('2026-07')
  const b = s.store.selectMonth('2026-08')
  const again = s.store.selectMonth('2026-07')
  assert.equal(s.requests.length, 2)
  await finish(s, 0); await Promise.all([a, again])
  s.requests[1].reject(new Error('old month')); await b
  assert.equal(s.store.data.month, '2026-07')
  assert.equal(s.store.error, null)
  assert.equal(s.store.loading, false)
  const c = s.store.selectMonth('2026-09')
  assert.equal(s.store.data, null, 'the previous month must not appear under the new selection')
  s.requests[2].reject(new Error('offline')); await c
  assert.equal(s.store.error.message, 'offline')
  const retry = s.store.selectMonth('2026-09'); await finish(s, 3); await retry
  assert.equal(s.store.error, null)
})

for (const change of ['session', 'role', 'privileges', 'logout', 'dispose']) {
  test(`dashboard invalidates cached and pending responses after ${change}`, async t => {
    const s = setup(t)
    const initial = s.store.selectMonth('2026-06'); await finish(s, 0); await initial
    const old = s.store.selectMonth('2026-07')
    if (change === 'session') s.switchSession()
    if (change === 'role') s.authorize.activeRole = { id: 2 }
    if (change === 'privileges') s.access.privileges = []
    if (change === 'logout') s.auth.isAuthenticated = false
    if (change === 'dispose') s.store.$dispose()
    assert.equal(s.store.data, null)
    await finish(s, 1, 999); await old
    assert.equal(s.store.data, null, 'old account data must not reappear')
    if (change === 'session' || change === 'role') {
      await finish(s, 2, 2)
      assert.equal(s.store.data.totals.tasks, 2)
      const revisit = s.store.selectMonth('2026-06'); await finish(s, 3, 3); await revisit
      assert.equal(s.store.data.totals.tasks, 3)
    } else {
      assert.equal(s.requests.length, 2)
    }
  })
}
