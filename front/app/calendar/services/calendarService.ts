import { api } from '@/core/api'
import type { GoalAgendaEvent } from '@/app/goal'
import type { MemoryAgendaOccurrence } from '@/app/memory'

export type SyncState = 'local' | 'synced' | 'pending' | 'conflict'
export type ExecutionState = 'scheduled' | 'cancelled' | 'skipped' | 'pending' | 'dispatch_error' | 'queued' | 'running' | 'judging' | 'waiting' | 'paused' | 'done' | 'error' | 'unavailable'
export type EventScope = 'series' | 'occurrence' | 'following'
export interface CalendarConnection { id: number; agent_id: number; label: string }
export interface CalendarFeed {
  resource_uri?: string
  id: number; connection_id: number; agent_id: number; label: string; tool_label: string; owner_label: string | null
  source_kind: 'internal' | 'ical' | 'caldav' | 'google' | 'microsoft' | 'icloud'; timezone: string; writable: boolean; initialized: boolean
  actions_enabled: boolean; is_default: boolean; origin: string; url_configured: boolean; username_configured: boolean
  password_configured: boolean; active: boolean; last_synced_at: string | null; last_checked_at: string | null
  last_error: string | null
  sync_interval_hours: number; next_sync_at: string | null
}
export interface CalendarEvent {
  contact_id?: string | null
  memory_event?: MemoryAgendaOccurrence
  goal_event?: GoalAgendaEvent
  event_id: string; occurrence_id: string | null; recurrence_key: string; revision: number; recurring: boolean
  sync_state: SyncState; calendar_id: number; calendar_label: string; uid: string; summary: string
  description: string; location: string; start: string; end: string; all_day: boolean
  start_date: string | null; end_date: string | null; timezone_name: string; status: string; transparent: boolean
}
export interface EventDetail {
  contact_id?: string | null
  event_id: string; calendar_id: number; uid: string; revision: number; timezone: string; summary: string
  description: string; location: string; start: string; end: string; all_day: boolean
  start_date: string | null; end_date: string | null; recurring: boolean; deleted: boolean
  rrule: string | null; rdates: string[]; exdates: string[]; sync_state: SyncState; ical: string
  alarms: { key: string; at: string; anchor: 'start' | 'end' | 'absolute'; offset_seconds: number | null }[]
}
export interface CalendarReminder {
  id: string; calendar_id: number; calendar_label: string; event_uid: string; event_summary: string
  reminder_at: string; dispatch_status: string; task_uri: string | null; task_status: string | null
  state: ExecutionState; treated: boolean; event_id: string | null; recurrence_key: string; action_key: string; reason: string | null
}
export interface CalendarAction {
  id: string; event_id: string; revision: number; recurrence_key: string | null; anchor: 'start' | 'end'
  offset_minutes: number; instructions: string; active: boolean; max_lateness_minutes: number
}
export type ActionWrite = Omit<CalendarAction, 'id' | 'event_id' | 'revision'> & { expected_revision?: number; request_key?: string }
export interface EventCreate {
  contact_id?: string | null
  summary: string; description: string; location: string; start: string; end: string; timezone: string
  uid?: string; rrule?: string | null; reminder_minutes_before?: number | null
}
export type EventUpdate = Partial<EventCreate> & { expected_revision: number; scope: EventScope; recurrence_key?: string; clear_recurrence?: boolean; clear_reminder?: boolean }
export interface MutationReceipt { event_id: string; calendar_id: number; uid: string; revision: number; sync_state: SyncState; state: string }
export interface CalendarConnectionStatus { calendar_id: number; ok: boolean; sync_run_id?: string | null; events_seen: number; next_events: { uid: string; summary: string; start: string; end: string; all_day: boolean }[] }
export interface EventWindow { items: CalendarEvent[]; total: number; complete: boolean; stale_calendar_ids: number[] }
export interface CalendarConflict { event_id: string; uid: string; revision: number; local_deleted: boolean; remote_deleted: boolean; local_ical: string; remote_ical: string | null }
export interface SyncProgress {
  calendar_changed: boolean
  steps: { stage: string; started_at: string; finished_at: string | null }[]
  server_reached: boolean; network_phase: string | null; http_requests: number; last_http_status: number | null; calendars: number
  downloaded: number; download_total: number | null; applied: number; apply_total: number | null
  uploaded: number; upload_total: number | null; upload_succeeded: number; conflicts: number; deleted: number
  bytes_received: number; bytes_sent: number; transfer_completed: number; transfer_total: number | null
}
export interface SyncRun { id: string; stage: string; state: string; error_category: string | null; error_location?: string | null; http_status: number | null; started_at: string; finished_at: string | null; progress?: SyncProgress }
export interface EventHistory { revision: number; deleted: boolean; created_at: string; ical: string }
export interface ExecutionSummary { event_id: string; recurrence_key: string; total: number; states: Partial<Record<ExecutionState, number>> }
const eventPath = (calendar: number, event: string) => `/calendars/${calendar}/events/${encodeURIComponent(event)}`

export const calendarService = {
  async get(id: number, signal?: AbortSignal): Promise<CalendarFeed> { return (await api.get(`/calendars/${id}`, { signal })).data },
  async searchResources(query: string): Promise<{ id: number; uri: string; label: string; agent_id: number }[]> {
    return (await api.get('/calendars/resources', { params: { query, limit: 50 } })).data
  },
  async deleteFeed(id: number): Promise<void> { await api.delete(`/calendars/${id}`) },
  async executionStates(connection: number, occurrences: { event_id: string; recurrence_key: string }[], signal?: AbortSignal): Promise<ExecutionSummary[]> {
    return (await api.post('/calendars/execution-states', { connection_id: connection, occurrences }, { signal })).data
  },
  async connections(signal?: AbortSignal): Promise<CalendarConnection[]> { return (await api.get('/calendars/connection-options', { signal })).data },
  async list(connectionId: number, signal?: AbortSignal): Promise<CalendarFeed[]> { return (await api.get('/calendars', { params: { connection_id: connectionId }, signal })).data },
  async events(agent: number, start: string, end: string, calendars: number[], signal?: AbortSignal): Promise<EventWindow> {
    return (await api.get('/calendars/events', { params: { agent_id: agent, start, end, calendar_ids: calendars }, paramsSerializer: { indexes: null }, signal })).data
  },
  async detail(calendar: number, event: string, recurrenceKey?: string, signal?: AbortSignal): Promise<EventDetail> {
    return (await api.get(eventPath(calendar, event), { params: { recurrence_key: recurrenceKey }, signal })).data
  },
  async createEvent(calendar: number, data: EventCreate): Promise<MutationReceipt> { return (await api.post(`/calendars/${calendar}/events`, data)).data },
  async updateEvent(calendar: number, event: string, data: EventUpdate): Promise<MutationReceipt> { return (await api.put(eventPath(calendar, event), data)).data },
  async deleteEvent(calendar: number, event: string, data: { expected_revision: number; scope: EventScope; recurrence_key?: string }): Promise<MutationReceipt> {
    return (await api.delete(eventPath(calendar, event), { data })).data
  },
  async actions(calendar: number, event: string, signal?: AbortSignal): Promise<CalendarAction[]> { return (await api.get(`${eventPath(calendar, event)}/actions`, { signal })).data },
  async saveAction(calendar: number, event: string, data: ActionWrite, id?: string): Promise<CalendarAction> {
    const path = `${eventPath(calendar, event)}/actions`
    return (await (id ? api.put(`${path}/${id}`, data) : api.post(path, data))).data
  },
  async reminders(connection: number, skip = 0, limit = 50, filter: { event_id?: string; recurrence_key?: string } = {}, signal?: AbortSignal): Promise<{ items: CalendarReminder[]; total: number }> {
    return (await api.get('/calendars/reminders', { params: { connection_id: connection, skip, limit, ...filter }, signal })).data
  },
  async relaunch(calendar: number, execution: string, revision: number, key: string): Promise<{ id: string; state: string; task_uri: string | null }> {
    return (await api.post(`/calendars/${calendar}/executions/${execution}/relaunch`, { request_key: key, expected_event_revision: revision })).data
  },
  async updateFeed(id: number, data: Partial<Pick<CalendarFeed, 'label' | 'owner_label' | 'active' | 'actions_enabled'>>): Promise<CalendarFeed> { return (await api.put(`/calendars/${id}`, data)).data },
  async test(id: number): Promise<CalendarConnectionStatus> { return (await api.post(`/calendars/${id}/test`)).data },
  async conflicts(id: number, skip = 0): Promise<CalendarConflict[]> { return (await api.get(`/calendars/${id}/conflicts`, { params: { skip, limit: 50 } })).data },
  async resolve(calendar: number, event: string, revision: number, choice: 'local' | 'remote'): Promise<MutationReceipt> { return (await api.post(`${eventPath(calendar, event)}/resolve`, { expected_revision: revision, choice })).data },
  async syncRuns(id: number, skip = 0, signal?: AbortSignal, runId?: string | null, limit = 50): Promise<SyncRun[]> { return (await api.get(`/calendars/${id}/sync-runs`, { params: { skip, limit, run_id: runId || undefined }, signal })).data },
  async history(calendar: number, event: string, skip = 0): Promise<EventHistory[]> { return (await api.get(`${eventPath(calendar, event)}/history`, { params: { skip, limit: 50 } })).data },
}
