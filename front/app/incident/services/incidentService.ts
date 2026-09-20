import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export type FailureKind = 'llm' | 'tool'
export type FailurePatternStatus =
  | 'new'
  | 'triaged'
  | 'fix_planned'
  | 'resolved'
  | 'ignored'
  | 'regression'

export interface FailurePattern {
  id: string
  fingerprint: string
  fingerprint_version: number
  kind: FailureKind
  category: string
  title: string
  status: FailurePatternStatus
  occurrence_count: number
  first_seen_at: string
  last_seen_at: string
  diagnosis: string
  root_cause: string
  remediation: string
  fixed_by_commit: string
  regression_test: string
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface FailureIncident {
  id: string
  pattern_id: string
  pattern_status: FailurePatternStatus
  pattern_occurrence_count: number
  causal_incident_id: string | null
  idempotency_key: string
  kind: FailureKind
  category: string
  phase: string
  severity: string
  error_type: string
  error_code: string | null
  error_message: string
  retryable: boolean | null
  attempt_number: number | null
  retry_limit: number | null
  will_retry: boolean | null
  recovered_at: string | null
  task_id: string | null
  task_attempt_id: string | null
  llm_call_id: string | null
  conversation_round_id: string | null
  process_run_id: string | null
  agent_id: number | null
  run_uuid: string | null
  driver_code: string | null
  provider_code: string | null
  model_code: string | null
  tool_name: string | null
  tool_call_external_id: string | null
  occurred_at: string
  created_at: string
}

export interface FailureIncidentDetail extends FailureIncident {
  pattern: FailurePattern
  trace_schema_version: string
  trace: Record<string, unknown>
  redacted_fields: string[]
  truncated_fields: string[]
  trace_content_hash: string
  trace_byte_size: number
}

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface IncidentFilters {
  page: number
  page_size: number
  kind?: FailureKind
  recovered?: boolean
  search?: string
}

export interface PatternFilters {
  page: number
  page_size: number
  kind?: FailureKind
  status?: FailurePatternStatus
  search?: string
}

export type FailurePatternUpdate = Partial<Pick<
  FailurePattern,
  'status' | 'diagnosis' | 'root_cause' | 'remediation' | 'fixed_by_commit' | 'regression_test'
>>

export const incidentService = {
  listIncidents(params: IncidentFilters): Promise<AxiosResponse<Page<FailureIncident>>> {
    return api.get('/incidents', { params })
  },
  getIncident(id: string): Promise<AxiosResponse<FailureIncidentDetail>> {
    return api.get(`/incidents/${id}`)
  },
  listPatterns(params: PatternFilters): Promise<AxiosResponse<Page<FailurePattern>>> {
    return api.get('/incidents/patterns', { params })
  },
  updatePattern(
    id: string,
    data: FailurePatternUpdate,
  ): Promise<AxiosResponse<FailurePattern>> {
    return api.patch(`/incidents/patterns/${id}`, data)
  },
}
