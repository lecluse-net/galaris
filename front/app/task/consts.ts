/**
 * Constants for the task module.
 */

// Task statuses as returned by the API.
export const TASK_STATUS = {
  CREATE: 'CREATE',
  DISPATCH: 'DISPATCH',
  BRIEFING: 'BRIEFING',
  EXEC: 'EXEC',
  PLAN: 'PLAN',
  SUCCESS: 'SUCCESS',
  ERROR: 'ERROR'
} as const
