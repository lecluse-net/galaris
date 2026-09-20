<template>
  <q-card flat bordered>
    <q-card-section class="row items-center">
      <div>
        <div class="text-subtitle2">{{ t('calendars.connectionTitle') }}</div>
        <div class="text-caption text-grey-7">{{ t('calendars.connectionHint') }}</div>
      </div>
      <q-space />
      <q-btn v-if="canEdit" outline color="primary" icon="add" :label="t('calendars.add')" @click="openCreate" />
    </q-card-section>

    <q-separator />
    <q-table
      :rows="feeds"
      :columns="columns"
      row-key="id"
      dense
      flat
      :loading="loading"
      :no-data-label="t('calendars.empty')"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
    >
      <template #body-cell-access_mode="props">
        <q-td :props="props">
          <q-chip dense :icon="props.row.access_mode === 'write' ? 'edit_calendar' : 'event_note'">
            {{ t(`calendars.${props.row.access_mode}`) }}
          </q-chip>
        </q-td>
      </template>
      <template #body-cell-active="props">
        <q-td :props="props">
          <q-badge :color="props.row.active ? 'positive' : 'grey'">
            {{ t(props.row.active ? 'calendars.enabled' : 'calendars.disabled') }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn flat round dense icon="event_available" :loading="testingId === props.row.id" :aria-label="t('calendars.testAction')" @click="testFeed(props.row)">
            <q-tooltip>{{ t('calendars.testAction') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit" flat round dense icon="edit" :aria-label="t('calendars.editAction')" @click="openEdit(props.row)" />
          <q-btn v-if="canEdit" flat round dense color="negative" icon="delete" :aria-label="t('calendars.deleteAction')" @click="confirmDelete(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="formDialog" @hide="resetForm">
      <q-card class="calendar-feed-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="calendar_month" size="sm" />
          <div class="text-subtitle1 text-weight-medium q-ml-sm">
            {{ editingId === null ? t('calendars.add') : t('calendars.edit') }}
          </div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section class="calendar-feed-form q-gutter-y-md">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-sm-6">
              <q-input v-model="form.label" outlined :label="t('calendars.label')" />
            </div>
            <div class="col-12 col-sm-6">
              <q-input v-model="form.owner_label" outlined :label="t('calendars.owner')" :hint="t('calendars.ownerHint')" />
            </div>
          </div>
          <q-select v-model="form.access_mode" :options="accessOptions" emit-value map-options outlined :label="t('calendars.access')" />
          <q-banner v-if="form.access_mode === 'write'" dense rounded class="bg-blue-1 text-blue-9">
            {{ t('calendars.writeHint') }}
          </q-banner>
          <q-input
            v-model="form.url"
            outlined
            type="password"
            autocomplete="off"
            :label="t('calendars.url')"
            :hint="editingId === null ? undefined : t('calendars.urlEditHint')"
          />
          <div class="row q-col-gutter-md">
            <div class="col-12 col-sm-6">
              <q-input v-model="form.username" outlined autocomplete="off" :label="t('calendars.username')" :hint="editingId === null ? undefined : t('calendars.credentialEditHint')" />
            </div>
            <div class="col-12 col-sm-6">
              <q-input v-model="form.password" outlined type="password" autocomplete="new-password" :label="t('calendars.password')" :hint="editingId === null ? undefined : t('calendars.credentialEditHint')" />
            </div>
          </div>
          <q-toggle v-model="form.active" :label="t('calendars.active')" />
          <div>
            <div class="text-subtitle2 q-mb-xs">{{ t('calendars.triggers') }}</div>
            <q-checkbox v-model="form.trigger_on_start" :label="t('calendars.triggerStart')" />
            <q-checkbox v-model="form.trigger_on_alarm" :label="t('calendars.triggerAlarm')" />
          </div>
          <q-select v-model="form.action_kind" :options="actionOptions" emit-value map-options outlined :label="t('calendars.action')" />
          <q-select
            v-if="form.action_kind === 'process'"
            v-model="form.process_workflow_id"
            :options="processOptions"
            emit-value
            map-options
            outlined
            :label="t('calendars.processTarget')"
          />
          <q-input
            v-else
            v-model="form.action_instructions"
            type="textarea"
            autogrow
            outlined
            :label="t('calendars.instructions')"
            :hint="t('calendars.instructionsHint')"
          />
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="primary" :loading="saving" :label="t('common.save')" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="testDialog">
      <q-card class="calendar-test-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="event_available" size="sm" />
          <div class="text-subtitle1 text-weight-medium q-ml-sm">{{ t('calendars.testTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section v-if="testResult" class="q-gutter-md">
          <q-banner dense rounded class="bg-green-1 text-positive">
            {{ t('calendars.testSuccess', { count: testResult.events_seen }) }}
          </q-banner>
          <div v-if="testedFeed?.access_mode === 'write' && testResult.writable_advertised !== null" class="text-body2">
            {{ t(testResult.writable_advertised ? 'calendars.testWriteYes' : 'calendars.testWriteNo') }}
          </div>
          <div class="text-subtitle2">{{ t('calendars.nextEvents') }}</div>
          <q-list v-if="testResult.next_events.length" bordered separator rounded>
            <q-item v-for="event in testResult.next_events" :key="`${event.uid}:${event.start}`">
              <q-item-section avatar><q-icon name="event" color="primary" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ event.summary || t('calendars.untitledEvent') }}</q-item-label>
                <q-item-label caption>{{ formatEventStart(event.start, event.all_day) }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-else class="text-grey-7">{{ t('calendars.noUpcomingEvents') }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup flat color="primary" :label="t('common.close')" /></q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteDialog">
      <q-card class="calendar-delete-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-subtitle1 text-weight-medium">{{ t('calendars.deleteTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('calendars.deleteMessage') }}</q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="negative" :loading="deleting" :label="t('common.delete')" @click="remove" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import {
  calendarService,
  type CalendarAccess,
  type CalendarAction,
  type CalendarConnectionStatus,
  type CalendarFeed,
  type CalendarFeedCreate,
  type CalendarFeedUpdate,
  type CalendarProcessOption,
} from '../services/calendarService'

interface CalendarForm {
  label: string
  owner_label: string
  access_mode: CalendarAccess
  url: string
  username: string
  password: string
  active: boolean
  trigger_on_start: boolean
  trigger_on_alarm: boolean
  action_kind: CalendarAction
  process_workflow_id: string | null
  action_instructions: string
}

const props = defineProps<{ connectionId: number; agentId: number }>()
const $q = useQuasar()
const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))
const feeds = ref<CalendarFeed[]>([])
const processes = ref<CalendarProcessOption[]>([])
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const testingId = ref<number | null>(null)
const editingId = ref<number | null>(null)
const deletingFeed = ref<CalendarFeed | null>(null)
const testedFeed = ref<CalendarFeed | null>(null)
const testResult = ref<CalendarConnectionStatus | null>(null)
const formDialog = ref(false)
const testDialog = ref(false)
const deleteDialog = ref(false)
const form = reactive<CalendarForm>(emptyForm())

const columns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('calendars.label'), field: 'label', align: 'left', sortable: true },
  { name: 'owner_label', label: t('calendars.owner'), field: (row: CalendarFeed) => row.owner_label || '—', align: 'left' },
  { name: 'origin', label: t('calendars.origin'), field: 'origin', align: 'left' },
  { name: 'access_mode', label: t('calendars.access'), field: 'access_mode', align: 'left' },
  { name: 'active', label: t('calendars.state'), field: 'active', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])
const accessOptions = computed(() => [
  { label: t('calendars.read'), value: 'read' },
  { label: t('calendars.write'), value: 'write' },
])
const actionOptions = computed(() => [
  { label: t('calendars.task'), value: 'task' },
  { label: t('calendars.process'), value: 'process' },
])
const processOptions = computed(() => processes.value
  .filter(process => process.agent_id === props.agentId)
  .map(process => ({ label: process.label, value: process.engine_process_id })))

function emptyForm(): CalendarForm {
  return { label: '', owner_label: '', access_mode: 'read', url: '', username: '', password: '', active: true, trigger_on_start: true, trigger_on_alarm: true, action_kind: 'task', process_workflow_id: null, action_instructions: '' }
}
function resetForm(): void { Object.assign(form, emptyForm()); editingId.value = null }
function formatEventStart(value: string, allDay: boolean): string {
  return new Intl.DateTimeFormat(locale.value, allDay
    ? { dateStyle: 'full', timeZone: 'UTC' }
    : { dateStyle: 'full', timeStyle: 'short' }).format(new Date(value))
}
function notifyError(error: unknown): void {
  $q.notify({ type: 'negative', message: apiErrorDetail(error) || t('calendars.actionError') })
}

async function load(): Promise<void> {
  loading.value = true
  try {
    feeds.value = await calendarService.list(props.connectionId)
    processes.value = await calendarService.processes().catch(() => [])
  } catch (error) {
    notifyError(error)
  } finally {
    loading.value = false
  }
}
function openCreate(): void { resetForm(); formDialog.value = true }
function openEdit(feed: CalendarFeed): void {
  editingId.value = feed.id
  Object.assign(form, {
    label: feed.label, owner_label: feed.owner_label ?? '', access_mode: feed.access_mode,
    url: '', username: '', password: '', active: feed.active,
    trigger_on_start: feed.trigger_on_start, trigger_on_alarm: feed.trigger_on_alarm,
    action_kind: feed.action_kind, process_workflow_id: feed.process_workflow_id,
    action_instructions: feed.action_instructions ?? '',
  })
  formDialog.value = true
}
async function save(): Promise<void> {
  if (!form.label.trim() || (editingId.value === null && !form.url.trim())) {
    $q.notify({ type: 'warning', message: t('calendars.required') })
    return
  }
  if (form.action_kind === 'process' && !form.process_workflow_id) {
    $q.notify({ type: 'warning', message: t('calendars.processRequired') })
    return
  }
  saving.value = true
  try {
    const common = {
      label: form.label.trim(), owner_label: form.owner_label.trim() || null,
      access_mode: form.access_mode, active: form.active,
      trigger_on_start: form.trigger_on_start, trigger_on_alarm: form.trigger_on_alarm,
      action_kind: form.action_kind,
      process_workflow_id: form.action_kind === 'process' ? form.process_workflow_id : null,
      action_instructions: form.action_kind === 'task' ? form.action_instructions.trim() || null : null,
    }
    if (editingId.value === null) {
      const payload: CalendarFeedCreate = {
        ...common, connection_id: props.connectionId, url: form.url.trim(),
        username: form.username.trim() || null, password: form.password || null,
      }
      await calendarService.create(payload)
    } else {
      const payload: CalendarFeedUpdate = { ...common }
      if (form.url.trim()) payload.url = form.url.trim()
      if (form.username.trim()) payload.username = form.username.trim()
      if (form.password) payload.password = form.password
      await calendarService.update(editingId.value, payload)
    }
    formDialog.value = false
    $q.notify({ type: 'positive', message: t('calendars.saved') })
    await load()
  } catch (error) {
    notifyError(error)
  } finally {
    saving.value = false
  }
}
async function testFeed(feed: CalendarFeed): Promise<void> {
  testingId.value = feed.id
  try {
    testResult.value = await calendarService.test(feed.id)
    testedFeed.value = feed
    testDialog.value = true
  } catch (error) {
    notifyError(error)
  } finally {
    testingId.value = null
  }
}
function confirmDelete(feed: CalendarFeed): void { deletingFeed.value = feed; deleteDialog.value = true }
async function remove(): Promise<void> {
  if (!deletingFeed.value) return
  deleting.value = true
  try {
    await calendarService.remove(deletingFeed.value.id)
    deleteDialog.value = false
    deletingFeed.value = null
    await load()
  } catch (error) {
    notifyError(error)
  } finally {
    deleting.value = false
  }
}

watch(() => props.connectionId, load, { immediate: true })
</script>

<style scoped>
.calendar-feed-dialog { width: min(760px, 94vw); max-width: 94vw; }
.calendar-feed-form { padding: 24px; }
.calendar-test-dialog { width: min(620px, 94vw); max-width: 94vw; }
.calendar-delete-dialog { width: min(480px, 94vw); max-width: 94vw; }
</style>
