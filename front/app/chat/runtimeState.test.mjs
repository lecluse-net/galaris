import assert from 'node:assert/strict'
import test from 'node:test'

import { currentAIResponse, emptyAIResult } from '../task/facade.ts'
import { applyConversationRuntimeEvent } from './runtimeState.ts'

function apply(round, event) {
  return applyConversationRuntimeEvent(round, {
    room_id: 'room-1', round_id: 'round-stream', ...event,
  })?.round ?? round
}

test('every partition of a short Unicode response converges despite duplicate delivery', () => {
  const characters = Array.from('Été🙂漢字')
  // Exhaust all contiguous partitions, preserving the order guaranteed by the transport.
  for (let mask = 0; mask < 2 ** (characters.length - 1); mask++) {
    const fragments = [characters[0]]
    for (let i = 1; i < characters.length; i++) {
      if (mask & (1 << (i - 1))) fragments.push(characters[i])
      else fragments[fragments.length - 1] += characters[i]
    }
    let round = apply(null, { kind: 'started', sequence: 0 })
    for (const [index, fragment] of fragments.entries()) {
      const event = { kind: 'message', sequence: index + 1, message: { type: 'text', content: fragment } }
      round = apply(round, event)
      const previous = round
      round = apply(round, event)
      assert.strictEqual(round, previous, `duplicate changed partition ${mask}`)
    }
    assert.equal(currentAIResponse(round.ai_result), characters.join(''))
    round = apply(round, { kind: 'finished', sequence: fragments.length + 1 })
    assert.equal(round.active, false)
    assert.equal(currentAIResponse(round.ai_result), characters.join(''))
  }
})

test('reset discards provisional text and a stale pre-reset event cannot restore it', () => {
  let round = apply(null, { kind: 'started', sequence: 0 })
  const stale = { kind: 'message', sequence: 1, message: { type: 'text', content: 'provisional' } }
  round = apply(round, stale)
  round = apply(round, { kind: 'reset', sequence: 2 })
  assert.equal(currentAIResponse(round.ai_result), '')
  round = apply(round, stale)
  round = apply(round, { kind: 'message', sequence: 3, message: { type: 'text', content: 'corrected' } })
  round = apply(round, { kind: 'finished', sequence: 4, success: false })
  assert.equal(currentAIResponse(round.ai_result), 'corrected')
  assert.equal(round.active, false)
  assert.equal(round.success, false)
})

test('ordered text events replace the live state and update the response immediately', () => {
  const started = applyConversationRuntimeEvent(null, {
    room_id: 'room-1',
    round_id: 'round-stream',
    kind: 'started',
    sequence: 0,
  })
  assert.ok(started)

  const first = applyConversationRuntimeEvent(started.round, {
    room_id: 'room-1',
    round_id: 'round-stream',
    kind: 'message',
    sequence: 1,
    message: { type: 'text', content: 'Bon' },
  })
  assert.ok(first)

  const second = applyConversationRuntimeEvent(first.round, {
    room_id: 'room-1',
    round_id: 'round-stream',
    kind: 'message',
    sequence: 2,
    message: { type: 'text', content: 'jour' },
  })
  assert.ok(second)

  assert.equal(currentAIResponse(first.round.ai_result), 'Bon')
  assert.equal(currentAIResponse(second.round.ai_result), 'Bonjour')
  assert.notStrictEqual(first.round, second.round)
})

test('a new attempt restarts sequencing while retaining reflection and rejecting the old attempt', () => {
  let round = apply(null, { kind: 'started', sequence: 0, attempt: 1 })
  round = apply(round, { kind: 'message', sequence: 1, attempt: 1,
    message: { type: 'tool', tool_name: 'thinking', stream_id: 'r1', content: 'Analyse déjà reçue' } })
  round = apply(round, { kind: 'finished', sequence: 5, attempt: 1, success: false })
  round = apply(round, { kind: 'started', sequence: 0, attempt: 2 })
  round = apply(round, { kind: 'message', sequence: 1, attempt: 2,
    message: { type: 'text', stream_id: 't2', content: 'Réponse' } })
  assert.equal(round.attempt, 2)
  assert.equal(round.active, true)
  assert.equal(round.ai_result.messages[0].content, 'Analyse déjà reçue')
  const before = round
  round = apply(round, { kind: 'finished', sequence: 9, attempt: 1 })
  assert.strictEqual(round, before)
  round = apply(round, { kind: 'finished', sequence: 2, attempt: 2 })
  const terminal = round
  round = apply(round, { kind: 'message', sequence: 3, attempt: 2,
    message: { type: 'text', content: 'tardif' } })
  assert.strictEqual(round, terminal)
})

test('a missing fragment requests a snapshot before accepting more deltas', () => {
  let round = apply(null, { kind: 'started', sequence: 0 })
  round = apply(round, { kind: 'message', sequence: 1, message: { type: 'text', stream_id: 't', content: 'Bon' } })
  const gap = applyConversationRuntimeEvent(round, {
    room_id: 'room-1', round_id: 'round-stream', kind: 'message', sequence: 3,
    message: { type: 'text', stream_id: 't', content: ' !' },
  })
  assert.equal(gap.needsSnapshot, true)
  assert.strictEqual(gap.round, round)
  round = apply(round, { kind: 'snapshot', sequence: 3, result: {
    ...emptyAIResult(),
    messages: [{ type: 'text', stream_id: 't', content: 'Bonjour !' }], result: 'Bonjour !',
  } })
  assert.equal(currentAIResponse(round.ai_result), 'Bonjour !')
  round = apply(round, { kind: 'message', sequence: 4, message: { type: 'text', stream_id: 't', content: ' Suite.' } })
  assert.equal(currentAIResponse(round.ai_result), 'Bonjour ! Suite.')
})

test('a new client restores an active result from its snapshot without duplication', () => {
  const event = { kind: 'snapshot', sequence: 20, result: {
    ...emptyAIResult(),
    messages: [{ type: 'text', stream_id: 't', content: 'Déjà généré' }], result: 'Déjà généré',
  } }
  let round = apply(null, event)
  round = apply(round, event)
  assert.equal(round.active, true)
  assert.equal(currentAIResponse(round.ai_result), 'Déjà généré')
  round = apply(round, { kind: 'finished', sequence: 21, result: event.result })
  const finished = round
  round = apply(round, event)
  assert.strictEqual(round, finished)
})

test('an HTTP terminal catch-up still accepts the richer finished event', () => {
  let round = apply(null, { kind: 'started', sequence: 0 })
  round = apply(round, { kind: 'message', sequence: 1,
    message: { type: 'text', stream_id: 't', content: 'Bon' } })
  round = { ...round, active: false }
  round = apply(round, { kind: 'finished', sequence: 2, result: {
    ...round.ai_result, result: 'Bonjour', messages: [{ type: 'text', stream_id: 't', content: 'Bonjour' }],
  } })
  assert.equal(currentAIResponse(round.ai_result), 'Bonjour')
  assert.equal(round.terminal_received, true)
})
test('a foreign round event cannot replace the current response without an authoritative snapshot', () => {
  const current = apply(null, { kind: 'started', sequence: 0 })
  for (const kind of ['started', 'message', 'snapshot', 'finished']) {
    const update = applyConversationRuntimeEvent(current, {
      room_id: 'room-1', round_id: 'older-or-newer-unknown', kind, sequence: 5,
      message: { type: 'text', content: 'Autre réponse' }, result: emptyAIResult(),
    })
    assert.strictEqual(update.round, current)
    assert.equal(update.needsSnapshot, true)
  }
  const authoritative = { ...current, round_id: 'new-round', last_sequence: -1 }
  const update = applyConversationRuntimeEvent(authoritative, {
    room_id: 'room-1', round_id: 'new-round', kind: 'snapshot', sequence: 8,
    result: { ...emptyAIResult(), result: 'Réponse reprise' },
  })
  assert.equal(update.round.round_id, 'new-round')
  assert.equal(update.round.ai_result.result, 'Réponse reprise')
})
