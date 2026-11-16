export interface AIMessage {
  type: 'text' | 'audio' | 'image' | 'video' | 'tool'
  content: string
  /** Stable identifier for fragments belonging to one live semantic block. */
  stream_id?: string
  /** Full block replacement versus a fragment to append (the legacy default). */
  stream_mode?: 'delta' | 'snapshot'
  /** Explicit completion of a text/reasoning block; absent on legacy drivers. */
  stream_complete?: boolean | null
  /** Runtime identity of one tool invocation, shared by snapshots and live updates. */
  tool_call_external_id?: string | null
  tool_retry_number?: number | null
  tool_retry_limit?: number | null
  tool_name?: string
  tool_arguments?: Record<string, unknown>
  tool_result?: Record<string, unknown>
  execution_time?: number
  cost?: number
  /** False only when the tool call failed; defaults to success. */
  success?: boolean
}

export interface AIResult {
  prompt: string
  system_prompt: string
  messages?: AIMessage[]
  execution_time: number
  result: string
  cost: number
  tools_used: string[]
  metadata?: Record<string, unknown>
  disposition?: 'completed' | 'waiting_for_authorization'
  success: boolean
}

export type ExecutionResult = AIResult
