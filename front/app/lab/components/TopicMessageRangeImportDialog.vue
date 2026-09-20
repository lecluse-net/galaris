<template>
  <q-dialog v-model="dialogOpen">
    <q-card class="range-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="col dialog-heading">
          <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.topicImport.title') }}</div>
          <div class="text-caption text-blue-1">{{ t('evaluation.topicImport.help') }}</div>
        </div>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-separator />

      <q-card-section class="filters">
        <q-select
          v-model="agentId"
          :options="agentOptions"
          emit-value
          map-options
          outlined
          :loading="agentsLoading"
          :aria-label="t('evaluation.topicImport.ai')"
        >
          <template #prepend>
            <q-avatar v-if="selectedAgent" color="deep-purple" text-color="white" size="28px">
              {{ agentInitials(selectedAgent.label) }}
            </q-avatar>
          </template>
          <template #option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section avatar>
                <q-avatar color="deep-purple" text-color="white" size="32px">
                  {{ agentInitials(scope.opt.label) }}
                </q-avatar>
              </q-item-section>
              <q-item-section><q-item-label>{{ scope.opt.label }}</q-item-label></q-item-section>
            </q-item>
          </template>
        </q-select>
        <q-select
          v-model="personKey"
          :options="personOptions"
          emit-value
          map-options
          outlined
          :loading="peopleLoading"
          :disable="agentId == null"
          :label="t('evaluation.topicImport.person')"
        />
        <q-input v-model="dateFrom" type="datetime-local" outlined stack-label :label="t('evaluation.topicImport.dateFrom')" />
        <q-input v-model="dateTo" type="datetime-local" outlined stack-label :label="t('evaluation.topicImport.dateTo')" />
        <q-btn
          color="deep-purple"
          outline
          icon="preview"
          :label="t('evaluation.topicImport.preview')"
          :loading="previewLoading"
          :disable="!canPreview"
          @click="loadPreview"
        />
      </q-card-section>

      <q-separator />
      <q-scroll-area class="preview-scroll">
        <div v-if="previewLoading" class="flex flex-center q-pa-xl">
          <q-spinner color="deep-purple" size="42px" />
        </div>
        <div v-else-if="preview" class="preview-content">
          <q-banner v-if="preview.truncated" rounded class="bg-orange-1 text-orange-10">
            <template #avatar><q-icon name="warning_amber" /></template>
            {{ t('evaluation.topicImport.tooMany', { count: preview.total_count }) }}
          </q-banner>
          <div class="row items-center justify-between q-gutter-sm">
            <div class="text-subtitle2">{{ t('evaluation.topicImport.messageCount', { count: preview.total_count }) }}</div>
            <div class="text-caption text-grey-7">{{ t('evaluation.topicImport.rolesHelp') }}</div>
          </div>
          <div v-if="preview.messages.length" class="message-thread">
            <article
              v-for="(item, index) in preview.messages"
              :key="item.journal_message_id"
              class="message-row"
              :class="{ 'message-row--assistant': item.role === 'assistant' }"
            >
              <div v-if="index > 0" class="message-gap">
                <q-icon name="schedule" size="14px" />
                {{ elapsedTime(preview.messages[index - 1]?.message.time ?? 0, item.message.time) }}
              </div>
              <div class="message-bubble">
                <div class="row items-center q-gutter-sm">
                  <q-avatar :color="item.role === 'assistant' ? 'deep-purple' : 'blue-grey'" text-color="white" size="28px">
                    <q-icon :name="item.role === 'assistant' ? 'smart_toy' : 'person'" size="17px" />
                  </q-avatar>
                  <strong>{{ item.role === 'assistant' ? t('evaluation.topicImport.aiRole') : t('evaluation.topicImport.humanRole') }}</strong>
                  <span class="text-caption text-grey-7">{{ formatDate(item.occurred_at) }}</span>
                </div>
                <div class="message-text">{{ item.message.text }}</div>
                <q-chip v-if="item.detected_topic" dense outline color="deep-purple" icon="label">
                  {{ t('evaluation.topicImport.detectedTopic') }} · {{ item.detected_topic }}
                </q-chip>
              </div>
            </article>
          </div>
          <div v-else class="text-center text-grey-7 q-pa-xl">{{ t('evaluation.topicImport.noMessages') }}</div>
        </div>
        <div v-else class="preview-empty">
          <q-icon name="forum" size="56px" color="grey-5" />
          <div>{{ t('evaluation.topicImport.previewEmpty') }}</div>
        </div>
      </q-scroll-area>

      <q-separator />
      <q-card-actions align="right" class="q-px-md galaris-dialog-actions">
        <q-btn v-close-popup outline :label="t('evaluation.close')" />
        <q-btn
          color="deep-purple"
          icon="download"
          :label="t('evaluation.topicImport.importExchange')"
          :loading="importing"
          :disable="!canImport"
          @click="importExchange"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
  <LabCaptureConfirmation :mismatch="captureMismatch" @confirm="confirmCapture" @cancel="cancelCapture" />
</template>

<script setup lang="ts">
import LabCaptureConfirmation from './LabCaptureConfirmation.vue'
import { useCaptureConfirmation } from '../services/useCaptureConfirmation'
import { computed, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import {
  mechanismEvaluationService,
  type MechanismCase,
  type TopicMessageAgent,
  type TopicMessagePerson,
  type TopicMessageRangeFilter,
  type TopicMessageRangePreview,
} from '../services/mechanismEvaluationService'

const { datasetId } = defineProps<{ datasetId: string }>()
const emit = defineEmits<{ imported: [value: MechanismCase] }>()
const dialogOpen = defineModel<boolean>({ required: true })
const { mismatch: captureMismatch, run: withCaptureConfirmation, confirm: confirmCapture, cancel: cancelCapture } = useCaptureConfirmation()
const { t, locale } = useI18n()
const $q = useQuasar()

const agents = ref<TopicMessageAgent[]>([])
const people = ref<TopicMessagePerson[]>([])
const agentId = ref<number | null>(null)
const personKey = ref('')
const dateFrom = ref(datetimeLocal(new Date(Date.now() - 7 * 86_400_000)))
const dateTo = ref(datetimeLocal(new Date()))
const preview = ref<TopicMessageRangePreview | null>(null)
const agentsLoading = ref(false)
const peopleLoading = ref(false)
const previewLoading = ref(false)
const importing = ref(false)

const agentOptions = computed(() => agents.value.map((agent) => ({
  label: `${agent.label} · ${t('evaluation.topicImport.messageCount', { count: agent.message_count })}`,
  value: agent.id,
})))
const selectedAgent = computed(() => (
  agents.value.find(agent => agent.id === agentId.value) ?? null
))
const personOptions = computed(() => people.value.map((person) => ({
  label: `${person.platform} · ${person.label} · ${t('evaluation.topicImport.messageCount', { count: person.message_count })}`,
  value: personValue(person),
})))
const selectedPerson = computed(() => people.value.find((person) => personValue(person) === personKey.value) ?? null)
const canPreview = computed(() => agentId.value != null && selectedPerson.value != null && Boolean(dateFrom.value && dateTo.value))
const canImport = computed(() => preview.value != null && preview.value.messages.length > 0 && !preview.value.truncated)

watch(dialogOpen, async (open) => {
  if (!open || agents.value.length) return
  agentsLoading.value = true
  try {
    agents.value = (await mechanismEvaluationService.topicMessageAgents()).data
  } catch (error) {
    notifyError(error)
  } finally {
    agentsLoading.value = false
  }
})

watch(agentId, async (value) => {
  people.value = []
  personKey.value = ''
  preview.value = null
  if (value == null) return
  peopleLoading.value = true
  try {
    people.value = (await mechanismEvaluationService.topicMessagePeople(value)).data
  } catch (error) {
    notifyError(error)
  } finally {
    peopleLoading.value = false
  }
})

watch([personKey, dateFrom, dateTo], () => { preview.value = null })

function personValue(person: TopicMessagePerson): string {
  return `${person.connection_id}:${person.user_id}`
}

function agentInitials(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean)
  return `${parts[0]?.[0] ?? ''}${parts.at(-1)?.[0] ?? ''}`.toLocaleUpperCase() || '?'
}

function datetimeLocal(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function filterValue(): TopicMessageRangeFilter {
  const person = selectedPerson.value
  if (agentId.value == null || person == null) throw new Error(t('evaluation.topicImport.incompleteFilter'))
  return {
    agent_id: agentId.value,
    connection_id: person.connection_id,
    user_id: person.user_id,
    date_from: new Date(dateFrom.value).toISOString(),
    date_to: new Date(dateTo.value).toISOString(),
  }
}

async function loadPreview(): Promise<void> {
  previewLoading.value = true
  try {
    preview.value = (await mechanismEvaluationService.previewTopicMessageRange(filterValue())).data
  } catch (error) {
    notifyError(error)
  } finally {
    previewLoading.value = false
  }
}

async function importExchange(): Promise<void> {
  importing.value = true
  try {
    const filter = filterValue()
    const response = await withCaptureConfirmation(token => mechanismEvaluationService.importTopicMessageRange(datasetId, filter, token))
    if (!response) return
    const created = response.data
    emit('imported', created)
    dialogOpen.value = false
  } catch (error) {
    notifyError(error)
  } finally {
    importing.value = false
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function elapsedTime(previous: number, current: number): string {
  if (!previous || !current) return t('evaluation.topicEditor.unknownGap')
  const seconds = Math.max(0, current - previous)
  if (seconds < 60) return t('evaluation.topicEditor.elapsed', { duration: `${seconds} s` })
  if (seconds < 3_600) return t('evaluation.topicEditor.elapsed', { duration: `${Math.round(seconds / 60)} min` })
  if (seconds < 86_400) return t('evaluation.topicEditor.elapsed', { duration: `${Math.round(seconds / 3_600)} h` })
  return t('evaluation.topicEditor.elapsed', { duration: t('evaluation.topicEditor.daysShort', { count: Math.round(seconds / 86_400) }) })
}

function notifyError(error: unknown): void {
  console.error('Topic message range import failed', error)
  $q.notify({ color: 'negative', icon: 'error', message: error instanceof Error ? error.message : t('evaluation.error') })
}
</script>

<style scoped>
.range-dialog { display: flex; flex-direction: column; width: min(1050px, calc(100vw - 24px)); max-width: calc(100vw - 24px); height: min(880px, calc(100vh - 24px)); max-height: calc(100vh - 24px); min-width: 0; overflow-x: hidden; }
.dialog-heading { min-width: 0; }
.filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: center; }
.filters > .q-btn { justify-self: start; }
.filters :deep(.q-field), .filters :deep(.q-field__inner), .filters :deep(.q-field__control-container) { min-width: 0; }
.preview-scroll { flex: 1 1 auto; min-height: 0; }
.preview-content { display: grid; gap: 16px; min-width: 0; padding: 16px; }
.preview-empty { display: flex; min-height: 320px; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #757575; }
.message-thread { display: grid; gap: 10px; min-width: 0; }
.message-row { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; }
.message-row--assistant { align-items: flex-end; }
.message-bubble { width: min(760px, 88%); min-width: 0; padding: 12px; border: 1px solid rgba(96, 125, 139, 0.25); border-radius: 4px 16px 16px 16px; background: rgba(96, 125, 139, 0.06); }
.message-row--assistant .message-bubble { border-radius: 16px 4px 16px 16px; background: rgba(103, 58, 183, 0.07); }
.message-text { margin-top: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.message-gap { align-self: center; margin: 2px 0 8px; color: #757575; font-size: 0.75rem; }
.range-dialog :deep(.q-card__actions) { flex-wrap: wrap; gap: 8px; }
@media (max-width: 699px) {
  .filters { grid-template-columns: 1fr; }
  .message-bubble { width: 96%; }
}
</style>
