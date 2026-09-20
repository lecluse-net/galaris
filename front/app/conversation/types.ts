import type { LLMCall } from '@/app/llm/types'
import type { ExecutionResult } from '@/app/task/types'
import type { TaskStartupTiming } from '@/app/task'

export type ConversationStatus = 'IDLE' | 'READY' | 'RUNNING'

export interface ConversationStatusOverview {
  idle: number
  ready: number
  running: number
  errors: number
}

export interface ConversationMessage {
  id: string
  sequence: number
  agent_id: number
  agent_name: string | null
  agent_code: string | null
  channel_kind: string
  connection_id: number
  room_id: string
  participant_key: string
  language: string
  payload: Record<string, unknown>
  created_at: string
  round_id: string | null
  round_status: string | null
  response_text: string | null
  response_error: string | null
  responded_at: string | null
  aggregated_message_count: number
  topic_id: string | null
}

export interface ConversationMessagePage {
  items: ConversationMessage[]
  total: number
  page: number
  page_size: number
  summary: ConversationStatusOverview
}

export interface ConversationRound {
  id: string
  topic_id: string | null
  status: string
  rendered_input: Array<Record<string, unknown>>
  response_text: string | null
  execution_result: ExecutionResult | null
  delivery_state: string
  effect_started: boolean
  attempt_count: number
  last_error: string | null
  created_at: string
  finished_at: string | null
}

export interface ConversationUnknownNotification {
  kind: 'task' | 'process'
  link_id: string
  target_id: string
  attempt_number: number
  error: string | null
}

export interface ConversationRoundDetail extends ConversationRound {
  task_startup_timings?: TaskStartupTiming[]
  agent_id: number
  agent_name: string | null
  channel_kind: string
  connection_id: number
  room_id: string
  participant_key: string
  language: string
  unknown_notifications: ConversationUnknownNotification[]
}

export type ConversationRoundCalls = Record<string, LLMCall[]>
