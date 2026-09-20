<template>
  <div>
    <div v-if="loading" class="row justify-center q-pa-xl">
      <q-spinner color="primary" size="48px" />
    </div>

    <q-banner v-else-if="error" rounded class="conversation-notice--error q-ma-md">
      <template #avatar><q-icon name="error" /></template>
      {{ error }}
    </q-banner>

    <template v-else>
      <div class="conversation-detail-header">
        <div class="conversation-detail-header-shell">
          <q-spinner
            v-if="roundRunning"
            :color="statusVisual.color"
            size="md"
            class="q-mr-sm"
          />
          <q-icon
            v-else
            :name="statusVisual.icon"
            :color="statusVisual.color"
            size="md"
            class="q-mr-sm"
          />

          <div class="col conversation-detail-header-content">
            <div class="conversation-detail-header-row">
              <div class="row items-center q-gutter-x-sm conversation-detail-heading">
                <span class="text-weight-medium">
                  {{ t('conversation.history.detail.turn') }}
                </span>
                <div class="conversation-detail-agent">
                  <AgentAvatar
                    :agent-id="message.agent_id"
                    :name="agentName"
                    size="24px"
                    color="white"
                    text-color="grey-7"
                  />
                  <span class="conversation-detail-agent-name">{{ agentName }}</span>
                  <q-tooltip>{{ t('conversation.history.agent') }}</q-tooltip>
                </div>
              </div>
              <StatusBadge :tone="statusTone" :label="statusLabel" />
            </div>

            <div class="conversation-detail-header-row conversation-detail-header-row--secondary q-mt-xs">
              <div class="row items-center q-gutter-x-sm conversation-detail-metadata">
                <div
                  class="text-caption text-grey cursor-pointer conversation-detail-metadata-id"
                  :title="t('common.copy')"
                  @click="copyRoundId"
                >
                  ID: {{ roundId || '-' }}
                </div>
                <q-separator vertical size="1px" color="grey-5" />
                <div class="row items-center no-wrap text-caption text-grey">
                  <q-icon name="event" size="xs" class="q-mr-xs" />
                  {{ formatDate(round?.created_at || message.created_at) }}
                  <q-tooltip>{{ t('conversation.history.receivedAt') }}</q-tooltip>
                </div>
                <q-separator vertical size="1px" color="grey-5" />
                <div class="row items-center no-wrap text-caption text-grey">
                  <q-icon name="hub" size="xs" class="q-mr-xs" />
                  {{ message.channel_kind }}
                  <q-tooltip>{{ t('conversation.history.channel') }}</q-tooltip>
                </div>
                <q-separator vertical size="1px" color="grey-5" />
                <div
                  class="row items-center no-wrap text-caption text-grey conversation-detail-metadata-room"
                >
                  <q-icon name="forum" size="xs" class="q-mr-xs" />
                  <span class="ellipsis">{{ message.room_id }}</span>
                  <q-tooltip>{{ t('conversation.history.room') }} · {{ message.room_id }}</q-tooltip>
                </div>
              </div>
              <div v-if="roundId" class="conversation-action-buttons">
                <ConversationDatasetCaptureButton
                  v-if="canEditLab"
                  kind="text"
                  :source-id="roundId"
                  :source-label="messageText(message.payload)"
                />
                <q-btn
                  size="sm"
                  color="secondary"
                  icon="content_copy"
                  :label="t('conversation.history.detail.copyJson')"
                  :loading="copyingJson"
                  @click="copyJson"
                />
                <q-btn
                  v-if="canEdit"
                  size="sm"
                  color="negative"
                  icon="delete"
                  :label="t('common.delete')"
                  @click="deleteDialog = true"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <TopicAssignmentEditor
        :key="roundId ?? message.id"
        :topic-id="round?.topic_id || message.topic_id"
        :editable="canEdit && Boolean(roundId)"
        :saving="topicSaving"
        @save="saveTopic"
      />

      <DeliveryResolution
        v-if="round && roundId"
        :key="roundId"
        :round-id="roundId"
        :state="round.delivery_state"
        :editable="canEdit"
        @resolved="emit('delivery-resolved', $event)"
      />
      <DeliveryResolution
        v-for="notification in round?.unknown_notifications || []"
        :key="`${round?.id}-${notification.kind}-${notification.link_id}-${notification.attempt_number}`"
        :round-id="round!.id"
        state="UNKNOWN"
        :notification="notification"
        :editable="canEdit"
        @resolved="emit('delivery-resolved', $event)"
      />

      <q-separator />

      <q-card-section class="conversation-thread">
        <div class="column q-gutter-md">
          <ConversationBubble
            v-for="(input, index) in renderedInputs"
            :key="`${message.id}-${index}`"
            :speaker="senderName(input)"
          >
            <div>{{ messageText(input) }}</div>
          </ConversationBubble>

          <ConversationBubble :speaker="agentName" side="outgoing" content-mode="rich">
            <Markdown
              v-if="responseText"
              :content="responseText"
            />
            <WaitingResponseIndicator
              v-else-if="roundRunning"
              :label="t('conversation.history.waitingResponse')"
            />
            <div v-else>
              {{ message.round_id
                ? t('conversation.history.detail.noResponse')
                : t('conversation.history.responsePending') }}
            </div>
          </ConversationBubble>
        </div>
        <q-banner
          v-if="responseError"
          dense
          rounded
          class="conversation-notice--error q-mt-md"
        >
          {{ responseError }}
        </q-banner>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <ExecutionResultComponent
          :execution-result="round?.execution_result || null"
          :execution-success="executionSuccess"
          :running="roundRunning"
          :llm-calls="calls"
          :llm-calls-loading="callsLoading"
          :llm-calls-error="callsError"
          :agent-id="message.agent_id"
          :agent-name="agentName"
          :user-name="userName"
          show-memory
        >
          <template #details>
            <ConversationExecutionDetails
              :round="round"
              :status="effectiveStatus"
              :calls="calls"
              :calls-loading="callsLoading"
              :calls-error="callsError"
            />
          </template>
        </ExecutionResultComponent>
      </q-card-section>

      <q-dialog v-model="deleteDialog">
        <q-card class="confirm-dialog">
          <q-card-section class="galaris-dialog-title row items-center no-wrap">
            <div class="text-h6">{{ t('conversation.history.detail.deleteTitle') }}</div>
            <q-space />
            <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
          </q-card-section>
          <q-separator />
          <q-card-section>{{ t('conversation.history.detail.deleteConfirm') }}</q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
            <q-btn v-close-popup flat :label="t('common.cancel')" />
            <q-btn
              color="negative"
              icon="delete"
              :label="t('common.delete')"
              :loading="deleting"
              @click="deleteRound"
            />
          </q-card-actions>
        </q-card>
      </q-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import AgentAvatar from '@/app/agent/components/AgentAvatar.vue'
import type { LLMCall } from '@/app/llm/types'
import ExecutionResultComponent from '@/app/task/components/ExecutionResult.vue'
import ConversationExecutionDetails from './ConversationExecutionDetails.vue'
import ConversationDatasetCaptureButton from '@/app/lab/components/ConversationDatasetCaptureButton.vue'
import { labSectionPrivileges } from '@/app/lab'
import ConversationBubble from '@/core/util/components/ConversationBubble.vue'
import Markdown from '@/core/util/components/Markdown.vue'
import WaitingResponseIndicator from '@/core/util/components/WaitingResponseIndicator.vue'
import { StatusBadge, type StatusBadgeTone } from '@/core/util'
import type { ConversationMessage, ConversationRoundDetail } from '../types'
import { conversationService } from '../services/conversationService'
import TopicAssignmentEditor from '@/app/topic/components/TopicAssignmentEditor.vue'
import DeliveryResolution from './DeliveryResolution.vue'

const props = defineProps<{
  message: ConversationMessage
  round: ConversationRoundDetail | null
  calls: LLMCall[]
  loading: boolean
  error: string
  callsLoading: boolean
  callsError: string
}>()
const emit = defineEmits<{
  deleted: []
  'topic-updated': [round: ConversationRoundDetail]
  'delivery-resolved': [round: ConversationRoundDetail]
}>()

const { t, te, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))
const canEditLab = computed(() => privilegeStore.hasPrivilege(
  labSectionPrivileges.conversation_executor[1],
))
const copyingJson = ref(false)
const deleteDialog = ref(false)
const deleting = ref(false)
const topicSaving = ref(false)
const roundId = computed(() => props.round?.id || props.message.round_id)
const renderedInputs = computed<Array<Record<string, unknown>>>(() => (
  props.round?.rendered_input.length ? props.round.rendered_input : [props.message.payload]
))
const agentName = computed(() => (
  props.round?.agent_name?.trim()
  || props.message.agent_name?.trim()
  || t('conversation.history.unknownAgent', { id: props.message.agent_id })
))
const responseText = computed(() => (
  props.round?.response_text || props.message.response_text || ''
).trim())
const responseError = computed(() => executionSuccess.value === true ? '' : (
  props.round?.last_error || props.message.response_error || ''
).trim())
const effectiveStatus = computed(() => {
  const roundStatus = props.round?.status
  const messageStatus = props.message.round_status
  const activeStatuses = ['FROZEN', 'CLAIMED', 'RUNNING']
  if (roundStatus && !activeStatuses.includes(roundStatus)) return roundStatus
  if (messageStatus && !activeStatuses.includes(messageStatus)) return messageStatus
  return roundStatus || messageStatus
})
const executionSuccess = computed<boolean | undefined>(() => {
  if (['SUCCEEDED', 'COMPLETED'].includes(effectiveStatus.value || '')) return true
  if (['ERROR_RESOLVED', 'FAILED'].includes(effectiveStatus.value || '')) return false
  return undefined
})
const statusLabel = computed(() => {
  if (!effectiveStatus.value) return t('conversation.history.detail.pending')
  const key = `conversation.history.detail.roundStatuses.${effectiveStatus.value}`
  return te(key) ? t(key) : effectiveStatus.value
})
const statusVisual = computed(() => {
  const status = effectiveStatus.value
  if (!status) return { color: 'warning', icon: 'pending' }
  if (status === 'SUCCEEDED' || status === 'COMPLETED') return { color: 'positive', icon: 'check_circle' }
  if (['RUNNING', 'CLAIMED', 'FROZEN'].includes(status)) {
    return { color: 'primary', icon: 'pending' }
  }
  if (status === 'SUPERSEDED' || status === 'CANCELLED') return { color: 'grey-7', icon: 'skip_next' }
  if (status === 'INTERRUPTED') return { color: 'warning', icon: 'pause' }
  return { color: 'negative', icon: 'error' }
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
const roundRunning = computed(() => (
  ['RUNNING', 'CLAIMED', 'FROZEN'].includes(effectiveStatus.value || '')
))

const userName = computed(() => {
  const input = [...renderedInputs.value]
    .reverse()
    .find(payload => {
      const sender = payload.sender
      const nested = sender && typeof sender === 'object'
        ? sender as Record<string, unknown>
        : null
      return Number(payload.sender_agent_id ?? nested?.agent_id) !== props.message.agent_id
    })
  return input ? senderName(input) : t('conversation.history.detail.user')
})

function senderName(payload: Record<string, unknown>): string {
  const sender = payload.sender
  const nested = sender && typeof sender === 'object'
    ? sender as Record<string, unknown>
    : null
  const displayName = String(
    payload.sender_display_name || nested?.display_name || '',
  ).trim()
  if (displayName) return displayName

  const senderAgentId = Number(payload.sender_agent_id ?? nested?.agent_id)
  if (senderAgentId === props.message.agent_id) return agentName.value

  const externalId = String(
    payload.sender_external_id || nested?.id || '',
  ).trim()
  return externalId || t('conversation.history.detail.user')
}

function messageText(payload: Record<string, unknown>): string {
  const text = String(payload.text || '').trim()
  return text || t('conversation.history.detail.nonTextMessage')
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

async function copyRoundId(): Promise<void> {
  if (!roundId.value) return
  try {
    await copyToClipboard(roundId.value)
    $q.notify({
      message: t('common.copied'),
      color: 'positive',
      icon: 'check_circle',
      timeout: 1500,
      position: 'top',
    })
  } catch {
    $q.notify({
      message: t('common.copyError'),
      color: 'negative',
      icon: 'error',
      timeout: 3000,
      position: 'top',
    })
  }
}

async function copyJson(): Promise<void> {
  if (!roundId.value || copyingJson.value) return
  copyingJson.value = true
  try {
    const dataset = await conversationService.exportRound(roundId.value)
    await copyToClipboard(JSON.stringify(dataset, null, 2))
    $q.notify({ color: 'positive', icon: 'check_circle', message: t('conversation.history.detail.jsonCopied') })
  } catch (reason) {
    console.error('Failed to copy text conversation round JSON:', reason)
    $q.notify({ color: 'negative', icon: 'error', message: t('conversation.history.detail.copyJsonError') })
  } finally {
    copyingJson.value = false
  }
}

async function saveTopic(topicId: string | null): Promise<void> {
  if (!roundId.value || topicSaving.value || !canEdit.value) return
  topicSaving.value = true
  try {
    const updated = await conversationService.updateRoundTopic(roundId.value, topicId)
    emit('topic-updated', updated)
    $q.notify({ color: 'positive', icon: 'folder', message: t('topic.assignmentUpdated') })
  } catch (reason) {
    console.error('Failed to update text conversation topic:', reason)
    $q.notify({ color: 'negative', icon: 'error', message: t('topic.assignmentUpdateError') })
  } finally {
    topicSaving.value = false
  }
}

async function deleteRound(): Promise<void> {
  if (!roundId.value || deleting.value || !canEdit.value) return
  deleting.value = true
  try {
    await conversationService.deleteRound(roundId.value)
    deleteDialog.value = false
    $q.notify({ color: 'positive', icon: 'delete', message: t('conversation.history.detail.deleted') })
    emit('deleted')
  } catch (reason) {
    console.error('Failed to delete text conversation round:', reason)
    $q.notify({
      color: 'negative',
      icon: 'error',
      message: apiErrorDetail(reason) || t('conversation.history.detail.deleteError'),
    })
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.conversation-thread {
  background: #fafafa;
}

.conversation-detail-header {
  padding: 16px;
  background: rgba(33, 186, 69, 0.1);
}

.conversation-detail-header-shell {
  display: flex;
  align-items: center;
}

.conversation-detail-header-content {
  min-width: 0;
}

.conversation-detail-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.conversation-detail-heading {
  min-width: 0;
}

.conversation-detail-agent {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 260px;
  padding: 2px 8px 2px 2px;
  border-radius: 999px;
  color: #3c4043;
  font-size: 12px;
  line-height: 1.2;
  background: rgba(255, 255, 255, 0.72);
}

.conversation-detail-agent-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

body.body--dark .conversation-detail-agent {
  color: #f5f5f5;
  background: rgba(0, 0, 0, 0.22);
}

.conversation-detail-metadata {
  flex: 1 1 760px;
  min-width: min(100%, 760px);
  flex-wrap: wrap;
}

.conversation-detail-metadata-id {
  flex: 0 0 auto;
  white-space: nowrap;
}

.conversation-detail-metadata-room {
  flex: 1 1 120px;
  min-width: 0;
}

.conversation-action-buttons {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.confirm-dialog {
  width: min(480px, 92vw);
  max-width: 92vw;
}

@media (max-width: 760px) {
  .conversation-detail-header-shell {
    align-items: flex-start;
  }

  .conversation-detail-header-row {
    align-items: flex-start;
  }

  .conversation-detail-heading {
    flex-wrap: wrap;
  }

  .conversation-action-buttons {
    justify-content: flex-start;
  }
}

.conversation-notice--warning {
  color: #8a4b08;
  background: #fff3e0;
}

.conversation-notice--error {
  color: #b71c1c;
  background: #ffebee;
}

body.body--dark .conversation-thread {
  background: #1d1d1d;
}

body.body--dark .conversation-notice--warning {
  color: #ffcc80;
  background: #3d2d16;
}

body.body--dark .conversation-notice--error {
  color: #ffb3b8;
  background: #3b1f23;
}
</style>
