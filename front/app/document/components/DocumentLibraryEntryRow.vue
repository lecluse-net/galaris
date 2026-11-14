<template>
  <q-item clickable class="document-row" :title="entry.item.title" :dense="compact" :class="{ 'document-row--compact': compact }" :active="selected ?? selectedDocumentId === entry.item.id" :aria-selected="selected ?? selectedDocumentId === entry.item.id" :disable="loading" draggable="true"
    @click.stop="emit('select', entry, $event)" @mousedown="preventTextSelection" @dragstart.stop="startDrag" @dragend.stop="emit('dragend')">
    <slot name="toggle" />
    <q-item-section>
      <q-item-label class="row items-center no-wrap"><DocumentIcon :document-id="entry.item.id" :document-format="entry.item.document_format" :title="entry.item.title" readonly size="26px" class="library-document-icon" :class="compact ? 'q-mr-xs' : 'q-mr-sm'" /><span class="ellipsis" :title="entry.item.title">{{ entry.item.title }}</span></q-item-label>
      <q-item-label v-if="!compact" caption class="ellipsis"><q-icon :name="entry.item.owner_agent_id !== null ? 'smart_toy' : 'person'" /> {{ entry.owner_label || t('documents.library.noOwner') }}</q-item-label>
      <q-item-label v-if="!compact" caption class="document-dates">{{ t('documents.library.dates', { created: formatDate(entry.item.created_at), updated: formatDate(entry.item.updated_at ?? entry.item.created_at) }) }}</q-item-label>
    </q-item-section>
    <q-item-section v-if="!compact" side class="library-document-preview"><DocumentThumbnail class="library-document-thumbnail" :document-id="entry.item.id" :document-format="entry.item.document_format" :revision="entry.item.revision" :updated-at="entry.item.updated_at" /></q-item-section>
  </q-item>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { DocumentLibraryEntry } from '../types'
import DocumentIcon from '@/app/document/components/DocumentIcon.vue'
import DocumentThumbnail from '@/app/document/components/DocumentThumbnail.vue'
import { setDocumentDragData } from '../documentDrag'
const props = defineProps<{
  entry: DocumentLibraryEntry
  loading: boolean
  compact?: boolean
  selectedDocumentId: string | null
  selected?: boolean
}>()
const emit = defineEmits<{ select: [entry: DocumentLibraryEntry, event: Event]; dragstart: [event: DragEvent, id: string]; dragend: [] }>()
function preventTextSelection(event: MouseEvent): void {
  if (event.shiftKey || event.ctrlKey || event.metaKey) event.preventDefault()
}
function startDrag(event: DragEvent): void {
  setDocumentDragData(event, [props.entry])
  emit('dragstart', event, props.entry.item.id)
}
const { t, locale } = useI18n()
function formatDate(value: string): string { return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short' }).format(new Date(value)) }
</script>
<style scoped>
.document-row { padding-left: 4px; padding-right: 1px; }
.document-row[aria-selected="true"] { background: var(--solaire-blue-light); }
body.body--dark .document-row[aria-selected="true"] { background: var(--solaire-blue-dark); }
.library-document-icon { width: 26px; height: 24px; min-width: 26px; min-height: 24px; padding: 0; }
.library-document-preview { position: relative; align-self: stretch; width: 124px; min-width: 124px; padding-left: 4px; }
.library-document-preview .library-document-thumbnail { position: absolute; top: -4px; right: 0; bottom: -4px; width: 120px; height: auto; }
.document-dates { font-size: 11px; line-height: 1.4; }
.document-row--compact { min-height: 26px; padding: 0; }
</style>
