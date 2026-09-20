export type DreamRuntimeStatus =
  | 'disabled'
  | 'stopped'
  | 'starting'
  | 'running'
  | 'paused_voice'
  | 'paused_tasks'
  | 'idle'
  | 'unavailable'
  | 'faulted'

export type DreamRuntimePhase =
  | 'stopped'
  | 'starting'
  | 'checking'
  | 'claiming'
  | 'preparing'
  | 'applying'
  | 'waiting'
  | 'faulted'

export type DreamRuntimeReason =
  | 'not_started'
  | 'startup'
  | 'disabled'
  | 'voice_active'
  | 'task_active'
  | 'checking_activity'
  | 'checking_mechanism'
  | 'claiming_subject'
  | 'preparing_subject'
  | 'applying_subject'
  | 'cycle_completed'
  | 'no_eligible_subject'
  | 'mechanism_unavailable'
  | 'worker_error'
  | 'stopping'

export type DreamReceiptStatus = 'running' | 'retry' | 'success' | 'error'

export type DreamMechanismKey =
  | 'topic.classify_message'
  | 'topic.classify_voice_turn'
  | 'topic.classify_task'
  | 'topic.classify_voice_session'
  | 'memory.extract_task'
  | 'memory.attachment_text'
  | 'memory.attachment_document'
  | 'memory.attachment_image'
  | 'memory.attachment_video'
  | 'memory.extract_conversation_round'
  | 'memory.reflect_task_outcome'
  | 'skill.learn_task_outcome'
  | 'memory.extract_voice_turn'
  | 'memory.link_topic_source'
  | 'memory.project_process'
  | 'memory.maintain_findings'
  | 'topic.suggest_maintenance'
  | 'memory.forget_stale'

export interface DreamRuntimeView {
  status: DreamRuntimeStatus
  phase: DreamRuntimePhase
  reason: DreamRuntimeReason
  worker_running: boolean
  current_mechanism: string | null
  current_subject_kind: string | null
  current_subject_id: string | null
  last_cycle_at: string | null
  last_cycle_finished_at: string | null
  next_cycle_at: string | null
  state_changed_at: string | null
  cycle_count: number
  last_error_type: string | null
}

export interface DreamMechanismSummary {
  mechanism_key: DreamMechanismKey
  pending: number
  running: number
  retry: number
  success: number
  error: number
  result_count: number
  cost: number
}

export interface DreamOverview {
  runtime: DreamRuntimeView
  total_operations: number
  completed_operations: number
  pending_operations: number
  terminal_tasks: number
  unscanned_tasks: number
  running_receipts: number
  retry_receipts: number
  successful_receipts: number
  error_receipts: number
  memories_created: number
  memories_linked: number
  total_cost: number
  mechanisms: DreamMechanismSummary[]
}

export interface DreamReceiptSummary {
  id: string
  mechanism_key: string
  subject_kind: string
  subject_id: string
  status: DreamReceiptStatus
  attempts: number
  result_count: number
  cost: number
  created_at: string
  updated_at: string
  available_at: string
  subject_preview: string | null
  task_label: string | null
  task_status: string | null
  agent_id: number | null
}

export interface DreamReceiptDetail extends DreamReceiptSummary {
  lease_owner: string | null
  lease_expires_at: string | null
  last_error: string | null
  prepared_payload: Record<string, unknown> | null
  llm_calls: LLMCall[]
}

export interface DreamReceiptPage {
  items: DreamReceiptSummary[]
  total: number
  page: number
  page_size: number
}

export interface ProposedMemory {
  action?: 'CREATE'
  title: string
  content: string
  memory_type?: string
  keywords?: string[]
}

export interface LinkedMemory {
  action: 'LINK'
  target_memory_id: string
  reason?: string
}

export type MemoryExtractionOperation = ProposedMemory | LinkedMemory

export interface DreamOutcomeEvidenceItem {
  reference: string
  kind: string
  status?: string
  name?: string
  detail?: string
}

export interface DreamOutcomeDiagnostics {
  significanceReason: string
  applicationMode: string
  included: boolean
  observations: DreamOutcomeEvidenceItem[]
}
import type { LLMCall } from '@/app/llm/types'
