import type { ActiveCall, RealtimeCallEvent, VoiceCallStatus, WebRtcIceCandidate } from './types'

export interface ReconciledCallState {
  activeCall: ActiveCall | null
  stoppingCallId: string | null
  endedCallId: string | null
}

export interface TrickleIceSender {
  add(candidate: RTCIceCandidate | null): Promise<void>
  bind(callId: string): Promise<void>
  close(): void
}

export function iceCandidatePayload(candidate: RTCIceCandidate | null): WebRtcIceCandidate {
  return {
    candidate: candidate?.candidate || null,
    sdp_mid: candidate?.sdpMid ?? null,
    sdp_m_line_index: candidate?.sdpMLineIndex ?? null,
  }
}

export function createTrickleIceSender(
  send: (callId: string, candidates: WebRtcIceCandidate[]) => Promise<void>,
): TrickleIceSender {
  const queue: WebRtcIceCandidate[] = []
  const pending: {
    candidate: WebRtcIceCandidate
    resolve: () => void
    reject: (error: unknown) => void
  }[] = []
  let callId: string | null = null
  let flushing = false
  let closed = false

  const schedule = (candidate: WebRtcIceCandidate): Promise<void> => {
    const task = new Promise<void>((resolve, reject) => {
      pending.push({ candidate, resolve, reject })
    })
    if (!flushing) {
      flushing = true
      // Coalesce the startup backlog and candidates gathered while HTTP is busy.
      // The API accepts at most 50 routes per request, in gathering order.
      void Promise.resolve().then(async () => {
        try {
          while (!closed && callId && pending.length) {
            const batch = pending.splice(0, 50)
            try {
              await send(callId, batch.map(item => item.candidate))
              batch.forEach(item => item.resolve())
            } catch (error) {
              batch.forEach(item => closed ? item.resolve() : item.reject(error))
            }
          }
        } finally { flushing = false }
      })
    }
    return task
  }

  return {
    async add(candidate: RTCIceCandidate | null): Promise<void> {
      if (closed) return
      const payload = iceCandidatePayload(candidate)
      if (!callId) {
        queue.push(payload)
        return
      }
      await schedule(payload)
    },
    async bind(boundCallId: string): Promise<void> {
      if (closed) return
      callId = boundCallId
      const pending = queue.splice(0).map(schedule)
      await Promise.all(pending)
    },
    close(): void {
      closed = true
      queue.length = 0
      pending.splice(0).forEach(item => item.resolve())
    },
  }
}

export function reconcileRealtimeCall(
  activeCall: ActiveCall | null,
  stoppingCallId: string | null,
  endedCallId: string | null,
  event: RealtimeCallEvent,
): ReconciledCallState | null {
  const callId = event.data?.call_id
  const status = event.data?.status
  if (!callId || !status) return null
  if (status === 'active') return { activeCall, stoppingCallId: null, endedCallId: null }
  if (status === 'stopping') return { activeCall, stoppingCallId: callId, endedCallId }
  if (status !== 'ended') return null
  return {
    activeCall: activeCall?.call_id === callId ? null : activeCall,
    stoppingCallId: stoppingCallId === callId ? null : stoppingCallId,
    endedCallId: callId,
  }
}

export function peerConfiguration(status: VoiceCallStatus): RTCConfiguration {
  return {
    iceServers: status.ice_servers.map(server => ({
      urls: server.urls,
      username: server.username ?? undefined,
      credential: server.credential ?? undefined,
    })),
  }
}

export async function hangUpLocalFirst(
  closeLocal: () => void,
  requestRemoteStop: () => Promise<void>,
): Promise<void> {
  closeLocal()
  await requestRemoteStop()
}
