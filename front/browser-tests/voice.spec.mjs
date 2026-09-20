import { test, expect, mount, jsonRoute } from './fixtures.mjs'

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
