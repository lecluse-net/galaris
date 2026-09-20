import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export type EvaluationMechanism =
  | 'task_analysis'
  | 'briefing'
  | 'planner'
  | 'topic_classification'
  | 'memory_extraction'
  | 'outcome_reflection'
  | 'goal_tracking'
  | 'task_executor'
  | 'conversation_executor'
  | 'voice_executor'
export type EvaluationValueFormat = 'json' | 'text'
export type ExecutorPromptKind = 'task' | 'conversation' | 'voice'
export type LabCaptureTarget =
  | 'task_analysis'
  | 'dispatcher'
  | 'briefing'
  | 'planner'
  | 'task_executor'
  | 'conversation_executor'
  | 'voice_executor'
export type EvaluationRunStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'
export type EvaluationValue = unknown
export const MEMORY_EXTRACTION_MAX_MEMORIES = 10

export interface TopicLabIdentity {
  id: string
  display_name: string
  agent_id?: number | null
  connection_id?: number | null
  tool_id?: number | null
}

export interface TopicLabRoom {
  id: string
  label: string
  kind: 'direct' | 'group'
  users: TopicLabIdentity[]
  connection_id?: number | null
  tool_id?: number | null
}

export interface TopicLabMessage {
  id: string
  platform: string
  tool_id?: number | null
  sender: TopicLabIdentity | null
  recipient?: TopicLabIdentity | null
  room: TopicLabRoom | null
  text: string
  attachments: unknown[]
  reply_to?: string | null
  time: number
}

export interface TopicLabTopic {
  title: string
  description: string
  keywords: string[]
}

export interface TopicDetectionLabInput {
  messages: TopicLabMessage[]
  initial_topic: TopicLabTopic | null
}

export interface TopicDetectionLabOutput {
  topics: string[]
}

export interface TopicDetectionLabPrompts {
  continuity_system_prompt: string
  resolution_system_prompt: string
}

export interface TopicDatasetConfiguration {
  schema: 'galaris.topic-lab-configuration/v1'
  topics: TopicLabTopic[]
  prompts: TopicDetectionLabPrompts
}


export interface TopicMessageAgent {
  id: number
  label: string
  message_count: number
}

export interface TopicMessagePerson {
  connection_id: number
  user_id: string
  label: string
  platform: string
  message_count: number
}

export interface TopicMessagePreview {
  journal_message_id: string
  message: TopicLabMessage
  role: 'human' | 'assistant'
  occurred_at: string
  detected_topic?: string | null
}

export interface TopicMessageRangePreview {
  agent_id: number
  connection_id: number
  user_id: string
  date_from: string
  date_to: string
  total_count: number
  truncated: boolean
  messages: TopicMessagePreview[]
}

export interface TopicMessageRangeFilter {
  agent_id: number
  connection_id: number
  user_id: string
  date_from: string
  date_to: string
  name?: string | null
}

export interface MechanismDescriptor {
  key: EvaluationMechanism
  input_format: EvaluationValueFormat
  output_format: EvaluationValueFormat
  source_import: boolean
  executor?: ExecutorPromptKind | null
}

export interface MechanismDataset {
  id: string
  revision: number
  mechanism: EvaluationMechanism
  name: string
  description: string
  prompt_suffix?: string | null
  configuration: Record<string, unknown>
  case_count: number
  ready_case_count: number
  created_at: string
  updated_at?: string | null
}

export interface MechanismCase {
  id: string
  revision: number
  dataset_id: string
  derived_from_case_id?: string | null
  source_task_id?: string | null
  source_task_revision?: number | null
  name: string
  enabled: boolean
  readiness: 'draft' | 'ready'
  input_data: EvaluationValue
  expected_output: EvaluationValue
  reference: Record<string, unknown>
  source_capture: Record<string, unknown>
  created_at: string
  updated_at?: string | null
}

export interface MechanismSourceCandidate {
  source_id: string
  source_kind: 'llm_call' | 'messenger_message' | 'task' | 'conversation_round' | 'voice_turn'
  call_id?: string | null
  task_id?: string | null
  label: string
  model: string
  created_at: string
  input_preview: string
}

export type MemoryExtractionSourceKind = 'task' | 'conversation_round' | 'voice_turn'

export interface MemoryExtractionMessage {
  speaker_name: string
  speaker_kind: 'human' | 'AI'
  text: string
}

export interface MemoryExtractionExistingMemory {
  id: string
  title: string
  content: string
  memory_type: 'core' | 'working' | 'episodic' | 'semantic' | 'procedural' | 'social'
  keywords: string[]
  score: number
}

export interface MemoryExtractionInput {
  source_kind: MemoryExtractionSourceKind
  topic: Record<string, unknown>
  history: MemoryExtractionMessage[]
  current: MemoryExtractionMessage[]
  task_trace: Record<string, unknown> | null
  existing_memories: MemoryExtractionExistingMemory[]
}

export type MemoryExtractionOperation =
  | {
    action: 'CREATE'
    title: string
    content: string
    memory_type: MemoryExtractionExistingMemory['memory_type']
    keywords: string[]
    retention_reason: string
    future_utility: 'high'
    reason: string
  }
  | { action: 'LINK', target_memory_id: string, reason: string }

export interface MemoryExtractionOutput {
  operations: MemoryExtractionOperation[]
  relevant_memory_ids: string[]
  ranked_memory_ids: string[]
}

export interface MemoryExtractionDatasetConfiguration {
  schema: 'galaris.memory-extraction-lab-configuration'
  system_prompt: string
}

export interface PlannerDatasetConfiguration {
  schema: 'galaris.planner-lab-configuration'
  system_prompt: string
}

export interface MechanismRun {
  id: string
  dataset_id: string
  llm_id?: number | null
  judge_llm_id?: number | null
  status: EvaluationRunStatus
  score_version: string
  llm_snapshot: Record<string, unknown>
  judge_llm_snapshot: Record<string, unknown>
  configuration_snapshot: Record<string, unknown>
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

export interface MechanismRunCase {
  id: string
  run_id: string
  case_id?: string | null
  case_snapshot: MechanismCase
  actual_output?: EvaluationValue | null
  score_details: Record<string, unknown>
  judge_output?: Record<string, unknown> | null
  score_percent?: number | null
  structured_score_percent: number
  cost: number
  duration: number
  error?: string | null
  created_at: string
}

export interface MechanismJudgeDimension {
  code: string
  score_percent: number
  assessment: string
}

export interface MechanismRunDetail extends MechanismRun {
  results: MechanismRunCase[]
}

function base(mechanism: EvaluationMechanism): string {
  return `/evaluation/${mechanism}`
}

export const mechanismEvaluationService = {
  mechanisms(): Promise<AxiosResponse<MechanismDescriptor[]>> {
    return api.get('/evaluation/mechanisms')
  },
  datasets(mechanism: EvaluationMechanism): Promise<AxiosResponse<MechanismDataset[]>> {
    return api.get(`${base(mechanism)}/datasets`)
  },
  createDataset(mechanism: EvaluationMechanism, name: string, description = '', promptSuffix?: string | null): Promise<AxiosResponse<MechanismDataset>> {
    return api.post(`${base(mechanism)}/datasets`, { name, description, prompt_suffix: promptSuffix })
  },
  updateDataset(mechanism: EvaluationMechanism, dataset: MechanismDataset): Promise<AxiosResponse<MechanismDataset>> {
    return api.patch(`${base(mechanism)}/datasets/${dataset.id}`, {
      revision: dataset.revision,
      name: dataset.name,
      description: dataset.description,
      prompt_suffix: dataset.prompt_suffix,
    })
  },
  deleteDataset(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<void>> {
    return api.delete(`${base(mechanism)}/datasets/${id}`)
  },
  cases(mechanism: EvaluationMechanism, datasetId: string): Promise<AxiosResponse<MechanismCase[]>> {
    return api.get(`${base(mechanism)}/datasets/${datasetId}/cases`)
  },
  createCase(mechanism: EvaluationMechanism, datasetId: string, name: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/datasets/${datasetId}/cases`, { name })
  },
  candidates(mechanism: EvaluationMechanism, search = ''): Promise<AxiosResponse<MechanismSourceCandidate[]>> {
    return api.get(`${base(mechanism)}/candidates`, { params: { search: search || undefined, limit: 50 } })
  },
  importSource(mechanism: EvaluationMechanism, datasetId: string, sourceId: string, confirmation_token?: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/datasets/${datasetId}/cases/from-source`, { source_id: sourceId, confirmation_token })
  },
  topicMessageAgents(): Promise<AxiosResponse<TopicMessageAgent[]>> {
    return api.get('/evaluation/topic-classification/message-agents')
  },
  topicMessagePeople(agentId: number): Promise<AxiosResponse<TopicMessagePerson[]>> {
    return api.get('/evaluation/topic-classification/message-people', { params: { agent_id: agentId } })
  },
  previewTopicMessageRange(filter: TopicMessageRangeFilter): Promise<AxiosResponse<TopicMessageRangePreview>> {
    return api.get('/evaluation/topic-classification/message-preview', { params: filter })
  },
  importTopicMessageRange(datasetId: string, filter: TopicMessageRangeFilter, confirmation_token?: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`/evaluation/topic-classification/datasets/${datasetId}/cases/from-message-range`, { ...filter, confirmation_token })
  },
  updateTopicDatasetConfiguration(datasetId: string, revision: number, configuration: TopicDatasetConfiguration): Promise<AxiosResponse<MechanismDataset>> {
    return api.patch(`/evaluation/topic-classification/datasets/${datasetId}/configuration`, { revision, configuration })
  },
  updateMemoryExtractionDatasetConfiguration(datasetId: string, revision: number, configuration: MemoryExtractionDatasetConfiguration): Promise<AxiosResponse<MechanismDataset>> {
    return api.patch(`/evaluation/memory_extraction/datasets/${datasetId}/configuration`, { revision, configuration })
  },
  updatePlannerDatasetConfiguration(datasetId: string, revision: number, configuration: PlannerDatasetConfiguration): Promise<AxiosResponse<MechanismDataset>> {
    return api.patch(`/evaluation/planner/datasets/${datasetId}/configuration`, { revision, configuration })
  },
  plannerPromptDefault(): Promise<AxiosResponse<{ configuration: PlannerDatasetConfiguration }>> {
    return api.get('/evaluation/planner/prompt-default')
  },
  memoryExtractionPromptDefault(): Promise<AxiosResponse<{ configuration: MemoryExtractionDatasetConfiguration }>> {
    return api.get('/evaluation/memory_extraction/prompt-default')
  },
  importTask(mechanism: EvaluationMechanism, datasetId: string, taskId: string, confirmation_token?: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/datasets/${datasetId}/cases/from-task`, { task_id: taskId, confirmation_token })
  },
  importExecution(mechanism: EvaluationMechanism, datasetId: string, sourceId: string, confirmation_token?: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/datasets/${datasetId}/cases/from-execution`, { source_id: sourceId, confirmation_token })
  },
  updateCase(mechanism: EvaluationMechanism, id: string, revision: number, inputData: EvaluationValue, expectedOutput: EvaluationValue): Promise<AxiosResponse<MechanismCase>> {
    return api.patch(`${base(mechanism)}/cases/${id}`, {
      revision,
      input_data: inputData,
      expected_output: expectedOutput,
    })
  },
  duplicateCase(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/cases/${id}/duplicate`)
  },
  restoreCase(mechanism: EvaluationMechanism, id: string, confirmation_token?: string): Promise<AxiosResponse<MechanismCase>> {
    return api.post(`${base(mechanism)}/cases/${id}/restore-source`, { confirmation_token })
  },
  generateExpected(mechanism: EvaluationMechanism, id: string, inputData: EvaluationValue): Promise<AxiosResponse<{ output: EvaluationValue, llm: Record<string, unknown>, cost: number }>> {
    return api.post(`${base(mechanism)}/cases/${id}/generate-expected`, { input_data: inputData })
  },
  deleteCase(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<void>> {
    return api.delete(`${base(mechanism)}/cases/${id}`)
  },
  runs(mechanism: EvaluationMechanism, datasetId: string): Promise<AxiosResponse<MechanismRun[]>> {
    return api.get(`${base(mechanism)}/datasets/${datasetId}/runs`, { params: { limit: 50 } })
  },
  startRun(mechanism: EvaluationMechanism, datasetId: string, llmId: number): Promise<AxiosResponse<MechanismRun>> {
    return api.post(`${base(mechanism)}/datasets/${datasetId}/runs`, { llm_id: llmId })
  },
  run(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<MechanismRunDetail>> {
    return api.get(`${base(mechanism)}/runs/${id}`)
  },
  deleteRun(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<void>> {
    return api.delete(`${base(mechanism)}/runs/${id}`)
  },
  analyzeRun(mechanism: EvaluationMechanism, id: string, language: 'fr' | 'en' | 'zh'): Promise<AxiosResponse<MechanismRunDetail>> {
    return api.post(`${base(mechanism)}/runs/${id}/analyze`, { language })
  },
  cancelRun(mechanism: EvaluationMechanism, id: string): Promise<AxiosResponse<MechanismRun>> {
    return api.post(`${base(mechanism)}/runs/${id}/cancel`)
  },
  executorPromptDefaults(): Promise<AxiosResponse<{ defaults: Record<ExecutorPromptKind, string> }>> {
    return api.get('/evaluation/executor-prompts/defaults')
  },
}
