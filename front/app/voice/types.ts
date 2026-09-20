import type { LLMCall } from '@/app/llm/types'
import type { ExecutionResult } from '@/app/task/types'

export type VoiceConversationStatus = 'ACTIVE' | 'COMPLETED' | 'CANCELLED' | 'ERROR'
export type VoiceTurnStatus = 'RUNNING' | 'COMPLETED' | 'INTERRUPTED' | 'FAILED'

export interface VoiceConversationSummary {
  id: string
  agent_id: number
  agent_name: string | null
  agent_code: string | null
  caller_name: string | null
  connection_id: number | null
  topic_id: string | null
  transport_kind: string
  room_id: string
  language: string
  status: VoiceConversationStatus
  started_at: string
  finished_at: string | null
  duration: number
  turn_count: number
  interrupted_count: number
  failed_count: number
}

export interface VoiceConversationTurn {
  id: string
  sequence: number
  run_id: string
  source_turn_id: string | null
  resolved_by_turn_id: string | null
  topic_id: string | null
  transcript: string | null
  effective_objective: string | null
  assistant_response: string | null
  status: VoiceTurnStatus
  error: string | null
  started_at: string
  first_text_at: string | null
  first_audio_at: string | null
  interrupted_at: string | null
  completed_at: string | null
  llm_call_count: number
}

export interface VoiceConversationTurnDetail extends VoiceConversationTurn {
  session_id: string
  agent_id: number
  agent_name: string | null
  caller_name: string | null
  connection_id: number | null
  transport_kind: string
  room_id: string
  language: string
  execution_result: ExecutionResult | null
}

export interface VoiceConversationDetail extends VoiceConversationSummary {
  error: string | null
  turns: VoiceConversationTurn[]
}

export interface VoiceConversationOverview {
  active: number
  completed: number
  cancelled: number
  errors: number
}

export interface VoiceConversationPage {
  items: VoiceConversationDetail[]
  total: number
  page: number
  page_size: number
  summary: VoiceConversationOverview
}

export type VoiceTurnCalls = Record<string, LLMCall[]>
