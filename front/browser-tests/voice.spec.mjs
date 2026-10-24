import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

test.use({ permissions: ['microphone'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } })

async function voice(page) {
  await jsonRoute(page, '**/api/chat/rooms/room-a/calls/status', { available: true, ice_servers: [], ice_transport_policy: 'all' })
  await mount(page, 'app/chat/components/VoiceCallPanel.vue', { props: { roomId: 'room-a', language: 'en', mobile: true } })
  // Observe real browser tracks; Chromium supplies synthetic audio, not the host mic.
  await page.evaluate(() => {
    const acquire = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    window.voiceTracks = []
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await acquire(constraints)
      window.voiceTracks.push(...stream.getTracks())
      return stream
    }
  })
}
const stopped = page => page.evaluate(() => window.voiceTracks.length > 0 && window.voiceTracks.every(track => track.readyState === 'ended'))

const audioTurn = {
  id: 'synthetic-audio-turn', sequence: 1, status: 'RUNNING', started_at: '2026-01-01T10:00:00Z',
  transcript: 'Synthetic audio input', assistant_response: null, effective_objective: null,
  topic_id: null, llm_call_count: 0, execution_result: null,
}
const audioConversation = {
  id: 'synthetic-audio-session', agent_id: 7, agent_name: 'Alice Example', caller_name: 'Synthetic caller',
  status: 'ACTIVE', transport_kind: 'matrix', room_id: 'synthetic-audio-room', language: 'en',
}

async function audioAdministration(page, privileges = ['VOICE_HISTORY_ACCESS', 'VOICE_HISTORY_CONTROL']) {
  await jsonRoute(page, '**/api/voice/conversations/turns/*', audioTurn)
  await page.route('**/api/voice/conversations/turns/*/deletion', route => route.fulfill({ status: 404, json: {} }))
  await mount(page, 'app/voice/components/VoiceConversationDetail.vue', {
    props: { conversation: audioConversation, turn: audioTurn }, privileges,
  })
}

test('audio administration honors edit permissions and confirms force hangup with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  let requests = 0
  await page.route('**/api/voice/conversations/turns/*/force-hangup', route => {
    requests += 1
    return route.fulfill({ json: { revoked: true, local_audio_stopped: false } })
  })
  await audioAdministration(page, ['VOICE_HISTORY_ACCESS'])
  const hangup = page.getByRole('button', { name: 'Force hangup', exact: true })
  await expect(hangup).toHaveCount(0)
  await setPrivileges(page, ['VOICE_HISTORY_ACCESS', 'VOICE_HISTORY_CONTROL'])
  await hangup.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(requests).toBe(0)
  await hangup.click()
  await page.getByRole('dialog').getByRole('button', { name: 'Force hangup', exact: true }).click()
  await expect.poll(() => requests).toBe(1)
  await expect(page.getByText('Execution revoked; local teardown pending. You can retry.', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'stopped').length)).toBe(1)
  await page.screenshot({ path: '/artifacts/audio-hangup-mobile.png' })
})

test('a pending audio deletion retains content and follows recovery across temporary API failures', async ({ page }) => {
  await audioAdministration(page)
  let polls = 0
  await page.route('**/api/voice/conversations/turns/*/deletion', route => {
    polls += 1
    if (polls === 2) return route.fulfill({ status: 503, json: {} })
    return route.fulfill({ json: { status: polls >= 3 ? 'COMPLETED' : 'PENDING', last_error: 'Synthetic transport cleanup' } })
  })
  await page.route('**/api/voice/conversations/turns/synthetic-audio-turn', route => {
    expect(route.request().method()).toBe('DELETE')
    return route.fulfill({ status: 202, json: { detail: 'Pending' } })
  })
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByText('Deletion requested: audio shutdown and cleanup in progress.')).toBeVisible()
  await expect(page.getByText('Synthetic audio input', { exact: true })).toBeVisible()
  await expect(page.getByText('Synthetic transport cleanup', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'deleted').length), { timeout: 10000 }).toBe(1)
  expect(polls).toBe(3)
})

test('late audio deletion responses cannot remove another turn after an A-B-A navigation', async ({ page }) => {
  await audioAdministration(page)
  let release
  await page.route('**/api/voice/conversations/turns/synthetic-audio-turn', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 204 })
  })
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(turn => window.testApp.setProps({ turn: { ...turn, id: 'synthetic-other-turn' } }), audioTurn)
  await expect(page.getByText('ID: synthetic-other-turn', { exact: true })).toBeVisible()
  await page.evaluate(turn => window.testApp.setProps({ turn }), audioTurn)
  await expect(page.getByText('ID: synthetic-audio-turn', { exact: true })).toBeVisible()
  release()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true })).toBeEnabled()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'deleted'))).toEqual([])
})

test('cancelling a connecting call releases the microphone and stops a late server call', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const requests = []
  await page.route('**/api/chat/rooms/room-a/calls', async route => {
    const body = route.request().postDataJSON()
    expect(body.type).toBe('offer')
    expect(body.sdp).toContain('m=audio')
    requests.push('start')
    await pending
    await route.fulfill({ json: { call_id: 'late-call', sdp: '', type: 'answer' } })
  })
  await page.route('**/api/chat/rooms/room-a/calls/late-call', route => {
    expect(route.request().method()).toBe('DELETE')
    requests.push('stop')
    return route.fulfill({ status: 204 })
  })
  await voice(page)
  try {
    await page.getByRole('button', { name: /call/i }).click()
    await expect.poll(() => requests).toEqual(['start'])
    await page.getByRole('button', { name: /hang up/i }).click()
    await expect.poll(() => stopped(page)).toBe(true)
  } finally { release() }
  await expect.poll(() => requests).toEqual(['start', 'stop'])
  await expect(page.getByRole('button', { name: /hang up/i })).toHaveCount(0)
})

test('a real WebRTC offer trickles candidates and server termination closes local media', async ({ page }) => {
  const candidates = []
  await page.route('**/api/chat/rooms/room-a/calls', async route => {
    const offer = route.request().postDataJSON()
    const answer = await page.evaluate(async offer => {
      const remote = new RTCPeerConnection({ iceServers: [] })
      window.remoteTestPeer = remote
      await remote.setRemoteDescription({ type: offer.type, sdp: offer.sdp })
      const answer = await remote.createAnswer()
      await remote.setLocalDescription(answer)
      return { call_id: 'call-a', type: answer.type, sdp: answer.sdp }
    }, offer)
    await route.fulfill({ json: answer })
  })
  await page.route('**/api/chat/rooms/room-a/calls/call-a/candidates', route => {
    const payload = route.request().postDataJSON()
    candidates.push(...payload.candidates)
    return route.fulfill({ status: 204 })
  })
  await voice(page)
  try {
    await page.getByRole('button', { name: /call/i }).click()
    await expect.poll(() => candidates.some(item => typeof item.candidate === 'string')).toBe(true)
    await expect(page.getByRole('button', { name: /mute microphone/i })).toBeVisible()
    await page.getByRole('button', { name: /mute microphone/i }).click()
    await expect.poll(() => page.evaluate(() => window.voiceTracks.every(track => !track.enabled))).toBe(true)
    await page.evaluate(() => window.testApp.setProps({ endedCallId: 'call-a' }))
    await expect.poll(() => stopped(page)).toBe(true)
    await expect(page.getByRole('button', { name: /hang up/i })).toHaveCount(0)
    await page.evaluate(() => window.testApp.setProps({ stoppingCallId: 'call-a' }))
    await expect(page.getByRole('button')).toBeDisabled()
  } finally { await page.evaluate(() => window.remoteTestPeer?.close()) }
})

test('a rejected extra ICE route does not hang up an established audio call', async ({ page }) => {
  let rejected = false
  let stops = 0
  await page.route('**/api/chat/rooms/room-a/calls', async route => {
    const answer = await page.evaluate(async offer => {
      const remote = new RTCPeerConnection({ iceServers: [] })
      window.remoteTestPeer = remote
      await remote.setRemoteDescription({ type: offer.type, sdp: offer.sdp })
      await remote.setLocalDescription(await remote.createAnswer())
      if (remote.iceGatheringState !== 'complete') {
        await new Promise(resolve => remote.addEventListener('icegatheringstatechange', () => {
          if (remote.iceGatheringState === 'complete') resolve()
        }))
      }
      return { call_id: 'call-a', type: 'answer', sdp: remote.localDescription.sdp }
    }, route.request().postDataJSON())
    await route.fulfill({ json: answer })
  })
  await page.route('**/api/chat/rooms/room-a/calls/call-a/candidates', async route => {
    const payload = route.request().postDataJSON()
    await page.evaluate(async payload => {
      for (const item of payload.candidates ?? [payload]) {
        await window.remoteTestPeer.addIceCandidate(item.candidate ? {
          candidate: item.candidate, sdpMid: item.sdp_mid, sdpMLineIndex: item.sdp_m_line_index,
        } : null)
      }
    }, payload)
    // A working route exists before another signaling request is rejected.
    await page.waitForFunction(() => window.remoteTestPeer.connectionState === 'connected')
    if (!rejected) {
      rejected = true
      await route.fulfill({ status: 429, json: { detail: 'Too many requests' } })
    } else await route.fulfill({ status: 204 })
  })
  await page.route('**/api/chat/rooms/room-a/calls/call-a', async route => {
    stops += 1
    await route.fulfill({ status: 204 })
  })
  await voice(page)
  try {
    await page.getByRole('button', { name: /call/i }).click()
    await expect.poll(() => rejected).toBe(true)
    await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'error'))).toBe(true)
    await expect(page.getByRole('button', { name: /mute microphone/i })).toBeVisible()
    expect(await stopped(page)).toBe(false)
    expect(stops).toBe(0)
    await page.getByRole('button', { name: /hang up/i }).click()
    await expect.poll(() => stopped(page)).toBe(true)
    await expect.poll(() => stops).toBe(1)
  } finally { await page.evaluate(() => window.remoteTestPeer?.close()) }
})
