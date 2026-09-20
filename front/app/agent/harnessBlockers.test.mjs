import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Execute the real form submission handler, not a parallel implementation of its guard.
const page = readFileSync(new URL('./pages/index.vue', import.meta.url), 'utf8')
const script = page.match(/<script setup[^>]*>([\s\S]*?)<\/script>/)[1]
const source = ts.createSourceFile('agent.ts', script, ts.ScriptTarget.Latest, true)
const declaration = source.statements
  .filter(ts.isVariableStatement)
  .flatMap(statement => [...statement.declarationList.declarations])
  .find(node => node.name.getText(source) === 'onAgentSubmit')
assert.ok(declaration?.initializer)
const handler = ts.transpileModule(`const submit = ${declaration.initializer.getText(source)}`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

function setup({ active = 0, paused = 0, confirmed = false, checkFails = false } = {}) {
  const calls = []
  const ref = value => ({ value })
  const scope = {
    canSaveAgent: ref(true), harnessChangePending: ref(false), isAgentEdit: ref(true),
    harnessSelectionLoaded: ref(true), selectedHarnessId: ref(null), initialHarnessId: ref('hermes'),
    confirmHarnessReplacement: async () => true,
    privilegeStore: { hasPrivilege: () => true }, privileges: { TASK_EDIT: 'edit' },
    agentForm: { id: 1 }, pausedHarnessTasks: ref([]), activeHarnessTaskCount: ref(0),
    loadPausedHarnessTasks: async () => {
      calls.push('check')
      if (checkFails) throw new Error('offline')
      scope.pausedHarnessTasks.value = Array.from({ length: paused }, () => ({ id: 'paused' }))
      scope.activeHarnessTaskCount.value = active
    },
    confirmPausedHarnessTasksTermination: async () => { calls.push('dialog'); return confirmed },
    terminatePausedHarnessTasks: async () => { calls.push('terminate'); scope.pausedHarnessTasks.value = [] },
    NO_VOICE: 'none', harnessStates: {}, showAgentDialog: ref(true),
    harnessState: () => ({ status: 'loading' }),
    agentStore: {
      agents: [],
      updateAgent: async () => calls.push('save'), fetchAgents: async () => {},
    },
    harnessService: { selectInternal: async () => { calls.push('switch'); return { data: { internal: true } } } },
    $q: { notify: value => calls.push(value.message) }, t: key => key,
  }
  const submit = new Function(...Object.keys(scope), `${handler}; return submit`)(...Object.values(scope))
  return { calls, scope, submit }
}

for (const paused of [0, 1]) {
  test(`active blockers open their dialog without mutation (${paused} paused)`, async () => {
    const { calls, scope, submit } = setup({ active: 1, paused, confirmed: true })
    await submit()
    assert.deepEqual(calls, ['check', 'dialog'])
    assert.equal(scope.harnessChangePending.value, false)
  })
}

test('dismissal preserves paused tasks and harness', async () => {
  const { calls, submit } = setup({ paused: 1 })
  await submit()
  assert.deepEqual(calls, ['check', 'dialog'])
})

test('paused-only blockers still require confirmation before termination and switch', async () => {
  const { calls, submit } = setup({ paused: 1, confirmed: true })
  await submit()
  assert.deepEqual(calls, ['check', 'dialog', 'terminate', 'save', 'switch', 'agent.harness.preferenceSaved'])
})

test('no blockers allow the normal switch', async () => {
  const { calls, submit } = setup()
  await submit()
  assert.deepEqual(calls, ['check', 'save', 'switch', 'agent.harness.preferenceSaved'])
})

test('failed inspection never saves or switches', async () => {
  const { calls, scope, submit } = setup({ checkFails: true })
  await submit()
  assert.deepEqual(calls, ['check', 'agent.harness.pausedTasksCheckError'])
  assert.equal(scope.harnessChangePending.value, false)
})
