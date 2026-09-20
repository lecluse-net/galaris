import type { Task } from './types'

const TERMINAL_STATUSES = new Set(['SUCCESS', 'ERROR'])

function timestamp(value: string | undefined): number | null {
  if (!value) return null
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? null : parsed
}

/**
 * Merge a task snapshot without allowing a delayed HTTP response to roll the UI
 * back after a newer WebSocket event has already been applied.
 */
export function mergeTaskSnapshot<T extends Task>(current: T | null, incoming: T): T {
  if (!current || current.id !== incoming.id) return incoming

  if (incoming.revision < current.revision) return current
  if (incoming.revision > current.revision) return { ...current, ...incoming }

  const currentUpdatedAt = timestamp(current.updated_at)
  const incomingUpdatedAt = timestamp(incoming.updated_at)
  if (
    currentUpdatedAt !== null
    && incomingUpdatedAt !== null
    && incomingUpdatedAt < currentUpdatedAt
  ) {
    return current
  }

  // Equal revisions can occur for execution-orthogonal topic updates. Preserve a
  // terminal state if an older active snapshot arrives without a usable timestamp.
  if (
    TERMINAL_STATUSES.has(current.status)
    && !TERMINAL_STATUSES.has(incoming.status)
  ) {
    return current
  }

  return { ...current, ...incoming }
}
