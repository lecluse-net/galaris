import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

const { descriptor } = parse(readFileSync(new URL('./components/HarnessEditor.vue', import.meta.url), 'utf8'))
const code = ts.transpileModule(compileScript(descriptor, { id: 'navigation-test' }).content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function setup(initial = 'first') {
  const route = vue.reactive({ params: { id: initial } })
  const requests = []
  const notifications = []
  const redirects = []
  let beforeUnmount
  function request(id) {
    return new Promise((resolve, reject) => requests.push({ id, resolve, reject }))
  }
  const modules = {
    vue: { ...vue, onBeforeUnmount: fn => { beforeUnmount = fn } },
    quasar: { useQuasar: () => ({ notify: value => notifications.push(value) }) },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    'vue-router': { useRoute: () => route, useRouter: () => ({ replace: async path => redirects.push(path) }) },
    '@/core/authorize': { privileges: {}, usePrivilegeStore: () => ({ hasPrivilege: () => true }) },
    '@/core/util': {}, '@/core/params': {},
    '../branding': { harnessBrand: () => ({ icon: 'test' }) },
    '../services/harnessService': { harnessService: {
      catalogEntry: request, catalog: () => request('catalog'),
      updateCatalogEntry: (id, payload) => request({ id, payload }),
    } },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    assert.ok(name in modules, `Unexpected dependency ${name}`)
    return modules[name]
  }, module, module.exports)
  const scope = vue.effectScope()
  const state = scope.run(() => module.exports.default.setup({}, { expose() {}, emit() {} }))
  return {
    state, requests, notifications, redirects,
    async go(id) { route.params.id = id; await vue.nextTick() },
    stop() { beforeUnmount(); scope.stop() },
  }
}

function entry(id) {
  return { id, name: id, provider_code: id, enabled: true, base_url: '', model: null, settings: {}, token_configured: false }
}
async function resolve(request, data) {
  request.resolve({ data })
  await vue.nextTick()
}

test('switching external harness entries reloads the reused editor', async t => {
  const page = setup()
  t.after(page.stop)
  await resolve(page.requests[0], entry('first'))
  await page.go('second')
  assert.equal(page.requests[1].id, 'second')
  assert.equal(page.state.entry.value, null)
  await resolve(page.requests[1], entry('second'))
  assert.equal(page.state.form.name, 'second')
})

test('rapid navigation ignores the previous response and keeps the current spinner', async t => {
  const page = setup()
  t.after(page.stop)
  await page.go('second')
  await resolve(page.requests[0], entry('first'))
  assert.equal(page.state.entry.value, null)
  assert.equal(page.state.loading.value, true)
  await resolve(page.requests[1], entry('second'))
  assert.equal(page.state.form.name, 'second')
})

test('late errors from the previous harness never redirect the current page', async t => {
  const page = setup()
  t.after(page.stop)
  await page.go('second')
  await resolve(page.requests[1], entry('second'))
  page.requests[0].reject(new Error('old request'))
  await vue.nextTick()
  assert.equal(page.state.form.name, 'second')
  assert.deepEqual(page.redirects, [])
  assert.deepEqual(page.notifications, [])
})

test('new harness clears previous fields, tokens and dialogs', async t => {
  const page = setup()
  t.after(page.stop)
  await resolve(page.requests[0], entry('first'))
  page.state.form.token = 'unsaved-secret'
  page.state.showToken.value = true
  page.state.deleteDialog.value = true
  await page.go('new')
  assert.equal(page.requests.length, 1)
  assert.equal(page.state.form.token, '')
  assert.equal(page.state.showToken.value, false)
  assert.equal(page.state.deleteDialog.value, false)
  assert.equal(page.state.entry.value, null)
  assert.equal(page.state.form.name, 'harnesses.catalog.defaultApiName')
})

test('built-in harness aliases follow route changes too', async t => {
  const page = setup('bridge-hermes')
  t.after(page.stop)
  await page.go('bridge-codex')
  await resolve(page.requests[1], [entry('hermes'), entry('codex')])
  await resolve(page.requests[0], [entry('hermes'), entry('codex')])
  assert.equal(page.state.form.name, 'codex')
})

test('leaving the page invalidates outstanding requests', async () => {
  const page = setup()
  page.stop()
  page.requests[0].reject(new Error('old page'))
  await vue.nextTick()
  assert.deepEqual(page.redirects, [])
  assert.deepEqual(page.notifications, [])
})

test('built-in harnesses persist only through the activation command', async t => {
  const page = setup('hermes')
  t.after(page.stop)
  await resolve(page.requests[0], { ...entry('hermes'), enabled: false })
  await page.state.save()
  assert.equal(page.requests.length, 1)
  page.state.requestEnabledChange(true)
  assert.equal(page.requests.length, 2)
  assert.equal(page.requests[1].id.id, 'hermes')
  assert.equal(page.requests[1].id.payload.enabled, true)
  await resolve(page.requests[1], entry('hermes'))
  assert.equal(page.state.form.enabled, true)
})

test('disabling still requires confirmation before its automatic save', async t => {
  const page = setup('hermes')
  t.after(page.stop)
  await resolve(page.requests[0], entry('hermes'))
  page.state.requestEnabledChange(false)
  assert.equal(page.state.disableDialog.value, true)
  assert.equal(page.requests.length, 1)
  const confirmed = page.state.confirmDisable()
  assert.equal(page.requests[1].id.payload.enabled, false)
  await resolve(page.requests[1], { ...entry('hermes'), enabled: false })
  await confirmed
  assert.equal(page.state.form.enabled, false)
})

test('failed toggle persistence preserves the previous activation state', async t => {
  const page = setup('hermes')
  t.after(page.stop)
  await resolve(page.requests[0], { ...entry('hermes'), enabled: false })
  const updating = page.state.persistEnabled(true)
  page.requests[1].reject(new Error('unavailable'))
  await updating
  assert.equal(page.state.form.enabled, false)
  assert.equal(page.state.activationBusy.value, false)
  assert.equal(page.notifications[0].type, 'negative')
})
