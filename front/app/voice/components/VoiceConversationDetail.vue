<template>
  <div>
    <div class="conversation-detail-header">
      <div class="conversation-detail-header-shell">
        <q-spinner
          v-if="turn.status === 'RUNNING'"
          :color="turnVisual.color"
          size="md"
          class="q-mr-sm"
        />
        <q-icon
          v-else
          :name="turnVisual.icon"
          :color="turnVisual.color"
          size="md"
          class="q-mr-sm"
        />

        <div class="col conversation-detail-header-content">
          <div class="conversation-detail-header-row">
            <div class="row items-center q-gutter-x-sm conversation-detail-heading">
              <span class="text-weight-medium">
                {{ t('voice.history.detail.turnTitle', { sequence: turn.sequence }) }}
              </span>
              <div class="conversation-detail-agent">
                <AgentAvatar
                  :agent-id="conversation.agent_id"
                  :name="agentName"
                  size="24px"
                  color="white"
                  text-color="grey-7"
                />
                <span class="conversation-detail-agent-name">{{ agentName }}</span>
                <q-tooltip>{{ t('voice.history.agent') }}</q-tooltip>
              </div>
            </div>
            <StatusBadge
              :tone="turnTone"
              :label="t(`voice.history.turnStatuses.${turn.status}`)"
              :icon="turnVisual.icon"
            />
          </div>

          <div class="conversation-detail-header-row conversation-detail-header-row--secondary q-mt-xs">
            <div class="row items-center q-gutter-x-sm conversation-detail-metadata">
              <div
                class="text-caption text-grey cursor-pointer conversation-detail-metadata-id"
                :title="t('common.copy')"
                @click="copyTurnId"
              >
                ID: {{ turn.id }}
              </div>
              <q-separator vertical size="1px" color="grey-5" />
              <div class="row items-center no-wrap text-caption text-grey">
                <q-icon name="event" size="xs" class="q-mr-xs" />
                {{ formatDate(turn.started_at) }}
                <q-tooltip>{{ t('voice.history.detail.turnDate') }}</q-tooltip>
              </div>
              <q-separator vertical size="1px" color="grey-5" />
              <div class="row items-center no-wrap text-caption text-grey">
                <q-icon name="hub" size="xs" class="q-mr-xs" />
                {{ transportLabel(conversation.transport_kind) }}
                <q-tooltip>{{ t('voice.history.channel') }}</q-tooltip>
              </div>
              <q-separator vertical size="1px" color="grey-5" />
              <div
                class="row items-center no-wrap text-caption text-grey conversation-detail-metadata-room"
              >
                <q-icon name="forum" size="xs" class="q-mr-xs" />
                <span class="ellipsis">{{ conversation.room_id }}</span>
                <q-tooltip>{{ t('voice.history.room') }} · {{ conversation.room_id }}</q-tooltip>
              </div>
            </div>
            <div class="conversation-action-buttons">
              <ConversationDatasetCaptureButton
                v-if="canEditLab"
                kind="voice"
                :source-id="turn.id"
                :source-label="effectiveObjectiveText || transcriptText || turn.id"
              />
              <q-btn
                size="sm"
                color="secondary"
                icon="content_copy"
                :label="t('voice.history.detail.copyJson')"
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
      :key="turn.id"
      :topic-id="turn.topic_id"
      :editable="canEdit"
      :saving="topicSaving"
      @save="saveTopic"
    />

    <q-separator />

    <q-card-section class="conversation-thread">
      <div class="column q-gutter-md">
        <ConversationBubble :speaker="callerName">
          <div v-if="transcriptText">
            {{ transcriptText }}
          </div>
          <div v-else>
            {{ t('voice.history.detail.nativeAudio') }}
          </div>
        </ConversationBubble>

        <q-banner
          v-if="turn.source_turn_id && effectiveObjectiveText"
          dense
          rounded
          class="conversation-notice--warning"
        >
          <div class="text-caption text-weight-medium">
            {{ t('voice.history.detail.accumulatedObjective') }}
          </div>
          <div class="voice-message">{{ effectiveObjectiveText }}</div>
        </q-banner>

        <ConversationBubble :speaker="agentName" side="outgoing" content-mode="rich">
          <Markdown
            v-if="assistantResponseText"
            :content="assistantResponseText"
          />
          <WaitingResponseIndicator
            v-else-if="turn.status === 'RUNNING'"
            :label="t('voice.history.waitingResponse')"
            color="warning"
          />
          <div v-else>
            {{ t('voice.history.detail.noResponse') }}
          </div>
        </ConversationBubble>
      </div>
      <q-banner v-if="errorText" dense rounded class="conversation-notice--error q-mt-md">
        {{ errorText }}
      </q-banner>
    </q-card-section>

    <q-separator />

    <q-card-section>
      <div v-if="detailLoading" class="row justify-center q-pa-lg">
        <q-spinner color="deep-orange" size="32px" />
      </div>
      <q-banner v-else-if="detailError" rounded class="conversation-notice--error">
        {{ detailError }}
      </q-banner>
      <ExecutionResultComponent
        v-else
        :execution-result="turnDetail?.execution_result || null"
        :running="turn.status === 'RUNNING'"
        :llm-calls="calls"
        :llm-calls-loading="callsLoading"
        :llm-calls-error="callsError"
        :agent-id="conversation.agent_id"
        :agent-name="agentName"
        :user-name="callerName"
        show-memory
      />
    </q-card-section>

    <q-dialog v-model="deleteDialog">
      <q-card class="confirm-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('voice.history.detail.deleteTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section>{{ t('voice.history.detail.deleteConfirm') }}</q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="negative" icon="delete" :label="t('common.delete')" :loading="deleting" @click="deleteTurn" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import AgentAvatar from '@/app/agent/components/AgentAvatar.vue'
import type { LLMCall } from '@/app/llm/types'
import ExecutionResultComponent from '@/app/task/components/ExecutionResult.vue'
import ConversationDatasetCaptureButton from '@/app/lab/components/ConversationDatasetCaptureButton.vue'
import { labSectionPrivileges } from '@/app/lab'
import ConversationBubble from '@/core/util/components/ConversationBubble.vue'
import Markdown from '@/core/util/components/Markdown.vue'
import WaitingResponseIndicator from '@/core/util/components/WaitingResponseIndicator.vue'
import { StatusBadge, type StatusBadgeTone } from '@/core/util'
import { voiceConversationService } from '../services/voiceConversationService'
import type {
  VoiceConversationDetail,
  VoiceConversationTurn,
  VoiceConversationTurnDetail,
  VoiceTurnStatus,
} from '../types'
import TopicAssignmentEditor from '@/app/topic/components/TopicAssignmentEditor.vue'

const props = defineProps<{
  conversation: VoiceConversationDetail
  turn: VoiceConversationTurn
}>()
const emit = defineEmits<{
  deleted: []
  'topic-updated': [turn: VoiceConversationTurnDetail]
}>()
const { t, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))
const canEditLab = computed(() => privilegeStore.hasPrivilege(
  labSectionPrivileges.voice_executor[1],
))
const calls = ref<LLMCall[]>([])
const callsLoading = ref(false)
const callsError = ref('')
const turnDetail = ref<VoiceConversationTurnDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const copyingJson = ref(false)
const deleteDialog = ref(false)
const deleting = ref(false)
const topicSaving = ref(false)

const agentName = computed(() => (
  turnDetail.value?.agent_name?.trim()
  || props.conversation.agent_name?.trim()
  || t('voice.history.unknownAgent', { id: props.conversation.agent_id })
))
const callerName = computed(() => (
  turnDetail.value?.caller_name?.trim()
  || props.conversation.caller_name?.trim()
  || t('voice.history.detail.user')
))
const transcriptText = computed(() => props.turn.transcript?.trim() || '')
const assistantResponseText = computed(() => props.turn.assistant_response?.trim() || '')
const effectiveObjectiveText = computed(() => props.turn.effective_objective?.trim() || '')
const errorText = computed(() => props.turn.error?.trim() || '')
const turnVisual = computed(() => {
  const visuals: Record<VoiceTurnStatus, { color: string; icon: string }> = {
    RUNNING: { color: 'warning', icon: 'pending' },
    COMPLETED: { color: 'positive', icon: 'check_circle' },
    INTERRUPTED: { color: 'orange', icon: 'mic_off' },
    FAILED: { color: 'negative', icon: 'error' },
  }
  return visuals[props.turn.status]
})
const turnTone = computed<StatusBadgeTone>(() => ({
  RUNNING: 'active',
  COMPLETED: 'success',
  INTERRUPTED: 'warning',
  FAILED: 'error',
})[props.turn.status] as StatusBadgeTone)

onMounted(loadDetails)
watch(() => props.turn.id, loadDetails)

async function loadDetails(): Promise<void> {
  const turnId = props.turn.id
  turnDetail.value = null
  calls.value = []
  detailError.value = ''
  callsError.value = ''
  detailLoading.value = true
  callsLoading.value = props.turn.llm_call_count > 0

  const detailPromise = voiceConversationService.getTurn(turnId)
  const callsPromise = props.turn.llm_call_count > 0
    ? voiceConversationService.llmCalls(turnId)
    : Promise.resolve([])
  const [detailResult, callsResult] = await Promise.allSettled([
    detailPromise,
    callsPromise,
  ])
  if (props.turn.id !== turnId) return

  if (detailResult.status === 'fulfilled') {
    turnDetail.value = detailResult.value
  } else {
    detailError.value = t('voice.history.loadError')
  }
  if (callsResult.status === 'fulfilled') {
    calls.value = callsResult.value
  } else {
    callsError.value = t('voice.history.detail.llmLoadError')
  }
  detailLoading.value = false
  callsLoading.value = false
}

function transportLabel(kind: string): string {
  if (kind === 'matrix' || kind === 'nextcloud_talk') {
    return t(`voice.history.transports.${kind}`)
  }
  return kind.replaceAll('_', ' ')
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

async function copyTurnId(): Promise<void> {
  try {
    await copyToClipboard(props.turn.id)
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
  if (copyingJson.value) return
  copyingJson.value = true
  try {
    const dataset = await voiceConversationService.exportTurn(props.turn.id)
    await copyToClipboard(JSON.stringify(dataset, null, 2))
    $q.notify({ color: 'positive', icon: 'check_circle', message: t('voice.history.detail.jsonCopied') })
  } catch (reason) {
    console.error('Failed to copy voice conversation turn JSON:', reason)
    $q.notify({ color: 'negative', icon: 'error', message: t('voice.history.detail.copyJsonError') })
  } finally {
    copyingJson.value = false
  }
}

async function saveTopic(topicId: string | null): Promise<void> {
  if (topicSaving.value || !canEdit.value) return
  topicSaving.value = true
  try {
    const updated = await voiceConversationService.updateTurnTopic(props.turn.id, topicId)
    turnDetail.value = updated
    emit('topic-updated', updated)
    $q.notify({ color: 'positive', icon: 'folder', message: t('topic.assignmentUpdated') })
  } catch (reason) {
    console.error('Failed to update voice conversation topic:', reason)
    $q.notify({ color: 'negative', icon: 'error', message: t('topic.assignmentUpdateError') })
  } finally {
    topicSaving.value = false
  }
}

async function deleteTurn(): Promise<void> {
  if (deleting.value || !canEdit.value) return
  deleting.value = true
  try {
    await voiceConversationService.deleteTurn(props.turn.id)
    deleteDialog.value = false
    $q.notify({ color: 'positive', icon: 'delete', message: t('voice.history.detail.deleted') })
    emit('deleted')
  } catch (reason) {
    console.error('Failed to delete voice conversation turn:', reason)
    $q.notify({ color: 'negative', icon: 'error', message: t('voice.history.detail.deleteError') })
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.voice-message {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

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
