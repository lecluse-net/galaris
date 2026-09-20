import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyVoiceTranscriptionEvent,
  conversationRoundId,
  conversationTimelineEntryText,
  conversationTimelineEntries,
  conversationTimelineRenderKey,
  mergeChatMessages,
  loadMessageActivitySnapshot,
  mergeConversationActivity,
  orderChatMessages,
  reconcileLiveRoundFromActivity,
  reconcileLiveRoundFromActivitySnapshot,
  reconcileVoiceTranscriptions,
  shouldShowLiveConversationRound,
  startLiveConversationRound,
} from './liveState.ts'

const emptyResult = {
  prompt: '',
  system_prompt: '',
  messages: [],
  execution_time: 0,
  result: '',
  cost: 0,
  tools_used: [],
  success: true,
}

function liveRound(overrides = {}) {
  return {
    room_id: 'room-1',
    round_id: 'round-live',
    topic_id: null,
    active: true,
    success: true,
    last_sequence: 4,
    ai_result: emptyResult,
    ...overrides,
  }
}

function activity(id, status) {
  return {
    id,
    response_message_id: null,
    topic_id: null,
    status,
    effect_started: false,
    tools_used: [],
    execution_time: 0,
    cost: 0,
    process_started: false,
    created_at: '2026-08-24T10:00:00Z',
    finished_at: null,
  }
}

test('message reads complete before activity reads, without publishing a half snapshot', async () => {
  const messages = Promise.withResolvers()
  const lineage = Promise.withResolvers()
  const calls = []
  let published = false
  const snapshot = loadMessageActivitySnapshot(
    () => { calls.push('messages'); return messages.promise },
    () => { calls.push('activity'); return lineage.promise },
  ).then(value => { published = true; return value })
  assert.deepEqual(calls, ['messages'])
  messages.resolve([{ id: 'durable' }])
  await Promise.resolve()
  assert.deepEqual(calls, ['messages', 'activity'])
  assert.equal(published, false)
  lineage.resolve([{ id: 'round-live', response_message_id: 'durable' }])
  assert.deepEqual(await snapshot, [
    [{ id: 'durable' }], [{ id: 'round-live', response_message_id: 'durable' }],
  ])
})

test('a stale activity response cannot duplicate an already linked live response', () => {
  const current = [{ ...activity('round-live', 'SUCCEEDED'), response_message_id: 'durable' }]
  const stale = [activity('round-live', 'RUNNING')]
  const merged = mergeConversationActivity(current, stale)
  const entries = conversationTimelineEntries('room-1', [{ id: 'durable' }], merged, liveRound())
  assert.equal(entries.length, 1)
  assert.equal(entries[0].key, 'response:round-live')
  assert.equal(stale[0].response_message_id, null)
  assert.equal(mergeConversationActivity(current, [{ ...stale[0], response_message_id: 'new' }])[0].response_message_id, 'new')
  assert.deepEqual(mergeConversationActivity(current, []), [])
})

test('a stale HTTP refresh cannot hide or replace a streamed round', () => {
  const current = liveRound()
  const createRound = roundId => liveRound({ round_id: roundId, last_sequence: -1 })

  assert.equal(
    reconcileLiveRoundFromActivity(current, 'room-1', [], false, createRound),
    current,
  )
  assert.equal(
    reconcileLiveRoundFromActivity(
      current,
      'room-1',
      [activity('older-round', 'RUNNING')],
      false,
      createRound,
    ),
    current,
  )
})

test('a pending round is visible before the runtime starts producing content', () => {
  const reconciled = reconcileLiveRoundFromActivity(
    null,
    'room-1',
    [activity('round-pending', 'PENDING')],
    true,
    roundId => liveRound({ round_id: roundId, last_sequence: -1 }),
  )

  assert.equal(reconciled?.round_id, 'round-pending')
  assert.equal(reconciled?.active, true)
})

test('a newer pending round cannot replace the round that is already streaming', () => {
  const current = liveRound()
  const reconciled = reconcileLiveRoundFromActivity(
    current,
    'room-1',
    [activity('round-pending', 'PENDING'), activity('round-live', 'RUNNING')],
    true,
    roundId => liveRound({ round_id: roundId, last_sequence: -1 }),
  )

  assert.equal(reconciled, current)
})

test('a delayed start event cannot erase streamed reflection fragments', () => {
  const progressed = liveRound({
    last_sequence: 2,
    ai_result: {
      ...emptyResult,
      messages: [{
        type: 'tool',
        tool_name: 'thinking',
        stream_id: 'reasoning:1',
        content: 'Réflexion déjà visible',
      }],
    },
  })

  assert.equal(
    startLiveConversationRound(progressed, 'room-1', 'round-live', 0),
    progressed,
  )
})

test('the rendered timeline identity changes for a room or new block, not a stream fragment', () => {
  const round = liveRound({ round_id: 'round-scroll' })
  const first = conversationTimelineEntries('room-1', [], [], round)
  const streamed = conversationTimelineEntries(
    'room-1',
    [],
    [],
    liveRound({
      round_id: 'round-scroll',
      ai_result: {
        ...emptyResult,
        messages: [{ type: 'text', content: 'Texte reçu' }],
      },
    }),
  )
  const nextMessage = conversationTimelineEntries(
    'room-1',
    [{ id: 'message-2' }],
    [],
    null,
  )

  assert.equal(
    conversationTimelineRenderKey('room-1', first),
    conversationTimelineRenderKey('room-1', streamed),
  )
  assert.notEqual(
    conversationTimelineRenderKey('room-1', streamed),
    conversationTimelineRenderKey('room-1', nextMessage),
  )
  assert.notEqual(
    conversationTimelineRenderKey('room-1', nextMessage),
    conversationTimelineRenderKey('room-2', nextMessage),
  )
})

test('a live round keeps the topic announced by the runtime', () => {
  const started = startLiveConversationRound(
    null,
    'room-1',
    'round-topic',
    0,
    'topic-1',
  )

  assert.equal(started.topic_id, 'topic-1')
})

test('an explicit reconnect catch-up may close a missed terminal event', () => {
  const current = liveRound()
  const reconciled = reconcileLiveRoundFromActivity(
    current,
    'room-1',
    [],
    true,
    roundId => liveRound({ round_id: roundId }),
  )

  assert.deepEqual(reconciled, { ...current, active: false })
})

test('a stable durable snapshot closes a round when the finished event was missed', () => {
  const current = liveRound()
  const reconciled = reconcileLiveRoundFromActivitySnapshot(
    current,
    'room-1',
    [activity('round-live', 'SUCCEEDED')],
    7,
    7,
    roundId => liveRound({ round_id: roundId }),
  )

  assert.deepEqual(reconciled, { ...current, active: false })
})

test('a snapshot cannot close a round after newer runtime progress arrived', () => {
  const current = liveRound()
  const reconciled = reconcileLiveRoundFromActivitySnapshot(
    current,
    'room-1',
    [activity('round-live', 'SUCCEEDED')],
    7,
    8,
    roundId => liveRound({ round_id: roundId }),
  )

  assert.equal(reconciled, current)
})

test('a durable message atomically replaces its optimistic counterpart', () => {
  const optimistic = {
    id: 'pending:client-1',
    external_id: 'client-1',
    text: 'Bonjour',
  }
  const durable = {
    id: 'message-1',
    external_id: 'client-1',
    text: 'Bonjour',
  }

  assert.deepEqual(mergeChatMessages([optimistic], [durable]), [durable])
})

test('a human voice placeholder stays until its durable transcription is loaded', () => {
  const sender = { external_id: 'nicolas', display_name: 'Nicolas', is_ai: false }
  const started = applyVoiceTranscriptionEvent([], {
    data: {
      room_id: 'room-1',
      transcription_id: 'transcription-1',
      status: 'started',
      started_at: '2026-08-30T12:00:00Z',
    },
  }, sender)

  assert.equal(started.length, 1)
  assert.equal(started[0].sender, sender)
  assert.equal(started[0].message_id, null)
  assert.equal(
    conversationTimelineEntries('room-1', [], [], null, started).at(-1).key,
    'voice-transcription:transcription-1',
  )

  const completed = applyVoiceTranscriptionEvent(started, {
    data: {
      room_id: 'room-1',
      transcription_id: 'transcription-1',
      status: 'completed',
      message_id: 'message-1',
    },
  }, sender)
  assert.equal(reconcileVoiceTranscriptions(completed, []).length, 1)
  assert.deepEqual(
    reconcileVoiceTranscriptions(completed, [{ id: 'message-1' }]),
    [],
  )
})

test('a failed voice transcription removes its human placeholder', () => {
  const started = applyVoiceTranscriptionEvent([], {
    data: {
      room_id: 'room-1',
      transcription_id: 'transcription-1',
      status: 'started',
    },
  }, null)

  assert.deepEqual(applyVoiceTranscriptionEvent(started, {
    data: {
      room_id: 'room-1',
      transcription_id: 'transcription-1',
      status: 'failed',
    },
  }, null), [])
})

test('an optimistic question remains before a response regardless of browser clock skew', () => {
  const historical = { id: 'before', created_at: '2026-08-24T10:00:00Z' }
  const optimistic = {
    id: 'pending:question',
    created_at: '2026-08-24T10:00:10Z',
    optimistic_after_id: historical.id,
  }
  const response = { id: 'response', created_at: '2026-08-24T10:00:05Z' }
  const compare = (left, right) => Date.parse(left.created_at) - Date.parse(right.created_at)

  assert.deepEqual(
    orderChatMessages([historical, optimistic, response], compare).map(message => message.id),
    ['before', 'pending:question', 'response'],
  )
})

test('the terminal response has no gap before its durable message is rendered', () => {
  const terminal = liveRound({
    active: false,
    ai_result: { ...emptyResult, result: 'Réponse complète' },
  })

  assert.equal(
    shouldShowLiveConversationRound(
      terminal,
      'room-1',
      [activity('round-live', 'SUCCEEDED')],
      [],
    ),
    true,
  )
})

test('the durable response atomically replaces the live response even before finished', () => {
  const responseActivity = {
    ...activity('round-live', 'SUCCEEDED'),
    response_message_id: 'response-1',
  }
  const response = { id: 'response-1' }

  assert.equal(
    shouldShowLiveConversationRound(
      liveRound({ ai_result: { ...emptyResult, result: 'Réponse complète' } }),
      'room-1',
      [responseActivity],
      [response],
    ),
    false,
  )
  assert.equal(
    shouldShowLiveConversationRound(
      liveRound({ active: false, ai_result: { ...emptyResult, result: 'Réponse complète' } }),
      'room-1',
      [responseActivity],
      [response],
    ),
    false,
  )
})

test('the durable handoff keeps the accumulated live result on the same timeline entry', () => {
  const terminal = liveRound({
    active: false,
    ai_result: { ...emptyResult, result: 'ABC' },
  })
  const liveEntries = conversationTimelineEntries(
    'room-1',
    [],
    [activity('round-live', 'SUCCEEDED')],
    terminal,
  )
  const responseActivity = {
    ...activity('round-live', 'SUCCEEDED'),
    response_message_id: 'response-1',
    message_ids: ['question-1'],
  }
  const durableEntries = conversationTimelineEntries(
    'room-1',
    [{ id: 'question-1' }, { id: 'response-1', text: 'C' }],
    [responseActivity],
    terminal,
  )

  assert.equal(liveEntries.at(-1).key, 'response:round-live')
  assert.equal(durableEntries.at(-1).key, liveEntries.at(-1).key)
  assert.equal(durableEntries[0].key, 'message:question-1')
  assert.equal(durableEntries.at(-1).message.id, 'response-1')
  assert.notEqual(durableEntries.at(-1).liveRound, terminal)
  assert.equal(durableEntries.at(-1).liveRound.active, false)
  assert.equal(durableEntries.at(-1).liveRound.ai_result.result, 'ABC')
})

test('a durable response remains visible when its stale live handoff is empty', () => {
  const entry = {
    key: 'response:round-live',
    message: { id: 'response-1', text: 'Réponse persistée' },
    liveRound: liveRound({ active: false }),
    pendingTranscription: null,
  }

  assert.equal(conversationTimelineEntryText(entry), 'Réponse persistée')
})

test('a live response is rendered before its durable message exists', () => {
  const entry = {
    key: 'response:round-live',
    message: null,
    liveRound: liveRound({
      ai_result: {
        ...emptyResult,
        messages: [{ type: 'text', content: 'Réponse streamée' }],
      },
    }),
    pendingTranscription: null,
  }

  assert.equal(conversationTimelineEntryText(entry), 'Réponse streamée')
})

test('a durable response ends a still-active live presentation during handoff', () => {
  const activeRound = liveRound({
    active: true,
    ai_result: { ...emptyResult, result: 'Réponse complète' },
  })
  const responseActivity = {
    ...activity('round-live', 'SUCCEEDED'),
    response_message_id: 'response-1',
  }

  const entry = conversationTimelineEntries(
    'room-1',
    [{ id: 'response-1', text: 'Réponse complète' }],
    [responseActivity],
    activeRound,
  ).at(-1)

  assert.equal(entry.liveRound.active, false)
  assert.equal(activeRound.active, true)
})

test('the execution trace keeps its round identity during the live handoff', () => {
  const current = liveRound()
  const durableActivity = activity('round-live', 'SUCCEEDED')

  assert.equal(conversationRoundId(undefined, current), 'round-live')
  assert.equal(conversationRoundId(durableActivity, null), 'round-live')
})

test('a successful terminal round without visible output leaves no empty live bubble', () => {
  assert.equal(
    shouldShowLiveConversationRound(
      liveRound({ active: false }),
      'room-1',
      [activity('round-live', 'SUCCEEDED')],
      [],
    ),
    false,
  )
})
