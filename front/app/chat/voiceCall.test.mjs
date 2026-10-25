import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createTrickleIceSender,
  hangUpLocalFirst,
  iceCandidatePayload,
  peerConfiguration,
  reconcileRealtimeCall,
} from './voiceCall.ts'

globalThis.window ??= globalThis

test('the browser peer receives every authenticated ICE server from the API', () => {
  assert.deepEqual(
    peerConfiguration({
      available: true,
      ice_servers: [
        { urls: ['stun:turn.example.test:3478'], username: null, credential: null },
        {
          urls: ['turn:turn.example.test:3478?transport=udp'],
          username: '1600:galaris:user:17',
          credential: 'credential',
        },
      ],
    }),
    {
      iceServers: [
        {
          urls: ['stun:turn.example.test:3478'],
          username: undefined,
          credential: undefined,
        },
        {
          urls: ['turn:turn.example.test:3478?transport=udp'],
          username: '1600:galaris:user:17',
          credential: 'credential',
        },
      ],
    },
  )
})

test('hangup closes the local media before waiting for the server', async () => {
  const events = []
  let releaseRemote = () => {}
  const remoteStopped = new Promise(resolve => { releaseRemote = resolve })

  const pending = hangUpLocalFirst(
    () => events.push('local-closed'),
    async () => {
      events.push('remote-requested')
      await remoteStopped
    },
  )

  assert.deepEqual(events, ['local-closed', 'remote-requested'])
  releaseRemote()
  await pending
})

test('the terminal realtime event immediately clears the matching active call', () => {
  assert.deepEqual(
    reconcileRealtimeCall(
      { call_id: 'call-7', started_at: 1 },
      'call-7',
      null,
      { data: { room_id: 'room-1', call_id: 'call-7', status: 'ended' } },
    ),
    { activeCall: null, stoppingCallId: null, endedCallId: 'call-7' },
  )
})

test('a terminal event cannot clear another active call', () => {
  const activeCall = { call_id: 'call-8', started_at: 2 }
  assert.deepEqual(
    reconcileRealtimeCall(
      activeCall,
      null,
      null,
      { data: { room_id: 'room-1', call_id: 'call-7', status: 'ended' } },
    ),
    { activeCall, stoppingCallId: null, endedCallId: 'call-7' },
  )
})

test('a stopping event keeps the call visible as closing until it ends', () => {
  const activeCall = { call_id: 'call-7', started_at: 3 }
  assert.deepEqual(
    reconcileRealtimeCall(
      activeCall,
      null,
      null,
      { data: { room_id: 'room-1', call_id: 'call-7', status: 'stopping' } },
    ),
    { activeCall, stoppingCallId: 'call-7', endedCallId: null },
  )
})

test('a newly active call clears the previous terminal marker', () => {
  const activeCall = { call_id: 'call-7', started_at: 3 }
  assert.deepEqual(
    reconcileRealtimeCall(
      activeCall,
      'call-7',
      'call-7',
      { data: { room_id: 'room-1', call_id: 'call-7', status: 'active' } },
    ),
    { activeCall, stoppingCallId: null, endedCallId: null },
  )
})

test('mobile ICE candidates are queued until the call exists then sent in order', async () => {
  const sent = []
  const sender = createTrickleIceSender(async (callId, candidates) => {
    sent.push(...candidates.map(candidate => ({ callId, candidate })))
  })
  const host = {
    candidate: 'candidate:host 1 udp 1 192.0.2.10 50000 typ host',
    sdpMid: '0',
    sdpMLineIndex: 0,
  }
  const relay = {
    candidate: 'candidate:relay 1 udp 1 203.0.113.7 47000 typ relay',
    sdpMid: '0',
    sdpMLineIndex: 0,
  }

  await sender.add(host)
  await sender.add(relay)
  await sender.add(null)
  assert.deepEqual(sent, [])

  await sender.bind('call-mobile')

  assert.deepEqual(sent, [
    { callId: 'call-mobile', candidate: iceCandidatePayload(host) },
    { callId: 'call-mobile', candidate: iceCandidatePayload(relay) },
    {
      callId: 'call-mobile',
      candidate: { candidate: null, sdp_mid: null, sdp_m_line_index: null },
    },
  ])
})

test('closing mobile ICE signaling discards candidates gathered afterwards', async () => {
  const sent = []
  const sender = createTrickleIceSender(async (_callId, candidates) => { sent.push(...candidates) })
  await sender.bind('call-mobile')
  sender.close()

  await sender.add({
    candidate: 'candidate:late 1 tcp 1 203.0.113.8 47001 typ relay',
    sdpMid: '0',
    sdpMLineIndex: 0,
  })

  assert.deepEqual(sent, [])
})

test('a burst of ICE routes fits in bounded requests without losing their order', async () => {
  const batches = []
  const sender = createTrickleIceSender(async (_callId, batch) => { batches.push(batch) })
  const candidates = Array.from({ length: 125 }, (_, index) => ({
    candidate: `candidate:${index} 1 udp 1 192.0.2.10 ${50000 + index} typ host`,
    sdpMid: '0', sdpMLineIndex: 0,
  }))
  for (const candidate of candidates) await sender.add(candidate)
  await sender.add(null)
  await sender.bind('call-many-routes')

  assert.equal(batches.length, 3)
  assert.ok(batches.every(batch => batch.length <= 50))
  assert.deepEqual(batches.flat(), [...candidates, null].map(iceCandidatePayload))
})

for (const closeWhileSending of [false, true]) {
  test(`ICE gathered during a pending request is preserved or released on hangup (close=${closeWhileSending})`, async () => {
    const batches = []
    let release
    const firstRequest = new Promise(resolve => { release = resolve })
    const sender = createTrickleIceSender(async (_callId, batch) => {
      batches.push(batch)
      if (batches.length === 1) await firstRequest
    })
    await sender.bind('call-mobile')
    const candidates = Array.from({ length: 110 }, (_, index) => ({
      candidate: `candidate:${index} 1 udp 1 192.0.2.10 ${50000 + index} typ host`,
      sdpMid: '0', sdpMLineIndex: 0,
    }))
    const first = sender.add(candidates[0])
    await Promise.resolve()
    const waiting = candidates.slice(1).map(candidate => sender.add(candidate))
    waiting.push(sender.add(null))
    if (closeWhileSending) sender.close()
    release()
    await Promise.all([first, ...waiting])

    if (closeWhileSending) {
      assert.deepEqual(batches.flat(), [iceCandidatePayload(candidates[0])])
    } else {
      assert.equal(batches.length, 4)
      assert.deepEqual(batches.flat(), [...candidates, null].map(iceCandidatePayload))
    }
  })
}

test('a rejected ICE candidate does not block the following relay candidate', async () => {
  const sent = []
  const sender = createTrickleIceSender(async (_callId, candidates) => {
    sent.push(...candidates.map(candidate => candidate.candidate))
    if (candidates.some(candidate => candidate.candidate?.includes('host'))) throw new Error('host route rejected')
  })
  await sender.bind('call-mobile')

  await assert.rejects(sender.add({
    candidate: 'candidate:host 1 udp 1 192.0.2.10 50000 typ host',
    sdpMid: '0',
    sdpMLineIndex: 0,
  }))
  await sender.add({
    candidate: 'candidate:relay 1 udp 1 203.0.113.7 47000 typ relay',
    sdpMid: '0',
    sdpMLineIndex: 0,
  })

  assert.deepEqual(sent, [
    'candidate:host 1 udp 1 192.0.2.10 50000 typ host',
    'candidate:relay 1 udp 1 203.0.113.7 47000 typ relay',
  ])
})

test('a failed server notification cannot keep local media open', async () => {
  let localClosed = false

  await assert.rejects(
    hangUpLocalFirst(
      () => { localClosed = true },
      async () => { throw new Error('network unavailable') },
    ),
  )

  assert.equal(localClosed, true)
})
