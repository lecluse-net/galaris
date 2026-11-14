import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { createActivity, canAssignActivityActor, assignActivityActor, processingMode } = loadTypescript(new URL('./graphEditing.ts', import.meta.url), {
  './services/nativeProcessService': {},
})
const graph = { schema_version: 'galaris.bpmn/v2', nodes: [], flows: [], actors: [
  { id: 'ai', name: 'Synthetic AI', kind: 'agent' }, { id: 'person', name: 'Synthetic human', kind: 'human' },
] }

test('all four task types remain explicit when created from a human lane', () => {
  for (const [kind, expectedMode, actor] of [['task', 'ai', 'ai'], ['llm_task', 'llm', 'person'], ['code', 'code', 'person'], ['human_task', 'human', 'person']]) {
    const node = createActivity(kind, graph, 'person')
    assert.equal(processingMode(node), expectedMode)
    assert.equal(node.config.actor, actor)
  }
  const decision = createActivity('if', graph, 'person')
  assert.equal(processingMode(decision), 'llm')
  assert.equal(decision.config.actor, 'person')
})

test('moving an activity preserves its execution type, instructions and variable bindings', () => {
  for (const kind of ['llm_task', 'code', 'if']) {
    const node = { ...createActivity(kind, graph, 'ai'), inputs: ['source'], outputs: kind === 'if' ? [] : ['result'] }
    for (const actor of ['person', '', 'ai']) {
      const moved = assignActivityActor(node, actor, graph)
      assert.deepEqual(moved, { ...node, config: { ...node.config, actor: actor || null } })
      assert.equal(processingMode(moved), processingMode(node))
    }
  }
  for (const [kind, forbidden] of [['task', 'person'], ['human_task', 'ai']]) {
    const node = createActivity(kind, graph)
    assert.equal(assignActivityActor(node, forbidden, graph), node)
    if (kind === 'human_task') assert.equal(assignActivityActor(node, '', graph), node)
  }
})

test('agentic tasks can use the process execution agent even when named human roles exist', () => {
  const value = { ...graph, execution_agent_id: 7, actors: graph.actors.filter(actor => actor.kind === 'human') }
  const node = createActivity('task', value)
  assert.equal(canAssignActivityActor(node, '', value), true)
  const assigned = assignActivityActor(node, '', value)
  assert.equal(assigned.config.actor, null)
  assert.equal(value.execution_agent_id, 7)
  assert.deepEqual(value.actors, graph.actors.filter(actor => actor.kind === 'human'))
})
