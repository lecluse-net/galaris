<template>
  <q-item clickable :dense="compact" :class="{ 'document-row--compact': compact }" :active="selectedDocumentId === entry.item.id" :disable="loading" draggable="true"
    @click.stop="emit('select', entry)" @dragstart.stop="emit('dragstart', $event, entry.item.id)" @dragend.stop="emit('dragend')">
    <q-item-section>
      <q-item-label class="row items-center no-wrap"><DocumentIcon :document-id="entry.item.id" :title="entry.item.title" :readonly="compact" size="26px" class="library-document-icon" :class="compact ? 'q-mr-xs' : 'q-mr-sm'" /><span class="ellipsis">{{ entry.item.title }}</span></q-item-label>
      <q-item-label v-if="!compact" caption class="ellipsis"><q-icon :name="entry.item.owner_agent_id !== null ? 'smart_toy' : 'person'" /> {{ entry.owner_label || t('documents.library.noOwner') }}</q-item-label>
      <q-item-label v-if="!compact" caption class="document-dates">{{ t('documents.library.dates', { created: formatDate(entry.item.created_at), updated: formatDate(entry.item.updated_at ?? entry.item.created_at) }) }}</q-item-label>
      <q-item-label v-if="!compact" caption>{{ t(`documents.types.${entry.item.document_type ?? 'html'}`) }}</q-item-label>
    </q-item-section>
    <q-item-section v-if="!compact" side><q-icon v-if="entry.item.document_type === 'dataset'" name="data_object" size="28px" :aria-label="t('documents.types.dataset')" /><DocumentThumbnail v-else :document-id="entry.item.id" :revision="entry.item.revision" :updated-at="entry.item.updated_at" /></q-item-section>
  </q-item>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { DocumentLibraryEntry } from '../types'
import DocumentIcon from './DocumentIcon.vue'
import DocumentThumbnail from './DocumentThumbnail.vue'
defineProps<{
  entry: DocumentLibraryEntry
  loading: boolean
  compact?: boolean
  selectedDocumentId: string | null
}>()
const emit = defineEmits<{ select: [entry: DocumentLibraryEntry]; dragstart: [event: DragEvent, id: string]; dragend: [] }>()
const { t, locale } = useI18n()
function formatDate(value: string): string { return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short' }).format(new Date(value)) }
</script>
<style scoped>
.library-document-icon { width: 26px; height: 24px; min-width: 26px; min-height: 24px; padding: 0; }
.document-dates { font-size: 11px; line-height: 1.4; }
.document-row--compact { min-height: 26px; padding: 2px 4px; }
</style>
