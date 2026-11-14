<template>
  <div class="q-gutter-y-md">
    <p class="text-caption">{{ t('agenda.automaticTask') }} {{ t('agenda.taskHelp') }}</p>
    <q-banner v-if="!feed.actions_enabled">{{ t('agenda.actionsDisabled') }}</q-banner>
    <q-banner v-if="actionsError" role="alert">{{ actionsError }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="loadActions" /></template></q-banner>
    <q-linear-progress v-if="actionsLoading" indeterminate color="primary" />
    <q-list v-if="actions.length" bordered separator>
      <q-item v-for="action in actions" :key="action.id"><q-item-section><q-item-label class="action-instructions">{{ action.instructions }}</q-item-label>
        <q-item-label caption>{{ actionTiming(action) }} · {{ t(action.recurrence_key ? 'agenda.thisOccurrence' : 'agenda.allOccurrences') }} · {{ t(action.active ? 'calendars.enabled' : 'calendars.disabled') }}</q-item-label>
      </q-item-section><q-item-section v-if="canEdit" side><div class="row"><q-btn flat round color="primary" icon="edit" :aria-label="t('agenda.editAction')" @click="editAction(action)" />
        <q-btn flat round color="primary" :icon="action.active ? 'pause' : 'play_arrow'" :loading="toggling === action.id" :aria-label="t(action.active ? 'agenda.disableAction' : 'agenda.enableAction')" @click="toggle(action)" /></div></q-item-section></q-item>
    </q-list>
    <q-expansion-item v-if="detail.alarms.length" icon="alarm" :label="t('agenda.alarms')"><q-list><q-item v-for="alarm in detail.alarms" :key="alarm.key"><q-item-section>{{ t('agenda.alarmAt', { date: format(alarm.at) }) }}</q-item-section></q-item></q-list></q-expansion-item>
    <q-separator />
    <div class="row items-center q-gutter-sm"><div class="text-subtitle1 col">{{ t('agenda.history') }}</div><q-btn flat round color="primary" icon="refresh" :aria-label="t('agenda.refresh')" :loading="executionsLoading" @click="loadExecutions" /></div>
    <q-toggle v-if="detail.recurring" v-model="wholeSeries" :label="t('agenda.seriesHistory')" @update:model-value="resetExecutions" />
    <q-banner v-if="executionsError" role="alert">{{ executionsError }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="loadExecutions" /></template></q-banner>
    <q-table v-model:pagination="pagination" :rows="executions" :columns="columns" row-key="id" flat :loading="executionsLoading" :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('agenda.noExecutions')" @request="pageRequest">
      <template #body-cell-state="scope"><q-td :props="scope"><ExecutionBadge :state="scope.row.state" /><div v-if="scope.row.reason" class="text-caption">{{ scope.row.reason }}</div></q-td></template>
      <template #body-cell-actions="scope"><q-td :props="scope"><div class="row q-gutter-xs no-wrap">
        <q-btn v-if="scope.row.task_uri && canReadTasks" outline color="primary" size="sm" :label="t('agenda.openTask')" @click="openTask(scope.row.task_uri)" />
        <q-btn v-if="canRelaunch(scope.row)" flat round color="primary" icon="replay" :aria-label="t('agenda.relaunch')" @click="relaunchTarget = scope.row" />
      </div></q-td></template>
      <template #item="scope"><article class="col-12 q-mb-sm"><q-card flat bordered><q-card-section class="q-gutter-y-sm"><div>{{ format(scope.row.reminder_at) }}</div><ExecutionBadge :state="scope.row.state" /><p v-if="scope.row.reason">{{ scope.row.reason }}</p>
        <div class="row q-gutter-sm"><q-btn v-if="scope.row.task_uri && canReadTasks" outline color="primary" :label="t('agenda.openTask')" @click="openTask(scope.row.task_uri)" /><q-btn v-if="canRelaunch(scope.row)" outline color="primary" icon="replay" :label="t('agenda.relaunch')" @click="relaunchTarget = scope.row" /></div>
      </q-card-section></q-card></article></template>
    </q-table>
    <q-dialog v-model="actionDialog"><q-card class="galaris-dialog-card action-dialog"><q-card-section class="galaris-dialog-title row items-center no-wrap"><div class="text-subtitle1">{{ t(editingAction ? 'agenda.editAction' : 'agenda.addAction') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('agenda.close')" /></q-card-section>
      <q-form @submit="saveAction"><q-card-section class="galaris-dialog-body q-gutter-y-md">
        <q-banner v-if="saveError" role="alert">{{ saveError }}</q-banner>
        <q-input v-model="draft.instructions" outlined type="textarea" autogrow :label="t('agenda.instructions')" :maxlength="20000" :rules="[value => Boolean(value?.trim()) || t('agenda.required')]" />
        <CalendarActionTiming v-model:anchor="draft.anchor" v-model:offset="draft.offset_minutes" />
        <q-select v-if="detail.recurring" v-model="onlyOccurrence" outlined dense emit-value map-options :label="t('agenda.actionScope')" :options="[{ value: false, label: t('agenda.allOccurrences') }, { value: true, label: t('agenda.thisOccurrence'), disable: !recurrenceKey }]" />
        <q-input v-model.number="draft.max_lateness_minutes" type="number" outlined dense :min="0" :max="10080" :label="t('agenda.lateness')" :rules="[value => Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 10080 || t('agenda.required')]" />
        <q-checkbox v-model="draft.active" :label="t('agenda.active')" />
      </q-card-section><q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup outline color="primary" :label="t('agenda.cancel')" /><q-btn color="primary" type="submit" :label="t('agenda.saveAction')" :loading="saving" /></q-card-actions></q-form>
    </q-card></q-dialog>
    <CalendarConfirmDialog v-if="relaunchTarget" :title="t('agenda.relaunch')" :message="t('agenda.relaunchConfirm')" :hint="t('agenda.relaunchHint')" :confirm="t('agenda.relaunch')" :busy="relaunching" :error="relaunchError" @close="relaunchTarget = null; relaunchError = ''" @confirm="relaunch" />
    <ResourceDetailDialog v-if="selectedTask && canReadTasks" :target="selectedTask" @close="selectedTask = null" @changed="loadExecutions(); emit('changed')" />
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ResourceDetailDialog, type ResourceDetailTarget } from '@/core/util'
import { calendarService, type ActionWrite, type CalendarAction, type CalendarFeed, type CalendarReminder, type EventDetail } from '../services/calendarService'
import ExecutionBadge from './ExecutionBadge.vue'
import CalendarConfirmDialog from './CalendarConfirmDialog.vue'
import CalendarActionTiming from './CalendarActionTiming.vue'
const props = defineProps<{ feed: CalendarFeed; detail: EventDetail; recurrenceKey: string; canEdit: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t, locale } = useI18n(), $q = useQuasar(), privilegeStore = usePrivilegeStore()
const canReadTasks = computed(() => privilegeStore.hasAnyPrivilege([privileges.TASK_ACCESS, privileges.TASK_EDIT]))
const actions = ref<CalendarAction[]>([]), actionsLoading = ref(false), actionsError = ref(''), toggling = ref<string | null>(null)
const executions = ref<CalendarReminder[]>([]), executionsLoading = ref(false), executionsError = ref(''), wholeSeries = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let alive = true, request = 0, actionRequest = 0, timer: ReturnType<typeof setInterval> | undefined
const controller = new AbortController()
const format = (value: string) => new Intl.DateTimeFormat(locale.value, { timeZone: props.detail.timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
const columns = computed<QTableColumn[]>(() => [{ name: 'date', field: (row: CalendarReminder) => format(row.reminder_at), label: t('agenda.launchAt'), align: 'left' }, { name: 'state', field: 'state', label: t('calendars.state'), align: 'left' }, { name: 'actions', field: 'id', label: '', align: 'right' }])
const selectedTask = ref<ResourceDetailTarget | null>(null)
function openTask(uri: string): void { selectedTask.value = { kind: 'task', id: uri.slice('galaris://task/'.length), title: '' } }
function actionTiming(action: CalendarAction): string { return t(action.offset_minutes < 0 ? 'agenda.minutesBefore' : action.offset_minutes > 0 ? 'agenda.minutesAfter' : 'agenda.atAnchor', { minutes: Math.abs(action.offset_minutes), anchor: t(`agenda.anchors.${action.anchor}`) }) }
async function loadActions(): Promise<void> {
  const token = ++actionRequest; actionsLoading.value = true; actionsError.value = ''
  try { const rows = await calendarService.actions(props.feed.id, props.detail.event_id, controller.signal); if (alive && token === actionRequest) actions.value = rows }
  catch (caught) { if (alive && token === actionRequest) actionsError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive && token === actionRequest) actionsLoading.value = false }
}
async function loadExecutions(): Promise<void> {
  const token = ++request; executionsLoading.value = true; executionsError.value = ''
  try {
    const { page, rowsPerPage } = pagination.value
    const result = await calendarService.reminders(props.feed.connection_id, (page - 1) * rowsPerPage, rowsPerPage, { event_id: props.detail.event_id, ...(!wholeSeries.value ? { recurrence_key: props.recurrenceKey } : {}) }, controller.signal)
    if (!alive || token !== request) return
    executions.value = result.items; pagination.value.rowsNumber = result.total
    if (page > 1 && !result.items.length) { pagination.value.page = Math.max(1, Math.ceil(result.total / rowsPerPage)); void loadExecutions() }
  } catch (caught) { if (alive && token === request) executionsError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive && token === request) executionsLoading.value = false }
}
function resetExecutions(): void { pagination.value.page = 1; executions.value = []; void loadExecutions() }
function pageRequest(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void loadExecutions() }
const actionDialog = ref(false), editingAction = ref<CalendarAction | null>(null), saving = ref(false), saveError = ref('')
const onlyOccurrence = ref(false)
let actionKey = crypto.randomUUID()
const draft = reactive<ActionWrite>({ instructions: '', anchor: 'start', offset_minutes: -10, active: true, max_lateness_minutes: 60, recurrence_key: null })
function editAction(action?: CalendarAction): void {
  actionKey = crypto.randomUUID()
  editingAction.value = action ?? null; saveError.value = ''; onlyOccurrence.value = Boolean(action?.recurrence_key)
  Object.assign(draft, { instructions: action?.instructions ?? '', anchor: action?.anchor ?? 'start', offset_minutes: action?.offset_minutes ?? -10, active: action?.active ?? true, max_lateness_minutes: action?.max_lateness_minutes ?? 60 })
  actionDialog.value = true
}
async function saveAction(): Promise<void> {
  if (saving.value || !props.canEdit) return
  saving.value = true; saveError.value = ''
  try {
    await calendarService.saveAction(props.feed.id, props.detail.event_id, { ...draft,
      recurrence_key: onlyOccurrence.value ? props.recurrenceKey : null, ...(editingAction.value ? { expected_revision: editingAction.value.revision } : { request_key: actionKey }) }, editingAction.value?.id)
    if (!alive) return
    actionDialog.value = false; await loadActions(); await loadExecutions(); emit('changed')
  } catch (caught) { if (alive) saveError.value = `${t('agenda.error')} ${apiErrorDetail(caught) ?? ''}` }
  finally { if (alive) saving.value = false }
}
async function toggle(action: CalendarAction): Promise<void> {
  if (toggling.value || !props.canEdit) return
  toggling.value = action.id
  try {
    const { id, event_id: _event, revision, ...fields } = action
    await calendarService.saveAction(props.feed.id, props.detail.event_id, { ...fields, active: !action.active, expected_revision: revision }, id)
    if (!alive) return
    await loadActions(); await loadExecutions(); emit('changed')
  } catch (caught) { if (alive) actionsError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) toggling.value = null }
}
const relaunchTarget = ref<CalendarReminder | null>(null), relaunching = ref(false), relaunchError = ref(''), keys = new Map<string, string>()
function canRelaunch(row: CalendarReminder): boolean { return props.canEdit && props.feed.active && props.feed.actions_enabled && ['done', 'error', 'dispatch_error', 'cancelled', 'skipped'].includes(row.state) }
async function relaunch(): Promise<void> {
  const target = relaunchTarget.value
  if (!target || relaunching.value || !canRelaunch(target)) return
  const key = keys.get(target.id) ?? crypto.randomUUID(); keys.set(target.id, key)
  relaunching.value = true; relaunchError.value = ''
  try {
    await calendarService.relaunch(props.feed.id, target.id, props.detail.revision, key)
    if (!alive) return
    keys.delete(target.id); relaunchTarget.value = null; $q.notify({ type: 'positive', message: t('agenda.relaunchQueued') }); await loadExecutions(); emit('changed')
  } catch (caught) { if (alive) relaunchError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) relaunching.value = false }
}
onMounted(() => { void loadActions(); void loadExecutions(); timer = setInterval(() => { if (!document.hidden && !executionsLoading.value) void loadExecutions() }, 15_000) })
watch(() => props.canEdit, allowed => { if (!allowed) { actionDialog.value = false; relaunchTarget.value = null } })
onBeforeUnmount(() => { alive = false; controller.abort(); clearInterval(timer) })
</script>
<style scoped>
.action-instructions { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 130px; overflow-y: auto; }
.action-dialog { width: 640px; max-width: 96vw; }
</style>
