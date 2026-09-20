import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../../test-support/load-typescript.mjs'
import * as activity from '../taskActivity.ts'

const service = loadTypescript(new URL('./taskStatusService.ts', import.meta.url), {
  '@/core/i18n': { i18n: { global: { t: key => key } } }, '../taskActivity': activity,
})

test('terminal statuses use semantic tones and unknown statuses have a safe fallback', () => {
  assert.equal(service.getTaskStatusTone('SUCCESS'), 'success')
  assert.equal(service.getTaskStatusTone('ERROR'), 'error')
  assert.equal(service.getTaskStatusTone('EXEC'), 'active')
  assert.equal(service.getTaskStatusTone('unknown'), 'neutral')
})

test('human pause takes precedence over automatic wait and the execution phase', () => {
  assert.equal(service.getTaskOperationalIcon({ status: 'EXEC', paused: false }), 'play_circle')
  assert.equal(service.getTaskOperationalIcon({ status: 'EXEC', paused: true, data: { pause_reasons: ['await'] } }), 'hourglass_top')
  assert.equal(service.getTaskOperationalIcon({ status: 'EXEC', paused: true, data: { pause_reasons: ['await', 'user'] } }), 'pause_circle')
  assert.equal(service.pauseBadge({ paused: true, data: { pause_reasons: ['await', 'user'] } }).waiting, false)
})
