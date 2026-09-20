<template>
  <div class="topic-editor">
    <div class="thread-heading">
      <div>
        <div class="text-subtitle2 text-weight-medium">{{ t('evaluation.topicEditor.conversation') }}</div>
        <div class="text-caption text-grey-7">{{ t('evaluation.topicEditor.sequenceHelp') }}</div>
      </div>
    </div>

    <div class="role-legend">
      <q-chip dense color="blue-grey" text-color="white" icon="person">{{ t('evaluation.topicEditor.human') }}</q-chip>
      <q-chip dense color="deep-purple" text-color="white" icon="smart_toy">{{ t('evaluation.topicEditor.ai') }}</q-chip>
      <span class="text-caption text-grey-7">{{ t('evaluation.topicEditor.identitiesIgnored') }}</span>
    </div>

    <div class="message-thread">
      <article
        v-for="(message, index) in model.messages"
        :key="message.id || index"
        class="message-row"
        :class="{ 'message-row--ai': isAi(message) }"
      >
        <div v-if="index > 0" class="message-gap">
          <q-icon name="schedule" size="14px" />
          {{ elapsedTime(model.messages[index - 1]?.time ?? 0, message.time) }}
        </div>
        <div class="message-bubble">
          <div class="message-bubble-heading">
            <div class="row items-center q-gutter-sm">
              <q-avatar :color="isAi(message) ? 'deep-purple' : 'blue-grey'" text-color="white" size="30px">
                <q-icon :name="isAi(message) ? 'smart_toy' : 'person'" size="18px" />
              </q-avatar>
              <strong>{{ isAi(message) ? t('evaluation.topicEditor.ai') : t('evaluation.topicEditor.human') }}</strong>
              <q-btn-toggle
                v-if="!readonly"
                :model-value="isAi(message) ? 'assistant' : 'human'"
                dense
                unelevated
                toggle-color="deep-purple"
                color="grey-3"
                text-color="grey-8"
                :options="roleOptions"
                @update:model-value="value => updateRole(message, value)"
              />
            </div>
            <q-btn
              v-if="!readonly && model.messages.length > 1"
              flat
              round
              dense
              size="sm"
              color="negative"
              icon="delete_outline"
              :aria-label="t('evaluation.topicEditor.deleteMessage')"
              @click="removeMessage(index)"
            />
          </div>

          <q-input
            v-if="!readonly"
            v-model="message.text"
            type="textarea"
            autogrow
            outlined
            dense
            :label="t('evaluation.topicEditor.messageText')"
          />
          <div v-else class="message-text">{{ message.text }}</div>

          <div class="message-metadata">
            <q-input
              v-if="!readonly"
              :model-value="datetimeLocal(message.time)"
              type="datetime-local"
              dense
              borderless
              stack-label
              :label="t('evaluation.topicEditor.timestamp')"
              @update:model-value="value => updateTimestamp(message, String(value ?? ''))"
            />
            <span v-else><q-icon name="schedule" /> {{ formatMessageTime(message.time) }}</span>
          </div>

          <div class="expected-topic">
            <q-icon name="topic" color="deep-purple" size="22px" />
            <q-input
              :model-value="expectedTopics[index] ?? ''"
              outlined
              dense
              class="expected-topic-input"
              :readonly="readonly"
              :label="t('evaluation.topicEditor.expectedTopicForMessage')"
              @update:model-value="value => updateExpectedTopic(index, String(value ?? ''))"
            />
          </div>

          <div
            v-if="calculatedTopics !== null"
            class="calculated-topic"
            :class="topicMatches(index) ? 'calculated-topic--matching' : 'calculated-topic--different'"
          >
            <q-icon :name="topicMatches(index) ? 'check_circle' : 'cancel'" size="22px" />
            <div class="calculated-topic-value">
              <div class="text-caption text-weight-medium">{{ t('evaluation.topicEditor.calculatedTopicForMessage') }}</div>
              <div>{{ calculatedTopics[index] || t('evaluation.topicEditor.noCalculatedTopic') }}</div>
            </div>
            <q-badge :color="topicMatches(index) ? 'positive' : 'negative'">
              {{ topicMatches(index) ? t('evaluation.topicEditor.matchesExpected') : t('evaluation.topicEditor.differsExpected') }}
            </q-badge>
          </div>

          <q-chip v-if="sourceTopic(message)" dense outline color="grey-7" icon="history">
            {{ t('evaluation.topicEditor.detectedTopic') }} · {{ sourceTopic(message) }}
          </q-chip>
        </div>
      </article>
    </div>

    <div v-if="!readonly" class="add-message-footer">
      <q-btn
        outline
        color="deep-purple"
        icon="add_comment"
        :label="t('evaluation.topicEditor.addMessage')"
        @click="addMessage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TopicDetectionLabInput, TopicLabMessage } from '../services/mechanismEvaluationService'

const { sourceCapture = {}, readonly = false, calculatedTopics = null } = defineProps<{
  sourceCapture?: Record<string, unknown>
  readonly?: boolean
  calculatedTopics?: string[] | null
}>()
const model = defineModel<TopicDetectionLabInput>({ required: true })
const expectedTopics = defineModel<string[]>('expectedTopics', { required: true })
const { t, locale } = useI18n()

const roleOptions = computed(() => [
  { label: t('evaluation.topicEditor.human'), value: 'human' },
  { label: t('evaluation.topicEditor.ai'), value: 'assistant' },
])
const capturedTopics = computed(() => {
  const result = new Map<string, string>()
  const directMessages = Array.isArray(sourceCapture.messages) ? sourceCapture.messages : []
  const ecosystem = asRecord(sourceCapture.ecosystem)
  const ecosystemMessages = Array.isArray(ecosystem.messages) ? ecosystem.messages : []
  for (const value of [...directMessages, ...ecosystemMessages]) {
    const item = asRecord(value)
    const message = asRecord(item.message)
    const messageId = typeof message.id === 'string'
      ? message.id
      : typeof item.remote_message_id === 'string' ? item.remote_message_id : ''
    const topic = typeof item.detected_topic === 'string' ? item.detected_topic.trim() : ''
    if (messageId && topic) result.set(messageId, topic)
  }
  return result
})

watch(() => model.value.messages.length, syncExpectedTopics, { immediate: true })

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function syncExpectedTopics(): void {
  const topics = [...expectedTopics.value]
  while (topics.length < model.value.messages.length) topics.push('')
  if (topics.length > model.value.messages.length) topics.length = model.value.messages.length
  expectedTopics.value = topics
}

function isAi(message: TopicLabMessage): boolean {
  return message.sender?.agent_id != null
}

function updateRole(message: TopicLabMessage, role: string): void {
  message.sender = {
    id: role === 'assistant' ? 'assistant' : 'human',
    display_name: '',
    agent_id: role === 'assistant' ? 1 : null,
  }
}

function updateExpectedTopic(index: number, value: string): void {
  const topics = [...expectedTopics.value]
  topics[index] = value
  expectedTopics.value = topics
}

function topicMatches(index: number): boolean {
  const expected = expectedTopics.value[index]?.trim().toLocaleLowerCase() ?? ''
  const calculated = calculatedTopics?.[index]?.trim().toLocaleLowerCase() ?? ''
  return Boolean(expected && calculated && expected === calculated)
}

function sourceTopic(message: TopicLabMessage): string {
  return capturedTopics.value.get(message.id) ?? ''
}

function addMessage(): void {
  const previous = model.value.messages.at(-1)
  const ai = previous == null ? false : !isAi(previous)
  model.value.messages.push({
    id: `lab-message-${Date.now()}`,
    platform: 'lab',
    tool_id: null,
    sender: { id: ai ? 'assistant' : 'human', display_name: '', agent_id: ai ? 1 : null },
    recipient: null,
    room: { id: 'exchange', label: '', kind: 'direct', users: [] },
    text: '',
    attachments: [],
    reply_to: null,
    time: previous?.time ? previous.time + 60 : Math.floor(Date.now() / 1000),
  })
  expectedTopics.value = [...expectedTopics.value, '']
}

function removeMessage(index: number): void {
  model.value.messages.splice(index, 1)
  const topics = [...expectedTopics.value]
  topics.splice(index, 1)
  expectedTopics.value = topics
}

function datetimeLocal(timestamp: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function updateTimestamp(message: TopicLabMessage, value: string): void {
  const timestamp = Date.parse(value)
  message.time = Number.isNaN(timestamp) ? 0 : Math.floor(timestamp / 1000)
}

function formatMessageTime(timestamp: number): string {
  return timestamp
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(timestamp * 1000))
    : t('evaluation.topicEditor.unknownTimestamp')
}

function elapsedTime(previous: number, current: number): string {
  if (!previous || !current) return t('evaluation.topicEditor.unknownGap')
  const seconds = Math.max(0, current - previous)
  if (seconds < 60) return t('evaluation.topicEditor.elapsed', { duration: `${seconds} s` })
  if (seconds < 3_600) return t('evaluation.topicEditor.elapsed', { duration: `${Math.round(seconds / 60)} min` })
  if (seconds < 86_400) return t('evaluation.topicEditor.elapsed', { duration: `${Math.round(seconds / 3_600)} h` })
  return t('evaluation.topicEditor.elapsed', { duration: t('evaluation.topicEditor.daysShort', { count: Math.round(seconds / 86_400) }) })
}
</script>

<style scoped>
.topic-editor { display: grid; gap: 14px; min-width: 0; max-width: 100%; }
.thread-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.role-legend { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.message-thread { display: grid; gap: 10px; min-width: 0; }
.add-message-footer { display: flex; justify-content: center; padding: 8px 0 4px; }
.message-row { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; }
.message-row--ai { align-items: flex-end; }
.message-bubble { display: grid; width: min(780px, 90%); min-width: 0; gap: 12px; padding: 14px; border: 1px solid rgba(96, 125, 139, 0.28); border-radius: 4px 18px 18px 18px; background: rgba(96, 125, 139, 0.06); }
.message-row--ai .message-bubble { border-color: rgba(103, 58, 183, 0.3); border-radius: 18px 4px 18px 18px; background: rgba(103, 58, 183, 0.07); }
.message-bubble-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; }
.message-bubble-heading > .row { min-width: 0; flex-wrap: wrap; }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.message-metadata { display: flex; align-items: center; gap: 12px; color: #757575; font-size: 0.78rem; }
.message-metadata > * { width: min(260px, 100%); }
.message-gap { align-self: center; margin: 2px 0 8px; color: #757575; font-size: 0.75rem; }
.expected-topic { display: flex; align-items: center; gap: 10px; min-width: 0; padding-top: 10px; border-top: 1px solid rgba(103, 58, 183, 0.18); }
.expected-topic-input { flex: 1 1 auto; min-width: 0; }
.calculated-topic { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px; border: 1px solid; border-radius: 8px; }
.calculated-topic--matching { border-color: rgba(33, 186, 69, 0.35); background: rgba(33, 186, 69, 0.08); color: #16853a; }
.calculated-topic--different { border-color: rgba(193, 0, 21, 0.3); background: rgba(193, 0, 21, 0.07); color: #a00018; }
.calculated-topic-value { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
@media (max-width: 699px) {
  .thread-heading { align-items: flex-start; flex-direction: column; }
  .message-bubble { width: 97%; }
  .message-bubble-heading { align-items: flex-start; }
  .message-bubble-heading > .row { align-items: flex-start; }
  .expected-topic { align-items: flex-start; }
  .calculated-topic { align-items: flex-start; flex-wrap: wrap; }
}
</style>
