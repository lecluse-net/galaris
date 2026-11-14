<template>
  <q-dialog :model-value="true" @update:model-value="!$event && emit('close')">
    <q-card class="galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="calendar_month" class="q-mr-sm" /><div class="text-h6">{{ feed ? calendarLabel(feed, t) : t('agenda.calendar') }}</div><q-space />
        <CopyResourceReference :uri="`galaris://calendar/${calendarId}`" /><q-btn flat round dense icon="close" :aria-label="t('agenda.close')" @click="emit('close')" />
      </q-card-section>
      <q-card-section v-if="loading" role="status"><q-spinner color="primary" /> {{ t('agenda.loading') }}</q-card-section>
      <q-banner v-else-if="error" role="alert" class="q-ma-md">{{ error }}<template #action><q-btn outline color="primary" :label="t('agenda.retry')" @click="load" /></template></q-banner>
      <template v-else-if="feed">
        <q-card-section>{{ t('agenda.timezone') }} : {{ feed.timezone }}<div v-if="!feed.writable" class="text-caption">{{ t('agenda.readOnly') }}</div></q-card-section>
        <q-card-actions align="right"><q-btn color="primary" icon="open_in_new" :label="t('agenda.openCalendar')" :to="{ path: '/calendar', query: { calendar_id: feed.id, agent_id: feed.agent_id } }" @click="emit('close')" /></q-card-actions>
      </template>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { CopyResourceReference } from '@/core/util'
import { calendarService, type CalendarFeed } from '../services/calendarService'
import { calendarLabel } from '../presentation'
const { calendarId } = defineProps<{ calendarId: number }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n(), feed = ref<CalendarFeed | null>(null), error = ref(''), loading = ref(false)
let controller = new AbortController(), generation = 0
async function load(): Promise<void> {
  controller.abort(); controller = new AbortController()
  const token = ++generation
  loading.value = true; error.value = ''; feed.value = null
  try { const result = await calendarService.get(calendarId, controller.signal); if (token === generation) feed.value = result }
  catch (caught) { if (token === generation && !isCancelledRequest(caught)) error.value = apiErrorDetail(caught) ?? t('agenda.loadError') }
  finally { if (token === generation) loading.value = false }
}
watch(() => calendarId, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++; controller.abort() })
</script>
