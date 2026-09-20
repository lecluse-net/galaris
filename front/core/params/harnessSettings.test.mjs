import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

function evaluate(source, modules) {
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    assert.ok(name in modules, `Unexpected dependency: ${name}`)
    return modules[name]
  }, module, module.exports)
  return module.exports.default
}

function hermesSettings() {
  return evaluate(readFileSync(new URL('../../bridge/hermes/settings.ts', import.meta.url), 'utf8'), {
    './components/HermesConfigurationHint.vue': {},
  })
}

const componentSource = readFileSync(new URL('./components/HarnessProviderSettings.vue', import.meta.url), 'utf8')
const { descriptor } = parse(componentSource)
const compiled = compileScript(descriptor, { id: 'harness-settings-test' }).content

async function setup(provider, { error = null, throws = false } = {}) {
  let loads = 0
  let pending
  const store = {
    error,
    async fetchParams() { loads++; if (throws) throw new Error('offline') },
  }
  const component = evaluate(compiled, {
    vue: { ...vue, watch: (_source, callback) => { pending = callback() } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    '../bridgeSettings': { harnessBridgeSettings: [hermesSettings()] },
    '../stores/paramsStore': { useParamsStore: () => store },
    './BridgeSettingsPanel.vue': {},
  })
  const state = component.setup({ provider }, { expose() {} })
  await pending
  return { state, store, loads: () => loads }
}

test('Hermes global defaults do not require an assigned agent or an agent API call', () => {
  // evaluate() rejects any undeclared API dependency, including the old availability fetch.
  const contribution = hermesSettings()
  assert.notEqual(contribution.isAvailable?.(), false)
  assert.equal(contribution.refreshAvailability, undefined)
  assert.deepEqual(contribution.groups.flatMap(group => group.fields.map(field => field.name)), [
    'hermes.default.config', 'hermes.default.data-env',
  ])
})

test('the Hermes detail panel loads the existing parameter store', async () => {
  const { state, loads } = await setup('hermes')
  assert.equal(loads(), 1)
  assert.equal(state.contribution.value.kind, 'hermes')
  assert.equal(state.loading.value, false)
  assert.equal(state.loadFailed.value, false)
})

for (const failure of [{ error: new Error('offline') }, { throws: true }]) {
  test(`loading failure is explicit, not an empty editable form (${failure.throws ? 'throws' : 'store error'})`, async () => {
    const { state } = await setup('hermes', failure)
    assert.equal(state.loading.value, false)
    assert.equal(state.loadFailed.value, true)
  })
}

test('retry restores the panel after a failed parameter load', async () => {
  const { state, store, loads } = await setup('hermes', { error: new Error('offline') })
  store.error = null
  await state.load()
  assert.equal(loads(), 2)
  assert.equal(state.loadFailed.value, false)
})

test('providers without a settings contribution do not fetch parameters', async () => {
  const { state, loads } = await setup('openai_messages')
  assert.equal(state.contribution.value, undefined)
  assert.equal(loads(), 0)
})
