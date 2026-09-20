import type { TaskStatus } from './types'

export const ACTION_STATUSES: TaskStatus[] = ['DISPATCH', 'BRIEFING', 'EXEC', 'PLAN']

const ACTION_STATUS_SET = new Set<TaskStatus>(ACTION_STATUSES)

interface TaskActivityState {
  status?: TaskStatus | null
  paused?: boolean
  operationalState?: 'QUEUED' | 'RUNNING' | 'WAITING' | 'PAUSED' | 'TERMINAL'
}

/** Animate a Task phase only while its durable execution is not suspended. */
export function shouldAnimateTaskStatus(task: TaskActivityState | null | undefined): boolean {
  if (!task?.status || task.paused) return false
  if (task.operationalState) return ACTION_STATUS_SET.has(task.status) && task.operationalState === 'RUNNING'
  return ACTION_STATUS_SET.has(task.status)
}
