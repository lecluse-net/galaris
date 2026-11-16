<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card class="topic-form-dialog galaris-dialog-card">
      <DialogHeader :title="topic ? t('topic.editTitle') : t('topic.createTitle')" />
      <q-form class="galaris-dialog-form" @submit.prevent="save">
        <q-card-section class="q-gutter-md galaris-dialog-body">
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
          <q-btn outline color="primary" v-close-popup  :label="t('topic.cancel')" />
          <q-btn color="primary" type="submit" icon="save" :label="t('topic.save')" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { topicService } from '../services/topicService'
import { normalizeTopicInput } from '../topicInput'
import type { Topic, TopicInput } from '../types'
import { DialogHeader } from '@/core/util'

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
let opening = 0
onBeforeUnmount(() => { opening++ })
const requiredRule = (value: string): true | string => Boolean(value.trim()) || t('topic.required')

function resetForm(): void {
  Object.assign(form, props.topic ? {
    title: props.topic.title,
    description: props.topic.description,
    keywords: [...props.topic.keywords],
  } : { title: '', description: '', keywords: [] })
}

async function loadKeywords(): Promise<void> {
  const request = opening
  loadingKeywords.value = true
  try {
    const keywords = await topicService.listKeywords()
    if (request === opening) keywordOptions.value = keywords
  } catch {
    if (request === opening) keywordOptions.value = []
  } finally {
    if (request === opening) {
      filteredKeywordOptions.value = keywordOptions.value
      loadingKeywords.value = false
    }
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

async function save(): Promise<void> {
  if (!form.title.trim() || saving.value) return
  saving.value = true
  const request = opening, topic = props.topic
  const current = () => request === opening && props.modelValue
  try {
    const saved = topic
      ? await topicService.update(topic, normalizeTopicInput(form))
      : await topicService.create(normalizeTopicInput(form))
    if (!current()) return
    $q.notify({ type: 'positive', message: t(topic ? 'topic.updateSuccess' : 'topic.createSuccess') })
    emit('saved', saved)
    emit('update:modelValue', false)
  } catch {
    if (current()) $q.notify({ type: 'negative', message: t('topic.operationError') })
  } finally {
    if (current()) saving.value = false
  }
}

watch(() => [props.modelValue, props.topic?.id] as const, ([open]) => {
  opening++
  saving.value = false
  loadingKeywords.value = false
  if (!open) return
  resetForm()
  void loadKeywords()
}, { immediate: true, flush: 'sync' })
</script>

<style scoped>
.topic-form-dialog { width: min(92vw, 620px); }
</style>
