import type { AIMessage, AIResult, Task } from '@/app/task'

export interface MessengerStatus { enabled: boolean; chat_enabled: boolean; max_attachment_bytes: number; page_sizes: number[] }
export interface MessengerInteraction {
  id: string
  reference: string
  title: string
  body: string
  options: { id: string; label: string }[]
  free_text: boolean
  status: 'PENDING' | 'PROCESSING' | 'RESOLVED' | 'EXPIRED'
  expires_at: string
  selected_option_id: string | null
  can_answer: boolean
}
export interface ChatInboxSummary { unread_count: number }
export interface PushConfiguration { available: boolean; public_key: string }
export interface PushSubscriptionRead { id: string; enabled: boolean }
export interface PushSubscriptionPayload { endpoint: string; expiration_time: number | null; keys: { p256dh: string; auth: string } }
export interface FrequentEmojiList { items: string[]; limit: number }
export interface DictationResult { text: string }
export interface MessageSpeechStatus { available_agent_ids: number[] }
export interface WebRtcIceServer { urls: string[]; username: string | null; credential: string | null }
export interface VoiceCallStatus { available: boolean; ice_servers: WebRtcIceServer[] }
export interface WebRtcIceCandidate { candidate: string | null; sdp_mid: string | null; sdp_m_line_index: number | null }
export type ReasoningEffort = 'none' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export type ChatCommandCode =
  | 'task'
  | 'exec'
  | 'plan'
  | 'briefing'
  | 'standard'
  | 'high'
  | 'effort'
  | 'approve'
export interface ChatCommandCatalog { commands: ChatCommandCode[] }
export interface MessengerAgent { agent_id: number; connection_id: number; code: string; display_name: string; active: boolean }
export interface RecipientCatalog { agents: MessengerAgent[] }
export interface MessengerMember { id: string; external_id: string; display_name: string; avatar_url: string | null; is_ai: boolean; agent_id: number | null; role: 'owner' | 'manager' | 'member'; joined_at: string | null; muted: boolean }
export interface MessengerFile { id: string; uri: string; name: string; mime_type: string; size_bytes: number | null; kind: string }
export interface MessengerMessage { interaction?: MessengerInteraction | null; id: string; external_id: string; room_id: string; direction: string; text: string; topic_id: string | null; topic_overridden: boolean; sender: MessengerMember | null; reply_to: string | null; files: MessengerFile[]; status: string; created_at: string; is_mine: boolean; optimistic_after_id?: string | null }
export type MessageTopicChangeScope = 'message' | 'following_same_topic'
export interface MessageTopicUpdateResult { updated_messages: number }
export interface MessageTopicChange {
  message_id: string
  previous_topic_id: string | null
  topic_id: string
  scope: MessageTopicChangeScope
}
export type MessageResourcePreviewKind = 'document' | 'memory' | 'task' | 'text' | 'voice' | 'goal' | 'goal_cycle' | 'process' | 'skill' | 'file' | 'resource' | 'web' | 'youtube'
export type MessageResourceContentFormat = 'html' | 'markdown' | 'text' | 'json' | 'none'
export interface MessageResourcePreview { uri: string; deleted: boolean; kind: MessageResourcePreviewKind; title: string; subtitle: string; description: string; media_type: string; content: string | null; content_format: MessageResourceContentFormat; truncated: boolean; image_available: boolean; download_available: boolean; open_mode: 'inline' | 'external'; external_url: string | null; embed_url: string | null; metadata: Record<string, unknown> }
export interface MessengerRoom { id: string; external_id: string; label: string; kind: string; conversation_type: 'text' | 'audio'; topic_id: string | null; connection_id: number; agent_id: number; agent_name: string; agent_active: boolean; source: string | null; messenger_label: string; messenger_active: boolean; writable: boolean; role: string; muted: boolean; unread_count: number; show_last_message: boolean; archived: boolean; last_message: MessengerMessage | null; members: MessengerMember[] }
export interface ChatViewerAgent { agent_id: number; code: string; display_name: string }
export interface ChatIdentityMapping { tool_id: number; tool_code: string; tool_label: string; source: string; external_id: string | null; display_name: string | null }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface MessagePage<T> extends Page<T> { provider_history: boolean; history_has_more: boolean; history_next_cursor: string | null }
export interface ConversationActivity { id: string; response_message_id: string | null; message_ids?: string[]; topic_id: string | null; status: string; effect_started: boolean; tools_used: string[]; execution_time: number; cost: number; process_started: boolean; created_at: string; finished_at: string | null }
export type ConversationInteractionKind = 'thinking' | 'tool_call' | 'ai_message' | 'error'
export interface ConversationActivityInteraction { sequence: number; kind: ConversationInteractionKind; content: string; tool_name: string | null; arguments: Record<string, unknown>; result: Record<string, unknown>; success: boolean; execution_time: number; cost: number }
export interface ConversationActivityDetail { id: string; status: string; success: boolean; execution_time: number; cost: number; result: string; tools_used: string[]; interactions: ConversationActivityInteraction[]; created_at: string; finished_at: string | null }
export interface ConversationTask extends Task { tree_parent_id: string | null; directly_linked: boolean }
export interface ConversationTaskTree extends Page<ConversationTask> {}
export interface ConversationDocumentReference { id: string; uri: string; label: string; revision: number | null; source_task_id: string | null; updated_at: string | null }
export interface ConversationDocumentList extends Page<ConversationDocumentReference> {}
export interface ConversationDocumentDetail { id: string; revision: number; title: string; node_kind: 'memory' | 'document'; read_only: boolean; updated_at: string | null; access: { can_read: boolean; can_write: boolean }; payload: { text?: string | null; base64?: string | null } }
export interface ConversationDocumentUpdate { expected_revision: number; title: string; payload: { text: string }; reason: string }
export type ConversationProcessStatus = 'queued' | 'running' | 'waiting' | 'success' | 'error' | 'cancelling' | 'cancelled' | 'unknown'
export interface ConversationProcess { id: string; process_id: number; workflow_id: string | null; process_label: string | null; launcher_agent_id: number; launcher_agent_code: string | null; task_id: string | null; await_task_id: string | null; tool_code: string; engine_run_id: string | null; correlation_id: string; status: ConversationProcessStatus; input: Record<string, unknown>; output: Record<string, unknown> | null; engine_metadata: Record<string, unknown>; error_code: string | null; error_message: string | null; started_at: string | null; finished_at: string | null; created_at: string; updated_at: string | null; fresh: boolean; summary: string }
export interface ConversationProcessList extends Page<ConversationProcess> {}
export interface RealtimeMessageEvent { data?: { room_id?: string; message_id?: string; is_new?: boolean } }
export type RealtimeCallStatus = 'active' | 'stopping' | 'ended'
export interface RealtimeCallEvent { data?: { room_id?: string; call_id?: string; status?: RealtimeCallStatus } }
export type VoiceTranscriptionStatus = 'started' | 'completed' | 'failed'
export interface RealtimeVoiceTranscriptionEvent { data?: { room_id?: string; transcription_id?: string; status?: VoiceTranscriptionStatus; started_at?: string; message_id?: string | null } }
export interface PendingVoiceTranscription { id: string; room_id: string; started_at: string; message_id: string | null; sender: MessengerMember | null; is_mine: boolean }
export interface LiveAgentRound { room_id: string; round_id: string; attempt?: number; terminal_received?: boolean; topic_id: string | null; active: boolean; success: boolean; last_sequence: number; ai_result: AIResult }
export interface RealtimeRuntimeEvent { data?: { room_id?: string; round_id?: string; attempt?: number; topic_id?: string | null; kind?: 'started' | 'message' | 'reset' | 'snapshot' | 'finished'; sequence?: number; success?: boolean; message?: AIMessage | null; result?: AIResult | null } }
export interface ConversationActivityPage extends Page<ConversationActivity> { runtime?: RealtimeRuntimeEvent['data'] | null }
export interface ActiveCall { call_id: string; started_at: number }
