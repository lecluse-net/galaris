<template>
  <q-card tag="section" flat bordered class="q-pa-sm" :aria-label="t('task.detail.detailedState')">
    <h3 class="text-subtitle2 q-mt-none q-mb-sm text-primary">
      <q-icon name="monitor_heart" size="xs" class="q-mr-xs" />
      {{ t('task.detail.detailedState') }}
    </h3>
    <StatusBadge :tone="statusTone" :label="statusLabel" />
    <q-spinner v-if="loading" color="primary" class="q-ml-sm" />
    <div v-if="round" class="text-caption q-mt-sm">
      {{ t('conversation.history.detail.attempts', { count: round.attempt_count }) }}
    </div>
    <div v-if="round?.effect_started" class="text-caption">
      {{ t('conversation.history.detail.effectStarted') }}
    </div>
    <TaskStartupTimingPanel
      v-for="timing in round?.task_startup_timings || []"
      :key="timing.task_id"
      :timing="timing"
      show-task
    />
  </q-card>
  <q-card tag="section" flat bordered class="q-pa-sm q-mt-md" :aria-label="t('task.budget.recorded')">
    <h3 class="text-subtitle2 q-mt-none q-mb-sm text-primary">
      <q-icon name="account_balance_wallet" size="xs" class="q-mr-xs" />
      {{ t('task.budget.recorded') }}
    </h3>
    <q-spinner v-if="callsLoading" color="primary" />
    <p v-if="callsError" role="alert">{{ callsError }}</p>
    <p v-if="calls.length">
      {{ t('task.budget.usage', { tokens: recordedUsage.tokens, cost: recordedUsage.cost.toFixed(4) }) }}
    </p>
    <p v-else-if="!callsLoading && !callsError">{{ t('conversation.history.detail.noLlmCalls') }}</p>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LLMCall } from '@/app/llm'
import { TaskStartupTimingPanel } from '@/app/task'
import { StatusBadge, type StatusBadgeTone } from '@/core/util'
import type { ConversationRoundDetail } from '../types'

const props = defineProps<{
  round: ConversationRoundDetail | null
  status?: string | null
  loading?: boolean
  calls: LLMCall[]
  callsLoading: boolean
  callsError: string
}>()
const { t, te } = useI18n()
const effectiveStatus = computed(() => props.status ?? props.round?.status)
const statusLabel = computed(() => {
  const status = effectiveStatus.value
  if (!status) return t('conversation.history.detail.pending')
  const key = `conversation.history.detail.roundStatuses.${status}`
  return te(key) ? t(key) : status
})
const statusTone = computed<StatusBadgeTone>(() => {
  const status = effectiveStatus.value
  if (!status || status === 'FROZEN') return 'warning'
  if (status === 'SUCCEEDED' || status === 'COMPLETED') return 'success'
  if (['RUNNING', 'CLAIMED'].includes(status)) return 'active'
  if (status === 'SUPERSEDED' || status === 'CANCELLED') return 'neutral'
  if (status === 'INTERRUPTED') return 'warning'
  return 'error'
})
const recordedUsage = computed(() => props.calls.reduce((usage, call) => ({
  tokens: usage.tokens + (call.total_tokens ?? 0),
  cost: usage.cost + (call.cost ?? 0),
}), { tokens: 0, cost: 0 }))
</script>
