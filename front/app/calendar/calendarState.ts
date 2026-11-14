import type { CalendarEvent } from './services/calendarService'
import type { EventExecutionSummary } from './components/CalendarEventChip.vue'

const eventKey = (event: CalendarEvent): string => `${event.event_id}:${event.recurrence_key}`

/** Reuse immutable API snapshots; revisions alone do not cover sync or Task states. */
export function retainCalendarEvents(previous: CalendarEvent[], incoming: CalendarEvent[]): CalendarEvent[] {
  const indexed = new Map(previous.map(event => [eventKey(event), event]))
  const retained = incoming.map(event => {
    const existing = indexed.get(eventKey(event))
    return existing && JSON.stringify(existing) === JSON.stringify(event) ? existing : event
  })
  return retained.length === previous.length && retained.every((event, index) => event === previous[index]) ? previous : retained
}

/** Preserve unchanged badge objects and drop states that left the active window. */
export function retainExecutionStates(previous: Record<string, EventExecutionSummary>, incoming: Record<string, EventExecutionSummary>): Record<string, EventExecutionSummary> {
  let changed = Object.keys(previous).length !== Object.keys(incoming).length
  const retained: Record<string, EventExecutionSummary> = {}
  for (const [key, value] of Object.entries(incoming)) {
    const existing = previous[key]
    if (existing && JSON.stringify(existing) === JSON.stringify(value)) retained[key] = existing
    else { retained[key] = value; changed = true }
  }
  return changed ? retained : previous
}
