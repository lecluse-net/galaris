<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="dream" :help-text="$t('contextHelpPages.dream')" :icon="navigationIcon('bedtime')" :title="t('nav.dream')" :description="t('nav.dream_desc')">
      <template #title-after>
        <q-badge color="positive" rounded>
          <q-icon name="fiber_manual_record" size="10px" class="q-mr-xs" />
          {{ t('dream.live') }}
        </q-badge>
      </template>
    </PageHeader>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error" /></template>
      {{ error }}
    </q-banner>

    <div v-if="overview" class="row q-col-gutter-md q-mb-lg">
      <div v-for="metric in metrics" :key="metric.key" class="col-12 col-sm-6 col-md-3">
        <q-card
          flat
          bordered
          class="dream-metric full-height"
          :class="{
            'dream-metric--interactive': metric.key === 'errors',
            'dream-metric--active': metric.key === 'errors' && statusFilter === 'error',
          }"
          :role="metric.key === 'errors' ? 'button' : undefined"
          :tabindex="metric.key === 'errors' ? 0 : undefined"
          :aria-pressed="metric.key === 'errors' ? statusFilter === 'error' : undefined"
          @click="metric.key === 'errors' && toggleErrors()"
          @keydown.enter.prevent="metric.key === 'errors' && toggleErrors()"
          @keydown.space.prevent="metric.key === 'errors' && toggleErrors()"
        >
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md" style="min-width: 0">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <div class="text-h5 text-weight-medium">{{ metric.value }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <q-card
      v-if="overview"
      flat
      bordered
      class="q-mb-lg dream-runtime"
      :class="`dream-runtime--${overview.runtime.status}`"
    >
      <q-card-section class="row items-center no-wrap">
        <q-avatar :color="runtimeVisual.color" text-color="white" :icon="runtimeVisual.icon" />
        <div class="col q-ml-md" style="min-width: 0">
          <div class="row items-center q-gutter-sm">
            <div class="text-weight-medium">{{ t(`dream.runtime.${overview.runtime.status}`) }}</div>
            <q-badge outline :color="runtimeVisual.color">
              {{ t(`dream.runtime.phases.${overview.runtime.phase}`) }}
            </q-badge>
          </div>
          <div class="text-body2 text-grey-7">
            {{ t(`dream.runtime.reasons.${overview.runtime.reason}`) }}
          </div>
          <div
            v-if="overview.runtime.current_mechanism && overview.runtime.current_subject_id"
            class="text-caption ellipsis"
          >
            {{
              t('dream.runtime.current', {
                mechanism: mechanismLabel(overview.runtime.current_mechanism),
                subject: overview.runtime.current_subject_id,
              })
            }}
          </div>
          <div class="row items-center q-gutter-xs q-mt-xs dream-runtime-meta">
            <q-chip dense size="sm" icon="history">
              {{
                overview.runtime.last_cycle_at
                  ? t('dream.runtime.lastCycle', { date: formatDate(overview.runtime.last_cycle_at) })
                  : t('dream.runtime.noCycle')
              }}
            </q-chip>
            <q-chip v-if="overview.runtime.next_cycle_at" dense size="sm" icon="schedule">
              {{ t('dream.runtime.nextCycle', { date: formatDate(overview.runtime.next_cycle_at) }) }}
            </q-chip>
            <q-chip dense size="sm" icon="repeat">
              {{ t('dream.runtime.cycleCount', { count: overview.runtime.cycle_count }) }}
            </q-chip>
            <q-chip
              v-if="overview.runtime.last_error_type"
              dense
              size="sm"
              color="negative"
              text-color="white"
              icon="error"
            >
              {{ t('dream.runtime.lastError', { type: overview.runtime.last_error_type }) }}
            </q-chip>
          </div>
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pt-md">
        <div class="text-subtitle2">{{ t('dream.overview.progressByAction') }}</div>
        <div class="text-caption text-grey-7 q-mb-md">
          {{ t('dream.overview.progressByActionHint') }}
        </div>

        <div class="dream-action-progress-list">
          <div
            v-for="action in actionProgress"
            :key="action.mechanismKey"
            class="dream-action-progress"
            :class="{ 'dream-action-progress--current': action.current }"
          >
            <div class="row items-center no-wrap q-gutter-xs dream-action-label">
              <q-icon
                :name="action.current ? 'play_circle' : action.remaining === 0 && action.total > 0 ? 'check_circle' : 'pending_actions'"
                :color="action.color"
                size="18px"
              />
              <span class="text-body2 text-weight-medium ellipsis">
                {{ mechanismLabel(action.mechanismKey) }}
              </span>
              <q-tooltip v-if="action.current">
                {{ t('dream.overview.currentAction') }}
              </q-tooltip>
            </div>

            <q-linear-progress
              rounded
              size="8px"
              class="dream-action-bar"
              :color="action.color"
              track-color="grey-3"
              :value="action.percent / 100"
              :aria-label="
                action.total
                  ? t('dream.overview.actionProgress', {
                      done: action.completed,
                      remaining: action.remaining,
                      total: action.total,
                    })
                  : t('dream.overview.noActionWork')
              "
            />

            <div class="text-caption text-no-wrap dream-action-progress-value">
              <span class="text-weight-medium">{{ action.displayedPercent }} %</span>
              <span class="text-grey-7"> · {{ action.completed }}/{{ action.total }}</span>
              <q-tooltip>
                {{
                  action.total
                    ? t('dream.overview.actionProgress', {
                        done: action.completed,
                        remaining: action.remaining,
                        total: action.total,
                      })
                    : t('dream.overview.noActionWork')
                }}
              </q-tooltip>
            </div>

            <div class="row items-center justify-end no-wrap q-gutter-sm dream-action-states">
              <span v-if="action.running" class="dream-action-state text-primary">
                <q-icon name="play_arrow" size="15px" />{{ action.running }}
                <q-tooltip>{{ t('dream.overview.runningCount', { count: action.running }) }}</q-tooltip>
              </span>
              <span v-if="action.retry" class="dream-action-state text-warning">
                <q-icon name="replay" size="15px" />{{ action.retry }}
                <q-tooltip>{{ t('dream.overview.retryCount', { count: action.retry }) }}</q-tooltip>
              </span>
              <span v-if="action.error" class="dream-action-state text-negative">
                <q-icon name="error_outline" size="15px" />{{ action.error }}
                <q-tooltip>{{ t('dream.overview.errorCount', { count: action.error }) }}</q-tooltip>
              </span>
            </div>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered class="dream-history-card">
      <q-card-section class="dream-history-header">
        <div class="row items-center justify-between no-wrap dream-history-header-row">
          <div class="row items-center no-wrap dream-history-title">
            <q-icon name="history" size="sm" class="q-mr-sm" />
            <span class="text-subtitle1">
              {{ t('executionMonitoring.history', { count: pagination.rowsNumber }) }}
            </span>
          </div>
          <div class="row items-center dream-history-filters">
            <q-input
              v-model="search"
              outlined
              dense
              clearable
              debounce="300"
              :label="t('dream.history.search')"
              class="dream-search-filter"
              @update:model-value="filtersChanged"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
            <q-select
              v-model="statusFilter"
              outlined
              dense
              emit-value
              map-options
              :label="t('dream.history.status')"
              :options="statusOptions"
              class="dream-select-filter"
              @update:model-value="filtersChanged"
            />
            <q-select
              v-model="mechanismFilter"
              outlined
              dense
              emit-value
              map-options
              :label="t('dream.history.mechanism')"
              :options="mechanismOptions"
              class="dream-select-filter"
              @update:model-value="filtersChanged"
            />
            <ExecutionDateFilters
              v-model:date-from="dateFrom"
              v-model:date-to="dateTo"
              @change="filtersChanged"
            />
          </div>
        </div>
        <q-separator class="q-mt-sm" />
      </q-card-section>

      <q-table
        v-model:pagination="pagination"
        flat
        class="dream-history-table"
        row-key="id"
        :rows="receipts"
        :columns="columns"
        :loading="loading"
        :grid="$q.screen.lt.md"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :no-data-label="t('dream.history.noRows')"
        @request="onRequest"
        @row-click="openReceipt"
      >
        <template #body-cell-updated_at="props">
          <q-td :props="props">{{ formatDate(props.row.updated_at) }}</q-td>
        </template>
        <template #body-cell-mechanism="props">
          <q-td :props="props">
            <div class="dream-mechanism-label">
              {{ mechanismLabel(props.row.mechanism_key) }}
            </div>
          </q-td>
        </template>
        <template #body-cell-subject="props">
          <q-td :props="props">
            <div class="text-weight-medium dream-subject-preview">
              {{ receiptSubjectPreview(props.row) }}
              <q-tooltip>{{ receiptSubjectPreview(props.row) }}</q-tooltip>
            </div>
          </q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge
              rounded
              :color="receiptStatusVisual(props.row.status).color"
              :label="t(`dream.statuses.${props.row.status}`)"
            />
          </q-td>
        </template>
        <template #body-cell-result_count="props">
          <q-td :props="props">
            {{ receiptResultLabel(props.row) }}
          </q-td>
        </template>
        <template #body-cell-cost="props">
          <q-td :props="props">{{ formatCost(props.row.cost) }}</q-td>
        </template>
        <template #item="props">
          <div class="col-12 col-md-6 q-pa-xs">
            <q-card
              flat
              bordered
              class="dream-history-item"
              role="button"
              tabindex="0"
              :aria-label="receiptSubjectPreview(props.row)"
              @click="openReceiptRow(props.row)"
              @keydown.enter.prevent="openReceiptRow(props.row)"
              @keydown.space.prevent="openReceiptRow(props.row)"
            >
              <q-card-section class="q-pa-sm">
                <div class="row items-start justify-between no-wrap q-gutter-sm">
                  <div class="col" style="min-width: 0">
                    <div class="text-caption text-grey-7">
                      {{ formatDate(props.row.updated_at) }}
                    </div>
                    <div class="text-body2 text-weight-medium dream-mechanism-label">
                      {{ mechanismLabel(props.row.mechanism_key) }}
                    </div>
                  </div>
                  <q-badge
                    rounded
                    :color="receiptStatusVisual(props.row.status).color"
                    :label="t(`dream.statuses.${props.row.status}`)"
                  />
                </div>

                <div class="dream-history-item-subject q-mt-sm">
                  {{ receiptSubjectPreview(props.row) }}
                </div>

                <div class="row items-center q-col-gutter-sm q-mt-sm text-caption text-grey-7">
                  <div>
                    {{ t('dream.history.attempts') }} : {{ props.row.attempts }}
                  </div>
                  <div class="col dream-history-item-result">
                    {{ receiptResultLabel(props.row) }}
                  </div>
                  <div>{{ formatCost(props.row.cost) }}</div>
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="detailOpen">
      <q-card class="dream-detail-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="bedtime" size="sm" />
          <div class="text-subtitle1 text-weight-medium q-ml-sm">
            {{ t('dream.detail.title') }}
          </div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('dream.detail.close')" />
        </q-card-section>

        <q-separator />

        <q-card-section v-if="detailLoading" class="row justify-center q-pa-xl">
          <q-spinner color="primary" size="42px" />
        </q-card-section>

        <template v-else-if="selectedReceipt">
          <q-card-section>
            <div class="row q-col-gutter-md">
              <div class="col-12 col-md-6">
                <div class="text-caption text-grey-7">{{ t('dream.detail.mechanism') }}</div>
                <div>{{ mechanismLabel(selectedReceipt.mechanism_key) }}</div>
              </div>
              <div class="col-12 col-md-6">
                <div class="text-caption text-grey-7">{{ t('dream.history.status') }}</div>
                <q-badge
                  :color="receiptStatusVisual(selectedReceipt.status).color"
                  :label="t(`dream.statuses.${selectedReceipt.status}`)"
                />
              </div>
              <div class="col-12">
                <div class="text-caption text-grey-7">{{ t('dream.detail.subject') }}</div>
                <div class="text-weight-medium">{{ receiptSubjectPreview(selectedReceipt) }}</div>
                <div class="text-caption text-grey-7">{{ selectedReceipt.subject_id }}</div>
                <div v-if="selectedReceipt.agent_id !== null" class="text-caption">
                  {{ t('dream.detail.agent', { id: selectedReceipt.agent_id }) }}
                </div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('dream.detail.created') }}</div>
                <div>{{ formatDate(selectedReceipt.created_at) }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('dream.detail.updated') }}</div>
                <div>{{ formatDate(selectedReceipt.updated_at) }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('dream.detail.attempts') }}</div>
                <div>{{ selectedReceipt.attempts }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('dream.history.cost') }}</div>
                <div>{{ formatCost(selectedReceipt.cost) }}</div>
              </div>
            </div>

            <q-btn
              v-if="selectedTaskId"
              class="q-mt-md"
              outline
              color="primary"
              icon="open_in_new"
              :label="t('dream.detail.task')"
              :to="{ path: '/task', query: { task_id: selectedTaskId } }"
            />
          </q-card-section>

          <q-separator />

          <q-card-section v-if="outcomeDiagnostics">
            <div class="text-subtitle1 text-weight-medium">
              {{ t('dream.detail.outcomeDiagnostics') }}
            </div>
            <div class="text-caption text-grey-7 q-mb-sm">
              {{ t('dream.detail.outcomeDiagnosticsHint') }}
            </div>
            <div class="row q-gutter-xs q-mb-md">
              <q-chip dense icon="rule">
                {{ t('dream.detail.significance', { reason: outcomeDiagnostics.significanceReason }) }}
              </q-chip>
              <q-chip dense icon="visibility">
                {{ t('dream.detail.applicationMode', { mode: outcomeDiagnostics.applicationMode }) }}
              </q-chip>
              <q-chip
                dense
                :color="outcomeDiagnostics.included ? 'positive' : 'grey-6'"
                text-color="white"
              >
                {{ outcomeDiagnostics.included ? t('dream.detail.included') : t('dream.detail.excluded') }}
              </q-chip>
            </div>
            <q-list v-if="outcomeDiagnostics.observations.length" bordered separator dense>
              <q-item
                v-for="observation in outcomeDiagnostics.observations"
                :key="`${observation.reference}-${observation.status ?? ''}`"
              >
                <q-item-section>
                  <q-item-label>
                    {{ observation.name || observation.kind }}
                  </q-item-label>
                  <q-item-label caption>
                    {{ observation.kind }} · {{ observation.status || t('dream.detail.noStatus') }}
                  </q-item-label>
                  <q-item-label v-if="observation.detail" caption class="q-mt-xs">
                    {{ observation.detail }}
                  </q-item-label>
                  <q-item-label caption class="text-mono q-mt-xs">
                    {{ observation.reference }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
            <q-banner v-else rounded class="bg-grey-2 text-grey-8">
              {{ t('dream.detail.noEvidence') }}
            </q-banner>
          </q-card-section>

          <q-separator v-if="outcomeDiagnostics" />

          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              {{ t('dream.detail.inference', { count: selectedReceipt.llm_calls.length }) }}
            </div>
            <div class="text-caption text-grey-7 q-mb-md">
              {{ t('dream.detail.inferenceHint') }}
            </div>

            <LlmCalls
              v-if="selectedReceipt.llm_calls.length"
              :external-calls="selectedReceipt.llm_calls"
            />
            <q-banner v-else rounded class="bg-grey-2 text-grey-8">
              {{ t('dream.detail.noInference') }}
            </q-banner>
          </q-card-section>

          <q-separator v-if="isMemoryExtractionMechanism(selectedReceipt.mechanism_key)" />

          <q-card-section v-if="isMemoryExtractionMechanism(selectedReceipt.mechanism_key)">
            <div class="text-subtitle1 text-weight-medium">{{ t('dream.detail.proposed') }}</div>
            <div class="text-caption text-grey-7 q-mb-md">{{ t('dream.detail.proposedHint') }}</div>

            <q-list v-if="extractionOperations.length" bordered separator>
              <q-item
                v-for="(operation, index) in extractionOperations"
                :key="`${index}-${operation.action}-${operation.action === 'LINK' ? operation.target_memory_id : operation.title}`"
              >
                <q-item-section>
                  <q-item-label>
                    <q-badge
                      outline
                      :color="operation.action === 'LINK' ? 'secondary' : 'primary'"
                      :label="t(operation.action === 'LINK' ? 'dream.detail.linkAction' : 'dream.detail.createAction')"
                      class="q-mr-sm"
                    />
                    <span v-if="operation.action !== 'LINK'" class="text-weight-medium">
                      {{ operation.title }}
                    </span>
                    <span v-else class="text-weight-medium">
                      {{ t('dream.detail.linkTarget', { id: operation.target_memory_id }) }}
                    </span>
                  </q-item-label>
                  <template v-if="operation.action !== 'LINK'">
                    <q-item-label caption>{{ operation.content }}</q-item-label>
                    <q-item-label v-if="operation.memory_type" caption class="q-mt-xs">
                      {{ t('dream.detail.memoryType', { type: memoryTypeLabel(operation.memory_type) }) }}
                    </q-item-label>
                    <div v-if="operation.keywords?.length" class="row q-gutter-xs q-mt-sm">
                      <q-chip v-for="keyword in operation.keywords" :key="keyword" dense size="sm">
                        {{ keyword }}
                      </q-chip>
                    </div>
                  </template>
                  <q-item-label v-else-if="operation.reason" caption class="q-mt-xs">
                    {{ operation.reason }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
            <q-banner v-else rounded class="bg-grey-2 text-grey-8">
              {{ t('dream.detail.noProposal') }}
            </q-banner>
          </q-card-section>

          <q-card-section v-if="selectedReceipt.last_error">
            <q-banner rounded class="bg-red-1 text-negative">
              <div class="text-weight-medium">{{ t('dream.detail.error') }}</div>
              <div class="text-caption">{{ selectedReceipt.last_error }}</div>
            </q-banner>
          </q-card-section>
        </template>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { QTableColumn, QTableProps } from 'quasar'
import { LlmCalls } from '@/app/llm'
import { BaseRoom, websocket } from '@/core/websocket'
import { ExecutionDateFilters, PageHeader } from '@/core/util'
import { dreamService } from '../services/dreamService'
import type {
  DreamOverview,
  DreamMechanismKey,
  DreamMechanismSummary,
  DreamOutcomeDiagnostics,
  DreamOutcomeEvidenceItem,
  MemoryExtractionOperation,
  DreamReceiptDetail,
  DreamReceiptStatus,
  DreamReceiptSummary,
  DreamRuntimeStatus,
  ProposedMemory,
} from '../types'

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

class DreamRoom extends BaseRoom {
  readonly className = 'DreamRoom'
}

const { t, locale } = useI18n()
const $q = useQuasar()
const route = useRoute()
const overview = ref<DreamOverview | null>(null)
const receipts = ref<DreamReceiptSummary[]>([])
const selectedReceipt = ref<DreamReceiptDetail | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const detailOpen = ref(false)
const error = ref('')
const search = ref('')
const statusFilter = ref<DreamReceiptStatus | null>(null)
const mechanismFilter = ref<string | null>(null)
const dateFrom = ref<string | null>(null)
const dateTo = ref<string | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let refreshRequested = false
let realtimeRefreshTimer: ReturnType<typeof setTimeout> | null = null

const mechanismTranslationKeys = {
  'memory.attachment_text': 'dream.mechanisms.attachmentText',
  'memory.attachment_document': 'dream.mechanisms.attachmentDocument',
  'memory.attachment_image': 'dream.mechanisms.attachmentImage',
  'memory.attachment_video': 'dream.mechanisms.attachmentVideo',
  'topic.classify_message': 'dream.mechanisms.messageTopicClassification',
  'topic.classify_voice_turn': 'dream.mechanisms.voiceTurnTopicClassification',
  'topic.classify_task': 'dream.mechanisms.taskTopicClassification',
  'topic.classify_voice_session': 'dream.mechanisms.voiceTopicClassification',
  'memory.extract_task': 'dream.mechanisms.taskMemory',
  'memory.extract_conversation_round': 'dream.mechanisms.conversationMemory',
  'memory.reflect_task_outcome': 'dream.mechanisms.taskOutcomeReflection',
  'skill.learn_task_outcome': 'dream.mechanisms.learnedSkills',
  'memory.extract_voice_turn': 'dream.mechanisms.voiceMemory',
  'memory.link_topic_source': 'dream.mechanisms.topicMemoryLinks',
  'memory.project_process': 'dream.mechanisms.processMemory',
  'memory.maintain_findings': 'dream.mechanisms.memoryMaintenance',
  'topic.suggest_maintenance': 'dream.mechanisms.topicMaintenance',
  'memory.forget_stale': 'dream.mechanisms.staleMemory',
} satisfies Record<DreamMechanismKey, string>

const memoryTypeTranslationKeys: Record<string, string> = {
  core: 'memory.types.core',
  working: 'memory.types.working',
  episodic: 'memory.types.episodic',
  semantic: 'memory.types.semantic',
  procedural: 'memory.types.procedural',
  social: 'memory.types.social',
}

const columns = computed<QTableColumn<DreamReceiptSummary>[]>(() => [
  { name: 'updated_at', label: t('dream.history.date'), field: 'updated_at', align: 'left', style: 'width: 150px', headerStyle: 'width: 150px' },
  { name: 'mechanism', label: t('dream.history.mechanism'), field: 'mechanism_key', align: 'left', style: 'width: 200px', headerStyle: 'width: 200px' },
  { name: 'subject', label: t('dream.history.subject'), field: 'subject_id', align: 'left' },
  { name: 'status', label: t('dream.history.status'), field: 'status', align: 'left', style: 'width: 100px', headerStyle: 'width: 100px' },
  { name: 'attempts', label: t('dream.history.attempts'), field: 'attempts', align: 'right', style: 'width: 78px', headerStyle: 'width: 78px' },
  { name: 'result_count', label: t('dream.history.results'), field: 'result_count', align: 'left', style: 'width: 170px', headerStyle: 'width: 170px' },
  { name: 'cost', label: t('dream.history.cost'), field: 'cost', align: 'right', style: 'width: 90px', headerStyle: 'width: 90px' },
])

const statusOptions = computed(() => [
  { label: t('dream.history.allStatuses'), value: null },
  ...(['retry', 'success', 'error'] as DreamReceiptStatus[]).map(status => ({
    label: t(`dream.statuses.${status}`),
    value: status,
  })),
])

const mechanismOptions = computed(() => [
  { label: t('dream.history.allMechanisms'), value: null },
  ...(overview.value?.mechanisms ?? []).map(item => ({
    label: mechanismLabel(item.mechanism_key),
    value: item.mechanism_key,
  })),
])

interface DreamActionProgress {
  mechanismKey: string
  completed: number
  remaining: number
  total: number
  running: number
  retry: number
  error: number
  percent: number
  displayedPercent: number
  current: boolean
  color: string
}

const actionProgress = computed<DreamActionProgress[]>(() =>
  (overview.value?.mechanisms ?? []).map(actionProgressView),
)

function actionProgressView(mechanism: DreamMechanismSummary): DreamActionProgress {
  const completed = mechanism.success + mechanism.error
  const remaining = mechanism.pending + mechanism.running + mechanism.retry
  const total = completed + remaining
  const percent = total ? Math.min(100, (completed / total) * 100) : 0
  const current = overview.value?.runtime.current_mechanism === mechanism.mechanism_key
  return {
    mechanismKey: mechanism.mechanism_key,
    completed,
    remaining,
    total,
    running: mechanism.running,
    retry: mechanism.retry,
    error: mechanism.error,
    percent,
    displayedPercent: total && remaining === 0 ? 100 : Math.min(99, Math.floor(percent)),
    current,
    color: current ? 'primary' : remaining > 0 ? 'warning' : total > 0 ? 'positive' : 'grey-5',
  }
}
const metrics = computed(() => {
  if (!overview.value) return []
  return [
    { key: 'completed', label: t('dream.overview.completed'), value: overview.value.completed_operations, icon: 'fact_check', color: 'positive' },
    { key: 'remaining', label: t('dream.overview.remaining'), value: overview.value.pending_operations, icon: 'hourglass_top', color: 'warning' },
    { key: 'memories-created', label: t('dream.overview.memoriesCreated'), value: overview.value.memories_created, icon: 'add_circle', color: 'primary' },
    { key: 'memories-linked', label: t('dream.overview.memoriesLinked'), value: overview.value.memories_linked, icon: 'link', color: 'secondary' },
    { key: 'errors', label: t('dream.overview.errors'), value: overview.value.error_receipts, icon: 'error', color: 'negative' },
  ]
})

const runtimeVisual = computed(() => {
  const visuals: Record<DreamRuntimeStatus, { icon: string; color: string }> = {
    disabled: { icon: 'bedtime_off', color: 'grey' },
    stopped: { icon: 'stop_circle', color: 'grey' },
    starting: { icon: 'pending', color: 'info' },
    running: { icon: 'psychology', color: 'primary' },
    paused_voice: { icon: 'record_voice_over', color: 'deep-orange' },
    paused_tasks: { icon: 'monitor_heart', color: 'warning' },
    idle: { icon: 'bedtime', color: 'positive' },
    unavailable: { icon: 'model_training', color: 'negative' },
    faulted: { icon: 'error', color: 'negative' },
  }
  return visuals[overview.value?.runtime.status ?? 'stopped']
})

const extractionOperations = computed<MemoryExtractionOperation[]>(() => {
  const payload = selectedReceipt.value?.prepared_payload
  if (!payload) return []

  const decision = payload.decision
  if (decision && typeof decision === 'object') {
    const operations = (decision as Record<string, unknown>).operations
    if (Array.isArray(operations)) return operations.filter(isMemoryExtractionOperation)
  }

  const legacyMemories = payload.memories
  if (!Array.isArray(legacyMemories)) return []
  return legacyMemories.filter(isProposedMemory).map(memory => ({
    ...memory,
    action: 'CREATE' as const,
  }))
})

const selectedTaskId = computed<string | null>(() => {
  const receipt = selectedReceipt.value
  if (!receipt) return null
  if (receipt.subject_kind === 'task') return receipt.subject_id
  if (receipt.subject_kind === 'task_outcome') return receipt.subject_id.split(':', 1)[0] ?? null
  return null
})

const outcomeDiagnostics = computed<DreamOutcomeDiagnostics | null>(() => {
  const payload = selectedReceipt.value?.prepared_payload
  if (!payload || typeof payload !== 'object') return null
  if (typeof payload.significance_reason !== 'string') return null
  const evidence = payload.evidence
  if (!evidence || typeof evidence !== 'object') return null
  const evidenceRecord = evidence as Record<string, unknown>
  const observations = Array.isArray(evidenceRecord.observations)
    ? evidenceRecord.observations.filter(isOutcomeEvidenceItem)
    : []
  return {
    significanceReason: payload.significance_reason,
    applicationMode: String(payload.application_mode ?? ''),
    included: payload.included === true,
    observations,
  }
})

async function loadOverview(): Promise<void> {
  overview.value = await dreamService.overview()
}

async function loadReceipts(
  page: number = pagination.value.page,
  pageSize: number = pagination.value.rowsPerPage,
): Promise<void> {
  const response = await dreamService.receipts({
    page,
    pageSize,
    status: statusFilter.value,
    active: false,
    dateFrom: dateFrom.value,
    dateTo: dateTo.value,
    mechanism: mechanismFilter.value,
    search: search.value,
  })
  receipts.value = response.items
  pagination.value = {
    page: response.page,
    rowsPerPage: response.page_size,
    rowsNumber: response.total,
  }
}

async function loadAll(): Promise<void> {
  if (loading.value) {
    refreshRequested = true
    return
  }
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadOverview(), loadReceipts(), refreshSelectedReceipt()])
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('dream.loadError')
  } finally {
    loading.value = false
    if (refreshRequested) {
      refreshRequested = false
      void loadAll()
    }
  }
}

async function refreshSelectedReceipt(): Promise<void> {
  const receiptId = detailOpen.value ? selectedReceipt.value?.id : null
  if (!receiptId) return
  selectedReceipt.value = await dreamService.receipt(receiptId)
}

async function onRequest(request: TableRequest): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await loadReceipts(request.pagination.page, request.pagination.rowsPerPage)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('dream.loadError')
  } finally {
    loading.value = false
  }
}

function filtersChanged(): void {
  pagination.value.page = 1
  void loadAll()
}

function toggleErrors(): void {
  statusFilter.value = statusFilter.value === 'error' ? null : 'error'
  filtersChanged()
}

function scheduleRealtimeRefresh(): void {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  realtimeRefreshTimer = setTimeout(() => {
    realtimeRefreshTimer = null
    void loadAll()
  }, 250)
}

async function openReceipt(_event: Event, row: DreamReceiptSummary): Promise<void> {
  await openReceiptRow(row)
}

async function openReceiptRow(row: DreamReceiptSummary): Promise<void> {
  await openReceiptId(row.id)
}

async function openReceiptId(receiptId: string): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  selectedReceipt.value = null
  try {
    selectedReceipt.value = await dreamService.receipt(receiptId)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('dream.loadError')
    detailOpen.value = false
  } finally {
    detailLoading.value = false
  }
}

function receiptSubjectPreview(receipt: DreamReceiptSummary): string {
  return receipt.subject_preview?.trim()
    || receipt.task_label?.trim()
    || t('dream.history.subjectUnavailable')
}

function mechanismLabel(key: string): string {
  const translationKey = mechanismTranslationKeys[key as DreamMechanismKey]
  return translationKey ? t(translationKey) : key
}

function memoryTypeLabel(type: string): string {
  const translationKey = memoryTypeTranslationKeys[type]
  return translationKey ? t(translationKey) : type
}

function receiptStatusVisual(status: DreamReceiptStatus): { color: string } {
  return {
    running: { color: 'primary' },
    retry: { color: 'warning' },
    success: { color: 'positive' },
    error: { color: 'negative' },
  }[status]
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function formatCost(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 4,
  }).format(value)
}

function isProposedMemory(value: unknown): value is ProposedMemory {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.title === 'string' && typeof candidate.content === 'string'
}

function isMemoryExtractionOperation(value: unknown): value is MemoryExtractionOperation {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  if (candidate.action === 'CREATE') return isProposedMemory(value)
  return candidate.action === 'LINK' && typeof candidate.target_memory_id === 'string'
}

function isMemoryExtractionMechanism(mechanismKey: string): boolean {
  return mechanismKey === 'memory.extract_task'
    || mechanismKey === 'memory.extract_conversation_round'
    || mechanismKey === 'memory.extract_voice_turn'
}

function receiptResultLabel(receipt: DreamReceiptSummary): string {
  if (!receipt.result_count) return t('dream.history.noResult')
  if (isMemoryExtractionMechanism(receipt.mechanism_key)) {
    return t('dream.history.memoryEffectCount', { count: receipt.result_count })
  }
  if (receipt.mechanism_key.startsWith('topic.classify_')) {
    return t('dream.history.topicAssociationCount', { count: receipt.result_count })
  }
  return t('dream.history.effectCount', { count: receipt.result_count })
}

function isOutcomeEvidenceItem(value: unknown): value is DreamOutcomeEvidenceItem {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.reference === 'string' && typeof candidate.kind === 'string'
}

watch(
  () => route.query.receipt_id,
  value => {
    const receiptId = Array.isArray(value) ? value[0] : value
    if (!receiptId || selectedReceipt.value?.id === receiptId) return
    void openReceiptId(receiptId)
  },
  { immediate: true },
)

onMounted(() => {
  void loadAll()
  const socket = websocket.createWebsocket()
  websocket.setDisplayedRoom(new DreamRoom('monitoring'))
  socket.on('connect', scheduleRealtimeRefresh)
  websocket.onEvent('dream', 'update', scheduleRealtimeRefresh)
})

onBeforeUnmount(() => websocket.setDisplayedRoom(null))

onUnmounted(() => {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  websocket.socket?.off('connect', scheduleRealtimeRefresh)
  websocket.offEvent('dream', 'update', scheduleRealtimeRefresh)
})
</script>

<style scoped>
.dream-runtime {
  border: 1px solid color-mix(in srgb, var(--q-primary) 24%, transparent);
  background: color-mix(in srgb, var(--q-primary) 7%, transparent);
}

.dream-runtime--paused_voice,
.dream-runtime--paused_tasks {
  border-color: color-mix(in srgb, var(--q-warning) 40%, transparent);
  background: color-mix(in srgb, var(--q-warning) 10%, transparent);
}

.dream-runtime--disabled,
.dream-runtime--stopped,
.dream-runtime--unavailable,
.dream-runtime--faulted {
  border-color: color-mix(in srgb, var(--q-negative) 30%, transparent);
  background: color-mix(in srgb, var(--q-negative) 7%, transparent);
}

.dream-metric {
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.dream-metric--interactive {
  cursor: pointer;
}

.dream-metric--interactive:hover,
.dream-metric--interactive:focus-visible,
.dream-metric--active {
  border-color: var(--q-negative);
  box-shadow: 0 4px 14px rgb(193 40 46 / 14%);
  outline: none;
  transform: translateY(-1px);
}

.dream-runtime-meta {
  min-width: 0;
}

.dream-action-progress-list {
  display: grid;
  overflow-x: auto;
}

.dream-action-progress {
  display: grid;
  grid-template-columns:
    minmax(220px, 1.4fr) minmax(140px, 2fr) max-content
    minmax(72px, max-content);
  grid-template-areas: "label progress value states";
  gap: 12px;
  align-items: center;
  min-width: 620px;
  min-height: 36px;
  padding: 6px 0;
  border-bottom: 1px solid rgb(117 117 117 / 18%);
}

.dream-action-progress:last-child {
  border-bottom: 0;
}

.dream-action-progress--current {
  font-weight: 500;
}

.dream-action-label {
  grid-area: label;
  min-width: 0;
}

.dream-action-bar {
  grid-area: progress;
}

.dream-action-progress-value {
  grid-area: value;
  width: 16ch;
  min-width: 16ch;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.dream-action-states {
  grid-area: states;
  min-width: 72px;
}

.dream-action-state {
  display: inline-flex;
  gap: 2px;
  align-items: center;
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.dream-history-card {
  width: 100%;
  overflow: hidden;
}

.dream-history-header {
  padding-bottom: 0;
}

.dream-history-header-row {
  gap: 12px;
}

.dream-history-title {
  flex: 0 0 auto;
}

.dream-history-filters {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.dream-search-filter {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}

.dream-select-filter {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.dream-history-table :deep(.q-table) {
  width: 100%;
  table-layout: fixed;
}

.dream-history-table :deep(.q-table__middle) {
  overflow-x: hidden;
}

.dream-mechanism-label {
  overflow-wrap: anywhere;
  line-height: 1.3;
  white-space: normal;
}

.dream-subject-preview {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dream-history-item {
  width: 100%;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.dream-history-item:hover,
.dream-history-item:focus-visible {
  border-color: var(--q-primary);
  background: color-mix(in srgb, var(--q-primary) 5%, transparent);
  outline: none;
}

.dream-history-item-subject {
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.dream-history-item-result {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.q-table tbody tr) {
  cursor: pointer;
}

.dream-detail-card {
  width: 900px;
  max-width: 96vw;
  max-height: 94vh;
  overflow-y: auto;
}

@media (max-width: 760px) {
  .dream-history-header-row,
  .dream-history-filters {
    flex-wrap: wrap;
  }

  .dream-history-filters,
  .dream-search-filter,
  .dream-select-filter {
    width: 100%;
    max-width: none;
  }
}

@media (max-width: 1023.98px) {
  .dream-action-progress-list {
    overflow-x: visible;
  }

  .dream-action-progress {
    grid-template-columns: minmax(0, 1fr) max-content max-content;
    grid-template-areas:
      "label value states"
      "progress progress progress";
    gap: 4px 8px;
    min-width: 0;
    min-height: 0;
    padding: 5px 0;
  }

  .dream-action-label {
    font-size: 0.75rem;
  }

  .dream-action-label :deep(.q-icon) {
    font-size: 15px !important;
  }

  .dream-action-label .text-body2,
  .dream-action-progress-value,
  .dream-action-state {
    font-size: 0.7rem;
    line-height: 1.15;
  }

  .dream-action-bar {
    font-size: 5px !important;
  }

  .dream-action-states {
    min-width: 72px;
    gap: 4px;
  }
}
</style>
