import type { ExecutionResult } from '@/app/agent/contracts'
export type { AIMessage, AIResult, ExecutionResult } from '@/app/agent/contracts'
// Suspension is represented by paused and data.pause_reasons rather than a status.
export type TaskStatus = 'CREATE' | 'DISPATCH' | 'EXEC' | 'PLAN' | 'SUCCESS' | 'ERROR'
export type CoordinationType = 'await_reply'

// Dispatcher overrides; null or undefined delegates the decision to the dispatcher.
export type ForcedRoute = 'EXEC' | 'PLAN'
export type Effort = 'standard' | 'high'
export type ReasoningEffort = 'none' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export type TaskContextKind = 'conversation' | 'task' | 'resource' | 'memory'

export interface TaskContextEntry {
  key: string
  kind: TaskContextKind
  reference: string
  title?: string
  excerpt?: string
  revision?: number | null
  occurred_at?: string | null
  provenance?: string[]
}
export interface TaskContextCapsule {
  version: 1
  contact_memory_item_id: string
  entries: TaskContextEntry[]
  truncated: boolean
  created_at: string
}

export interface PlanBrief {
  objective?: string
  context?: string
  strategy?: string
  rationale?: string
  constraints?: string[]
  success_criteria?: string[]
  deliverables?: string[]
}

export interface PlanStep {
  objective?: string
  label?: string
  announce?: string
  effort?: Effort
  artifact_policy?: 'none' | 'intermediate' | 'final'
  delivery_policy?: 'forbidden' | 'required'
  steps?: PlanStep[]
}

export interface TaskPlan {
  steps?: PlanStep[]
  cursor?: number
  brief?: PlanBrief | null
  clarification_questions?: string[]
  prompt?: string
  system_prompt?: string
  execution_time?: number
  cost?: number
  tools_used?: string[]
  success?: boolean
  [key: string]: any
}

export interface Task {
  objective_media_type?: string
  id: string
  revision: number
  label: string
  objective?: string
  status: TaskStatus
  paused: boolean
  ai: boolean
  feedback?: string
  cost: number
  effort?: Effort
  forced_route?: ForcedRoute | null
  forced_effort?: Effort | null
  reasoning_effort_override?: ReasoningEffort | null
  auto_approve?: boolean
  agent_id?: number
  goal_id?: string | null
  topic_id?: string | null
  requester_agent_id?: number
  message_platform?: string
  message_group_id?: string
  dispatch_result?: DispatchResult
  execution_result?: ExecutionResult
  data?: Record<string, any>
  parent_id?: string
  source_task_id?: string
  coordination_type?: CoordinationType | null
  is_coordination?: boolean
  execution_expected?: boolean
  resolved_by_task_id?: string | null
  plan?: TaskPlan
  created_at?: string
  created_by?: number
  updated_at?: string
  updated_by?: number
  deleted_at?: string
  deleted_by?: number
}

export interface TaskPage {
  items: Task[]
  total: number
  summary: TaskOverview
}

export interface TaskOverview {
  running: number
  completed: number
  paused: number
  errors: number
}

export interface TaskAssignment {
  id: string
  task_id: string
  agent_id: number
  manager: boolean
  created_at?: string
  created_by?: number
  updated_at?: string
  updated_by?: number
  deleted_at?: string
  deleted_by?: number
}

export interface TaskWithAssignments extends Task {
  assignments: TaskAssignment[]
}

export interface TaskSummary extends Task {}

export interface TaskFull extends TaskWithAssignments {}

export interface TaskCreate {
  label: string
  objective?: string
  status?: TaskStatus
  paused?: boolean
  ai?: boolean
  feedback?: string
  cost?: number
  effort?: Effort
  forced_route?: ForcedRoute | null
  forced_effort?: Effort | null
  reasoning_effort_override?: ReasoningEffort | null
  auto_approve?: boolean
  agent_id?: number
  goal_id?: string
  requester_agent_id?: number
  message_platform?: string
  message_group_id?: string
  dispatch_result?: DispatchResult
  execution_result?: ExecutionResult
  data?: Record<string, any>
  parent_id?: string
  source_task_id?: string
  plan?: TaskPlan
}

export interface TaskUpdate {
  expected_revision: number
  topic_id?: string | null
  label?: string
  objective?: string
  forced_route?: ForcedRoute | null
  forced_effort?: Effort | null
  reasoning_effort_override?: ReasoningEffort | null
  auto_approve?: boolean
  agent_id?: number
}

export interface DispatchDecision {
  reasoning: string
  route: 'EXEC' | 'PLAN' | 'END'
  // Missing from dispatch results created before executor_llm_tier became effort.
  effort?: 'standard' | 'high'
  // Missing from dispatch results created before language detection.
  language?: string
}

export interface DispatchResult {
  prompt: string
  system_prompt: string
  execution_time: number
  cost: number
  tools_used: string[]
  success: boolean
  decision: DispatchDecision
}
