<template>
  <section class="q-pa-md q-gutter-y-md" :aria-label="t('nativeProcesses.execution.details')" :aria-busy="loading">
    <div class="row items-center no-wrap q-gutter-sm">
      <div class="text-subtitle1 col">{{ title }}</div>
      <q-btn flat round dense icon="close" :aria-label="t('nativeProcesses.execution.close')" @click="emit('close')" />
    </div>
    <q-banner v-if="error" role="alert">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="emit('retry')" /></template>
    </q-banner>
    <q-spinner v-if="loading" color="primary" />
    <template v-else-if="!error">
      <template v-if="occurrences && occurrences.total > 1">
        <q-select :model-value="selectedOccurrence" :options="options" emit-value map-options outlined dense
          :label="t('nativeProcesses.execution.occurrence')" @update:model-value="emit('select', $event)" />
        <div class="row items-center q-gutter-sm">
          <q-select :model-value="pageSize" :options="[10, 20, 50, 100, 500]" dense outlined hide-bottom-space
            :aria-label="t('nativeProcesses.execution.pageSize')" @update:model-value="emit('page', 1, $event)" />
          <q-pagination v-if="occurrences.total > pageSize" :model-value="occurrences.page" :max="Math.ceil(occurrences.total / pageSize)"
            :max-pages="5" direction-links @update:model-value="emit('page', $event, pageSize)" />
        </div>
      </template>
      <template v-if="detail">
        <div class="row items-center q-gutter-sm">
          <q-badge outline>{{ status(detail.status) }}</q-badge>
          <span v-if="detail.started_at" class="text-caption">{{ t('nativeProcesses.execution.started', { date: date(detail.started_at) }) }}</span>
          <span v-if="detail.finished_at" class="text-caption">{{ t('nativeProcesses.execution.finished', { date: date(detail.finished_at) }) }}</span>
        </div>
        <CodeEditor v-if="detail.output !== null" :model-value="pretty(detail.output)" language="json" readonly
          :label="t('nativeProcesses.execution.output')" :min-lines="3" :visible-lines="8" />
        <div v-else class="text-body2">{{ t('nativeProcesses.execution.noResult') }}</div>
        <q-expansion-item v-for="(attempt, index) in detail.attempts" :key="attempt.id" icon="history"
          :label="t('nativeProcesses.execution.attempt', { number: attempt.number })" :caption="status(attempt.status)"
          :default-opened="index === detail.attempts.length - 1">
          <div class="q-pa-sm q-gutter-y-md">
            <q-banner v-if="attempt.error" role="alert">{{ attempt.error }}</q-banner>
            <q-btn v-if="attempt.task_uri && canReadTasks" outline icon="task_alt" :label="t('nativeProcesses.execution.task')" :to="richLinkHref(attempt.task_uri) ?? ''" />
            <q-btn v-if="attempt.child_run_id" outline icon="account_tree" :label="t('nativeProcesses.execution.childRun')" :to="`/process/internal/run/${attempt.child_run_id}`" />
            <CodeEditor v-if="attempt.receipt !== null" :model-value="pretty(attempt.receipt)" language="json" readonly
              :label="t('nativeProcesses.execution.result')" :min-lines="3" :visible-lines="8" />
            <CodeEditor :model-value="pretty(attempt.input)" language="json" readonly :label="t('nativeProcesses.execution.input')" :min-lines="3" :visible-lines="8" />
            <q-expansion-item v-if="attempt.prompt" icon="description" :label="t('nativeProcesses.execution.prompt')">
              <CodeEditor :model-value="attempt.prompt" language="plaintext" readonly :label="t('nativeProcesses.execution.prompt')" :min-lines="3" :visible-lines="8" />
            </q-expansion-item>
          </div>
        </q-expansion-item>
      </template>
      <div v-else class="text-body2">{{ t('nativeProcesses.execution.notStarted') }}</div>
    </template>
    <slot />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { CodeEditor, richLinkHref } from '@/core/util'
import type { NodeExecutionDetail, NodeOccurrencePage } from '../services/nativeProcessService'
const props = defineProps<{
  title: string; detail: NodeExecutionDetail | null; occurrences: NodeOccurrencePage | null
  selectedOccurrence: string | null; pageSize: number; loading: boolean; error: boolean
}>()
const emit = defineEmits<{ select: [id: string]; page: [page: number, pageSize: number]; retry: []; close: [] }>()
const { t, te, locale } = useI18n(), privileges = usePrivilegeStore()
const canReadTasks = computed(() => privileges.hasPrivilege('TASK_ACCESS') || privileges.hasPrivilege('TASK_EDIT'))
function status(value: string): string {
  const mapped = ({ completed: 'success', failed: 'error', accepted: 'running', executing: 'running', human_waiting: 'waiting', waiting_for_input: 'waiting', waiting_approval: 'waiting', pending: 'queued', intent: 'queued', ready: 'queued' } as Record<string, string>)[value] ?? value
  const key = `processes.statuses.${mapped}`
  return te(key) ? t(key) : t('nativeProcesses.unknown')
}
function date(value: string): string { return new Date(value).toLocaleString(locale.value, { dateStyle: 'medium', timeStyle: 'medium' }) }
function pretty(value: unknown): string { return JSON.stringify(value, null, 2) }
const options = computed(() => {
  const items = [...(props.occurrences?.items ?? [])]
  if (props.detail && !items.some(item => item.id === props.detail?.id)) items.unshift(props.detail)
  return items.map(item => ({ value: item.id, label: `${item.started_at ? date(item.started_at) : t('nativeProcesses.execution.notStarted')} · ${status(item.status)}` }))
})
</script>
