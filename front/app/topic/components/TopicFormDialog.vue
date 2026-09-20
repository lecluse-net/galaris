<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card class="topic-form-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ topic ? t('topic.editTitle') : t('topic.createTitle') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('topic.cancel')" />
      </q-card-section>
      <q-form @submit.prevent="save">
        <q-card-section class="q-gutter-md">
          <q-input v-model="form.title" outlined autofocus :label="t('topic.title')" :rules="[requiredRule]" />
          <q-input v-model="form.description" outlined type="textarea" autogrow :label="t('topic.description')" />
          <q-select
            v-model="form.keywords"
            outlined
            multiple
            use-input
            use-chips
            input-debounce="0"
            :options="filteredKeywordOptions"
            :max-values="20"
            :loading="loadingKeywords"
            :label="t('topic.keywords')"
            :hint="t('topic.keywordsHelp')"
            @filter="filterKeywords"
            @new-value="addKeyword"
          >
            <template #no-option>
              <q-item><q-item-section class="text-grey-7">{{ t('topic.keywordsEmpty') }}</q-item-section></q-item>
            </template>
          </q-select>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('topic.cancel')" />
          <q-btn color="primary" type="submit" icon="save" :label="t('topic.save')" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { topicService } from '../services/topicService'
import type { Topic, TopicInput } from '../types'

type NewKeywordDone = (value?: string, mode?: 'add' | 'add-unique' | 'toggle') => void

const props = withDefaults(defineProps<{
  modelValue: boolean
  topic?: Topic | null
}>(), { topic: null })
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [topic: Topic]
}>()
const { t, locale } = useI18n()
const $q = useQuasar()
const form = reactive<TopicInput>({ title: '', description: '', keywords: [] })
const keywordOptions = ref<string[]>([])
const filteredKeywordOptions = ref<string[]>([])
const loadingKeywords = ref(false)
const saving = ref(false)
const requiredRule = (value: string): true | string => Boolean(value.trim()) || t('topic.required')

function resetForm(): void {
  Object.assign(form, props.topic ? {
    title: props.topic.title,
    description: props.topic.description,
    keywords: [...props.topic.keywords],
  } : { title: '', description: '', keywords: [] })
}

async function loadKeywords(): Promise<void> {
  loadingKeywords.value = true
  try {
    keywordOptions.value = await topicService.listKeywords()
  } catch {
    keywordOptions.value = []
  } finally {
    filteredKeywordOptions.value = keywordOptions.value
    loadingKeywords.value = false
  }
}

function filterKeywords(value: string, update: (callback: () => void) => void): void {
  update(() => {
    const needle = value.trim().toLocaleLowerCase(locale.value)
    filteredKeywordOptions.value = needle
      ? keywordOptions.value.filter(item => item.toLocaleLowerCase(locale.value).includes(needle))
      : keywordOptions.value
  })
}

function addKeyword(value: string, done: NewKeywordDone): void {
  const normalized = value.trim().slice(0, 80)
  done(normalized || undefined, normalized ? 'add-unique' : undefined)
}

function payload(): TopicInput {
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    keywords: [...new Set(form.keywords.map(value => value.trim().slice(0, 80)).filter(Boolean))].slice(0, 20),
  }
}

async function save(): Promise<void> {
  if (!form.title.trim() || saving.value) return
  saving.value = true
  try {
    const saved = props.topic
      ? await topicService.update(props.topic, payload())
      : await topicService.create(payload())
    $q.notify({ type: 'positive', message: t(props.topic ? 'topic.updateSuccess' : 'topic.createSuccess') })
    emit('saved', saved)
    emit('update:modelValue', false)
  } catch {
    $q.notify({ type: 'negative', message: t('topic.operationError') })
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, open => {
  if (!open) return
  resetForm()
  void loadKeywords()
})
</script>

<style scoped>
.topic-form-dialog { width: min(92vw, 620px); }
</style>
