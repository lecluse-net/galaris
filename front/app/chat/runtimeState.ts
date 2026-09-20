import { appendAIMessage, finalizeAIResult, reconcileAIResult, resetAIResultText } from '../task/facade.ts'
import { startLiveConversationRound } from './liveState.ts'
import type { LiveAgentRound, RealtimeRuntimeEvent } from './types'

export interface ConversationRuntimeUpdate {
  round: LiveAgentRound
  finished: boolean
  needsSnapshot?: boolean
}

/** Apply one ordered runtime event to the reactive chat projection. */
export function applyConversationRuntimeEvent(
  current: LiveAgentRound | null,
  data: NonNullable<RealtimeRuntimeEvent['data']>,
): ConversationRuntimeUpdate | null {
  const { room_id: roomId, round_id: roundId, kind, sequence } = data
  if (!roomId || !roundId || !kind || sequence === undefined) return null
  const attempt = data.attempt ?? 1
  const sameRound = current?.room_id === roomId && current.round_id === roundId
  // Sequences are local to a round; an event from another round cannot prove
  // which response is current. Let the store reconcile the durable room state.
  if (current?.room_id === roomId && !sameRound) {
    return { round: current, finished: false, needsSnapshot: true }
  }
  if (current && sameRound && attempt < (current.attempt ?? 1)) return null
  if (current && sameRound && attempt > (current.attempt ?? 1)) {
    current = {
      ...current,
      attempt,
      active: true,
      success: true,
      terminal_received: false,
      last_sequence: -1,
      ai_result: resetAIResultText(current.ai_result),
    }
    if (kind === 'started') {
      return { round: { ...current, last_sequence: sequence }, finished: false }
    }
  }
  if (sameRound && current?.terminal_received) return null

  if (kind === 'started') {
    const round = startLiveConversationRound(
      current,
      roomId,
      roundId,
      sequence,
      data.topic_id ?? null,
    )
    if (round === current) return null
    return {
      round: { ...round, attempt },
      finished: false,
    }
  }

  const baseline = current?.room_id === roomId && current.round_id === roundId
    ? current
    : startLiveConversationRound(null, roomId, roundId, -1, data.topic_id ?? null)
  if (sequence < baseline.last_sequence || (sequence === baseline.last_sequence && kind !== 'snapshot')) return null
  if ((kind === 'message' || kind === 'reset') && sequence > baseline.last_sequence + 1) {
    return { round: baseline, finished: false, needsSnapshot: true }
  }

  const next = {
    ...baseline,
    attempt,
    last_sequence: sequence,
    topic_id: data.topic_id ?? baseline.topic_id,
  }
  if (kind === 'snapshot') {
    if (!data.result) return null
    return {
      round: { ...next, active: true, ai_result: reconcileAIResult(baseline.ai_result, data.result) ?? baseline.ai_result },
      finished: false,
    }
  }
  if (kind === 'finished') {
    return {
      round: {
        ...next,
        active: false,
        terminal_received: true,
        success: data.success !== false,
        ai_result: data.result
          ? finalizeAIResult(baseline.ai_result, data.result)
          : baseline.ai_result,
      },
      finished: true,
    }
  }
  if (kind === 'reset') {
    return {
      round: { ...next, active: true, ai_result: resetAIResultText(baseline.ai_result) },
      finished: false,
    }
  }
  if (!data.message?.type) return null
  return {
    round: {
      ...next,
      active: true,
      ai_result: appendAIMessage(baseline.ai_result, data.message),
    },
    finished: false,
  }
}
