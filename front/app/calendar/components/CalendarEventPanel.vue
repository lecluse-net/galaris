<template>
  <q-dialog :model-value="true" :position="$q.screen.lt.md ? 'standard' : 'right'" :maximized="$q.screen.lt.md" @update:model-value="!$event && emit('close')">
    <q-card class="event-panel">
      <q-card-section class="galaris-dialog-title row items-center no-wrap"><div class="text-subtitle1 ellipsis">{{ detail?.summary || event.summary }}</div><q-space /><q-btn flat round dense icon="close" :aria-label="t('agenda.close')" @click="emit('close')" /></q-card-section>
      <q-linear-progress v-if="loading" indeterminate color="primary" />
      <q-banner v-if="error" role="alert">{{ error }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="load" /></template></q-banner>
      <template v-if="detail">
        <q-card-section class="q-gutter-y-sm"><div class="row items-center q-gutter-sm"><q-icon name="event" color="primary" /><span>{{ period }}</span></div>
          <div class="row items-center q-gutter-sm"><q-icon name="calendar_month" color="primary" /><span>{{ calendarLabel(feed, t) }}</span><q-chip dense>{{ t(`agenda.sync.${detail.sync_state}`) }}</q-chip></div>
          <div class="text-caption">{{ detail.timezone }}</div>
          <div v-if="detail.recurring" class="row items-center q-gutter-sm"><q-icon name="repeat" /><span>{{ t('agenda.repeated') }}</span></div>
          <div v-if="detail.location" class="row items-center q-gutter-sm"><q-icon name="location_on" /><span>{{ detail.location }}</span></div>
          <q-btn v-if="detail.contact_id" outline color="primary" icon="person" :label="t('agenda.linkedContact')" @click="contactOpen = true" />
          <div v-if="detail.description" class="event-description">{{ detail.description }}</div>
          <q-expansion-item v-if="detail.recurring" icon="repeat" :label="t('agenda.recurrence')">
            <div class="q-pa-sm"><code v-if="detail.rrule">{{ detail.rrule }}</code><div v-if="detail.rdates.length"><strong>{{ t('agenda.recurrenceDates') }}</strong><div v-for="date in detail.rdates" :key="date">{{ date.length === 10 ? date : format(date) }}</div></div><div v-if="detail.exdates.length"><strong>{{ t('agenda.excludedDates') }}</strong><div v-for="date in detail.exdates" :key="date">{{ date.length === 10 ? date : format(date) }}</div></div></div>
          </q-expansion-item>
          <q-banner v-if="!feed.writable">{{ t('agenda.readOnly') }}</q-banner>
          <q-banner v-if="detail.sync_state === 'conflict'">{{ t('agenda.sync.conflict') }}<template #action><q-btn outline color="primary" :label="t('agenda.settings')" @click="emit('settings')" /></template></q-banner>
          <q-banner v-if="nativeSeries" role="note">{{ t('agenda.nativeSeriesHint') }}</q-banner>
          <div v-if="writable" class="row q-gutter-sm"><q-btn v-if="!nativeSeries" outline color="primary" icon="edit" :label="t('agenda.edit')" :loading="preparingEdit" @click="edit" /><q-btn color="negative" icon="delete" :label="t('agenda.delete')" @click="deleteDialog = true" /></div>
          <q-btn outline color="primary" icon="file_download" :label="t('agenda.downloadIcal')" @click="download" />
        </q-card-section>
        <q-tabs v-model="tab" dense align="left" active-color="primary"><q-tab name="tasks" :label="t('agenda.tasks')" /><q-tab name="history" :label="t('agenda.eventHistory')" /></q-tabs><q-separator />
        <q-card-section v-if="tab === 'tasks'"><CalendarEventTasks :key="`${detail.event_id}:${detail.revision}`" :feed="feed" :detail="detail" :recurrence-key="event.recurrence_key" :can-edit="canEdit && feed.active && !detail.deleted" @changed="emit('changed')" /></q-card-section>
        <q-card-section v-else class="q-gutter-y-sm"><q-linear-progress v-if="historyLoading" indeterminate color="primary" /><q-banner v-if="historyError" role="alert">{{ historyError }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="loadHistory" /></template></q-banner>
          <q-expansion-item v-for="row in history" :key="row.revision" :label="t('agenda.revision', { revision: row.revision })" :caption="format(row.created_at)"><pre class="ical">{{ row.ical }}</pre></q-expansion-item>
          <p v-if="!history.length && !historyLoading">{{ t('agenda.noHistory') }}</p>
          <div class="row q-gutter-sm"><q-btn outline color="primary" :label="t('agenda.newer')" :disable="historyPage === 0 || historyLoading" @click="historyPage--; loadHistory()" /><q-btn outline color="primary" :label="t('agenda.older')" :disable="history.length < 50 || historyLoading" @click="historyPage++; loadHistory()" /></div>
        </q-card-section>
      </template>
    </q-card>
    <CalendarConfirmDialog v-if="deleteDialog && detail" :title="t('agenda.delete')" :message="t('agenda.deleteConfirm', { title: detail.summary })" :hint="t('agenda.deleteHint')" :confirm="t('agenda.delete')" negative :busy="deleting" :error="deleteError" @close="deleteDialog = false" @confirm="remove">
      <q-select v-if="detail.recurring" v-model="deleteScope" outlined emit-value map-options :options="scopeOptions" :label="t('agenda.scope')" />
    </CalendarConfirmDialog>
    <ContactResourceDialog v-if="contactOpen && detail?.contact_id" :contact-id="detail.contact_id" @close="contactOpen = false" />
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { ContactResourceDialog } from '@/app/memory'
import { addDays } from '../calendarDates'
import { calendarLabel } from '../presentation'
import { calendarService, type CalendarEvent, type CalendarFeed, type EventDetail, type EventHistory, type EventScope } from '../services/calendarService'
import CalendarEventTasks from './CalendarEventTasks.vue'
import CalendarConfirmDialog from './CalendarConfirmDialog.vue'
const props = defineProps<{ event: CalendarEvent; feed: CalendarFeed; canEdit: boolean }>()
const emit = defineEmits<{ close: []; changed: []; edit: [detail: EventDetail, master: EventDetail]; settings: [] }>()
const { t, locale } = useI18n(), $q = useQuasar()
const detail = ref<EventDetail | null>(null), loading = ref(false), error = ref(''), preparingEdit = ref(false), tab = ref('tasks')
const contactOpen = ref(false)
const history = ref<EventHistory[]>([]), historyLoading = ref(false), historyError = ref(''), historyPage = ref(0)
const controller = new AbortController(); let alive = true, generation = 0, historyGeneration = 0
const writable = computed(() => props.canEdit && props.feed.writable && props.feed.active && detail.value && !detail.value.deleted && detail.value.sync_state !== 'conflict')
const nativeSeries = computed(() => ['google', 'microsoft'].includes(props.feed.source_kind) && props.event.recurring)
const format = (value: string) => new Intl.DateTimeFormat(locale.value, { timeZone: detail.value?.timezone ?? props.feed.timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
const period = computed(() => {
  if (!detail.value) return ''
  const row = detail.value
  if (!row.all_day) return `${format(row.start)} – ${format(row.end)}`
  const date = (value: string) => new Intl.DateTimeFormat(locale.value, { timeZone: 'UTC', dateStyle: 'medium' }).format(new Date(`${value}T12:00:00Z`))
  return `${date(row.start_date ?? row.start.slice(0, 10))} – ${date(addDays(row.end_date ?? row.end.slice(0, 10), -1))} · ${t('agenda.allDay')}`
})
async function load(): Promise<void> {
  const token = ++generation; loading.value = true; error.value = ''
  try { const row = await calendarService.detail(props.feed.id, props.event.event_id, props.event.recurrence_key || undefined, controller.signal); if (alive && token === generation) detail.value = row }
  catch (caught) { if (alive && token === generation) error.value = apiErrorDetail(caught) ?? t('agenda.loadError') }
  finally { if (alive && token === generation) loading.value = false }
}
function download(): void {
  if (!detail.value) return
  const url = URL.createObjectURL(new Blob([detail.value.ical], { type: 'text/calendar;charset=utf-8' })), link = document.createElement('a')
  link.href = url; link.download = `${detail.value.summary.replace(/[^\p{L}\p{N} _-]/gu, '').slice(0, 80) || 'event'}.ics`; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function edit(): Promise<void> {
  if (!detail.value || preparingEdit.value) return
  preparingEdit.value = true
  try { const master = detail.value.recurring ? await calendarService.detail(props.feed.id, props.event.event_id, undefined, controller.signal) : detail.value; if (alive) emit('edit', detail.value, master) }
  catch (caught) { if (alive) error.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) preparingEdit.value = false }
}
async function loadHistory(): Promise<void> {
  const token = ++historyGeneration; historyLoading.value = true; historyError.value = ''
  try { const rows = await calendarService.history(props.feed.id, props.event.event_id, historyPage.value * 50); if (alive && token === historyGeneration) history.value = rows }
  catch (caught) { if (alive && token === historyGeneration) historyError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive && token === historyGeneration) historyLoading.value = false }
}
watch(tab, value => { if (value === 'history') void loadHistory() })
const deleteDialog = ref(false), deleting = ref(false), deleteError = ref(''), deleteScope = ref<EventScope>(props.event.recurring && !nativeSeries.value ? 'occurrence' : 'series')
const scopeOptions = computed(() => (nativeSeries.value ? ['series'] : ['occurrence', 'following', 'series']).map(value => ({ value, label: t(`agenda.scopes.${value}`) })))
async function remove(): Promise<void> {
  if (!detail.value || deleting.value || !writable.value) return
  deleting.value = true; deleteError.value = ''
  try {
    await calendarService.deleteEvent(props.feed.id, detail.value.event_id, { expected_revision: detail.value.revision, scope: deleteScope.value, ...(deleteScope.value !== 'series' ? { recurrence_key: props.event.recurrence_key } : {}) })
    if (!alive) return
    $q.notify({ type: 'positive', message: t('agenda.deleted') }); emit('changed'); emit('close')
  } catch (caught) { if (alive) deleteError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) deleting.value = false }
}
onMounted(load)
onBeforeUnmount(() => { alive = false; controller.abort(); generation++; historyGeneration++ })
</script>
<style scoped>
.event-panel { width: 560px; max-width: 100vw; height: 100%; overflow-y: auto; }
.event-description { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; padding: 10px 0; }
.ical { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow-y: auto; font-size: 12px; padding: 12px; }
</style>
