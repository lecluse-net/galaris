import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendAIMessage,
  currentAIResponse,
  emptyAIResult,
  finalizeAIResult,
} from '../task/aiResult.ts'

test('reflection fragments never become live or finalized conversation text', () => {
  const reflection = {
    type: 'tool',
    tool_name: 'thinking',
    stream_id: 'reasoning:1',
    content: 'PRIVATE STREAMED REFLECTION',
  }
  const visible = appendAIMessage(emptyAIResult(), {
    type: 'text',
    content: 'Visible answer',
  })
  const thinking = appendAIMessage(visible, reflection)
  assert.equal(currentAIResponse(thinking), 'Visible answer')
  assert.doesNotMatch(currentAIResponse(thinking), /PRIVATE STREAMED REFLECTION/)

  const reflectionOnly = appendAIMessage(emptyAIResult(), reflection)
  assert.equal(currentAIResponse(reflectionOnly), '')

  const finalized = finalizeAIResult(thinking, {
    ...emptyAIResult(),
    messages: [
      ...(reflectionOnly.messages ?? []),
      { type: 'text', content: 'Visible answer' },
    ],
    result: 'Visible answer',
  })
  assert.equal(currentAIResponse(finalized), 'Visible answer')
  assert.doesNotMatch(currentAIResponse(finalized), /PRIVATE STREAMED REFLECTION/)
})
