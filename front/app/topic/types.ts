export interface Topic {
  id: string
  revision: number
  title: string
  description: string
  keywords: string[]
  memory_item_id: string | null
  created_at: string
  updated_at: string | null
}

export interface TopicRef {
  id: string
  title: string
}

export type TopicAssignmentSubjectKind =
  | 'task'
  | 'message'
  | 'conversation_round'
  | 'voice_session'

export type TopicAssignmentChangeScope = 'message' | 'following_same_topic'

export interface TopicAssignmentAudit {
  topic_id: string
  subject_kind: TopicAssignmentSubjectKind
  subject_id: string
  origin: 'dream' | 'manual'
  reason: string | null
  action: 'continuity' | 'reuse' | 'create' | null
  confidence: number | null
  human_confirmed: boolean
  dream_receipt_id: string | null
  dream_mechanism_key: string | null
  dream_subject_kind: string | null
  dream_subject_id: string | null
  decided_at: string | null
}

export interface TopicMonthlyUsage extends Topic {
  inference_cost: number
  llm_calls: number
  agents: TopicRelatedAgent[]
  users: TopicRelatedUser[]
  teams: TopicRelatedTeam[]
  documents: TopicRelatedDocument[]
}

export interface TopicRelatedTeam {
  id: number
  name: string
}

export interface TopicRelatedAgent {
  id: number
  name: string
}

export interface TopicRelatedUser {
  id: string
  display_name: string
  user_id: string
}

export interface TopicRelatedDocument {
  id: string
  title: string
  filename: string | null
}

export interface TopicPage {
  items: TopicMonthlyUsage[]
  total: number
  month: string
  available_months: string[]
}

export interface TopicInput {
  title: string
  description: string
  keywords: string[]
}

export interface TopicLinkedMemory {
  id: string
  title: string
  excerpt: string
  memory_type: string
  owner_agent_id: number | null
  visibility: string
}

export interface TopicMutationResult {
  topic: Topic
  moved_memory_links: number
  reassigned_tasks: number
  reassigned_voice_sessions: number
  reassigned_voice_turns: number
  reassigned_messages: number
  reassigned_conversation_rounds: number
}

export interface TopicContentSummary {
  rooms: number
  tasks: number
  conversation_rounds: number
  voice_turns: number
  memories: number
  documents: number
}

export interface TopicRoom {
  id: string
  connection_id: number
  external_id: string
  label: string
  kind: string
  conversation_type: string
}

export interface TopicTask {
  id: string
  label: string
  objective: string | null
  status: string
  agent_id: number | null
  agent_name: string | null
  created_at: string | null
}

export interface TopicRound {
  id: string
  room_id: string
  room_label: string
  status: string
  preview: string
  response: string
  created_at: string
}

export interface TopicVoiceTurn extends TopicRound {
  session_id: string
  sequence: number
}

export interface TopicContent {
  topic: Topic
  summary: TopicContentSummary
  rooms: TopicRoom[]
  tasks: TopicTask[]
  conversation_rounds: TopicRound[]
  voice_turns: TopicVoiceTurn[]
  memories: TopicLinkedMemory[]
  documents: TopicRelatedDocument[]
}
