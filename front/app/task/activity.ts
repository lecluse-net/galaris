import type { AIResult } from './types'

export interface TaskStartupTiming {
  task_id: string
  label: string
  preparation_started_at: string | null
  preparation_finished_at: string | null
  enqueued_at: string | null
  first_claimed_at: string | null
  preparation_seconds: number | null
  preparation_source?: 'observed' | 'llm_calls'
  preparation_to_first_call_seconds?: number | null
  admission_seconds: number | null
  queue_wait_upper_bound_seconds: number | null
  lifecycle_seconds?: Record<string, number>
  lifecycle_observed_since?: string | null
  phase_seconds?: Record<string, Record<string, number>>
  processing_intervals?: { call_id: string; purpose: string | null; started_at: string; completed_at: string | null; seconds: number }[]
}

export interface TaskActivitySnapshot {
  task_id: string
  startup_timing?: TaskStartupTiming | null
  revision: number
  phase: string
  operational: {
    operational_state: 'QUEUED' | 'RUNNING' | 'WAITING' | 'PAUSED' | 'TERMINAL'
    resume_phase: string
    waits: { kind: string; question?: string; peer_display?: string; process_label?: string }[]
  }
  pause_pending: boolean
  attempt_number: number
  attempt_status: string | null
  latest_attempt?: { id: string; attempt_number: number; status: string; phase: string } | null
  last_activity_at: string | null
  next_attempt_at: string | null
  run_id: string | null
  streams_ai_messages: boolean
  calls_limited?: boolean
  live: { run_id: string; attempt_id?: string | null; sequence: number; result: AIResult } | null
  original_demand?: string | null
  parent_task_id?: string | null
  source_task_id?: string | null
  messenger_message_id?: string | null
  delivery_policy?: string | null
  resources?: { type: string; reference: string; label: string; state: string; producer_task_id: string | null }[]
}

/** Independent consumers keep a room alive until the last one leaves. */
export function roomReferences(join: (id: string) => void, leave: (id: string) => void) {
  const counts = new Map<string, number>()
  return {
    retain(id: string) {
      const count = counts.get(id) ?? 0
      counts.set(id, count + 1)
      if (!count) join(id)
    },
    release(id: string) {
      const count = counts.get(id) ?? 0
      if (count > 1) counts.set(id, count - 1)
      else if (count) { counts.delete(id); leave(id) }
    },
  }
}
