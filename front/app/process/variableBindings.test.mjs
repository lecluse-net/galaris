import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { variableUsage, setVariableUsage, updateProcessVariables, processInputs, processOutputs, allowsVariableDirection } = loadTypescript(new URL('./variableBindings.ts', import.meta.url), {})
const node = (id, extra = {}) => ({ id, kind: 'task', config: {}, body: null, ...extra })
function graph() {
  return { variables: [{ name: 'source', type: 'string', nullable: true }, { name: 'result', type: 'bool', nullable: true }],
    nodes: [node('work', { inputs: ['source'], outputs: ['result'] }),
      node('loop', { body: { nodes: [node('inside', { inputs: ['source'], outputs: ['source'] })], flows: [] } }),
      node('start', { kind: 'start', inputs: ['source'] }), node('end', { kind: 'end', outputs: ['result'] })], flows: [] }
}

test('both editing directions use the same references, including nested steps and process boundaries', () => {
  const original = graph(), before = structuredClone(original)
  assert.deepEqual(variableUsage(original, 'source', 'inputs'), ['["work"]', '["loop","inside"]', '["start"]'])
  assert.deepEqual(processInputs(original), ['source'])
  const updated = setVariableUsage(original, 'source', 'inputs', ['["loop"]'])
  assert.deepEqual(variableUsage(updated, 'source', 'inputs'), ['["loop"]'])
  assert.deepEqual(variableUsage(updated, 'source', 'outputs'), ['["loop","inside"]'])
  assert.deepEqual(updated.variables, before.variables)
  assert.deepEqual(original, before)
  assert.equal(setVariableUsage(original, 'undeclared', 'inputs', ['[]']), original)
})

test('renaming and deleting variables updates all references without changing other directions or declarations', () => {
  const original = graph()
  const renamed = updateProcessVariables(original, [{ ...original.variables[0], name: 'renamed' }, original.variables[1]])
  assert.deepEqual(variableUsage(renamed, 'renamed', 'inputs'), ['["work"]', '["loop","inside"]', '["start"]'])
  assert.deepEqual(variableUsage(renamed, 'source', 'inputs'), [])
  assert.deepEqual(renamed.nodes[1].body.nodes[0].outputs, ['renamed'])
  const reordered = updateProcessVariables(renamed, [...renamed.variables].reverse())
  assert.deepEqual(variableUsage(reordered, 'renamed', 'inputs'), variableUsage(renamed, 'renamed', 'inputs'))
  const removed = updateProcessVariables(reordered, reordered.variables.filter(variable => variable.name !== 'renamed'))
  assert.deepEqual(processInputs(removed), [])
  assert.deepEqual(removed.nodes[1].body.nodes[0].outputs, [])
  assert.deepEqual(processOutputs(removed), ['result'])
  assert.deepEqual(removed.variables, [original.variables[1]])
})

test('control-node directions cannot be assigned from the variable even with forged selections', () => {
  const value = graph()
  value.nodes.push(node('if', { kind: 'if' }), node('end', { kind: 'end' }))
  for (const [kind, direction] of [['start', 'outputs'], ['if', 'outputs'], ['end', 'inputs']]) {
    assert.equal(allowsVariableDirection(kind, direction), false)
    const updated = setVariableUsage(value, 'source', direction, [`["${kind}"]`])
    assert.deepEqual(updated.nodes.find(node => node.id === kind)[direction], [])
  }
  const updated = setVariableUsage(value, 'source', 'inputs', ['["start"]', '[]'])
  assert.deepEqual(processInputs(updated), ['source'])
  assert.equal(Object.hasOwn(updated, 'inputs'), false)
})

test('a task output alone never makes a variable a process output or adds a generic process use', () => {
  const value = graph()
  value.nodes.find(node => node.id === 'end').outputs = []
  assert.deepEqual(processOutputs(value), [])
  assert.deepEqual(variableUsage(value, 'result', 'outputs'), ['["work"]'])
  const selected = setVariableUsage(value, 'result', 'outputs', ['["work"]', '["end"]', '[]'])
  assert.deepEqual(processOutputs(selected), ['result'])
  assert.deepEqual(variableUsage(selected, 'result', 'outputs'), ['["work"]', '["end"]'])
  assert.equal(Object.hasOwn(selected, 'outputs'), false)
})
