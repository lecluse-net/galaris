<template>
  <section class="q-mt-sm text-caption" :aria-label="t('task.startup.title')">
    <div class="text-weight-medium">{{ t('task.startup.title') }}</div>
    <div v-if="showTask" class="startup-task q-mb-xs">
      {{ timing.label }} · {{ `galaris://task/${timing.task_id}` }}
    </div>
    <dl class="q-my-sm">
      <div v-for="stage in stages" :key="stage.label" class="row q-col-gutter-sm">
        <dt class="col-8">{{ stage.label }}</dt>
        <dd class="col-4 q-ma-none">{{ duration(stage.seconds) }}</dd>
      </div>
    </dl>
    <div v-if="timing.lifecycle_observed_since">{{ t('task.startup.observedSince', { value: date(timing.lifecycle_observed_since) }) }}</div>
    <details v-if="Object.keys(timing.phase_seconds ?? {}).length" class="q-mt-xs">
      <summary>{{ t('task.startup.phases') }}</summary>
      <div v-for="(states, phase) in timing.phase_seconds" :key="phase">
        <div class="text-weight-medium">{{ t(`task.status.${phase}`) }}</div>
        <div v-for="(seconds, state) in states" :key="state">
          {{ t(`task.startup.${state}`) }} : {{ duration(seconds) }}
        </div>
      </div>
    </details>
    <div v-if="timing.queue_wait_upper_bound_seconds != null">{{ t('task.startup.waitExplanation') }}</div>
    <dl v-if="lifecycle.length" class="q-my-sm">
      <div v-for="stage in lifecycle" :key="stage.label" class="row q-col-gutter-sm">
        <dt class="col-8">{{ stage.label }}</dt>
        <dd class="col-4 q-ma-none">{{ duration(stage.seconds) }}</dd>
      </div>
    </dl>
    <details v-if="timing.processing_intervals?.length" class="q-mt-xs">
      <summary>{{ t('task.startup.callTimings') }}</summary>
      <div v-for="interval in timing.processing_intervals" :key="interval.call_id">
        {{ interval.purpose }} · {{ date(interval.started_at) }}
        <template v-if="interval.completed_at"> → {{ date(interval.completed_at) }} · {{ duration(interval.seconds) }}</template>
      </div>
    </details>
    <details v-if="milestones.length" class="q-mt-xs">
      <summary>{{ t('task.startup.timestamps') }}</summary>
      <div v-for="milestone in milestones" :key="milestone.label">
        {{ milestone.label }} : {{ date(milestone.time!) }}
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TaskStartupTiming } from '../activity'

const { timing, showTask = false } = defineProps<{ timing: TaskStartupTiming; showTask?: boolean }>()
const { t, locale } = useI18n()
const stages = computed(() => [
  { label: t(timing.preparation_source === 'llm_calls' ? 'task.startup.preparationCalls' : 'task.startup.preparation'), seconds: timing.preparation_seconds },
  { label: t('task.startup.beforeFirstCall'), seconds: timing.preparation_to_first_call_seconds },
  { label: t('task.startup.admission'), seconds: timing.admission_seconds },
  { label: t('task.startup.wait'), seconds: timing.queue_wait_upper_bound_seconds },
].filter(stage => stage.seconds != null))
const lifecycle = computed(() => Object.entries(timing.lifecycle_seconds ?? {})
  .filter(([state]) => ['queue', 'processing', 'user_pause', 'external_wait', 'backoff'].includes(state))
  .map(([state, seconds]) => ({ label: t(`task.startup.${state}`), seconds })))
const milestones = computed(() => [
  { label: t('task.startup.preparationStarted'), time: timing.preparation_started_at },
  { label: t('task.startup.preparationFinished'), time: timing.preparation_finished_at },
  { label: t('task.startup.enqueued'), time: timing.enqueued_at },
  { label: t('task.startup.claimed'), time: timing.first_claimed_at },
].filter(milestone => milestone.time))
function duration(seconds: number | null | undefined): string {
  return t('task.startup.seconds', { value: new Intl.NumberFormat(locale.value, { maximumFractionDigits: 3 }).format(seconds ?? 0) })
}
const date = (value: string) => new Date(value).toLocaleString(locale.value, {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
})
</script>

<style scoped>
.startup-task { overflow-wrap: anywhere; }
</style>
