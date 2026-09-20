const TASK_RESOURCE_PREFIX = 'galaris://task/'

/** Return the canonical, copyable resource reference for a Task. */
export function taskResourceUri(taskId: string): string {
  const value = taskId.trim()
  return value.startsWith(TASK_RESOURCE_PREFIX)
    ? value
    : `${TASK_RESOURCE_PREFIX}${value}`
}
