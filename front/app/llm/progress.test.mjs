import assert from 'node:assert/strict'
import test from 'node:test'
import { applyLlmCallProgress } from './progress.ts'

const call = { id: 'synthetic', status: 'running', response_text: 'Été🙂', reasoning: 'First',
  updated_at: '2026-01-01T12:00:00.000001Z', prompt: 'Retained context', tool_calls: [] }
const progress = { id: call.id, status: 'running', base_updated_at: call.updated_at,
  updated_at: '2026-01-01T12:00:00.000002Z', response_text: { append: '漢字' }, reasoning: { replace: 'Revised' } }

test('progress preserves context, Unicode and tools across deltas, retries and snapshots', () => {
  const updated = applyLlmCallProgress(call, progress)
  assert.equal(updated.response_text, 'Été🙂漢字')
  assert.equal(updated.reasoning, 'Revised')
  assert.equal(updated.prompt, call.prompt)
  assert.strictEqual(updated.tool_calls, call.tool_calls)
  assert.strictEqual(applyLlmCallProgress(updated, progress), updated)
  const newer = { ...updated, updated_at: '2026-01-01T12:00:00.000003Z' }
  assert.strictEqual(applyLlmCallProgress(newer, progress), newer)
  assert.equal(applyLlmCallProgress(call, { ...progress, base_updated_at: progress.updated_at }), null)
  const completed = { ...updated, status: 'completed' }
  assert.strictEqual(applyLlmCallProgress(completed, progress), completed)
  assert.equal(applyLlmCallProgress({ ...call, updated_at: call.updated_at.replace('Z', '+00:00') }, progress).response_text, updated.response_text)
})
