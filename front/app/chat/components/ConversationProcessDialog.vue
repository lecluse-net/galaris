<template>
  <q-dialog v-model="open">
    <q-card class="conversation-process-dialog galaris-detail-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="account_tree" size="sm" />
        <div class="text-h6 ellipsis q-ml-sm">
          {{ process ? processLabel(process) : t('processes.tracking.details') }}
        </div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>

      <q-card-section v-if="process" class="q-gutter-md">
        <div class="row items-center q-gutter-sm">
          <q-chip :color="statusColor(process.status)" text-color="white">
            <q-spinner v-if="isActive(process.status)" color="white" size="1em" class="q-mr-xs" />
            <q-icon v-else :name="statusIcon(process.status)" class="q-mr-xs" />
            {{ statusLabel(process.status) }}
          </q-chip>
          <span v-if="process.summary" class="text-subtitle1">{{ process.summary }}</span>
        </div>

        <div class="conversation-process-metadata">
          <div>
            <div class="metadata-label">{{ t('processes.runId') }}</div>
            <div class="text-body2 text-mono">{{ process.id }}</div>
          </div>
          <div>
            <div class="metadata-label">{{ t('processes.agent') }}</div>
            <div class="text-body2">{{ agentLabel(process) }}</div>
          </div>
          <div>
            <div class="metadata-label">{{ t('processes.tool') }}</div>
            <div class="text-body2">{{ process.tool_code }}</div>
          </div>
          <div>
            <div class="metadata-label">{{ t('processes.createdAt') }}</div>
            <div class="text-body2">{{ formatDate(process.created_at) }}</div>
          </div>
          <div>
            <div class="metadata-label">{{ t('processes.finishedAt') }}</div>
            <div class="text-body2">{{ formatDate(process.finished_at) }}</div>
          </div>
          <div>
            <div class="metadata-label">{{ t('processes.duration') }}</div>
            <div class="text-body2">{{ formatRunDuration(process) }}</div>
          </div>
        </div>

        <q-banner v-if="process.error_message" rounded class="bg-red-1 text-negative">
          <template #avatar><q-icon name="error" /></template>
          <span v-if="process.error_code">{{ process.error_code }} — </span>
          {{ process.error_message }}
        </q-banner>

        <q-expansion-item bordered icon="input" :label="t('processes.input')">
          <CodeEditor
            :model-value="pretty(process.input)"
            language="json"
            :label="t('processes.input')"
            readonly
            :show-error="false"
            :visible-lines="10"
            :min-lines="5"
            class="q-pa-md"
          />
        </q-expansion-item>
        <q-expansion-item bordered icon="output" :label="t('processes.output')">
          <CodeEditor
            :model-value="pretty(process.output)"
            language="json"
            :label="t('processes.output')"
            readonly
            :show-error="false"
            :visible-lines="10"
            :min-lines="5"
            class="q-pa-md"
          />
        </q-expansion-item>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CodeEditor } from '@/core/util'
import type { ConversationProcess, ConversationProcessStatus } from '../types'

const open = defineModel<boolean>({ required: true })
const { process } = defineProps<{
  process: ConversationProcess | null
}>()
const { t, te, locale } = useI18n()

function isActive(status: ConversationProcessStatus): boolean {
  return status === 'queued' || status === 'running'
}

function statusLabel(status: ConversationProcessStatus): string {
  if (isActive(status)) return t('chat.processInProgress')
  const key = `processes.statuses.${status}`
  return te(key) ? t(key) : status
}

function statusColor(status: ConversationProcessStatus): string {
  return ({
    success: 'positive',
    error: 'negative',
    cancelled: 'grey',
    running: 'primary',
    waiting: 'orange',
    queued: 'primary',
    cancelling: 'warning',
    unknown: 'dark',
  } as Record<ConversationProcessStatus, string>)[status]
}

function statusIcon(status: ConversationProcessStatus): string {
  return ({
    success: 'check_circle',
    error: 'error',
    cancelled: 'cancel',
    running: 'play_circle',
    waiting: 'hourglass_top',
    queued: 'schedule',
    cancelling: 'pending',
    unknown: 'help',
  } as Record<ConversationProcessStatus, string>)[status]
}

function processLabel(value: ConversationProcess): string {
  return value.process_label || value.workflow_id || `#${value.process_id}`
}

function agentLabel(value: ConversationProcess): string {
  return value.launcher_agent_code || `#${value.launcher_agent_id}`
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function formatRunDuration(value: ConversationProcess): string {
  if (!value.started_at) return '—'
  const start = Date.parse(value.started_at)
  const end = value.finished_at ? Date.parse(value.finished_at) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—'
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

function pretty(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2)
}
</script>

<style scoped>
.conversation-process-dialog {
  width: 900px;
  max-width: 96vw;
  max-height: 96vh;
  overflow-y: auto;
}

.conversation-process-metadata {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.metadata-label {
  color: #667085;
  font-size: 12px;
}

body.body--dark .metadata-label {
  color: #98a2b8;
}
</style>
