import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as aiResult from './aiResult.ts'
import * as activity from './activity.ts'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

function setup(getActivity) {
  const tasks = vue.ref([{ id: 'task', revision: 1, status: 'EXEC',
    data: { _agent_run_identity: { request_run_id: 'run' } } }])
  const events = new Map(), timers = new Map()
  let cleanup, timerId = 0
  const scope = vue.effectScope()
  const { useTaskActivity } = loadTypescript(new URL('./useTaskActivity.ts', import.meta.url), {
    vue: { ...vue, onBeforeUnmount: callback => { cleanup = callback } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    '@/core/authorize': { privileges: { LLM_CALL_ACCESS: 'LLM_CALL_ACCESS', LLM_CALL_CONTROL: 'LLM_CALL_CONTROL' },
      usePrivilegeStore: () => ({ hasAnyPrivilege: () => true }) },
    '@/core/websocket': { BaseRoom: class {}, websocket: {
      createWebsocket() {}, joinRoom() {}, leaveRoom() {},
      onEvent: (subject, action, callback) => events.set(`${subject}.${action}`, callback),
      offEvent() {}, onConnect() {}, offConnect() {},
    } },
    '@/app/llm': { llmCallService: { getByRuns: async () => [] } }, './services/taskService': { taskService: { getActivity } },
    './aiResult': aiResult, './activity': activity,
  }, {
    setTimeout: callback => { timers.set(++timerId, callback); return timerId },
    clearTimeout: id => timers.delete(id), setInterval: () => 1, clearInterval() {},
  })
  const state = scope.run(() => useTaskActivity(() => tasks.value))
  return { ...state, tasks, events, timers,
    tick() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()) },
    close() { cleanup(); scope.stop() },
  }
}

const snapshot = id => ({ task_id: id, revision: 1, run_id: 'run', streams_ai_messages: true,
  latest_attempt: null, live: null, last_activity_at: null })

test('slow activity reads coalesce refreshes and still display live messages immediately', async () => {
  const pending = deferred()
  let calls = 0
  const state = setup(() => { calls++; return calls === 1 ? pending.promise : Promise.resolve([snapshot('task')]) })
  try {
    const first = state.refresh()
    for (let i = 0; i < 30; i++) await state.refresh()
    assert.equal(calls, 1, 'one read at a time even when updates outpace the server')
    state.events.get('agent_run.event')({ data: { task_id: 'task', run_id: 'run',
      sequence: 1, kind: 'message', message: { type: 'text', stream_id: 'text', stream_complete: true, content: 'Live progress' } } })
    assert.equal(state.resultFor(state.tasks.value[0]).messages[0].content, 'Live progress')
    pending.resolve([snapshot('task')])
    await first
    state.tick()
    await vue.nextTick()
    assert.equal(calls, 2, 'all pending updates produce one follow-up read')
    assert.equal(state.resultFor(state.tasks.value[0]).messages[0].content, 'Live progress')
  } finally { state.close() }
})

test('switching tasks rejects late activity and an empty selection makes no HTTP request', async () => {
  const pending = deferred()
  const requests = []
  const state = setup(ids => { requests.push(ids); return requests.length === 1 ? pending.promise : Promise.resolve([snapshot('new')]) })
  try {
    const first = state.refresh()
    state.tasks.value = [{ ...state.tasks.value[0], id: 'new' }]
    await vue.nextTick()
    pending.resolve([snapshot('task')])
    await first
    assert.equal(state.snapshots.value.task, undefined)
    state.tick()
    await vue.nextTick()
    assert.deepEqual(requests, [['task'], ['new']])
    assert.equal(state.snapshots.value.new.task_id, 'new')
    state.tasks.value = []
    await vue.nextTick()
    state.tick()
    await state.refresh()
    assert.deepEqual(state.snapshots.value, {})
    assert.equal(requests.length, 2)
  } finally { state.close() }
})

test('text-only fallback progress keeps activity fresh without reloading call histories', async () => {
  const state = setup(async () => [{ ...snapshot('task'), streams_ai_messages: false }])
  try {
    await state.refresh()
    const progress = state.events.get('llm_call.progress')
    const at = '2026-01-01T12:00:00Z'
    for (let index = 0; index < 1000; index++) {
      progress({ data: { id: 'call', task_id: 'task', agent_run_id: 'run', updated_at: at } })
    }
    assert.equal(state.snapshots.value.task.last_activity_at, at)
    assert.equal(state.timers.size, 0)
    progress({ data: { task_id: 'task', agent_run_id: 'run', updated_at: at, tool_calls: [] } })
    assert.equal(state.timers.size, 1)
  } finally { state.close() }
})
