import { useI18n } from 'vue-i18n'
import { formatDollars } from '@/core/util/facade'
import { UNIT_SECONDS, type DurationUnit } from './durations'
import type { Goal, GoalStatus } from './types'

export function hasOpenGoalCycle(goal: Goal): boolean {
  return Boolean(goal.current_task_id || goal.current_process_run_reference)
}

export function statusColor(status: GoalStatus): string {
  return { ACTIVE: 'positive', PAUSED: 'warning', COMPLETED: 'primary', ERROR: 'negative' }[status]
}

export function useGoalFormatting(timezone: () => string | undefined) {
  const { t, locale } = useI18n()
  function formatCost(value: number): string {
    return formatDollars(value || 0, locale.value, { minimumFractionDigits: 2, maximumFractionDigits: 6 })
  }

  function formatDate(value: string | null): string {
    if (!value) return t('goal.never')
    return new Intl.DateTimeFormat(locale.value, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: timezone(),
    }).format(new Date(value))
  }

  function formatDuration(seconds: number | null): string {
    if (seconds === null) return t('goal.disabled')
    if (seconds === 0) return `0 ${t('goal.units.seconds')}`
    for (const unit of ['years', 'months', 'weeks', 'days', 'hours', 'minutes'] as DurationUnit[]) {
      const factor = UNIT_SECONDS[unit]
      if (seconds % factor === 0) return `${seconds / factor} ${t(`goal.units.${unit}`)}`
    }
    return `${seconds} ${t('goal.units.seconds')}`
  }
  return { formatCost, formatDate, formatDuration }
}
