<template>
  <section class="sync-history column q-gutter-y-md">
    <div v-if="showTrigger" class="row"><q-btn color="primary" icon="add" :label="t('agenda.newSync')" :loading="requesting" :disable="active || pending" @click="start" /></div>
    <q-banner v-if="requestError || error" role="alert">{{ requestError || error }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="requestError ? start() : poll()" /></template></q-banner>
    <q-linear-progress v-if="loading && !runs.length" indeterminate color="primary" />
    <q-list v-if="runs.length || pending" separator>
      <q-expansion-item v-if="pending && !runs.some(row => row.id === requestedId)" :key="requestedId ?? 'pending'" default-opened icon="sync" :label="t('agenda.monitor.states.queued')">
        <div class="q-pa-md" role="status">{{ t('agenda.monitor.stages.queued') }}<q-linear-progress indeterminate color="primary" /></div>
      </q-expansion-item>
      <q-expansion-item v-for="(row, index) in runs" :key="row.id" :model-value="Boolean(expanded[row.id])"
        :label="t(`agenda.monitor.states.${row.state}`)" :caption="format(row.started_at)"
        :icon="['queued', 'running'].includes(row.state) ? 'sync' : row.state === 'success' ? 'check_circle' : 'error_outline'"
        @update:model-value="expanded = { ...expanded, [row.id]: $event }">
        <div class="q-pa-md"><CalendarSyncDetails :run="row" :now="now" /><slot name="entry" :run="row" :first="index === 0" /></div>
      </q-expansion-item>
    </q-list>
    <div v-else-if="!loading && !pending" class="text-caption">{{ t('agenda.noHistory') }}</div>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { calendarService, type SyncRun } from '../services/calendarService'
import CalendarSyncDetails from './CalendarSyncDetails.vue'
const { calendarId, initialRunId = null, showTrigger = true, autoStart = false } = defineProps<{ calendarId: number; initialRunId?: string | null; showTrigger?: boolean; autoStart?: boolean }>()
const emit = defineEmits<{ settled: [run: SyncRun]; changed: [run: SyncRun] }>()
const { t, locale } = useI18n()
const recentRunLimit = 50
const runs = ref<SyncRun[]>([]), expanded = ref<Record<string, boolean>>({})
const requestedId = ref<string | null>(initialRunId), requesting = ref(false), loading = ref(false), error = ref(''), requestError = ref(''), now = ref(Date.now())
const active = computed(() => runs.value.some(row => ['queued', 'running'].includes(row.state)))
const pending = ref(Boolean(initialRunId))
const canStart = computed(() => !requesting.value && !active.value && !pending.value)
defineExpose({ start, requesting, canStart })
let generation = 0, alive = true, initialized = false
let timer: ReturnType<typeof setTimeout> | undefined, controller = new AbortController()
const observedActive = new Set<string>()
const format = (value: string) => new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(value))
async function poll(): Promise<void> {
  if (!alive || loading.value) return
  clearTimeout(timer)
  const version = generation, requested = requestedId.value
  loading.value = true
  try {
    let rows = await calendarService.syncRuns(calendarId, 0, controller.signal, undefined, recentRunLimit)
    if (requested && !rows.some(row => row.id === requested)) {
      const selected = await calendarService.syncRuns(calendarId, 0, controller.signal, requested, 1)
      rows = [...selected, ...rows].slice(0, recentRunLimit)
    }
    if (!alive || version !== generation) return
    if (!initialized && rows[0]) {
      expanded.value = { [requested ?? rows[0].id]: true }; initialized = true
    }
    runs.value = rows
    error.value = ''; now.value = Date.now()
    for (const row of rows) {
      if (['queued', 'running'].includes(row.state)) observedActive.add(row.id)
      else if (observedActive.delete(row.id) || (pending.value && requested === row.id)) {
        if (requested === row.id) { pending.value = false; requestedId.value = null }
        emit('settled', row)
        if (row.progress?.calendar_changed) emit('changed', row)
      }
    }
  } catch (caught) {
    if (alive && version === generation && !isCancelledRequest(caught)) error.value = apiErrorDetail(caught) || t('agenda.error')
  } finally {
    if (alive && version === generation) {
      loading.value = false
      timer = setTimeout(() => { void poll() }, active.value || pending.value ? 1000 : 5000)
    }
  }
}
async function start(): Promise<void> {
  if (requesting.value || active.value || pending.value) return
  let version = generation
  requesting.value = true; requestError.value = ''
  try {
    const result = await calendarService.test(calendarId)
    if (!alive || version !== generation) return
    resetRead(); version = generation
    requesting.value = false
    requestedId.value = result.sync_run_id ?? null
    pending.value = Boolean(requestedId.value)
    if (requestedId.value) expanded.value = { [requestedId.value]: true }
    await poll()
  } catch (caught) {
    if (alive && version === generation) requestError.value = apiErrorDetail(caught) || t('agenda.error')
  } finally { if (alive && version === generation) requesting.value = false }
}
function resetRead(): void {
  generation++; controller.abort(); controller = new AbortController(); clearTimeout(timer)
  loading.value = false
}
watch(() => [calendarId, initialRunId] as const, () => {
  resetRead(); requesting.value = false; runs.value = []; expanded.value = {}; initialized = false; observedActive.clear()
  error.value = ''; requestError.value = ''; requestedId.value = initialRunId; pending.value = Boolean(initialRunId)
  if (!autoStart) void poll()
}, { immediate: true })
onBeforeUnmount(() => { alive = false; resetRead() })
onMounted(() => { if (autoStart) void start() })
</script>
