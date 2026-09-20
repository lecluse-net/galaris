import assert from 'node:assert/strict'
import test from 'node:test'
import * as catalog from './settingsCatalog.ts'
import * as harnessCatalog from '../../app/harnesses/runtimeSettings.ts'

const promptNames = [
  'ai.task-objective-system-prompt',
  'ai.planner-system-prompt',
  'ai.briefing-system-prompt',
  'ai.executor-system-prompt',
  'ai.conversation-executor-system-prompt',
  'ai.voice-executor-system-prompt',
  'ai.conversation-action-policy',
  'ai.topic-classification-system-prompt',
  'ai.topic-continuity-system-prompt',
  'ai.topic-resolution-system-prompt',
  'ai.memory-extraction-system-prompt',
  'audio.summary-meeting-segment-system-prompt',
  'audio.summary-meeting-reduce-system-prompt',
  'audio.summary-meeting-final-system-prompt',
  'audio.summary-video-segment-system-prompt',
  'audio.summary-video-reduce-system-prompt',
  'audio.summary-video-final-system-prompt',
]

test('every configurable prompt uses the governed prompt field', () => {
  const fields = [...Object.values(catalog), ...Object.values(harnessCatalog)].filter(Array.isArray).flat()
  for (const name of promptNames) {
    assert.equal(fields.find(field => field.name === name)?.input, 'prompt', name)
  }
})
