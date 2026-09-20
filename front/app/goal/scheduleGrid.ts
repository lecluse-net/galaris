import type { GoalScheduleWindow } from './types'

export const GOAL_SCHEDULE_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const
export const GOAL_SCHEDULE_HOURS = Array.from({ length: 24 }, (_, index) => index)

export type GoalScheduleSlots = Set<string>

export function goalScheduleSlotKey(weekday: number, hour: number): string {
  return `${weekday}:${hour}`
}

export function goalScheduleDefaultSlots(): GoalScheduleSlots {
  const slots: GoalScheduleSlots = new Set()
  for (const weekday of GOAL_SCHEDULE_WEEKDAYS) {
    for (const hour of GOAL_SCHEDULE_HOURS) {
      slots.add(goalScheduleSlotKey(weekday, hour))
    }
  }
  return slots
}

function clockMinutes(clock: string): number {
  const [hour = '0', minute = '0'] = clock.split(':')
  return Number(hour) * 60 + Number(minute)
}

function clockFromHour(hour: number): string {
  const normalized = hour % 24
  return `${String(normalized).padStart(2, '0')}:00`
}

function addGroupedWindow(
  grouped: Map<string, GoalScheduleWindow>,
  weekday: number,
  startHour: number,
  endHour: number,
): void {
  const startTime = clockFromHour(startHour)
  const endTime = clockFromHour(endHour)
  const key = `${startTime}-${endTime}`
  const existing = grouped.get(key)
  if (existing) {
    existing.weekdays.push(weekday)
  } else {
    grouped.set(key, {
      weekdays: [weekday],
      start_time: startTime,
      end_time: endTime,
    })
  }
}

function windowContainsSlot(
  window: GoalScheduleWindow,
  weekday: number,
  hour: number,
): boolean {
  // Sampling the middle of the cell also gives a predictable best-effort import for legacy
  // schedules that used minute-level boundaries before the hourly grid was introduced.
  const slotMinute = hour * 60 + 30
  const start = clockMinutes(window.start_time)
  const end = clockMinutes(window.end_time)
  if (start < end) {
    return window.weekdays.includes(weekday) && start <= slotMinute && slotMinute < end
  }
  const previousWeekday = (weekday + 6) % 7
  return (
    (window.weekdays.includes(weekday) && slotMinute >= start)
    || (window.weekdays.includes(previousWeekday) && slotMinute < end)
  )
}

export function goalScheduleWindowsToSlots(
  windows: GoalScheduleWindow[],
): GoalScheduleSlots {
  const slots: GoalScheduleSlots = new Set()
  for (const weekday of GOAL_SCHEDULE_WEEKDAYS) {
    for (const hour of GOAL_SCHEDULE_HOURS) {
      if (windows.some(window => windowContainsSlot(window, weekday, hour))) {
        slots.add(goalScheduleSlotKey(weekday, hour))
      }
    }
  }
  return slots
}

export function goalScheduleSlotsToWindows(
  slots: GoalScheduleSlots,
): GoalScheduleWindow[] {
  const grouped = new Map<string, GoalScheduleWindow>()

  for (const weekday of GOAL_SCHEDULE_WEEKDAYS) {
    let rangeStart: number | null = null
    for (let hour = GOAL_SCHEDULE_HOURS[0]; hour <= 24; hour += 1) {
      const active = hour < 24 && slots.has(goalScheduleSlotKey(weekday, hour))
      if (active && rangeStart === null) {
        rangeStart = hour
      } else if (!active && rangeStart !== null) {
        if (rangeStart === 0 && hour === 24) {
          // The API intentionally rejects 00:00 → 00:00 as a zero-length window.
          // Two non-empty windows preserve an exact 24-hour selection and round-trip.
          addGroupedWindow(grouped, weekday, 0, 12)
          addGroupedWindow(grouped, weekday, 12, 24)
        } else {
          addGroupedWindow(grouped, weekday, rangeStart, hour)
        }
        rangeStart = null
      }
    }
  }

  return [...grouped.values()]
}
