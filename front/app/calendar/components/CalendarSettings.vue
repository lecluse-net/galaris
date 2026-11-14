<template>
  <q-dialog :model-value="true" :maximized="$q.screen.lt.md" @update:model-value="!$event && emit('close')"><q-card class="galaris-dialog-card calendar-settings">
    <q-card-section class="galaris-dialog-title row items-center no-wrap">
      <div class="col row items-center q-gutter-sm"><span class="text-subtitle1">{{ title }}</span><q-badge v-if="sourceLabel" outline color="white" class="calendar-source-badge">{{ sourceLabel }}</q-badge></div>
      <q-btn flat round dense icon="close" :aria-label="t('agenda.close')" @click="emit('close')" />
    </q-card-section>
    <q-form class="galaris-dialog-form" @submit="save">
    <q-tabs v-model="panel" inline-label align="left" active-color="primary" indicator-color="primary" class="calendar-dialog-tabs text-primary" :style="{ background: $q.dark.isActive ? solaireCss.gray.dark : solaireCss.gray.light }">
      <q-tab name="settings" icon="edit" :label="t('agenda.tabs.settings')" :disable="busy" />
      <q-tab v-if="synchronizable" name="sync" icon="sync" :label="t('agenda.tabs.synchronization')" :disable="busy" />
    </q-tabs>
    <q-separator />
    <q-tab-panels v-model="panel" class="calendar-dialog-panels galaris-dialog-body">
    <q-tab-panel name="settings">
      <div class="column q-gutter-y-md">
      <CalendarColorSelect v-if="!feed && selected !== undefined && colors" v-model="color" />
      <template v-if="feed">
        <q-chip v-if="!feed.writable" dense class="self-start">{{ t('agenda.readOnly') }}</q-chip>
        <q-banner v-if="error" role="alert">{{ error }}</q-banner>
        <q-input v-model="label" outlined dense hide-bottom-space :label="t('calendars.label')" :readonly="!canEdit" :maxlength="200" :rules="[value => Boolean(value?.trim()) || t('agenda.required')]" />
          <CalendarColorSelect v-if="colors" v-model="color" :disable="busy" />
          <div class="column items-start">
          <q-toggle v-model="actionsEnabled" :disable="!canEdit || busy" :label="t('agenda.enableActions')" />
          <q-toggle v-if="!feed.is_default" v-model="active" :disable="!canEdit || busy" :label="t('calendars.enabled')" />
          </div>
        <q-btn v-if="canEdit && feed.source_kind === 'internal' && !feed.is_default" color="negative" icon="delete" class="self-start" :label="t('agenda.deleteCalendar')" @click="deleteDialog = true" />
      </template>
      </div>
    </q-tab-panel>
    <q-tab-panel v-if="synchronizable && feed" name="sync">
      <div class="column q-gutter-y-md">
        <CalendarSyncMonitor v-if="panel === 'sync'" ref="syncMonitor" :key="feed.id" :calendar-id="feed.id" :show-trigger="false" @changed="emit('changed'); load()">
          <template #entry="{ first }"><template v-if="first">
          <q-linear-progress v-if="loading" indeterminate color="primary" />
          <q-banner v-if="readError" role="alert">{{ readError }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="load" /></template></q-banner>
            <q-card v-for="conflict in conflicts" :key="conflict.event_id" flat bordered><q-card-section>
              <q-expansion-item :label="t('agenda.localVersion')" :caption="conflict.local_deleted ? t('agenda.localDeleted') : t('agenda.revision', { revision: conflict.revision })"><pre>{{ conflict.local_ical }}</pre></q-expansion-item>
              <q-expansion-item :label="t('agenda.remoteVersion')" :caption="conflict.remote_deleted ? t('agenda.remoteDeleted') : ''"><pre>{{ conflict.remote_ical }}</pre></q-expansion-item>
            </q-card-section><q-card-actions v-if="canEdit" align="right"><q-btn v-if="feed.writable" outline color="primary" :label="t('agenda.keepLocal')" @click="resolution = { conflict, choice: 'local' }" /><q-btn outline color="primary" :label="t('agenda.keepRemote')" @click="resolution = { conflict, choice: 'remote' }" /></q-card-actions></q-card>
          </template></template>
        </CalendarSyncMonitor>
      </div>
    </q-tab-panel>
    </q-tab-panels>
    <q-card-actions v-if="canSave || canSync || (canConfigureConnections && synchronizable)" class="galaris-dialog-actions" align="right">
      <q-btn v-if="canConfigureConnections && synchronizable && feed" outline color="primary" icon="settings_ethernet" :label="t('agenda.connectionSettings')" @click="connectionId = feed.connection_id" />
      <q-btn v-if="canSync" color="primary" icon="sync" :label="t('agenda.newSync')" :loading="syncMonitor?.requesting" :disable="!syncMonitor?.canStart" @click="syncMonitor?.start()" />
      <q-btn v-if="canSave" color="primary" type="submit" :label="t('agenda.save')" :loading="busy" />
    </q-card-actions>
    </q-form>
  </q-card></q-dialog>
  <ResourceDetailDialog v-if="connectionId !== null && canConfigureConnections" :target="{ kind: 'connection', id: String(connectionId), title: '' }" @close="connectionId = null" @changed="emit('changed'); load()" />
  <CalendarConfirmDialog v-if="deleteDialog && feed" :title="t('agenda.deleteCalendar')" :message="t('agenda.deleteCalendarConfirm', { title: calendarLabel(feed, t) })" :confirm="t('agenda.deleteCalendar')" negative :busy="deleting" :error="deleteError" @close="deleteDialog = false" @confirm="deleteCalendar" />
  <CalendarConfirmDialog v-if="resolution" :title="t('agenda.conflicts')" :message="t('agenda.resolveConfirm', { choice: t(resolution.choice === 'local' ? 'agenda.localVersion' : 'agenda.remoteVersion') })" :confirm="t(resolution.choice === 'local' ? 'agenda.keepLocal' : 'agenda.keepRemote')" :busy="resolving" :error="resolveError" @close="resolution = null; resolveError = ''" @confirm="resolve" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ResourceDetailDialog, solaireCss, type SolaireColor } from '@/core/util'
import { calendarService, type CalendarFeed, type CalendarConflict } from '../services/calendarService'
import { calendarLabel, calendarSourceLabel } from '../presentation'
import CalendarColorSelect from './CalendarColorSelect.vue'
import CalendarConfirmDialog from './CalendarConfirmDialog.vue'
import CalendarSyncMonitor from './CalendarSyncMonitor.vue'
const props = defineProps<{ feeds: CalendarFeed[]; initialId?: number; canEdit: boolean; colors?: Record<number, SolaireColor> }>()
const emit = defineEmits<{ close: []; changed: []; color: [id: number, color: SolaireColor] }>()
const { t } = useI18n(), $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canConfigureConnections = computed(() => privilegeStore.hasAnyPrivilege([privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT]))
const connectionId = ref<number | null>(null)
const selected = computed(() => props.initialId), feed = computed(() => props.feeds.find(row => row.id === selected.value))
const title = computed(() => feed.value ? calendarLabel(feed.value, t) : selected.value === 0 ? t('goal.agenda.layer') : selected.value === -1 ? t('agenda.memoryLayer') : t('agenda.calendar'))
const sourceLabel = computed(() => feed.value ? calendarSourceLabel(feed.value, t) : selected.value !== undefined ? t('agenda.sources.internal') : '')
const synchronizable = computed(() => Boolean(feed.value && feed.value.source_kind !== 'internal'))
const panel = ref('settings')
const syncMonitor = useTemplateRef<InstanceType<typeof CalendarSyncMonitor>>('syncMonitor')
const canSync = computed(() => props.canEdit && synchronizable.value && panel.value === 'sync')
const canSave = computed(() => selected.value !== undefined && panel.value === 'settings' && (props.canEdit || Boolean(props.colors)))
const active = ref(true)
const deleteDialog = ref(false), deleting = ref(false), deleteError = ref('')
const label = ref(''), actionsEnabled = ref(false), error = ref(''), busy = ref(false)
const color = ref<SolaireColor>('blue')
watch(selected, id => { color.value = id !== undefined ? props.colors?.[id] ?? 'blue' : 'blue' }, { immediate: true })
const conflicts = ref<CalendarConflict[]>([]), loading = ref(false), readError = ref('')
const resolution = ref<{ conflict: CalendarConflict; choice: 'local' | 'remote' } | null>(null), resolving = ref(false), resolveError = ref('')
let alive = true, generation = 0
watch(selected, () => { panel.value = 'settings'; label.value = feed.value ? calendarLabel(feed.value, t) : ''; actionsEnabled.value = feed.value?.actions_enabled ?? false; active.value = feed.value?.active ?? true; error.value = ''; conflicts.value = []; void load() }, { immediate: true })
watch(panel, () => { void load() })
async function load(): Promise<void> {
  const token = ++generation, id = selected.value
  if (id === undefined || !synchronizable.value || panel.value !== 'sync') { loading.value = false; return }
  loading.value = true; readError.value = ''
  try {
    const rows = await calendarService.conflicts(id)
    if (alive && token === generation) conflicts.value = rows
  } catch (caught) { if (alive && token === generation) readError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive && token === generation) loading.value = false }
}
async function save(): Promise<void> {
  const id = selected.value
  if (id === undefined || busy.value || !canSave.value) return
  busy.value = true; error.value = ''
  const chosenColor = color.value
  const savingPanel = panel.value
  try {
    if (feed.value && props.canEdit) {
      await calendarService.updateFeed(id, { ...(label.value.trim() !== calendarLabel(feed.value, t) ? { label: label.value.trim() } : {}), actions_enabled: actionsEnabled.value, ...(!feed.value.is_default ? { active: active.value } : {}) })
      if (alive) emit('changed')
    }
    if (alive) {
      if (props.colors && savingPanel === 'settings') emit('color', id, chosenColor)
      $q.notify({ type: 'positive', message: t('agenda.settingsSaved') })
    }
  }
  catch (caught) { if (alive && selected.value === id) error.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) busy.value = false }
}
async function resolve(): Promise<void> {
  const target = resolution.value, id = selected.value
  if (!id || !target || resolving.value || !props.canEdit) return
  resolving.value = true; resolveError.value = ''
  try { await calendarService.resolve(id, target.conflict.event_id, target.conflict.revision, target.choice); if (alive) { resolution.value = null; $q.notify({ type: 'positive', message: t('agenda.resolved') }); await load(); emit('changed') } }
  catch (caught) { if (alive) resolveError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) resolving.value = false }
}
async function deleteCalendar(): Promise<void> {
  const current = feed.value
  if (!current || deleting.value || current.is_default || current.source_kind !== 'internal' || !props.canEdit) return
  deleting.value = true; deleteError.value = ''
  try { await calendarService.deleteFeed(current.id); if (alive) { emit('changed'); emit('close') } }
  catch (caught) { if (alive) deleteError.value = apiErrorDetail(caught) ?? t('agenda.error') }
  finally { if (alive) deleting.value = false }
}
onBeforeUnmount(() => { alive = false; generation++ })
watch(() => props.canEdit, allowed => { if (!allowed) { deleteDialog.value = false; resolution.value = null } })
</script>
<style scoped>
.calendar-settings { width: 800px; max-width: 96vw; }
.calendar-dialog-tabs { flex: 0 0 auto; }
.calendar-dialog-panels { flex: 1 1 auto; min-height: 0; }
.calendar-source-badge { white-space: normal; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; padding: 12px; font-size: 12px; }
</style>
