import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { runDurationSeconds } = loadTypescript(new URL('./runTiming.ts', import.meta.url), {})
const start = '2026-01-01T12:00:00Z'
const now = Date.parse(start) + 65_500

test('run durations exclude queueing and stop at the recorded finish', () => {
  assert.equal(runDurationSeconds({ status: 'queued', started_at: null }, now), null)
  assert.equal(runDurationSeconds({ status: 'running', started_at: start }, now), 65.5)
  for (const status of ['success', 'error', 'cancelled']) {
    const run = { status, started_at: start, finished_at: '2026-01-01T12:00:05Z' }
    assert.equal(runDurationSeconds(run, now), 5)
    assert.equal(runDurationSeconds(run, now + 3600_000), 5)
    assert.equal(runDurationSeconds({ status, started_at: start }, now), null)
  }
  assert.equal(runDurationSeconds({ status: 'running', started_at: 'invalid' }, now), null)
  assert.equal(runDurationSeconds({ status: 'running', started_at: start }, now - 120_000), 0)
})
