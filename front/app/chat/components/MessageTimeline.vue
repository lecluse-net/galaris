<template>
  <div ref="timelineElement" class="message-timeline">
    <div
      v-if="loading && !messages.length && !showEphemeralBubble"
      class="conversation-loading-state"
      role="status"
      aria-live="polite"
    >
      <div class="conversation-loading-bubble" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <span class="conversation-loading-label">{{ t('chat.loadingRoom') }}</span>
    </div>
    <div
      v-else-if="!messages.length && !showEphemeralBubble"
      class="conversation-empty-state text-grey"
    >
      {{ t('chat.emptyRoom') }}
    </div>
    <div
      v-for="entry in timelineEntries"
      :key="entry.key"
      class="message-row"
      :class="{
        'message-row--sent': entry.isMine,
        'message-row--live': entry.liveRound,
        'message-row--transcribing': entry.pendingTranscription,
      }"
      :aria-live="entry.liveRound || entry.pendingTranscription ? 'polite' : undefined"
      :data-message-id="entry.message?.id"
    >
      <InternalAgentAvatar
        v-if="entry.senderAgentId !== null"
        :agent-id="entry.senderAgentId"
        :name="entry.senderName"
        size="32px"
        class="message-avatar"
      />
      <InternalParticipantAvatar
        v-else
        :name="entry.senderName"
        :avatar-url="entry.avatarUrl"
        size="32px"
        class="message-avatar"
      />
      <div
        class="message-stack"
        :class="{ 'message-stack--trace': entry.activity || entry.liveRound || entry.pendingTranscription }"
      >
        <div class="message-meta">
          <button
            type="button"
            class="message-round-copy"
            :disabled="!entry.copyRoundId"
            :title="t('chat.copyRoundId')"
            @click="copyRoundId(entry.copyRoundId)"
          >
            <span class="message-sender">{{ entry.senderName }}</span>
            <template v-if="entry.createdAt">
              <span aria-hidden="true">·</span>
              <time :datetime="entry.createdAt">{{ formatTimestamp(entry.createdAt) }}</time>
            </template>
          </button>
          <TopicBadge
            v-if="entry.message?.topic_id && !$q.screen.lt.md"
            :topic-id="entry.message.topic_id"
            :title="topicTitle(entry.message.topic_id)"
            subject-kind="message"
            :subject-id="entry.message.id"
            :allow-topic-change="viewerAgentId === null"
            :reassign-topic="(topicId, scope) => reassignMessageTopic(entry.message!, topicId, scope)"
          />
          <TopicBadge
            v-else-if="entry.liveRound?.topic_id && !$q.screen.lt.md"
            :topic-id="entry.liveRound.topic_id"
            :title="topicTitle(entry.liveRound.topic_id)"
            :allow-topic-change="false"
          />
          <div
            v-if="entry.message && (canReadMessage(entry.message) || (allowReply && !entry.message.is_mine))"
            class="message-actions"
          >
            <q-btn
              v-if="canReadMessage(entry.message)"
              flat
              dense
              no-caps
              :icon-right="speechPlayingMessageId === entry.message.id ? 'stop_circle' : 'volume_up'"
              :label="speechPlayingMessageId === entry.message.id ? t('chat.stopReadingMessage') : t('chat.readMessage')"
              :aria-label="speechPlayingMessageId === entry.message.id ? t('chat.stopReadingMessage') : t('chat.readMessage')"
              :loading="speechLoadingMessageId === entry.message.id"
              :disable="speechLoadingMessageId !== null && speechLoadingMessageId !== entry.message.id"
              class="message-action"
              @click="toggleMessageSpeech(entry.message)"
            />
            <q-btn
              v-if="allowReply && !entry.message.is_mine"
              flat
              dense
              no-caps
              icon-right="reply"
              :label="t('chat.reply')"
              :aria-label="t('chat.reply')"
              class="message-action"
              @click="$emit('reply', entry.message)"
            />
          </div>
        </div>
        <div class="message-bubble" :class="{ 'message-bubble--live': entry.liveRound }">
          <div class="message-body">
            <VoiceTranscriptionStatus v-if="entry.pendingTranscription" />
            <div v-if="entry.message?.reply_to" class="reply-preview text-caption text-grey-7 q-mb-xs">
              ↪ {{ repliedMessage(entry.message.reply_to)?.sender?.display_name || t('chat.reply') }} · {{ repliedMessage(entry.message.reply_to)?.text || entry.message.reply_to }}
            </div>
            <AgentExecutionTrace
              v-if="entry.activity || entry.liveRound"
              :room-id="roomId"
              :activity="entry.activity"
              :live-round="entry.liveRound"
            />
            <InteractionChoice
              v-if="entry.message?.interaction?.options.length"
              :key="entry.message.interaction.id"
              :room-id="roomId"
              :interaction="entry.message.interaction"
              :readonly="!allowReply || viewerAgentId !== null"
            />
            <SafeMessageContent v-else-if="entry.text" class="message-text" :content="entry.text" />
            <MessageResourcePreviews
              v-if="entry.message && hasPreviewableReference(entry.message.text)"
              :room-id="roomId"
              :message-id="entry.message.id"
              :conversation-agent-id="agentId"
              :viewer-agent-id="viewerAgentId"
              :can-read-documents="canReadDocuments"
              :can-edit-documents="canEditDocuments"
              @open-document="emit('openDocument', $event)"
            />
            <div v-for="file in entry.message?.files ?? []" :key="file.id" class="attachment q-mt-xs">
              <button
                v-if="isModel3dFile(file)"
                type="button"
                class="image-preview-button model3d-attachment"
                :aria-label="t('chat.openAttachmentPreview', { name: file.name })"
                @click="openPreview(file)"
              >
                <Model3dThumbnail :source="modelSource(file)" />
              </button>
              <audio
                v-else-if="isAudioFile(file) && mediaUrls[file.id]"
                controls
                preload="metadata"
                :src="mediaUrls[file.id]"
                class="audio-note"
              />
              <button
                v-else-if="isImageFile(file) && mediaUrls[file.id]"
                type="button"
                class="image-preview-button"
                :aria-label="t('chat.openAttachmentPreview', { name: file.name })"
                @click="openPreview(file)"
              >
                <img :src="mediaUrls[file.id]" :alt="file.name" class="image-preview" />
              </button>
              <video
                v-else-if="isVideoFile(file) && mediaUrls[file.id]"
                controls
                playsinline
                preload="metadata"
                :src="mediaUrls[file.id]"
                class="video-player"
              />
              <iframe
                v-else-if="isPdfFile(file) && mediaUrls[file.id]"
                :src="mediaUrls[file.id]"
                :title="t('chat.pdfPreview', { name: file.name })"
                class="pdf-reader"
              />
              <MarkdownAttachmentPreview
                v-else-if="isMarkdownFile(file)"
                :room-id="roomId"
                :file="file"
                :viewer-agent-id="viewerAgentId"
                @loaded="storeMarkdownContent"
              />
              <div class="attachment-actions">
                <q-btn
                  flat
                  dense
                  no-caps
                  :href="attachmentStandaloneHref(file)"
                  rel="noopener noreferrer"
                  :icon="canOpenPreview(file) ? 'open_in_full' : 'attach_file'"
                  :label="file.name"
                  @click="attachmentAction($event, file)"
                />
                <q-btn
                  v-if="attachmentStandaloneHref(file)"
                  flat
                  round
                  dense
                  icon="open_in_new"
                  :href="attachmentStandaloneHref(file)"
                  target="_blank"
                  rel="noopener noreferrer"
                  :aria-label="t('chat.resourcePreview.openNewTab')"
                >
                  <q-tooltip>{{ t('chat.resourcePreview.openNewTab') }}</q-tooltip>
                </q-btn>
                <q-btn
                  flat
                  round
                  dense
                  icon="download"
                  :aria-label="t('chat.downloadAttachment', { name: file.name })"
                  @click="download(file.id, file.name)"
                >
                  <q-tooltip>{{ t('chat.downloadAttachment', { name: file.name }) }}</q-tooltip>
                </q-btn>
                <q-btn
                  v-if="mediaLoadErrors[file.id]"
                  flat
                  round
                  dense
                  color="negative"
                  icon="refresh"
                  :aria-label="t('chat.retryAttachmentPreview', { name: file.name })"
                  @click="retryMedia(file)"
                >
                  <q-tooltip>{{ t('chat.retryAttachmentPreview', { name: file.name }) }}</q-tooltip>
                </q-btn>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <FullscreenPreview
    v-model="previewOpen"
    :immersive="previewIsImmersive"
    :interactive="Boolean(previewFile && (isHtmlFile(previewFile) || isModel3dFile(previewFile) || isMarkdownFile(previewFile) || isTextFile(previewFile)))"
    :spatial="Boolean(previewFile && isModel3dFile(previewFile))"
    :viewer-label="t('chat.resourcePreview.viewerLabel')"
  >
    <template #actions>
      <q-btn
        v-if="previewFile"
        flat
        round
        dense
        icon="download"
        color="white"
        :aria-label="t('chat.downloadAttachment', { name: previewFile.name })"
        @click="download(previewFile.id, previewFile.name)"
      >
        <q-tooltip>{{ t('chat.downloadAttachment', { name: previewFile.name }) }}</q-tooltip>
      </q-btn>
    </template>
    <template v-if="previewFile" #default="{ fit }">
        <Model3dViewer v-if="isModel3dFile(previewFile)" :source="modelSource(previewFile)" />
        <img
          v-else-if="isImageFile(previewFile) && mediaUrls[previewFile.id]"
          :src="mediaUrls[previewFile.id]"
          :alt="previewFile.name"
          class="attachment-preview-image"
          :class="{ 'attachment-preview-content--fit': fit }"
        />
        <video
          v-else-if="isVideoFile(previewFile) && mediaUrls[previewFile.id]"
          controls
          playsinline
          preload="metadata"
          :src="mediaUrls[previewFile.id]"
          class="attachment-preview-video"
          :class="{ 'attachment-preview-content--fit': fit }"
        />
        <iframe
          v-else-if="isHtmlFile(previewFile) && mediaUrls[previewFile.id]"
          :src="mediaUrls[previewFile.id]"
          :title="previewFile.name"
          sandbox="allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads allow-presentation"
          referrerpolicy="no-referrer"
          class="attachment-preview-html"
          :class="{ 'attachment-preview-content--fit': fit }"
        />
        <iframe
          v-else-if="isPdfFile(previewFile) && mediaUrls[previewFile.id]"
          :src="mediaUrls[previewFile.id]"
          :title="t('chat.pdfPreview', { name: previewFile.name })"
          class="attachment-preview-pdf"
          :class="{ 'attachment-preview-content--fit': fit }"
        />
        <TextResourcePreview
          v-else-if="(isMarkdownFile(previewFile) || isTextFile(previewFile)) && hasMediaText(previewFile.id)"
          :content="mediaTexts[previewFile.id]"
          :title="previewFile.name"
          :fit="fit"
          :markdown="isMarkdownFile(previewFile)"
          :media-type="previewFile.mime_type"
        />
        <div v-else-if="isTextFile(previewFile)" class="q-pa-xl text-center">
          <template v-if="mediaLoadErrors[previewFile.id]">
            <p role="alert">{{ t('chat.attachmentPreviewError', { name: previewFile.name }) }}</p>
            <q-btn color="primary" :label="t('chat.retryAttachmentPreview', { name: previewFile.name })" @click="retryMedia(previewFile)" />
          </template>
          <template v-else>
            <q-spinner color="primary" size="32px" />
            <p role="status">{{ t('chat.loadingAttachmentPreview', { name: previewFile.name }) }}</p>
          </template>
        </div>
    </template>
  </FullscreenPreview>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { browserResourceKind, FullscreenPreview, isolatedBrowserResourceUrl, TextResourcePreview, shouldOpenInline, model3dFormat, Model3dThumbnail, Model3dViewer, type Model3dSource } from '@/core/util'
import { TopicBadge, useTopicRefs, type TopicAssignmentChangeScope } from '@/app/topic'
import SafeMessageContent from './SafeMessageContent.vue'
import InteractionChoice from './InteractionChoice.vue'
import InternalAgentAvatar from './InternalAgentAvatar.vue'
import InternalParticipantAvatar from './InternalParticipantAvatar.vue'
import AgentExecutionTrace from './AgentExecutionTrace.vue'
import MarkdownAttachmentPreview from './MarkdownAttachmentPreview.vue'
import MessageResourcePreviews from './MessageResourcePreviews.vue'
import VoiceTranscriptionStatus from './VoiceTranscriptionStatus.vue'
import type { ConversationActivity, ConversationDocumentReference, LiveAgentRound, MessageTopicChange, MessengerFile, MessengerMessage, PendingVoiceTranscription } from '../types'
import { chatService } from '../services/chatService'
import { visibleMessageText } from '../messageDirectives'
import { conversationTimelineEntries, conversationTimelineEntryText, conversationTimelineRenderKey, shouldShowLiveConversationRound } from '../liveState'

const props = withDefaults(defineProps<{ roomId: string; messages: MessengerMessage[]; activity: ConversationActivity[]; liveRound: LiveAgentRound | null; pendingTranscriptions?: PendingVoiceTranscription[]; agentId: number; agentName: string; loading?: boolean; viewerAgentId?: number | null; showAgentAvatars?: boolean; allowReply?: boolean; canReadDocuments?: boolean; canEditDocuments?: boolean }>(), {
  pendingTranscriptions: () => [],
  loading: false,
  viewerAgentId: null,
  showAgentAvatars: true,
  allowReply: true,
  canReadDocuments: false,
  canEditDocuments: false,
})
const emit = defineEmits<{
  reply: [message: MessengerMessage]
  openDocument: [document: Pick<ConversationDocumentReference, 'id' | 'label'>]
  topicChanged: [change: MessageTopicChange]
  blockRendered: []
  layoutChanged: []
  messageVisible: [messageId: string]
}>()
const { t, locale } = useI18n()
const $q = useQuasar()
const { resolveTopicRefs, topicTitle } = useTopicRefs()
const timelineElement = useTemplateRef<HTMLElement>('timelineElement')
const mediaUrls = reactive<Record<string, string>>({})
const mediaTexts = reactive<Record<string, string>>({})
const mediaLoading = reactive<Record<string, boolean>>({})
const mediaLoadErrors = reactive<Record<string, boolean>>({})
const previewOpen = ref(false)
const previewFile = ref<MessengerFile | null>(null)
const speechAvailableAgentIds = ref<Set<number>>(new Set())
const speechLoadingMessageId = ref<string | null>(null)
const speechPlayingMessageId = ref<string | null>(null)
const speechBuffers = new Map<string, AudioBuffer>()
let generation = 0
let mediaScopeKey = ''
let speechContext: AudioContext | null = null
let speechSource: AudioBufferSourceNode | null = null
let speechScopeGeneration = 0
let speechRequestGeneration = 0
let timelineResizeObserver: ResizeObserver | null = null
let messageVisibilityObserver: IntersectionObserver | null = null
const visibleMessageIds = new Set<string>()
const audioFilenamePattern = /\.(?:aac|flac|m4a|mp3|oga|ogg|opus|wav|weba)$/i
const imageFilenamePattern = /\.(?:avif|bmp|gif|ico|jpe?g|png|webp)$/i
const htmlFilenamePattern = /\.x?html?$/i
const pdfFilenamePattern = /\.pdf$/i
const videoFilenamePattern = /\.(?:m4v|mkv|mov|mp4|ogv|webm)$/i
const messagesByExternalId = computed(() => new Map(props.messages.map(message => [message.external_id, message])))
const activityByMessageId = computed(() => new Map(
  props.activity
    .filter(item => item.response_message_id)
    .map(item => [item.response_message_id as string, item]),
))
const activityByRoundId = computed(() => new Map(props.activity.map(item => [item.id, item])))
const roundIdByMessageId = computed(() => {
  const result = new Map<string, string>()
  for (const activity of props.activity) {
    for (const messageId of activity.message_ids ?? []) {
      if (!result.has(messageId)) result.set(messageId, activity.id)
    }
    if (activity.response_message_id) result.set(activity.response_message_id, activity.id)
  }
  return result
})
const showLiveBubble = computed(() => shouldShowLiveConversationRound(
  props.liveRound,
  props.roomId,
  props.activity,
  props.messages,
))
const showEphemeralBubble = computed(() => showLiveBubble.value || props.pendingTranscriptions.length > 0)
const timelineEntries = computed(() => conversationTimelineEntries(
  props.roomId,
  props.messages,
  props.activity,
  props.liveRound,
  props.pendingTranscriptions,
).map(entry => {
  const message = entry.message
  const liveRound = entry.liveRound
  const activity = liveRound
    ? activityByRoundId.value.get(liveRound.round_id)
    : message
      ? activityByMessageId.value.get(message.id)
      : undefined
  const pendingTranscription = entry.pendingTranscription
  return {
    ...entry,
    isMine: message?.is_mine ?? pendingTranscription?.is_mine ?? false,
    senderName: message?.sender?.display_name || pendingTranscription?.sender?.display_name || (liveRound ? props.agentName : t('chat.message')),
    senderAgentId: props.showAgentAvatars
      ? message?.sender?.agent_id ?? pendingTranscription?.sender?.agent_id ?? (liveRound ? props.agentId : null)
      : null,
    avatarUrl: message?.sender?.avatar_url ?? pendingTranscription?.sender?.avatar_url,
    activity,
    copyRoundId: message ? roundIdByMessageId.value.get(message.id) : undefined,
    createdAt: message?.created_at ?? pendingTranscription?.started_at ?? null,
    text: visibleMessageText(conversationTimelineEntryText(entry)),
  }
}))
const timelineRenderKey = computed(() => conversationTimelineRenderKey(
  props.roomId,
  timelineEntries.value,
))
const previewIsImmersive = computed(() => Boolean(
  previewFile.value
  && (
    isImageFile(previewFile.value)
    || isHtmlFile(previewFile.value)
    || isPdfFile(previewFile.value)
    || isVideoFile(previewFile.value)
  ),
))

watch(timelineRenderKey, () => emit('blockRendered'), { flush: 'post', immediate: true })

function emitNewestVisibleMessage(): void {
  const message = [...props.messages].reverse().find(item => visibleMessageIds.has(item.id))
  if (message) emit('messageVisible', message.id)
}

function observeMessageVisibility(): void {
  messageVisibilityObserver?.disconnect()
  visibleMessageIds.clear()
  messageVisibilityObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const messageId = (entry.target as HTMLElement).dataset.messageId
      if (!messageId) continue
      const enoughVisible = entry.isIntersecting && entry.intersectionRect.height >= Math.min(
        80,
        entry.boundingClientRect.height * 0.25,
      )
      if (enoughVisible) visibleMessageIds.add(messageId)
      else visibleMessageIds.delete(messageId)
    }
    emitNewestVisibleMessage()
  }, { threshold: [0, 0.25, 0.5] })
  for (const element of timelineElement.value?.querySelectorAll<HTMLElement>('[data-message-id]') ?? []) {
    messageVisibilityObserver.observe(element)
  }
}

watch(timelineRenderKey, async () => {
  await nextTick()
  observeMessageVisibility()
}, { flush: 'post' })

function repliedMessage(externalId: string): MessengerMessage | undefined {
  const message = messagesByExternalId.value.get(externalId)
  return message ? { ...message, text: visibleMessageText(message.text) } : undefined
}
async function reassignMessageTopic(
  message: MessengerMessage,
  topicId: string,
  scope: TopicAssignmentChangeScope,
): Promise<number> {
  const result = await chatService.updateMessageTopic(props.roomId, message.id, topicId, scope)
  emit('topicChanged', {
    message_id: message.id,
    previous_topic_id: message.topic_id,
    topic_id: topicId,
    scope,
  })
  return result.updated_messages
}
function hasPreviewableReference(text: string): boolean {
  return /[a-z][a-z0-9+.-]*:\/\//i.test(text)
}
function canReadMessage(message: MessengerMessage): boolean {
  const text = message.text.trim()
  const sender = message.sender
  const speakerAgentId = sender?.agent_id
  return sender?.is_ai === true
    && speakerAgentId !== null
    && speakerAgentId !== undefined
    && speechAvailableAgentIds.value.has(speakerAgentId)
    && text.length > 0
    && text.length <= 10_000
}
async function unlockMessageSpeech(): Promise<AudioContext> {
  if (!speechContext || speechContext.state === 'closed') {
    speechContext = new AudioContext()
  }
  if (speechContext.state === 'suspended') await speechContext.resume()
  if (speechContext.state !== 'running') throw new Error('Audio output is unavailable')
  return speechContext
}
function stopMessageSpeech(): void {
  if (speechSource) {
    speechSource.onended = null
    try {
      speechSource.stop()
    } catch {
      // The source may already have reached its natural end.
    }
    speechSource.disconnect()
    speechSource = null
  }
  speechPlayingMessageId.value = null
}
function clearMessageSpeech(): void {
  speechRequestGeneration += 1
  speechLoadingMessageId.value = null
  stopMessageSpeech()
  speechBuffers.clear()
}
function playMessageSpeech(
  messageId: string,
  buffer: AudioBuffer,
  context: AudioContext,
): void {
  stopMessageSpeech()
  const source = context.createBufferSource()
  source.buffer = buffer
  source.connect(context.destination)
  speechSource = source
  speechPlayingMessageId.value = messageId
  source.onended = () => {
    if (speechSource === source) stopMessageSpeech()
  }
  try {
    source.start()
  } catch (error) {
    stopMessageSpeech()
    throw error
  }
}
async function audioContextForMessageSpeech(): Promise<AudioContext | null> {
  try {
    return await unlockMessageSpeech()
  } catch {
    $q.notify({ type: 'negative', message: t('chat.readMessageError') })
    return null
  }
}
async function toggleMessageSpeech(message: MessengerMessage): Promise<void> {
  if (speechPlayingMessageId.value === message.id) {
    stopMessageSpeech()
    return
  }
  const context = await audioContextForMessageSpeech()
  if (!context) return
  const cachedBuffer = speechBuffers.get(message.id)
  if (cachedBuffer) {
    playMessageSpeech(message.id, cachedBuffer, context)
    return
  }
  if (speechLoadingMessageId.value === message.id) return
  const scopeGeneration = speechScopeGeneration
  const requestGeneration = ++speechRequestGeneration
  speechLoadingMessageId.value = message.id
  try {
    const blob = await chatService.messageSpeechBlob(
      props.roomId,
      message.id,
      locale.value,
      props.viewerAgentId,
    )
    if (
      scopeGeneration !== speechScopeGeneration
      || requestGeneration !== speechRequestGeneration
    ) return
    const buffer = await context.decodeAudioData(await blob.arrayBuffer())
    if (
      scopeGeneration !== speechScopeGeneration
      || requestGeneration !== speechRequestGeneration
    ) return
    speechBuffers.set(message.id, buffer)
    playMessageSpeech(message.id, buffer, context)
  } catch {
    if (
      scopeGeneration === speechScopeGeneration
      && requestGeneration === speechRequestGeneration
    ) $q.notify({ type: 'negative', message: t('chat.readMessageError') })
  } finally {
    if (requestGeneration === speechRequestGeneration) speechLoadingMessageId.value = null
  }
}
async function loadMessageSpeechStatus(): Promise<void> {
  const currentGeneration = ++speechScopeGeneration
  clearMessageSpeech()
  speechAvailableAgentIds.value = new Set()
  try {
    const result = await chatService.messageSpeechStatus(props.roomId, props.viewerAgentId)
    if (currentGeneration === speechScopeGeneration) {
      speechAvailableAgentIds.value = new Set(result.available_agent_ids)
    }
  } catch {
    // A missing or inaccessible voice simply leaves the optional action hidden.
  }
}
function isAudioFile(file: MessengerFile): boolean {
  const mimeType = file.mime_type.toLowerCase()
  return file.kind === 'audio'
    || mimeType.startsWith('audio/')
    || ['application/ogg', 'application/x-ogg'].includes(mimeType)
    || audioFilenamePattern.test(file.name)
}
function isModel3dFile(file: MessengerFile): boolean {
  return model3dFormat(file.mime_type, file.name) !== null
}
function modelSource(file: MessengerFile): Model3dSource {
  const roomId = props.roomId
  const viewerAgentId = props.viewerAgentId
  return {
    key: `${roomId}:${viewerAgentId ?? 'user'}:${file.id}:${file.name}`,
    name: file.name,
    mediaType: file.mime_type,
    size: file.size_bytes,
    load: () => chatService.attachmentBlob(roomId, file.id, viewerAgentId),
  }
}
function isImageFile(file: MessengerFile): boolean {
  return file.kind === 'image'
    || file.mime_type.toLowerCase().startsWith('image/')
    || imageFilenamePattern.test(file.name)
}
function isMarkdownFile(file: MessengerFile): boolean {
  return browserResourceKind(file.mime_type, file.name) === 'markdown'
}
function isTextFile(file: MessengerFile): boolean {
  return browserResourceKind(file.mime_type, file.name) === 'text'
}
function isHtmlFile(file: MessengerFile): boolean {
  const mimeType = file.mime_type.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  return ['text/html', 'application/xhtml+xml'].includes(mimeType)
    || htmlFilenamePattern.test(file.name)
}
function isPdfFile(file: MessengerFile): boolean {
  return file.mime_type.toLowerCase() === 'application/pdf' || pdfFilenamePattern.test(file.name)
}
function isVideoFile(file: MessengerFile): boolean {
  return file.kind === 'video'
    || file.mime_type.toLowerCase().startsWith('video/')
    || videoFilenamePattern.test(file.name)
}
function isPreviewableFile(file: MessengerFile): boolean {
  return isAudioFile(file)
    || isImageFile(file)
    || isHtmlFile(file)
    || isPdfFile(file)
    || isVideoFile(file)
    || isTextFile(file)
}
function hasMediaText(fileId: string): boolean {
  return Object.hasOwn(mediaTexts, fileId)
}
function canOpenPreview(file: MessengerFile): boolean {
  if (isModel3dFile(file)) return true
  if (isTextFile(file)) return true
  if (isMarkdownFile(file)) return hasMediaText(file.id)
  return Boolean(mediaUrls[file.id]) && (
    isImageFile(file) || isHtmlFile(file) || isPdfFile(file) || isVideoFile(file)
  )
}
function openPreview(file: MessengerFile): void {
  if (!canOpenPreview(file)) return
  previewFile.value = file
  previewOpen.value = true
}
function storeMarkdownContent(fileId: string, content: string): void {
  mediaTexts[fileId] = content
}
function attachmentStandaloneHref(file: MessengerFile): string | undefined {
  if (isHtmlFile(file) || isImageFile(file) || isPdfFile(file) || isVideoFile(file)) {
    return mediaUrls[file.id]
  }
  return undefined
}
function attachmentAction(event: Event, file: MessengerFile): void {
  if (canOpenPreview(file)) {
    if (!(event instanceof MouseEvent) || !shouldOpenInline(event)) return
    event.preventDefault()
    openPreview(file)
    return
  }
  event.preventDefault()
  void download(file.id, file.name)
}
function retryMedia(file: MessengerFile): void {
  delete mediaLoadErrors[file.id]
  void loadMedia([file])
}
function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
async function copyRoundId(roundId: string | undefined): Promise<void> {
  if (!roundId) return
  try {
    await navigator.clipboard.writeText(roundId)
    $q.notify({ type: 'positive', icon: 'content_copy', message: t('chat.roundIdCopied'), timeout: 1600 })
  } catch {
    $q.notify({ type: 'negative', icon: 'error', message: t('chat.copyRoundIdError') })
  }
}
function clearMedia(): void {
  for (const url of Object.values(mediaUrls)) URL.revokeObjectURL(url)
  for (const key of Object.keys(mediaUrls)) delete mediaUrls[key]
  for (const key of Object.keys(mediaTexts)) delete mediaTexts[key]
  for (const key of Object.keys(mediaLoading)) delete mediaLoading[key]
  for (const key of Object.keys(mediaLoadErrors)) delete mediaLoadErrors[key]
}

async function loadMedia(requestedFiles?: MessengerFile[]): Promise<void> {
  const scopeKey = `${props.roomId}:${props.viewerAgentId ?? 'user'}`
  if (mediaScopeKey !== scopeKey) {
    generation += 1
    clearMedia()
    mediaScopeKey = scopeKey
    previewOpen.value = false
    previewFile.value = null
  }
  const currentGeneration = generation
  const visibleFileIds = new Set(
    props.messages.flatMap(message => message.files.map(file => file.id)),
  )
  for (const [fileId, url] of Object.entries(mediaUrls)) {
    if (visibleFileIds.has(fileId)) continue
    URL.revokeObjectURL(url)
    delete mediaUrls[fileId]
  }
  for (const fileId of Object.keys(mediaTexts)) {
    if (!visibleFileIds.has(fileId)) delete mediaTexts[fileId]
  }
  for (const fileId of Object.keys(mediaLoadErrors)) {
    if (!visibleFileIds.has(fileId)) delete mediaLoadErrors[fileId]
  }
  if (previewFile.value && !visibleFileIds.has(previewFile.value.id)) {
    previewOpen.value = false
    previewFile.value = null
  }
  const files = requestedFiles ?? props.messages.flatMap(message => message.files)
  for (const file of files) {
      if (
        !isPreviewableFile(file)
        || mediaUrls[file.id]
        || hasMediaText(file.id)
        || mediaLoading[file.id]
        || mediaLoadErrors[file.id]
      ) continue
      mediaLoading[file.id] = true
      try {
        const blob = await chatService.attachmentBlob(props.roomId, file.id, props.viewerAgentId)
        if (isTextFile(file)) {
          const text = await blob.text()
          if (currentGeneration !== generation) return
          mediaTexts[file.id] = text
          continue
        }
        if (currentGeneration !== generation) return
        const objectUrl = isHtmlFile(file)
          ? await chatService.standaloneHtmlPreview(blob, file.name)
          : await isolatedBrowserResourceUrl(blob, file.mime_type, file.name)
        if (currentGeneration !== generation) {
          if (objectUrl.startsWith('blob:')) URL.revokeObjectURL(objectUrl)
          return
        }
        mediaUrls[file.id] = objectUrl
        delete mediaLoadErrors[file.id]
      } catch {
        if (currentGeneration === generation) mediaLoadErrors[file.id] = true
      } finally {
        if (currentGeneration === generation) delete mediaLoading[file.id]
      }
  }
}

async function download(fileId: string, name: string): Promise<void> {
  try { await chatService.downloadFile(props.roomId, fileId, name, props.viewerAgentId) }
  catch (error) { $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('chat.error') }) }
}

const mediaSignature = computed(() => props.messages
  .flatMap(message => message.files)
  .map(file => `${file.id}:${file.name}:${file.mime_type}:${file.kind}`)
  .join('|'))
watch(
  () => [props.roomId, props.viewerAgentId, mediaSignature.value] as const,
  () => void loadMedia(),
  { immediate: true },
)
watch(
  () => props.messages.map(message => message.topic_id),
  topicIds => { void resolveTopicRefs(topicIds) },
  { immediate: true },
)
watch(
  () => props.liveRound?.topic_id ?? null,
  topicId => { void resolveTopicRefs([topicId]) },
  { immediate: true },
)
watch(
  () => [props.roomId, props.viewerAgentId] as const,
  () => void loadMessageSpeechStatus(),
  { immediate: true },
)
watch(
  () => props.messages.map(message => message.id),
  messageIds => {
    const visible = new Set(messageIds)
    if (speechPlayingMessageId.value && !visible.has(speechPlayingMessageId.value)) {
      stopMessageSpeech()
    }
    for (const messageId of speechBuffers.keys()) {
      if (visible.has(messageId)) continue
      speechBuffers.delete(messageId)
    }
  },
)
onMounted(() => {
  timelineResizeObserver = new ResizeObserver(() => emit('layoutChanged'))
  if (timelineElement.value) timelineResizeObserver.observe(timelineElement.value)
  observeMessageVisibility()
})
onBeforeUnmount(() => {
  timelineResizeObserver?.disconnect()
  timelineResizeObserver = null
  messageVisibilityObserver?.disconnect()
  messageVisibilityObserver = null
  visibleMessageIds.clear()
  generation += 1
  speechScopeGeneration += 1
  clearMedia()
  clearMessageSpeech()
  if (speechContext && speechContext.state !== 'closed') {
    void speechContext.close()
  }
  speechContext = null
})
</script>
<style scoped>
.model3d-attachment { display: block; width: 260px; max-width: 100%; height: 180px; overflow: hidden; border-radius: 8px; }
.message-timeline { box-sizing: border-box; width: 100%; min-width: 0; min-height: 100%; padding: 18px 20px 28px; overflow-x: hidden; color: var(--chat-text, #252b36); background: var(--chat-page-bg, #f1f3f6); }
.conversation-loading-state,.conversation-empty-state { display: flex; min-height: min(320px, 48vh); align-items: center; justify-content: center; }
.conversation-loading-state { flex-direction: column; gap: 13px; color: var(--chat-text-secondary, #596274); }
.conversation-loading-bubble { position: relative; display: flex; width: 62px; height: 40px; align-items: center; justify-content: center; gap: 5px; background: var(--chat-surface-raised, #fff); border: 1px solid color-mix(in srgb, var(--q-primary) 26%, var(--chat-border, rgba(53, 69, 94, .14))); border-radius: 18px 18px 18px 6px; box-shadow: 0 5px 18px color-mix(in srgb, var(--q-primary) 12%, transparent); }
.conversation-loading-bubble span { width: 7px; height: 7px; background: var(--q-primary); border-radius: 50%; animation: conversation-loading-dot 1.2s ease-in-out infinite; }
.conversation-loading-bubble span:nth-child(2) { animation-delay: .14s; }
.conversation-loading-bubble span:nth-child(3) { animation-delay: .28s; }
.conversation-loading-label { font-size: .82rem; font-weight: 600; letter-spacing: .01em; }
@keyframes conversation-loading-dot { 0%,60%,100% { opacity: .38; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-5px); } }
.message-row { box-sizing: border-box; display: flex; width: 100%; min-width: 0; max-width: 100%; align-items: flex-start; gap: 9px; margin: 0 0 16px; padding-right: calc(6% + 20px); }
.message-row--sent { flex-direction: row-reverse; padding-right: 0; padding-left: calc(6% + 20px); }
.message-row--live { align-items: flex-start; }
.message-avatar { flex: 0 0 auto; margin-top: 16px; }
.message-stack { display: flex; flex: 1 1 0; width: auto; min-width: 0; max-width: none; flex-direction: column; }
.message-row--sent .message-stack { align-items: flex-end; }
.message-meta { display: flex; width: auto; min-width: 0; max-width: 100%; min-height: 15px; align-items: center; flex-wrap: wrap; gap: 4px; margin: 0 5px 3px; color: var(--chat-text-secondary, #596274); font-size: .68rem; font-weight: 500; line-height: 1.2; }
.message-row--sent .message-meta { justify-content: flex-end; }
.message-sender { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 650; }
.message-round-copy { display: inline-flex; min-width: 0; align-items: center; gap: 4px; padding: 0; color: inherit; font: inherit; line-height: inherit; text-align: inherit; background: transparent; border: 0; cursor: copy; }
.message-round-copy:hover:not(:disabled),.message-round-copy:focus-visible:not(:disabled) { color: var(--q-primary); text-decoration: underline; text-underline-offset: 2px; }
.message-round-copy:focus-visible { border-radius: 3px; outline: 2px solid color-mix(in srgb, var(--q-primary) 45%, transparent); outline-offset: 2px; }
.message-round-copy:disabled { cursor: default; }
.message-bubble { box-sizing: border-box; width: 100%; min-width: 42px; max-width: 100%; padding: 8px 11px; overflow: hidden; color: var(--chat-text, #20242c); background: var(--chat-surface-raised, #fff); border: 1px solid var(--chat-received-border, rgba(86, 105, 137, .2)); border-radius: 0 13px 13px 13px; box-shadow: 0 2px 9px var(--chat-shadow, rgba(31, 45, 61, .07)); }
.message-bubble--live { min-width: 66px; }
.message-row--sent .message-bubble { background: var(--chat-surface-sent, #e6efff); border-radius: 13px 0 13px 13px; border-color: color-mix(in srgb, var(--q-primary) 42%, var(--chat-border, transparent)); }
.message-row:not(.message-row--sent) .execution-trace { border-radius: 0 10px 0 0; }
.message-row--sent .execution-trace { border-radius: 10px 0 0 0; }
.message-body { position: relative; min-width: 0; max-width: 100%; }
.message-text { overflow-wrap: anywhere; font-size: calc(1em + 1pt); }
.reply-preview { max-width: 420px; border-left: 2px solid currentColor; padding-left: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.message-actions { display: inline-flex; align-items: center; gap: 2px; margin: -2px 0 -2px auto; }
.message-action { min-height: 15px; padding: 0 2px; color: var(--chat-text-secondary, #596274); font-size: .67rem; font-weight: 600; line-height: 1; opacity: 1; }
.message-action:hover,.message-action:focus-visible { color: var(--q-primary); }
.message-action :deep(.q-icon) { margin-left: 3px; font-size: 11px; }
.attachment { min-width: 0; }
.attachment-actions { display: flex; min-width: 0; align-items: center; gap: 2px; }
.attachment-actions :deep(.q-btn:first-child) { flex: 0 1 auto; min-width: 0; max-width: 100%; }
.attachment-actions :deep(.q-btn:first-child .q-btn__content) { min-width: 0; flex-wrap: nowrap; }
.attachment-actions :deep(.q-btn:first-child .block) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.audio-note { display: block; width: min(420px, 100%); max-width: 100%; }
.image-preview-button { display: block; max-width: 100%; padding: 0; background: transparent; border: 0; border-radius: 8px; cursor: zoom-in; }
.image-preview-button:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 2px; }
.image-preview { display: block; width: auto; max-width: 100%; height: auto; object-fit: contain; background: var(--chat-surface-soft, #0000000a); border-radius: 8px; }
.video-player { display: block; width: auto; max-width: 100%; max-height: min(520px, 62vh); background: #000; border-radius: 8px; }
.pdf-reader { display: block; width: 100%; height: min(520px, 62vh); min-height: 320px; background: var(--chat-surface-raised, #fff); border: 1px solid var(--chat-border, rgba(53, 69, 94, .14)); border-radius: 8px; }
.attachment-preview-image { display: block; width: auto; max-width: none; height: auto; max-height: none; margin: 0 auto; object-fit: contain; }
.attachment-preview-image.attachment-preview-content--fit { max-width: 100vw; max-height: var(--galaris-preview-height, 100dvh); }
.attachment-preview-video { display: block; width: auto; max-width: none; height: auto; max-height: none; margin: 0 auto; background: #000; }
.attachment-preview-video.attachment-preview-content--fit { max-width: 100vw; max-height: var(--galaris-preview-height, 100dvh); }
.attachment-preview-html,.attachment-preview-pdf { display: block; width: 1280px; height: 800px; background: var(--chat-surface-raised, #fff); border: 0; }
.attachment-preview-html.attachment-preview-content--fit,.attachment-preview-pdf.attachment-preview-content--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); }

@media (max-width: 599px) {
  .message-timeline { padding: 14px 10px 24px; }
  .message-row { padding-right: calc(3% + 20px); }
  .message-row--sent { padding-right: 0; padding-left: calc(3% + 20px); }
}
@media (prefers-reduced-motion: reduce) {
  .conversation-loading-bubble span { animation: none; opacity: .75; }
}
</style>
