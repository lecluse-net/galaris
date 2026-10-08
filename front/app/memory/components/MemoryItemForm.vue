<template>
  <q-card-section class="memory-editor-fields">
    <q-banner v-if="summaryOutdated" dense>{{ t('memory.summaryOutdated') }}</q-banner>
    <q-select :model-value="draft.keywords" :readonly="readonly" @update:model-value="updateDraft({ keywords: $event })"
      class="memory-form-keywords" outlined dense stack-label hide-bottom-space multiple use-input use-chips input-debounce="0"
      :options="filteredKeywordOptions" :max-values="50" :label="t('memory.keywords')"
      @filter="filterKeywords" @new-value="addKeyword">
      <template #no-option>
        <q-item><q-item-section class="text-grey-7">{{ t('documents.keywordsEmpty') }}</q-item-section></q-item>
      </template>
    </q-select>
    <section class="memory-form-content" :aria-label="t('memory.content')">
      <q-banner v-if="!textAvailable" dense>{{ t('memory.binaryContent') }}</q-banner>
      <RichTextEditor
        v-else-if="draft.contentType === 'text' && ['text/html', 'text/markdown'].includes(draft.mediaType)"
        :readonly="readonly"
        :hidden-toolbar-groups="['reading', 'editing']"
        single-row-toolbar
        :media-type="draft.mediaType"
        :model-value="draft.content" @update:model-value="updateDraft({ content: $event, mediaType: 'text/html' })"
        :aria-label="t('memory.content')"
        min-height="160px"
      />
      <q-input
        v-else
        :readonly="readonly"
        :model-value="draft.content" @update:model-value="updateDraft({ content: String($event ?? ''), mediaType: draft.mediaType })"
        type="textarea"
        outlined
        dense
        autogrow
        :label="t('memory.content')"
        input-style="min-height: 120px"
      />
    </section>
    <MemoryTemporalFields class="memory-form-section" :model-value="draft.temporal ?? null" :readonly="readonly"
      @update:model-value="updateDraft({ temporal: $event })" />
    <q-badge v-if="resourceReadOnly" outline color="primary" class="memory-read-only-state">
      <q-icon name="lock" class="q-mr-xs" /><span>{{ t('memory.readOnly') }}</span>
    </q-badge>
  </q-card-section>
</template>

<script lang="ts">
import type { MemoryNodeKind, MemoryTemporalAnchor } from '../types'

export interface MemoryEditorDraft {
  temporal?: MemoryTemporalAnchor | null
  content: string
  nodeKind: MemoryNodeKind
  mediaType: string
  contentType: string
  keywords: string[]
  revision: number | null
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RichTextEditor } from '@/core/util'
import MemoryTemporalFields from './MemoryTemporalFields.vue'

const { draft, readonly = false, resourceReadOnly = false, textAvailable = true, keywordOptions = [], summaryOutdated = false } = defineProps<{
  draft: MemoryEditorDraft
  editingId: string | null
  lockVersion?: number
  sharingEditable: boolean
  readonly?: boolean
  resourceReadOnly?: boolean
  textAvailable?: boolean
  keywordOptions?: string[]
  summaryOutdated?: boolean
}>()
const emit = defineEmits<{ 'sharing-changed': []; 'update:draft': [value: MemoryEditorDraft] }>()
function updateDraft(patch: Partial<MemoryEditorDraft>): void {
  if (readonly) return
  emit('update:draft', { ...draft, ...patch })
}
const { t } = useI18n()
const keywordQuery = ref('')
const filteredKeywordOptions = computed(() => [...new Set([...keywordOptions, ...draft.keywords])]
  .filter(keyword => !draft.keywords.includes(keyword) && keyword.toLocaleLowerCase().includes(keywordQuery.value)))
function filterKeywords(value: string, update: (callback: () => void) => void): void {
  update(() => { keywordQuery.value = value.trim().toLocaleLowerCase() })
}
function addKeyword(value: string, done: (value?: string, mode?: 'add-unique') => void): void {
  const keyword = value.trim().slice(0, 100)
  if (keyword) done(keyword, 'add-unique')
  else done()
}
</script>

<style scoped>
.memory-editor-fields {
  display: grid;
  gap: 16px;
  padding: 16px;
}
.memory-editor-fields > * { min-width: 0; }
.memory-editor-heading { display: flex; gap: 12px; }
.memory-editor-heading > .q-input { flex: 1; min-width: 0; }
.memory-editor-heading > .q-select { width: 200px; }
.memory-form-section {
  padding: 12px;
  border-radius: 8px;
  background: var(--solaire-gray-light);
}
body.body--dark .memory-form-section { background: var(--solaire-gray-dark); }
.memory-read-only-state { justify-self: start; }
.memory-form-keywords :deep(.q-field__native) { align-content: flex-start; align-items: flex-start; }
@media (max-width: 599px) {
  .memory-editor-heading { flex-direction: column; }
  .memory-editor-heading > .q-select { width: 100%; }
}
</style>
