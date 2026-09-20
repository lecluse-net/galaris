/**
 * Central task-status presentation configuration.
 * 
 * Defines icons, colors, translation keys, and animation state.
 */

import type { TaskStatus } from '../types'
import { i18n } from '@/core/i18n'
import type { StatusBadgeTone } from '@/core/util'
import { ACTION_STATUSES, shouldAnimateTaskStatus } from '../taskActivity'

export { ACTION_STATUSES, shouldAnimateTaskStatus }

/**
 * Complete task-status presentation.
 */
export interface TaskStatusConfig {
  /** Quasar icon, optionally animated. */
  icon: string
  /** Icon color. */
  color: string
  /** Semantic tone shared by status badges across Activity tabs. */
  badgeTone: StatusBadgeTone
  /** Displayed label translation key. */
  labelKey: string
  /** Whether the status represents an active operation. */
  isAction: boolean
}

/**
 * Presentation for every task status.
 */
export const TASK_STATUS_CONFIG: Record<TaskStatus, TaskStatusConfig> = {
  // Static statuses.
  CREATE: {
    icon: 'add_circle_outline',
    color: 'grey-7',
    badgeTone: 'neutral',
    labelKey: 'task.status.CREATE',
    isAction: false
  },
  SUCCESS: {
    icon: 'check_circle',
    color: 'positive',
    badgeTone: 'success',
    labelKey: 'task.status.SUCCESS',
    isAction: false
  },
  ERROR: {
    icon: 'error_outline',
    color: 'negative',
    badgeTone: 'error',
    labelKey: 'task.status.ERROR',
    isAction: false
  },

  // Active statuses with animated icons.
  DISPATCH: {
    icon: 'sync',
    color: 'purple',
    badgeTone: 'active',
    labelKey: 'task.status.DISPATCH',
    isAction: true
  },
  BRIEFING: {
    icon: 'manage_search',
    color: 'amber-9',
    badgeTone: 'active',
    labelKey: 'task.status.BRIEFING',
    isAction: true
  },
  EXEC: {
    icon: 'play_circle',
    color: 'blue',
    badgeTone: 'active',
    labelKey: 'task.status.EXEC',
    isAction: true
  },
  PLAN: {
    icon: 'psychology',
    color: 'teal',
    badgeTone: 'active',
    labelKey: 'task.status.PLAN',
    isAction: true
  }
}

/**
 * Fallback presentation for an unknown status.
 */
const DEFAULT_STATUS_CONFIG: TaskStatusConfig = {
  icon: 'help_outline',
  color: 'grey',
  badgeTone: 'neutral',
  labelKey: 'task.status.unknown',
  isAction: false
}

/**
 * Return a complete status presentation.
 */
export function getTaskStatusConfig(status: TaskStatus | null | undefined): TaskStatusConfig {
  if (!status) return DEFAULT_STATUS_CONFIG
  return TASK_STATUS_CONFIG[status] ?? DEFAULT_STATUS_CONFIG
}

/**
 * Return a status icon.
 */
export function getTaskStatusIcon(status: TaskStatus | null | undefined): string {
  return getTaskStatusConfig(status).icon
}

/**
 * Return a status color.
 */
export function getTaskStatusColor(status: TaskStatus | null | undefined): string {
  return getTaskStatusConfig(status).color
}

/**
 * Return a translated status label.
 */
export function getTaskStatusLabel(status: TaskStatus | null | undefined): string {
  return i18n.global.t(getTaskStatusConfig(status).labelKey)
}

/**
 * Return whether a status represents an active operation.
 */
export function isTaskStatusAction(status: TaskStatus | null | undefined): boolean {
  return getTaskStatusConfig(status).isAction
}

/**
 * Return the status badge color.
 */
export function getTaskStatusBadgeColor(status: TaskStatus | null | undefined): string {
  return ({
    active: 'primary',
    success: 'positive',
    warning: 'orange-10',
    error: 'negative',
    neutral: 'grey-7',
  } satisfies Record<StatusBadgeTone, string>)[getTaskStatusTone(status)]
}

/**
 * Return the status badge text color.
 */
export function getTaskStatusBadgeTextColor(status: TaskStatus | null | undefined): string {
  void status
  return 'white'
}

/** Return the semantic status-badge tone used throughout Activity. */
export function getTaskStatusTone(status: TaskStatus | null | undefined): StatusBadgeTone {
  return getTaskStatusConfig(status).badgeTone
}

/** Static statuses. */
export const STATIC_STATUSES: TaskStatus[] = ['CREATE', 'SUCCESS', 'ERROR']

// ─────────────────────────────────────────────────────────────────────────────
// Unified suspension: status no longer encodes pause. A suspended task has paused=true and
// reasons in data.pause_reasons. Only "user" is a human freeze; other reasons are internal waits.
// ─────────────────────────────────────────────────────────────────────────────

export const PAUSE_REASON = {
  USER: 'user', AWAIT: 'await', PLAN: 'plan', CLARIFY: 'clarify', CHILD: 'child',
} as const

interface HasPause { paused?: boolean; data?: Record<string, any> | null }

export function pauseReasons(task: HasPause): string[] {
  const raw = task?.data?.pause_reasons
  return Array.isArray(raw) ? raw.map(String) : []
}

/** Return whether a human explicitly froze the task. */
export function isUserPaused(task: HasPause): boolean {
  return Boolean(task?.paused) && pauseReasons(task).includes(PAUSE_REASON.USER)
}

export interface PauseBadge {
  labelKey: string
  color: string
  textColor: string
  icon: string
  tone: StatusBadgeTone
  /** true for a self-resuming wait; false for a human pause. */
  waiting: boolean
}

// Distinguish human pauses from automatic waits visually.
const PAUSED = { color: 'orange-10', textColor: 'white', icon: 'pause_circle', tone: 'warning', waiting: false } as const
const WAITING = { color: 'primary', textColor: 'white', icon: 'hourglass_top', tone: 'active', waiting: true } as const

/** Return the suspension badge, or null for an active task. */
export function pauseBadge(task: HasPause): PauseBadge | null {
  if (!task?.paused) return null
  const reasons = pauseReasons(task)
  // A human pause takes precedence over automatic wait reasons.
  if (reasons.includes(PAUSE_REASON.USER)) return { labelKey: 'task.detail.pausedBadge', ...PAUSED }
  if (reasons.includes(PAUSE_REASON.AWAIT)) return { labelKey: 'task.detail.waitingColleague', ...WAITING }
  if (reasons.includes(PAUSE_REASON.CHILD)) return { labelKey: 'task.detail.waitingSubtask', ...WAITING }
  if (reasons.includes(PAUSE_REASON.CLARIFY)) return { labelKey: 'task.detail.waitingClarification', ...WAITING }
  if (reasons.includes(PAUSE_REASON.PLAN)) return { labelKey: 'task.detail.waitingPlan', ...WAITING }
  return { labelKey: 'task.detail.pausedBadge', ...PAUSED }
}

interface HasTaskOperationalPresentation extends HasPause {
  status?: TaskStatus | null
}

/** Return the pause/wait icon when suspended, otherwise the resume-phase icon. */
export function getTaskOperationalIcon(task: HasTaskOperationalPresentation): string {
  return pauseBadge(task)?.icon ?? getTaskStatusIcon(task.status)
}

/** Return the pause/wait color when suspended, otherwise the resume-phase color. */
export function getTaskOperationalColor(task: HasTaskOperationalPresentation): string {
  const suspension = pauseBadge(task)
  if (!suspension) return getTaskStatusColor(task.status)
  return suspension.waiting ? 'blue-7' : 'orange-8'
}
