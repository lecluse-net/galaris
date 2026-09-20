import assert from 'node:assert/strict'
import test from 'node:test'
import { roomReferences } from './activity.ts'
import { applyTaskLiveRunEvent, emptyAIResult } from './aiResult.ts'

test('closing details keeps chat live until its own subscription is released', () => {
  const events = []
  const rooms = roomReferences(id => events.push(`join:${id}`), id => events.push(`leave:${id}`))
  rooms.retain('task'); rooms.retain('task'); rooms.release('task')
  assert.deepEqual(events, ['join:task'])
  rooms.release('task'); rooms.release('task')
  assert.deepEqual(events, ['join:task', 'leave:task'])
})

test('a cumulative checkpoint includes its delta exactly once and rejects an obsolete run', () => {
  const result = { ...emptyAIResult(), messages: [{ type: 'text', content: 'Hello', stream_id: 'text' }] }
  const event = { task_id: 'task', run_id: 'run', sequence: 4, kind: 'message',
    message: { type: 'text', content: 'lo', stream_id: 'text' }, snapshot: { run_id: 'run', sequence: 4, result } }
  const live = applyTaskLiveRunEvent(null, event, null, 'run')
  assert.equal(live.result.messages[0].content, 'Hello')
  assert.strictEqual(applyTaskLiveRunEvent(live, event, null, 'run'), live)
  assert.strictEqual(applyTaskLiveRunEvent(live, { ...event, run_id: 'old', sequence: 99 }, null, 'run'), live)
})

test('a resumed attempt can restart sequence numbers without accepting late events from its predecessor', () => {
  const previous = { runId: 'run', attemptId: 'old', sequence: 100, result: emptyAIResult() }
  const resumed = applyTaskLiveRunEvent(previous, { task_id: 'task', run_id: 'run', attempt_id: 'new',
    sequence: 0, kind: 'started' }, null, 'run', 'new')
  assert.equal(resumed.sequence, 0)
  assert.equal(resumed.attemptId, 'new')
  assert.strictEqual(applyTaskLiveRunEvent(resumed, { task_id: 'task', run_id: 'run', attempt_id: 'old',
    sequence: 101, kind: 'message', message: { type: 'text', content: 'Late old work' } }, null, 'run', 'new'), resumed)
})
