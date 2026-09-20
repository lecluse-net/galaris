import type {
  ConversationActivity,
  LiveAgentRound,
  MessengerMessage,
  PendingVoiceTranscription,
  RealtimeVoiceTranscriptionEvent,
} from './types'
import { currentAIResponse } from '../task/facade.ts'

export interface ConversationTimelineEntry {
  key: string
  message: MessengerMessage | null
  liveRound: LiveAgentRound | null
  pendingTranscription: PendingVoiceTranscription | null
}

/** Read lineage after messages so it cannot predate a newly visible response. */
export async function loadMessageActivitySnapshot<M, A>(
  loadMessages: () => Promise<M>,
  loadActivity: () => Promise<A>,
): Promise<[M, A]> {
  const messages = await loadMessages()
  return [messages, await loadActivity()]
}

/** An older overlapping refresh must not erase an already known durable link. */
export function mergeConversationActivity(
  current: readonly ConversationActivity[],
  incoming: readonly ConversationActivity[],
): ConversationActivity[] {
  const knownResponses = new Map(current.map(item => [item.id, item.response_message_id]))
  return incoming.map(item => ({
    ...item,
    response_message_id: item.response_message_id ?? knownResponses.get(item.id) ?? null,
  }))
}

/** Resolve bubble text without letting an ephemeral handoff hide durable content. */
export function conversationTimelineEntryText(
  entry: ConversationTimelineEntry,
): string {
  if (entry.message) return entry.message.text
  return entry.liveRound ? currentAIResponse(entry.liveRound.ai_result) : ''
}

export function applyVoiceTranscriptionEvent(
  current: readonly PendingVoiceTranscription[],
  event: RealtimeVoiceTranscriptionEvent,
  sender: PendingVoiceTranscription['sender'],
): PendingVoiceTranscription[] {
  const data = event.data
  if (!data?.room_id || !data.transcription_id || !data.status) return [...current]
  if (data.status === 'failed') {
    return current.filter(item => item.id !== data.transcription_id)
  }
  const existing = current.find(item => item.id === data.transcription_id)
  if (data.status === 'completed') {
    if (!existing || !data.message_id) return [...current]
    return current.map(item => item.id === data.transcription_id
      ? { ...item, message_id: data.message_id ?? null }
      : item)
  }
  if (existing) return [...current]
  return [
    ...current,
    {
      id: data.transcription_id,
      room_id: data.room_id,
      started_at: data.started_at ?? new Date().toISOString(),
      message_id: null,
      sender,
      is_mine: true,
    },
  ]
}

export function reconcileVoiceTranscriptions(
  current: readonly PendingVoiceTranscription[],
  messages: readonly MessengerMessage[],
): PendingVoiceTranscription[] {
  const messageIds = new Set(messages.map(message => message.id))
  return current.filter(item => item.message_id === null || !messageIds.has(item.message_id))
}

export function conversationRoundId(
  activity: ConversationActivity | undefined,
  liveRound: LiveAgentRound | null | undefined,
): string | null {
  return activity?.id ?? liveRound?.round_id ?? null
}

export function startLiveConversationRound(
  current: LiveAgentRound | null,
  roomId: string,
  roundId: string,
  sequence: number,
  topicId: string | null = null,
): LiveAgentRound {
  // A delayed or duplicated `started` event must not erase reflection/text
  // fragments that have already advanced the same round.
  if (
    current?.room_id === roomId
    && current.round_id === roundId
    && current.last_sequence >= sequence
  ) return current

  return {
    room_id: roomId,
    round_id: roundId,
    topic_id: topicId,
    active: true,
    success: true,
    last_sequence: sequence,
    ai_result: {
      prompt: '',
      system_prompt: '',
      messages: [],
      execution_time: 0,
      result: '',
      cost: 0,
      tools_used: [],
      success: true,
    },
  }
}

export function mergeChatMessages(
  current: readonly MessengerMessage[],
  incoming: readonly MessengerMessage[],
): MessengerMessage[] {
  const incomingIds = new Set(incoming.map(message => message.id))
  const incomingExternalIds = new Set(incoming.map(message => message.external_id))
  return [
    ...current.filter(message => (
      !incomingIds.has(message.id) && !incomingExternalIds.has(message.external_id)
    )),
    ...incoming,
  ]
}

export function orderChatMessages(
  messages: readonly MessengerMessage[],
  compare: (left: MessengerMessage, right: MessengerMessage) => number,
): MessengerMessage[] {
  const optimistic = messages.filter(message => message.optimistic_after_id !== undefined)
  const ordered = messages
    .filter(message => message.optimistic_after_id === undefined)
    .sort(compare)

  for (const message of optimistic) {
    const anchorIndex = message.optimistic_after_id === null
      ? -1
      : ordered.findIndex(item => item.id === message.optimistic_after_id)
    ordered.splice(anchorIndex + 1, 0, message)
  }
  return ordered
}

export function reconcileLiveRoundFromActivity(
  current: LiveAgentRound | null,
  roomId: string,
  activity: readonly ConversationActivity[],
  allowTerminalCatchup: boolean,
  createRound: (roundId: string) => LiveAgentRound,
): LiveAgentRound | null {
  const runningRounds = activity.filter(item => (
    ['PENDING', 'CLAIMED', 'RUNNING'].includes(item.status)
  ))
  const running = runningRounds[0]

  // Runtime events are the live authority. Ordinary message/activity refreshes can lag
  // behind them and must never hide or replace an already streaming response.
  if (current?.room_id === roomId && current.active) {
    const currentStillRunning = runningRounds.some(item => item.id === current.round_id)
    if (!allowTerminalCatchup || currentStillRunning) return current
    if (!running) return { ...current, active: false }
  }

  if (running && current?.round_id !== running.id) return createRound(running.id)
  return current
}

export function reconcileLiveRoundFromActivitySnapshot(
  current: LiveAgentRound | null,
  roomId: string,
  activity: readonly ConversationActivity[],
  runtimeRevisionAtRequest: number,
  currentRuntimeRevision: number,
  createRound: (roundId: string) => LiveAgentRound,
): LiveAgentRound | null {
  return reconcileLiveRoundFromActivity(
    current,
    roomId,
    activity,
    runtimeRevisionAtRequest === currentRuntimeRevision,
    createRound,
  )
}

export function shouldShowLiveConversationRound(
  round: LiveAgentRound | null,
  roomId: string,
  activity: readonly ConversationActivity[],
  messages: readonly MessengerMessage[],
): boolean {
  if (!round || round.room_id !== roomId) return false

  const responseMessageId = activity.find(item => item.id === round.round_id)?.response_message_id
  if (
    responseMessageId
    && messages.some(message => message.id === responseMessageId)
  ) return false

  if (round.active || !round.success) return true

  // A successful terminal event can precede its HTTP projection. Keep the exact
  // terminal AIResult visible until its canonical Messenger response is rendered.
  return round.ai_result.result.trim().length > 0
}

export function conversationTimelineEntries(
  roomId: string,
  messages: readonly MessengerMessage[],
  activity: readonly ConversationActivity[],
  liveRound: LiveAgentRound | null,
  pendingTranscriptions: readonly PendingVoiceTranscription[] = [],
): ConversationTimelineEntry[] {
  const responseRoundByMessageId = new Map(
    activity
      .filter(item => item.response_message_id)
      .map(item => [item.response_message_id as string, item.id]),
  )
  const entries: ConversationTimelineEntry[] = messages.map(message => {
    const responseRoundId = responseRoundByMessageId.get(message.id)
    const matchingLiveRound = responseRoundId
      && liveRound?.room_id === roomId
      && liveRound.round_id === responseRoundId
      // A durable response is terminal by definition. Keep the richer streamed
      // result during the handoff, but never keep displaying it as still running.
      ? { ...liveRound, active: false }
      : null
    return {
      key: responseRoundId ? `response:${responseRoundId}` : `message:${message.id}`,
      message,
      liveRound: matchingLiveRound,
      pendingTranscription: null,
    }
  })

  if (shouldShowLiveConversationRound(liveRound, roomId, activity, messages) && liveRound) {
    entries.push({
      key: `response:${liveRound.round_id}`,
      message: null,
      liveRound,
      pendingTranscription: null,
    })
  }
  for (const pendingTranscription of pendingTranscriptions) {
    if (pendingTranscription.room_id !== roomId) continue
    entries.push({
      key: `voice-transcription:${pendingTranscription.id}`,
      message: null,
      liveRound: null,
      pendingTranscription,
    })
  }
  return entries
}

/** Identity of the last rendered block; streamed fragments keep the same identity. */
export function conversationTimelineRenderKey(
  roomId: string,
  entries: readonly ConversationTimelineEntry[],
): string {
  return `${roomId}:${entries.at(-1)?.key ?? 'empty'}`
}
