import { api } from '@/core/api'

export type CalendarAccess = 'read' | 'write'
export type CalendarAction = 'task' | 'process'

export interface CalendarFeed {
  id: number
  connection_id: number
  agent_id: number
  label: string
  owner_label: string | null
  access_mode: CalendarAccess
  origin: string
  username_configured: boolean
  password_configured: boolean
  active: boolean
  trigger_on_start: boolean
  trigger_on_alarm: boolean
  action_kind: CalendarAction
  process_workflow_id: string | null
  action_instructions: string | null
  last_synced_at: string | null
  last_error: string | null
}

export interface CalendarFeedCreate {
  connection_id: number
  label: string
  owner_label?: string | null
  access_mode: CalendarAccess
  url: string
  username?: string | null
  password?: string | null
  active: boolean
  trigger_on_start: boolean
  trigger_on_alarm: boolean
  action_kind: CalendarAction
  process_workflow_id?: string | null
  action_instructions?: string | null
}

export interface CalendarFeedUpdate extends Partial<Omit<CalendarFeedCreate, 'connection_id'>> {}

export interface CalendarConnectionEvent {
  uid: string
  summary: string
  start: string
  end: string
  all_day: boolean
}

export interface CalendarConnectionStatus {
  calendar_id: number
  ok: boolean
  events_seen: number
  writable_advertised: boolean | null
  next_events: CalendarConnectionEvent[]
}

export interface CalendarProcessOption {
  agent_id: number | null
  engine_process_id: string
  label: string
}

export const calendarService = {
  async list(connectionId: number): Promise<CalendarFeed[]> {
    return (await api.get('/calendars', { params: { connection_id: connectionId } })).data
  },
  async processes(): Promise<CalendarProcessOption[]> {
    return (await api.get('/processes/definitions')).data
  },
  async create(data: CalendarFeedCreate): Promise<CalendarFeed> {
    return (await api.post('/calendars', data)).data
  },
  async update(id: number, data: CalendarFeedUpdate): Promise<CalendarFeed> {
    return (await api.put(`/calendars/${id}`, data)).data
  },
  async remove(id: number): Promise<void> {
    await api.delete(`/calendars/${id}`)
  },
  async test(id: number): Promise<CalendarConnectionStatus> {
    return (await api.post(`/calendars/${id}/test`)).data
  },
}
