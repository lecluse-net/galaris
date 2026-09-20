<template>
  <div>
    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error" /></template>
      {{ error }}
    </q-banner>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="metric in metrics" :key="metric.key" class="col-6 col-md-3">
        <q-card
          flat
          bordered
          class="full-height conversation-metric-card"
          :class="{
            'conversation-metric-card--interactive': metric.key !== 'running',
            'conversation-metric-card--active': isMetricActive(metric),
          }"
          :role="metric.key !== 'running' ? 'button' : undefined"
          :tabindex="metric.key !== 'running' ? 0 : undefined"
          :aria-pressed="metric.key !== 'running' ? isMetricActive(metric) : undefined"
          @click="metric.key !== 'running' && toggleMetric(metric)"
          @keydown.enter.prevent="metric.key !== 'running' && toggleMetric(metric)"
          @keydown.space.prevent="metric.key !== 'running' && toggleMetric(metric)"
        >
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md conversation-metric-content">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <q-skeleton v-if="loading && !messages.length" type="text" width="48px" height="32px" />
              <div v-else class="text-h5 text-weight-medium">{{ metric.value }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <q-card class="conversation-history-card">
      <q-card-section>
        <div class="row items-center justify-between no-wrap conversation-history-header-row">
          <div class="row items-center no-wrap conversation-history-title">
            <q-icon name="history" size="sm" class="q-mr-sm" />
            <span class="text-subtitle1">
              {{ t('executionMonitoring.history', { count: pagination.rowsNumber }) }}
            </span>
          </div>
          <div class="row items-center conversation-history-filters">
            <q-input
              v-model="search"
              outlined
              dense
              clearable
              debounce="300"
              :label="t('conversation.history.messageSearch')"
              class="conversation-search-filter"
              @update:model-value="filtersChanged"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
            <AgentSelect
              v-model="agentFilter"
              outlined
              dense
              emit-value
              map-options
              :label="t('conversation.history.agentFilter')"
              :options="agentOptions"
              class="conversation-agent-filter"
              @update:model-value="filtersChanged"
            />
            <TopicSelect
              v-model="topicFilter"
              :allow-create="false"
              :label="t('topic.filter')"
              dense
              outlined
              class="conversation-topic-filter"
              @update:model-value="filtersChanged"
            />
            <q-select
              v-model="statusFilter"
              outlined
              dense
              emit-value
              map-options
              :label="t('conversation.history.statusFilter')"
              :options="statusOptions"
              class="conversation-status-filter"
              @update:model-value="statusFilterChanged"
            />
            <ExecutionDateFilters
              v-model:date-from="dateFrom"
              v-model:date-to="dateTo"
              @change="filtersChanged"
            />
          </div>
        </div>
      </q-card-section>

      <q-separator />

      <q-table
        v-model:pagination="pagination"
        flat
        row-key="id"
        :rows="messages"
        :columns="columns"
        :loading="loading"
        :grid="$q.screen.lt.md"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :no-data-label="t('conversation.history.noMessages')"
        class="conversation-table"
        @request="onRequest"
      >
        <template #body="props">
          <q-tr
            :props="props"
            class="conversation-message-row"
            tabindex="0"
            @click="openDetail(props.row)"
            @keydown.enter.prevent="openDetail(props.row)"
            @keydown.space.prevent="openDetail(props.row)"
          >
            <q-td key="created_at" :props="props">
              <div class="ellipsis">{{ formatDate(props.row.created_at) }}</div>
              <div class="text-caption text-grey-7 ellipsis">{{ senderName(props.row.payload) }}</div>
            </q-td>
            <q-td key="agent" :props="props">
              <div class="row items-center no-wrap">
                <AgentAvatar
                  :agent-id="props.row.agent_id"
                  :name="props.row.agent_name || ''"
                  size="36px"
                />
                <div class="q-ml-sm ellipsis text-weight-medium">{{ agentName(props.row) }}</div>
              </div>
            </q-td>
            <q-td key="conversation" :props="props">
              <div class="ellipsis">{{ props.row.channel_kind }}</div>
              <div class="text-caption text-grey-7 ellipsis">{{ props.row.room_id }}</div>
            </q-td>
            <q-td key="exchange" :props="props" class="conversation-detail-cell">
              <div v-if="props.row.topic_id" class="topic-line">
                <TopicBadge
                  :topic-id="props.row.topic_id"
                  :title="topicTitle(props.row.topic_id)"
                  :subject-kind="props.row.round_id ? 'conversation_round' : 'message'"
                  :subject-id="props.row.round_id || props.row.id"
                />
              </div>
              <div class="exchange-line ellipsis">{{ messageText(props.row.payload) }}</div>
              <div class="exchange-line exchange-line--response ellipsis">
                <WaitingResponseIndicator
                  v-if="isMessageAwaitingResponse(props.row)"
                  :label="t('conversation.history.waitingResponse')"
                  size="22px"
                />
                <template v-else>{{ responsePreview(props.row) }}</template>
              </div>
            </q-td>
            <q-td key="status" :props="props">
              <StatusBadge
                :tone="messageStatusTone(props.row)"
                :label="messageStatusLabel(props.row)"
              />
              <div
                v-if="props.row.aggregated_message_count > 1"
                class="text-caption text-primary ellipsis q-mt-xs"
              >
                {{ t('conversation.history.aggregatedShort', {
                  count: props.row.aggregated_message_count,
                }) }}
              </div>
            </q-td>
          </q-tr>
        </template>
        <template #item="props">
          <div class="q-table__grid-item col-12">
            <q-card
              flat
              bordered
              class="conversation-mobile-card"
              role="button"
              tabindex="0"
              @click="openDetail(props.row)"
              @keydown.enter.prevent="openDetail(props.row)"
              @keydown.space.prevent="openDetail(props.row)"
            >
              <q-card-section class="q-pa-md">
                <div class="row items-start no-wrap q-gutter-sm">
                  <AgentAvatar
                    :agent-id="props.row.agent_id"
                    :name="props.row.agent_name || ''"
                    size="40px"
                  />
                  <div class="col conversation-mobile-heading">
                    <div class="text-weight-medium ellipsis">{{ agentName(props.row) }}</div>
                    <div class="text-caption text-grey-7 ellipsis">
                      {{ formatDate(props.row.created_at) }} · {{ senderName(props.row.payload) }}
                    </div>
                  </div>
                  <StatusBadge
                    :tone="messageStatusTone(props.row)"
                    :label="messageStatusLabel(props.row)"
                  />
                </div>

                <div class="conversation-mobile-room q-mt-sm">
                  <q-icon name="forum" color="grey-7" size="16px" />
                  <span class="ellipsis">{{ props.row.channel_kind }} · {{ props.row.room_id }}</span>
                </div>

                <div v-if="props.row.topic_id" class="topic-line q-mt-sm">
                  <TopicBadge
                    :topic-id="props.row.topic_id"
                    :title="topicTitle(props.row.topic_id)"
                    :subject-kind="props.row.round_id ? 'conversation_round' : 'message'"
                    :subject-id="props.row.round_id || props.row.id"
                  />
                </div>

                <div class="conversation-mobile-exchange q-mt-sm">
                  <div class="conversation-mobile-exchange-label">
                    {{ t('conversation.history.detail.request') }}
                  </div>
                  <div class="conversation-mobile-exchange-text">
                    {{ messageText(props.row.payload) }}
                  </div>
                </div>
                <div class="conversation-mobile-exchange conversation-mobile-exchange--response">
                  <div class="conversation-mobile-exchange-label">
                    {{ t('conversation.history.detail.response') }}
                  </div>
                  <WaitingResponseIndicator
                    v-if="isMessageAwaitingResponse(props.row)"
                    :label="t('conversation.history.waitingResponse')"
                    size="22px"
                  />
                  <div v-else class="conversation-mobile-exchange-text">
                    {{ responsePreview(props.row) }}
                  </div>
                </div>

                <div
                  v-if="props.row.aggregated_message_count > 1"
                  class="text-caption text-primary q-mt-sm"
                >
                  {{ t('conversation.history.aggregatedShort', {
                    count: props.row.aggregated_message_count,
                  }) }}
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <ConversationTurnDialog
      v-model="detailOpen"
      icon="forum"
      :title="detailTitle"
      :close-label="t('conversation.history.detail.close')"
    >
      <ConversationRoundDetail
        v-if="selectedMessage"
        :message="selectedMessage"
        :round="selectedRound"
        :calls="selectedCalls"
        :loading="detailLoading"
        :error="detailError"
        :calls-loading="callsLoading"
        :calls-error="callsError"
        @deleted="onRoundDeleted"
        @topic-updated="onRoundTopicUpdated"
        @delivery-resolved="onRoundTopicUpdated"
      />
    </ConversationTurnDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInterval, type QTableColumn, type QTableProps } from 'quasar'
import AgentAvatar from '@/app/agent/components/AgentAvatar.vue'
import { AgentSelect } from '@/app/agent'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import type { LLMCall } from '@/app/llm/types'
import ConversationTurnDialog from '@/core/util/components/ConversationTurnDialog.vue'
import WaitingResponseIndicator from '@/core/util/components/WaitingResponseIndicator.vue'
import { ExecutionDateFilters, StatusBadge, type StatusBadgeTone } from '@/core/util'
import ConversationRoundDetail from './ConversationRoundDetail.vue'
import { conversationService } from '../services/conversationService'
import type {
  ConversationMessage,
  ConversationRoundDetail as ConversationRoundDetailData,
  ConversationStatus,
  ConversationStatusOverview,
} from '../types'
import TopicBadge from '@/app/topic/components/TopicBadge.vue'
import { useTopicRefs } from '@/app/topic/composables/useTopicRefs'
import TopicSelect from '@/app/topic/components/TopicSelect.vue'

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]
type ConversationMetricKey = 'idle' | 'ready' | 'running' | 'errors'
interface ConversationMetric {
  key: ConversationMetricKey
  status: ConversationStatus | null
  label: string
  value: number
  icon: string
  color: string
}

const { t, te, locale } = useI18n()
const { registerInterval } = useInterval()
const agentStore = useAgentStore()
const messages = ref<ConversationMessage[]>([])
const loading = ref(false)
const error = ref('')
const search = ref('')
const agentFilter = ref<number | null>(null)
const statusFilter = ref<ConversationStatus | null>(null)
const topicFilter = ref<string | null>(null)
const errorsOnly = ref(false)
const dateFrom = ref<string | null>(null)
const dateTo = ref<string | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const summary = ref<ConversationStatusOverview>({ idle: 0, ready: 0, running: 0, errors: 0 })
const detailOpen = ref(false)
const selectedMessage = ref<ConversationMessage | null>(null)
const selectedRound = ref<ConversationRoundDetailData | null>(null)
const selectedCalls = ref<LLMCall[]>([])
const detailLoading = ref(false)
const detailError = ref('')
const callsLoading = ref(false)
const callsError = ref('')
let listRequest = 0
let roundRequest = 0
let callsRequest = 0
const { resolveTopicRefs, topicTitle } = useTopicRefs()

const columns = computed<QTableColumn<ConversationMessage>[]>(() => [
  { name: 'created_at', label: t('conversation.history.receivedAt'), field: 'created_at', align: 'left', classes: 'gt-xs', headerClasses: 'gt-xs', style: 'width: 165px', headerStyle: 'width: 165px' },
  { name: 'agent', label: t('conversation.history.agent'), field: 'agent_name', align: 'left', style: 'width: 205px', headerStyle: 'width: 205px' },
  { name: 'conversation', label: t('conversation.history.room'), field: 'room_id', align: 'left', classes: 'gt-sm', headerClasses: 'gt-sm', style: 'width: 190px', headerStyle: 'width: 190px' },
  { name: 'exchange', label: t('conversation.history.exchange'), field: row => messageText(row.payload), align: 'left' },
  { name: 'status', label: t('conversation.history.status'), field: 'round_status', align: 'left', style: 'width: 130px', headerStyle: 'width: 130px' },
])

const agentOptions = computed(() => [
  { label: t('conversation.history.allAgents'), value: null },
  ...agentStore.sortedAgents.map(agent => ({
    label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
    value: agent.id,
  })),
])
const statusOptions = computed(() => [
  { label: t('conversation.history.allStatuses'), value: null },
  ...(['IDLE', 'READY'] as ConversationStatus[]).map(status => ({
    label: t(`conversation.history.statuses.${status}`),
    value: status,
  })),
])
const metrics = computed<ConversationMetric[]>(() => [
  { key: 'idle', status: 'IDLE', label: t('conversation.history.metrics.idle'), value: summary.value.idle, icon: 'check_circle', color: 'positive' },
  { key: 'ready', status: 'READY', label: t('conversation.history.metrics.ready'), value: summary.value.ready, icon: 'schedule', color: 'warning' },
  { key: 'running', status: 'RUNNING', label: t('conversation.history.metrics.running'), value: summary.value.running, icon: 'motion_photos_on', color: 'primary' },
  { key: 'errors', status: null, label: t('conversation.history.metrics.errors'), value: summary.value.errors, icon: 'error', color: 'negative' },
])
const detailTitle = computed(() => t('conversation.history.detail.turn'))

onMounted(() => {
  if (!agentStore.agents.length) void agentStore.fetchAgents()
  void refresh()
  registerInterval(() => {
    void refresh(false)
    if (detailOpen.value && selectedMessage.value?.round_id && selectedRoundIsActive()) {
      void refreshSelectedRound(false)
      void refreshSelectedCalls(false)
    }
  }, 3000)
})

async function refresh(showLoading = true): Promise<void> {
  const request = ++listRequest
  if (showLoading) {
    loading.value = true
    error.value = ''
  }
  try {
    const page = await conversationService.listMessages({
      page: pagination.value.page,
      pageSize: pagination.value.rowsPerPage,
      agentId: agentFilter.value,
      status: statusFilter.value,
      topicId: topicFilter.value,
      search: search.value,
      errorsOnly: errorsOnly.value,
      dateFrom: dateFrom.value,
      dateTo: dateTo.value,
    })
    if (request !== listRequest) return
    messages.value = page.items
    void resolveTopicRefs(page.items.map(item => item.topic_id))
    summary.value = page.summary
    pagination.value = { page: page.page, rowsPerPage: page.page_size, rowsNumber: page.total }
    const refreshedSelection = page.items.find(item => item.id === selectedMessage.value?.id)
    if (refreshedSelection) selectedMessage.value = refreshedSelection
  } catch (reason) {
    if (showLoading && request === listRequest) {
      error.value = reason instanceof Error ? reason.message : t('conversation.history.loadError')
    }
  } finally {
    if (request === listRequest) loading.value = false
  }
}

function filtersChanged(): void {
  pagination.value.page = 1
  void refresh()
}

function statusFilterChanged(): void {
  errorsOnly.value = false
  filtersChanged()
}

function isMetricActive(metric: ConversationMetric): boolean {
  if (metric.key === 'running') return false
  return metric.key === 'errors'
    ? errorsOnly.value
    : !errorsOnly.value && statusFilter.value === metric.status
}

function toggleMetric(metric: ConversationMetric): void {
  if (metric.key === 'errors') {
    errorsOnly.value = !errorsOnly.value
    statusFilter.value = null
  } else {
    errorsOnly.value = false
    statusFilter.value = statusFilter.value === metric.status ? null : metric.status
  }
  filtersChanged()
}

function onRequest(request: TableRequest): void {
  pagination.value = { ...request.pagination, rowsNumber: request.pagination.rowsNumber ?? pagination.value.rowsNumber }
  void refresh()
}

async function openDetail(message: ConversationMessage): Promise<void> {
  selectedMessage.value = message
  selectedRound.value = null
  selectedCalls.value = []
  detailError.value = ''
  callsError.value = ''
  detailOpen.value = true
  if (!message.round_id) {
    detailLoading.value = false
    callsLoading.value = false
    return
  }
  void refreshSelectedRound(true)
  void refreshSelectedCalls(true)
}

function selectedRoundIsActive(): boolean {
  const statuses = [selectedRound.value?.status, selectedMessage.value?.round_status]
    .filter((status): status is string => Boolean(status))
  return statuses.length > 0
    && statuses.every(status => ['FROZEN', 'CLAIMED', 'RUNNING'].includes(status))
}

async function refreshSelectedRound(showLoading: boolean): Promise<void> {
  const roundId = selectedMessage.value?.round_id
  if (!roundId) return
  const request = ++roundRequest
  if (showLoading) detailLoading.value = true
  try {
    const round = await conversationService.getRound(roundId)
    if (
      request === roundRequest
      && detailOpen.value
      && selectedMessage.value?.round_id === roundId
    ) {
      selectedRound.value = round
      detailError.value = ''
    }
  } catch (reason) {
    if (
      showLoading
      && request === roundRequest
      && selectedMessage.value?.round_id === roundId
    ) {
      detailError.value = reason instanceof Error
        ? reason.message
        : t('conversation.history.detail.loadError')
    }
  } finally {
    if (request === roundRequest) detailLoading.value = false
  }
}

async function refreshSelectedCalls(showLoading: boolean): Promise<void> {
  const roundId = selectedMessage.value?.round_id
  if (!roundId) return
  const request = ++callsRequest
  if (showLoading) callsLoading.value = true
  try {
    const calls = await conversationService.llmCalls(roundId)
    if (
      request === callsRequest
      && detailOpen.value
      && selectedMessage.value?.round_id === roundId
    ) {
      selectedCalls.value = calls
      callsError.value = ''
    }
  } catch (reason) {
    if (
      showLoading
      && request === callsRequest
      && selectedMessage.value?.round_id === roundId
    ) {
      callsError.value = reason instanceof Error
        ? reason.message
        : t('conversation.history.detail.llmLoadError')
    }
  } finally {
    if (request === callsRequest) callsLoading.value = false
  }
}

async function onRoundDeleted(): Promise<void> {
  detailOpen.value = false
  selectedMessage.value = null
  selectedRound.value = null
  selectedCalls.value = []
  await refresh()
}

function onRoundTopicUpdated(round: ConversationRoundDetailData): void {
  selectedRound.value = round
  messages.value = messages.value.map(message => (
    message.round_id === round.id ? { ...message, topic_id: round.topic_id } : message
  ))
  if (selectedMessage.value?.round_id === round.id) {
    selectedMessage.value = { ...selectedMessage.value, topic_id: round.topic_id }
  }
  void resolveTopicRefs([round.topic_id])
}

function agentName(message: ConversationMessage): string {
  return message.agent_name?.trim()
    || t('conversation.history.unknownAgent', { id: message.agent_id })
}

function senderName(payload: Record<string, unknown>): string {
  const sender = payload.sender
  if (!sender || typeof sender !== 'object') return t('conversation.history.detail.user')
  const data = sender as Record<string, unknown>
  const name = String(data.display_name || data.id || '').trim()
  return name || t('conversation.history.detail.user')
}

function messageText(payload: Record<string, unknown>): string {
  const text = String(payload.text || '').trim()
  return text || t('conversation.history.detail.nonTextMessage')
}

function responsePreview(message: ConversationMessage): string {
  return message.response_text?.trim()
    || message.response_error?.trim()
    || (message.round_id
      ? t('conversation.history.detail.noResponse')
      : t('conversation.history.responsePending'))
}

function isMessageAwaitingResponse(message: ConversationMessage): boolean {
  return ['FROZEN', 'CLAIMED', 'RUNNING'].includes(message.round_status || '')
    && !message.response_text?.trim()
    && !message.response_error?.trim()
}

function messageStatusLabel(message: ConversationMessage): string {
  if (!message.round_status) return t('conversation.history.detail.pending')
  const key = `conversation.history.detail.roundStatuses.${message.round_status}`
  return te(key) ? t(key) : message.round_status
}

function messageStatusTone(message: ConversationMessage): StatusBadgeTone {
  if (!message.round_status) return 'warning'
  if (['SUCCEEDED', 'COMPLETED'].includes(message.round_status)) return 'success'
  if (['RUNNING', 'CLAIMED'].includes(message.round_status)) return 'active'
  if (message.round_status === 'FROZEN') return 'warning'
  if (['SUPERSEDED', 'CANCELLED'].includes(message.round_status)) return 'neutral'
  if (message.round_status === 'INTERRUPTED') return 'warning'
  return 'error'
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
</script>

<style scoped>
.conversation-metric-card {
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.conversation-metric-card--interactive {
  cursor: pointer;
}

.conversation-metric-card--interactive:hover,
.conversation-metric-card--interactive:focus-visible,
.conversation-metric-card--active {
  border-color: var(--q-primary);
  box-shadow: 0 4px 14px rgb(25 118 210 / 16%);
  outline: none;
  transform: translateY(-1px);
}

.conversation-metric-content,
.conversation-mobile-heading {
  min-width: 0;
}

.conversation-history-header-row {
  gap: 12px;
}

.conversation-history-title {
  flex: 0 0 auto;
}

.conversation-history-filters {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.conversation-search-filter {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}

.conversation-agent-filter {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.conversation-status-filter {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.conversation-topic-filter {
  flex: 0 1 220px;
  width: 220px;
  min-width: 150px;
  max-width: 220px;
}

.conversation-history-card {
  width: 100%;
  overflow: hidden;
}

.conversation-table :deep(.q-table__middle) {
  overflow-x: hidden;
}

.conversation-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.conversation-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 12px;
}

.conversation-table :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.conversation-table :deep(th),
.conversation-table :deep(td) {
  min-width: 0;
  overflow: hidden;
}

.conversation-table :deep(.conversation-message-row) {
  cursor: pointer;
}

.conversation-table :deep(.conversation-message-row > td) {
  vertical-align: middle;
  padding-block: 12px;
}

.conversation-table :deep(.conversation-message-row > .conversation-detail-cell) {
  padding-block: 3px;
}

.conversation-table :deep(.conversation-message-row:hover),
.conversation-table :deep(.conversation-message-row:focus-visible) {
  background: rgb(25 118 210 / 6%);
  outline: none;
}

.conversation-mobile-card {
  min-width: 0;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.conversation-mobile-card:hover,
.conversation-mobile-card:focus-visible {
  border-color: var(--q-primary);
  box-shadow: 0 3px 12px rgb(25 118 210 / 14%);
  outline: none;
}

.conversation-mobile-room {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: #616161;
  font-size: 0.75rem;
}

.conversation-mobile-exchange {
  min-width: 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f5f7fa;
}

.conversation-mobile-exchange--response {
  margin-top: 6px;
  background: #edf7ee;
}

.conversation-mobile-exchange-label {
  margin-bottom: 2px;
  color: #757575;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.conversation-mobile-exchange-text {
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

body.body--dark .conversation-mobile-room {
  color: #bdbdbd;
}

body.body--dark .conversation-mobile-exchange {
  background: #252a31;
}

body.body--dark .conversation-mobile-exchange--response {
  background: #203126;
}

.topic-line {
  display: flex;
  min-width: 0;
  margin-bottom: 2px;
}

.exchange-line {
  min-width: 0;
  line-height: 1.3;
}

.exchange-line--response {
  color: #616161;
}

body.body--dark .exchange-line--response {
  color: #bdbdbd;
}

@media (max-width: 1023px) {
  .conversation-history-header-row {
    flex-wrap: wrap;
  }

  .conversation-history-title,
  .conversation-history-filters {
    width: 100%;
  }

  .conversation-history-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .conversation-search-filter,
  .conversation-agent-filter,
  .conversation-status-filter,
  .conversation-topic-filter {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .conversation-search-filter,
  .conversation-history-filters :deep(.execution-date-filters) {
    grid-column: 1 / -1;
  }

  .conversation-history-filters :deep(.execution-date-filters) {
    justify-content: stretch;
  }
}

@media (max-width: 599px) {
  .conversation-history-filters {
    grid-template-columns: minmax(0, 1fr);
  }

  .conversation-search-filter,
  .conversation-history-filters :deep(.execution-date-filters) {
    grid-column: auto;
  }

  .conversation-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .conversation-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .conversation-metric-content {
    margin-left: 8px;
  }

  .conversation-table :deep(.q-table__grid-item) {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
