import { wallTime, zonedInstant } from "@/core/util"
import type { CalendarEvent } from './services/calendarService'

export type CalendarView = 'month' | 'week' | 'day' | 'list'
export const dayKey = (date: Date): string => date.toISOString().slice(0, 10)
export function addDays(day: string, amount: number): string { const date = new Date(`${day}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + amount); return dayKey(date) }
export function addMonths(day: string, amount: number): string {
  const date = new Date(`${day}T12:00:00Z`), n = date.getUTCDate()
  date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + amount)
  date.setUTCDate(Math.min(n, new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate()))
  return dayKey(date)
}
export { wallTime, zonedInstant } from "@/core/util"
export function isoWeekNumber(day: string): number {
  const thursday = new Date(`${day}T12:00:00Z`)
  thursday.setUTCDate(thursday.getUTCDate() + 3 - ((thursday.getUTCDay() + 6) % 7))
  const yearStart = new Date(thursday)
  yearStart.setUTCMonth(0, 1)
  return Math.floor((thursday.getTime() - yearStart.getTime()) / (7 * 86400000)) + 1
}
export function visibleDays(day: string, view: CalendarView): string[] {
  if (view === 'day') return [day]
  const date = new Date(`${day}T12:00:00Z`)
  if (view === 'week') { const start = addDays(day, -((date.getUTCDay() + 6) % 7)); return Array.from({ length: 7 }, (_, n) => addDays(start, n)) }
  const first = day.slice(0, 7) + '-01'
  if (view === 'list') return Array.from({ length: 30 }, (_, n) => addDays(day, n))
  const start = addDays(first, -((new Date(`${first}T12:00:00Z`).getUTCDay() + 6) % 7))
  const end = addMonths(first, 1), days = Math.round((Date.parse(end) - Date.parse(start)) / 86400000)
  return Array.from({ length: Math.ceil(days / 7) * 7 }, (_, n) => addDays(start, n))
}
/** API windows are capped at 32 days; a month grid may cover six weeks. */
export function queryWindows(days: string[], timezone: string): { start: string; end: string }[] {
  const result: { start: string; end: string }[] = []
  for (let n = 0; n < days.length; n += 28) result.push({ start: zonedInstant(`${days[n]}T00:00`, timezone), end: zonedInstant(`${addDays(days[Math.min(n + 27, days.length - 1)]!, 1)}T00:00`, timezone) })
  return result
}
export function eventOnDay(event: CalendarEvent, day: string, timezone: string): boolean {
  const start = event.all_day ? event.start_date ?? event.start.slice(0, 10) : wallTime(event.start, timezone).slice(0, 10)
  const end = event.all_day ? event.end_date ?? event.end.slice(0, 10) : wallTime(new Date(Math.max(Date.parse(event.start), Date.parse(event.end) - 1)), timezone).slice(0, 10)
  return start <= day && (event.all_day ? end > day : end >= day)
}
export const occurrenceKey = (event: Pick<CalendarEvent, 'event_id' | 'recurrence_key'>): string => `${event.event_id}:${event.recurrence_key}`
export interface PositionedEvent { event: CalendarEvent; top: number; height: number; column: number; columns: number; span: number }
export function positionEvents(events: CalendarEvent[], day: string, timezone: string): PositionedEvent[] {
  const minutes = (instant: string) => { const wall = wallTime(instant, timezone); return wall.slice(0, 10) < day ? 0 : wall.slice(0, 10) > day ? 1440 : Number(wall.slice(11, 13)) * 60 + Number(wall.slice(14, 16)) }
  const rows = events.filter(event => !event.all_day && eventOnDay(event, day, timezone)).map(event => {
    const top = minutes(event.start)
    return { event, top, height: Math.min(1440 - top, Math.max(32, minutes(event.end) - top)), column: 0, columns: 1, span: 1 }
  }).sort((a, b) => a.top - b.top || b.height - a.height || occurrenceKey(a.event).localeCompare(occurrenceKey(b.event)))
  let group: PositionedEvent[] = [], until = 0
  const overlaps = (a: PositionedEvent, b: PositionedEvent) => a.top < b.top + b.height && b.top < a.top + a.height
  const finish = () => {
    const count = Math.max(1, ...group.map(row => row.column + 1))
    for (const row of group) {
      row.columns = count
      while (row.column + row.span < count && !group.some(other => other.column === row.column + row.span && overlaps(row, other))) row.span++
    }
    group = []
  }
  for (const row of rows) {
    if (group.length && row.top >= until) finish()
    const occupied = group.filter(other => other.top + other.height > row.top).map(other => other.column)
    while (occupied.includes(row.column)) row.column++
    group.push(row); until = Math.max(...group.map(other => other.top + other.height))
  }
  finish(); return rows
}
