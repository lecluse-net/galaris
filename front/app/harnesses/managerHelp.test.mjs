import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('./components/HarnessManagerHelp.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const code = ts.transpileModule(compileScript(descriptor, { id: 'manager-help-test' }).content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function setup() {
  const requests = []
  const timers = new Map()
  let mounted, unmounted, nextTimer = 0
  const modules = {
    './HarnessManagerConfiguration.vue': { __esModule: true, default: {} },
    './HarnessManagerRelease.vue': { __esModule: true, default: {} },
    vue: { ...vue, onMounted: fn => { mounted = fn }, onUnmounted: fn => { unmounted = fn } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    '../services/managerService': { managerService: { diagnostics: () => new Promise((resolve, reject) => requests.push({ resolve, reject })) } },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', 'setTimeout', 'clearTimeout', code)(
    name => { assert.ok(name in modules, `Unexpected dependency ${name}`); return modules[name] },
    module, module.exports,
    (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id },
    id => { timers.delete(id) },
  )
  const state = module.exports.default.setup({}, { expose() {} })
  return { state, requests, timers, mount: () => mounted(), stop: () => unmounted() }
}

test('checks are bounded by completion and scheduled again after 30 seconds', async () => {
  const page = setup()
  const mounted = page.mount()
  assert.equal(page.requests.length, 1)
  await page.state.refresh()
  assert.equal(page.requests.length, 1)
  assert.equal(page.timers.size, 0)
  page.requests[0].resolve({ state: 'ok', secret_configured: true })
  await mounted
  assert.equal(page.state.diagnostics.value.state, 'ok')
  assert.equal([...page.timers.values()][0].delay, 30_000)
  page.stop()
  assert.equal(page.timers.size, 0)
})

test('a failed refresh removes stale healthy status', async () => {
  const page = setup()
  const mounted = page.mount()
  page.requests[0].resolve({ state: 'ok', secret_configured: true })
  await mounted
  const refresh = page.state.refresh()
  page.requests[1].reject(new Error('offline'))
  await refresh
  assert.equal(page.state.diagnostics.value, null)
  assert.equal(page.state.loadFailed.value, true)
  page.stop()
})

test('unmount ignores late responses and does not rearm polling', async () => {
  const page = setup()
  const mounted = page.mount()
  page.stop()
  page.requests[0].resolve({ state: 'ok' })
  await mounted
  assert.equal(page.state.diagnostics.value, null)
  assert.equal(page.timers.size, 0)
})
