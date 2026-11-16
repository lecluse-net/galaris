import type { LLMCall } from './types'
import { solaire, solaireColors } from '@/core/util/facade'

export interface LlmTaskColor {
  name: string
  hex: string
}

export const LLM_TASK_COLORS: readonly LlmTaskColor[] = solaireColors.map(color => ({
  name: `solaire-${color}`, hex: solaire[color].accent,
}))

export function callTaskKey(call: LLMCall): string {
  if (call.task_id) return `task:${call.task_id}`
  if (call.process_run_id) return `process:${call.process_run_id}`
  if (call.agent_id) return `agent:${call.agent_id}`
  return `system:${call.call_type}`
}

/**
 * Assigns one color per task while treating consecutive visible tasks as
 * neighbours. The greedy pass starts at a stable hash-derived palette index,
 * then skips colors already used by adjacent tasks.
 */
export function assignTaskColors(sections: readonly LLMCall[][]): Map<string, LlmTaskColor> {
  const neighbours = new Map<string, Set<string>>()
  const orderedKeys: string[] = []
  const seen = new Set<string>()

  for (const calls of sections) {
    let previousKey: string | undefined
    for (const call of calls) {
      const key = callTaskKey(call)
      if (!seen.has(key)) {
        seen.add(key)
        orderedKeys.push(key)
      }
      if (previousKey && previousKey !== key) {
        addNeighbour(neighbours, previousKey, key)
        addNeighbour(neighbours, key, previousKey)
      }
      previousKey = key
    }
  }

  const assignments = new Map<string, LlmTaskColor>()
  for (const key of orderedKeys) {
    const unavailable = new Set(
      [...(neighbours.get(key) || [])]
        .map(neighbour => assignments.get(neighbour)?.name)
        .filter((name): name is string => Boolean(name)),
    )
    const start = stableHash(key) % LLM_TASK_COLORS.length
    const color = [...LLM_TASK_COLORS.slice(start), ...LLM_TASK_COLORS.slice(0, start)]
      .find(candidate => !unavailable.has(candidate.name)) || LLM_TASK_COLORS[start]
    assignments.set(key, color)
  }
  return assignments
}

function addNeighbour(neighbours: Map<string, Set<string>>, key: string, neighbour: string): void {
  if (!neighbours.has(key)) neighbours.set(key, new Set())
  neighbours.get(key)?.add(neighbour)
}

function stableHash(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash)
}
