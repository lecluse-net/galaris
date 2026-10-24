<template>
  <q-page class="q-pa-md">
    <PageHeader :icon="navigationIcon('calendar_month')" :title="t('calendars.title')" :description="t('calendars.description')" />
    <q-banner v-if="failed" role="alert" class="q-mb-md">
      {{ t('calendars.actionError') }}
      <template #action><q-btn outline :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <q-select v-model="selected" :options="options" option-value="id" option-label="label" emit-value map-options outlined
      :loading="loading" :label="t('calendars.connection')" class="q-mb-md" />
    <CalendarConnectionEditor v-if="connection" :key="connection.id" :connection-id="connection.id" :agent-id="connection.agent_id" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import CalendarConnectionEditor from '../components/CalendarConnectionEditor.vue'
import { calendarService } from '../services/calendarService'

const { t } = useI18n()
const options = ref<Awaited<ReturnType<typeof calendarService.connections>>>([])
const selected = ref<number | null>(null)
const loading = ref(false)
const failed = ref(false)
const connection = computed(() => options.value.find(item => item.id === selected.value))
async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    options.value = await calendarService.connections()
    if (!connection.value) selected.value = options.value[0]?.id ?? null
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
