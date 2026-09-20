<template>
  <div class="memory-case-editor q-gutter-md">
    <q-banner rounded class="bg-blue-1 text-blue-10">
      <template #avatar><q-icon name="memory" /></template>
      {{ t('evaluation.memoryEditor.isolationHelp') }}
    </q-banner>

    <q-card flat bordered>
      <q-card-section class="row items-center q-col-gutter-md">
        <div class="col-12 col-md-4">
          <q-select
            :model-value="model.source_kind"
            :options="sourceOptions"
            emit-value
            map-options
            outlined
            dense
            readonly
            :label="t('evaluation.memoryEditor.sourceKind')"
          />
        </div>
        <div class="col-12 col-md">
          <q-input
            :model-value="topicTitle"
            outlined
            dense
            :readonly="readonly"
            :label="t('evaluation.memoryEditor.topic')"
            @update:model-value="setTopicTitle(String($event ?? ''))"
          />
        </div>
      </q-card-section>
    </q-card>

    <q-card v-if="model.source_kind === 'task'" flat bordered>
      <q-card-section>
        <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.memoryEditor.taskTrace') }}</div>
        <div class="text-caption text-grey-7">{{ t('evaluation.memoryEditor.taskTraceHelp') }}</div>
      </q-card-section>
      <q-separator />
      <div class="task-trace-editor">
        <JsonEditor
          v-model="taskTraceJson"
          language="json"
          fill-height
          :readonly="readonly"
          :label="t('evaluation.memoryEditor.taskTrace')"
        />
      </div>
    </q-card>

    <template v-else>
      <q-card flat bordered>
        <q-card-section class="row items-center">
          <div class="col">
            <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.memoryEditor.history') }}</div>
            <div class="text-caption text-grey-7">{{ t('evaluation.memoryEditor.historyHelp') }}</div>
          </div>
          <q-btn v-if="!readonly && model.history.length < 5" flat round color="primary" icon="add" @click="addMessage('history')" />
        </q-card-section>
        <q-separator />
        <q-list v-if="model.history.length" separator>
          <q-item v-for="(message, index) in model.history" :key="`history-${index}`" class="message-row">
            <q-item-section side>
              <q-select v-model="message.speaker_kind" :options="speakerKindOptions" emit-value map-options dense outlined :readonly="readonly" class="role-select" />
            </q-item-section>
            <q-item-section class="speaker-name"><q-input v-model="message.speaker_name" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.speakerName')" /></q-item-section>
            <q-item-section><q-input v-model="message.text" autogrow outlined dense :readonly="readonly" /></q-item-section>
            <q-item-section v-if="!readonly" side><q-btn flat round dense color="negative" icon="delete_outline" @click="model.history.splice(index, 1)" /></q-item-section>
          </q-item>
        </q-list>
        <q-card-section v-else class="text-grey-7">{{ t('evaluation.memoryEditor.noHistory') }}</q-card-section>
      </q-card>

      <q-card flat bordered>
        <q-card-section class="row items-center">
          <div class="col text-subtitle1 text-weight-medium">{{ t('evaluation.memoryEditor.currentRound') }}</div>
          <q-btn v-if="!readonly" flat round color="primary" icon="add" @click="addMessage('current')" />
        </q-card-section>
        <q-separator />
        <q-list separator>
          <q-item v-for="(message, index) in model.current" :key="`current-${index}`" class="message-row">
            <q-item-section side><q-select v-model="message.speaker_kind" :options="speakerKindOptions" emit-value map-options dense outlined :readonly="readonly" class="role-select" /></q-item-section>
            <q-item-section class="speaker-name"><q-input v-model="message.speaker_name" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.speakerName')" /></q-item-section>
            <q-item-section><q-input v-model="message.text" autogrow outlined dense :readonly="readonly" /></q-item-section>
            <q-item-section v-if="!readonly && model.current.length > 1" side><q-btn flat round dense color="negative" icon="delete_outline" @click="model.current.splice(index, 1)" /></q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </template>

    <q-card flat bordered>
      <q-card-section class="row items-center">
        <div class="col">
          <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.memoryEditor.existingMemories') }}</div>
          <div class="text-caption text-grey-7">{{ t('evaluation.memoryEditor.existingMemoriesHelp', { count: model.existing_memories.length, max: MEMORY_EXTRACTION_MAX_MEMORIES }) }}</div>
        </div>
        <q-btn v-if="!readonly" outline color="primary" icon="add" :label="t('evaluation.memoryEditor.addMemory')" :disable="model.existing_memories.length >= MEMORY_EXTRACTION_MAX_MEMORIES" @click="addMemory" />
      </q-card-section>
      <q-separator />
      <q-expansion-item
        v-for="(memory, index) in model.existing_memories"
        :key="memory.id"
        :label="memory.title || memory.id"
        :caption="`${memory.id} · ${memory.memory_type}`"
        icon="description"
        group="existing-memories"
      >
        <q-card-section class="row q-col-gutter-md q-gutter-y-sm">
          <div class="col-12 col-md-3"><q-input v-model="memory.id" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.localId')" /></div>
          <div class="col-12 col-md-6"><q-input v-model="memory.title" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.memoryTitle')" /></div>
          <div class="col-12 col-md-3"><q-select v-model="memory.memory_type" :options="memoryTypes" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.memoryType')" /></div>
          <div class="col-12"><q-input v-model="memory.content" type="textarea" autogrow outlined :readonly="readonly" :label="t('evaluation.memoryEditor.memoryContent')" /></div>
          <div v-if="!readonly" class="col-auto"><q-btn flat round color="negative" icon="delete_outline" @click="removeMemory(index)" /></div>
        </q-card-section>
      </q-expansion-item>
      <q-card-section v-if="!model.existing_memories.length" class="text-center text-grey-7 q-py-lg">
        {{ t('evaluation.memoryEditor.emptyCorpus') }}
      </q-card-section>
    </q-card>

    <q-card flat bordered>
      <q-card-section class="row items-center q-gutter-md">
        <div class="col">
          <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.memoryEditor.expectedDecision') }}</div>
          <div class="text-caption text-grey-7">{{ t('evaluation.memoryEditor.expectedDecisionHelp') }}</div>
        </div>
        <q-btn
          v-if="!readonly"
          outline
          color="deep-purple"
          icon="auto_awesome"
          :label="t('evaluation.dispatcher.generateExpected')"
          :loading="generatingExpected"
          :disable="!canGenerateExpected"
          @click="emit('generate-expected')"
        />
      </q-card-section>
      <q-separator />
      <q-card-section class="row q-gutter-sm">
        <q-btn v-if="!readonly" outline color="positive" icon="add_circle" label="CREATE" @click="addCreate" />
        <q-btn v-if="!readonly" outline color="primary" icon="link" label="LINK" :disable="!model.existing_memories.length" @click="addLink" />
        <q-btn v-if="!readonly" outline color="grey-8" icon="block" label="IGNORE" @click="expected.operations = []" />
        <q-badge v-if="!expected.operations.length" color="grey-7" class="q-pa-sm">IGNORE</q-badge>
      </q-card-section>
      <q-list separator>
        <q-item v-for="(operation, index) in expected.operations" :key="`operation-${index}`" class="operation-row">
          <q-item-section>
            <div class="row q-col-gutter-md q-gutter-y-sm">
              <div class="col-12"><q-badge :color="operation.action === 'CREATE' ? 'positive' : 'primary'">{{ operation.action }}</q-badge></div>
              <template v-if="operation.action === 'CREATE'">
                <div class="col-12 col-md-6"><q-input v-model="operation.title" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.memoryTitle')" /></div>
                <div class="col-12 col-md-3"><q-select v-model="operation.memory_type" :options="memoryTypes" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.memoryType')" /></div>
                <div class="col-12 col-md-3"><q-select v-model="operation.retention_reason" :options="retentionReasons" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.retentionReason')" /></div>
                <div class="col-12"><q-input v-model="operation.content" type="textarea" autogrow outlined :readonly="readonly" :label="t('evaluation.memoryEditor.memoryContent')" /></div>
              </template>
              <template v-else>
                <div class="col-12 col-md-5"><q-select v-model="operation.target_memory_id" :options="memoryOptions" emit-value map-options outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.linkTarget')" /></div>
                <div class="col-12 col-md"><q-input v-model="operation.reason" outlined dense :readonly="readonly" :label="t('evaluation.memoryEditor.reason')" /></div>
              </template>
            </div>
          </q-item-section>
          <q-item-section v-if="!readonly" side><q-btn flat round color="negative" icon="delete_outline" @click="expected.operations.splice(index, 1)" /></q-item-section>
        </q-item>
      </q-list>
      <q-separator />
      <q-card-section>
        <q-select
          v-model="expected.relevant_memory_ids"
          :options="memoryOptions"
          multiple
          use-chips
          emit-value
          map-options
          outlined
          :readonly="readonly"
          :label="t('evaluation.memoryEditor.relevantForRetrieval')"
          :hint="t('evaluation.memoryEditor.relevantForRetrievalHelp')"
        />
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { JsonEditor } from '@/core/util'
import {
  MEMORY_EXTRACTION_MAX_MEMORIES,
  type MemoryExtractionInput,
  type MemoryExtractionOutput,
} from '../services/mechanismEvaluationService'

const {
  readonly = false,
  generatingExpected = false,
  canGenerateExpected = true,
} = defineProps<{
  readonly?: boolean
  generatingExpected?: boolean
  canGenerateExpected?: boolean
}>()
const emit = defineEmits<{ 'generate-expected': [] }>()
const model = defineModel<MemoryExtractionInput>({ required: true })
const expected = defineModel<MemoryExtractionOutput>('expected', { required: true })
const { t } = useI18n()
const taskTraceJson = ref(JSON.stringify(model.value.task_trace ?? {}, null, 2))

const sourceOptions = computed(() => [
  { label: t('evaluation.memoryEditor.sources.task'), value: 'task' },
  { label: t('evaluation.memoryEditor.sources.conversation'), value: 'conversation_round' },
  { label: t('evaluation.memoryEditor.sources.voice'), value: 'voice_turn' },
])
const speakerKindOptions = computed(() => [
  { label: t('evaluation.memoryEditor.human'), value: 'human' },
  { label: t('evaluation.memoryEditor.assistant'), value: 'AI' },
])
const memoryTypes = ['core', 'working', 'episodic', 'semantic', 'procedural', 'social'] as const
const retentionReasons = [
  'explicit_user_preference',
  'stable_personal_fact',
  'explicit_decision_or_commitment',
  'recurring_constraint',
  'reusable_procedure',
  'explicit_correction',
  'durable_relationship',
]
const memoryOptions = computed(() => model.value.existing_memories.map(item => ({
  label: `${item.id} · ${item.title}`,
  value: item.id,
})))
const topicTitle = computed(() => typeof model.value.topic.title === 'string' ? model.value.topic.title : '')

watch(taskTraceJson, value => {
  if (readonly || model.value.source_kind !== 'task') return
  try {
    const parsed = JSON.parse(value) as unknown
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      model.value.task_trace = parsed as Record<string, unknown>
    }
  } catch {
    // The parent save action reports invalid JSON through its normal validation path.
  }
})

watch(
  () => model.value.task_trace,
  value => {
    const serialized = JSON.stringify(value ?? {}, null, 2)
    try {
      if (JSON.stringify(JSON.parse(taskTraceJson.value), null, 2) === serialized) return
    } catch {
      // Replacing the edited case must replace an invalid draft from the previous case.
    }
    taskTraceJson.value = serialized
  },
  { deep: true },
)

function commitTaskTrace(): void {
  if (model.value.source_kind !== 'task') return
  let parsed: unknown
  try {
    parsed = JSON.parse(taskTraceJson.value)
  } catch {
    throw new Error(t('evaluation.memoryEditor.invalidTaskTrace'))
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(t('evaluation.memoryEditor.invalidTaskTrace'))
  }
  model.value.task_trace = parsed as Record<string, unknown>
}

defineExpose({ commitTaskTrace })

function setTopicTitle(value: string): void {
  model.value.topic = { ...model.value.topic, title: value }
}

function addMessage(target: 'history' | 'current'): void {
  model.value[target].push({ speaker_name: t('evaluation.memoryEditor.human'), speaker_kind: 'human', text: '' })
}

function nextMemoryId(): string {
  const used = new Set(model.value.existing_memories.map(item => item.id))
  let index = model.value.existing_memories.length + 1
  while (used.has(`memory-${String(index).padStart(3, '0')}`)) index += 1
  return `memory-${String(index).padStart(3, '0')}`
}

function addMemory(): void {
  if (model.value.existing_memories.length >= MEMORY_EXTRACTION_MAX_MEMORIES) return
  model.value.existing_memories.push({
    id: nextMemoryId(),
    title: '',
    content: '',
    memory_type: 'semantic',
    keywords: [],
    score: 0,
  })
}

function removeMemory(index: number): void {
  const removed = model.value.existing_memories[index]?.id
  model.value.existing_memories.splice(index, 1)
  if (!removed) return
  expected.value.relevant_memory_ids = expected.value.relevant_memory_ids.filter(id => id !== removed)
  expected.value.operations = expected.value.operations.filter(operation => operation.action !== 'LINK' || operation.target_memory_id !== removed)
}

function addCreate(): void {
  expected.value.operations.push({
    action: 'CREATE',
    title: '',
    content: '',
    memory_type: 'semantic',
    keywords: [],
    retention_reason: 'explicit_user_preference',
    future_utility: 'high',
    reason: '',
  })
}

function addLink(): void {
  const target = model.value.existing_memories[0]?.id
  if (!target) return
  expected.value.operations.push({ action: 'LINK', target_memory_id: target, reason: '' })
}
</script>

<style scoped>
.task-trace-editor { height: 360px; }
.message-row, .operation-row { align-items: flex-start; }
.role-select { width: 150px; }
</style>
