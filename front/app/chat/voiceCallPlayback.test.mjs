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

async function setup(t, play = async () => {}, { android = true, resume, acquire, autoStart = true } = {}) {
  let connection, cleanup
  const events = []
  const contexts = []
  const captures = []
  const preferences = new Map([['galaris.chat.call-audio', '{"volume":0,"handsFree":false}']])
  const track = { kind: 'audio', stopped: false, stop() { this.stopped = true } }
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
    localStorage: { getItem: key => preferences.get(key) ?? null, setItem: (key, value) => preferences.set(key, value) },
    navigator: {
      userAgent: android ? 'Mozilla/5.0 (Linux; Android 16; Synthetic Phone)' : 'Mozilla/5.0 (X11; Linux x86_64)',
      mediaDevices: { getUserMedia: async constraints => {
        if (acquire) await acquire()
        captures.push(constraints)
        return new FakeStream()
      } },
    },
    RTCPeerConnection: FakePeer,
    MediaStream: FakeStream,
    AudioContext: class {
      state = 'suspended'
      destination = {}
      sources = []
      resumes = 0
      constructor(options) { this.options = options; this.capturesAtCreation = captures.length; contexts.push(this) }
      async resume() {
        this.resumes++
        if (resume) await resume(this)
        this.state = 'running'
        this.onstatechange?.()
      }
      createMediaStreamSource(stream) {
        const source = {
          mediaStream: stream, output: null,
          connect(output) { this.output = output },
          disconnect() { this.output = null },
        }
        this.sources.push(source)
        return source
      }
      async close() { this.state = 'closed'; this.onstatechange?.() }
    },
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
  const audio = vue.markRaw({ srcObject: null, muted: true, volume: 1, play, pause() {} })
  state.remoteAudio.value = audio
  t.after(() => { cleanup(); scope.stop() })
  if (autoStart) await state.start()
  const remote = new FakeStream()
  return { state, audio, events, remote, get connection() { return connection }, track, contexts, captures, props }
}

test('Android calls retain one Web Audio output and a silent native consumer', async t => {
  const c = await setup(t, function () { assert.equal(this.muted, true, 'the native WebRTC output must stay silent') })
  assert.equal(c.contexts.length, 1, 'unlock before the remote track arrives')
  const context = c.contexts[0]
  assert.equal(context.resumes, 1)
  c.connection.ontrack({ streams: [c.remote], track: c.track })
  await new Promise(setImmediate)
  assert.equal(context.sources.length, 1)
  assert.equal(context.sources[0].mediaStream, c.remote)
  assert.equal(context.sources[0].output, context.destination)
  assert.equal(c.audio.srcObject, c.remote)
  assert.equal(c.audio.muted, true, 'no parallel native output at full volume')
  await c.state.playRemoteStream(c.remote)
  assert.equal(context.sources.length, 1, 'repeated track delivery cannot double the volume')
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.events.some(([name]) => name === 'error'), false)
})

test('Android Web Audio opens after microphone capture, ignoring obsolete media preferences', async t => {
  const c = await setup(t)
  assert.equal(c.contexts.length, 1)
  assert.equal(c.contexts[0].capturesAtCreation, 1, 'microphone mode must be established before output opens')
  assert.deepEqual(c.contexts[0].options, { latencyHint: 'interactive' })
  await c.state.playRemoteStream(c.remote)
  assert.equal(c.audio.srcObject, c.remote)
  assert.equal(c.audio.muted, true, 'native WebRTC stays silent to preserve the Web Audio workaround')
  assert.equal(c.audio.volume, 1)
  assert.deepEqual(c.captures[0].audio, { autoGainControl: true, echoCancellation: true, noiseSuppression: true })
})

for (const cancel of [false, true]) {
  test(`pending microphone permission cannot open a media-mode output (cancel=${cancel})`, async t => {
    const permission = deferred()
    const c = await setup(t, undefined, { acquire: () => permission.promise, autoStart: false })
    const starting = c.state.start()
    await vue.nextTick()
    assert.equal(c.contexts.length, 0)
    if (cancel) await c.state.stop()
    permission.resolve()
    await starting
    assert.equal(c.contexts.length, cancel ? 0 : 1)
    assert.equal(c.track.stopped, cancel)
    if (!cancel) assert.equal(c.contexts[0].capturesAtCreation, 1)
  })
}

test('other browsers retain native WebRTC playback', async t => {
  let played = 0
  const c = await setup(t, async function () {
    assert.equal(this.srcObject, c.remote)
    assert.equal(this.muted, false)
    assert.equal(this.volume, 1)
    played++
  }, { android: false })
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
  }, { android: false })
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
  const c = await setup(t, () => pending.promise, { android: false })
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

for (const android of [false, true]) {
  test(`streamless WebRTC audio tracks remain playable (Android=${android})`, async t => {
    const c = await setup(t, undefined, { android })
    c.connection.ontrack({ streams: [], track: c.track })
    await new Promise(setImmediate)
    const outputStream = android ? c.contexts[0].sources[0].mediaStream : c.audio.srcObject
    assert.deepEqual(outputStream.getAudioTracks(), [c.track])
  })
}

test('Android playback blockage stays silent and can be resumed from a tap', async t => {
  let blocked = true
  const c = await setup(t, function () { assert.equal(this.muted, true, 'no audible native fallback') }, {
    resume: async () => { if (blocked) throw new DOMException('Gesture required', 'NotAllowedError') },
  })
  await c.state.playRemoteStream(c.remote)
  assert.equal(c.state.playbackNeedsGesture.value, true)
  assert.equal(c.events.at(-1)[0], 'error')
  const context = c.contexts[0]
  blocked = false
  const resumes = context.resumes
  c.state.retryRemoteAudio()
  assert.equal(context.resumes, resumes + 1, 'resume runs synchronously inside the tap')
  await vue.nextTick()
  assert.equal(context.state, 'running')
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.state.callId.value, 'call-1')
  context.state = 'suspended'
  context.onstatechange()
  assert.equal(c.state.playbackNeedsGesture.value, true, 'interruption exposes the resume action')
})

test('Android hangup disconnects output and a late resume cannot revive it', async t => {
  const c = await setup(t)
  const context = c.contexts[0]
  await c.state.playRemoteStream(c.remote)
  const source = context.sources[0]
  const pending = deferred()
  context.state = 'suspended'
  context.resume = () => pending.promise
  const playback = c.state.playRemoteStream(c.remote)
  await c.state.stop()
  assert.equal(source.output, null)
  assert.equal(context.state, 'closed')
  pending.reject(new DOMException('Output closed', 'AbortError'))
  await playback
  assert.equal(c.state.playbackNeedsGesture.value, false)
  assert.equal(c.events.some(([name]) => name === 'error'), false)
  c.connection.ontrack({ streams: [c.remote], track: c.track })
  assert.equal(context.sources.length, 1)
  await c.state.start()
  assert.equal(c.contexts.length, 2, 'a new call opens a fresh output')
})

test('Android reopening retains communication processing and navigation closes the output', async t => {
  const c = await setup(t)
  assert.deepEqual(c.captures[0].audio, { autoGainControl: true, echoCancellation: true, noiseSuppression: true })
  await c.state.stop()
  await c.state.start()
  assert.deepEqual(c.captures[1].audio, { autoGainControl: true, echoCancellation: true, noiseSuppression: true })
  assert.equal(c.contexts[1].capturesAtCreation, 2)
  await c.state.playRemoteStream(c.remote)
  c.props.roomId = 'room-2'
  await vue.nextTick()
  assert.equal(c.contexts[1].state, 'closed')
  assert.equal(c.contexts[1].sources[0].output, null)
})
