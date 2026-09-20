import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as voiceCall from './voiceCall.ts'
import { deferred } from '../../test-support/load-typescript.mjs'

const { descriptor } = parse(readFileSync(new URL('./components/VoiceCallPanel.vue', import.meta.url), 'utf8'))
const code = ts.transpileModule(compileScript(descriptor, { id: 'voice-playback' }).content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

async function setup(t, play = async () => {}) {
  let connection, cleanup
  const events = []
  const track = { kind: 'audio', stop() {} }
  class FakeStream {
    constructor(tracks = [track]) { this.tracks = tracks }
    getTracks() { return this.tracks }
    getAudioTracks() { return this.tracks }
  }
  class FakePeer {
    constructor() { connection = this }
    addTrack() {}
    async createOffer() { return { sdp: 'offer' } }
    async setLocalDescription() {}
    async setRemoteDescription() {}
    close() {}
  }
  for (const [name, value] of Object.entries({
    navigator: {
      userAgent: 'Mozilla/5.0 (Linux; Android 15; Pixel 9)',
      mediaDevices: { getUserMedia: async () => new FakeStream() },
    },
    RTCPeerConnection: FakePeer,
    MediaStream: FakeStream,
    AudioContext: class { constructor() { assert.fail('Android playback must not open a second audio output') } },
  })) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name)
    Object.defineProperty(globalThis, name, { configurable: true, value })
    t.after(() => {
      if (original) Object.defineProperty(globalThis, name, original)
      else delete globalThis[name]
    })
  }
  const dependencies = {
    vue: { ...vue, onBeforeUnmount(fn) { cleanup = fn } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    '../voiceCall': voiceCall,
    '../services/chatService': { chatService: {
      callStatus: async () => ({ available: true, ice_servers: [] }),
      startCall: async () => ({ call_id: 'call-1', sdp: 'answer', type: 'answer' }),
      stopCall: async () => {},
    } },
  }
  const exports = {}
  new Function('require', 'exports', code)(name => {
    assert.ok(name in dependencies, name)
    return dependencies[name]
  }, exports)
  const scope = vue.effectScope()
  const props = vue.reactive({ roomId: 'room-1', language: 'fr' })
  const state = scope.run(() => exports.default.setup(props, {
    expose() {}, emit: (...args) => events.push(args),
  }))
  const audio = vue.markRaw({ srcObject: null, muted: true, volume: 0, play, pause() {} })
  state.remoteAudio.value = audio
  t.after(() => { cleanup(); scope.stop() })
  await state.start()
  const remote = new FakeStream()
  return { state, audio, events, remote, connection, track }
}

test('Android remote tracks play through the native element at device-controlled volume', async t => {
  let played = 0
  const c = await setup(t, async function () {
    assert.equal(this.srcObject, c.remote)
    assert.equal(this.muted, false)
    assert.equal(this.volume, 1)
    played++
  })
  c.connection.ontrack({ streams: [c.remote], track: c.track })
  await vue.nextTick()
  assert.equal(played, 1)
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.events.some(([name]) => name === 'error'), false)
})

test('blocked playback can be retried synchronously from a tap without restarting the call', async t => {
  let attempts = 0
  const c = await setup(t, () => {
    attempts++
    return attempts === 1
      ? Promise.reject(new DOMException('User gesture required', 'NotAllowedError'))
      : Promise.resolve()
  })
  await c.state.playRemoteStream(c.remote)
  assert.equal(c.state.playbackNeedsGesture.value, true)
  assert.equal(c.events.at(-1)[0], 'error')
  c.state.retryRemoteAudio()
  assert.equal(attempts, 2, 'play must run before the user gesture expires')
  await vue.nextTick()
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.state.callId.value, 'call-1')
  assert.equal(c.audio.srcObject, c.remote)
})

test('hangup clears the output and ignores a late playback rejection', async t => {
  const pending = deferred()
  const c = await setup(t, () => pending.promise)
  const playback = c.state.playRemoteStream(c.remote)
  await c.state.stop()
  assert.equal(c.audio.srcObject, null)
  pending.reject(new DOMException('Playback interrupted', 'AbortError'))
  await playback
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.events.some(([name]) => name === 'error'), false)
  c.connection.ontrack({ streams: [c.remote], track: c.track })
  assert.equal(c.audio.srcObject, null, 'a late track cannot restart a closed call')
})

test('streamless WebRTC audio tracks are attached to a native stream', async t => {
  const c = await setup(t)
  c.connection.ontrack({ streams: [], track: c.track })
  await vue.nextTick()
  assert.deepEqual(c.audio.srcObject.getAudioTracks(), [c.track])
})
