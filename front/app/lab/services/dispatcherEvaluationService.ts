import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export type DispatcherRoute = 'EXEC' | 'BRIEFING' | 'PLAN' | 'END'
export type DispatcherEffort = 'standard' | 'high'
export type EvaluationRunStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'

export interface DispatcherDecision {
  reasoning: string
  route: DispatcherRoute
  effort: DispatcherEffort
  language: string
}

export interface DispatcherDataset {
  id: string
  revision: number
  mechanism: string
  name: string
  description: string
  case_count: number
  ready_case_count: number
  created_at: string
  updated_at?: string | null
}

export interface DispatcherCase {
  id: string
  revision: number
  dataset_id: string
  derived_from_case_id?: string | null
  source_task_id?: string | null
  source_task_revision?: number | null
  name: string
  enabled: boolean
  readiness: 'draft' | 'ready'
  input_data: Record<string, unknown>
  expected_output: DispatcherDecision
  reference: Record<string, unknown>
  source_capture: Record<string, unknown>
  created_at: string
  updated_at?: string | null
}

export interface DispatcherTaskCandidate {
  task_id: string
  revision: number
  label: string
  objective?: string | null
  status: string
  agent_name?: string | null
  driver?: string | null
  created_at?: string | null
}

export interface DispatcherRun {
  id: string
  dataset_id: string
  llm_id?: number | null
  judge_llm_id?: number | null
  status: EvaluationRunStatus
  score_version: string
  llm_snapshot: Record<string, unknown>
  judge_llm_snapshot: Record<string, unknown>
  total_cases: number
  completed_cases: number
  score_percent?: number | null
  structured_score_percent?: number | null
  cost: number
  analysis_markdown?: string | null
  analysis_llm_snapshot: Record<string, unknown>
  analysis_cost: number
  analysis_language?: string | null
  analysis_created_at?: string | null
  error?: string | null
  cancel_requested: boolean
  started_at?: string | null
  finished_at?: string | null
  created_at: string
}

export interface DispatcherRunCase {
  id: string
  run_id: string
  case_id?: string | null
  case_snapshot: DispatcherCase
  actual_output?: DispatcherDecision | null
  score_details: Record<string, unknown>
  judge_output?: Record<string, unknown> | null
  score_percent: number
  structured_score_percent: number
  cost: number
  duration: number
  error?: string | null
  created_at: string
}

export interface DispatcherRunDetail extends DispatcherRun {
  results: DispatcherRunCase[]
}

export interface DispatcherCaseUpdate {
  revision: number
  input_data: Record<string, unknown>
  expected_output: DispatcherDecision
}

export const dispatcherEvaluationService = {
  datasets(): Promise<AxiosResponse<DispatcherDataset[]>> {
    return api.get('/evaluation/dispatcher/datasets')
  },
  createDataset(name: string, description = ''): Promise<AxiosResponse<DispatcherDataset>> {
    return api.post('/evaluation/dispatcher/datasets', { name, description, mechanism: 'dispatcher' })
  },
  updateDataset(dataset: DispatcherDataset): Promise<AxiosResponse<DispatcherDataset>> {
    return api.patch(`/evaluation/dispatcher/datasets/${dataset.id}`, {
      revision: dataset.revision,
      name: dataset.name,
      description: dataset.description,
    })
  },
  deleteDataset(id: string): Promise<AxiosResponse<void>> {
    return api.delete(`/evaluation/dispatcher/datasets/${id}`)
  },
  cases(datasetId: string): Promise<AxiosResponse<DispatcherCase[]>> {
    return api.get(`/evaluation/dispatcher/datasets/${datasetId}/cases`)
  },
  createCase(datasetId: string, name: string): Promise<AxiosResponse<DispatcherCase>> {
    return api.post(`/evaluation/dispatcher/datasets/${datasetId}/cases`, { name })
  },
  candidates(search = ''): Promise<AxiosResponse<DispatcherTaskCandidate[]>> {
    return api.get('/evaluation/dispatcher/candidates', {
      params: { search: search || undefined, limit: 50 },
    })
  },
  importTask(datasetId: string, taskId: string, confirmation_token?: string): Promise<AxiosResponse<DispatcherCase>> {
    return api.post(`/evaluation/dispatcher/datasets/${datasetId}/cases/from-task`, { task_id: taskId, confirmation_token })
  },
  updateCase(id: string, data: DispatcherCaseUpdate): Promise<AxiosResponse<DispatcherCase>> {
    return api.patch(`/evaluation/dispatcher/cases/${id}`, data)
  },
  duplicateCase(id: string): Promise<AxiosResponse<DispatcherCase>> {
    return api.post(`/evaluation/dispatcher/cases/${id}/duplicate`)
  },
  restoreCase(id: string, confirmation_token?: string): Promise<AxiosResponse<DispatcherCase>> {
    return api.post(`/evaluation/dispatcher/cases/${id}/restore-source`, { confirmation_token })
  },
  generateExpected(
    id: string,
    inputData: Record<string, unknown>,
  ): Promise<AxiosResponse<{
    output: DispatcherDecision
    llm: Record<string, unknown>
    cost: number
  }>> {
    return api.post(`/evaluation/dispatcher/cases/${id}/generate-expected`, {
      input_data: inputData,
    })
  },
  deleteCase(id: string): Promise<AxiosResponse<void>> {
    return api.delete(`/evaluation/dispatcher/cases/${id}`)
  },
  runs(datasetId: string): Promise<AxiosResponse<DispatcherRun[]>> {
    return api.get(`/evaluation/dispatcher/datasets/${datasetId}/runs`, { params: { limit: 50 } })
  },
  startRun(datasetId: string, llmId: number): Promise<AxiosResponse<DispatcherRun>> {
    return api.post(`/evaluation/dispatcher/datasets/${datasetId}/runs`, {
      llm_id: llmId,
    })
  },
  run(id: string): Promise<AxiosResponse<DispatcherRunDetail>> {
    return api.get(`/evaluation/dispatcher/runs/${id}`)
  },
  analyzeRun(id: string, language: 'fr' | 'en' | 'zh'): Promise<AxiosResponse<DispatcherRunDetail>> {
    return api.post(`/evaluation/dispatcher/runs/${id}/analyze`, { language })
  },
  cancelRun(id: string): Promise<AxiosResponse<DispatcherRun>> {
    return api.post(`/evaluation/dispatcher/runs/${id}/cancel`)
  },
}
