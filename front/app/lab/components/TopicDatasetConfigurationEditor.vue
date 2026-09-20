<template>
  <div class="topic-configuration">
    <q-expansion-item
      default-opened
      icon="topic"
      :label="t('evaluation.topicEditor.predefinedTopics')"
      :caption="t('evaluation.topicEditor.predefinedTopicsHelp')"
      header-class="text-deep-purple"
    >
      <div class="q-px-md q-pb-md q-gutter-md">
        <q-banner v-if="!draft.topics.length" rounded class="bg-blue-grey-1 text-blue-grey-8">
          {{ t('evaluation.topicEditor.noPredefinedTopics') }}
        </q-banner>
        <q-card v-for="(topic, index) in draft.topics" :key="index" flat bordered class="topic-card">
          <q-card-section class="row items-start q-col-gutter-md">
            <div class="col-12 col-md">
              <q-input v-model="topic.title" outlined dense :readonly="readonly" :label="t('evaluation.topicEditor.topicName')" />
            </div>
            <div v-if="!readonly" class="col-auto">
              <q-btn flat round dense color="negative" icon="delete_outline" @click="removeTopic(index)">
                <q-tooltip>{{ t('evaluation.topicEditor.deletePredefinedTopic') }}</q-tooltip>
              </q-btn>
            </div>
            <div class="col-12">
              <q-input v-model="topic.description" type="textarea" autogrow outlined dense :readonly="readonly" :label="t('evaluation.topicEditor.topicDescription')" />
            </div>
            <div class="col-12">
              <q-select
                v-model="topic.keywords"
                outlined
                dense
                multiple
                use-input
                use-chips
                hide-dropdown-icon
                new-value-mode="add-unique"
                :readonly="readonly"
                :label="t('evaluation.topicEditor.topicKeywords')"
              />
            </div>
          </q-card-section>
        </q-card>
        <q-btn v-if="!readonly" outline color="deep-purple" icon="add" :label="t('evaluation.topicEditor.addPredefinedTopic')" @click="addTopic" />
      </div>
    </q-expansion-item>

    <q-separator />

    <q-expansion-item
      icon="prompt_suggestion"
      :label="t('evaluation.topicEditor.datasetPrompts')"
      :caption="readonly ? t('evaluation.topicEditor.benchmarkPromptsHelp') : t('evaluation.topicEditor.datasetPromptsHelp')"
      header-class="text-deep-purple"
    >
      <div class="q-px-md q-pb-md q-gutter-md">
        <q-input
          v-model="draft.prompts.continuity_system_prompt"
          type="textarea"
          autogrow
          outlined
          :readonly="readonly"
          input-style="min-height: 160px; font-family: monospace; overflow-wrap: anywhere;"
          :label="t('evaluation.topicEditor.continuityPrompt')"
        />
        <q-input
          v-model="draft.prompts.resolution_system_prompt"
          type="textarea"
          autogrow
          outlined
          :readonly="readonly"
          input-style="min-height: 160px; font-family: monospace; overflow-wrap: anywhere;"
          :label="t('evaluation.topicEditor.resolutionPrompt')"
        />
      </div>
    </q-expansion-item>

    <div v-if="!readonly" class="row justify-end q-pa-md">
      <q-btn color="deep-purple" icon="save" :label="t('evaluation.topicEditor.saveConfiguration')" :loading="saving" @click="save" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TopicDatasetConfiguration } from '../services/mechanismEvaluationService'

const props = withDefaults(defineProps<{
  configuration: TopicDatasetConfiguration
  readonly?: boolean
  saving?: boolean
}>(), {
  readonly: false,
  saving: false,
})

const emit = defineEmits<{
  save: [configuration: TopicDatasetConfiguration]
}>()

const { t } = useI18n()
const draft = ref<TopicDatasetConfiguration>(clone(props.configuration))

watch(() => props.configuration, value => {
  draft.value = clone(value)
}, { deep: true })

function clone(value: TopicDatasetConfiguration): TopicDatasetConfiguration {
  return JSON.parse(JSON.stringify(value)) as TopicDatasetConfiguration
}

function addTopic(): void {
  draft.value.topics.push({ title: '', description: '', keywords: [] })
}

function removeTopic(index: number): void {
  draft.value.topics.splice(index, 1)
}

function save(): void {
  emit('save', clone(draft.value))
}
</script>

<style scoped>
.topic-configuration { min-width: 0; max-width: 100%; overflow-x: clip; }
.topic-card { min-width: 0; max-width: 100%; }
.topic-configuration :deep(.q-item__section),
.topic-configuration :deep(.q-field),
.topic-configuration :deep(.q-field__control),
.topic-configuration :deep(.q-field__native) { min-width: 0; max-width: 100%; }
</style>
