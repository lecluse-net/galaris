import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'
import { deferred } from '../../../test-support/load-typescript.mjs'

function setup(t) {
  const { descriptor } = parse(readFileSync(new URL('./LlmCalls.vue', import.meta.url), 'utf8'))
  const code = ts.transpileModule(compileScript(descriptor, { id: 'calls-races' }).content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  let cleanup
  let session = 'A'
  const requests = new Map(), notices = []
  const dependencies = {
    vue: { ...vue, onBeforeUnmount(fn) { cleanup = fn } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    quasar: { useQuasar: () => ({ notify: notice => notices.push(notice) }) },
    '@/core/api': { sessionGeneration: () => session },
    '@/core/util': { showConfirmationDialog: () => assert.fail('No confirmation is expected while loading calls') },
    '@/core/authorize': { usePrivilegeStore: () => ({ hasPrivilege: () => true }), privileges: {} },
    '@/core/websocket': { websocket: { createWebsocket() {}, onEvent() {}, offEvent() {} } },
    './LlmCallTaskDetail.vue': {},
    '../services/llmCallService': { llmCallService: { getByTask(id) { const r = deferred(); requests.set(id, r); return r.promise } } },
  }
  const exports = {}
  new Function('require', 'exports', code)(name => {
    assert.ok(name in dependencies, name)
    return dependencies[name]
  }, exports)
  const scope = vue.effectScope()
  const props = vue.reactive({ taskId: 'first', externalCalls: [], loading: false, error: '' })
  const state = scope.run(() => exports.default.setup(props, { expose() {} }))
  t.after(() => { cleanup(); scope.stop() })
  return { state, props, requests, notices, close: () => cleanup(), switchSession: () => { session = 'B' } }
}

test('LLM calls reject old success/error after selection, session change and closure', async t => {
  const c = setup(t)
  c.props.taskId = 'second'; await vue.nextTick()
  c.requests.get('second').resolve([{ id: 'second' }]); await vue.nextTick(); await vue.nextTick()
  c.requests.get('first').reject(new Error('old')); await vue.nextTick(); await vue.nextTick()
  assert.equal(c.state.calls.value[0].id, 'second')
  assert.equal(c.state.internalLoading.value, false)
  assert.deepEqual(c.notices, [])
  c.props.taskId = 'third'; await vue.nextTick()
  c.switchSession()
  c.requests.get('third').resolve([{ id: 'wrong-account' }]); await vue.nextTick(); await vue.nextTick()
  assert.deepEqual([...c.state.calls.value], [])
  c.props.taskId = 'fourth'; await vue.nextTick()
  c.close()
  c.requests.get('fourth').reject(new Error('closed')); await vue.nextTick(); await vue.nextTick()
  assert.deepEqual(c.notices, [])
})
