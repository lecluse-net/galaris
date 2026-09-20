import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export type AnalysisVerdict = 'success' | 'partial' | 'failure' | 'inconclusive'
export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type RecommendationPriority = 'high' | 'medium' | 'low'
export type RecommendationScope =
  | 'task'
  | 'agent'
  | 'model'
  | 'tools'
  | 'skills'
  | 'connections'
  | 'runtime'
  | 'external'

export interface LabTaskSummary {
  task_id: string
  revision: number
  label: string
  objective?: string | null
  status: string
  paused: boolean
  effort: string
  forced_route?: string | null
  forced_effort?: string | null
  feedback?: string | null
  last_error?: string | null
  cost: number
  attempt_count: number
  agent_id?: number | null
  agent_name?: string | null
  agent_code?: string | null
  driver?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface LabTaskReference {
  task_id: string
  task?: LabTaskSummary | null
}

export interface LabConfig {
  lab_llm_id: number | null
  llms: Array<{ id: number; code: string; label: string; model: string }>
}

export interface EvidenceCoverage {
  task_count: number
  attempt_count: number
  llm_call_count: number
  tool_call_count: number
  process_run_count: number
  has_agent_configuration: boolean
  has_final_result: boolean
  truncated: boolean
}

export interface AnalysisFinding {
  title: string
  severity: FindingSeverity
  observation: string
  impact: string
  evidence: string[]
}

export interface AnalysisRootCause {
  cause: string
  confidence: number
  evidence: string[]
}

export interface AnalysisRecommendation {
  scope: RecommendationScope
  priority: RecommendationPriority
  action: string
  rationale: string
  expected_impact: string
  where_to_change: string
  evidence: string[]
}

export interface TaskAnalysis {
  id: string
  task_id: string
  task_revision: number
  language: 'fr' | 'en' | 'zh'
  prompt_version: string
  verdict: AnalysisVerdict
  confidence: number
  summary: string
  goal_assessment: string
  observed_outcome: string
  strengths: string[]
  findings: AnalysisFinding[]
  root_causes: AnalysisRootCause[]
  recommendations: AnalysisRecommendation[]
  missing_evidence: string[]
  next_questions: string[]
  evidence: EvidenceCoverage
  model: string
  duration: number
  cost: number
  created_at: string
  created_by?: number | null
}

export const evaluationService = {
  config(): Promise<AxiosResponse<LabConfig>> {
    return api.get('/evaluation/config')
  },
  candidates(search = ''): Promise<AxiosResponse<LabTaskSummary[]>> {
    return api.get('/evaluation/candidates', { params: { search: search || undefined, limit: 50 } })
  },
  tasks(): Promise<AxiosResponse<LabTaskReference[]>> {
    return api.get('/evaluation/tasks')
  },
  addTask(taskId: string): Promise<AxiosResponse<LabTaskReference>> {
    return api.post('/evaluation/tasks', { task_id: taskId })
  },
  removeTask(taskId: string): Promise<AxiosResponse<void>> {
    return api.delete(`/evaluation/tasks/${taskId}`)
  },
  diagnoses(taskId: string): Promise<AxiosResponse<TaskAnalysis[]>> {
    return api.get(`/evaluation/tasks/${taskId}/diagnoses`, { params: { limit: 50 } })
  },
  analyzeTask(
    taskId: string,
    language: 'fr' | 'en' | 'zh',
    userContext: string,
  ): Promise<AxiosResponse<TaskAnalysis>> {
    return api.post(`/evaluation/tasks/${taskId}/analyze`, {
      language,
      user_context: userContext,
    })
  },
}
