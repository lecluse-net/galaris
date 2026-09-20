import assert from 'node:assert/strict'
import test from 'node:test'

import { shouldAnimateTaskStatus } from './taskActivity.ts'

test('queued and waiting attempts do not suggest active work', () => {
  for (const operationalState of ['QUEUED', 'WAITING', 'PAUSED', 'TERMINAL']) {
    assert.equal(shouldAnimateTaskStatus({ status: 'EXEC', operationalState }), false)
  }
  assert.equal(shouldAnimateTaskStatus({ status: 'EXEC', operationalState: 'RUNNING' }), true)
  assert.equal(shouldAnimateTaskStatus({ status: 'SUCCESS', operationalState: 'RUNNING' }), false)
})

test('an active execution phase is animated', () => {
  assert.equal(shouldAnimateTaskStatus({ status: 'EXEC', paused: false }), true)
})

test('a suspended task never keeps an active phase animation', () => {
  assert.equal(shouldAnimateTaskStatus({ status: 'DISPATCH', paused: true }), false)
  assert.equal(shouldAnimateTaskStatus({ status: 'EXEC', paused: true }), false)
})

test('a static phase is never animated', () => {
  assert.equal(shouldAnimateTaskStatus({ status: 'CREATE', paused: false }), false)
  assert.equal(shouldAnimateTaskStatus({ status: 'SUCCESS', paused: false }), false)
})
