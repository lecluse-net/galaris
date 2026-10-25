import axios from 'axios'
import type { DocumentFocus } from '@/core/util'
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { defineStore } from 'pinia'
import { usePrivilegeStore } from '@/core/authorize'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken, sessionGeneration } from '@/core/api'
import { websocket, BaseRoom } from '@/core/websocket'
import { chatService as service } from '../services/chatService'
import { applyVoiceTranscriptionEvent, loadMessageActivitySnapshot, mergeConversationActivity, mergeChatMessages, orderChatMessages, reconcileLiveRoundFromActivitySnapshot, reconcileVoiceTranscriptions, shouldShowLiveConversationRound, startLiveConversationRound } from '../liveState'
import { applyConversationRuntimeEvent } from '../runtimeState'
import { reconcileRealtimeCall } from '../voiceCall'
import type { ActiveCall, ChatCommandCode, ConversationActivity, ConversationActivityPage, LiveAgentRound, MessagePage, MessageTopicChange, MessengerMessage, MessengerRoom, MessengerStatus, PendingVoiceTranscription, ReasoningEffort, RealtimeCallEvent, RealtimeMessageEvent, RealtimeRuntimeEvent, RealtimeVoiceTranscriptionEvent } from '../types'

class ChatRoom extends BaseRoom { readonly className = 'ChatRoom' }

const OBSERVED_REALTIME_MESSAGE_LIMIT = 500
const externalMessageIdCollator = new Intl.Collator('en', {
  numeric: true,
  sensitivity: 'variant',
})

function compareMessages(left: MessengerMessage, right: MessengerMessage): number {
  const timestampDifference = Date.parse(left.created_at) - Date.parse(right.created_at)
  if (timestampDifference !== 0) return timestampDifference
  return externalMessageIdCollator.compare(left.external_id, right.external_id)
    || left.id.localeCompare(right.id)
}

/** Each conversation surface owns its selection and subscriptions. */
export function useChatState(documentId: () => string | null = () => null) {
  const privilegeStore = usePrivilegeStore()
  const status = ref<MessengerStatus | null>(null)
  const rooms = ref<MessengerRoom[]>([])
  const selectedRoom = ref<MessengerRoom | null>(null)
  const loadingRoomId = ref<string | null>(null)
  const messages = ref<MessengerMessage[]>([])
  const activity = ref<ConversationActivity[]>([])
  const commands = ref<ChatCommandCode[]>([])
  const activeCall = ref<ActiveCall | null>(null)
  const stoppingCallId = ref<string | null>(null)
  const endedCallId = ref<string | null>(null)
  const callAvailable = ref(false)
  // Runtime reducers replace the root; completed trace messages stay immutable.
  const liveRound = shallowRef<LiveAgentRound | null>(null)
  const pendingVoiceTranscriptions = ref<PendingVoiceTranscription[]>([])
  const roomsTotal = ref(0)
  const roomsPage = ref(1)
  const roomsPageSize = ref(50)
  const loadingMoreRooms = ref(false)
  const includeExternalRooms = ref(false)
  const includeArchivedRooms = ref(false)
  const messagesTotal = ref(0)
  const messagesPage = ref(1)
  const messagesPageSize = 50
  const providerHistory = ref(false)
  const historyHasMore = ref(false)
  const historyNextCursor = ref<string | null>(null)
  const loadingOlderMessages = ref(false)
  const loadingRecentMessages = ref(false)
  const activityTotal = ref(0)
  const activityPage = ref(1)
  const activityPageSize = ref(50)
  const loading = ref(false)
  const sending = ref(false)
  let sendSequence = 0
  let unconfirmedSend: { signature: string; files: readonly File[]; clientMessageId: ReturnType<typeof crypto.randomUUID> } | null = null
  const roomSearch = ref('')
  const viewerAgentId = ref<number | null>(null)
  const incomingMessageNotification = ref<{ roomId: string; messageId: string } | null>(null)
  const observedRealtimeMessageIds = new Set<string>()
  let subscribedRoom: ChatRoom | null = null
  let connected = false
  let lastRecentMessagesLoad = 0
  let roomsRequestSequence = 0
  let runtimeEventRevision = 0
  let runtimeRenderTimer: ReturnType<typeof setTimeout> | undefined
  let pendingRuntimeRound: LiveAgentRound | null = null
  let pendingRuntimeGeneration = 0
  let pendingRuntimeDelta: { data: NonNullable<RealtimeRuntimeEvent['data']>; lastSequence: number } | null = null
  let callEventRevision = 0
  let selectedRoomGeneration = 0
  let projectionRequestSequence = 0
  let appliedProjectionSequence = 0
  let controlsEpoch = 0
  let pendingControls: {
    generation: number; roomId: string
    commands?: ReturnType<typeof service.commands>
    activeCall?: ReturnType<typeof service.activeCall>
    callStatus?: ReturnType<typeof service.callStatus>
  } | null = null

  // Only an accepted newer projection supersedes an older one. A failed request
  // must not discard useful data still arriving for the same selection and viewer.
  function selectedProjectionRequest(): { canApply: () => boolean; accept: () => void } {
    const roomId = selectedRoom.value?.id
    const generation = selectedRoomGeneration
    const scopeAgentId = viewerAgentId.value
    const sequence = ++projectionRequestSequence
    return {
      canApply: () => selectedRoom.value?.id === roomId
        && selectedRoomGeneration === generation && viewerAgentId.value === scopeAgentId
        && sequence >= appliedProjectionSequence,
      accept: () => { appliedProjectionSequence = sequence },
    }
  }
  let catchUpTimer: ReturnType<typeof setTimeout> | null = null
  const needsCatchUp = computed(() => {
    const roomId = selectedRoom.value?.id
    const round = liveRound.value
    return !!roomId && !!round && round.room_id === roomId
      && (round.active || (round.success && shouldShowLiveConversationRound(round, roomId, activity.value, messages.value)))
  })

  function stopCatchUp(): void {
    if (catchUpTimer !== null) clearTimeout(catchUpTimer)
    catchUpTimer = null
  }
  function scheduleCatchUp(): void {
    if (!connected || !needsCatchUp.value || catchUpTimer !== null) return
    // Socket events can arrive while HTTP is offline, or before the durable commit.
    // Keep one sequential reconciliation loop until the visible response is durable.
    catchUpTimer = setTimeout(async () => {
      catchUpTimer = null
      if (!connected || !needsCatchUp.value) return
      try { await loadRecentMessages() }
      catch { /* A temporary HTTP failure keeps the same durable catch-up pending. */ }
      finally { scheduleCatchUp() }
    }, 3_000)
  }
  watch(needsCatchUp, needed => { if (needed) scheduleCatchUp(); else stopCatchUp() })
  onScopeDispose(disconnect)

  const enabled = computed(() => status.value?.enabled === true)
  const loadingSelectedRoom = computed(() => (
    selectedRoom.value !== null && loadingRoomId.value === selectedRoom.value.id
  ))
  const hasMoreRooms = computed(() => rooms.value.length < roomsTotal.value)
  const hasOlderMessages = computed(() => providerHistory.value
    ? historyHasMore.value
    : messages.value.length < messagesTotal.value)
  const latestDisplayedMessageId = computed(() => (
    [...messages.value]
      .reverse()
      .find(message => !message.id.startsWith('pending:'))
      ?.id ?? null
  ))

  function mergeMessagePage(result: MessagePage<MessengerMessage>): void {
    messages.value = orderChatMessages(
      mergeChatMessages(messages.value, result.items),
      compareMessages,
    )
    messagesTotal.value = Math.max(result.total, messages.value.length)
    pendingVoiceTranscriptions.value = reconcileVoiceTranscriptions(
      pendingVoiceTranscriptions.value,
      messages.value,
    )
  }

  function mergeSentMessage(message: MessengerMessage): void {
    messages.value = orderChatMessages(
      mergeChatMessages(messages.value, [message]),
      compareMessages,
    )
    messagesTotal.value = Math.max(messagesTotal.value, messages.value.length)
    pendingVoiceTranscriptions.value = reconcileVoiceTranscriptions(
      pendingVoiceTranscriptions.value,
      messages.value,
    )
  }

  function markRoomReadLocally(roomId: string): void {
    if (selectedRoom.value?.id === roomId) {
      selectedRoom.value = { ...selectedRoom.value, unread_count: 0 }
    }
    rooms.value = rooms.value.map(room => (
      room.id === roomId ? { ...room, unread_count: 0 } : room
    ))
  }

  let readAcknowledgement: {
    generation: number; roomId: string; acknowledged: string | null; requested: string | null;
    promise: Promise<boolean> | null
  } | null = null

  function readCovers(cursor: string | null, messageId: string): boolean {
    if (cursor === messageId) return true
    const cursorIndex = messages.value.findIndex(message => message.id === cursor)
    const messageIndex = messages.value.findIndex(message => message.id === messageId)
    return cursorIndex >= 0 && messageIndex >= 0 && cursorIndex >= messageIndex
  }

  // Only the caller starting the shared work refreshes the inbox summary.
  async function markSelectedRoomRead(messageId: string): Promise<boolean> {
    const roomId = selectedRoom.value?.id
    if (!roomId || viewerAgentId.value !== null
      || !messages.value.some(message => message.id === messageId && !message.id.startsWith('pending:'))) return false
    if (readAcknowledgement?.generation !== selectedRoomGeneration || readAcknowledgement.roomId !== roomId) {
      readAcknowledgement = { generation: selectedRoomGeneration, roomId, acknowledged: null, requested: null, promise: null }
    }
    const state = readAcknowledgement
    const current = (): boolean => readAcknowledgement === state
      && state.generation === selectedRoomGeneration && selectedRoom.value?.id === roomId && viewerAgentId.value === null
    if (readCovers(state.acknowledged, messageId)) return false
    if (!readCovers(state.requested, messageId)) state.requested = messageId
    if (state.promise) {
      await state.promise
      return false
    }
    state.promise = (async () => {
      while (state.requested && current()) {
        const target = state.requested
        state.requested = null
        if (readCovers(state.acknowledged, target)) continue
        try {
          await service.markRead(roomId, target)
        } catch (error) {
          if (!current()) return false
          // A later visible message can also acknowledge a failed earlier read.
          clearDeniedScope(error)
          if (!current()) return false
          if (state.requested) continue
          throw error
        }
        if (!current()) return false
        state.acknowledged = target
        if (latestDisplayedMessageId.value === target) markRoomReadLocally(roomId)
        // The read is durable even if the optional room-list refresh fails.
        // A denial still purges the scope inside refreshRooms.
        else await refreshRooms(current).catch(() => undefined)
      }
      return current()
    })()
    try {
      return await state.promise
    } finally { state.promise = null }
  }

  function createLiveRound(roomId: string, roundId: string, topicId: string | null = null): LiveAgentRound {
    return startLiveConversationRound(null, roomId, roundId, -1, topicId)
  }

  function applyActivitySnapshot(
    roomId: string,
    result: ConversationActivityPage,
    runtimeRevisionAtRequest: number,
  ): void {
    flushRuntimeProjection()
    activity.value = mergeConversationActivity(activity.value, result.items)
    activityTotal.value = result.total
    liveRound.value = reconcileLiveRoundFromActivitySnapshot(
      liveRound.value,
      roomId,
      result.items,
      runtimeRevisionAtRequest,
      runtimeEventRevision,
      roundId => createLiveRound(
        roomId,
        roundId,
        result.items.find(item => item.id === roundId)?.topic_id ?? null,
      ),
    )
    if (result.runtime && runtimeRevisionAtRequest === runtimeEventRevision) {
      const update = applyConversationRuntimeEvent(liveRound.value, { ...result.runtime, room_id: roomId })
      if (update) liveRound.value = update.round
    }
  }

  function resetProviderHistory(result?: MessagePage<MessengerMessage>): void {
    providerHistory.value = result?.provider_history ?? false
    historyHasMore.value = result?.history_has_more ?? false
    historyNextCursor.value = result?.history_next_cursor ?? null
  }

  async function loadStatus(): Promise<void> { status.value = await service.status() }
  function clearDeniedScope(error: unknown): void {
    if (axios.isAxiosError(error) && [403, 404].includes(error.response?.status ?? 0)) {
      disconnect()
      purge()
    }
  }
  function handleScopeError(error: unknown): never { clearDeniedScope(error); throw error }
  async function loadRooms(
    search = roomSearch.value,
    includeExternal = includeExternalRooms.value,
    includeArchived = includeArchivedRooms.value,
  ): Promise<void> {
    const sequence = ++roomsRequestSequence
    try {
      roomSearch.value = search
      const result = await service.rooms(
        1,
        roomsPageSize.value,
        search,
        viewerAgentId.value,
        includeExternal,
        includeArchived,
        null,
        documentId(),
      )
      if (sequence !== roomsRequestSequence) return
      rooms.value = result.items
      roomsTotal.value = result.total
      roomsPage.value = 1
      includeExternalRooms.value = includeExternal
      includeArchivedRooms.value = includeArchived
    } catch (error) { if (sequence === roomsRequestSequence) handleScopeError(error) }
  }
  async function refreshRooms(canApply: () => boolean = () => true): Promise<void> {
    const sequence = ++roomsRequestSequence
    const loadedCount = Math.max(roomsPageSize.value, rooms.value.length)
    try {
      const result = await service.rooms(
        1,
        loadedCount,
        roomSearch.value,
        viewerAgentId.value,
        includeExternalRooms.value,
        includeArchivedRooms.value,
        null,
        documentId(),
      )
      if (sequence !== roomsRequestSequence || !canApply()) return
      rooms.value = result.items
      roomsTotal.value = result.total
      roomsPage.value = Math.max(1, Math.ceil(result.items.length / roomsPageSize.value))
    } catch (error) { if (sequence === roomsRequestSequence && canApply()) handleScopeError(error) }
  }
  async function loadMoreRooms(): Promise<void> {
    if (loadingMoreRooms.value || !hasMoreRooms.value) return
    const sequence = roomsRequestSequence
    loadingMoreRooms.value = true
    try {
      const result = await service.rooms(
        roomsPage.value + 1,
        roomsPageSize.value,
        roomSearch.value,
        viewerAgentId.value,
        includeExternalRooms.value,
        includeArchivedRooms.value,
        null,
        documentId(),
      )
      if (sequence !== roomsRequestSequence) return
      const merged = new Map(rooms.value.map(room => [room.id, room]))
      for (const room of result.items) merged.set(room.id, room)
      rooms.value = [...merged.values()]
      roomsTotal.value = result.total
      roomsPage.value = result.page
    } catch (error) { if (sequence === roomsRequestSequence) handleScopeError(error) }
    finally { loadingMoreRooms.value = false }
  }
  async function refreshSelected(): Promise<void> {
    if (!selectedRoom.value) return
    const id = selectedRoom.value.id
    const request = selectedProjectionRequest()
    const scopeAgentId = viewerAgentId.value
    const runtimeRevisionAtRequest = runtimeEventRevision
    const callRevisionAtRequest = callEventRevision
    try {
      const canLoadCall = scopeAgentId === null && selectedRoom.value.source === null
        && selectedRoom.value.kind === 'direct' && privilegeStore.hasPrivilege('CHAT_CALL')
      const canLoadCommands = selectedRoom.value.writable && scopeAgentId === null
      const [room, [messageResult, activityResult]] = await Promise.all([
        service.room(id, scopeAgentId, documentId()),
        loadMessageActivitySnapshot(
          () => service.messages(id, 1, messagesPageSize, scopeAgentId),
          () => service.activity(id, activityPage.value, activityPageSize.value, scopeAgentId),
        ),
      ])
      if (!request.canApply()) return
      request.accept()
      selectedRoom.value = room
      mergeMessagePage(messageResult)
      if (messagesPage.value === 1) resetProviderHistory(messageResult)
      lastRecentMessagesLoad = Date.now()
      applyActivitySnapshot(id, activityResult, runtimeRevisionAtRequest)
      // Optional controls must not delay the canonical message/activity projection.
      // Share only unfinished reads within this selection. Settled reads are
      // discarded so later refreshes still observe configuration changes.
      if (!pendingControls || pendingControls.generation !== selectedRoomGeneration || pendingControls.roomId !== id) {
        pendingControls = { generation: selectedRoomGeneration, roomId: id }
      }
      const controls = pendingControls
      const epoch = controlsEpoch
      const canApplyControls = (): boolean => request.canApply() && pendingControls === controls
      // A call transition invalidates data, but an access denial still applies
      // to this selection/session even when the call state has changed.
      const optionalError = (error: unknown): void => {
        if (request.canApply() && epoch === controlsEpoch) clearDeniedScope(error)
      }
      const callRead = Promise.all([
        canLoadCall
          ? controls.activeCall ??= service.activeCall(id).finally(() => { controls.activeCall = undefined })
          : Promise.resolve(null),
        canLoadCall
          ? controls.callStatus ??= service.callStatus(id).finally(() => { controls.callStatus = undefined })
          : Promise.resolve(null),
      ])
      void callRead.then(([call, status]) => {
        if (!canApplyControls()) return
        if (callRevisionAtRequest === callEventRevision) {
          activeCall.value = call?.call_id === endedCallId.value ? null : call
          if (!activeCall.value) stoppingCallId.value = null
        }
        callAvailable.value = status?.available ?? false
      }).catch(optionalError)
      const commandRead = canLoadCommands
        ? controls.commands ??= service.commands(id).finally(() => { controls.commands = undefined })
        : Promise.resolve(null)
      void commandRead.then(catalog => {
        if (canApplyControls()) commands.value = catalog?.commands ?? []
      }).catch(optionalError)
    } catch (error) { if (request.canApply()) handleScopeError(error) }
  }
  async function selectRoom(room: MessengerRoom | null): Promise<void> {
    if (!room) {
      releaseSelectedRoom()
      selectedRoom.value = null
      loadingRoomId.value = null
      connect()
      return
    }
    selectedRoomGeneration += 1
    if (subscribedRoom) websocket.leaveRoom(subscribedRoom)
    loadingRoomId.value = room.id
    selectedRoom.value = room
    messagesPage.value = 1
    messages.value = []
    resetProviderHistory()
    commands.value = []
    activeCall.value = null
    stoppingCallId.value = null
    endedCallId.value = null
    callAvailable.value = false
    messagesTotal.value = 0
    liveRound.value = null
    pendingVoiceTranscriptions.value = []
    activityPage.value = 1
    subscribedRoom = new ChatRoom(room.id)
    websocket.joinRoom(subscribedRoom)
    try {
      await refreshSelected()
    } finally {
      if (loadingRoomId.value === room.id) loadingRoomId.value = null
    }
  }
  function setDisplayedRoom(roomId: string | null): void {
    websocket.setDisplayedRoom(roomId ? new ChatRoom(roomId) : null)
  }
  async function updateRoomPreferences(label: string, showLastMessage: boolean): Promise<void> {
    const roomId = selectedRoom.value?.id
    if (!roomId || viewerAgentId.value !== null) return
    try {
      const updated = await service.updateRoomPreferences(roomId, label, showLastMessage)
      if (selectedRoom.value?.id === roomId) selectedRoom.value = updated
      rooms.value = rooms.value.map(room => room.id === roomId ? updated : room)
    } catch (error) { handleScopeError(error) }
  }
  async function setRoomArchived(archived: boolean): Promise<void> {
    const roomId = selectedRoom.value?.id
    if (!roomId || viewerAgentId.value !== null) return
    try {
      const updated = await service.setArchived(roomId, archived)
      if (selectedRoom.value?.id === roomId) selectedRoom.value = updated
      await refreshRooms()
    } catch (error) { handleScopeError(error) }
  }
  async function updateRoomTopic(topicId: string | null): Promise<void> {
    const roomId = selectedRoom.value?.id
    if (!roomId || viewerAgentId.value !== null) return
    try {
      const updated = await service.updateRoomTopic(roomId, topicId)
      if (selectedRoom.value?.id === roomId) selectedRoom.value = updated
      rooms.value = rooms.value.map(room => room.id === roomId ? updated : room)
      await refreshSelected()
    } catch (error) { handleScopeError(error) }
  }
  function prepareCallStart(): void {
    pendingControls = null
    callEventRevision += 1
    stoppingCallId.value = null
    endedCallId.value = null
  }
  function markCallStopping(callId: string): void {
    pendingControls = null
    callEventRevision += 1
    stoppingCallId.value = callId
  }
  async function loadRecentMessages(): Promise<void> {
    const roomId = selectedRoom.value?.id
    const now = Date.now()
    // Opening the room restores messages, activity and streaming together. A
    // messages-only scroll refresh must not supersede that initial projection.
    if (!roomId || loadingRoomId.value === roomId || loadingRecentMessages.value || now - lastRecentMessagesLoad < 1_500) return
    const request = selectedProjectionRequest()
    const scopeAgentId = viewerAgentId.value
    loadingRecentMessages.value = true
    lastRecentMessagesLoad = now
    const runtimeRevisionAtRequest = runtimeEventRevision
    const catchUpLiveRound = liveRound.value?.room_id === roomId
    try {
      const [result, activityResult] = await loadMessageActivitySnapshot(
        () => service.messages(roomId, 1, messagesPageSize, scopeAgentId),
        () => catchUpLiveRound
          ? service.activity(roomId, activityPage.value, activityPageSize.value, scopeAgentId)
          : Promise.resolve(null),
      )
      if (!request.canApply()) return
      request.accept()
      mergeMessagePage(result)
      if (messagesPage.value === 1) resetProviderHistory(result)
      if (activityResult) applyActivitySnapshot(roomId, activityResult, runtimeRevisionAtRequest)
    } catch (error) { if (request.canApply()) handleScopeError(error) }
    finally { loadingRecentMessages.value = false }
  }
  async function send(text: string, files?: readonly File[], replyToMessageId: string | null = null, topicId: string | null = null, reasoningEffortOverride: ReasoningEffort | null = null, taskRequested = false, displayedDocumentId: string | null = null, language = '', documentFocus: DocumentFocus | null = null, displayedRepositoryId: string | null = null): Promise<boolean> {
    if (!selectedRoom.value?.writable || viewerAgentId.value !== null || sending.value) return false
    const room = selectedRoom.value
    const session = sessionGeneration()
    const generation = selectedRoomGeneration
    const operation = ++sendSequence
    const active = (): boolean => operation === sendSequence && session === sessionGeneration()
    const current = (): boolean => active() && generation === selectedRoomGeneration && selectedRoom.value?.id === room.id
    const attachments = files ?? []
    const signature = JSON.stringify([session, room.id, text, replyToMessageId, topicId, reasoningEffortOverride,
      taskRequested, displayedDocumentId, language, documentFocus, displayedRepositoryId])
    // An explicit retry of unchanged content retains its admission identity. It
    // can recover a lost HTTP receipt without creating a second message/round.
    const retry = unconfirmedSend?.signature === signature
      && unconfirmedSend.files.length === attachments.length
      && unconfirmedSend.files.every((file, index) => file === attachments[index])
    const clientMessageId = retry && unconfirmedSend ? unconfirmedSend.clientMessageId : crypto.randomUUID()
    unconfirmedSend = { signature, files: [...attachments], clientMessageId }
    const repliedMessage = replyToMessageId
      ? messages.value.find(message => message.id === replyToMessageId) ?? null
      : null
    const sender = [...messages.value].reverse().find(message => message.is_mine)?.sender
      ?? room.members.find(member => !member.is_ai)
      ?? null
    const optimisticMessage: MessengerMessage = {
      id: `pending:${clientMessageId}`,
      external_id: clientMessageId,
      room_id: room.id,
      direction: 'inbound',
      text,
      topic_id: topicId ?? room.topic_id,
      topic_overridden: topicId !== null,
      sender,
      reply_to: repliedMessage?.external_id ?? null,
      files: [],
      status: 'pending',
      created_at: new Date().toISOString(),
      is_mine: true,
      optimistic_after_id: messages.value.at(-1)?.id ?? null,
    }
    mergeSentMessage(optimisticMessage)
    sending.value = true
    try {
      const sentMessage = files?.length
        ? await service.upload(room.id, files, text, replyToMessageId, topicId, clientMessageId, reasoningEffortOverride, taskRequested, displayedDocumentId, language, documentFocus, displayedRepositoryId)
        : await service.send(room.id, text, replyToMessageId, topicId, clientMessageId, reasoningEffortOverride, taskRequested, displayedDocumentId, language, documentFocus, displayedRepositoryId)
      if (!active()) return false
      unconfirmedSend = null
      if (current()) {
        mergeSentMessage(sentMessage)
        messagesPage.value = 1
        // Optional reads cannot hold the composer or turn an accepted POST into
        // a failed send. They retain their normal access-denial handling.
        void refreshSelected().catch(() => undefined)
        void refreshRooms().catch(() => undefined)
      }
      return true
    } catch (error) {
      if (!active()) return false
      if (current()) {
        const confirmed = messages.value.some(message => message.external_id === clientMessageId
          && message.room_id === room.id && !message.id.startsWith('pending:'))
        if (confirmed && axios.isAxiosError(error) && !error.response) {
          unconfirmedSend = null
          return true
        }
        const optimisticStillExists = messages.value.some(message => message.id === optimisticMessage.id)
        if (optimisticStillExists) {
          messages.value = messages.value.filter(message => message.id !== optimisticMessage.id)
          messagesTotal.value = Math.max(messages.value.length, messagesTotal.value - 1)
        }
        handleScopeError(error)
      }
      throw error
    } finally {
      if (operation === sendSequence) {
        sending.value = false
        if (session !== sessionGeneration()) unconfirmedSend = null
      }
    }
  }
  function applyMessageTopicChange(change: MessageTopicChange): void {
    const anchor = messages.value.find(message => message.id === change.message_id)
    if (!anchor) return
    messages.value = messages.value.map(message => {
      const isAnchor = message.id === change.message_id
      const isFollowingSameTopic = change.scope === 'following_same_topic'
        && message.topic_id === change.previous_topic_id
        && (
          message.created_at > anchor.created_at
          || (message.created_at === anchor.created_at && message.id >= anchor.id)
        )
      return isAnchor || isFollowingSameTopic
        ? { ...message, topic_id: change.topic_id, topic_overridden: true }
        : message
    })
  }
  let signalRefresh: {
    generation: number; requested: boolean; refreshRoom: boolean; refreshRoomList: boolean; promise: Promise<void>
  } | null = null
  // Keep one HTTP projection in flight and retain invalidations received while
  // it runs. A new selection starts independently of a blocked previous room.
  async function refreshFromSignal(refreshRoom: boolean, refreshRoomList = true): Promise<void> {
    if (!refreshRoom && !refreshRoomList) return
    const generation = selectedRoomGeneration
    if (signalRefresh?.generation === generation) {
      signalRefresh.requested = true
      signalRefresh.refreshRoom ||= refreshRoom
      signalRefresh.refreshRoomList ||= refreshRoomList
      return signalRefresh.promise
    }
    const refresh = { generation, requested: true, refreshRoom, refreshRoomList, promise: Promise.resolve() }
    signalRefresh = refresh
    refresh.promise = (async () => {
      try {
        do {
          const reloadRoom = refresh.refreshRoom
          const reloadRoomList = refresh.refreshRoomList
          refresh.requested = refresh.refreshRoom = refresh.refreshRoomList = false
          try {
            if (reloadRoom) await refreshSelected()
            if (signalRefresh !== refresh || generation !== selectedRoomGeneration || !connected) return
            if (reloadRoomList) await refreshRooms()
          } catch { /* A 403 purges scoped state; subsequent signals and HTTP catch-up retry transient failures. */ }
        } while (refresh.requested && signalRefresh === refresh && generation === selectedRoomGeneration && connected)
      } finally {
        if (signalRefresh === refresh) signalRefresh = null
      }
    })()
    return refresh.promise
  }
  function rememberRealtimeMessage(messageId: string): boolean {
    if (observedRealtimeMessageIds.has(messageId)) return false
    if (observedRealtimeMessageIds.size >= OBSERVED_REALTIME_MESSAGE_LIMIT) {
      const oldestMessageId = observedRealtimeMessageIds.values().next().value
      if (oldestMessageId) observedRealtimeMessageIds.delete(oldestMessageId)
    }
    observedRealtimeMessageIds.add(messageId)
    return true
  }
  async function refreshMessageFromSignal(event: RealtimeMessageEvent): Promise<void> {
    const roomId = event.data?.room_id
    const messageId = event.data?.message_id
    const refreshRoom = roomId === selectedRoom.value?.id
    if (!roomId || !messageId) {
      await refreshFromSignal(refreshRoom)
      return
    }
    const isFirstSignal = event.data?.is_new === true && rememberRealtimeMessage(messageId)
    await refreshFromSignal(refreshRoom)
    if (!isFirstSignal || viewerAgentId.value !== null) return

    let room = selectedRoom.value?.id === roomId
      ? selectedRoom.value
      : rooms.value.find(item => item.id === roomId) ?? null
    if (!room) {
      try {
        room = await service.room(roomId, viewerAgentId.value, documentId())
      } catch {
        return
      }
    }
    const message = selectedRoom.value?.id === roomId
      ? messages.value.find(item => item.id === messageId) ?? room.last_message
      : room.last_message
    if (room.muted || message?.id !== messageId || message.is_mine) return
    incomingMessageNotification.value = { roomId, messageId }
  }
  function onRealtimeMessage(event: RealtimeMessageEvent): void { void refreshMessageFromSignal(event) }
  function onRealtime(event: RealtimeMessageEvent): void {
    const roomId = event.data?.room_id
    // Round progress does not alter list ordering or unread counts. Keep the
    // selected snapshot current; message and call signals also refresh lists.
    void refreshFromSignal(roomId === selectedRoom.value?.id, !roomId)
  }
  function onCall(event: RealtimeCallEvent): void {
    const roomId = event.data?.room_id
    if (roomId === selectedRoom.value?.id) {
      const update = reconcileRealtimeCall(
        activeCall.value,
        stoppingCallId.value,
        endedCallId.value,
        event,
      )
      if (update) {
        pendingControls = null
        callEventRevision += 1
        activeCall.value = update.activeCall
        stoppingCallId.value = update.stoppingCallId
        endedCallId.value = update.endedCallId
      }
      if (event.data?.status === 'ended') {
        pendingVoiceTranscriptions.value = pendingVoiceTranscriptions.value.filter(
          item => item.room_id !== roomId,
        )
      }
    }
    void refreshFromSignal(roomId === selectedRoom.value?.id)
  }
  function onVoiceTranscription(event: RealtimeVoiceTranscriptionEvent): void {
    const roomId = event.data?.room_id
    const room = selectedRoom.value
    if (!room || room.id !== roomId) return
    const sender = [...messages.value]
      .reverse()
      .find(message => message.sender?.is_ai === false)
      ?.sender
      ?? room.members.find(member => !member.is_ai)
      ?? null
    pendingVoiceTranscriptions.value = reconcileVoiceTranscriptions(
      applyVoiceTranscriptionEvent(
        pendingVoiceTranscriptions.value,
        event,
        sender,
      ),
      messages.value,
    )
  }
  function clearRuntimeProjection(): void {
    if (runtimeRenderTimer) clearTimeout(runtimeRenderTimer)
    runtimeRenderTimer = undefined
    pendingRuntimeRound = null
    pendingRuntimeDelta = null
  }
  function flushRuntimeDelta(): void {
    const batch = pendingRuntimeDelta
    pendingRuntimeDelta = null
    if (!batch || !pendingRuntimeRound || pendingRuntimeGeneration !== selectedRoomGeneration
      || pendingRuntimeRound.room_id !== selectedRoom.value?.id) return
    // Reduce at the first sequence, then advance to the last accepted cursor.
    const update = applyConversationRuntimeEvent(pendingRuntimeRound, batch.data)
    if (update && !update.needsSnapshot) {
      pendingRuntimeRound = { ...update.round, last_sequence: batch.lastSequence }
    }
  }
  function bufferRuntimeDelta(data: NonNullable<RealtimeRuntimeEvent['data']>): boolean {
    // Accounting, completion markers and other boundaries retain their original
    // event-by-event semantics. Only zero-cost append fragments can coalesce.
    const round = pendingRuntimeRound
    const message = data.message
    if (!round || pendingRuntimeGeneration !== selectedRoomGeneration || round.terminal_received
      || data.kind !== 'message' || data.sequence === undefined || !message?.stream_id || typeof message.content !== 'string'
      || data.room_id !== round.room_id || data.round_id !== round.round_id
      || (data.attempt ?? 1) !== (round.attempt ?? 1)
      || data.sequence !== (pendingRuntimeDelta?.lastSequence ?? round.last_sequence) + 1
      || (message.type !== 'text' && !(message.type === 'tool' && message.tool_name === 'thinking'))
      || (message.stream_mode ?? 'delta') !== 'delta' || message.stream_complete === true
      || message.success === false || (message.cost ?? 0) !== 0 || (message.execution_time ?? 0) !== 0) return false
    const batch = pendingRuntimeDelta
    if (batch) {
      const previous = batch.data.message!
      if (data.topic_id !== batch.data.topic_id || message.stream_id !== previous.stream_id
        || message.type !== previous.type || (message.tool_name ?? null) !== (previous.tool_name ?? null)
        || message.stream_complete !== previous.stream_complete) return false
      // This buffer owns its message; published rounds and incoming events stay immutable.
      previous.content += message.content
      batch.lastSequence = data.sequence
    } else {
      const previous = round.ai_result.messages?.find(item => item.stream_id === message.stream_id)
      if (!previous || previous.type !== message.type
        || (previous.tool_name ?? null) !== (message.tool_name ?? null)) return false
      pendingRuntimeDelta = { data: { ...data, message: { ...message } }, lastSequence: data.sequence }
    }
    return true
  }
  function flushRuntimeProjection(): void {
    flushRuntimeDelta()
    const pending = pendingRuntimeRound
    clearRuntimeProjection()
    if (pending && pending.room_id === selectedRoom.value?.id && pendingRuntimeGeneration === selectedRoomGeneration) {
      liveRound.value = pending
    }
  }
  function onRuntime(event: RealtimeRuntimeEvent): void {
    const data = event.data
    const roomId = data?.room_id
    if (!data || !roomId || roomId !== selectedRoom.value?.id) return
    if (bufferRuntimeDelta(data)) {
      runtimeEventRevision += 1
      return
    }
    flushRuntimeDelta()
    const baseline = pendingRuntimeRound?.room_id === roomId && pendingRuntimeGeneration === selectedRoomGeneration
      ? pendingRuntimeRound : liveRound.value
    const update = applyConversationRuntimeEvent(baseline, data)
    if (!update) return
    if (update.needsSnapshot) {
      flushRuntimeProjection()
      void refreshFromSignal(true)
      return
    }
    runtimeEventRevision += 1
    if (data.kind === 'message') {
      // Accumulate every ordered delta outside Vue, but render at most 20 times
      // per second. One cumulative value bounds memory even in hidden tabs.
      pendingRuntimeRound = update.round
      pendingRuntimeGeneration = selectedRoomGeneration
      runtimeRenderTimer ??= setTimeout(flushRuntimeProjection, 50)
    } else {
      clearRuntimeProjection()
      liveRound.value = update.round
    }
    if (update.finished) {
      // The live AIResult remains visible while this catches up the canonical
      // Messenger response. MessageTimeline swaps only after that response and
      // its round link are both present in the same HTTP projection.
      void refreshFromSignal(true)
    }
  }
  function onConnect(): void {
    controlsEpoch += 1
    pendingControls = null
    signalRefresh = null
    if (subscribedRoom) websocket.joinRoom(subscribedRoom)
    void loadStatus().catch(() => undefined)
    void refreshFromSignal(true)
  }
  function onAuthChanged(): void { controlsEpoch += 1; pendingControls = null; readAcknowledgement = null; if (!getStoredAccessToken()) { disconnect(); purge(); status.value = null } }
  function connect(): void {
    if (connected) return
    connected = true
    scheduleCatchUp()
    websocket.createWebsocket()
    websocket.onEvent('chat', 'message', onRealtimeMessage)
    websocket.onEvent('chat', 'activity', onRealtime)
    websocket.onEvent('chat', 'runtime', onRuntime)
    websocket.onEvent('chat', 'call', onCall)
    websocket.onEvent('chat', 'voice_transcription', onVoiceTranscription)
    websocket.onConnect(onConnect)
    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged)
  }
  function disconnect(): void {
    controlsEpoch += 1
    pendingControls = null
    clearRuntimeProjection()
    readAcknowledgement = null
    stopCatchUp()
    signalRefresh = null
    if (subscribedRoom) websocket.leaveRoom(subscribedRoom)
    subscribedRoom = null
    if (!connected) return
    websocket.offEvent('chat', 'message', onRealtimeMessage)
    websocket.offEvent('chat', 'activity', onRealtime)
    websocket.offEvent('chat', 'runtime', onRuntime)
    websocket.offEvent('chat', 'call', onCall)
    websocket.offEvent('chat', 'voice_transcription', onVoiceTranscription)
    websocket.offConnect(onConnect)
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onAuthChanged)
    connected = false
  }
  function releaseSelectedRoom(): void {
    selectedRoomGeneration += 1
    disconnect()
    loadingRoomId.value = selectedRoom.value?.id ?? null
    messagesPage.value = 1
    messages.value = []
    messagesTotal.value = 0
    resetProviderHistory()
    activity.value = []
    activityTotal.value = 0
    commands.value = []
    activeCall.value = null
    stoppingCallId.value = null
    endedCallId.value = null
    callAvailable.value = false
    liveRound.value = null
    pendingVoiceTranscriptions.value = []
  }
  function purge(): void {
    sendSequence += 1
    sending.value = false
    unconfirmedSend = null
    selectedRoomGeneration += 1
    roomsRequestSequence += 1
    viewerAgentId.value = null; rooms.value = []; roomsTotal.value = 0; roomsPage.value = 1; loadingMoreRooms.value = false; includeExternalRooms.value = false; includeArchivedRooms.value = false; selectedRoom.value = null; loadingRoomId.value = null; messages.value = []; messagesTotal.value = 0; resetProviderHistory(); activity.value = []; activityTotal.value = 0; commands.value = []; activeCall.value = null; stoppingCallId.value = null; endedCallId.value = null; callAvailable.value = false; liveRound.value = null; pendingVoiceTranscriptions.value = []; incomingMessageNotification.value = null; observedRealtimeMessageIds.clear()
  }
  async function loadOlderMessages(): Promise<void> {
    const roomId = selectedRoom.value?.id
    const generation = selectedRoomGeneration
    if (!roomId || loadingOlderMessages.value || !hasOlderMessages.value) return
    loadingOlderMessages.value = true
    try {
      const nextPage = messagesPage.value + 1
      const result = await service.messages(
        roomId,
        nextPage,
        messagesPageSize,
        viewerAgentId.value,
        providerHistory.value ? historyNextCursor.value : null,
      )
      if (selectedRoom.value?.id !== roomId || generation !== selectedRoomGeneration) return
      const existingIds = new Set(messages.value.map(message => message.id))
      messages.value = orderChatMessages([
        ...result.items.filter(message => !existingIds.has(message.id)),
        ...messages.value,
      ], compareMessages)
      messagesTotal.value = result.total
      messagesPage.value = result.page
      if (result.provider_history) {
        providerHistory.value = true
        historyHasMore.value = result.history_has_more
        historyNextCursor.value = result.history_next_cursor
      }
    } catch (error) {
      if (selectedRoom.value?.id === roomId && generation === selectedRoomGeneration) handleScopeError(error)
    }
    finally { loadingOlderMessages.value = false }
  }
  async function setActivityPage(page: number, pageSize = activityPageSize.value): Promise<void> { activityPage.value = page; activityPageSize.value = pageSize; await refreshSelected() }
  async function setViewerAgent(agentId: number | null): Promise<void> {
    if (viewerAgentId.value === agentId) return
    selectedRoomGeneration += 1
    if (subscribedRoom) websocket.leaveRoom(subscribedRoom)
    subscribedRoom = null
    viewerAgentId.value = agentId
    selectedRoom.value = null
    loadingRoomId.value = null
    messages.value = []
    messagesTotal.value = 0
    resetProviderHistory()
    activity.value = []
    commands.value = []
    activityTotal.value = 0
    activeCall.value = null
    stoppingCallId.value = null
    endedCallId.value = null
    callAvailable.value = false
    liveRound.value = null
    pendingVoiceTranscriptions.value = []
    roomsPage.value = 1
    await loadRooms(roomSearch.value)
  }
  async function initialize(): Promise<void> {
    loading.value = true
    try {
      await loadStatus()
      if (enabled.value) {
        await loadRooms()
        connect()
        if (selectedRoom.value) {
          const room = rooms.value.find(item => item.id === selectedRoom.value?.id)
            ?? selectedRoom.value
          await selectRoom(room)
        }
      } else {
        connect()
      }
    } finally { loading.value = false }
  }

  return { status, enabled, viewerAgentId, rooms, roomsTotal, hasMoreRooms, loadingMoreRooms, includeExternalRooms, includeArchivedRooms, selectedRoom, loadingSelectedRoom, messages, messagesTotal, latestDisplayedMessageId, hasOlderMessages, loadingOlderMessages, loadingRecentMessages, activity, activityTotal, activityPage, activityPageSize, commands, activeCall, stoppingCallId, endedCallId, callAvailable, liveRound, pendingVoiceTranscriptions, incomingMessageNotification, loading, sending, initialize, loadRooms, loadMoreRooms, selectRoom, setDisplayedRoom, markSelectedRoomRead, updateRoomPreferences, setRoomArchived, updateRoomTopic, prepareCallStart, markCallStopping, refreshSelected, loadRecentMessages, loadOlderMessages, setActivityPage, setViewerAgent, send, applyMessageTopicChange, disconnect, releaseSelectedRoom, purge }
}

export const useChatStore = defineStore('chat', () => useChatState())
