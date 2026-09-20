<template>
  <div class="row q-gutter-sm">
    <q-btn
      v-if="stoppingCallId"
      color="negative"
      icon="call_end"
      :label="mobile ? undefined : t('chat.callClosing')"
      :round="mobile"
      :aria-label="t('chat.callClosing')"
      loading
      disable
    />
    <q-btn
      v-else-if="!displayedCallId && !loading"
      color="positive"
      icon="call"
      :label="mobile ? undefined : t('chat.call')"
      :round="mobile"
      :aria-label="t('chat.call')"
      @click="start"
    />
    <q-btn
      v-else-if="!displayedCallId"
      color="negative"
      icon="call_end"
      :label="mobile ? undefined : t('chat.hangup')"
      :round="mobile"
      :aria-label="t('chat.hangup')"
      @click="stop"
    />
    <template v-else>
      <q-btn
        v-if="callId && playbackNeedsGesture"
        color="warning"
        icon="volume_up"
        :label="t('chat.callEnableAudio')"
        @click="retryRemoteAudio"
      />
      <q-btn
        v-if="callId"
        :color="muted ? 'warning' : 'primary'"
        :icon="muted ? 'mic_off' : 'mic'"
        round
        :aria-label="t(muted ? 'chat.callUnmuteMicrophone' : 'chat.callMuteMicrophone')"
        @click="toggleMute"
      />
      <q-btn
        color="negative"
        icon="call_end"
        :label="mobile ? undefined : t('chat.hangup')"
        :round="mobile"
        :aria-label="t('chat.hangup')"
        @click="stop"
      />
    </template>
    <audio ref="remoteAudio" autoplay playsinline />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { chatService } from '../services/chatService'
import {
  createTrickleIceSender,
  hangUpLocalFirst,
  peerConfiguration,
  type TrickleIceSender,
} from '../voiceCall'

const props = defineProps<{
  roomId: string
  language: string
  activeCallId?: string | null
  stoppingCallId?: string | null
  endedCallId?: string | null
  mobile?: boolean
}>()
const emit = defineEmits<{
  error: [error: unknown]
  ended: []
  starting: []
  stopping: [callId: string]
}>()
const { t } = useI18n()
const loading = ref(false)
const muted = ref(false)
const playbackNeedsGesture = ref(false)
const callId = ref<string | null>(null)
const ignoredCallId = ref<string | null>(null)
const displayedCallId = computed(() => {
  if (callId.value) return callId.value
  const activeCallId = props.activeCallId ?? null
  return activeCallId === ignoredCallId.value ? null : activeCallId
})
const remoteAudio = ref<HTMLAudioElement>()
let peer: RTCPeerConnection | null = null
let stream: MediaStream | null = null
let playbackAttempt = 0
let iceSender: TrickleIceSender | null = null
let disconnectTimer: number | null = null
interface StartAttempt {
  controller: AbortController
  pendingStream: MediaStream | null
}
let startAttempt: StartAttempt | null = null

function clearDisconnectTimer(): void {
  if (disconnectTimer === null) return
  window.clearTimeout(disconnectTimer)
  disconnectTimer = null
}

function cleanup(endedCallId: string | null = null): void {
  if (endedCallId) ignoredCallId.value = endedCallId
  callId.value = null
  clearDisconnectTimer()
  const currentPeer = peer
  peer = null
  iceSender?.close()
  iceSender = null
  if (currentPeer) currentPeer.onicecandidate = null
  currentPeer?.close()
  for (const track of stream?.getTracks() ?? []) track.stop()
  stream = null
  muted.value = false
  playbackAttempt += 1
  playbackNeedsGesture.value = false
  if (remoteAudio.value) {
    remoteAudio.value.pause()
    remoteAudio.value.srcObject = null
  }
}

async function playRemoteStream(remoteStream: MediaStream): Promise<void> {
  const audio = remoteAudio.value
  if (!audio) return
  const attempt = ++playbackAttempt
  // Keep WebRTC on the native media element, including installed Android PWAs.
  // Android owns output routing and hardware volume; a separate AudioContext
  // cannot select the system volume channel and can silently suspend playback.
  if (audio.srcObject !== remoteStream) audio.srcObject = remoteStream
  audio.muted = false
  audio.volume = 1
  try {
    await audio.play()
    if (attempt === playbackAttempt) playbackNeedsGesture.value = false
  } catch {
    if (attempt !== playbackAttempt) return
    playbackNeedsGesture.value = true
    emit('error', new Error(t('chat.callPlaybackError')))
  }
}

function retryRemoteAudio(): void {
  const remoteStream = remoteAudio.value?.srcObject
  if (!peer || !(remoteStream instanceof MediaStream)) return
  // Invoke play synchronously from the tap to satisfy mobile autoplay policies.
  void playRemoteStream(remoteStream)
}

function handlePeerState(connection: RTCPeerConnection): void {
  if (peer !== connection) return
  clearDisconnectTimer()
  if (connection.connectionState === 'failed' || connection.connectionState === 'closed') {
    const endedCallId = callId.value
    cleanup(endedCallId)
    emit('ended')
    return
  }
  if (connection.connectionState === 'disconnected') {
    disconnectTimer = window.setTimeout(() => {
      if (peer !== connection || connection.connectionState !== 'disconnected') return
      const endedCallId = callId.value
      cleanup(endedCallId)
      emit('ended')
    }, 5000)
  }
}

async function start(): Promise<void> {
  if (startAttempt) return
  const attempt: StartAttempt = {
    controller: new AbortController(),
    pendingStream: null,
  }
  const { controller } = attempt
  const roomId = props.roomId
  const language = props.language
  startAttempt = attempt
  loading.value = true
  ignoredCallId.value = null
  emit('starting')
  try {
    const mediaRequest = navigator.mediaDevices.getUserMedia({
      audio: {
        autoGainControl: true,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })
    void mediaRequest.then((acquiredStream) => {
      if (controller.signal.aborted) {
        for (const track of acquiredStream.getTracks()) track.stop()
      } else {
        attempt.pendingStream = acquiredStream
      }
    }).catch(() => undefined)
    const [mediaStream, status] = await Promise.all([
      mediaRequest,
      chatService.callStatus(roomId),
    ]).catch((error: unknown) => {
      // The status request can fail while the permission prompt is still open.
      // Stop a stream that resolves afterwards instead of leaking the mobile mic.
      void mediaRequest.then((acquiredStream) => {
        for (const track of acquiredStream.getTracks()) track.stop()
      }).catch(() => undefined)
      throw error
    })
    if (controller.signal.aborted) {
      for (const track of mediaStream.getTracks()) track.stop()
      return
    }
    attempt.pendingStream = null
    stream = mediaStream
    if (!status.available) throw new Error(t('chat.callUnavailable'))
    const connection = new RTCPeerConnection(peerConfiguration(status))
    peer = connection
    const candidateSender = createTrickleIceSender(
      (id, candidates) => chatService.addCallCandidates(roomId, id, candidates),
    )
    iceSender = candidateSender
    const reportCandidateError = (error: unknown): void => {
      if (peer === connection) emit('error', error)
    }
    connection.onicecandidate = (event) => {
      void candidateSender.add(event.candidate).catch(reportCandidateError)
    }
    connection.onconnectionstatechange = () => handlePeerState(connection)
    for (const track of stream.getTracks()) connection.addTrack(track, stream)
    connection.ontrack = (event) => {
      if (peer !== connection || event.track.kind !== 'audio') return
      const remoteStream = event.streams[0] ?? new MediaStream([event.track])
      void playRemoteStream(remoteStream)
    }
    const offer = await connection.createOffer()
    await connection.setLocalDescription(offer)
    if (controller.signal.aborted) return
    if (!offer.sdp) throw new Error('Missing WebRTC offer')
    const answer = await chatService.startCall(roomId, offer.sdp, language)
    if (controller.signal.aborted) {
      await chatService.stopCall(roomId, answer.call_id).catch(() => undefined)
      return
    }
    callId.value = answer.call_id
    await connection.setRemoteDescription({ sdp: answer.sdp, type: answer.type })
    // ICE can already be connected while queued alternative routes are sent.
    // Let peer state decide whether the call has failed, as for later candidates.
    await candidateSender.bind(answer.call_id).catch(reportCandidateError)
  } catch (error) {
    if (controller.signal.aborted) return
    const startedId = callId.value
    if (startedId) {
      await hangUpLocalFirst(
        () => cleanup(startedId),
        () => chatService.stopCall(roomId, startedId),
      ).catch(() => undefined)
      emit('ended')
    } else {
      cleanup()
    }
    emit('error', error)
  } finally {
    if (startAttempt === attempt) {
      startAttempt = null
      loading.value = false
    }
  }
}

function toggleMute(): void {
  muted.value = !muted.value
  for (const track of stream?.getAudioTracks() ?? []) track.enabled = !muted.value
}

async function stop(): Promise<void> {
  const attempt = startAttempt
  if (attempt) {
    attempt.controller.abort()
    for (const track of attempt.pendingStream?.getTracks() ?? []) track.stop()
    attempt.pendingStream = null
    startAttempt = null
    loading.value = false
  }
  const id = displayedCallId.value
  if (!id) {
    cleanup()
    emit('ended')
    return
  }
  emit('stopping', id)
  try {
    await hangUpLocalFirst(
      () => {
        cleanup(id)
        emit('ended')
      },
      () => chatService.stopCall(props.roomId, id),
    )
  } catch (error) {
    emit('error', error)
  }
}

watch(
  () => props.activeCallId ?? null,
  (activeCallId) => {
    if (activeCallId !== ignoredCallId.value) ignoredCallId.value = null
  },
)

watch(
  [callId, () => props.endedCallId ?? null],
  ([localCallId, endedCallId]) => {
    if (!localCallId || localCallId !== endedCallId) return
    cleanup(endedCallId)
  },
)

watch(
  () => props.roomId,
  (_roomId, previousRoomId) => {
    startAttempt?.controller.abort()
    for (const track of startAttempt?.pendingStream?.getTracks() ?? []) track.stop()
    startAttempt = null
    loading.value = false
    const activeLocalCallId = callId.value
    if (!activeLocalCallId) {
      cleanup()
      return
    }
    cleanup(activeLocalCallId)
    void chatService.stopCall(previousRoomId, activeLocalCallId).catch(() => undefined)
  },
)

onBeforeUnmount(() => {
  if (startAttempt || callId.value) void stop()
  else cleanup()
})
</script>
