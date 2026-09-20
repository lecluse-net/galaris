export interface LLMToolCall {
  id: string
  type: string
  name: string
  arguments: Record<string, unknown>
  status: string
  result?: unknown
  completed_at?: string
}

export type ReasoningEffort = 'none' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface LLMCall {
  id: string
  task_id?: string
  task_attempt_id?: string
  agent_run_id?: string
  voice_turn_id?: string
  conversation_round_id?: string
  process_run_id?: string
  correlation_ref?: string
  purpose?: string | null
  agent_id?: number
  llm_id?: number
  task_label?: string
  task_status?: string
  agent_name?: string
  agent_code?: string
  process_label?: string
  call_type: 'chat' | 'dispatch' | 'planning' | 'briefing' | 'synthesis' | 'goal_tracking' | 'vision'
  provider_name: string
  provider_code?: string
  requested_model: string
  effective_model: string
  reasoning_effort?: ReasoningEffort | null
  status: string
  stream: boolean
  request_messages: Array<Record<string, any>>
  prompt: string
  system_prompt: string
  response_text: string
  reasoning: string
  tool_calls: LLMToolCall[]
  raw_response: string
  finish_reason?: string
  usage: Record<string, any>
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  reasoning_tokens: number
  cost: number
  inference_cost: number
  cost_estimated: boolean
  is_subscription: boolean
  upstream_request_id?: string
  error?: string
  started_at: string
  first_token_at?: string
  completed_at?: string
  duration: number
  created_at: string
  updated_at: string | null
}

export interface LLMCallPage {
  items: LLMCall[]
  total: number
  page: number
  page_size: number
  summary: LLMCallSummary
}

export interface LLMCallSummary {
  running: number
  completed: number
  errors: number
  total_cost: number
  total_inference_cost: number
}
