import type { CalendarFeed } from './services/calendarService'
import type { SolaireColor } from '@/core/util'

const defaultColors: SolaireColor[] = ['blue', 'iris', 'green', 'orange', 'fuchsia', 'cyan', 'violet', 'salmon']

export function defaultCalendarColor(id: number, index: number): SolaireColor {
  return id === -1 ? 'yellow' : id === 0 ? 'salmon' : defaultColors[index % defaultColors.length]!
}

export function calendarLabel(feed: CalendarFeed, translate: (key: string) => string): string {
  return feed.source_kind === 'internal' && feed.is_default && feed.label === 'Personal agenda'
    ? translate('calendars.personalAgenda') : feed.label
}

export function calendarSourceLabel(feed: CalendarFeed, translate: (key: string) => string): string {
  return feed.source_kind === 'internal' ? translate('agenda.sources.internal') : feed.tool_label
}
