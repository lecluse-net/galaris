<template>
  <section class="document-summary-panel document-secondary-panel column no-wrap" :aria-label="t('resourceSummary.title')"
    :style="{ minHeight, maxHeight: maxHeight || undefined }">
    <header class="document-secondary-header">
      <q-icon name="short_text" color="primary" size="26px" />
      <div class="text-h6 document-secondary-heading">{{ t('resourceSummary.title') }}</div>
      <div class="document-secondary-actions">
        <q-btn v-if="writable && summary" class="document-secondary-action-wide" outline color="primary" icon="refresh"
          :label="t('documents.summaryRegenerate')" :aria-label="t('documents.summaryRegenerate')"
          :loading="regenerating" :disable="busy" @click="regenerationOpen = true">
          <q-tooltip>{{ t('documents.summaryRegenerate') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="writable && summary" class="document-secondary-action-compact" flat round color="primary" icon="refresh"
          :aria-label="t('documents.summaryRegenerate')" :loading="regenerating" :disable="busy" @click="regenerationOpen = true">
          <q-tooltip>{{ t('documents.summaryRegenerate') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="writable && summary" class="document-secondary-action-wide" color="primary" icon="save"
          :label="t('documents.summarySave')" :aria-label="t('documents.summarySave')"
          :loading="saving" :disable="busy || !dirty" @click="save">
          <q-tooltip>{{ t('documents.summarySave') }}</q-tooltip>
        </q-btn>
        <q-btn v-if="writable && summary" class="document-secondary-action-compact" flat round color="primary" icon="save"
          :aria-label="t('documents.summarySave')" :loading="saving" :disable="busy || !dirty" @click="save">
          <q-tooltip>{{ t('documents.summarySave') }}</q-tooltip>
        </q-btn>
        <q-btn class="document-secondary-back-wide" outline color="primary" icon="arrow_back" :label="t('documents.historyBack')"
          :disable="busy" @click="back" />
        <q-btn class="document-secondary-back-compact" flat round color="primary" icon="arrow_back"
          :aria-label="t('documents.historyBack')" :disable="busy" @click="back">
          <q-tooltip>{{ t('documents.historyBack') }}</q-tooltip>
        </q-btn>
      </div>
    </header>
    <q-separator />
    <div class="document-secondary-content q-pa-sm scroll col">
      <div v-if="loading" class="row justify-center q-pa-md" role="status">
        <q-spinner color="primary" size="32px" :aria-label="t('resourceSummary.loading')" />
      </div>
      <q-banner v-if="error" role="alert" class="q-mb-sm">
        {{ t(error) }}
        <template #action>
          <q-btn v-if="!summary" outline color="primary" :label="t('resourceSummary.retry')" @click="load" />
          <q-btn v-if="conflict" outline color="primary" :label="t('documents.summaryReload')" @click="load" />
        </template>
      </q-banner>
      <template v-if="summary && !loading">
        <div v-if="!writable && !hasContent" class="text-grey-7 q-pa-sm">{{ t('resourceSummary.empty') }}</div>
        <RichTextEditor v-else v-model="draft" profile="rich-text" :readonly="!writable || busy"
          :aria-label="t('resourceSummary.title')" :min-height="minHeight" :max-height="maxHeight" auto-grow />
        <div v-if="dirty" class="text-caption q-pa-sm" role="status">
          {{ t('documents.summaryUnsaved') }}
        </div>
      </template>
    </div>
  </section>
  <q-dialog v-model="regenerationOpen" :aria-label="t('documents.summaryRegenerate')">
    <q-card class="galaris-dialog-card" style="width: 440px; max-width: 95vw">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.summaryRegenerate') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body">{{ t('documents.summaryHint') }}</q-card-section>
      <q-card-actions align="right">
        <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('documents.summaryRegenerate')" :disable="busy || !writable" @click="regenerate" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import '../documentSecondaryView.css'
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { RichTextEditor, richTextExcerpt } from '@/core/util'
import { documentService } from '../services/documentService'
import type { DocumentDetail } from '../types'

const props = defineProps<{
  documentId: string; agentId: number | null; editable: boolean; minHeight: string; maxHeight?: string
}>()
const emit = defineEmits<{ close: []; updated: [summary: DocumentDetail] }>()
const { t } = useI18n()
const summary = shallowRef<DocumentDetail>()
const draft = ref(''), saved = ref(''), error = ref('')
const loading = ref(false), saving = ref(false), regenerating = ref(false), conflict = ref(false)
const regenerationOpen = ref(false)
const busy = computed(() => loading.value || saving.value || regenerating.value)
const writable = computed(() => props.editable && !!summary.value?.access.can_write && !summary.value.read_only)
const dirty = computed(() => !!summary.value && draft.value !== saved.value)
const hasContent = computed(() => !!richTextExcerpt(draft.value))
let generation = 0
let controller: AbortController | undefined
let pending: Promise<boolean> | undefined

function apply(value: DocumentDetail): void {
  summary.value = value
  let html = value.payload.text ?? ''
  if (value.media_type === 'text/plain') {
    const paragraph = document.createElement('p')
    paragraph.textContent = html
    html = html ? paragraph.outerHTML : ''
  }
  draft.value = saved.value = html
}
function failed(cause: unknown, key: string): void {
  conflict.value = isAxiosError(cause) && cause.response?.status === 409
  error.value = conflict.value ? 'documents.summaryConflict' : key
}
async function load(): Promise<void> {
  const request = ++generation
  controller?.abort()
  controller = new AbortController()
  summary.value = undefined
  draft.value = saved.value = ''
  error.value = ''
  conflict.value = false
  saving.value = regenerating.value = false
  pending = undefined
  loading.value = true
  try {
    const result = await documentService.summary(props.documentId, props.agentId, controller.signal)
    if (request === generation) apply(result)
  } catch {
    if (request === generation) error.value = 'resourceSummary.error'
  } finally {
    if (request === generation) loading.value = false
  }
}
function mutate(regenerate: boolean): Promise<boolean> {
  if (pending) return pending
  if (!summary.value || !writable.value || loading.value) return Promise.resolve(!dirty.value)
  if (!regenerate && !dirty.value) return Promise.resolve(true)
  const request = generation, current = summary.value, content = draft.value
  error.value = ''
  conflict.value = false
  saving.value = !regenerate
  regenerating.value = regenerate
  pending = (async () => {
    try {
      const result = regenerate
        ? await documentService.regenerateSummary(props.documentId, props.agentId, current.lock_version)
        : await documentService.updateSummary(props.documentId, props.agentId, {
          payload: { text: content }, expected_lock_version: current.lock_version,
        })
      if (request !== generation) return false
      apply(result)
      emit('updated', result)
      return true
    } catch (cause) {
      if (request === generation) failed(cause, regenerate ? 'documents.summaryRegenerateError' : 'documents.summarySaveError')
      return false
    } finally {
      if (request === generation) { saving.value = false; regenerating.value = false; pending = undefined }
    }
  })()
  return pending
}
function save(): Promise<boolean> { return mutate(false) }
async function flush(): Promise<boolean> {
  if (pending && !await pending) return false
  return await save()
}
async function back(): Promise<void> { if (await flush()) emit('close') }
async function regenerate(): Promise<void> { regenerationOpen.value = false; await mutate(true) }
watch(() => [props.documentId, props.agentId], () => { regenerationOpen.value = false; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort() })
defineExpose({ flush })
</script>
