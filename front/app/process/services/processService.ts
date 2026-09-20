import { api } from '@/core/api'

export interface ProcessDefinition {
  id: number
  agent_id: number | null
  tool_id: number
  engine_process_id: string
  label: string
  description: string | null
  created_at: string
  updated_at: string | null
}

export type ProcessDefinitionCreate = Omit<ProcessDefinition, 'id' | 'created_at' | 'updated_at'>
export interface ProcessDefinitionUpdate {
  description?: string | null
}

export interface ProcessRunEvent {
  id: number
  event_id: string | null
  source: string
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface ProcessLLMCall {
  id: string
  task_id: string | null
  purpose: string | null
  provider_name: string
  requested_model: string
  effective_model: string
  status: string
  duration: number
  input_tokens: number
  cache_read_tokens: number
  output_tokens: number
  total_tokens: number
  cost: number
  error: string | null
  started_at: string
}

export type ProcessRunStatus =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'success'
  | 'error'
  | 'cancelling'
  | 'cancelled'
  | 'unknown'

export interface ProcessRun {
  id: string
  process_id: number
  workflow_id: string | null
  process_label: string | null
  launcher_agent_id: number
  launcher_agent_code: string | null
  tool_code: string
  engine_run_id: string | null
  correlation_id: string
  status: ProcessRunStatus
  input: Record<string, unknown>
  output: Record<string, unknown> | null
  engine_metadata: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string | null
  fresh: boolean
  summary: string
  events?: ProcessRunEvent[]
  task_ids?: string[]
  llm_calls?: ProcessLLMCall[]
}

export interface ProcessRunPage {
  items: ProcessRun[]
  total: number
  page: number
  page_size: number
}

export interface ProcessTool {
  id: number
  code: string
  label: string
}

export interface ToolProcessDefinition {
  engine_process_id: string
  label: string
  description: string | null
  active: boolean
}

export interface ProcessEngineHealth {
  tool_code: string
  status: 'healthy' | 'degraded' | 'error'
  reachable: boolean
  authenticated: boolean
  supports_cancel: boolean
  cancel_mode: 'supported' | 'best_effort' | 'unsupported'
  message: string
  details: string[]
  checked_at: string
}

export interface ProcessOperations {
  status_counts: Record<string, number>
  pending_start_jobs: number
  stale_active_runs: number
  failed_last_24h: number
  oldest_pending_job_seconds: number | null
  checked_at: string
}

export interface ProcessAnalysis {
  run_id: string
  success: boolean
  status: string
  summary: string
  duration_seconds: number | null
  failed_steps: string[]
  agent_calls: Record<string, unknown>[]
  llm_calls: Record<string, unknown>[]
  recommendations: string[]
}

export interface AgentOption {
  id: number
  code: string
  first_name: string
  last_name: string
  has_avatar: boolean
}

export const processService = {
  async tools(): Promise<ProcessTool[]> {
    return (await api.get('/processes/tools')).data
  },
  async toolHealth(toolCode: string): Promise<ProcessEngineHealth> {
    return (await api.get(`/processes/tools/${toolCode}/health`)).data
  },
  async operations(agentId?: number): Promise<ProcessOperations> {
    return (await api.get('/processes/operations', {
      params: { agent_id: agentId },
    })).data
  },
  async definitions(agentId?: number): Promise<ProcessDefinition[]> {
    return (await api.get('/processes/definitions', {
      params: { agent_id: agentId },
    })).data
  },
  async createDefinition(data: ProcessDefinitionCreate): Promise<ProcessDefinition> {
    return (await api.post('/processes/definitions', data)).data
  },
  async updateDefinition(id: number, data: ProcessDefinitionUpdate): Promise<ProcessDefinition> {
    return (await api.put(`/processes/definitions/${id}`, data)).data
  },
  async deleteDefinition(id: number): Promise<void> {
    await api.delete(`/processes/definitions/${id}`)
  },
  async syncDefinitions(toolCode: string): Promise<ToolProcessDefinition[]> {
    return (await api.post('/processes/definitions/sync', null, { params: { tool_code: toolCode } })).data
  },
  async runs(params: {
    agentId?: number
    processId?: number
    workflowId?: string
    status?: ProcessRunStatus
    active?: boolean | null
    page?: number
    pageSize?: number
    search?: string
    createdAfter?: string
    createdBefore?: string
    sortBy?: string
    descending?: boolean
  } = {}): Promise<ProcessRunPage> {
    return (await api.get('/processes/runs', { params: {
      agent_id: params.agentId,
      process_id: params.processId,
      workflow_id: params.workflowId,
      status: params.status,
      active: params.active ?? undefined,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 50,
      search: params.search || undefined,
      created_after: params.createdAfter,
      created_before: params.createdBefore,
      sort_by: params.sortBy || 'created_at',
      descending: params.descending ?? true,
    } })).data
  },
  async run(id: string): Promise<ProcessRun> {
    return (await api.get(`/processes/runs/${id}`)).data
  },
  async deleteRun(id: string): Promise<void> {
    await api.delete(`/processes/runs/${id}`)
  },
  async startRun(data: { agent_id: number; workflow_id: string; input: Record<string, unknown>; files: never[]; wait_for_completion: boolean }): Promise<Record<string, unknown>> {
    return (await api.post('/processes/runs', data)).data
  },
  async refreshRun(id: string): Promise<ProcessRun> {
    return (await api.post(`/processes/runs/${id}/refresh`)).data
  },
  async cancelRun(id: string): Promise<ProcessRun> {
    return (await api.post(`/processes/runs/${id}/cancel`)).data
  },
  async retryRun(id: string): Promise<Record<string, unknown>> {
    return (await api.post(`/processes/runs/${id}/retry`)).data
  },
  async analyzeRun(id: string): Promise<ProcessAnalysis> {
    return (await api.post(`/processes/runs/${id}/analyze`)).data
  },
  async agents(): Promise<AgentOption[]> {
    return (await api.get('/agents', { params: { limit: 500 } })).data
  },
}
