<template>
  <q-page class="calendar-workspace q-pa-md">
    <PageHeader icon="calendar_month" :title="t('calendars.title')" :description="t('agenda.workspaceDescription')" />
    <q-banner v-if="error || feedError || goalError || memoryError" class="q-mb-md" role="alert">{{ error || feedError || goalError || memoryError }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="initialize" /></template></q-banner>
    <div class="calendar-toolbar">
      <AgentSelect v-model="agentId" :options="agentOptions" :load-agents="false" outlined dense :label="t('agenda.agent')" class="agent-select" />
      <div class="calendar-date-navigation">
        <q-btn class="calendar-today" outline color="primary" :dense="$q.screen.lt.md" :no-caps="$q.screen.lt.md" :label="t('agenda.today')" @click="date = today" />
        <div class="calendar-period-arrows row no-wrap"><q-btn class="calendar-previous" flat round :dense="$q.screen.lt.md" color="primary" icon="chevron_left" :aria-label="t('agenda.previous')" @click="navigate(-1)" /><q-btn class="calendar-next" flat round :dense="$q.screen.lt.md" color="primary" icon="chevron_right" :aria-label="t('agenda.next')" @click="navigate(1)" /></div>
        <h2 class="calendar-period">{{ periodLabel }}</h2>
      </div>
      <div class="calendar-display-settings">
        <q-btn-toggle v-model="view" :options="viewOptions" color="primary" text-color="primary" toggle-color="primary" toggle-text-color="white" no-caps unelevated :spread="$q.screen.lt.md" role="group" :aria-label="t('agenda.view')" class="view-toggle" />
        <CalendarTimezoneSelect v-model="timezone" :label="t('agenda.timezone')" class="timezone-select" />
        <div class="calendar-utilities">
          <q-btn flat round :dense="$q.screen.lt.md" color="primary" icon="refresh" :aria-label="t('agenda.refresh')" :loading="loading || refreshing" @click="refresh" />
          <q-btn v-if="$q.screen.lt.md" flat round dense color="primary" icon="filter_list" :aria-label="t('agenda.showCalendars')" @click="sidebarOpen = !sidebarOpen" />
        </div>
      </div>
    </div>
    <div class="calendar-layout">
      <aside v-if="!$q.screen.lt.md || sidebarOpen" class="calendar-sidebar">
        <CalendarMiniDate v-model="date" :locale="dateLocale" />
        <q-input :model-value="date" type="date" outlined dense stack-label :label="t('agenda.date')" @update:model-value="selectDate" />
        <div class="text-subtitle2 q-mt-md">{{ t('agenda.calendars') }}</div>
        <q-linear-progress v-if="loading" indeterminate color="primary" />
        <q-list dense><q-item v-for="(feed, index) in feeds" :key="feed.id" class="calendar-choice" clickable role="button" :aria-label="t('agenda.settingsForCalendar', { calendar: calendarLabel(feed, t) })" @click="settingsId = feed.id; settingsOpen = true"><q-item-section>
          <div class="row items-center no-wrap"><q-checkbox v-model="selectedIds" :val="feed.id" :disable="!feed.active" :aria-label="calendarLabel(feed, t)" :style="{ '--calendar-accent': solaireCss[calendarColor(feed.id, index)].accent }" @click.stop />
            <div class="col"><span>{{ calendarLabel(feed, t) }}</span><q-icon v-if="feed.is_default" name="star" size="16px" class="q-ml-xs" :style="{ color: solaireCss.yellow.accent }" role="img" :aria-label="t('agenda.defaultCalendar')"><q-tooltip>{{ t('agenda.defaultCalendar') }}</q-tooltip></q-icon></div>
          </div>
          <q-item-label caption class="q-pl-sm">{{ calendarSourceLabel(feed, t) }}<q-icon v-if="!feed.writable" name="lock" size="12px" :title="t('agenda.readOnly')" /></q-item-label>
        </q-item-section><q-item-section side @click.stop><CalendarRowMenu :id="feed.id" :label="calendarLabel(feed, t)" :visible="selectedIds.includes(feed.id)" :active="feed.active" :synchronizable="canEdit && feed.source_kind !== 'internal'" @visibility="toggleFeed(feed.id)" @edit="settingsId = feed.id; settingsOpen = true" @sync="syncFeedId = feed.id" /></q-item-section></q-item>
          <q-item v-if="canReadGoals" class="calendar-choice" clickable role="button" :aria-label="t('agenda.settingsForCalendar', { calendar: t('goal.agenda.layer') })" @click="settingsId = 0; settingsOpen = true"><q-item-section>
            <div class="row items-center no-wrap"><q-checkbox v-model="showGoals" :aria-label="t('goal.agenda.layer')" :style="{ '--calendar-accent': solaireCss[calendarColor(0)].accent }" @click.stop /><span class="col">{{ t('goal.agenda.layer') }}</span></div>
            <q-item-label caption class="q-pl-sm">{{ t('agenda.sources.internal') }}</q-item-label>
          </q-item-section><q-item-section side @click.stop><CalendarRowMenu :id="0" :label="t('goal.agenda.layer')" :visible="showGoals" @visibility="showGoals = !showGoals" @edit="settingsId = 0; settingsOpen = true" /></q-item-section></q-item>
          <q-item v-if="canReadMemory" class="calendar-choice" clickable role="button" :aria-label="t('agenda.settingsForCalendar', { calendar: t('agenda.memoryLayer') })" @click="settingsId = -1; settingsOpen = true"><q-item-section>
            <div class="row items-center no-wrap"><q-checkbox v-model="showMemory" :aria-label="t('agenda.memoryLayer')" :style="{ '--calendar-accent': solaireCss[calendarColor(-1)].accent }" @click.stop /><span class="col">{{ t('agenda.memoryLayer') }}</span></div>
            <q-item-label caption class="q-pl-sm">{{ t('agenda.sources.internal') }}</q-item-label>
          </q-item-section><q-item-section side @click.stop><CalendarRowMenu :id="-1" :label="t('agenda.memoryLayer')" :visible="showMemory" @visibility="showMemory = !showMemory" @edit="settingsId = -1; settingsOpen = true" /></q-item-section></q-item>
        </q-list>
        <p v-if="!loading && !feeds.length" class="text-caption">{{ t('calendars.empty') }}</p>
      </aside>
      <main class="calendar-main">
        <q-banner v-if="stale" class="stale-banner q-mb-sm" role="status">{{ t('agenda.stale') }}</q-banner>
        <q-linear-progress v-if="refreshing" indeterminate color="primary" class="q-mb-xs" />
        <div v-if="loading" class="calendar-loading" role="status"><q-spinner size="32px" color="primary" /><span>{{ t('agenda.loading') }}</span></div>
        <q-banner v-else-if="!selectedIds.length && !(canReadGoals && showGoals) && !(canReadMemory && showMemory)">{{ t('agenda.noSelection') }}</q-banner>
        <CalendarBoard v-else :view="view" :days="days" :date="date" :timezone="timezone" :events="events" :feeds="feeds" :colors="calendarColors" :executions="executions" :can-create="canEdit && writableFeeds.length > 0 && !refreshing" :can-edit="canEdit && !refreshing"
          @open="open" @create="create" @day="openDay" @move="prepareMove" />
      </main>
    </div>
    <CalendarEventPanel v-if="selectedEvent && selectedFeed && !editor" :key="occurrenceKey(selectedEvent)" :event="selectedEvent" :feed="selectedFeed" :can-edit="canEdit" @close="selectedEvent = null" @changed="loadEvents(false)" @edit="edit" @settings="settingsId = selectedFeed.id; settingsOpen = true" />
    <GoalAgendaPanel v-if="selectedEvent?.goal_event && canReadGoals && !editor" :event="selectedEvent.goal_event" @close="selectedEvent = null" @changed="loadEvents(false)" />
    <ResourceDetailDialog v-if="selectedEvent?.memory_event && canReadMemory && agentId" :key="selectedEvent.memory_event.memory_id"
      :target="{ kind: 'memory', id: selectedEvent.memory_event.memory_id, title: selectedEvent.summary, agentId }" @close="selectedEvent = null; loadEvents(false)" />
    <CalendarEventEditor v-if="editor" :key="editorKey" :feeds="feeds" :detail="editor.detail" :master="editor.master" :recurrence-key="editor.recurrenceKey" :date="editor.date" :time="editor.time" :end-time="editor.endTime" :timezone="timezone" :calendar-id="editor.calendarId" @close="editor = null" @saved="saved" @reload="reloadEditor" />
    <CalendarSettings v-if="settingsOpen" :feeds="feeds" :colors="calendarColors" :initial-id="settingsId" :can-edit="canEdit" @close="settingsOpen = false" @changed="loadFeeds(true)" @color="setCalendarColor" />
    <q-dialog :model-value="syncFeedId !== null" @update:model-value="!$event && (syncFeedId = null)">
      <q-card class="galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap"><div class="text-h6">{{ t('agenda.syncHistory') }}</div><q-space /><q-btn flat round dense icon="close" :aria-label="t('agenda.close')" @click="syncFeedId = null" /></q-card-section>
        <q-card-section class="galaris-dialog-body"><CalendarSyncMonitor v-if="syncFeedId !== null" ref="syncMonitor" :key="syncFeedId" :calendar-id="syncFeedId" :show-trigger="false" auto-start @changed="refresh" /></q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right"><q-btn color="primary" icon="sync" :label="t('agenda.newSync')" :loading="syncMonitor?.requesting" :disable="!syncMonitor?.canStart" @click="syncMonitor?.start()" /></q-card-actions>
      </q-card>
    </q-dialog>
    <CalendarConfirmDialog v-if="moving" :title="t('agenda.move')" :message="t('agenda.moveConfirm', { title: moving.event.summary, date: moving.day + (moving.time ? ' ' + moving.time : '') })" :confirm="t('agenda.move')" :busy="moveBusy" :error="moveError" @close="moving = null" @confirm="move">
      <q-select v-if="moving.event.recurring" v-model="moveScope" :options="scopeOptions" emit-value map-options outlined :label="t('agenda.scope')" />
    </CalendarConfirmDialog>
  </q-page>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { AUTH_TOKEN_CHANGED_EVENT, apiErrorDetail, isCancelledRequest, sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useAuthStore } from '@/core/user'
import { AgentSelect, getAgentSelection } from '@/app/agent'
import { GoalAgendaPanel, goalService, type GoalAgendaEvent } from '@/app/goal'
import { memoryService, type MemoryAgendaOccurrence } from '@/app/memory'
import { PageHeader, ResourceDetailDialog, solaireColors, solaireCss, type SolaireColor } from '@/core/util'
import { calendarLabel, calendarSourceLabel, defaultCalendarColor } from '../presentation'
import { addDays, addMonths, isoWeekNumber, occurrenceKey, queryWindows, visibleDays, wallTime, zonedInstant, type CalendarView } from '../calendarDates'
import { calendarService, type CalendarConnection, type CalendarEvent, type CalendarFeed, type EventDetail, type EventScope, type MutationReceipt } from '../services/calendarService'
import CalendarBoard from './CalendarBoard.vue'
import CalendarEventPanel from './CalendarEventPanel.vue'
import CalendarEventEditor from './CalendarEventEditor.vue'
import CalendarSettings from './CalendarSettings.vue'
import CalendarConfirmDialog from './CalendarConfirmDialog.vue'
import CalendarTimezoneSelect from './CalendarTimezoneSelect.vue'
import CalendarMiniDate from './CalendarMiniDate.vue'
import CalendarRowMenu from './CalendarRowMenu.vue'
import CalendarSyncMonitor from './CalendarSyncMonitor.vue'
import type { EventExecutionSummary } from './CalendarEventChip.vue'
const { t, locale } = useI18n(), $q = useQuasar(), privilegeStore = usePrivilegeStore(), route = useRoute(), router = useRouter()
const canRead = computed(() => privilegeStore.hasAnyPrivilege([privileges.CALENDAR_ACCESS, privileges.CALENDAR_EDIT]))
const canEdit = computed(() => privilegeStore.hasAnyPrivilege([privileges.CALENDAR_EDIT]))
const canReadGoals = computed(() => privilegeStore.hasAnyPrivilege([privileges.GOAL_ACCESS, privileges.GOAL_EDIT]))
const canReadMemory = computed(() => privilegeStore.hasAnyPrivilege([privileges.MEMORY_ACCESS, privileges.MEMORY_EDIT, privileges.MEMORY_ADMIN]))
const showMemory = ref(true), memoryError = ref('')
const showGoals = ref(true)
const auth = useAuthStore(), colorOverrides = ref<Record<string, SolaireColor>>({})
const colorStorageKey = computed(() => auth.user?.id ? `galaris:calendar-colors:${auth.user.id}` : null)
watch(colorStorageKey, key => {
  colorOverrides.value = {}
  if (!key) return
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? '{}')
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      colorOverrides.value = Object.fromEntries(Object.entries(saved).filter((entry): entry is [string, SolaireColor] => solaireColors.includes(entry[1] as SolaireColor)))
    }
  } catch { /* Use the palette defaults when storage is unavailable or invalid. */ }
}, { immediate: true })
const goalError = ref('')
const validDay = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
const validZone = (value: unknown): value is string => { if (typeof value !== 'string') return false; try { new Intl.DateTimeFormat('en', { timeZone: value }); return true } catch { return false } }
const views: CalendarView[] = ['month', 'week', 'day', 'list']
const timezone = ref(validZone(route.query.timezone) ? route.query.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone)
const today = computed(() => wallTime(new Date(), timezone.value).slice(0, 10))
const date = ref(validDay(route.query.date) ? route.query.date : today.value)
const view = ref<CalendarView>(views.includes(route.query.view as CalendarView) ? route.query.view as CalendarView : $q.screen.lt.md ? 'list' : 'month')
const agentId = ref<number | null>(null), agentOptions = ref<{ value: number; label: string; hasAvatar: boolean }[]>([]), connections = ref<CalendarConnection[]>([])
const feeds = ref<CalendarFeed[]>([]), selectedIds = ref<number[]>([]), events = ref<CalendarEvent[]>([]), executions = ref<Record<string, EventExecutionSummary>>({})
const loading = ref(false), refreshing = ref(false), error = ref(''), feedError = ref(''), stale = ref(false), sidebarOpen = ref(false)
const selectedEvent = ref<CalendarEvent | null>(null), selectedFeed = computed(() => feeds.value.find(feed => feed.id === selectedEvent.value?.calendar_id))
interface Editor { date: string; time?: string; endTime?: string; calendarId?: number; detail?: EventDetail; master?: EventDetail; recurrenceKey?: string }
const editor = ref<Editor | null>(null), editorKey = ref(0), settingsOpen = ref(false), settingsId = ref<number>()
const syncFeedId = ref<number | null>(null)
const syncMonitor = useTemplateRef<InstanceType<typeof CalendarSyncMonitor>>('syncMonitor')
const linkedCalendar = ref<number | null>(null)
function toggleFeed(id: number): void { selectedIds.value = selectedIds.value.includes(id) ? selectedIds.value.filter(value => value !== id) : [...selectedIds.value, id] }
let focusedCalendar: number | null = null
let alive = true, ready = false, initialGeneration = 0, feedGeneration = 0, eventGeneration = 0, stateGeneration = 0
let context = new AbortController(), eventController = new AbortController(), stateController = new AbortController(), poll: ReturnType<typeof setInterval> | undefined
let session = sessionGeneration()
const days = computed(() => visibleDays(date.value, view.value))
const writableFeeds = computed(() => feeds.value.filter(feed => feed.active && feed.writable))
const viewOptions = computed(() => views.map(value => ({ value, label: t(`agenda.views.${value}`), outline: view.value !== value })))
const scopeOptions = computed(() => ['occurrence', 'following', 'series'].map(value => ({ value, label: t(`agenda.scopes.${value}`) })))
const periodLabel = computed(() => {
  const format = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(locale.value, { timeZone: 'UTC', ...options }).format(new Date(`${day}T12:00:00Z`))
  if (view.value === 'month') return format(date.value, { month: 'long', year: 'numeric' })
  if (view.value === 'day') return format(date.value, { dateStyle: 'long' })
  const period = `${format(days.value[0]!, { day: 'numeric', month: 'short' })} – ${format(days.value.at(-1)!, { day: 'numeric', month: 'short', year: 'numeric' })}`
  return view.value === 'week' ? t('agenda.weekPeriod', { week: isoWeekNumber(date.value), period }) : period
})
const dateLocale = computed(() => ({ days: Array.from({ length: 7 }, (_, n) => new Intl.DateTimeFormat(locale.value, { weekday: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, 0, 4 + n)))), daysShort: Array.from({ length: 7 }, (_, n) => new Intl.DateTimeFormat(locale.value, { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, 0, 4 + n)))), months: Array.from({ length: 12 }, (_, n) => new Intl.DateTimeFormat(locale.value, { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, n, 1)))), monthsShort: Array.from({ length: 12 }, (_, n) => new Intl.DateTimeFormat(locale.value, { month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, n, 1)))) }))
function colorKey(id: number): string { return id > 0 ? `feed:${id}` : `agent:${agentId.value}:${id}` }
function calendarColor(id: number, index = 0): SolaireColor { return colorOverrides.value[colorKey(id)] ?? defaultCalendarColor(id, index) }
const calendarColors = computed(() => Object.fromEntries([...feeds.value.map((feed, index) => [feed.id, calendarColor(feed.id, index)]), [0, calendarColor(0)], [-1, calendarColor(-1)]]))
function setCalendarColor(id: number, color: SolaireColor): void {
  colorOverrides.value = { ...colorOverrides.value, [colorKey(id)]: color }
  try { if (colorStorageKey.value) localStorage.setItem(colorStorageKey.value, JSON.stringify(colorOverrides.value)) }
  catch { $q.notify({ type: 'warning', message: t('agenda.colorStorageError') }) }
}
function selectDate(value: unknown): void { if (validDay(value)) date.value = value }
function navigate(direction: number): void { date.value = view.value === 'month' ? addMonths(date.value, direction) : addDays(date.value, direction * (view.value === 'week' ? 7 : view.value === 'list' ? 30 : 1)) }
function openDay(day: string): void { date.value = day; view.value = 'day'; sidebarOpen.value = false }
function open(event: CalendarEvent): void { selectedEvent.value = event }
function goalEvent(row: GoalAgendaEvent): CalendarEvent {
  return { event_id: row.id, occurrence_id: row.projected ? null : row.id, recurrence_key: row.id,
    revision: 1, recurring: row.projected, sync_state: 'local', calendar_id: 0,
    calendar_label: t('goal.agenda.layer'), uid: row.id, summary: row.title, description: '', location: '',
    start: row.scheduled_at, end: row.scheduled_at, all_day: false, start_date: null, end_date: null,
    timezone_name: row.timezone, status: row.state, transparent: true, goal_event: row }
}
function memoryEvent(row: MemoryAgendaOccurrence): CalendarEvent {
  return { event_id: row.id, occurrence_id: row.id, recurrence_key: row.start, revision: row.revision,
    recurring: false, sync_state: 'local', calendar_id: -1, calendar_label: t('agenda.memoryLayer'),
    uid: row.id, summary: row.title, description: row.excerpt, location: '', start: row.start, end: row.end,
    all_day: row.all_day, start_date: row.all_day ? wallTime(row.start, row.timezone).slice(0, 10) : null,
    end_date: row.all_day ? wallTime(row.end, row.timezone).slice(0, 10) : null,
    timezone_name: row.timezone, status: '', transparent: true, memory_event: row }
}
function create(day: string, time?: string, endTime?: string): void { if (!canEdit.value || !writableFeeds.value.length) return; selectedEvent.value = null; editorKey.value++; editor.value = { date: day, time, endTime, calendarId: writableFeeds.value.find(feed => feed.is_default && selectedIds.value.includes(feed.id))?.id ?? writableFeeds.value.find(feed => selectedIds.value.includes(feed.id))?.id ?? writableFeeds.value.find(feed => feed.is_default)?.id ?? writableFeeds.value[0]?.id } }
function edit(detail: EventDetail, master: EventDetail): void { editorKey.value++; editor.value = { date: date.value, detail, master, recurrenceKey: selectedEvent.value?.recurrence_key } }
async function reloadEditor(): Promise<void> {
  const current = editor.value, token = eventGeneration
  if (!current?.detail) return
  try { const detail = await calendarService.detail(current.detail.calendar_id, current.detail.event_id, current.recurrenceKey); const master = detail.recurring ? await calendarService.detail(detail.calendar_id, detail.event_id) : detail; if (alive && token === eventGeneration && editor.value === current) { editorKey.value++; editor.value = { ...current, detail, master } } }
  catch (caught) { if (alive && token === eventGeneration) $q.notify({ type: 'negative', message: apiErrorDetail(caught) ?? t('agenda.error') }) }
}
function resetContext(): void {
  syncFeedId.value = null
  context.abort(); eventController.abort(); stateController.abort(); context = new AbortController(); feedGeneration++; eventGeneration++; stateGeneration++
  feeds.value = []; selectedIds.value = []; events.value = []; executions.value = {}; selectedEvent.value = null; editor.value = null; moving.value = null; moveBusy.value = false; settingsOpen.value = false; error.value = ''; feedError.value = ''; goalError.value = ''; stale.value = false
}
async function initialize(): Promise<void> {
  const token = ++initialGeneration
  if (!canRead.value) return
  loading.value = true; error.value = ''
  try {
    const requestedId = typeof route.query.calendar_id === 'string' && /^[1-9][0-9]*$/.test(route.query.calendar_id) ? Number(route.query.calendar_id) : null
    const [options, agents, requestedFeed] = await Promise.all([calendarService.connections(context.signal), getAgentSelection('management', context.signal), requestedId ? calendarService.get(requestedId, context.signal) : Promise.resolve(null)])
    if (!alive || token !== initialGeneration) return
    connections.value = options
    agentOptions.value = agents.filter(agent => options.some(option => option.agent_id === agent.id)).map(agent => ({ value: agent.id, label: agent.label, hasAvatar: agent.has_avatar }))
    const requested = requestedFeed?.agent_id ?? Number(route.query.agent_id), chosen = agentOptions.value.find(agent => agent.value === requested)?.value ?? agentOptions.value.find(agent => agent.value === agentId.value)?.value ?? agentOptions.value[0]?.value ?? null
    const changed = agentId.value !== chosen
    ready = false
    if (changed) resetContext()
    linkedCalendar.value = requestedFeed?.id ?? null
    agentId.value = chosen
    focusedCalendar = requestedFeed?.id ?? null
    ready = true
    await loadFeeds(!changed)
  } catch (caught) { if (alive && token === initialGeneration && !isCancelledRequest(caught)) error.value = apiErrorDetail(caught) ?? t('agenda.loadError') }
  finally { if (alive && token === initialGeneration) loading.value = false }
}
async function loadFeeds(preserve = false): Promise<void> {
  const agent = agentId.value, token = ++feedGeneration
  if (!agent || !canRead.value) { loading.value = false; return }
  loading.value = true; feedError.value = ''
  const options = connections.value.filter(connection => connection.agent_id === agent)
  const result = await Promise.allSettled(options.map(option => calendarService.list(option.id, context.signal)))
  if (!alive || token !== feedGeneration || agentId.value !== agent) return
  const previous = new Set(feeds.value.map(feed => feed.id)), existing = selectedIds.value
  feeds.value = result.flatMap(row => row.status === 'fulfilled' ? row.value : [])
  feedError.value = result.some(row => row.status === 'rejected') ? t('agenda.loadError') : ''
  selectedIds.value = feeds.value.filter(feed => feed.active && (!preserve || !previous.has(feed.id) || existing.includes(feed.id))).map(feed => feed.id)
  if (focusedCalendar !== null) {
    selectedIds.value = feeds.value.filter(feed => feed.id === focusedCalendar && feed.active).map(feed => feed.id)
    showGoals.value = false; showMemory.value = false; focusedCalendar = null
  }
  if (!preserve && !route.query.timezone && feeds.value[0]) timezone.value = feeds.value[0].timezone
  await nextTick()
  if (!alive || token !== feedGeneration) return
  loading.value = false
  await loadEvents(false)
}
async function loadEvents(clear = true): Promise<void> {
  eventController.abort(); stateController.abort(); eventController = new AbortController()
  const token = ++eventGeneration, agent = agentId.value
  if (clear) { events.value = []; executions.value = {}; selectedEvent.value = null }
  if (!agent || (!selectedIds.value.length && !(canReadGoals.value && showGoals.value) && !(canReadMemory.value && showMemory.value)) || !canRead.value) { events.value = []; refreshing.value = false; return }
  refreshing.value = true; error.value = ''; goalError.value = ''; memoryError.value = ''
  try {
    const windows = queryWindows(days.value, timezone.value)
    const [result, goalWindows, memoryWindows] = await Promise.all([
      selectedIds.value.length ? Promise.all(windows.map(window => calendarService.events(agent, window.start, window.end, selectedIds.value, eventController.signal))) : Promise.resolve([]),
      canReadGoals.value && showGoals.value ? Promise.all(windows.map(window => goalService.agenda(agent, window.start, window.end, eventController.signal))).catch(caught => {
        if (alive && token === eventGeneration && !isCancelledRequest(caught)) goalError.value = t('goal.agenda.loadError')
        return []
      }) : Promise.resolve([]),
      canReadMemory.value && showMemory.value ? Promise.all(windows.map(window => memoryService.agenda(agent, window.start, window.end, eventController.signal))).catch(caught => {
        if (alive && token === eventGeneration && !isCancelledRequest(caught)) memoryError.value = t('agenda.memoryLoadError')
        return []
      }) : Promise.resolve([]),
    ])
    if (!alive || token !== eventGeneration) return
    events.value = [...new Map([...result.flatMap(window => window.items), ...goalWindows.flatMap(window => window.items.map(goalEvent)), ...memoryWindows.flatMap(window => window.items.map(memoryEvent))].map(event => [occurrenceKey(event), event])).values()].sort((a, b) => a.start.localeCompare(b.start))
    const next = { ...executions.value }
    for (const event of events.value) if (event.goal_event) next[occurrenceKey(event)] = { total: 1, states: { [event.goal_event.state]: 1 } }
    for (const event of events.value) if (event.memory_event) next[occurrenceKey(event)] = { total: 0 }
    executions.value = next
    if (selectedEvent.value?.goal_event) selectedEvent.value = events.value.find(event => event.event_id === selectedEvent.value?.event_id) ?? null
    if (selectedEvent.value?.memory_event) selectedEvent.value = events.value.find(event => event.event_id === selectedEvent.value?.event_id) ?? null
    stale.value = [...result, ...goalWindows].some(window => !window.complete)
    void loadStates()
  } catch (caught) { if (alive && token === eventGeneration && !isCancelledRequest(caught)) error.value = apiErrorDetail(caught) ?? t('agenda.loadError') }
  finally { if (alive && token === eventGeneration) refreshing.value = false }
}
async function loadStates(): Promise<void> {
  stateController.abort(); stateController = new AbortController()
  const token = ++stateGeneration, groups = new Map<number, CalendarEvent[]>()
  const connectionsByFeed = new Map(feeds.value.map(feed => [feed.id, feed.connection_id]))
  for (const event of events.value) {
    const connection = connectionsByFeed.get(event.calendar_id)
    if (connection && !event.goal_event && !event.memory_event) { const group = groups.get(connection) ?? []; group.push(event); groups.set(connection, group) }
  }
  const requests: { connection: number; items: CalendarEvent[] }[] = []
  for (const [connection, items] of groups) for (let offset = 0; offset < items.length; offset += 500) requests.push({ connection, items: items.slice(offset, offset + 500) })
  async function worker(): Promise<void> {
    while (requests.length && alive && token === stateGeneration) {
      const batch = requests.shift()!
      try {
        const states = await calendarService.executionStates(batch.connection, batch.items.map(event => ({ event_id: event.event_id, recurrence_key: event.recurrence_key })), stateController.signal)
        if (!alive || token !== stateGeneration) return
        const next = { ...executions.value }; for (const row of states) next[occurrenceKey(row)] = row; executions.value = next
      } catch (caught) {
        if (!alive || token !== stateGeneration || isCancelledRequest(caught)) return
        const next = { ...executions.value }; batch.items.forEach(event => { next[occurrenceKey(event)] = { total: 0, failed: true } }); executions.value = next
      }
    }
  }
  await Promise.all([worker(), worker()])
}
async function refresh(): Promise<void> { await loadFeeds(true) }
async function saved(receipt: MutationReceipt): Promise<void> {
  editor.value = null; selectedEvent.value = null; $q.notify({ type: 'positive', message: t(receipt.sync_state === 'pending' ? 'agenda.pendingSync' : 'agenda.saved') }); await loadEvents(false)
  if (alive) selectedEvent.value = events.value.find(event => event.event_id === receipt.event_id) ?? null
}
const moving = ref<{ event: CalendarEvent; day: string; time?: string } | null>(null), moveScope = ref<EventScope>('occurrence'), moveBusy = ref(false), moveError = ref('')
function prepareMove(event: CalendarEvent, day: string, time?: string): void { moving.value = { event, day, time }; moveScope.value = event.recurring ? 'occurrence' : 'series'; moveError.value = '' }
async function move(): Promise<void> {
  const target = moving.value, token = feedGeneration
  if (!target || moveBusy.value) return
  moveBusy.value = true; moveError.value = ''
  try {
    const detail = await calendarService.detail(target.event.calendar_id, target.event.event_id, target.event.recurrence_key || undefined)
    const master = target.event.recurring && moveScope.value === 'series' ? await calendarService.detail(target.event.calendar_id, target.event.event_id) : detail
    const dayDelta = Math.round((Date.parse(target.day) - Date.parse(wallTime(target.event.start, timezone.value).slice(0, 10))) / 86400000)
    let start: string, end: string
    if (detail.all_day) { start = addDays(master.start_date ?? master.start.slice(0, 10), dayDelta); end = addDays(master.end_date ?? master.end.slice(0, 10), dayDelta) }
    else {
      const local = wallTime(master.start, timezone.value)
      start = zonedInstant(`${addDays(local.slice(0, 10), dayDelta)}T${target.time ?? local.slice(11)}`, timezone.value)
      end = new Date(Date.parse(start) + Date.parse(master.end) - Date.parse(master.start)).toISOString()
    }
    if (!alive || token !== feedGeneration) return
    await calendarService.updateEvent(target.event.calendar_id, target.event.event_id, { start, end, expected_revision: target.event.revision, scope: moveScope.value, ...(moveScope.value !== 'series' ? { recurrence_key: target.event.recurrence_key } : {}) })
    if (!alive || token !== feedGeneration) return
    moving.value = null; $q.notify({ type: 'positive', message: t('agenda.moved') }); await loadEvents(false)
  } catch (caught) { if (alive && token === feedGeneration) moveError.value = apiErrorDetail(caught) ?? t('agenda.invalidDate') }
  finally { if (alive && token === feedGeneration) moveBusy.value = false }
}
watch(agentId, () => { if (!ready) return; linkedCalendar.value = null; resetContext(); void loadFeeds() }, { flush: 'sync' })
watch([date, view, timezone, selectedIds, showGoals, canReadGoals, showMemory, canReadMemory], () => { if (ready && !loading.value) void loadEvents() })
watch([agentId, date, view, timezone], () => { if (ready) void router.replace({ query: { ...route.query, calendar_id: linkedCalendar.value ?? undefined, agent_id: agentId.value ?? undefined, date: date.value, view: view.value, timezone: timezone.value } }) })
watch(() => [route.query.agent_id, route.query.date, route.query.view, route.query.timezone], () => {
  const requested = Number(route.query.agent_id)
  if (agentOptions.value.some(agent => agent.value === requested)) agentId.value = requested
  if (validDay(route.query.date)) date.value = route.query.date
  if (views.includes(route.query.view as CalendarView)) view.value = route.query.view as CalendarView
  if (validZone(route.query.timezone)) timezone.value = route.query.timezone
})
watch(() => route.query.calendar_id, value => { if (ready && value) void initialize() })
watch(canRead, allowed => { if (!allowed) { initialGeneration++; resetContext(); connections.value = []; agentOptions.value = []; agentId.value = null } else void initialize() })
watch(canEdit, allowed => { if (!allowed) { editor.value = null; moving.value = null; syncFeedId.value = null } })
function sessionChanged(): void { const current = sessionGeneration(); if (current !== session) { session = current; initialGeneration++; resetContext(); connections.value = []; agentOptions.value = []; agentId.value = null; void initialize() } }
onMounted(() => { void initialize(); window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged); poll = setInterval(() => { if (!document.hidden && !refreshing.value && !loading.value) void loadEvents(false) }, 30_000) })
onBeforeUnmount(() => { alive = false; initialGeneration++; context.abort(); eventController.abort(); stateController.abort(); clearInterval(poll); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
</script>
<style scoped>
.calendar-workspace { min-width: 0; --calendar-sidebar-width: 228px; --calendar-column-gap: 20px; }
.calendar-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 16px; }
.calendar-date-navigation, .calendar-utilities { display: contents; }
.agent-select { width: var(--calendar-sidebar-width); flex-shrink: 0; margin-right: calc(var(--calendar-column-gap) - 10px); }
.calendar-display-settings { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; margin-left: auto; }
.timezone-select { width: 210px; max-width: 100%; }
.calendar-period { font-size: 20px; font-weight: 500; line-height: 1.4; margin: 0; flex: 1; min-width: 180px; }
.calendar-layout { display: grid; grid-template-columns: var(--calendar-sidebar-width) minmax(0, 1fr); gap: var(--calendar-column-gap); }
.calendar-sidebar { min-width: 0; }
.calendar-choice { padding: 6px 0; }
.calendar-choice :deep(.q-checkbox__inner--truthy) { color: var(--calendar-accent); }
@media (hover: hover) and (pointer: fine) {
  .calendar-choice > .q-item__section--side { opacity: 0; pointer-events: none; }
  .calendar-choice:hover > .q-item__section--side,
  .calendar-choice:focus-within > .q-item__section--side { opacity: 1; pointer-events: auto; }
}
.calendar-main { min-width: 0; }
.calendar-loading { min-height: 350px; display: flex; justify-content: center; align-items: center; gap: 12px; }
.stale-banner { background: var(--solaire-orange-light); }
.body--dark .stale-banner { background: var(--solaire-orange-dark); }
@media (max-width: 1023px) {
  .calendar-layout { grid-template-columns: 1fr; }
  .calendar-sidebar { max-width: 350px; }
  .calendar-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); grid-template-areas: 'agent agent' 'navigation navigation' 'display display'; gap: 10px; align-items: stretch; }
  .agent-select { grid-area: agent; width: 100%; min-width: 0; margin-right: 0; }
  .calendar-date-navigation { grid-area: navigation; display: grid; grid-template-columns: 32px minmax(0, 1fr) 32px auto; grid-template-areas: 'previous period next today'; align-items: center; gap: 6px; }
  .calendar-period-arrows { display: contents; }
  .calendar-today { grid-area: today; }
  .calendar-previous { grid-area: previous; }
  .calendar-next { grid-area: next; }
  .calendar-period { grid-area: period; min-width: 0; font-size: 18px; text-align: center; overflow-wrap: anywhere; }
  .calendar-display-settings { grid-area: display; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; margin-left: 0; }
  .view-toggle { grid-column: 1 / -1; min-width: 0; }
  .timezone-select { width: 100%; min-width: 0; }
  .calendar-utilities { display: flex; align-items: center; justify-content: flex-end; gap: 2px; }
}
@media (max-width: 479px) {
  .calendar-period { font-size: 16px; }
}
</style>
