import axios from 'axios'
import { computed, onScopeDispose, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { usePrivilegeStore } from '@/core/authorize'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken } from '@/core/api'
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

export const useChatStore = defineStore('chat', () => {
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
  const liveRound = ref<LiveAgentRound | null>(null)
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
  const roomSearch = ref('')
  const viewerAgentId = ref<number | null>(null)
  const incomingMessageNotification = ref<{ roomId: string; messageId: string } | null>(null)
  const observedRealtimeMessageIds = new Set<string>()
  let subscribedRoom: ChatRoom | null = null
  let connected = false
  let lastRecentMessagesLoad = 0
  let roomsRequestSequence = 0
  let runtimeEventRevision = 0
  let callEventRevision = 0
  let selectedRoomGeneration = 0
  let projectionRequestSequence = 0
  let appliedProjectionSequence = 0

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

  async function markSelectedRoomRead(messageId: string): Promise<void> {
    const roomId = selectedRoom.value?.id
    if (!roomId || viewerAgentId.value !== null) return
    try {
      await service.markRead(roomId, messageId)
      if (
        selectedRoom.value?.id === roomId
        && latestDisplayedMessageId.value === messageId
      ) {
        markRoomReadLocally(roomId)
      } else {
        await refreshRooms()
      }
    } catch (error) { handleScopeError(error) }
  }

  function createLiveRound(roomId: string, roundId: string, topicId: string | null = null): LiveAgentRound {
    return startLiveConversationRound(null, roomId, roundId, -1, topicId)
  }

  function applyActivitySnapshot(
    roomId: string,
    result: ConversationActivityPage,
    runtimeRevisionAtRequest: number,
  ): void {
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
  function handleScopeError(error: unknown): never {
    if (axios.isAxiosError(error) && [403, 404].includes(error.response?.status ?? 0)) {
      disconnect()
      purge()
    }
    throw error
  }
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
      )
      if (sequence !== roomsRequestSequence) return
      rooms.value = result.items
      roomsTotal.value = result.total
      roomsPage.value = 1
      includeExternalRooms.value = includeExternal
      includeArchivedRooms.value = includeArchived
    } catch (error) { if (sequence === roomsRequestSequence) handleScopeError(error) }
  }
  async function refreshRooms(): Promise<void> {
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
      )
      if (sequence !== roomsRequestSequence) return
      rooms.value = result.items
      roomsTotal.value = result.total
      roomsPage.value = Math.max(1, Math.ceil(result.items.length / roomsPageSize.value))
    } catch (error) { if (sequence === roomsRequestSequence) handleScopeError(error) }
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
      const [room, [messageResult, activityResult], call, callStatus, commandCatalog] = await Promise.all([
        service.room(id, scopeAgentId),
        loadMessageActivitySnapshot(
          () => service.messages(id, 1, messagesPageSize, scopeAgentId),
          () => service.activity(id, activityPage.value, activityPageSize.value, scopeAgentId),
        ),
        canLoadCall ? service.activeCall(id) : Promise.resolve(null),
        canLoadCall ? service.callStatus(id) : Promise.resolve(null),
        canLoadCommands ? service.commands(id) : Promise.resolve(null),
      ])
      if (!request.canApply()) return
      request.accept()
      selectedRoom.value = room
      mergeMessagePage(messageResult)
      if (messagesPage.value === 1) resetProviderHistory(messageResult)
      lastRecentMessagesLoad = Date.now()
      applyActivitySnapshot(id, activityResult, runtimeRevisionAtRequest)
      if (callRevisionAtRequest === callEventRevision) {
        activeCall.value = call?.call_id === endedCallId.value ? null : call
        if (!activeCall.value) stoppingCallId.value = null
      }
      callAvailable.value = callStatus?.available ?? false
      commands.value = commandCatalog?.commands ?? []
    } catch (error) { if (request.canApply()) handleScopeError(error) }
  }
  async function selectRoom(room: MessengerRoom): Promise<void> {
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
    callEventRevision += 1
    stoppingCallId.value = null
    endedCallId.value = null
  }
  function markCallStopping(callId: string): void {
    callEventRevision += 1
    stoppingCallId.value = callId
  }
  async function loadRecentMessages(): Promise<void> {
    const roomId = selectedRoom.value?.id
    const now = Date.now()
    if (!roomId || loadingRecentMessages.value || now - lastRecentMessagesLoad < 1_500) return
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
  async function send(text: string, files?: readonly File[], replyToMessageId: string | null = null, topicId: string | null = null, reasoningEffortOverride: ReasoningEffort | null = null, taskRequested = false, displayedDocumentId: string | null = null, language = ''): Promise<void> {
    if (!selectedRoom.value?.writable || viewerAgentId.value !== null || sending.value) return
    const room = selectedRoom.value
    const clientMessageId = crypto.randomUUID()
    const messagesTotalBeforeSend = messagesTotal.value
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
        ? await service.upload(room.id, files, text, replyToMessageId, topicId, clientMessageId, reasoningEffortOverride, taskRequested, displayedDocumentId, language)
        : await service.send(room.id, text, replyToMessageId, topicId, clientMessageId, reasoningEffortOverride, taskRequested, displayedDocumentId, language)
      if (selectedRoom.value?.id === room.id) mergeSentMessage(sentMessage)
      messagesPage.value = 1
      await refreshSelected()
      await refreshRooms()
    } catch (error) {
      if (selectedRoom.value?.id === room.id) {
        const optimisticStillExists = messages.value.some(message => message.id === optimisticMessage.id)
        if (optimisticStillExists) {
          messages.value = messages.value.filter(message => message.id !== optimisticMessage.id)
          messagesTotal.value = messagesTotalBeforeSend
        }
      }
      handleScopeError(error)
    } finally { sending.value = false }
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
  async function refreshFromSignal(refreshRoom: boolean): Promise<void> {
    try {
      if (refreshRoom) await refreshSelected()
      await refreshRooms()
    } catch { /* A 403 already purges scoped state; transient losses use HTTP catch-up. */ }
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
        room = await service.room(roomId, viewerAgentId.value)
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
  function onRealtime(event: RealtimeMessageEvent): void { void refreshFromSignal(event.data?.room_id === selectedRoom.value?.id) }
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
  let runtimeRefresh: { generation: number; requested: boolean } | null = null
  function requestRuntimeRefresh(): void {
    const generation = selectedRoomGeneration
    // Coalesce requests without losing an invalidation received during HTTP.
    // A different selection owns its own recovery, even if the old one is blocked.
    if (runtimeRefresh?.generation === generation) {
      runtimeRefresh.requested = true
      return
    }
    const refresh = { generation, requested: true }
    runtimeRefresh = refresh
    void (async () => {
      try {
        do {
          refresh.requested = false
          await refreshFromSignal(true)
        } while (refresh.requested && generation === selectedRoomGeneration && connected)
      } finally {
        if (runtimeRefresh === refresh) runtimeRefresh = null
      }
    })()
  }
  function onRuntime(event: RealtimeRuntimeEvent): void {
    const data = event.data
    const roomId = data?.room_id
    if (!data || !roomId || roomId !== selectedRoom.value?.id) return
    const update = applyConversationRuntimeEvent(liveRound.value, data)
    if (!update) return
    if (update.needsSnapshot) {
      requestRuntimeRefresh()
      return
    }
    runtimeEventRevision += 1
    liveRound.value = update.round
    if (update.finished) {
      // The live AIResult remains visible while this catches up the canonical
      // Messenger response. MessageTimeline swaps only after that response and
      // its round link are both present in the same HTTP projection.
      void refreshFromSignal(true)
    }
  }
  function onConnect(): void {
    if (subscribedRoom) websocket.joinRoom(subscribedRoom)
    void loadStatus().catch(() => undefined)
    void refreshFromSignal(true)
  }
  function onAuthChanged(): void { if (!getStoredAccessToken()) { disconnect(); purge(); status.value = null } }
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
    stopCatchUp()
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
})
