import type { LLMCall } from './types'

export interface LlmTaskColor {
  name: string
  hex: string
}

// Deliberately mid-tone: visible on white without becoming visually aggressive.
export const LLM_TASK_COLORS: readonly LlmTaskColor[] = [
  { name: 'blue-7', hex: '#1976D2' },
  { name: 'deep-purple-6', hex: '#7E57C2' },
  { name: 'teal-7', hex: '#00897B' },
  { name: 'orange-8', hex: '#EF6C00' },
  { name: 'pink-6', hex: '#D81B60' },
  { name: 'cyan-8', hex: '#00838F' },
  { name: 'indigo-6', hex: '#3949AB' },
  { name: 'green-7', hex: '#388E3C' },
  { name: 'deep-orange-7', hex: '#E64A19' },
  { name: 'purple-6', hex: '#8E24AA' },
  { name: 'light-blue-8', hex: '#0277BD' },
  { name: 'brown-6', hex: '#6D4C41' },
  { name: 'blue-grey-7', hex: '#455A64' },
  { name: 'amber-9', hex: '#FF8F00' },
  { name: 'light-green-8', hex: '#558B2F' },
  { name: 'red-6', hex: '#E53935' },
  { name: 'teal-6', hex: '#009688' },
  { name: 'deep-purple-5', hex: '#673AB7' },
  { name: 'blue-6', hex: '#1E88E5' },
  { name: 'orange-7', hex: '#F57C00' },
  { name: 'pink-7', hex: '#C2185B' },
  { name: 'cyan-9', hex: '#006064' },
  { name: 'indigo-5', hex: '#3F51B5' },
  { name: 'green-8', hex: '#2E7D32' },
  { name: 'deep-orange-6', hex: '#F4511E' },
  { name: 'purple-7', hex: '#7B1FA2' },
  { name: 'light-blue-7', hex: '#0288D1' },
  { name: 'brown-5', hex: '#795548' },
  { name: 'blue-grey-6', hex: '#546E7A' },
  { name: 'light-green-9', hex: '#33691E' },
]

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
