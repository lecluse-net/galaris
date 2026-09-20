import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendAIMessage,
  completedTaskAIResult,
  currentAIResponse,
  emptyAIResult,
  finalizeAIResult,
  reconcileAIResult,
  reconcileTaskAIResult,
} from './aiResult.ts'

test('text AIMessage fragments are visible immediately and append to the current block', () => {
  const first = appendAIMessage(
    emptyAIResult('Question'),
    { type: 'text', content: 'Bon', success: true },
  )
  const second = appendAIMessage(
    first,
    { type: 'text', content: 'jour', success: true },
  )

  assert.equal(currentAIResponse(first), 'Bon')
  assert.equal(currentAIResponse(second), 'Bonjour')
  assert.notStrictEqual(second, first)
})

test('snapshot null tool names and omitted live tool names identify the same text block', () => {
  for (const stream_id of ['answer:1', undefined]) {
    let result = {
      ...emptyAIResult(),
      result: 'A free ',
      messages: [{ type: 'text', stream_id, tool_name: null, content: 'A free ' }],
    }
    for (const content of ['Samp', 'le image.']) {
      result = appendAIMessage(result, { type: 'text', stream_id, content })
    }
    assert.deepEqual(result.messages.map(message => message.content), ['A free Sample image.'])
    const snapshot = {
      ...emptyAIResult(),
      messages: [{ type: 'text', stream_id, content: 'A free Sample image.' }],
    }
    assert.equal(reconcileAIResult(result, snapshot).messages.length, 1)
    assert.equal(reconcileAIResult(snapshot, result).messages.length, 1)
  }
})

test('Task text stays hidden until completion while conversations still expose each delta', () => {
  let result = emptyAIResult()
  for (const content of ['Samp', 'le image.']) {
    result = appendAIMessage(result, { type: 'text', stream_id: 'text', stream_complete: false, content })
    assert.equal(completedTaskAIResult(result, false).messages.length, 0)
    assert.equal(completedTaskAIResult(result, false).result, '')
    assert.equal(currentAIResponse(result), result.result)
  }
  result = appendAIMessage(result, { type: 'text', stream_id: 'text', stream_complete: true, content: '' })
  assert.deepEqual(completedTaskAIResult(result, false).messages.map(message => message.content), ['Sample image.'])
  const stale = { ...result, messages: [{ ...result.messages[0], stream_complete: false }] }
  assert.equal(completedTaskAIResult(reconcileAIResult(result, stale), false).messages.length, 1)
  const next = appendAIMessage(result, { type: 'text', stream_id: 'next', stream_complete: false, content: 'Unfinished' })
  assert.equal(completedTaskAIResult(next, false).messages.length, 1)
  assert.equal(completedTaskAIResult(next, true).messages.length, 2)
})

test('legacy Task narration waits for the following operation or the terminal result', () => {
  let result = appendAIMessage(emptyAIResult(), { type: 'text', stream_id: 'text', content: 'Completed narration' })
  result = appendAIMessage(result, { type: 'tool', tool_name: 'thinking', stream_id: 'thought', content: 'In progress' })
  assert.equal(completedTaskAIResult(result, false).messages.length, 0)
  result = appendAIMessage(result, { type: 'tool', tool_name: 'search', content: 'Found' })
  assert.deepEqual(completedTaskAIResult(result, false).messages, result.messages)
  assert.deepEqual(completedTaskAIResult(result, true), result)
})

test('interleaved deltas belong to their identified AIMessage', () => {
  let result = emptyAIResult()
  for (const message of [
    { type: 'tool', tool_name: 'thinking', stream_id: 'r', content: 'Je ' },
    { type: 'text', stream_id: 't', content: 'Bon' },
    { type: 'tool', tool_name: 'thinking', stream_id: 'r', content: 'vérifie.' },
    { type: 'text', stream_id: 't', content: 'jour' },
  ]) result = appendAIMessage(result, message)
  assert.deepEqual(result.messages.map(m => m.content), ['Je vérifie.', 'Bonjour'])
  const terminal = { ...emptyAIResult(), messages: [{ type: 'text', stream_id: 't', content: 'Bonjour' }], result: 'Bonjour' }
  const final = finalizeAIResult(result, terminal)
  assert.deepEqual(final.messages.map(m => m.content), ['Je vérifie.', 'Bonjour'])
  assert.deepEqual(finalizeAIResult(final, terminal).messages, final.messages)
  assert.equal(currentAIResponse(final), 'Bonjour')
})

test('a longer snapshot cannot erase an existing reflection and stale snapshots cannot truncate it', () => {
  const reflection = { type: 'tool', tool_name: 'thinking', stream_id: 'r', content: 'Analyse complète.' }
  const current = { ...emptyAIResult(), messages: [reflection] }
  const incoming = { ...emptyAIResult(), messages: [
    { ...reflection, content: 'Analyse' },
    { type: 'text', stream_id: 't', content: 'Une réponse finale beaucoup plus longue que la réflexion.' },
  ] }
  const merged = reconcileAIResult(current, incoming)
  assert.equal(merged.messages[0].content, reflection.content)
  assert.deepEqual(reconcileAIResult(merged, incoming).messages, merged.messages)
})

test('the visible response contains only text AIMessages, separated by a blank line', () => {
  let result = { ...emptyAIResult(), result: 'NE DOIT PAS ÊTRE AFFICHÉ' }
  result = appendAIMessage(result, { type: 'text', content: 'Première partie.' })
  result = appendAIMessage(result, {
    type: 'tool',
    tool_name: 'search',
    content: 'DÉTAIL TECHNIQUE MASQUÉ',
  })
  result = appendAIMessage(result, { type: 'audio', content: 'AUDIO MASQUÉ' })
  result = appendAIMessage(result, { type: 'text', content: 'Deuxième partie.' })

  assert.equal(currentAIResponse(result), 'Première partie.\n\nDeuxième partie.')
})

test('different explicit text streams remain separate semantic AIMessages', () => {
  const first = appendAIMessage(emptyAIResult(), {
    type: 'text',
    stream_id: 'answer:1',
    content: 'Un',
  })
  const firstComplete = appendAIMessage(first, {
    type: 'text',
    stream_id: 'answer:1',
    content: ' bloc',
  })
  const second = appendAIMessage(firstComplete, {
    type: 'text',
    stream_id: 'answer:2',
    content: 'Un autre bloc',
  })

  assert.deepEqual(second.messages?.map(message => message.content), [
    'Un bloc',
    'Un autre bloc',
  ])
  assert.equal(currentAIResponse(second), 'Un bloc\n\nUn autre bloc')
})

test('the terminal projection replaces streamed text only when it supplies AIMessages', () => {
  const streamed = appendAIMessage(emptyAIResult(), {
    type: 'text',
    content: 'Réponse streamée',
  })
  const withoutMessages = finalizeAIResult(streamed, {
    ...emptyAIResult(),
    result: 'Résultat sans AIMessage',
  })
  assert.equal(currentAIResponse(withoutMessages), 'Réponse streamée')

  const withMessages = finalizeAIResult(streamed, {
    ...emptyAIResult(),
    messages: [{ type: 'text', content: 'Réponse terminale' }],
    result: 'Réponse terminale',
  })
  assert.equal(currentAIResponse(withMessages), 'Réponse terminale')
})

for (const identity of ['tool_call_external_id', 'stream_id', 'legacy']) {
  test(`snapshot/live overlap leaves one card per invocation (${identity})`, () => {
    const completed = ['image_generate', 'file_info', 'image_read'].map((tool_name, index) => ({
      type: 'tool', tool_name, content: `Résultat ${tool_name}`,
      ...(identity === 'legacy' ? {} : { [identity]: `call-${index}` }),
      tool_arguments: { file: 'nextcloud://image.png' },
      tool_result: { ok: true },
      execution_time: 2, cost: 0.1, success: true,
    }))
    let live = emptyAIResult()
    // A slow generation publishes a pending checkpoint. Faster reads may first
    // appear in a completed snapshot. Each then also arrives over WebSocket.
    const pending = { ...completed[0], content: "En cours d'exécution…", execution_time: 0, cost: 0 }
    live = reconcileAIResult(live, { ...emptyAIResult(), messages: [pending] })
    for (let index = 0; index < completed.length; index++) {
      const snapshot = { ...emptyAIResult(), messages: completed.slice(0, index + 1) }
      live = reconcileAIResult(live, snapshot)
      const { tool_arguments, tool_result, ...projected } = completed[index]
      live = appendAIMessage(live, projected)
      if (identity !== 'legacy') assert.equal(live.messages.length, index + 1)
    }
    const terminal = { ...emptyAIResult(), messages: completed, result: 'Terminé' }
    live = finalizeAIResult(live, terminal)
    live = reconcileAIResult(live, terminal)
    const displayed = reconcileAIResult(terminal, live)
    assert.deepEqual(displayed.messages, completed)
    assert.deepEqual(finalizeAIResult(displayed, terminal).messages, completed)
  })
}

test('tool updates replace content and retain stripped details without double counting', () => {
  const completed = {
    type: 'tool', tool_name: 'any_external_tool', tool_call_external_id: 'call-1',
    tool_arguments: { query: 'demo' }, tool_result: { ok: true },
    content: 'Résultat', execution_time: 3, cost: 0.2,
  }
  const baseline = appendAIMessage(emptyAIResult(), completed)
  const projected = {
    type: 'tool', tool_name: completed.tool_name, tool_call_external_id: 'call-1',
    content: 'Résultat', execution_time: 3, cost: 0.2,
  }
  const updated = appendAIMessage(baseline, projected)
  assert.equal(updated.messages.length, 1)
  assert.equal(updated.messages[0].content, 'Résultat')
  assert.deepEqual(updated.messages[0].tool_arguments, completed.tool_arguments)
  assert.deepEqual(updated.messages[0].tool_result, completed.tool_result)
  assert.equal(updated.cost, 0.2)
  assert.equal(updated.execution_time, 3)
  assert.equal(baseline.messages[0], completed)
  const longOutput = { ...completed, content: 'x'.repeat(10_000) }
  const full = { ...baseline, messages: [longOutput] }
  const bounded = { ...projected, content: longOutput.content.slice(0, 8_000) }
  assert.equal(appendAIMessage(full, bounded).messages[0].content.length, 10_000)
  assert.equal(finalizeAIResult(full, { ...baseline, messages: [bounded] }).messages[0].content.length, 10_000)
})

test('distinct invocations and retries with identical content remain separate', () => {
  const base = { type: 'tool', tool_name: 'image_read', content: 'Même résultat' }
  const messages = [
    { ...base, tool_call_external_id: 'call-1', stream_id: 'stream-1', tool_retry_number: 1 },
    { ...base, tool_call_external_id: 'call-1', stream_id: 'stream-1', tool_retry_number: 2 },
    { ...base, tool_call_external_id: 'call-2', stream_id: 'stream-2' },
  ]
  let result = emptyAIResult()
  for (const message of messages) result = appendAIMessage(result, message)
  assert.equal(result.messages.length, 3)
  const snapshot = { ...emptyAIResult(), messages }
  assert.equal(reconcileAIResult(result, snapshot).messages.length, 3)
  assert.equal(finalizeAIResult(result, snapshot).messages.length, 3)
  // An authoritative legacy trace can also contain two real identical calls.
  const legacy = { ...emptyAIResult(), messages: [base, { ...base }] }
  assert.equal(finalizeAIResult(result, legacy).messages.length, 2)
})

test('an identified tool failure replaces its pending card even with a shorter result', () => {
  const pending = {
    type: 'tool', tool_name: 'file_read', tool_call_external_id: 'call-1',
    content: 'En cours de lecture du fichier', success: true,
  }
  const failed = { ...pending, content: 'Erreur', success: false }
  const result = appendAIMessage(appendAIMessage(emptyAIResult(), pending), failed)
  assert.equal(result.messages.length, 1)
  assert.equal(result.messages[0].content, 'Erreur')
  assert.equal(result.success, false)
})

test('Hermes thinking snapshots replace the checkpoint already received over HTTP', () => {
  const thought = {
    type: 'tool', tool_name: 'thinking', stream_id: 'hermes:thought:1',
    stream_mode: 'snapshot', content: '**Clarifying image generation requirements**',
    execution_time: 2, cost: 0.1,
  }
  let live = reconcileAIResult(emptyAIResult(), {
    ...emptyAIResult(), messages: [thought], execution_time: 2, cost: 0.1,
  })
  live = appendAIMessage(live, thought)
  assert.deepEqual(live.messages.map(m => m.content), [thought.content])
  assert.equal(live.execution_time, 2)
  assert.equal(live.cost, 0.1)
  const complete = { ...thought, content: `${thought.content}\n\nInspecting available tools.` }
  live = appendAIMessage(live, complete)
  live = appendAIMessage(live, thought) // Delayed shorter projection.
  assert.deepEqual(live.messages.map(m => m.content), [complete.content])
  // Identical reasoning in a distinct semantic block must remain visible.
  const distinct = { ...complete, stream_id: 'hermes:thought:2' }
  assert.deepEqual(appendAIMessage(live, distinct).messages.map(m => m.stream_id), [complete.stream_id, distinct.stream_id])
})

test('the terminal trace repairs legacy HTTP/WebSocket thinking duplicates from task 76634f05', () => {
  const messages = [
    { type: 'tool', tool_name: 'thinking', content: '**Clarifying image generation requirements**' },
    { type: 'tool', tool_name: 'file_schemes', tool_call_external_id: 'call-1', content: 'Available schemes' },
    { type: 'tool', tool_name: 'thinking', content: '**Planning exact image generation without resizing**' },
    { type: 'tool', tool_name: 'image_generate', tool_call_external_id: 'call-2', content: 'Image generated' },
    { type: 'text', content: 'La génération disponible a produit une image en1200 ×896 pixels.' },
    { type: 'tool', tool_name: 'thinking', content: '**Assessing image resizing limitations**\n\n**Recognizing exact image size as unachievable**' },
    { type: 'text', content: ' nextcloud://robot_humanoide_football_640x480.png' },
  ]
  let live = emptyAIResult()
  for (let index = 0; index < messages.length; index++) {
    live = reconcileAIResult(live, { ...emptyAIResult(), messages: messages.slice(0, index + 1) })
    live = appendAIMessage(live, messages[index])
  }
  const terminal = { ...emptyAIResult(), messages }
  const final = finalizeAIResult(live, terminal)
  assert.deepEqual(final.messages.map(m => m.content), messages.map(m => m.content))
  assert.deepEqual(finalizeAIResult(final, terminal).messages, final.messages)
  // The HTTP terminal Task must also repair the buffer when its live terminal
  // event was missed, and when the detail view merges it with stale live data.
  const task = { status: 'SUCCESS', execution_result: terminal }
  assert.deepEqual(reconcileTaskAIResult(task, live).messages, final.messages)
  assert.deepEqual(reconcileTaskAIResult(task, final).messages, final.messages)
})

test('cumulative text snapshots replace an HTTP baseline while delta streams still append', () => {
  const message = { type: 'text', stream_id: 'hermes:text:1', stream_mode: 'snapshot', content: 'Bon' }
  const baseline = { ...emptyAIResult(), messages: [message], result: 'Bon' }
  const replayed = appendAIMessage(baseline, message)
  const completed = appendAIMessage(replayed, { ...message, content: 'Bonjour' })
  assert.deepEqual(completed.messages.map(m => m.content), ['Bonjour'])
  assert.equal(completed.result, 'Bonjour')
})
