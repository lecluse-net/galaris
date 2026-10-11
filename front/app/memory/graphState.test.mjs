import { test } from 'node:test'
import assert from 'node:assert/strict'
import { GraphStatePersistence } from './graphState.ts'

const context = { agent_id: 7, query: '', topic_item_id: null, contact_item_id: null }
const state = (revision = 0) => ({ format_version: 1, revision, preferences: {
  hidden_entity_kinds: [], expanded_branches: [], camera: null,
}, positions: {} })

test('saves only new positions in bounded batches and independent preference fields', async () => {
  const calls = []
  const saved = []
  const transport = { readGraphState: async () => state(), saveGraphState: async (scope, patch) => {
    calls.push(structuredClone(patch)); assert.deepEqual(scope, context)
    return { ...state(patch.expected_revision + 1), positions: patch.positions }
  } }
  const controller = new GraphStatePersistence(context, transport, points => saved.push(points), assert.ifError)
  await controller.load()
  controller.remember([['existing', { x: 1, y: 2 }]])
  controller.stagePositions(Array.from({ length: 1201 }, (_, i) => [`node-${i}`, { x: i, y: 0 }]))
  controller.stagePositions([['existing', { x: 9, y: 9 }]])
  controller.stagePreferences({ hidden_entity_kinds: ['contact'] })
  await controller.flush()
  assert.deepEqual(calls.map(call => Object.keys(call.positions).length), [500, 500, 201])
  assert.deepEqual(calls[0].preferences, { hidden_entity_kinds: ['contact'] })
  assert.deepEqual(calls[1].preferences, {})
  assert(calls.every(call => !call.positions.existing))
  await controller.flush()
  assert.equal(calls.length, 3)
})

test('a failed save keeps newer edits and retry preserves the immutable context', async () => {
  let release
  const calls = []
  const failures = []
  const transport = { readGraphState: async () => state(), saveGraphState: async (scope, patch) => {
    calls.push(structuredClone(patch)); assert.equal(scope.agent_id, 7)
    if (calls.length === 1) await new Promise((_, reject) => { release = () => reject(new Error('offline')) })
    return state(patch.expected_revision + 1)
  } }
  const controller = new GraphStatePersistence(context, transport, () => {}, error => failures.push(error))
  await controller.load()
  controller.stagePreferences({ hidden_entity_kinds: ['contact'] })
  const running = controller.flush()
  controller.stagePreferences({ hidden_entity_kinds: ['file'] })
  release()
  await running
  assert.equal(failures.at(-1).message, 'offline')
  await controller.flush()
  assert.deepEqual(calls[1].preferences, { hidden_entity_kinds: ['file'] })
})

test('a concurrent revision is rebased with only the edited fields', async () => {
  let calls = 0
  const transport = { readGraphState: async () => state(calls ? 4 : 0), saveGraphState: async (_, patch) => {
    if (++calls === 1) throw { response: { status: 409 } }
    assert.equal(patch.expected_revision, 4)
    assert.deepEqual(patch.preferences, { hidden_entity_kinds: ['contact'] })
    return state(5)
  } }
  const controller = new GraphStatePersistence(context, transport, () => {}, assert.ifError)
  await controller.load()
  controller.stagePreferences({ hidden_entity_kinds: ['contact'] })
  await controller.flush()
  assert.equal(calls, 2)
})

test('saving after a failed restoration reloads the revision and preserves current edits', async () => {
  let reads = 0
  const calls = [], failures = []
  const transport = {
    readGraphState: async () => {
      if (++reads === 1) throw new Error('unavailable')
      return { ...state(8), preferences: { ...state().preferences, hidden_entity_kinds: ['contact'] } }
    },
    saveGraphState: async (_, patch) => {
      calls.push(structuredClone(patch))
      return { ...state(patch.expected_revision + 1), positions: patch.positions }
    },
  }
  const controller = new GraphStatePersistence(context, transport, () => {}, error => failures.push(error))
  await assert.rejects(controller.load(), /unavailable/)
  controller.stagePositions([['new-node', { x: 12, y: 34 }]])
  controller.stagePreferences({ hidden_entity_kinds: ['file'] })
  await controller.flush()
  assert.equal(reads, 2)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].expected_revision, 8)
  assert.deepEqual(calls[0].positions, { 'new-node': { x: 12, y: 34 } })
  assert.deepEqual(calls[0].preferences, { hidden_entity_kinds: ['file'] })
  assert.equal(failures.at(-1), null)
})

for (const invalid of [
  { format_version: 99 }, { preferences: null }, { preferences: { ...state().preferences, resource_branches: null } },
  { preferences: { ...state().preferences, camera_3d: { position: 'obsolete' } } },
  { positions: { old: { x: null, y: 2 } } },
  { preferences: { ...state().preferences, future_format: 3 } },
  { preferences: { ...state().preferences, camera: 'obsolete' } },
]) test(`an incompatible saved view is rebuilt (${JSON.stringify(invalid)})`, async () => {
  const calls = [], failures = []
  const transport = {
    readGraphState: async () => ({ ...state(8), ...invalid }),
    saveGraphState: async (_, patch) => {
      calls.push(structuredClone(patch))
      return { ...state(patch.expected_revision + 1), positions: patch.positions }
    },
  }
  const controller = new GraphStatePersistence(context, transport, () => {}, error => failures.push(error))
  const preferences = await controller.load()
  assert.deepEqual(preferences.hidden_entity_kinds, [])
  assert.equal(controller.restoresPositions, false)
  controller.remember([['old', { x: 100, y: 200 }]])
  controller.stagePositions([['old', { x: 12, y: 34 }]])
  await controller.flush()
  assert.equal(calls[0].reset_layout, true)
  assert.equal(calls[0].expected_revision, 8)
  assert.deepEqual(calls[0].positions, { old: { x: 12, y: 34 } })
  controller.stagePreferences({ hidden_entity_kinds: ['file'] })
  await controller.flush()
  assert.equal(calls[1].reset_layout, undefined)
  assert(failures.every(error => error === null))
})
