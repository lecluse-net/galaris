import { api } from '@/core/api'
import type { DocumentFocus } from '../documentFocus'
import type { MessengerInteraction } from '../types'
import { isAxiosError } from 'axios'
import type { ActiveCall, ChatCommandCatalog, ChatIdentityMapping, ChatInboxSummary, ChatViewerAgent, ConversationActivityPage, ConversationActivityDetail, ConversationDocumentDetail, ConversationDocumentList, ConversationDocumentReference, ConversationDocumentUpdate, ConversationProcessList, ConversationTaskTree, DictationResult, FrequentEmojiList, MessagePage, MessageResourcePreview, MessageSpeechStatus, MessageTopicChangeScope, MessageTopicUpdateResult, MessengerMessage, MessengerRoom, MessengerStatus, Page, PushConfiguration, PushSubscriptionPayload, PushSubscriptionRead, ReasoningEffort, RecipientCatalog, VoiceCallStatus, WebRtcIceCandidate } from '../types'

interface HtmlPreviewTicket {
  url: string
  expires_in: number
}

const base = '/chat'

export class DictationNotConfiguredError extends Error {
  constructor() {
    super('Voice transcription is not configured')
    this.name = 'DictationNotConfiguredError'
  }
}

export const chatService = {
  async interaction(roomId: string, interactionId: string): Promise<MessengerInteraction> { return (await api.get<MessengerInteraction>(`${base}/rooms/${roomId}/interactions/${interactionId}`)).data },
  async answerInteraction(roomId: string, interactionId: string, optionId: string): Promise<MessengerInteraction> { return (await api.post<MessengerInteraction>(`${base}/rooms/${roomId}/interactions/${interactionId}/answer`, { option_id: optionId })).data },
  async status(): Promise<MessengerStatus> { return (await api.get<MessengerStatus>(`${base}/status`)).data },
  async inbox(): Promise<ChatInboxSummary> { return (await api.get<ChatInboxSummary>(`${base}/inbox`)).data },
  async pushConfiguration(): Promise<PushConfiguration> { return (await api.get<PushConfiguration>(`${base}/push/configuration`)).data },
  async registerPushSubscription(subscription: PushSubscriptionPayload): Promise<PushSubscriptionRead> { return (await api.post<PushSubscriptionRead>(`${base}/push/subscriptions`, subscription)).data },
  async deletePushSubscription(endpoint: string): Promise<void> { await api.delete(`${base}/push/subscriptions`, { data: { endpoint } }) },
  async frequentEmojis(): Promise<FrequentEmojiList> { return (await api.get<FrequentEmojiList>(`${base}/emojis/frequent`)).data },
  async recordEmojiUse(emoji: string): Promise<FrequentEmojiList> { return (await api.post<FrequentEmojiList>(`${base}/emojis/usage`, { emoji })).data },
  async identityMappings(): Promise<ChatIdentityMapping[]> { return (await api.get<ChatIdentityMapping[]>(`${base}/identities`)).data },
  async setIdentityMapping(toolId: number, externalId: string): Promise<ChatIdentityMapping> { return (await api.put<ChatIdentityMapping>(`${base}/identities/${toolId}`, { external_id: externalId })).data },
  async clearIdentityMapping(toolId: number): Promise<void> { await api.delete(`${base}/identities/${toolId}`) },
  async viewerAgents(): Promise<ChatViewerAgent[]> { return (await api.get<ChatViewerAgent[]>(`${base}/viewer-agents`)).data },
  async recipients(search = ''): Promise<RecipientCatalog> { return (await api.get<RecipientCatalog>(`${base}/recipients`, { params: { search } })).data },
  async agentAvatarBlob(agentId: number): Promise<Blob> { return (await api.get<Blob>(`${base}/agents/${agentId}/avatar`, { responseType: 'blob' })).data },
  async rooms(page = 1, pageSize = 50, search = '', agentId: number | null = null, includeExternal = false, includeArchived = false): Promise<Page<MessengerRoom>> { return (await api.get<Page<MessengerRoom>>(`${base}/rooms`, { params: { page, page_size: pageSize, search, agent_id: agentId, include_external: includeExternal, include_archived: includeArchived } })).data },
  async room(roomId: string, agentId: number | null = null): Promise<MessengerRoom> { return (await api.get<MessengerRoom>(`${base}/rooms/${roomId}`, { params: { agent_id: agentId } })).data },
  async updateRoomPreferences(roomId: string, label: string, showLastMessage: boolean): Promise<MessengerRoom> { return (await api.patch<MessengerRoom>(`${base}/rooms/${roomId}`, { label, show_last_message: showLastMessage })).data },
  async setArchived(roomId: string, archived: boolean): Promise<MessengerRoom> { return (await api.patch<MessengerRoom>(`${base}/rooms/${roomId}/archive`, { archived })).data },
  async updateRoomTopic(roomId: string, topicId: string | null): Promise<MessengerRoom> { return (await api.patch<MessengerRoom>(`${base}/rooms/${roomId}/topic`, { topic_id: topicId })).data },
  async commands(roomId: string): Promise<ChatCommandCatalog> { return (await api.get<ChatCommandCatalog>(`${base}/rooms/${roomId}/commands`)).data },
  async createRoom(agentId: number, label: string, topicId: string | null, showLastMessage: boolean): Promise<MessengerRoom> { return (await api.post<MessengerRoom>(`${base}/rooms`, { agent_id: agentId, label, topic_id: topicId, show_last_message: showLastMessage })).data },
  async messages(roomId: string, page = 1, pageSize = 50, agentId: number | null = null, historyCursor: string | null = null): Promise<MessagePage<MessengerMessage>> { return (await api.get<MessagePage<MessengerMessage>>(`${base}/rooms/${roomId}/messages`, { params: { page, page_size: pageSize, agent_id: agentId, history_cursor: historyCursor } })).data },
  async messageSpeechStatus(roomId: string, agentId: number | null = null): Promise<MessageSpeechStatus> { return (await api.get<MessageSpeechStatus>(`${base}/rooms/${roomId}/speech/status`, { params: { agent_id: agentId } })).data },
  async messageSpeechBlob(roomId: string, messageId: string, language: string, agentId: number | null = null): Promise<Blob> { return (await api.post<Blob>(`${base}/rooms/${roomId}/messages/${messageId}/speech`, undefined, { params: { language, agent_id: agentId }, responseType: 'blob' })).data },
  async updateMessageTopic(roomId: string, messageId: string, topicId: string, scope: MessageTopicChangeScope): Promise<MessageTopicUpdateResult> { return (await api.patch<MessageTopicUpdateResult>(`${base}/rooms/${roomId}/messages/${messageId}/topic`, { topic_id: topicId, scope })).data },
  async messagePreviews(roomId: string, messageId: string, agentId: number | null = null): Promise<MessageResourcePreview[]> { return (await api.get<MessageResourcePreview[]>(`${base}/rooms/${roomId}/messages/${messageId}/previews`, { params: { agent_id: agentId } })).data },
  async messagePreviewImageBlob(roomId: string, messageId: string, uri: string, agentId: number | null = null): Promise<Blob> { return (await api.get<Blob>(`${base}/rooms/${roomId}/messages/${messageId}/previews/image`, { params: { uri, agent_id: agentId }, responseType: 'blob' })).data },
  async messagePreviewContentBlob(roomId: string, messageId: string, uri: string, agentId: number | null = null): Promise<Blob> { return (await api.get<Blob>(`${base}/rooms/${roomId}/messages/${messageId}/previews/content`, { params: { uri, agent_id: agentId }, responseType: 'blob' })).data },
  async standaloneHtmlPreview(blob: Blob, name: string): Promise<string> { const data = new FormData(); data.append('file', blob, name); return (await api.post<HtmlPreviewTicket>(`${base}/html-previews`, data)).data.url },
  async activity(roomId: string, page = 1, pageSize = 50, agentId: number | null = null): Promise<ConversationActivityPage> { return (await api.get<ConversationActivityPage>(`${base}/rooms/${roomId}/activity`, { params: { page, page_size: pageSize, agent_id: agentId } })).data },
  async activityDetail(roomId: string, roundId: string, agentId: number | null = null): Promise<ConversationActivityDetail> { return (await api.get<ConversationActivityDetail>(`${base}/rooms/${roomId}/activity/${roundId}`, { params: { agent_id: agentId } })).data },
  async tasks(roomId: string, fromMessageId: string, page = 1, pageSize = 10, agentId: number | null = null): Promise<ConversationTaskTree> { return (await api.get<ConversationTaskTree>(`${base}/rooms/${roomId}/tasks`, { params: { from_message_id: fromMessageId, page, page_size: pageSize, agent_id: agentId } })).data },
  async documents(roomId: string, fromMessageId: string, page = 1, pageSize = 10, agentId: number | null = null): Promise<ConversationDocumentList> { return (await api.get<ConversationDocumentList>(`${base}/rooms/${roomId}/documents`, { params: { from_message_id: fromMessageId, page, page_size: pageSize, agent_id: agentId } })).data },
  async createDocument(roomId: string, title: string): Promise<ConversationDocumentReference> { return (await api.post<ConversationDocumentReference>(`${base}/rooms/${roomId}/documents`, { title })).data },
  async document(documentId: string, agentId: number): Promise<ConversationDocumentDetail> { return (await api.get<ConversationDocumentDetail>(`/memory/items/${documentId}`, { params: { agent_id: agentId } })).data },
  async updateDocument(documentId: string, agentId: number, data: ConversationDocumentUpdate): Promise<void> { await api.put(`/memory/items/${documentId}`, data, { headers: { 'X-Editorial-Profile-Version': '1' }, params: { actor_agent_id: agentId } }) },
  async processes(roomId: string, fromMessageId: string, page = 1, pageSize = 10, agentId: number | null = null): Promise<ConversationProcessList> { return (await api.get<ConversationProcessList>(`${base}/rooms/${roomId}/processes`, { params: { from_message_id: fromMessageId, page, page_size: pageSize, agent_id: agentId } })).data },
  async send(roomId: string, text: string, replyToMessageId: string | null = null, topicId: string | null = null, clientMessageId = crypto.randomUUID(), reasoningEffortOverride: ReasoningEffort | null = null, taskRequested = false, displayedDocumentId: string | null = null, language = '', documentFocus: DocumentFocus | null = null): Promise<MessengerMessage> { return (await api.post<MessengerMessage>(`${base}/rooms/${roomId}/messages`, { client_message_id: clientMessageId, text, language, topic_id: topicId, reply_to_message_id: replyToMessageId, reasoning_effort_override: reasoningEffortOverride, task_requested: taskRequested, ...(displayedDocumentId ? { displayed_document_id: displayedDocumentId, ...(documentFocus ? { document_focus: documentFocus } : {}) } : {}) })).data },
  async transcribeDictation(roomId: string, audio: Blob, language: string): Promise<DictationResult> {
    const form = new FormData()
    const mimeType = audio.type.split(';', 1)[0] || 'audio/webm'
    const extension = mimeType === 'audio/ogg' ? 'ogg' : mimeType === 'audio/mp4' ? 'm4a' : 'webm'
    form.append('audio', audio, `dictation.${extension}`)
    form.append('language', language)
    try {
      return (await api.post<DictationResult>(`${base}/rooms/${roomId}/dictation`, form)).data
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 503) {
        throw new DictationNotConfiguredError()
      }
      throw error
    }
  },
  async upload(roomId: string, files: readonly File[], text = '', replyToMessageId: string | null = null, topicId: string | null = null, clientMessageId = crypto.randomUUID(), reasoningEffortOverride: ReasoningEffort | null = null, taskRequested = false, displayedDocumentId: string | null = null, language = '', documentFocus: DocumentFocus | null = null): Promise<MessengerMessage> { const form = new FormData(); for (const file of files) form.append('files', file); form.append('client_message_id', clientMessageId); form.append('language', language); form.append('text', text); if (topicId) form.append('topic_id', topicId); if (replyToMessageId) form.append('reply_to_message_id', replyToMessageId); if (reasoningEffortOverride) form.append('reasoning_effort_override', reasoningEffortOverride); if (taskRequested) form.append('task_requested', 'true'); if (displayedDocumentId) { form.append('displayed_document_id', displayedDocumentId); if (documentFocus) form.append('document_focus', JSON.stringify(documentFocus)); } return (await api.post<MessengerMessage>(`${base}/rooms/${roomId}/attachments`, form)).data },
  async markRead(roomId: string, messageId: string | null = null): Promise<void> { await api.post(`${base}/rooms/${roomId}/read`, { message_id: messageId }) },
  async setMuted(roomId: string, muted: boolean): Promise<void> { await api.post(`${base}/rooms/${roomId}/mute`, { muted }) },
  async attachmentBlob(roomId: string, fileId: string, agentId: number | null = null): Promise<Blob> { return (await api.get<Blob>(`${base}/rooms/${roomId}/files/${fileId}`, { params: { agent_id: agentId }, responseType: 'blob' })).data },
  async downloadFile(roomId: string, fileId: string, name: string, agentId: number | null = null): Promise<void> {
    const blob = await this.attachmentBlob(roomId, fileId, agentId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.rel = 'noopener'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
  },
  async startCall(roomId: string, sdp: string, language: string): Promise<{ call_id: string; sdp: string; type: RTCSdpType }> { return (await api.post(`${base}/rooms/${roomId}/calls`, { sdp, type: 'offer', language })).data },
  // An active call may retain this callback across a development hot reload.
  async addCallCandidate(roomId: string, callId: string, candidate: WebRtcIceCandidate | WebRtcIceCandidate[]): Promise<void> { await this.addCallCandidates(roomId, callId, Array.isArray(candidate) ? candidate : [candidate]) },
  async addCallCandidates(roomId: string, callId: string, candidates: WebRtcIceCandidate[]): Promise<void> { await api.post(`${base}/rooms/${roomId}/calls/${encodeURIComponent(callId)}/candidates`, { candidates }) },
  async callStatus(roomId: string): Promise<VoiceCallStatus> { return (await api.get<VoiceCallStatus>(`${base}/rooms/${roomId}/calls/status`)).data },
  async activeCall(roomId: string): Promise<ActiveCall | null> { return (await api.get<ActiveCall | null>(`${base}/rooms/${roomId}/calls/active`)).data },
  async stopCall(roomId: string, callId: string): Promise<void> { await api.delete(`${base}/rooms/${roomId}/calls/${encodeURIComponent(callId)}`) },
}
