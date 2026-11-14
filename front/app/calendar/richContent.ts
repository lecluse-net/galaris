import type { RichContentContribution } from '@/core/util'
import { referenceCardHtml } from '@/core/util/facade'
import { calendarService } from './services/calendarService'
import { calendarLabel } from './presentation'

function idFrom(value: string): string | null {
  const native = /^galaris:\/\/calendar\/([1-9][0-9]*)$/.exec(value)
  if (native) return native[1]!
  try {
    const url = new URL(value, window.location.origin)
    const id = url.searchParams.get('calendar_id')
    return url.origin === window.location.origin && url.pathname.replace(/\/$/, '') === '/calendar' && id && /^[1-9][0-9]*$/.test(id) ? id : null
  } catch { return null }
}

export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://calendar/${id}` : null },
  async search(query, formatting) {
    return (await calendarService.searchResources(query)).map(calendar => ({ uri: calendar.uri, title: calendar.label, context: formatting.t('agenda.calendar') }))
  },
  href(uri) { const id = idFrom(uri); return id ? `/calendar?calendar_id=${id}` : null },
  target(uri, title = '', agentId = null) { const id = idFrom(uri); return id ? { kind: 'calendar', id, title, agentId } : null },
  async title(uri) { const id = idFrom(uri); return id ? (await calendarService.get(Number(id))).label : uri },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Calendar reference')
    const calendar = await calendarService.get(Number(id))
    return referenceCardHtml(`galaris://calendar/${id}`, calendarLabel(calendar, formatting.t), [formatting.t('agenda.calendar'), calendar.timezone])
  },
} satisfies RichContentContribution
