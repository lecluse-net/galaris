<template>
  <GoalPreview v-if="target.kind === 'goal'" :key="target.id" :preview-goal-id="target.id" @close="emit('close')" />
  <NativeRunDialog v-else-if="target.kind === 'process_run'" :key="target.id + ':' + target.agentId"
    :run-id="target.id" :agent-id="target.agentId" :title="target.title" @close="emit('close')" />
  <ExternalRunDialog v-else-if="target.kind === 'external_process_run'" :key="target.id" :run-id="target.id" @close="emit('close')" />
  <WorkingDocumentDialog v-else-if="target.kind === 'document'" ref="resourceEditor" :model-value="true"
    :document-id="target.id" :agent-id="target.agentId ?? null" :title="target.title"
    @update:model-value="!$event && emit('close')" @deleted="changedAndClose" />
  <DatasetDialog v-else-if="target.kind === 'dataset'" ref="resourceEditor" :key="target.id" :id="target.id" :title="target.title"
    @close="emit('close')" @updated="emit('changed')" @deleted="changedAndClose" />
  <ConversationTurnDialog v-else :model-value="true" :title="resolvedTitle || target.title || t(titleKeys[target.kind] || 'common.open')" :icon="icons[target.kind] || 'info'"
    :width="target.kind === 'agent' ? '700px' : undefined" :close-label="t('common.close')" @update:model-value="!$event && emit('close')">
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner color="primary" size="42px" /></div>
    <q-banner v-else-if="error" class="q-ma-md">
      {{ error }}
      <template #action><q-btn flat :label="t('common.retry')" @click="retry++" /></template>
    </q-banner>
    <TopicDetail v-else-if="target.kind === 'topic'" :key="target.id" :topic-id="target.id" embedded @loaded="resolvedTitle = $event" />
    <TaskDetail v-else-if="target.kind === 'task'" :task-id="taskId"
      @task-change="taskId = $event" @refresh="emit('changed')" @delete="taskToDelete = $event" />
    <AgentPreview v-else-if="target.kind === 'agent'" :key="target.id" :agent-id="Number(target.id)" @loaded="resolvedTitle = $event" @deleted="changedAndClose" />
    <ProcessPreview v-else-if="target.kind === 'process'" :key="target.id" :uri="`galaris://processes/${target.id}`" :agent-id="target.agentId" @loaded="resolvedTitle = $event.title" />
    <ConversationRoundDetailView v-else-if="round && message" :message="message" :round="round"
      :calls="calls" :loading="false" error="" :calls-loading="callsLoading" :calls-error="callsError"
      @deleted="changedAndClose" @topic-updated="round = $event; emit('changed')"
      @delivery-resolved="round = $event; emit('changed')" />
    <div v-else-if="conversation && turn">
      <q-btn v-if="target.kind === 'voice_session'" flat round icon="arrow_back" :aria-label="t('common.back')" @click="turn = null" />
      <VoiceConversationDetailView :conversation="conversation" :turn="turn"
        @deleted="changedAndClose" @stopped="changedAndClose" @topic-updated="emit('changed')" />
    </div>
    <div v-else-if="conversation" class="q-pa-md">
      <div class="row items-center q-gutter-sm q-mb-md">
        <span>{{ conversation.agent_name }} · {{ conversation.started_at }}</span>
        <CopyResourceReference :uri="`galaris://voice_session/${conversation.id}`" />
      </div>
      <q-list separator>
        <q-item v-for="item in conversation.turns" :key="item.id" clickable @click="turn = item">
          <q-item-section>{{ t('voice.history.turnLabel', { sequence: item.sequence }) }}</q-item-section>
          <q-item-section side>{{ t(`voice.history.turnStatuses.${item.status}`) }}</q-item-section>
          <ResourceReferenceMenu :uri="`galaris://voice/${item.id}`" target=".q-item" />
        </q-item>
        <q-item v-if="!conversation.turns.length"><q-item-section>{{ t('voice.history.noRows') }}</q-item-section></q-item>
      </q-list>
    </div>
    <RoomDiscussion v-else-if="room" :room="room" />
    <div v-else-if="memory" class="q-pa-md">
      <EditorialContent v-if="memory.payload.text != null" :content="memory.payload.text" :media-type="memory.media_type" />
      <q-banner v-else>{{ t('memory.binaryContent') }}</q-banner>
    </div>
  </ConversationTurnDialog>
  <q-dialog :model-value="taskToDelete !== null" @update:model-value="!$event && (taskToDelete = null)">
    <q-card class="galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('task.deleteConfirm') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>{{ t('task.deleteMessage', { label: taskToDelete?.label }) }}</q-card-section>
      <q-banner v-if="deleteError" class="q-ma-md">{{ deleteError }}</q-banner>
      <q-card-actions align="right">
        <q-btn v-close-popup flat :label="t('common.cancel')" />
        <q-btn color="negative" :label="t('common.delete')" :loading="deleting" @click="deleteTask" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script lang="ts">
export async function preload(kind: string): Promise<void> {
  if (kind === 'process_run' || kind === 'external_process_run' || kind === 'process') await import('@/app/process')
}
</script>

<script setup lang="ts">
import { onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CopyResourceReference, ResourceReferenceMenu, defineAsyncView, EditorialContent, ConversationTurnDialog, WorkingDocumentDialog, type ResourceDetailTarget } from '@/core/util'
import type { TaskFull } from '@/app/task'
import type { ConversationMessage, ConversationRoundDetail } from '@/app/conversation'
import type { VoiceConversationDetail, VoiceConversationTurn } from '@/app/voice'
import type { MessengerRoom } from '@/app/chat/interface'
import type { MemoryItemDetail } from '@/app/memory'
import type { LLMCall } from '@/app/llm'

const TaskDetail = defineAsyncView(async () => (await import('@/app/task')).TaskDetail)
const TopicDetail = defineAsyncView(async () => (await import('@/app/topic')).TopicDetail)
const AgentPreview = defineAsyncView(async () => (await import('@/app/agent')).AgentPreview)
const GoalPreview = defineAsyncView(async () => (await import('@/app/goal')).GoalPreview)
const NativeRunDialog = defineAsyncView(async () => (await import('@/app/process')).NativeRunDialog)
const ExternalRunDialog = defineAsyncView(async () => (await import('@/app/process')).ExternalRunDialog)
const ProcessPreview = defineAsyncView(async () => (await import('@/app/process')).ProcessPreview)
const DatasetDialog = defineAsyncView(async () => (await import('@/app/dataset')).DatasetDialog)
const ConversationRoundDetailView = defineAsyncView(async () => (await import('@/app/conversation')).ConversationRoundDetailView)
const VoiceConversationDetailView = defineAsyncView(async () => (await import('@/app/voice')).VoiceConversationDetailView)
const RoomDiscussion = defineAsyncView(async () => (await import('@/app/chat/interface')).RoomDiscussion)
const props = defineProps<{ target: ResourceDetailTarget }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const resourceEditor = useTemplateRef<{ canLeave?: () => boolean | Promise<boolean>; flush?: () => Promise<boolean> }>('resourceEditor')
async function canLeave(): Promise<boolean> {
  const editor = resourceEditor.value
  return editor?.canLeave ? await editor.canLeave() : editor?.flush ? await editor.flush() : true
}
defineExpose({ canLeave })
const { t } = useI18n()
const titleKeys: Record<string, string> = { topic: 'topic.detail.title', task: 'task.detailTitle', round: 'conversation.history.detail.title', voice: 'voice.history.detail.title', voice_session: 'voice.history.tab', room: 'chat.conversations' }
const icons: Record<string, string> = { topic: 'folder', voice_session: 'phone_in_talk', agent: 'person', task: 'task_alt', process_run: 'account_tree', dataset: 'data_object', round: 'forum', voice: 'record_voice_over', room: 'hub', document: 'description', memory: 'memory' }
const retry = ref(0)
const resolvedTitle = ref('')
const taskId = ref<string | null>(null)
const taskToDelete = ref<TaskFull | null>(null)
const deleting = ref(false)
const deleteError = ref('')
const loading = ref(false)
const error = ref('')
const round = ref<ConversationRoundDetail | null>(null)
const message = ref<ConversationMessage | null>(null)
const calls = ref<LLMCall[]>([])
const callsLoading = ref(false)
const callsError = ref('')
const conversation = ref<VoiceConversationDetail | null>(null)
const turn = ref<VoiceConversationTurn | null>(null)
const memory = ref<MemoryItemDetail | null>(null)
const room = ref<MessengerRoom | null>(null)
let generation = 0
onBeforeUnmount(() => { generation++ })

function changedAndClose(): void { emit('changed'); emit('close') }

async function deleteTask(): Promise<void> {
  if (!taskToDelete.value || deleting.value) return
  const current = generation
  const identity = taskToDelete.value.id
  deleting.value = true
  deleteError.value = ''
  try {
    const { taskService } = await import('@/app/task')
    if (current !== generation) return
    await taskService.delete(identity)
    if (current !== generation) return
    taskToDelete.value = null
    changedAndClose()
  } catch {
    if (current === generation) deleteError.value = t('topic.detail.targetLoadError')
  } finally {
    if (current === generation) deleting.value = false
  }
}

watch([() => props.target, retry], async ([target], _, onCleanup) => {
  const current = ++generation
  let active = true
  onCleanup(() => { active = false; generation++ })
  error.value = ''
  resolvedTitle.value = ''
  callsError.value = ''
  calls.value = []
  callsLoading.value = false
  round.value = null
  message.value = null
  conversation.value = null
  turn.value = null
  memory.value = null
  room.value = null
  taskId.value = target.id
  loading.value = !['agent', 'goal', 'task', 'topic', 'process', 'process_run', 'dataset'].includes(target.kind)
  try {
    if (target.kind === 'round') {
      const { conversationService } = await import('@/app/conversation')
      if (!active) return
      const value = await conversationService.getRound(target.id)
      if (!active) return
      round.value = value
      callsLoading.value = true
      void conversationService.llmCalls(target.id).then(value => {
        if (active) calls.value = value
      }).catch(() => {
        if (active) callsError.value = t('conversation.history.detail.llmLoadError')
      }).finally(() => {
        if (active) callsLoading.value = false
      })
      message.value = { id: value.id, sequence: 0, agent_id: value.agent_id, agent_name: value.agent_name,
        agent_code: null, channel_kind: value.channel_kind, connection_id: value.connection_id,
        room_id: value.room_id, participant_key: value.participant_key, language: value.language,
        payload: value.rendered_input[0] ?? {}, created_at: value.created_at, round_id: value.id,
        round_status: value.status, response_text: value.response_text, response_error: value.last_error,
        responded_at: value.finished_at, aggregated_message_count: value.rendered_input.length, topic_id: value.topic_id }
    } else if (target.kind === 'voice') {
      const { voiceConversationService } = await import('@/app/voice')
      if (!active) return
      const detail = await voiceConversationService.getTurn(target.id)
      if (!active) return
      const session = await voiceConversationService.get(detail.session_id)
      if (!active) return
      conversation.value = session
      turn.value = detail
    } else if (target.kind === 'voice_session') {
      const { voiceConversationService } = await import('@/app/voice')
      if (!active) return
      const detail = await voiceConversationService.get(target.id)
      if (active) conversation.value = detail
    } else if (target.kind === 'room') {
      const { chatService } = await import('@/app/chat/interface')
      if (!active) return
      const detail = await chatService.room(target.id)
      if (!active) return
      room.value = detail
      resolvedTitle.value = detail.label || detail.external_id
    } else if (target.kind === 'memory') {
      const { memoryService } = await import('@/app/memory')
      if (!active) return
      const detail = await memoryService.getItem(target.id, target.agentId)
      if (active) memory.value = detail
    }
  } catch {
    if (active) error.value = t('topic.detail.targetLoadError')
  } finally {
    if (active && current === generation) loading.value = false
  }
}, { immediate: true })
</script>
