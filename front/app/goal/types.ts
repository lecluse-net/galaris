export type GoalStatus = 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'ERROR'
export type GoalCycleStatus = 'RUNNING' | 'JUDGING' | 'DECIDED' | 'ERROR'
export type GoalVerdict = 'CONTINUE' | 'STOP'
export type GoalCycleTriggerKind = 'TEMPORAL' | 'RELATIONAL' | 'MANUAL'
export type GoalReferrerType = 'AGENT' | 'MESSENGER'
export type GoalPauseReason = 'MANUAL' | 'REFERRER_NO_RESPONSE' | string
export type GoalInactiveReason = 'GLOBAL_PAUSE' | 'OUTSIDE_SCHEDULE'

export interface GoalScheduleWindow {
  weekdays: number[]
  start_time: string
  end_time: string
}

export interface GoalSettings {
  globally_paused: boolean
  schedule_enabled: boolean
  schedule: GoalScheduleWindow[]
  timezone: string
  is_active: boolean
  inactive_reason: GoalInactiveReason | null
  next_active_at: string | null
}

export interface GoalSettingsUpdate {
  globally_paused?: boolean
  schedule_enabled?: boolean
  schedule?: GoalScheduleWindow[]
}

export interface GoalReferrer {
  type: GoalReferrerType
  display_name: string
  agent_id: number | null
  agent_code: string | null
  connection_id: number | null
  user_id: string | null
  platform: string | null
}

export type GoalReferrerInput = {
  type: 'MESSENGER'
  connection_id: number
  user_id: string
  display_name: string
}

export interface MessengerReferrerOption {
  connection_id: number
  tool_id: number
  platform: string
  user_id: string
  display_name: string
  is_current_user: boolean
}

export interface Goal {
  id: string
  memory_item_id: string | null
  revision: number
  title: string
  description_document_id: string
  tracking_document_id: string
  description: string
  tracking_content: string
  agent_id: number
  agent_name: string
  agent_code: string
  referrer: GoalReferrer | null
  cycle_delay_seconds: number | null
  parent_goal_id: string | null
  parent_title: string | null
  children_count: number
  schedule_enabled: boolean
  schedule: GoalScheduleWindow[]
  referrer_max_reminders: number
  status: GoalStatus
  pause_reason: GoalPauseReason | null
  next_cycle_at: string | null
  completed_at: string | null
  last_error: string | null
  cycle_count: number
  task_cost: number
  evaluation_cost: number
  total_cost: number
  current_task_id: string | null
  last_task_finished_at: string | null
  last_verdict: GoalVerdict | null
  created_at: string | null
  created_by: number | null
  updated_at: string | null
  updated_by: number | null
}

export interface GoalCycle {
  id: string
  memory_item_id: string | null
  goal_id: string
  sequence: number
  trigger_kind: GoalCycleTriggerKind
  source_cycle_id: string | null
  task_id: string | null
  task_label: string | null
  task_status: string | null
  task_cost: number
  status: GoalCycleStatus
  verdict: GoalVerdict | null
  reason: string | null
  progress_changed: boolean | null
  progress_summary: string | null
  evidence: string[]
  task_finished_at: string | null
  judge_cost: number
  judge_llm_id: number | null
  judge_attempt_count: number
  judge_started_at: string | null
  judge_finished_at: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type GoalDetail = Goal

export interface GoalCyclePage {
  items: GoalCycle[]
  total: number
  page: number
  page_size: number
}

export interface GoalSummary {
  active: number
  paused: number
  completed: number
  errors: number
  total_cost: number
}

export interface GoalPage {
  items: Goal[]
  total: number
  summary: GoalSummary
  tracking_llm_configured: boolean
}

export interface GoalTreeNode {
  id: string
  parent_goal_id: string | null
  title: string
  agent_id: number
  agent_name: string
  agent_code: string
  status: GoalStatus
  cycle_delay_seconds: number | null
  next_cycle_at: string | null
  children_count: number
}

export interface GoalTreePage {
  items: GoalTreeNode[]
  total: number
}

export interface GoalCreate {
  title: string
  description: string
  agent_id: number
  referrer: GoalReferrerInput
  cycle_delay_seconds: number | null
  parent_goal_id: string | null
  schedule_enabled: boolean
  schedule: GoalScheduleWindow[]
  referrer_max_reminders: number
  active: boolean
}

export interface GoalUpdate {
  expected_revision: number
  title?: string
  description?: string
  tracking_content?: string
  agent_id?: number
  referrer?: GoalReferrerInput
  cycle_delay_seconds?: number | null
  parent_goal_id?: string | null
  schedule_enabled?: boolean
  schedule?: GoalScheduleWindow[]
  referrer_max_reminders?: number
}

export interface GoalCommand {
  expected_revision: number
}
