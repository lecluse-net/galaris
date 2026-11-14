<template>
  <q-dialog :model-value="true" :maximized="$q.screen.lt.md" @update:model-value="!$event && emit('close')">
    <q-card class="galaris-dialog-card event-editor">
      <q-card-section class="galaris-dialog-title row items-center no-wrap"><div class="text-subtitle1">{{ t(detail ? 'agenda.editEvent' : 'agenda.newEvent') }}</div><q-space /><q-btn flat round dense icon="close" :aria-label="t('agenda.close')" @click="emit('close')" /></q-card-section>
      <q-form class="galaris-dialog-form" @submit="save">
        <q-card-section class="galaris-dialog-body q-gutter-y-md">
          <q-banner v-if="error" class="error-banner" role="alert">{{ error }}<template v-if="conflict" #action><q-btn outline color="primary" :label="t('agenda.reload')" @click="emit('reload')" /></template></q-banner>
          <q-banner v-if="nativeProvider" role="note">{{ t('agenda.nativeSeriesHint') }}</q-banner>
          <fieldset :disabled="busy" :inert="busy" class="event-fields q-gutter-y-md">
            <q-input v-model="form.summary" outlined autofocus :label="t('agenda.summary')" :maxlength="500" :rules="[required]" />
            <q-select v-model="form.calendarId" outlined dense :options="calendarOptions" emit-value map-options :disable="Boolean(detail)" :label="t('agenda.calendar')" :rules="[required]" />
            <ContactSelect v-if="contactAgentId" v-model="form.contactId" :agent-id="contactAgentId" :label="t('agenda.linkedContact')" :disable="Boolean(detail?.recurring && scope !== 'series')" />
            <p v-if="detail?.recurring" class="text-caption">{{ t('agenda.contactSeriesHint') }}</p>
            <q-select v-if="detail?.recurring" v-model="scope" outlined dense :options="scopeOptions" emit-value map-options :label="t('agenda.scope')" @update:model-value="applyScope" />
            <p v-if="detail?.recurring && scope === 'series'" class="text-caption">{{ t('agenda.seriesHint') }}</p>
            <q-checkbox v-model="form.allDay" :label="t('agenda.allDay')" />
            <div class="date-fields"><q-input :model-value="form.startDate" outlined dense type="date" stack-label :label="t('agenda.startDate')" :rules="[required]" @update:model-value="changeStart('startDate', String($event ?? ''))" />
              <q-input v-if="!form.allDay" :model-value="form.startTime" outlined dense type="time" stack-label :label="t('agenda.startTime')" :rules="[required]" @update:model-value="changeStart('startTime', String($event ?? ''))" />
              <q-input v-model="form.endDate" outlined dense type="date" stack-label :label="t('agenda.endDate')" :rules="[required]" />
              <q-input v-if="!form.allDay" v-model="form.endTime" outlined dense type="time" stack-label :label="t('agenda.endTime')" :rules="[required]" /></div>
            <q-input v-model="form.timezone" outlined dense :label="t('agenda.eventTimezone')" :rules="[validTimezone]" />
            <RecurrenceEditor v-if="!detail || scope !== 'occurrence'" v-model="form.rrule" :all-day="form.allDay" :timezone="form.timezone" />
            <q-input v-model="form.location" outlined dense :label="t('agenda.location')" :maxlength="1000"><template #prepend><q-icon name="location_on" /></template></q-input>
            <q-input v-model="form.description" outlined type="textarea" autogrow :label="t('agenda.description')" :maxlength="20000" />
            <q-banner role="note">{{ t('agenda.automaticTask') }}</q-banner>
          </fieldset>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right"><q-btn outline color="primary" :label="t('agenda.cancel')" @click="emit('close')" /><q-btn type="submit" color="primary" :label="t('agenda.save')" :loading="busy" :disable="conflict" /></q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { isAxiosError } from 'axios'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { ContactSelect } from '@/app/memory'
import { addDays, wallTime, zonedInstant } from '../calendarDates'
import { calendarLabel } from '../presentation'
import { calendarService, type CalendarFeed, type EventDetail, type EventScope, type EventCreate, type MutationReceipt } from '../services/calendarService'
import RecurrenceEditor from './RecurrenceEditor.vue'
const props = defineProps<{ feeds: CalendarFeed[]; detail?: EventDetail; master?: EventDetail; recurrenceKey?: string; date: string; time?: string; endTime?: string; timezone: string; calendarId?: number }>()
const emit = defineEmits<{ close: []; saved: [receipt: MutationReceipt]; reload: [] }>()
const { t } = useI18n(), $q = useQuasar()
const busy = ref(false), error = ref(''), conflict = ref(false)
const scope = ref<EventScope>(props.detail?.recurring && props.recurrenceKey ? 'occurrence' : 'series')
const uid = `galaris-${crypto.randomUUID()}`
let alive = true
onBeforeUnmount(() => { alive = false })
const form = reactive({ summary: '', description: '', location: '', calendarId: props.calendarId ?? props.feeds.find(feed => feed.is_default && feed.writable && feed.active)?.id ?? props.feeds.find(feed => feed.writable && feed.active)?.id ?? null,
  contactId: null as string | null,
  allDay: !props.time, startDate: props.date, endDate: props.date, startTime: props.time ?? '09:00', endTime: props.time ? `${String(Math.min(23, Number(props.time.slice(0, 2)) + 1)).padStart(2, '0')}:${props.time.slice(3)}` : '10:00', timezone: props.timezone, rrule: null as string | null })
function fill(detail: EventDetail): void {
  const start = wallTime(detail.start, detail.timezone), end = wallTime(detail.end, detail.timezone)
  Object.assign(form, { summary: detail.summary, description: detail.description, location: detail.location, calendarId: detail.calendar_id, allDay: detail.all_day,
    contactId: detail.contact_id ?? null,
    startDate: detail.all_day ? detail.start_date ?? start.slice(0, 10) : start.slice(0, 10), endDate: detail.all_day ? addDays(detail.end_date ?? end.slice(0, 10), -1) : end.slice(0, 10),
    startTime: start.slice(11), endTime: end.slice(11), timezone: detail.timezone, rrule: detail.rrule })
}
if (props.detail) fill(props.detail)
else if (props.endTime) { form.endTime = props.endTime === '24:00' ? '00:00' : props.endTime; if (props.endTime === '24:00') form.endDate = addDays(props.date, 1) }
else if (props.time?.startsWith('23:')) { form.endDate = addDays(props.date, 1); form.endTime = `00:${props.time.slice(3)}` }
function applyScope(): void {
  const detail = scope.value === 'series' ? props.master ?? props.detail : props.detail
  // Changing scope only replaces the recurrence anchor; preserve the user's text draft.
  if (!detail) return
  const draft = { summary: form.summary, description: form.description, location: form.location, rrule: form.rrule, contactId: form.contactId }
  fill(detail); Object.assign(form, draft)
}
const calendarOptions = computed(() => props.feeds.filter(feed => feed.writable && feed.active || feed.id === props.detail?.calendar_id).map(feed => ({ value: feed.id, label: calendarLabel(feed, t) })))
const contactAgentId = computed(() => props.feeds.find(feed => feed.id === form.calendarId)?.agent_id)
const nativeProvider = computed(() => ['google', 'microsoft'].includes(props.feeds.find(feed => feed.id === form.calendarId)?.source_kind ?? ''))
const scopeOptions = computed(() => ['occurrence', 'following', 'series'].map(value => ({ value, label: t(`agenda.scopes.${value}`) })))
function changeStart(field: 'startDate' | 'startTime', value: string): void {
  const before = Date.parse(`${form.startDate}T${form.startTime}:00Z`)
  const after = Date.parse(`${field === 'startDate' ? value : form.startDate}T${field === 'startTime' ? value : form.startTime}:00Z`)
  const end = Date.parse(`${form.endDate}T${form.endTime}:00Z`)
  if ([before, after, end].every(Number.isFinite)) { const shifted = new Date(end + after - before).toISOString(); form.endDate = shifted.slice(0, 10); form.endTime = shifted.slice(11, 16) }
  form[field] = value
}
const required = (value: unknown) => Boolean(String(value ?? '').trim()) || t('agenda.required')
function validTimezone(value: string): boolean | string { try { new Intl.DateTimeFormat('en', { timeZone: value }); return true } catch { return t('agenda.invalidDate') } }
function temporal(wall: string, original?: string): string {
  // Preserve the exact instant of an existing repeated DST hour when its wall clock is unchanged.
  if (original && wallTime(original, form.timezone) === wall) return original
  return zonedInstant(wall, form.timezone)
}
async function save(): Promise<void> {
  if (nativeProvider.value && (form.rrule || props.detail?.recurring)) { error.value = t('agenda.nativeSeriesHint'); return }
  if (busy.value || !form.calendarId) return
  error.value = ''; conflict.value = false; busy.value = true
  try {
      let data: EventCreate
      try {
        const original = scope.value === 'series' ? props.master ?? props.detail : props.detail
        const start = form.allDay ? form.startDate : temporal(`${form.startDate}T${form.startTime}`, original?.start)
        const end = form.allDay ? addDays(form.endDate, 1) : temporal(`${form.endDate}T${form.endTime}`, original?.end)
        if (!start || !end || (form.allDay ? end <= start : Date.parse(end) <= Date.parse(start))) throw new Error('invalidDate')
        data = { summary: form.summary.trim(), description: form.description, location: form.location, start, end, timezone: form.timezone }
        if (!props.detail || scope.value === 'series') data.contact_id = form.contactId
        if (!props.detail || scope.value !== 'occurrence') data.rrule = form.rrule
      } catch { error.value = t('agenda.invalidDate'); return }
      const receipt = props.detail ? await calendarService.updateEvent(form.calendarId, props.detail.event_id, { ...data,
        expected_revision: props.detail.revision, scope: scope.value, ...(scope.value !== 'series' ? { recurrence_key: props.recurrenceKey } : {}),
        ...(scope.value !== 'occurrence' && props.detail.rrule && !form.rrule ? { clear_recurrence: true } : {}) })
        : await calendarService.createEvent(form.calendarId, { ...data, uid })
    if (alive) emit('saved', receipt)
  } catch (caught) {
    conflict.value = isAxiosError(caught) && caught.response?.status === 409
    error.value = conflict.value ? t('agenda.conflictError') : `${t('agenda.error')} ${apiErrorDetail(caught) ?? ''}`
  } finally { busy.value = false }
}
</script>
<style scoped>
.event-editor { width: 760px; max-width: 96vw; }
.event-fields { border: 0; padding: 0; margin: 0; min-width: 0; }
.date-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.error-banner { background: var(--solaire-red-light); }
.body--dark .error-banner { background: var(--solaire-red-dark); }
@media (max-width: 599px) { .date-fields { grid-template-columns: 1fr; } }
</style>
