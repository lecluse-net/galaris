import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyTaskLiveRunEvent,
  reconcileAIResult,
  appendAIMessage,
  emptyAIResult,
} from './aiResult.ts'

const taskId = '91bb344f-19aa-4930-a867-7ca15195cdde'
const runId = '10ac9183-df9c-46b9-9c19-ec3e5825b331'

test('a late live subscription starts from the already persisted execution trace', () => {
  const durable = appendAIMessage(
    emptyAIResult('Question'),
    { type: 'tool', tool_name: 'search', content: 'Premier résultat' },
  )

  const state = applyTaskLiveRunEvent(null, {
    task_id: taskId,
    run_id: runId,
    sequence: 0,
    kind: 'started',
  }, durable, runId)

  assert.deepEqual(state?.result.messages, durable.messages)
})

test('duplicate or out-of-order events never clear a more advanced live trace', () => {
  const progressed = applyTaskLiveRunEvent(null, {
    task_id: taskId,
    run_id: runId,
    sequence: 2,
    kind: 'message',
    message: { type: 'text', content: 'Déjà visible' },
  }, null, runId)

  const delayedStart = applyTaskLiveRunEvent(progressed, {
    task_id: taskId,
    run_id: runId,
    sequence: 0,
    kind: 'started',
  }, null, runId)

  assert.strictEqual(delayedStart, progressed)
  assert.equal(delayedStart?.result.result, 'Déjà visible')
})

test('events from a superseded run cannot replace the current buffer', () => {
  const current = applyTaskLiveRunEvent(null, {
    task_id: taskId,
    run_id: runId,
    sequence: 1,
    kind: 'message',
    message: { type: 'text', content: 'Run courant' },
  }, null, runId)

  const stale = applyTaskLiveRunEvent(current, {
    task_id: taskId,
    run_id: 'b3ae77ac-45e7-4e49-bdfd-7daa9affaf35',
    sequence: 0,
    kind: 'started',
  }, null, runId)

  assert.strictEqual(stale, current)
})

test('a current-run message can replace an old buffer when the start event was missed', () => {
  const oldRun = applyTaskLiveRunEvent(null, {
    task_id: taskId,
    run_id: '83a942c9-b7e1-455d-ae25-37da94c54abe',
    sequence: 3,
    kind: 'message',
    message: { type: 'text', content: 'Ancienne tentative' },
  }, null, null)

  const currentRun = applyTaskLiveRunEvent(oldRun, {
    task_id: taskId,
    run_id: runId,
    sequence: 1,
    kind: 'message',
    message: { type: 'text', content: 'Nouvelle tentative' },
  }, null, runId)

  assert.equal(currentRun?.runId, runId)
  assert.equal(currentRun?.result.result, 'Nouvelle tentative')
})

test('a richer durable reconciliation repairs events missed during a disconnect', () => {
  const live = appendAIMessage(
    emptyAIResult('Question'),
    { type: 'text', content: 'Début' },
  )
  const durable = appendAIMessage(
    live,
    { type: 'tool', tool_name: 'search', content: 'Résultat récupéré' },
  )

  const reconciled = reconcileAIResult(live, durable)

  assert.deepEqual(reconciled?.messages, durable.messages)
  assert.equal(reconciled?.result, durable.result)
})

test('a durable result without messages cannot erase the live trace', () => {
  const live = appendAIMessage(
    emptyAIResult('Question'),
    { type: 'tool', tool_name: 'search', content: 'Trace déjà visible' },
  )
  const terminalProjection = {
    ...emptyAIResult('Question'),
    result: 'Réponse terminale beaucoup plus longue que la trace',
  }

  const reconciled = reconcileAIResult(live, terminalProjection)

  assert.deepEqual(reconciled?.messages, live.messages)
  assert.equal(reconciled?.result, terminalProjection.result)
})

test('live fragments with the same stream id stay in one thinking block', () => {
  const first = appendAIMessage(
    emptyAIResult('Question'),
    {
      type: 'tool',
      tool_name: 'thinking',
      stream_id: 'codex:reasoning:r1:0',
      content: 'Inspection ',
    },
  )
  const second = appendAIMessage(
    first,
    {
      type: 'tool',
      tool_name: 'thinking',
      stream_id: 'codex:reasoning:r1:0',
      content: 'des contrats.',
    },
  )
  const distinct = appendAIMessage(
    second,
    {
      type: 'tool',
      tool_name: 'thinking',
      stream_id: 'codex:reasoning:r1:1',
      content: 'Vérification des tests.',
    },
  )

  assert.equal(distinct.messages.length, 2)
  assert.equal(distinct.messages[0].content, 'Inspection des contrats.')
  assert.equal(distinct.messages[1].content, 'Vérification des tests.')
})
