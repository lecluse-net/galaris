<template>
  <q-card-section class="memory-editor-fields">
    <div class="memory-editor-title">
      <q-input :model-value="draft.title" :readonly="readonly" @update:model-value="updateDraft({ title: String($event ?? '') })" dense outlined hide-bottom-space :label="t('memory.title')" :rules="readonly ? [] : [requiredRule]" />
    </div>
    <div class="memory-editor-type">
      <q-select :model-value="draft.memoryType" :readonly="readonly" @update:model-value="updateDraft({ memoryType: $event })" :options="typeOptions" behavior="menu" emit-value map-options dense outlined hide-bottom-space :label="t('memory.type')" />
    </div>
    <div v-if="!editingId">
      <q-select
        :model-value="draft.nodeKind" @update:model-value="updateDraft({ nodeKind: $event })"
        :readonly="readonly"
        :options="nodeKindOptions"
        behavior="menu"
        emit-value
        map-options
        outlined
        dense
        hide-bottom-space
        :label="t('memory.kind')"
      />
    </div>
    <div class="memory-form-access">
      <q-input :model-value="ownerLabel" readonly dense outlined hide-bottom-space :label="t('memory.owner')" />
      <q-field class="memory-form-provenance" outlined dense stack-label hide-bottom-space tag="div" :label="t('memory.sources')">
        <template #control>
          <div class="full-width memory-form-sources">
            <div v-for="source in sources" :key="source.ref" class="text-caption">
              <RouterLink v-if="source.taskId !== null && canViewTasks" class="text-primary"
                :to="{ path: '/task', query: { task_id: source.taskId } }">{{ source.ref }}</RouterLink>
              <template v-else>{{ source.ref }}</template>
            </div>
            <span v-if="!sources.length" class="text-caption">{{ t('memory.noSources') }}</span>
          </div>
        </template>
      </q-field>
    </div>
    <div class="memory-sharing-row">
      <MemorySharingPanel v-if="editingId && (draft.nodeKind === 'memory' || draft.nodeKind === 'document')" class="memory-sharing-field" :item-id="editingId" :resource-kind="draft.nodeKind"
        :lock-version="lockVersion" :editable="sharingEditable"
        @changed="emit('sharing-changed')" />
      <q-toggle :model-value="draft.readOnly" :disable="readonly" @update:model-value="updateDraft({ readOnly: $event })" dense size="sm" :label="t('memory.readOnly')" />
    </div>
    <div>
      <q-select :model-value="draft.keywords" :readonly="readonly" @update:model-value="updateDraft({ keywords: $event })"
        class="memory-form-keywords" outlined dense stack-label hide-bottom-space multiple use-input use-chips input-debounce="0"
        :options="filteredKeywordOptions" :max-values="50" :label="t('memory.keywords')"
        @filter="filterKeywords" @new-value="addKeyword">
        <template #no-option>
          <q-item><q-item-section class="text-grey-7">{{ t('documents.keywordsEmpty') }}</q-item-section></q-item>
        </template>
      </q-select>
    </div>
    <div>
      <q-banner v-if="!textAvailable" dense>{{ t('memory.binaryContent') }}</q-banner>
      <CodeEditor
        v-else-if="draft.nodeKind === 'document' && draft.mediaType === 'application/json'"
        :model-value="draft.content" @update:model-value="updateDraft({ content: $event })"
        language="json" :readonly="readonly" :label="t('memory.content')" :min-lines="15"
      />
      <RichTextEditor
        v-else-if="draft.contentType === 'text' && ['text/html', 'text/markdown'].includes(draft.mediaType)"
        :readonly="readonly"
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
      <div v-if="!readonly && !draft.content.trim()" class="text-caption text-negative q-mt-xs">
        {{ t('memory.required') }}
      </div>
    </div>
  </q-card-section>
</template>

<script lang="ts">
import type { MemoryNodeKind, MemoryType } from '../types'

export interface MemoryEditorDraft {
  title: string
  content: string
  memoryType: MemoryType
  nodeKind: MemoryNodeKind
  mediaType: string
  contentType: string
  keywords: string[]
  readOnly: boolean
  revision: number | null
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { CodeEditor, RichTextEditor } from '@/core/util'
import MemorySharingPanel from './MemorySharingPanel.vue'

const { draft, editingId, lockVersion, sharingEditable, readonly = false, textAvailable = true, ownerLabel, sources, canViewTasks = false, keywordOptions = [] } = defineProps<{
  draft: MemoryEditorDraft
  editingId: string | null
  lockVersion?: number
  sharingEditable: boolean
  readonly?: boolean
  textAvailable?: boolean
  ownerLabel: string
  sources: { ref: string; taskId: string | null }[]
  canViewTasks?: boolean
  keywordOptions?: string[]
}>()
const emit = defineEmits<{ 'sharing-changed': []; 'update:draft': [value: MemoryEditorDraft] }>()
function updateDraft(patch: Partial<MemoryEditorDraft>): void {
  if (readonly) return
  emit('update:draft', { ...draft, ...patch })
}
const { t } = useI18n()
const memoryTypes: MemoryType[] = ['core', 'working', 'episodic', 'semantic', 'procedural', 'social']
const typeOptions = computed(() => memoryTypes.map(value => ({ value, label: t(`memory.types.${value}`) })))
const nodeKindOptions = computed(() => (['memory', 'document'] as MemoryNodeKind[]).map(value => ({ value, label: t(`memory.kinds.${value}`) })))
const requiredRule = (value: unknown): true | string => Boolean(String(value ?? '').trim()) || t('memory.required')
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
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 8px;
  padding: 8px;
}
.memory-editor-fields > div { grid-column: 1 / -1; min-width: 0; }
.memory-editor-fields > .memory-editor-title { grid-column: 1; }
.memory-editor-fields > .memory-editor-type { grid-column: 2; }
.memory-sharing-row { display: flex; align-items: center; gap: 8px; }
.memory-sharing-field { flex: 1; min-width: 0; }
.memory-sharing-row > .q-toggle { flex-shrink: 0; }
.memory-form-access { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; align-items: start; }
.memory-form-access > * { min-width: 0; }
.memory-form-sources { line-height: 20px; overflow-wrap: anywhere; }
.memory-form-provenance :deep(.q-field__control-container) { padding-top: 14px; }
.memory-form-keywords :deep(.q-field__native) { align-content: flex-start; align-items: flex-start; }
@media (max-width: 599px) {
  .memory-form-access { grid-template-columns: minmax(0, 1fr); }
  .memory-editor-fields { grid-template-columns: minmax(0, 1fr); }
  .memory-editor-fields > .memory-editor-type { grid-column: 1; }
}
</style>
