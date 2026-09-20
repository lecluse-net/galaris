import type { AIMessage, AIResult, Task } from './types'

export type LiveRunKind = 'started' | 'message' | 'result' | 'failed' | 'cancelled'

export interface TaskLiveRunEvent {
  task_id: string
  run_id: string
  attempt_id?: string | null
  sequence: number
  kind: LiveRunKind
  message?: AIMessage
  result?: AIResult
  snapshot?: { run_id: string; attempt_id?: string | null; sequence: number; result: AIResult }
}

export interface TaskLiveRunState {
  runId: string
  attemptId?: string | null
  sequence: number
  result: AIResult
}

export function emptyAIResult(prompt = ''): AIResult {
  return {
    prompt,
    system_prompt: '',
    messages: [],
    execution_time: 0,
    result: '',
    cost: 0,
    tools_used: [],
    success: true,
  }
}

function isToolInvocation(message: AIMessage): boolean {
  return message.type === 'tool' && message.tool_name !== 'thinking'
}

function sameToolInvocation(left: AIMessage, right: AIMessage): boolean {
  if (!isToolInvocation(left) || !isToolInvocation(right)
    || left.tool_name !== right.tool_name
    || (left.tool_retry_number ?? null) !== (right.tool_retry_number ?? null)) return false
  if (left.tool_call_external_id && right.tool_call_external_id) {
    return left.tool_call_external_id === right.tool_call_external_id
  }
  return Boolean(left.stream_id && left.stream_id === right.stream_id)
}

function mergeMessageUpdate(previous: AIMessage, incoming: AIMessage): AIMessage {
  return {
    ...previous,
    ...incoming,
    // Live projections may contain only a prefix of the durable tool output.
    content: incoming.content && previous.content.startsWith(incoming.content)
      ? previous.content : incoming.content,
    tool_arguments: incoming.tool_arguments ?? previous.tool_arguments,
    tool_result: incoming.tool_result ?? previous.tool_result,
    execution_time: Math.max(previous.execution_time ?? 0, incoming.execution_time ?? 0),
    cost: Math.max(previous.cost ?? 0, incoming.cost ?? 0),
  }
}

function sameSnapshotMessage(previous: AIMessage, next: AIMessage): boolean {
  if (isToolInvocation(previous) && isToolInvocation(next)
    && (previous.tool_call_external_id && next.tool_call_external_id
      || previous.stream_id && next.stream_id)) {
    return sameToolInvocation(previous, next)
  }
  if (previous.stream_id && next.stream_id) return previous.stream_id === next.stream_id
  return previous.type === next.type && (previous.tool_name ?? null) === (next.tool_name ?? null)
    && (previous.content === next.content
      || Boolean(previous.content && next.content)
        && (previous.content.startsWith(next.content) || next.content.startsWith(previous.content)))
}

export function appendAIMessage(current: AIResult | null, message: AIMessage): AIResult {
  const result = current ?? emptyAIResult()
  const messages = [...(result.messages ?? [])]
  const last = messages.at(-1)
  const invocationIndex = messages.findIndex(item => sameToolInvocation(item, message)
    || !isToolInvocation(message) && message.stream_mode === 'snapshot' && Boolean(message.stream_id)
      && item.stream_id === message.stream_id)
  const invocation = invocationIndex >= 0 ? messages[invocationIndex] : undefined
  if (invocation) {
    const updated = mergeMessageUpdate(invocation, message)
    messages[invocationIndex] = updated
    return {
      ...result,
      messages,
      result: message.type === 'text'
        ? messages.filter(item => item.type === 'text').map(item => item.content).join('')
        : result.result,
      execution_time: result.execution_time + (updated.execution_time ?? 0) - (invocation.execution_time ?? 0),
      cost: result.cost + (updated.cost ?? 0) - (invocation.cost ?? 0),
      success: result.success && message.success !== false,
    }
  }
  const streamIndex = message.stream_id
    && !isToolInvocation(message)
    ? messages.findIndex(item => item.stream_id === message.stream_id)
    : -1
  const streamed = streamIndex >= 0 ? messages[streamIndex] : undefined
  if (
    streamed
    && streamed.type === message.type
    // HTTP snapshots retain nulls; live projections omit absent tool names.
    && (streamed.tool_name ?? null) === (message.tool_name ?? null)
  ) {
    messages[streamIndex] = {
      ...streamed,
      stream_complete: streamed.stream_complete === true ? true : message.stream_complete ?? streamed.stream_complete,
      content: `${streamed.content}${message.content}`,
      execution_time: (streamed.execution_time ?? 0) + (message.execution_time ?? 0),
      cost: (streamed.cost ?? 0) + (message.cost ?? 0),
      success: streamed.success !== false && message.success !== false,
    }
  } else if (
    message.type === 'text'
    && last?.type === 'text'
    && !message.stream_id
    && !last.stream_id
  ) {
    messages[messages.length - 1] = {
      ...last,
      content: `${last.content}${message.content}`,
      execution_time: (last.execution_time ?? 0) + (message.execution_time ?? 0),
      cost: (last.cost ?? 0) + (message.cost ?? 0),
      success: last.success !== false && message.success !== false,
    }
  } else {
    messages.push(message)
  }
  const toolName = message.tool_name
  return {
    ...result,
    messages,
    result: message.type === 'text' ? `${result.result}${message.content}` : result.result,
    execution_time: result.execution_time + (message.execution_time ?? 0),
    cost: result.cost + (message.cost ?? 0),
    tools_used: toolName && !result.tools_used.includes(toolName)
      ? [...result.tools_used, toolName]
      : result.tools_used,
    success: result.success && message.success !== false,
  }
}

export function resetAIResultText(current: AIResult): AIResult {
  const messages = (current.messages ?? []).map(message => (
    message.type === 'text' && message.content.trim()
      ? {
          ...message,
          type: 'tool' as const,
          tool_name: 'thinking',
          execution_time: 0,
          cost: 0,
        }
      : message
  ))
  return { ...current, messages, result: '' }
}

function mergeCumulativeText(current: string, incoming: string): string {
  if (!current) return incoming
  if (!incoming || current.includes(incoming)) return current
  if (incoming.includes(current)) return incoming

  const maxOverlap = Math.min(current.length, incoming.length)
  for (let overlap = maxOverlap; overlap > 0; overlap -= 1) {
    if (current.endsWith(incoming.slice(0, overlap))) {
      return `${current}${incoming.slice(overlap)}`
    }
  }
  return `${current}${incoming}`
}

function visibleTextMessages(result: AIResult): string {
  return (result.messages ?? [])
    .filter(message => message.type === 'text')
    .map(message => message.content)
    .join('\n\n')
}

export function finalizeAIResult(current: AIResult | null, terminal: AIResult): AIResult {
  return {
    ...terminal,
    messages: mergeMessageSnapshots(current?.messages ?? [], terminal.messages ?? [], true),
  }
}

export function currentAIResponse(result: AIResult | null): string {
  return result ? visibleTextMessages(result).trim() : ''
}

/** Snapshots replace identified messages; only delta events concatenate fragments. */
function mergeMessageSnapshots(
  current: readonly AIMessage[],
  incoming: readonly AIMessage[],
  terminal = false,
): AIMessage[] {
  if (!incoming.length) return [...current]
  const messages = [...incoming]
  const matched = new Set<number>()
  let insertion = 0
  for (const previous of current) {
    const index = incoming.findIndex((next, index) => (
      !matched.has(index) && sameSnapshotMessage(previous, next)
    ))
    if (index >= 0) {
      matched.add(index)
      const next = incoming[index]!
      const target = messages.indexOf(next)
      // A shorter cumulative snapshot can arrive after newer deltas. A change
      // of type (e.g. narration becoming thinking) remains authoritative.
      messages[target] = isToolInvocation(next)
        ? mergeMessageUpdate(previous, next)
        : previous.type === next.type && previous.content.startsWith(next.content)
          && !terminal
        ? { ...next, content: previous.content }
        : next
      if (previous.stream_complete === true && !terminal) {
        messages[target] = { ...messages[target]!, stream_complete: true }
      }
      insertion = target + 1
    } else if (!terminal || previous.type !== 'text' && !isToolInvocation(previous)
      && !incoming.some(next => sameSnapshotMessage(previous, next))) {
      messages.splice(insertion++, 0, previous)
    }
  }
  return messages
}

/** A completed Task's durable trace also repairs a missed terminal live event. */
export function reconcileTaskAIResult(
  task: Pick<Task, 'status' | 'execution_result'> | null,
  live: AIResult | null,
): AIResult | null {
  const durable = task?.execution_result ?? null
  if (durable && (task?.status === 'SUCCESS' || task?.status === 'ERROR')) {
    return finalizeAIResult(live, durable)
  }
  return reconcileAIResult(live, durable)
}

/** Task monitoring shows completed blocks; conversation rendering keeps every delta. */
export function completedTaskAIResult(result: AIResult | null, terminal: boolean): AIResult | null {
  if (!result || terminal) return result
  const trace = result.messages ?? []
  // Older drivers lack completion markers. A subsequent tool/media operation
  // closes their preceding narration; keep the unconfirmed trailing text hidden.
  const boundary = trace.reduce((last, message, index) => message.type !== 'text'
    && !(message.type === 'tool' && message.tool_name === 'thinking') ? index : last, -1)
  const messages = trace.filter((message, index) => {
    if (message.type !== 'text' && !(message.type === 'tool' && message.tool_name === 'thinking')) return true
    return message.stream_complete ?? index < boundary
  })
  return { ...result, messages, result: messages.filter(message => message.type === 'text').map(message => message.content).join('') }
}

/** Keep the richest cumulative projection when HTTP and WebSocket overlap. */
export function reconcileAIResult(
  current: AIResult | null,
  incoming: AIResult | null,
): AIResult | null {
  if (!current) return incoming
  if (!incoming) return current

  const messages = mergeMessageSnapshots(current.messages ?? [], incoming.messages ?? [])

  return {
    ...current,
    ...incoming,
    prompt: incoming.prompt || current.prompt,
    system_prompt: incoming.system_prompt || current.system_prompt,
    messages,
    result: mergeCumulativeText(current.result, incoming.result),
    execution_time: Math.max(current.execution_time, incoming.execution_time),
    cost: Math.max(current.cost, incoming.cost),
    tools_used: [...new Set([...current.tools_used, ...incoming.tools_used])],
    metadata: { ...current.metadata, ...incoming.metadata },
    success: current.success && incoming.success,
  }
}

export function taskRunId(task: Pick<Task, 'data'>): string | null {
  const identity = task.data?._agent_run_identity
  if (!identity || typeof identity !== 'object') return null
  const runId = (identity as Record<string, unknown>).request_run_id
  return typeof runId === 'string' && runId ? runId : null
}

/**
 * Fold one ephemeral event into a monotonic per-Task buffer.
 *
 * The durable result is used as a baseline for late subscribers. Events from a
 * superseded run, plus duplicate or out-of-order sequences, are ignored.
 */
export function applyTaskLiveRunEvent(
  current: TaskLiveRunState | null,
  event: TaskLiveRunEvent,
  durableResult: AIResult | null,
  expectedRunId: string | null,
  expectedAttemptId: string | null = null,
): TaskLiveRunState | null {
  if (expectedRunId && event.run_id !== expectedRunId) return current
  if (expectedAttemptId && event.attempt_id && event.attempt_id !== expectedAttemptId) return current

  const sameRun = current?.runId === event.run_id && (current?.attemptId ?? null) === (event.attempt_id ?? null)
  if (sameRun && event.sequence <= current.sequence) return current

  if (event.snapshot?.run_id === event.run_id && event.snapshot.sequence === event.sequence) {
    return { runId: event.run_id, attemptId: event.attempt_id, sequence: event.sequence, result: event.snapshot.result }
  }

  if (!sameRun && current && event.kind !== 'started' && !expectedRunId) return current

  const baseline = sameRun
    ? current.result
    : durableResult ?? emptyAIResult()

  let result = baseline
  if (event.kind === 'message' && event.message) {
    result = appendAIMessage(baseline, event.message)
  } else if (event.result) {
    result = finalizeAIResult(baseline, event.result)
  }

  return {
    runId: event.run_id,
    attemptId: event.attempt_id,
    sequence: event.sequence,
    result,
  }
}
