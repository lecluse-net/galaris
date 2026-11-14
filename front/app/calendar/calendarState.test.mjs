import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { retainCalendarEvents, retainExecutionStates } = loadTypescript(new URL('./calendarState.ts', import.meta.url), {})
const event = { event_id: 'synthetic-event', recurrence_key: 'first', revision: 1, sync_state: 'pending', summary: 'Synthetic appointment' }

test('polling reuses unchanged snapshots but applies content, sync and nested source changes without relying on revision', () => {
  const previous = [event, { ...event, recurrence_key: 'second' }]
  assert.equal(retainCalendarEvents(previous, structuredClone(previous)), previous)
  for (const change of [{ summary: 'Synthetic revision' }, { sync_state: 'conflict' }, { goal_event: { state: 'done' } }, { memory_event: { excerpt: 'Synthetic changed memory' } }]) {
    const incoming = [{ ...event, ...change }, { ...previous[1] }]
    const result = retainCalendarEvents(previous, incoming)
    assert.equal(result[0], incoming[0])
    assert.equal(result[1], previous[1])
    assert.deepEqual(result, incoming)
  }
  assert.deepEqual(retainCalendarEvents(previous, [previous[1], previous[0]]), [previous[1], previous[0]])
  assert.deepEqual(retainCalendarEvents(previous, []), [])
  assert.deepEqual(retainCalendarEvents([], [event]), [event])
})

test('badge polling preserves unchanged states, refreshes live Tasks, recovers from errors and removes absent occurrences', () => {
  const previous = { first: { total: 1, states: { queued: 1 } }, second: { total: 0, failed: true } }
  assert.equal(retainExecutionStates(previous, structuredClone(previous)), previous)
  const incoming = { first: { total: 1, states: { running: 1 } }, second: { total: 0 } }
  assert.deepEqual(retainExecutionStates(previous, incoming), incoming)
  assert.equal(retainExecutionStates(previous, { first: { ...previous.first } }).first, previous.first)
  assert.deepEqual(retainExecutionStates(previous, {}), {})
  assert.deepEqual(retainExecutionStates({}, incoming), incoming)
})
