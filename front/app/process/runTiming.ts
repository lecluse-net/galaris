export interface RunTiming {
  status: string
  started_at?: string | null
  finished_at?: string | null
}

export function isRunTerminal(status: string): boolean {
  return ['success', 'error', 'cancelled', 'completed', 'failed'].includes(status)
}

/** Execution time excludes queueing; incomplete terminal records never keep ticking. */
export function runDurationSeconds(run: RunTiming, now: number): number | null {
  if (!run.started_at) return null
  const start = Date.parse(run.started_at)
  const end = run.finished_at ? Date.parse(run.finished_at) : isRunTerminal(run.status) ? NaN : now
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, (end - start) / 1000) : null
}
