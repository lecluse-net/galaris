<template>
  <div v-if="activity" class="task-activity text-caption q-py-xs" role="status">
    <span>{{ activity.operational.operational_state === 'TERMINAL' && activity.phase
      ? t(`task.status.${outcome ?? activity.phase}`)
      : t(`task.activity.${activity.pause_pending ? 'pausePending' : activity.operational.operational_state}`) }}</span>
    <span v-if="activity.attempt_number"> · {{ t('task.activity.attempt', { number: activity.attempt_number }) }}</span>
    <span v-if="showLastActivity && activity.last_activity_at"> · {{ t('task.activity.lastActivity', { time: date(activity.last_activity_at) }) }}</span>
    <q-banner v-if="silenceSeconds !== null" dense rounded class="task-silence-warning q-my-sm" role="alert">
      <template #avatar><q-icon name="warning" /></template>
      {{ t('task.activity.silenceWarning', { minutes: Math.floor(silenceSeconds / 60) }) }}
      <template v-if="canRecover" #action>
        <q-btn outline color="primary"  no-caps icon="restart_alt" :label="t('task.activity.recoverCall')"
          :loading="recovering" :disable="recovering || recovery?.state === 'requested'" @click.stop="recoverCall" />
      </template>
    </q-banner>
    <div v-if="recovery && !unavailable && activity.operational.operational_state === 'RUNNING'" class="q-my-xs" aria-live="polite">
      {{ t(`task.activity.recovery_${recovery.state}`) }}
    </div>
    <div v-if="recoveryError" class="q-my-xs" role="alert">{{ recoveryError }}</div>
    <div v-if="compactWaits && waitText" class="task-wait-preview">
      <span>{{ waitPreview }}</span>
      <div ref="waitPreviewMeasure" class="task-wait-preview-measure" aria-hidden="true"></div>
      <q-resize-observer :debounce="0" @resize="updateWaitPreview" />
    </div>
    <template v-else>
      <div v-for="(description, index) in waitDescriptions" :key="index">{{ description }}</div>
    </template>
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
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useInterval } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { apiErrorDetail } from '@/core/api'
import { taskService } from '../services/taskService'
import { activitySilenceSeconds, type TaskActivitySnapshot, type TaskCallRecoveryState } from '../activity'
import TaskStartupTiming from './TaskStartupTiming.vue'
import type { TaskOutcome } from '../types'
const { activity, outcome, unavailable = false, showLastActivity = true, compactWaits = false, hideDelegatedWaits = false } = defineProps<{
  activity?: TaskActivitySnapshot
  outcome?: TaskOutcome
  unavailable?: boolean
  showProvenance?: boolean
  showLastActivity?: boolean
  compactWaits?: boolean
  hideDelegatedWaits?: boolean
}>()
const { t, locale } = useI18n()
const waitDescriptions = computed(() => (activity?.operational.waits ?? [])
  .filter(wait => !hideDelegatedWaits || wait.kind !== 'DELEGATED_TASK')
  .map(wait => {
    const target = wait.peer_display || wait.process_label
    const label = t(`task.activity.${wait.kind}`)
    return label + (target ? ` — ${target}` : '') + (wait.question ? ` : ${wait.question}` : '')
  }))
const waitText = computed(() => compactWaits ? waitDescriptions.value.join('\n') : '')
const waitPreview = ref('')
const waitPreviewMeasure = useTemplateRef<HTMLElement>('waitPreviewMeasure')

function updateWaitPreview(): void {
  const measure = waitPreviewMeasure.value
  if (!measure?.clientWidth) return

  const text = waitText.value
  measure.textContent = text
  let preview = text

  if (measure.scrollHeight > measure.clientHeight) {
    // Find the longest suffix that fits with the ellipsis at this panel width.
    const characters = Array.from(text)
    let start = 1
    let end = characters.length
    preview = '...'
    while (start <= end) {
      const middle = Math.floor((start + end) / 2)
      const candidate = `...${characters.slice(middle).join('').trimStart()}`
      measure.textContent = candidate
      if (measure.scrollHeight > measure.clientHeight) {
        start = middle + 1
      } else {
        preview = candidate
        end = middle - 1
      }
    }
  }

  measure.textContent = ''
  waitPreview.value = preview
}

watch([waitText, waitPreviewMeasure], updateWaitPreview, { flush: 'post' })

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
.task-wait-preview, .task-wait-preview-measure { max-block-size: 5lh; overflow: clip; }
.task-wait-preview { position: relative; white-space: pre-line; }
.task-wait-preview-measure { position: absolute; inset: 0 0 auto; visibility: hidden; }
.task-silence-warning { background: var(--solaire-orange-light); color: inherit; }
.task-silence-warning :deep(.q-banner__avatar) { color: var(--solaire-orange-accent); }
:global(.body--dark) .task-silence-warning { background: var(--solaire-orange-dark); }
</style>
