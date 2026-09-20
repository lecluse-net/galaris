import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

test('harness preferences use the unified overview contribution', () => {
  const component = {}
  const contribution = loadTypescript(new URL('./settings.ts', import.meta.url), {
    './components/HarnessPreferences.vue': { __esModule: true, default: component },
    './components/TaskExecutionSettings.vue': { __esModule: true, default: {} },
  }).default
  assert.equal(contribution.placement, 'overview')
  assert.equal(contribution.component, component)
})

test('managed containers retain the shared YAML Compose preference', () => {
  const { managedComposeFields } = loadTypescript(new URL('./managedSettings.ts', import.meta.url), {})
  assert.deepEqual(managedComposeFields.map(({ name, input, codeLanguage }) => ({ name, input, codeLanguage })), [
    { name: 'harness.default.compose', input: 'code', codeLanguage: 'yaml' },
  ])
})
