<template>
  <div v-if="activity" class="task-activity text-caption q-py-xs" role="status">
    <span>{{ activity.operational.operational_state === 'TERMINAL' && activity.phase
      ? t(`task.status.${activity.phase}`)
      : t(`task.activity.${activity.pause_pending ? 'pausePending' : activity.operational.operational_state}`) }}</span>
    <span v-if="activity.attempt_number"> · {{ t('task.activity.attempt', { number: activity.attempt_number }) }}</span>
    <span v-if="showLastActivity && activity.last_activity_at"> · {{ t('task.activity.lastActivity', { time: date(activity.last_activity_at) }) }}</span>
    <q-banner v-if="silenceSeconds !== null" dense rounded class="task-silence-warning q-my-sm" role="alert">
      <template #avatar><q-icon name="warning" /></template>
      {{ t('task.activity.silenceWarning', { minutes: Math.floor(silenceSeconds / 60) }) }}
      <template v-if="canRecover" #action>
        <q-btn flat no-caps icon="restart_alt" :label="t('task.activity.recoverCall')"
          :loading="recovering" :disable="recovering || recovery?.state === 'requested'" @click.stop="recoverCall" />
      </template>
    </q-banner>
    <div v-if="recovery && !unavailable && activity.operational.operational_state === 'RUNNING'" class="q-my-xs" aria-live="polite">
      {{ t(`task.activity.recovery_${recovery.state}`) }}
    </div>
    <div v-if="recoveryError" class="q-my-xs" role="alert">{{ recoveryError }}</div>
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
import { computed, ref, watch } from 'vue'
import { useInterval } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { apiErrorDetail } from '@/core/api'
import { taskService } from '../services/taskService'
import { activitySilenceSeconds, type TaskActivitySnapshot, type TaskCallRecoveryState } from '../activity'
import TaskStartupTiming from './TaskStartupTiming.vue'
const { activity, unavailable = false, showLastActivity = true } = defineProps<{
  activity?: TaskActivitySnapshot
  unavailable?: boolean
  showProvenance?: boolean
  showLastActivity?: boolean
}>()
const { t, locale } = useI18n()
const now = ref(Date.now())
const { registerInterval } = useInterval()
registerInterval(() => { now.value = Date.now() }, 1_000)
const silenceSeconds = computed(() => unavailable ? null : activitySilenceSeconds(activity, now.value))
const privilegeStore = usePrivilegeStore()
const pendingRequest = ref<string | null>(null)
const recovering = computed(() => pendingRequest.value !== null)
const recoveryError = ref('')
const localRecovery = ref<TaskCallRecoveryState | null>(null)
const recovery = computed(() => {
  const remote = activity?.call_recovery
  if (remote && (!localRecovery.value || remote.version >= localRecovery.value.version)) return remote
  return localRecovery.value
})
const canRecover = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT)
  && activity?.call_recovery_supported && activity.run_id && activity.operational.operational_state === 'RUNNING')
watch([() => activity?.task_id, () => activity?.run_id, () => activity?.latest_attempt?.id], () => {
  pendingRequest.value = null
  localRecovery.value = null
  recoveryError.value = ''
}, { flush: 'sync' })
async function recoverCall() {
  if (!activity?.run_id || !canRecover.value || recovering.value || recovery.value?.state === 'requested') return
  const taskId = activity.task_id
  const runId = activity.run_id
  const attemptId = activity.latest_attempt?.id
  const requestId = crypto.randomUUID()
  pendingRequest.value = requestId
  recoveryError.value = ''
  try {
    const state = await taskService.recoverCall(taskId, runId, requestId, recovery.value?.version ?? 0)
    if (pendingRequest.value === requestId && activity?.task_id === taskId && activity.run_id === runId && activity.latest_attempt?.id === attemptId) {
      localRecovery.value = state
    }
  } catch (error) {
    if (pendingRequest.value === requestId && activity?.task_id === taskId && activity.run_id === runId && activity.latest_attempt?.id === attemptId) {
      recoveryError.value = apiErrorDetail(error) || t('task.activity.recoveryError')
    }
  } finally {
    if (pendingRequest.value === requestId) pendingRequest.value = null
  }
}
const date = (value: string) => new Date(value).toLocaleString(locale.value)
</script>

<style scoped>
.task-activity { overflow-wrap: anywhere; }
.task-silence-warning { background: var(--solaire-orange-light); color: inherit; }
.task-silence-warning :deep(.q-banner__avatar) { color: var(--solaire-orange-accent); }
:global(.body--dark) .task-silence-warning { background: var(--solaire-orange-dark); }
</style>
