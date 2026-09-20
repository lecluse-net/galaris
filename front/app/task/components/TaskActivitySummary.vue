<template>
  <div v-if="activity" class="task-activity text-caption q-py-xs" role="status">
    <span>{{ activity.operational.operational_state === 'TERMINAL' && activity.phase
      ? t(`task.status.${activity.phase}`)
      : t(`task.activity.${activity.pause_pending ? 'pausePending' : activity.operational.operational_state}`) }}</span>
    <span v-if="activity.attempt_number"> · {{ t('task.activity.attempt', { number: activity.attempt_number }) }}</span>
    <span v-if="showLastActivity && activity.last_activity_at"> · {{ t('task.activity.lastActivity', { time: date(activity.last_activity_at) }) }}</span>
    <div v-for="(wait, index) in activity.operational.waits" :key="index">
      {{ t(`task.activity.${wait.kind}`) }}<span v-if="wait.peer_display || wait.process_label"> — {{ wait.peer_display || wait.process_label }}</span>
      <span v-if="wait.question"> : {{ wait.question }}</span>
    </div>
    <div v-if="activity.next_attempt_at && activity.operational.operational_state === 'QUEUED'">
      {{ t('task.activity.retryAt', { time: date(activity.next_attempt_at) }) }}
    </div>
    <div v-if="!activity.streams_ai_messages">{{ t('task.activity.fromCalls') }}</div>
    <div v-if="activity.calls_limited">{{ t('task.activity.callLimit') }}</div>
    <TaskStartupTiming v-if="showProvenance && activity.startup_timing" :timing="activity.startup_timing" />
    <details v-if="showProvenance" class="q-mt-sm">
      <summary>{{ t('task.activity.provenance') }}</summary>
      <div v-if="activity.original_demand">{{ t('task.activity.originalDemand') }} : {{ activity.original_demand }}</div>
      <div v-if="activity.run_id">{{ t('task.activity.run') }} : {{ activity.run_id }}</div>
      <div v-if="activity.parent_task_id">{{ t('task.activity.parent') }} : {{ activity.parent_task_id }}</div>
      <div v-if="activity.source_task_id">{{ t('task.activity.sourceTask') }} : {{ activity.source_task_id }}</div>
      <div v-if="activity.messenger_message_id">{{ t('task.activity.sourceMessage') }} : {{ activity.messenger_message_id }}</div>
      <div v-if="activity.delivery_policy && ['required', 'forbidden', 'optional'].includes(activity.delivery_policy)">
        {{ t('task.activity.deliveryPolicy') }} : {{ t(`task.activity.delivery_${activity.delivery_policy}`) }}
      </div>
      <div v-for="resource in activity.resources" :key="resource.reference + resource.type">
        {{ resource.type === 'delivery_receipt' ? t('task.activity.receipt') : t('task.activity.resource') }} : {{ resource.label || resource.reference }}
        <div v-if="resource.label">{{ resource.reference }}</div>
      </div>
    </details>
  </div>
  <div v-if="unavailable" class="text-caption">{{ t('task.activity.unavailable') }}</div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TaskActivitySnapshot } from '../activity'
import TaskStartupTiming from './TaskStartupTiming.vue'
const { showLastActivity = true } = defineProps<{
  activity?: TaskActivitySnapshot
  unavailable?: boolean
  showProvenance?: boolean
  showLastActivity?: boolean
}>()
const { t, locale } = useI18n()
const date = (value: string) => new Date(value).toLocaleString(locale.value)
</script>

<style scoped>
.task-activity { overflow-wrap: anywhere; }
</style>
