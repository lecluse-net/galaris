import api from '@/core/api'
import type { LabConfig } from './evaluationService'
import type { EvaluationMechanism } from './mechanismEvaluationService'

export type LabKey = EvaluationMechanism | 'dispatcher' | 'task_analysis'
export interface JsonSchema {
  type?: string; title?: string; description?: string; default?: unknown
  enum?: unknown[]; const?: unknown; minimum?: number; maximum?: number
  properties?: Record<string, JsonSchema>; $defs?: Record<string, JsonSchema>
  $ref?: string; anyOf?: JsonSchema[]; oneOf?: JsonSchema[]
}
export interface LabContract {
  key: LabKey; variable_name: string; variable_schema: JsonSchema
  parameters_schema: JsonSchema; parameter_defaults: Record<string, unknown>
  context_schema: JsonSchema; context_defaults: Record<string, unknown>
  result_name: string; treatment: string
}
export interface LabDescriptor {
  key: LabKey; contract: LabContract; configuration_schema: JsonSchema
  algorithm: Record<string, unknown>; source_import: boolean
  executor: 'task' | 'conversation' | 'voice' | null
}
export interface LabInput { variable_value: unknown; context?: Record<string, unknown> }
export interface SyntheticDatasetRequest {
  name: string; instructions: string; count: number; language: 'fr' | 'en' | 'zh'
  llm_id: number | null; categories: string[]
  source_dataset_id?: string; source_revision?: number
}
export interface LabDataset {
  purpose: DatasetPurpose
  id: string; revision: number; name: string; description: string
  parameters: Record<string, unknown>; configuration: Record<string, unknown>
  prompt_suffix: string | null; case_count: number; ready_case_count: number
}
export interface LabCase {
  categories: string[]
  id: string; revision: number; name: string; readiness: string; enabled: boolean
  input_data: LabInput; expected_output: unknown; source_capture: Record<string, unknown>
}
export interface LabResult {
  id: string; repetition: number; case_snapshot: { id?: string; categories?: string[]; name: string; input_data: LabInput; resolved_input: unknown; expected_output: unknown }
  actual_output: unknown; error: string | null; verdict: string | null
  score_percent: number | null; score_details: Record<string, unknown>
  judge_output: JudgeOutput | null; cost: number; duration: number
}
export interface JudgmentCampaign {
  id: string; created_at: string; status: string; configuration: { rubric?: Rubric } & Record<string, unknown>
  results: Array<{ result_id: string; status: string; verdict: string; output: unknown; cost: number; duration: number }>
}
export interface LabRun {
  repetitions: number; max_cost: number | null; stop_reason: string | null
  id: string; status: string; phase: string; completed_cases: number; judged_cases: number
  total_cases: number; score_percent: number | null; candidate_cost: number; judge_cost: number
  created_at: string; llm_snapshot: Record<string, unknown>; judge_llm_snapshot: Record<string, unknown>
  configuration_snapshot: { rubric?: Rubric } & Record<string, unknown>; results: LabResult[]; campaigns: JudgmentCampaign[]
  analysis_markdown: string | null
}
export interface LabPreview {
  candidate_prompt: string; system_prompt: string
  input: LabInput; native_input: unknown; configuration: Record<string, unknown>
  parameters: Record<string, unknown>
  origins: Record<string, 'dataset' | 'item'>
}
const base = (key: LabKey) => `/evaluation/${key}`
export const labWorkbenchService = {
  async generateDataset(key: LabKey, data: SyntheticDatasetRequest) {
    return (await api.post<{ dataset: LabDataset; cost: number }>(`${base(key)}/datasets/synthetic`, data, { timeout: 200000 })).data
  },
  async review(key: LabKey, id: string, campaign_id?: string) { return (await api.get<ReviewQueue>(`${base(key)}/runs/${id}/human-review`, { params: { campaign_id } })).data },
  async submitReview(key: LabKey, id: string, data: ReviewSubmission) { return (await api.post<ReviewQueue>(`${base(key)}/runs/${id}/human-review`, data)).data },
  async config() { return (await api.get<LabConfig>('/evaluation/config')).data },
  async descriptors() { return (await api.get<LabDescriptor[]>('/evaluation/mechanisms')).data },
  async datasets(key: LabKey) { return (await api.get<LabDataset[]>(`${base(key)}/datasets`)).data },
  async createDataset(key: LabKey, name: string) { return (await api.post<LabDataset>(`${base(key)}/datasets`, { name })).data },
  async saveDataset(key: LabKey, dataset: LabDataset) {
    return (await api.patch<LabDataset>(`${base(key)}/datasets/${dataset.id}`, {
      purpose: dataset.purpose, revision: dataset.revision, name: dataset.name, description: dataset.description,
      parameters: dataset.parameters, configuration: dataset.configuration, prompt_suffix: dataset.prompt_suffix,
    })).data
  },
  async deleteDataset(key: LabKey, id: string) { await api.delete(`${base(key)}/datasets/${id}`) },
  async cases(key: LabKey, dataset: string) { return (await api.get<LabCase[]>(`${base(key)}/datasets/${dataset}/cases`)).data },
  async createCase(key: LabKey, dataset: string, name: string) { return (await api.post<LabCase>(`${base(key)}/datasets/${dataset}/cases`, { name })).data },
  async saveCase(key: LabKey, item: LabCase) {
    return (await api.patch<LabCase>(`${base(key)}/cases/${item.id}`, {
      categories: item.categories, revision: item.revision, name: item.name, input_data: item.input_data, expected_output: item.expected_output,
    })).data
  },
  async deleteCase(key: LabKey, id: string) { await api.delete(`${base(key)}/cases/${id}`) },
  async preview(key: LabKey, dataset: string, value: LabInput) { return (await api.post<LabPreview>(`${base(key)}/datasets/${dataset}/preview`, value)).data },
  async expected(key: LabKey, id: string, value: LabInput) {
    return (await api.post<{ output: unknown }>(`${base(key)}/cases/${id}/generate-expected`, { input_data: value })).data
  },
  async runs(key: LabKey, dataset: string) { return (await api.get<LabRun[]>(`${base(key)}/datasets/${dataset}/runs`, { params: { limit: 500 } })).data },
  async run(key: LabKey, id: string) { return (await api.get<LabRun>(`${base(key)}/runs/${id}`)).data },
  async start(key: LabKey, dataset: string, llm_id: number, judge_llm_id: number, repetitions = 1, max_cost: number | null = null) {
    return (await api.post<LabRun>(`${base(key)}/datasets/${dataset}/runs`, { llm_id, judge_llm_id, repetitions, max_cost })).data
  },
  async cancel(key: LabKey, id: string) { return (await api.post<LabRun>(`${base(key)}/runs/${id}/cancel`)).data },
  async resume(key: LabKey, id: string) { return (await api.post<LabRun>(`${base(key)}/runs/${id}/resume`)).data },
  async analyze(key: LabKey, id: string, language: string) { return (await api.post<LabRun>(`${base(key)}/runs/${id}/analyze`, { language })).data },
  async rejudge(key: LabKey, id: string, judge_llm_id: number) { return (await api.post<LabRun>(`${base(key)}/runs/${id}/rejudge`, { judge_llm_id })).data },
  async captureTask(key: LabKey, dataset: string, task_id: string, confirmation_token?: string) {
    return (await api.post<LabCase>(`${base(key)}/datasets/${dataset}/cases/from-task`, { task_id, confirmation_token })).data
  },
  async candidates(key: LabKey, search: string) { return (await api.get<Array<Record<string, unknown>>>(`${base(key)}/candidates`, { params: { search, limit: 500 } })).data },
  async captureSource(key: LabKey, dataset: string, source_id: string, confirmation_token?: string) {
    return (await api.post<LabCase>(`${base(key)}/datasets/${dataset}/cases/from-source`, { source_id, confirmation_token })).data
  },
}

export type DatasetPurpose = 'work' | 'validation' | 'holdout'
export const categories = ['nominal', 'ambiguity', 'incomplete', 'multilingual', 'robustness', 'security', 'incident', 'alternative'] as const
export interface Rubric { version: string; dimensions: Array<{ code: string; label: string; criteria: string; weight_percent: number }> }
export interface DimensionScore { code: string; score_percent: number; assessment: string }
export interface JudgeOutput { dimensions?: DimensionScore[]; explanation?: string; strengths?: string[]; weaknesses?: string[]; critical_failures?: string[]; error?: string }
export interface ReviewSubmission { campaign_id: string; result_id: string; dimensions: DimensionScore[]; critical_failures: string[]; explanation: string }
export interface ReviewItem {
  result_id: string; name: string; repetition: number; input: unknown; reference: unknown; output: unknown
  assessment: JudgeOutput | null; human_score: number | null; human_verdict: string | null
  judge: { score_percent: number | null; verdict: string; output: JudgeOutput | null } | null
}
export interface ReviewQueue { campaign_id: string; rubric: Rubric; parameters: Record<string, unknown>; items: ReviewItem[] }
