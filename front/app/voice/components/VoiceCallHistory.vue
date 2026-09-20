<template>
  <div>
    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error" /></template>
      {{ error }}
    </q-banner>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="metric in callMetrics" :key="metric.status" class="col-6 col-md-3">
        <q-card
          flat
          bordered
          class="full-height voice-metric-card"
          :class="{
            'voice-metric-card--interactive': metric.status !== 'ACTIVE',
            'voice-metric-card--active': statusFilter === metric.status,
          }"
          :role="metric.status !== 'ACTIVE' ? 'button' : undefined"
          :tabindex="metric.status !== 'ACTIVE' ? 0 : undefined"
          :aria-pressed="metric.status !== 'ACTIVE' ? statusFilter === metric.status : undefined"
          @click="metric.status !== 'ACTIVE' && toggleStatusFilter(metric.status)"
          @keydown.enter.prevent="metric.status !== 'ACTIVE' && toggleStatusFilter(metric.status)"
          @keydown.space.prevent="metric.status !== 'ACTIVE' && toggleStatusFilter(metric.status)"
        >
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md metric-content">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <q-skeleton v-if="loading && !conversations.length" type="text" width="48px" height="32px" />
              <div v-else class="text-h5 text-weight-medium">{{ metric.value }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <q-card class="voice-history-card">
      <q-card-section>
        <div class="row items-center justify-between no-wrap voice-history-header-row">
          <div class="row items-center no-wrap voice-history-title">
            <q-icon name="history" size="sm" class="q-mr-sm" />
            <span class="text-subtitle1">
              {{ t('executionMonitoring.history', { count: pagination.rowsNumber }) }}
            </span>
          </div>
          <div class="row items-center voice-history-filters">
            <q-input
              v-model="search"
              outlined
              dense
              clearable
              debounce="300"
              :label="t('voice.history.search')"
              class="voice-search-filter"
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
              :label="t('voice.history.agentFilter')"
              :options="agentOptions"
              class="voice-agent-filter"
              @update:model-value="filtersChanged"
            />
            <TopicSelect
              v-model="topicFilter"
              :allow-create="false"
              :label="t('topic.filter')"
              dense
              outlined
              class="voice-topic-filter"
              @update:model-value="filtersChanged"
            />
            <q-select
              v-model="statusFilter"
              outlined
              dense
              emit-value
              map-options
              :label="t('voice.history.statusFilter')"
              :options="statusOptions"
              class="voice-status-filter"
              @update:model-value="filtersChanged"
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
        :rows="conversations"
        :columns="columns"
        :loading="loading"
        :grid="$q.screen.lt.md"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :no-data-label="t('voice.history.noRows')"
        class="voice-history-table"
        @request="onRequest"
      >
        <template #body="props">
          <q-tr :props="props" class="voice-call-row">
            <q-td key="date" :props="props">
              <div class="ellipsis">{{ formatDate(props.row.started_at) }}</div>
              <div class="text-caption text-grey-7 ellipsis">
                {{ formatDuration(props.row.duration) }}
              </div>
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
            <q-td key="exchange" :props="props" class="voice-detail-cell">
              <div v-if="props.row.topic_id" class="topic-line">
                <TopicBadge
                  :topic-id="props.row.topic_id"
                  :title="topicTitle(props.row.topic_id)"
                  subject-kind="voice_session"
                  :subject-id="props.row.id"
                />
              </div>
              <div class="row items-center no-wrap text-weight-medium">
                <q-icon name="phone_in_talk" color="primary" size="18px" class="q-mr-xs" />
                <span class="ellipsis">{{ t('voice.history.callSummary', { count: props.row.turn_count }) }}</span>
              </div>
              <div class="text-caption text-grey-7 ellipsis">{{ props.row.room_id }}</div>
            </q-td>
            <q-td key="channel" :props="props">
              <div class="ellipsis">{{ transportLabel(props.row.transport_kind) }}</div>
              <div v-if="props.row.error" class="text-caption text-negative ellipsis">
                {{ props.row.error }}
              </div>
            </q-td>
            <q-td key="status" :props="props">
              <StatusBadge
                :tone="statusTone(props.row.status)"
                :label="t(`voice.history.statuses.${props.row.status}`)"
              />
              <div v-if="props.row.interrupted_count || props.row.failed_count" class="q-mt-xs">
                <StatusBadge
                  v-if="props.row.interrupted_count"
                  tone="warning"
                  :label="`${props.row.interrupted_count} ×`"
                  icon="mic_off"
                  class="q-mr-xs"
                />
                <StatusBadge
                  v-if="props.row.failed_count"
                  tone="error"
                  :label="`${props.row.failed_count} ×`"
                  icon="error"
                />
              </div>
            </q-td>
          </q-tr>

          <q-tr
            v-for="turn in props.row.turns"
            :key="turn.id"
            :props="props"
            class="voice-turn-row"
            tabindex="0"
            @click="openTurn(props.row, turn)"
            @keydown.enter.prevent="openTurn(props.row, turn)"
            @keydown.space.prevent="openTurn(props.row, turn)"
          >
            <q-td key="date" :props="props">
              <div class="ellipsis">{{ formatDate(turn.started_at) }}</div>
            </q-td>
            <q-td key="agent" :props="props">
              <div class="row items-center no-wrap voice-turn-indent">
                <q-icon name="subdirectory_arrow_right" color="grey-6" size="20px" />
                <span class="q-ml-xs text-weight-medium ellipsis">
                  {{ t('voice.history.turnLabel', { sequence: turn.sequence }) }}
                </span>
              </div>
            </q-td>
            <q-td key="exchange" :props="props" class="voice-detail-cell">
              <div v-if="turn.topic_id" class="topic-line">
                <TopicBadge
                  :topic-id="turn.topic_id"
                  :title="topicTitle(turn.topic_id)"
                  subject-kind="conversation_round"
                  :subject-id="turn.id"
                />
              </div>
              <div class="exchange-line ellipsis">{{ turnTranscriptPreview(turn) }}</div>
              <div class="exchange-line exchange-line--response ellipsis">
                <WaitingResponseIndicator
                  v-if="isTurnAwaitingResponse(turn)"
                  :label="t('voice.history.waitingResponse')"
                  color="warning"
                  size="22px"
                />
                <template v-else>{{ turnResponsePreview(turn) }}</template>
              </div>
            </q-td>
            <q-td key="channel" :props="props">
              <div class="text-caption text-grey-7 ellipsis">
                <q-icon name="memory" size="14px" class="q-mr-xs" />
                {{ t('voice.history.detail.llmCalls', { count: turn.llm_call_count }) }}
              </div>
            </q-td>
            <q-td key="status" :props="props">
              <StatusBadge
                :tone="turnStatusTone(turn.status)"
                :label="t(`voice.history.turnStatuses.${turn.status}`)"
              />
            </q-td>
          </q-tr>
        </template>
        <template #item="props">
          <div class="q-table__grid-item col-12">
            <q-card flat bordered class="voice-mobile-card">
              <q-card-section class="q-pa-md">
                <div class="row items-start no-wrap q-gutter-sm">
                  <AgentAvatar
                    :agent-id="props.row.agent_id"
                    :name="props.row.agent_name || ''"
                    size="40px"
                  />
                  <div class="col voice-mobile-heading">
                    <div class="text-weight-medium ellipsis">{{ agentName(props.row) }}</div>
                    <div class="text-caption text-grey-7 ellipsis">
                      {{ formatDate(props.row.started_at) }} · {{ formatDuration(props.row.duration) }}
                    </div>
                  </div>
                  <StatusBadge
                    :tone="statusTone(props.row.status)"
                    :label="t(`voice.history.statuses.${props.row.status}`)"
                  />
                </div>

                <div class="voice-mobile-room q-mt-sm">
                  <q-icon name="phone_in_talk" color="primary" size="18px" />
                  <span class="ellipsis">
                    {{ t('voice.history.callSummary', { count: props.row.turn_count }) }}
                    · {{ props.row.room_id }}
                  </span>
                </div>
                <div class="text-caption text-grey-7 q-mt-xs">
                  {{ transportLabel(props.row.transport_kind) }}
                </div>

                <div v-if="props.row.topic_id" class="topic-line q-mt-sm">
                  <TopicBadge
                    :topic-id="props.row.topic_id"
                    :title="topicTitle(props.row.topic_id)"
                    subject-kind="voice_session"
                    :subject-id="props.row.id"
                  />
                </div>

                <div
                  v-if="props.row.interrupted_count || props.row.failed_count"
                  class="row q-gutter-xs q-mt-sm"
                >
                  <StatusBadge
                    v-if="props.row.interrupted_count"
                    tone="warning"
                    :label="t('voice.history.interruptedCount', { count: props.row.interrupted_count })"
                  />
                  <StatusBadge
                    v-if="props.row.failed_count"
                    tone="error"
                    :label="t('voice.history.failedCount', { count: props.row.failed_count })"
                  />
                </div>
                <div v-if="props.row.error" class="text-caption text-negative q-mt-sm">
                  {{ props.row.error }}
                </div>
              </q-card-section>

              <q-separator v-if="props.row.turns.length" />
              <q-list v-if="props.row.turns.length" separator>
                <q-item
                  v-for="turn in props.row.turns"
                  :key="turn.id"
                  clickable
                  class="voice-mobile-turn"
                  @click="openTurn(props.row, turn)"
                  @keydown.enter.prevent="openTurn(props.row, turn)"
                  @keydown.space.prevent="openTurn(props.row, turn)"
                >
                  <q-item-section>
                    <q-item-label class="row items-center no-wrap q-gutter-xs">
                      <q-icon name="subdirectory_arrow_right" color="primary" size="18px" />
                      <span class="text-weight-medium">
                        {{ t('voice.history.turnLabel', { sequence: turn.sequence }) }}
                      </span>
                      <q-space />
                      <StatusBadge
                        :tone="turnStatusTone(turn.status)"
                        :label="t(`voice.history.turnStatuses.${turn.status}`)"
                      />
                    </q-item-label>
                    <div v-if="turn.topic_id" class="topic-line q-mt-xs">
                      <TopicBadge
                        :topic-id="turn.topic_id"
                        :title="topicTitle(turn.topic_id)"
                        subject-kind="conversation_round"
                        :subject-id="turn.id"
                      />
                    </div>
                    <q-item-label caption class="voice-mobile-preview q-mt-xs">
                      {{ turnTranscriptPreview(turn) }}
                    </q-item-label>
                    <q-item-label caption class="voice-mobile-preview voice-mobile-preview--response">
                      <WaitingResponseIndicator
                        v-if="isTurnAwaitingResponse(turn)"
                        :label="t('voice.history.waitingResponse')"
                        color="warning"
                        size="22px"
                      />
                      <template v-else>{{ turnResponsePreview(turn) }}</template>
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <ConversationTurnDialog
      v-model="turnDialogOpen"
      icon="record_voice_over"
      :title="selectedTurn
        ? t('voice.history.detail.turnTitle', { sequence: selectedTurn.sequence })
        : t('voice.history.detail.title')"
      :close-label="t('voice.history.detail.close')"
    >
      <VoiceConversationDetail
        v-if="selectedConversation && selectedTurn"
        :conversation="selectedConversation"
        :turn="selectedTurn"
        @deleted="onTurnDeleted"
        @topic-updated="onTurnTopicUpdated"
      />
    </ConversationTurnDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn, QTableProps } from 'quasar'
import AgentAvatar from '@/app/agent/components/AgentAvatar.vue'
import { AgentSelect } from '@/app/agent'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { websocket } from '@/core/websocket'
import ConversationTurnDialog from '@/core/util/components/ConversationTurnDialog.vue'
import WaitingResponseIndicator from '@/core/util/components/WaitingResponseIndicator.vue'
import { ExecutionDateFilters, StatusBadge, type StatusBadgeTone } from '@/core/util'
import VoiceConversationDetail from './VoiceConversationDetail.vue'
import { voiceConversationService } from '../services/voiceConversationService'
import type {
  VoiceConversationDetail as VoiceConversationDetailData,
  VoiceConversationOverview,
  VoiceConversationStatus,
  VoiceConversationTurn,
  VoiceTurnStatus,
} from '../types'
import TopicBadge from '@/app/topic/components/TopicBadge.vue'
import { useTopicRefs } from '@/app/topic/composables/useTopicRefs'
import TopicSelect from '@/app/topic/components/TopicSelect.vue'

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

const { t, locale } = useI18n()
const agentStore = useAgentStore()
const conversations = ref<VoiceConversationDetailData[]>([])
const loading = ref(false)
const error = ref('')
const search = ref('')
const agentFilter = ref<number | null>(null)
const statusFilter = ref<VoiceConversationStatus | null>(null)
const topicFilter = ref<string | null>(null)
const dateFrom = ref<string | null>(null)
const dateTo = ref<string | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const summary = ref<VoiceConversationOverview>({ active: 0, completed: 0, cancelled: 0, errors: 0 })
const turnDialogOpen = ref(false)
const selectedConversation = ref<VoiceConversationDetailData | null>(null)
const selectedTurn = ref<VoiceConversationTurn | null>(null)
let realtimeRefreshTimer: ReturnType<typeof setTimeout> | null = null
const { resolveTopicRefs, topicTitle } = useTopicRefs()

const columns = computed<QTableColumn<VoiceConversationDetailData>[]>(() => [
  { name: 'date', label: t('voice.history.date'), field: 'started_at', align: 'left', classes: 'gt-xs', headerClasses: 'gt-xs', style: 'width: 165px', headerStyle: 'width: 165px' },
  { name: 'agent', label: t('voice.history.agent'), field: 'agent_name', align: 'left', style: 'width: 205px', headerStyle: 'width: 205px' },
  { name: 'exchange', label: t('voice.history.exchange'), field: 'room_id', align: 'left' },
  { name: 'channel', label: t('voice.history.channel'), field: 'transport_kind', align: 'left', classes: 'gt-sm', headerClasses: 'gt-sm', style: 'width: 190px', headerStyle: 'width: 190px' },
  { name: 'status', label: t('voice.history.status'), field: 'status', align: 'left', style: 'width: 140px', headerStyle: 'width: 140px' },
])

const agentOptions = computed(() => [
  { label: t('voice.history.allAgents'), value: null },
  ...agentStore.sortedAgents.map(agent => ({
    label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
    value: agent.id,
  })),
])
const statusOptions = computed(() => [
  { label: t('voice.history.allStatuses'), value: null },
  ...(['COMPLETED', 'CANCELLED', 'ERROR'] as VoiceConversationStatus[]).map(status => ({
    label: t(`voice.history.statuses.${status}`),
    value: status,
  })),
])
const callMetrics = computed(() => [
  { status: 'COMPLETED' as const, label: t('voice.history.metrics.completed'), value: summary.value.completed, icon: 'check_circle', color: 'positive' },
  { status: 'CANCELLED' as const, label: t('voice.history.metrics.cancelled'), value: summary.value.cancelled, icon: 'phone_disabled', color: 'grey-7' },
  { status: 'ACTIVE' as const, label: t('voice.history.metrics.active'), value: summary.value.active, icon: 'phone_in_talk', color: 'primary' },
  { status: 'ERROR' as const, label: t('voice.history.metrics.errors'), value: summary.value.errors, icon: 'error', color: 'negative' },
])
async function load(page = pagination.value.page, pageSize = pagination.value.rowsPerPage): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await voiceConversationService.list({
      page,
      pageSize,
      agentId: agentFilter.value,
      status: statusFilter.value,
      topicId: topicFilter.value,
      dateFrom: dateFrom.value,
      dateTo: dateTo.value,
      search: search.value,
    })
    conversations.value = response.items
    void resolveTopicRefs(response.items.flatMap(item => (
      [item.topic_id, ...item.turns.map(turn => turn.topic_id)]
    )))
    summary.value = response.summary
    pagination.value = { page: response.page, rowsPerPage: response.page_size, rowsNumber: response.total }
    const selected = response.items.find(item => item.id === selectedConversation.value?.id)
    if (selected) {
      const turn = selected.turns.find(item => item.id === selectedTurn.value?.id)
      selectedConversation.value = selected
      if (turn) selectedTurn.value = turn
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('voice.history.loadError')
  } finally {
    loading.value = false
  }
}

function filtersChanged(): void {
  turnDialogOpen.value = false
  void load(1, pagination.value.rowsPerPage)
}

function toggleStatusFilter(status: VoiceConversationStatus): void {
  statusFilter.value = statusFilter.value === status ? null : status
  filtersChanged()
}

async function onRequest(request: TableRequest): Promise<void> {
  turnDialogOpen.value = false
  await load(request.pagination.page, request.pagination.rowsPerPage)
}

function openTurn(conversation: VoiceConversationDetailData, turn: VoiceConversationTurn): void {
  selectedConversation.value = conversation
  selectedTurn.value = turn
  turnDialogOpen.value = true
}

async function onTurnDeleted(): Promise<void> {
  turnDialogOpen.value = false
  selectedTurn.value = null
  selectedConversation.value = null
  await load()
}

function onTurnTopicUpdated(updated: VoiceConversationTurn): void {
  const updateConversation = (conversation: VoiceConversationDetailData): VoiceConversationDetailData => {
    if (!conversation.turns.some(turn => turn.id === updated.id)) return conversation
    const turns = conversation.turns.map(turn => turn.id === updated.id
      ? { ...turn, topic_id: updated.topic_id }
      : turn)
    const topicId = [...turns]
      .sort((left, right) => right.sequence - left.sequence)
      .find(turn => turn.topic_id)?.topic_id ?? null
    return { ...conversation, topic_id: topicId, turns }
  }

  conversations.value = conversations.value.map(updateConversation)
  if (selectedConversation.value) {
    selectedConversation.value = updateConversation(selectedConversation.value)
  }
  if (selectedTurn.value?.id === updated.id) {
    selectedTurn.value = { ...selectedTurn.value, topic_id: updated.topic_id }
  }
  void resolveTopicRefs([updated.topic_id])
}

function agentName(conversation: VoiceConversationDetailData): string {
  return conversation.agent_name?.trim()
    || t('voice.history.unknownAgent', { id: conversation.agent_id })
}

function turnTranscriptPreview(turn: VoiceConversationTurn): string {
  return turn.transcript?.trim() || t('voice.history.detail.nativeAudio')
}

function turnResponsePreview(turn: VoiceConversationTurn): string {
  return turn.assistant_response?.trim()
    || turn.error?.trim()
    || t('voice.history.detail.noResponse')
}

function isTurnAwaitingResponse(turn: VoiceConversationTurn): boolean {
  return turn.status === 'RUNNING'
    && !turn.assistant_response?.trim()
    && !turn.error?.trim()
}

function transportLabel(kind: string): string {
  if (kind === 'matrix' || kind === 'nextcloud_talk') return t(`voice.history.transports.${kind}`)
  return kind.replaceAll('_', ' ')
}

function statusTone(status: VoiceConversationStatus): StatusBadgeTone {
  const tones: Record<VoiceConversationStatus, StatusBadgeTone> = {
    ACTIVE: 'active', COMPLETED: 'success', CANCELLED: 'neutral', ERROR: 'error',
  }
  return tones[status]
}

function turnStatusTone(status: VoiceTurnStatus): StatusBadgeTone {
  const tones: Record<VoiceTurnStatus, StatusBadgeTone> = {
    RUNNING: 'active', COMPLETED: 'success', INTERRUPTED: 'warning', FAILED: 'error',
  }
  return tones[status]
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const remaining = Math.round(seconds % 60)
  return `${minutes} min ${remaining.toString().padStart(2, '0')} s`
}

function scheduleRealtimeRefresh(): void {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  realtimeRefreshTimer = setTimeout(() => {
    realtimeRefreshTimer = null
    if (loading.value) return scheduleRealtimeRefresh()
    void load()
  }, 300)
}

onMounted(() => {
  if (!agentStore.agents.length) void agentStore.fetchAgents()
  void load()
  const socket = websocket.createWebsocket()
  socket.on('connect', scheduleRealtimeRefresh)
  websocket.onEvent('voice_conversation', 'create', scheduleRealtimeRefresh)
  websocket.onEvent('voice_conversation', 'update', scheduleRealtimeRefresh)
})

onUnmounted(() => {
  if (realtimeRefreshTimer) clearTimeout(realtimeRefreshTimer)
  websocket.socket?.off('connect', scheduleRealtimeRefresh)
  websocket.offEvent('voice_conversation', 'create', scheduleRealtimeRefresh)
  websocket.offEvent('voice_conversation', 'update', scheduleRealtimeRefresh)
})
</script>

<style scoped>
.voice-metric-card {
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.voice-metric-card--interactive {
  cursor: pointer;
}

.voice-metric-card--interactive:hover,
.voice-metric-card--interactive:focus-visible,
.voice-metric-card--active {
  border-color: var(--q-primary);
  box-shadow: 0 2px 8px rgb(25 118 210 / 14%);
  outline: none;
}

.metric-content {
  min-width: 0;
}

.voice-history-header-row {
  gap: 12px;
}

.voice-history-title {
  flex: 0 0 auto;
}

.voice-history-filters {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.voice-search-filter {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}

.voice-agent-filter {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.voice-status-filter {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.voice-topic-filter {
  flex: 0 1 220px;
  width: 220px;
  min-width: 150px;
  max-width: 220px;
}

.voice-history-card {
  width: 100%;
  overflow: hidden;
}

.voice-history-table :deep(.q-table__middle) {
  overflow-x: hidden;
}

.voice-history-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.voice-history-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 12px;
}

.voice-history-table :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.voice-history-table :deep(th),
.voice-history-table :deep(td) {
  min-width: 0;
  overflow: hidden;
}

.voice-history-table :deep(.voice-call-row > td) {
  background: rgb(25 118 210 / 5%);
  border-top: 1px solid rgb(25 118 210 / 16%);
  font-weight: 500;
}

.voice-history-table :deep(.voice-call-row > .voice-detail-cell),
.voice-history-table :deep(.voice-turn-row > .voice-detail-cell) {
  padding-block: 3px;
}

.voice-history-table :deep(.voice-turn-row) {
  cursor: pointer;
}

.voice-history-table :deep(.voice-turn-row:hover),
.voice-history-table :deep(.voice-turn-row:focus-visible) {
  background: rgb(25 118 210 / 7%);
  outline: none;
}

.voice-turn-indent {
  padding-left: 12px;
}

.voice-mobile-card,
.voice-mobile-heading {
  min-width: 0;
}

.voice-mobile-room {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.voice-mobile-turn {
  min-width: 0;
  padding: 10px 16px;
}

.voice-mobile-preview {
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  line-height: 1.35;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.voice-mobile-preview--response {
  margin-top: 3px;
  color: #388e3c !important;
}

body.body--dark .voice-mobile-preview--response {
  color: #81c784 !important;
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
  .voice-history-header-row {
    flex-wrap: wrap;
  }

  .voice-history-title,
  .voice-history-filters {
    width: 100%;
  }

  .voice-history-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .voice-search-filter,
  .voice-agent-filter,
  .voice-status-filter,
  .voice-topic-filter {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .voice-search-filter,
  .voice-history-filters :deep(.execution-date-filters) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 599px) {
  .voice-history-filters {
    grid-template-columns: minmax(0, 1fr);
  }

  .voice-search-filter,
  .voice-history-filters :deep(.execution-date-filters) {
    grid-column: auto;
  }

  .voice-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .voice-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .metric-content {
    margin-left: 8px;
  }

  .voice-history-table :deep(.q-table__grid-item) {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
