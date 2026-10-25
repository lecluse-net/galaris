<template>
  <section :aria-label="t('task.costs.title')">
    <h3>{{ t('task.costs.title') }}</h3>
    <q-btn outline color="primary" icon="refresh" :label="t('common.refresh')" :loading="loading" @click="load" />
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="report">
      <p>{{ t('task.costs.taskHelp') }}</p>
      <p>{{ t('task.costs.quality.' + report.summary.quality) }}</p>
      <dl>
        <dt>{{ t('task.costs.recorded') }}</dt><dd>{{ format(report.summary.recorded_cost) }}</dd>
        <dt>{{ t('task.costs.total') }}</dt><dd>{{ format(report.summary.total_cost) }}</dd>
        <dt>{{ t('task.costs.inference') }}</dt><dd>{{ format(report.summary.inference_cost) }}</dd>
      </dl>
      <p>{{ t('task.costs.coverage', { ...report.summary }) }}</p>
      <p v-if="report.tasks_without_calls">{{ t('task.costs.missing', { count: report.tasks_without_calls }) }}</p>
      <p v-if="report.restricted">{{ t('task.costs.restricted') }}</p>
      <h4>{{ t('task.costs.byPurpose') }}</h4>
      <dl v-for="(summary, purpose) in report.by_purpose" :key="purpose">
        <dt>{{ te('llmCalls.purposes.' + purpose) ? t('llmCalls.purposes.' + purpose) : purpose }}</dt><dd>{{ format(summary.recorded_cost) }} USD · {{ t('task.costs.quality.' + summary.quality) }}</dd>
      </dl>
      <p class="text-caption">{{ t('task.costs.help') }}</p>
    </template>
  </section>
</template>
<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { taskService, type TaskCostReport } from '../services/taskService'
const props = defineProps<{ taskId: string }>()
const { t, te, locale } = useI18n()
const loading = ref(false)
const error = ref('')
const report = ref<TaskCostReport | null>(null)
let request = 0
onBeforeUnmount(() => { request++ })
async function load() {
  const current = ++request
  loading.value = true
  error.value = ''
  report.value = null
  try {
    const value = await taskService.getCosts(props.taskId)
    if (current === request) report.value = value
  } catch (cause) {
    if (current === request) error.value = apiErrorDetail(cause) ?? t('task.costs.error')
  } finally {
    if (current === request) loading.value = false
  }
}
function format(value: number | null) {
  return value == null ? '—' : value.toLocaleString(locale.value, { maximumFractionDigits: 10 })
}
watch(() => props.taskId, load, { immediate: true })
</script>
<style scoped>
h3, h4 { font-size: 1rem; font-weight: 600; }
dt { font-weight: 600; }
dd { margin: 0 0 12px; overflow-wrap: anywhere; }
</style>
