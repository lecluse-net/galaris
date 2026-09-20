import type { LabResult } from './services/labWorkbenchService'

export interface ObjectiveCheck { code: string; passed: boolean; critical: boolean; detail: string }
export function objectiveChecks(result: LabResult): ObjectiveCheck[] {
  const checks = result.score_details.checks
  if (!Array.isArray(checks)) return []
  return checks.filter((item): item is ObjectiveCheck => item != null && typeof item === 'object' && typeof item.code === 'string' && typeof item.passed === 'boolean')
}
export const isCritical = (result: LabResult) => objectiveChecks(result).some(check => !check.passed && check.critical) || Boolean(result.judge_output?.critical_failures?.length)
export function stability(results: LabResult[], repetitions: number) {
  const groups = new Map<string, LabResult[]>()
  for (const result of results) {
    const key = result.case_snapshot.id ?? result.id
    groups.set(key, [...(groups.get(key) ?? []), result])
  }
  return [...groups.entries()].map(([id, items]) => {
    const scores = items.flatMap(item => item.score_percent == null ? [] : [item.score_percent])
    const mean = scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null
    return {
      id, name: items[0]!.case_snapshot.name, attempts: items.length, judged: scores.length,
      repetitions, passed: items.filter(item => item.verdict === 'pass').length,
      failed: items.filter(item => item.verdict === 'fail' || item.error).length,
      mean, min: scores.length ? Math.min(...scores) : null, max: scores.length ? Math.max(...scores) : null,
      deviation: mean == null ? null : Math.sqrt(scores.reduce((sum, value) => sum + (value - mean) ** 2, 0) / scores.length),
    }
  })
}
