<template>
  <section :aria-label="t('task.budget.title')">
      <q-btn flat icon="refresh" :label="t('common.refresh')" :loading="loading" @click="load" />
      <p v-if="error" role="alert">{{ error }}</p>
      <template v-if="budget">
        <p>{{ t(budget.enabled ? 'task.budget.enabled' : 'task.budget.unlimited') }}</p>
        <p>{{ t(`task.budget.${budget.scope}`) }}</p>
        <dl>
          <dt>{{ t('task.budget.recorded') }}</dt>
          <dd>{{ t('task.budget.usage', { tokens: budget.recorded_tokens, cost: budget.recorded_cost.toFixed(4) }) }}</dd>
          <dt>{{ t('task.budget.reserved', { phases: budget.active_phases }) }}</dt>
          <dd>{{ t('task.budget.usage', { tokens: budget.reserved_tokens, cost: budget.reserved_cost.toFixed(4) }) }}</dd>
          <dt>{{ t('task.budget.remaining') }}</dt>
          <dd>{{ t('task.budget.capacity', {
            tokens: budget.remaining_tokens ?? '∞', cost: budget.remaining_cost?.toFixed(4) ?? '∞',
            seconds: budget.remaining_seconds == null ? '∞' : Math.floor(budget.remaining_seconds),
          }) }}</dd>
        </dl>
        <p class="text-caption">{{ t('task.budget.estimated') }}</p>
      </template>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { taskService, type TaskBudget } from '../services/taskService'

const props = defineProps<{ taskId: string }>()
const { t } = useI18n()
const loading = ref(false)
const error = ref('')
const budget = ref<TaskBudget | null>(null)
let request = 0

async function load() {
  const current = ++request
  loading.value = true
  error.value = ''
  budget.value = null
  try {
    const result = await taskService.getBudget(props.taskId)
    if (current === request) budget.value = result
  } catch (cause) {
    if (current === request) error.value = apiErrorDetail(cause) ?? t('task.budget.error')
  } finally {
    if (current === request) loading.value = false
  }
}

watch(() => props.taskId, load, { immediate: true })
</script>
