import type { LLMCall } from './types'

export interface LLMCallProgress extends Omit<Partial<LLMCall>, 'response_text' | 'reasoning'> {
  id: string
  base_updated_at: string | null
  response_text: { append: string } | { replace: string }
  reasoning: { append: string } | { replace: string }
}

// Keep microseconds: Date.parse truncates them and cannot identify a delta base.
function revision(value: string | null | undefined): string {
  return (value ?? '').replace('+00:00', 'Z').replace(/(?:\.(\d+))?Z$/, (_match, fraction: string | undefined) => `.${(fraction ?? '').padEnd(9, '0')}Z`)
}

export function isNewerCallRevision(left: string | null | undefined, right: string | null | undefined): boolean {
  if (!left || !right) return false
  const difference = Date.parse(left) - Date.parse(right)
  return difference > 0 || difference === 0 && revision(left) > revision(right)
}

/** null requests an authoritative snapshot; late progress never reopens a call. */
export function applyLlmCallProgress(call: LLMCall, progress: LLMCallProgress): LLMCall | null {
  if (call.id !== progress.id || call.status !== 'running') return call
  if (revision(call.updated_at) === revision(progress.updated_at)) return call
  if (isNewerCallRevision(call.updated_at, progress.updated_at)) return call
  if (revision(call.updated_at) !== revision(progress.base_updated_at)) return null
  const { base_updated_at: _base, response_text: text, reasoning, ...fields } = progress
  return {
    ...call, ...fields,
    response_text: 'replace' in text ? text.replace : call.response_text + text.append,
    reasoning: 'replace' in reasoning ? reasoning.replace : call.reasoning + reasoning.append,
  }
}
