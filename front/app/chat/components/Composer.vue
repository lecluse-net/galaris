<template>
  <div class="composer-shell q-pa-sm" :inert="preparingSend">
    <div v-if="replyTo" class="reply-target row items-center no-wrap bg-grey-2 q-mb-xs">
      <q-icon name="reply" size="13px" class="q-mr-xs" />
      <div class="ellipsis text-caption">
        <span class="text-weight-medium">{{ t('chat.replyTo', { name: replyTo.sender?.display_name || t('chat.message') }) }}</span>
        · {{ visibleMessageText(replyTo.text) }}
      </div>
      <q-space />
      <q-btn flat round dense size="xs" icon="close" :aria-label="t('chat.cancel')" @click="$emit('cancel-reply')" />
    </div>

    <div class="composer-layout">
      <div
        ref="attachmentDropZone"
        class="attachment-drop-zone"
        :class="{
          'attachment-drop-zone--active': dragActive,
          'attachment-drop-zone--disabled': sending,
          'attachment-drop-zone--populated': files.length > 0,
        }"
        role="button"
        :tabindex="sending ? -1 : 0"
        :aria-label="t('chat.addAttachments')"
        @click="openFilePicker"
        @keydown.enter.prevent="openFilePicker"
        @keydown.space.prevent="openFilePicker"
        @dragenter.prevent="dragActive = true"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="handleDrop"
      >
        <input
          ref="fileInput"
          hidden
          class="attachment-file-input"
          type="file"
          multiple
          :disabled="sending"
          @change="handleFileSelection"
        />
        <q-icon name="attach_file" size="22px" class="portrait-attachment-icon" />
        <q-badge v-if="files.length" floating rounded color="primary" class="portrait-attachment-count">
          {{ files.length }}
        </q-badge>
        <div v-if="!files.length" class="attachment-empty">
          <q-icon name="upload_file" size="22px" color="primary" />
          <div class="attachment-empty-copy">
            <span class="text-weight-medium">{{ t('chat.dropAttachments') }}</span>
          </div>
        </div>
        <div v-else class="attachment-list">
          <div
            v-for="(pendingFile, index) in files"
            :key="fileKey(pendingFile)"
            class="attachment-item"
          >
            <q-icon name="attach_file" size="17px" color="primary" />
            <span class="attachment-name">{{ pendingFile.name }}</span>
            <q-btn
              flat
              round
              dense
              size="xs"
              icon="close"
              :aria-label="t('chat.removeAttachment', { name: pendingFile.name })"
              @click.stop="removeFile(index)"
            >
              <q-tooltip>{{ t('chat.removeAttachment', { name: pendingFile.name }) }}</q-tooltip>
            </q-btn>
          </div>
        </div>
      </div>

      <div class="composer-fields">
        <div class="composer-input-shell" @focusout="handleCommandHelpFocusOut">
          <q-input
            ref="messageInput"
            v-model="text"
            dense
            outlined
            autogrow
            :placeholder="t('chat.write')"
            @keydown="handleCommandHelpKeydown"
            @keydown.enter="handleEnter"
            @keydown.esc="commandHelpOpen = false"
          >
            <template #prepend>
              <EmojiPicker @select="insertEmoji" @error="$emit('error', $event)" />
            </template>
            <template #append>
              <div
                ref="composerActions"
                class="composer-actions"
                :class="{ 'composer-actions--stacked': actionsStacked }"
              >
                <q-btn
                  v-if="commandHelpAvailable"
                  round
                  flat
                  dense
                  icon="alternate_email"
                  class="command-help-button"
                  :aria-label="t('chat.commandHelp.open')"
                  :aria-expanded="commandHelpOpen"
                  :aria-controls="commandHelpId"
                  @click.stop="commandHelpOpen = !commandHelpOpen"
                >
                  <q-tooltip>{{ t('chat.commandHelp.open') }}</q-tooltip>
                </q-btn>
                <q-btn
                  round
                  flat
                  dense
                  :color="dictating ? 'negative' : dictationBusy ? 'warning' : 'primary'"
                  :icon="dictating ? 'stop' : dictationBusy ? 'hourglass_top' : 'mic'"
                  :disable="sending || (dictationBusy && !dictating)"
                  :aria-label="t(dictating ? 'chat.stopDictation' : dictationBusy ? 'chat.dictationInProgress' : 'chat.startDictation')"
                  @click="toggleDictation"
                />
                <q-btn
                  unelevated
                  dense
                  color="primary"
                  icon="send"
                  class="composer-send-button"
                  :aria-label="t('chat.post')"
                  :loading="sending || preparingSend"
                  :disable="!canSubmit"
                  @click="submit"
                >
                  <q-tooltip>{{ t('chat.post') }}</q-tooltip>
                </q-btn>
              </div>
            </template>
          </q-input>

          <div
            v-if="commandHelpOpen && commandHelpAvailable"
            :id="commandHelpId"
            class="command-help-panel"
            role="region"
            :aria-label="t('chat.commandHelp.title')"
          >
            <div class="command-menu-heading">
              <div class="text-weight-medium">{{ t('chat.commandHelp.title') }}</div>
              <div class="command-menu-hint">{{ t('chat.commandHelp.hint') }}</div>
            </div>
            <q-separator />
            <q-list dense class="command-menu-list">
              <q-item
                v-for="command in commands"
                :key="command"
                clickable
                dense
                class="command-menu-item"
                @mousedown.prevent
                @click="insertCommand(command)"
              >
                <q-item-section side class="command-tag-section">
                  <q-badge outline color="primary">@{{ command }}</q-badge>
                </q-item-section>
                <q-item-section>{{ t(`chat.commandHelp.commands.${command}`) }}</q-item-section>
              </q-item>
              <q-item
                v-if="canSelectTopic"
                clickable
                dense
                class="command-menu-item"
                @mousedown.prevent
                @click="insertDirective('topic')"
              >
                <q-item-section side class="command-tag-section">
                  <q-badge outline color="deep-purple">@topic</q-badge>
                </q-item-section>
                <q-item-section>{{ t('chat.commandHelp.commands.topic') }}</q-item-section>
              </q-item>
            </q-list>
          </div>
        </div>

        <TopicSelect
          v-if="canSelectTopic && topicSelectOpen"
          :key="roomId"
          :model-value="topicId"
          allow-create
          :disable="sending"
          dense
          outlined
          clearable
          hide-bottom-space
          class="topic-context-select"
          :label="t('chat.currentTopic')"
          @update:model-value="$emit('update:topicId', $event)"
        />

        <div v-if="effortSelectOpen" class="effort-context-control">
          <div class="effort-context-control__header">
            <span class="text-caption text-weight-medium">
              {{ t('chat.reasoningEffort') }}
            </span>
            <q-chip dense square color="primary" text-color="white">
              {{ t(`chat.reasoningEfforts.${reasoningEffort}`) }}
            </q-chip>
          </div>
          <q-slider
            :model-value="reasoningEffortIndex"
            :min="REASONING_LEVEL_MIN"
            :max="REASONING_LEVEL_MAX"
            :step="1"
            markers
            snap
            color="primary"
            :aria-label="t('chat.reasoningEffort')"
            @update:model-value="updateReasoningEffortIndex"
          />
          <div class="effort-context-control__legend text-grey-7" aria-hidden="true">
            <span
              v-for="level in REASONING_LEVELS"
              :key="level.effort"
              :class="{ 'text-weight-bold': reasoningEffortIndex === level.value }"
            >
              {{ t(`chat.reasoningEfforts.${level.effort}`) }}
            </span>
          </div>
          <div class="text-caption text-grey-7 q-mt-sm">
            {{ t('chat.reasoningEffortHint') }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="files.length" class="portrait-attachment-list">
      <div
        v-for="(pendingFile, index) in files"
        :key="fileKey(pendingFile)"
        class="attachment-item"
      >
        <q-icon name="attach_file" size="17px" color="primary" />
        <span class="attachment-name">{{ pendingFile.name }}</span>
        <q-btn
          flat
          round
          dense
          size="xs"
          icon="close"
          :aria-label="t('chat.removeAttachment', { name: pendingFile.name })"
          @click="removeFile(index)"
        >
          <q-tooltip>{{ t('chat.removeAttachment', { name: pendingFile.name }) }}</q-tooltip>
        </q-btn>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { TopicSelect } from '@/app/topic'
import { chatService, DictationNotConfiguredError } from '../services/chatService'
import { visibleMessageText } from '../messageDirectives'
import type { ChatCommandCode, MessengerMessage, ReasoningEffort } from '../types'
import EmojiPicker from './EmojiPicker.vue'

const MAX_ATTACHMENTS = 20
const DICTATION_SEGMENT_MILLISECONDS = 3_000
const REASONING_LEVELS = [
  { value: 0, effort: 'none' },
  { value: 1, effort: 'low' },
  { value: 2, effort: 'medium' },
  { value: 3, effort: 'high' },
  { value: 4, effort: 'xhigh' },
  { value: 5, effort: 'max' },
] as const satisfies ReadonlyArray<{ value: number; effort: ReasoningEffort }>
const REASONING_LEVEL_MIN = REASONING_LEVELS[0].value
const REASONING_LEVEL_MAX = REASONING_LEVELS[REASONING_LEVELS.length - 1].value
const DEFAULT_REASONING_LEVEL = 2

const props = withDefaults(defineProps<{
  roomId: string
  sending: boolean
  beforeSend?: () => Promise<boolean>
  commands?: readonly ChatCommandCode[]
  replyTo?: MessengerMessage | null
  topicId?: string | null
  canSelectTopic?: boolean
  maxAttachmentBytes?: number
}>(), {
  replyTo: null,
  commands: () => [],
  topicId: null,
  canSelectTopic: false,
  maxAttachmentBytes: 0,
})
const emit = defineEmits<{
  send: [text: string, files?: File[], reasoningEffortOverride?: ReasoningEffort, taskRequested?: boolean]
  error: [error: unknown]
  'cancel-reply': []
  'update:topicId': [value: string | null]
}>()
const text = ref('')
const preparingSend = ref(false)
const files = ref<File[]>([])
const reasoningEffortIndex = ref(DEFAULT_REASONING_LEVEL)
const dictating = ref(false)
const preparingDictation = ref(false)
const transcribing = ref(false)
const dictationBusy = computed(() => dictating.value || preparingDictation.value || transcribing.value)
const dragActive = ref(false)
const commandHelpOpen = ref(false)
const commandHelpAvailable = computed(() => props.commands.length > 0 || props.canSelectTopic)
const commandHelpId = useId()
const topicSelectOpen = computed(() => props.canSelectTopic && hasTopicDirective(text.value))
const effortSelectOpen = computed(() => hasEffortDirective(text.value))
const taskRequested = computed(() => (
  hasTaskDirective(text.value) || hasPlanDirective(text.value) || effortSelectOpen.value
))
const reasoningEffort = computed<ReasoningEffort>(() => (
  REASONING_LEVELS.find(level => level.value === reasoningEffortIndex.value)?.effort
  ?? 'medium'
))
const outgoingText = computed(() => {
  const withoutTopic = props.canSelectTopic ? stripTopicDirectives(text.value) : text.value
  return withoutTopic.trim()
})
const canSubmit = computed(() => (
  !props.sending && !preparingSend.value && !dictationBusy.value && Boolean(outgoingText.value || files.value.length)
))
type MessageInputRef = {
  getNativeElement: () => HTMLInputElement | HTMLTextAreaElement
}
const messageInput = useTemplateRef<MessageInputRef>('messageInput')
const composerActions = useTemplateRef<HTMLElement>('composerActions')
const attachmentDropZone = useTemplateRef<HTMLElement>('attachmentDropZone')
const actionsStacked = ref(false)
let composerResizeObserver: ResizeObserver | null = null
let composerLayoutFrame: number | null = null
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const { locale, t } = useI18n()
let recorder: MediaRecorder | null = null
let recordingStream: MediaStream | null = null
let segmentTimer: number | null = null
let dictationGeneration = 0
let recordedChunks: Blob[] = []
let recordedMimeType = 'audio/webm'
let lastTranscript = ''
let audioRevision = 0
let transcribedRevision = 0
let transcriptionRunning = false
let suppressCommandHelpOpen = false

function updateComposerLayout(): void {
  composerLayoutFrame = null
  const input = messageInput.value?.getNativeElement()
  const actions = composerActions.value
  const inputContainer = input?.parentElement
  const append = actions?.parentElement
  if (!(input instanceof HTMLTextAreaElement) || !actions || !inputContainer || !append) return

  const buttons = Array.from(actions.children).filter((child): child is HTMLButtonElement => (
    child instanceof HTMLButtonElement
  ))
  const buttonSizes = buttons.map(button => button.getBoundingClientRect())
  if (!buttonSizes.length || !input.clientWidth) return
  const columnWidth = Math.max(...buttonSizes.map(size => size.width))
  const columnHeight = buttonSizes.reduce((height, size) => height + size.height, 0)
  const inputWidth = input.getBoundingClientRect().width
  const columnInputWidth = inputWidth + actions.getBoundingClientRect().width - columnWidth

  // Always decide using the wider, column-layout text. Measuring the current
  // layout would oscillate when that extra width removes a wrapped line.
  const measure = input.cloneNode(false) as HTMLTextAreaElement
  measure.removeAttribute('id')
  measure.removeAttribute('name')
  measure.removeAttribute('placeholder')
  measure.tabIndex = -1
  measure.setAttribute('aria-hidden', 'true')
  Object.assign(measure.style, {
    position: 'absolute', visibility: 'hidden', pointerEvents: 'none',
    height: '0', minHeight: '0', maxHeight: 'none',
    width: `${columnInputWidth}px`, maxWidth: 'none', overflow: 'hidden',
  })
  measure.value = input.value
  inputContainer.appendChild(measure)
  try {
    const containerStyle = getComputedStyle(inputContainer)
    const appendStyle = getComputedStyle(append)
    const textHeight = measure.scrollHeight
      + parseFloat(containerStyle.paddingTop) + parseFloat(containerStyle.paddingBottom)
    const dropZone = attachmentDropZone.value
    const dropStyle = dropZone ? getComputedStyle(dropZone) : null
    const attachmentContent = dropZone?.querySelector<HTMLElement>('.attachment-list, .attachment-empty')
    // Use the upload content's natural height, not its stretched height, which
    // may still reflect text wrapping in the previous action layout.
    const uploadHeight = dropStyle?.alignSelf === 'stretch' && attachmentContent
      ? attachmentContent.getBoundingClientRect().height
        + parseFloat(dropStyle.paddingTop) + parseFloat(dropStyle.paddingBottom)
        + parseFloat(dropStyle.borderTopWidth) + parseFloat(dropStyle.borderBottomWidth)
      : 0
    const availableHeight = Math.max(textHeight, uploadHeight)
      - parseFloat(appendStyle.paddingTop) - parseFloat(appendStyle.paddingBottom)
    actionsStacked.value = availableHeight >= columnHeight

    // Quasar grows on text edits; also refresh its native height after a width
    // change, including window resizing and switching the action layout.
    measure.style.width = `${inputWidth}px`
    const height = Math.max(measure.scrollHeight, parseFloat(getComputedStyle(input).minHeight) || 0)
    input.style.height = `${height}px`
  } finally {
    measure.remove()
  }
}

function scheduleComposerLayout(): void {
  if (composerLayoutFrame === null) {
    composerLayoutFrame = requestAnimationFrame(updateComposerLayout)
  }
}

onMounted(() => {
  composerResizeObserver = new ResizeObserver(scheduleComposerLayout)
  const input = messageInput.value?.getNativeElement()
  if (input) composerResizeObserver.observe(input)
  if (composerActions.value) composerResizeObserver.observe(composerActions.value)
  if (attachmentDropZone.value) composerResizeObserver.observe(attachmentDropZone.value)
  scheduleComposerLayout()
})

watch([text, commandHelpAvailable, files], scheduleComposerLayout, { flush: 'post' })

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}:${file.type}`
}

function rejectOversized(file: File): boolean {
  if (props.maxAttachmentBytes <= 0 || file.size <= props.maxAttachmentBytes) return false
  emit('error', new Error(t('chat.attachmentTooLarge', { name: file.name })))
  return true
}

function addFiles(candidates: Iterable<File>): void {
  const selected = new Map(files.value.map(file => [fileKey(file), file]))
  for (const file of candidates) {
    if (!rejectOversized(file)) selected.set(fileKey(file), file)
  }
  const nextFiles = [...selected.values()]
  if (nextFiles.length > MAX_ATTACHMENTS) {
    emit('error', new Error(t('chat.tooManyAttachments', { count: MAX_ATTACHMENTS })))
  }
  files.value = nextFiles.slice(0, MAX_ATTACHMENTS)
}

function openFilePicker(): void {
  if (!props.sending) fileInput.value?.click()
}

function handleFileSelection(event: Event): void {
  const input = event.target as HTMLInputElement
  addFiles(input.files ?? [])
  input.value = ''
}

function handleDrop(event: DragEvent): void {
  dragActive.value = false
  if (!props.sending) addFiles(event.dataTransfer?.files ?? [])
}

function removeFile(index: number): void {
  files.value = files.value.filter((_file, fileIndex) => fileIndex !== index)
}

interface TranscriptToken {
  end: number
  normalized: string
}

function transcriptTokens(value: string): TranscriptToken[] {
  return [...value.matchAll(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu)].map(match => ({
    end: (match.index ?? 0) + match[0].length,
    normalized: match[0].normalize('NFKC').toLocaleLowerCase(),
  }))
}

function newTranscriptSuffix(previous: string, current: string): string {
  const next = current.trim()
  const old = previous.trim()
  if (!next) return ''
  if (!old) return next
  if (next.startsWith(old)) return next.slice(old.length).trimStart()

  const oldTokens = transcriptTokens(old)
  const nextTokens = transcriptTokens(next)
  const maximumOverlap = Math.min(oldTokens.length, nextTokens.length)
  for (let overlap = maximumOverlap; overlap >= 2; overlap -= 1) {
    const oldStart = oldTokens.length - overlap
    for (let nextStart = nextTokens.length - overlap; nextStart >= 0; nextStart -= 1) {
      const matches = Array.from(
        { length: overlap },
        (_value, offset) => oldTokens[oldStart + offset]?.normalized
          === nextTokens[nextStart + offset]?.normalized,
      ).every(Boolean)
      if (matches) return next.slice(nextTokens[nextStart + overlap - 1]?.end).trimStart()
    }
  }

  let bestOldStart = -1
  let bestNextStart = -1
  let bestLength = 0
  const oldestCandidate = Math.max(0, oldTokens.length - 40)
  for (let oldStart = oldestCandidate; oldStart < oldTokens.length; oldStart += 1) {
    for (let nextStart = 0; nextStart < nextTokens.length; nextStart += 1) {
      let length = 0
      while (
        oldStart + length < oldTokens.length
        && nextStart + length < nextTokens.length
        && oldTokens[oldStart + length]?.normalized
        === nextTokens[nextStart + length]?.normalized
      ) {
        length += 1
      }
      const oldEnd = oldStart + length
      const bestOldEnd = bestOldStart + bestLength
      if (length > bestLength || (length === bestLength && oldEnd > bestOldEnd)) {
        bestOldStart = oldStart
        bestNextStart = nextStart
        bestLength = length
      }
    }
  }
  const singleAnchor = bestLength === 1
    ? oldTokens[bestOldStart]?.normalized ?? ''
    : ''
  if (bestLength >= 2 || singleAnchor.length >= 4) {
    const oldTailLength = oldTokens.length - (bestOldStart + bestLength)
    const nextBoundary = bestNextStart + bestLength + oldTailLength - 1
    if (nextBoundary >= 0 && nextBoundary < nextTokens.length) {
      return next.slice(nextTokens[nextBoundary]?.end).trimStart()
    }
  }
  return ''
}

function appendDictation(existing: string, addition: string): string {
  let spokenText = addition.trim()
  if (!spokenText) return existing
  const trimmedExisting = existing.trimEnd()
  if (/[,.!?;:…]$/.test(trimmedExisting) && /^[,.!?;:…]+/.test(spokenText)) {
    spokenText = spokenText.replace(/^[,.!?;:…]+\s*/, '')
  }
  if (!spokenText) return existing
  const separator = existing
    && !/\s$/.test(existing)
    && !/^[,.;:!?…)}\]]/.test(spokenText)
    && !/[({[]$/.test(existing)
    ? ' '
    : ''
  return `${existing}${separator}${spokenText}`
}

function stopRecordingStream(): void {
  for (const track of recordingStream?.getTracks() ?? []) track.stop()
  recordingStream = null
}

function cancelDictation(): void {
  dictationGeneration += 1
  if (segmentTimer !== null) {
    window.clearTimeout(segmentTimer)
    segmentTimer = null
  }
  if (recorder) {
    const activeRecorder = recorder
    recorder = null
    activeRecorder.onstart = null
    activeRecorder.ondataavailable = null
    activeRecorder.onerror = null
    activeRecorder.onstop = null
    try {
      if (activeRecorder.state !== 'inactive') activeRecorder.stop()
    } catch {
      // The browser may already have ended the recording segment.
    }
  }
  stopRecordingStream()
  dictating.value = false
  preparingDictation.value = false
  transcribing.value = false
  recordedChunks = []
  lastTranscript = ''
  audioRevision = 0
  transcribedRevision = 0
  transcriptionRunning = false
}

function recorderMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/ogg;codecs=opus',
    'audio/mp4',
    'audio/webm',
    'audio/ogg',
  ]
  return candidates.find(candidate => MediaRecorder.isTypeSupported(candidate)) ?? ''
}

async function transcribeRecordedAudio(generation: number): Promise<void> {
  if (generation !== dictationGeneration || transcriptionRunning) return
  transcriptionRunning = true
  transcribing.value = true
  try {
    while (
      generation === dictationGeneration
      && transcribedRevision < audioRevision
    ) {
      const revision = audioRevision
      const blob = new Blob(recordedChunks, { type: recordedMimeType })
      const result = await chatService.transcribeDictation(props.roomId, blob, locale.value)
      if (generation === dictationGeneration && result.text.trim()) {
        const addition = newTranscriptSuffix(lastTranscript, result.text)
        if (addition) {
          text.value = appendDictation(text.value, addition)
          lastTranscript = result.text
        }
      }
      transcribedRevision = revision
    }
  } catch (error) {
    if (generation !== dictationGeneration) return
    cancelDictation()
    emit('error', new Error(t(
      error instanceof DictationNotConfiguredError
        ? 'chat.dictationNotConfigured'
        : 'chat.dictationError',
    )))
  } finally {
    if (generation === dictationGeneration) {
      transcriptionRunning = false
      transcribing.value = transcribedRevision < audioRevision
      if (transcribing.value) void transcribeRecordedAudio(generation)
    }
  }
}

function scheduleTranscriptionSnapshot(generation: number): void {
  if (segmentTimer !== null) window.clearTimeout(segmentTimer)
  segmentTimer = window.setTimeout(() => {
    if (
      generation === dictationGeneration
      && recorder?.state === 'recording'
    ) {
      recorder.requestData()
      scheduleTranscriptionSnapshot(generation)
    }
  }, DICTATION_SEGMENT_MILLISECONDS)
}

function startContinuousRecording(generation: number): void {
  if (generation !== dictationGeneration || !preparingDictation.value || !recordingStream) return
  const mimeType = recorderMimeType()
  const activeRecorder = new MediaRecorder(
    recordingStream,
    mimeType ? { mimeType } : undefined,
  )
  recorder = activeRecorder
  recordedChunks = []
  recordedMimeType = activeRecorder.mimeType || mimeType || 'audio/webm'
  activeRecorder.onstart = () => {
    if (generation !== dictationGeneration) return
    preparingDictation.value = false
    dictating.value = true
    scheduleTranscriptionSnapshot(generation)
  }
  activeRecorder.ondataavailable = event => {
    if (generation !== dictationGeneration || !event.data.size) return
    recordedChunks.push(event.data)
    audioRevision += 1
    void transcribeRecordedAudio(generation)
  }
  activeRecorder.onerror = () => {
    if (generation !== dictationGeneration) return
    cancelDictation()
    emit('error', new Error(t('chat.microphoneAccessError')))
  }
  activeRecorder.onstop = () => {
    if (segmentTimer !== null) {
      window.clearTimeout(segmentTimer)
      segmentTimer = null
    }
    if (recorder === activeRecorder) recorder = null
    if (generation !== dictationGeneration) return
    preparingDictation.value = false
    dictating.value = false
    stopRecordingStream()
    transcribing.value = transcriptionRunning || transcribedRevision < audioRevision
  }
  activeRecorder.start()
}

async function startDictation(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    emit('error', new Error(t('chat.dictationUnsupported')))
    return
  }

  cancelDictation()
  const generation = dictationGeneration
  preparingDictation.value = true
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    if (generation !== dictationGeneration) {
      for (const track of stream.getTracks()) track.stop()
      return
    }
    recordingStream = stream
    lastTranscript = ''
    startContinuousRecording(generation)
  } catch (error) {
    if (generation !== dictationGeneration) return
    cancelDictation()
    emit('error', new Error(t('chat.microphoneAccessError')))
  }
}

function toggleDictation(): void {
  if (dictating.value) {
    dictating.value = false
    transcribing.value = true
    if (segmentTimer !== null) {
      window.clearTimeout(segmentTimer)
      segmentTimer = null
    }
    if (recorder?.state === 'recording') recorder.stop()
    else {
      stopRecordingStream()
      transcribing.value = transcriptionRunning || transcribedRevision < audioRevision
    }
  } else if (!dictationBusy.value) {
    void startDictation()
  }
}

function handleEnter(event: KeyboardEvent): void {
  if (event.shiftKey || event.isComposing) return
  event.preventDefault()
  submit()
}

function handleCommandHelpKeydown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === ' ') {
    commandHelpOpen.value = false
  } else if (event.key === '@' && commandHelpAvailable.value) {
    commandHelpOpen.value = true
  }
}

function insertedText(previous: string, current: string): string {
  let prefixLength = 0
  while (
    prefixLength < previous.length
    && prefixLength < current.length
    && previous[prefixLength] === current[prefixLength]
  ) {
    prefixLength += 1
  }

  let suffixLength = 0
  while (
    suffixLength < previous.length - prefixLength
    && suffixLength < current.length - prefixLength
    && previous[previous.length - suffixLength - 1] === current[current.length - suffixLength - 1]
  ) {
    suffixLength += 1
  }

  return current.slice(prefixLength, current.length - suffixLength)
}

function handleCommandHelpFocusOut(event: FocusEvent): void {
  const nextTarget = event.relatedTarget
  if (!(nextTarget instanceof Node) || !(event.currentTarget as HTMLElement).contains(nextTarget)) {
    commandHelpOpen.value = false
  }
}

function mentionSpacing(prefix: string, suffix: string): { leading: string; trailing: string } {
  return {
    leading: prefix && !/[\s([{]$/.test(prefix) ? ' ' : '',
    trailing: suffix && !/^[\s,.;:!?…)}\]]/.test(suffix) ? ' ' : '',
  }
}

function insertDirective(command: ChatCommandCode | 'topic'): void {
  const input = messageInput.value?.getNativeElement()
  const selectionStart = input?.selectionStart ?? text.value.length
  const selectionEnd = input?.selectionEnd ?? selectionStart
  const beforeSelection = text.value.slice(0, selectionStart)
  const activeMention = /(^|[^\p{L}\p{N}_])(@[\p{L}\p{N}_]*)$/u.exec(beforeSelection)
  const mentionStart = activeMention?.index === undefined
    ? selectionStart
    : activeMention.index + (activeMention[1]?.length ?? 0)
  let mentionEnd = selectionEnd
  while (/^[\p{L}\p{N}_]$/u.test(text.value[mentionEnd] ?? '')) mentionEnd += 1
  const prefix = text.value.slice(0, mentionStart)
  const suffix = text.value.slice(mentionEnd)
  const mention = `@${command}`
  const { leading, trailing } = mentionSpacing(prefix, suffix)

  suppressCommandHelpOpen = true
  text.value = `${prefix}${leading}${mention}${trailing}${suffix}`
  commandHelpOpen.value = false
  const cursor = prefix.length + leading.length + mention.length + trailing.length
  void nextTick(() => {
    suppressCommandHelpOpen = false
    const updatedInput = messageInput.value?.getNativeElement()
    updatedInput?.focus({ preventScroll: true })
    updatedInput?.setSelectionRange(cursor, cursor)
  })
}

function insertCommand(command: ChatCommandCode): void {
  insertDirective(command)
}

function hasTopicDirective(value: string): boolean {
  return /(^|[^\p{L}\p{N}_])@topic(?=$|[^\p{L}\p{N}_])/iu.test(value)
}

function hasTaskDirective(value: string): boolean {
  return /(^|[^\p{L}\p{N}_])@task(?=$|[^\p{L}\p{N}_])/iu.test(value)
}

function hasPlanDirective(value: string): boolean {
  return /(^|[^\p{L}\p{N}_])@plan(?=$|[^\p{L}\p{N}_])/iu.test(value)
}

function hasEffortDirective(value: string): boolean {
  return /(^|[^\p{L}\p{N}_])@effort(?=$|[^\p{L}\p{N}_])/iu.test(value)
}

function stripTopicDirectives(value: string): string {
  return value.replace(
    /(^|[^\p{L}\p{N}_])@topic(?=$|[^\p{L}\p{N}_])(?:[ \t]+)?/giu,
    '$1',
  )
}

function updateReasoningEffortIndex(value: number | null): void {
  if (value !== null && Number.isInteger(value)) reasoningEffortIndex.value = value
}

function insertEmoji(emoji: string): void {
  const input = messageInput.value?.getNativeElement()
  const start = input?.selectionStart ?? text.value.length
  const end = input?.selectionEnd ?? start
  text.value = `${text.value.slice(0, start)}${emoji}${text.value.slice(end)}`
  const cursor = start + emoji.length
  void nextTick(() => {
    const updatedInput = messageInput.value?.getNativeElement()
    updatedInput?.focus({ preventScroll: true })
    updatedInput?.setSelectionRange(cursor, cursor)
  })
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  const oversized = files.value.find(rejectOversized)
  if (oversized) return
  if (props.beforeSend) {
    const roomId = props.roomId
    preparingSend.value = true
    try {
      if (!await props.beforeSend() || props.roomId !== roomId) return
    } catch (error) {
      emit('error', error)
      return
    } finally {
      preparingSend.value = false
    }
  }
  cancelDictation()
  emit(
    'send',
    outgoingText.value,
    files.value.length ? [...files.value] : undefined,
    effortSelectOpen.value ? reasoningEffort.value : undefined,
    taskRequested.value,
  )
  commandHelpOpen.value = false
  text.value = ''
  files.value = []
  reasoningEffortIndex.value = DEFAULT_REASONING_LEVEL
}

onBeforeUnmount(() => {
  composerResizeObserver?.disconnect()
  if (composerLayoutFrame !== null) cancelAnimationFrame(composerLayoutFrame)
  cancelDictation()
})

watch(text, (current, previous) => {
  if (hasTopicDirective(current) && !hasTopicDirective(previous)) {
    commandHelpOpen.value = false
    return
  }
  if (
    !suppressCommandHelpOpen
    && commandHelpAvailable.value
    && insertedText(previous, current).includes('@')
  ) {
    commandHelpOpen.value = true
  }
})

watch(commandHelpAvailable, available => {
  if (!available) {
    commandHelpOpen.value = false
  } else if (text.value.includes('@')) {
    commandHelpOpen.value = true
  }
})

watch(topicSelectOpen, (visible, wasVisible) => {
  if (!visible && wasVisible && props.topicId !== null) emit('update:topicId', null)
})

watch(effortSelectOpen, (visible, wasVisible) => {
  if (!visible && wasVisible) reasoningEffortIndex.value = DEFAULT_REASONING_LEVEL
})

watch(() => props.roomId, () => {
  cancelDictation()
  commandHelpOpen.value = false
  reasoningEffortIndex.value = DEFAULT_REASONING_LEVEL
})
</script>

<style scoped>
.reply-target {
  min-height: 24px;
  max-height: 24px;
  padding: 1px 4px 1px 7px;
  border-left: 2px solid var(--q-primary);
  border-radius: 3px;
  overflow: hidden;
  color: var(--chat-text-secondary, #596274);
  background: var(--chat-surface-soft, #f5f7fa) !important;
}

.composer-shell {
  flex: 0 0 auto;
  color: var(--chat-text, #252b36);
  background: var(--chat-surface, #fff);
}

.composer-layout {
  display: grid;
  grid-template-columns: clamp(140px, calc(15% + 50px), 230px) minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
}

.composer-fields {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.topic-context-select {
  width: 100%;
}

.effort-context-control {
  width: 100%;
  padding: 8px 12px 10px;
  border: 1px solid var(--chat-border-strong, rgba(35, 46, 66, .14));
  border-radius: 4px;
  background: var(--chat-surface-soft, #f5f7fa);
}

.effort-context-control__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.effort-context-control__legend {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 4px;
  font-size: 10px;
  line-height: 1.2;
  text-align: center;
}

.attachment-drop-zone {
  box-sizing: border-box;
  min-height: 40px;
  align-self: stretch;
  padding: 6px 7px;
  border: 1px dashed var(--chat-border-strong, rgba(35, 46, 66, .22));
  border-radius: 5px;
  overflow: hidden;
  cursor: pointer;
  color: var(--chat-text-secondary, #596274);
  background: var(--chat-surface-soft, #f5f7fa);
  transition: border-color .15s ease, background-color .15s ease;
}

.attachment-drop-zone--populated {
  padding-bottom: 16px;
}

.attachment-drop-zone:hover,
.attachment-drop-zone:focus-visible,
.attachment-drop-zone--active {
  border-color: var(--q-primary);
  outline: none;
  background: color-mix(in srgb, var(--q-primary) 8%, var(--chat-surface, #fff));
}

.attachment-drop-zone--disabled {
  cursor: default;
  opacity: .65;
}

.attachment-file-input {
  display: none;
}

.portrait-attachment-icon,
.portrait-attachment-count,
.portrait-attachment-list {
  display: none;
}

.attachment-empty {
  display: flex;
  min-height: 26px;
  align-items: center;
  gap: 6px;
  text-align: left;
}

.attachment-empty-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: 1;
}

.attachment-list {
  display: flex;
  max-height: 118px;
  flex-direction: column;
  gap: 3px;
  overflow-y: auto;
}

.attachment-item {
  display: flex;
  min-width: 0;
  min-height: 26px;
  align-items: center;
  gap: 3px;
  padding-left: 3px;
  border-radius: 4px;
  background: var(--chat-surface, #fff);
}

.attachment-name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-input-shell {
  position: relative;
}

.composer-actions {
  display: flex;
  align-items: flex-end;
}

.composer-actions--stacked {
  flex-direction: column;
  align-items: center;
}

.composer-send-button {
  width: 36px;
  height: 36px;
  min-height: 36px;
  padding: 0;
  border-radius: 2px;
}

.composer-input-shell :deep(.q-field__control) {
  padding-right: 4px;
}

.command-help-button :deep(.q-icon) {
  font-size: 18px;
}

.composer-input-shell :deep(.q-field__append) {
  height: auto;
  align-self: stretch;
  align-items: flex-end;
  padding-top: 4px;
  padding-bottom: 4px;
}

.command-help-panel {
  position: absolute;
  left: 0;
  bottom: calc(100% + 4px);
  z-index: 10;
  width: min(480px, calc(100vw - 24px));
  max-height: min(480px, calc(100vh - 32px));
  overflow-y: auto;
  color: var(--chat-text, #252b36);
  border-radius: 4px;
  border: 1px solid var(--chat-border-strong, rgba(35, 46, 66, .14));
  box-shadow: 0 4px 14px rgba(0, 0, 0, .16);
  background: var(--chat-surface, #fff);
}

:global(body.body--dark .command-help-panel) {
  color: #e7ebf2;
  border-color: rgba(255, 255, 255, .15);
  background: #24282f;
}

.command-menu-heading {
  padding: 10px 12px 8px;
}

.command-menu-hint {
  margin-top: 2px;
  color: var(--chat-text-secondary, #596274);
  font-size: 12px;
  line-height: 1.3;
}

:global(body.body--dark .command-menu-hint) {
  color: #c3ccda;
}

.command-menu-list {
  padding: 4px 0;
  font-size: 13px;
}

.command-menu-item {
  cursor: pointer;
}

.command-tag-section {
  width: 92px;
  flex: 0 0 92px;
  align-items: flex-start;
}

@media (min-width: 1024px) {
  .composer-fields {
    display: contents;
  }

  .topic-context-select,
  .effort-context-control {
    grid-column: 2;
  }

  .composer-input-shell,
  .composer-input-shell :deep(.q-field),
  .composer-input-shell :deep(.q-field__inner) {
    display: grid;
  }

  .composer-input-shell :deep(.q-field__control) {
    height: 100%;
  }
}

@media (max-width: 1023.98px) {
  .composer-layout {
    grid-template-columns: 40px minmax(0, 1fr);
    align-items: start;
  }

  .attachment-drop-zone {
    position: relative;
    display: flex;
    width: 40px;
    height: 40px;
    min-height: 40px;
    align-items: center;
    justify-content: center;
    align-self: start;
    padding: 0;
    overflow: visible;
    border-style: solid;
    border-radius: 50%;
    color: var(--q-primary);
    background: transparent;
  }

  .attachment-empty,
  .attachment-drop-zone > .attachment-list {
    display: none;
  }

  .portrait-attachment-icon {
    display: inline-flex;
  }

  .portrait-attachment-count {
    display: flex;
    top: -7px;
    right: -7px;
  }

  .portrait-attachment-list {
    display: flex;
    max-height: 72px;
    margin: 6px 0 0 48px;
    flex-direction: column;
    gap: 3px;
    overflow-y: auto;
  }
}
</style>
