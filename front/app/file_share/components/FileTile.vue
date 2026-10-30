<template>
  <div class="file-tile-container" :class="{ 'file-tile-container--selectable': selectable }">
  <q-btn ref="tile" flat no-caps :ripple="false" :padding="selectable ? '0 16px' : undefined" class="file-tile" :class="{ 'file-tile--compact': compact, 'file-tile--selected': selected }" :aria-pressed="selectable && !entry.is_collection ? selected : undefined" :aria-label="t(selectable && !entry.is_collection ? 'files.selectItem' : 'files.openItem', { name: displayName })" @click="emit('open', entry, $event)" @dblclick="emit('activate', entry)">
    <div class="file-tile-content">
      <div class="file-tile-preview">
        <q-icon v-if="/^[a-z][a-z0-9+.-]*:\/\/$/.test(entry.uri)" name="storage" size="var(--file-icon-size)" color="primary" />
        <LibraryIcon v-else-if="documentFolderId(entry.uri)" :icon="typeof entry.metadata?.icon === 'string' ? entry.metadata.icon : null" size="var(--file-icon-size)" />
        <q-icon v-else-if="isSkillPackage(entry)" name="psychology" size="var(--file-icon-size)" color="primary" />
        <FolderIcon v-else-if="entry.is_collection" size="var(--file-icon-size)" />
        <WorkingDocumentThumbnail v-else-if="documentId && entry.capabilities.includes('read')" class="file-tile-document" :document-id="documentId" :agent-id="agentId" :updated-at="entry.modified_at" />
        <ResourceThumbnail v-else-if="process || resourceAgent !== null" :uri="entry.uri" :agent-id="selectable ? null : agentId" :title="displayName" />
        <img v-else-if="thumbnail" class="file-tile-image" :src="thumbnail" :alt="entry.name" loading="lazy" />
        <q-icon v-else class="file-tile-image" :name="icon" size="var(--file-icon-size)" color="primary" />
      </div>
      <div class="file-tile-name">{{ displayName }}</div>
      <div v-if="!entry.is_collection" class="file-tile-meta text-caption">{{ entry.size === null ? entry.media_type : formatFileSize(entry.size, locale) }}</div>
      <q-tooltip>{{ entry.uri }}</q-tooltip>
    </div>
  </q-btn>
  <div v-if="selectable" class="file-tile-actions">
  <q-btn v-if="!entry.is_collection && entry.capabilities.includes('read') && browserResourceKind(entry.media_type, entry.name)"
    flat round dense color="primary" icon="visibility"
    :aria-label="t('files.previewItem', { name: displayName })" @click="emit('preview', entry)">
    <q-tooltip>{{ t('files.previewItem', { name: displayName }) }}</q-tooltip>
  </q-btn>
  <q-checkbox dense size="md" color="primary" :model-value="selected"
    :disable="!entry.is_collection && !entry.capabilities.includes('read')" :aria-label="t('files.selectItem', { name: displayName })"
    @update:model-value="(_value, event) => emit('select', entry, event)" />
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { QBtn } from 'quasar'
import { FolderIcon, LibraryIcon, documentFolderId, WorkingDocumentThumbnail, ResourceThumbnail, browserResourceKind, formatFileSize, queuePreview } from '@/core/util'
import { agentResourceId } from '@/app/agent'
import { fileBrowserService, type FileEntry } from '../services/fileBrowserService'
import { resourceTarget, collectionLabel, isSkillPackage, executionResourceLabel } from '../presentation'

const { entry, agentId, compact = false, selectable = false, selected = false } = defineProps<{ entry: FileEntry; agentId: number; compact?: boolean; selectable?: boolean; selected?: boolean }>()
const emit = defineEmits<{ open: [entry: FileEntry, event: Event]; activate: [entry: FileEntry]; select: [entry: FileEntry, event: Event]; preview: [entry: FileEntry] }>()
const { t, locale } = useI18n()
const tile = useTemplateRef<QBtn>('tile')
const thumbnail = ref('')
const documentId = computed(() => /^document:\/\/([^/]+)$/.exec(entry.uri)?.[1] ?? null)
const process = computed(() => ['process', 'process_run'].includes(resourceTarget(entry, agentId)?.kind ?? ''))
const resourceAgent = computed(() => agentResourceId(entry.uri))
const displayName = computed(() => executionResourceLabel(entry, locale.value) ?? collectionLabel(entry.uri, t) ?? ((process.value || resourceAgent.value !== null || entry.uri.startsWith('galaris://code/')) && typeof entry.metadata?.label === 'string' ? entry.metadata.label : entry.name))
let request: AbortController | undefined
let observer: IntersectionObserver | undefined
const icon = computed(() => {
  const target = resourceTarget(entry, agentId)
  if (target) return ({ goal: 'flag_circle', task: 'task_alt', round: 'forum', voice: 'record_voice_over', document: 'description', dataset: 'data_object', memory: 'memory' })[target.kind] || 'description'
  const kind = browserResourceKind(entry.media_type, entry.name)
  return ({ image: 'image', pdf: 'picture_as_pdf', audio: 'audio_file', video: 'movie', html: 'html', model3d: 'view_in_ar', markdown: 'article', text: 'description' })[kind ?? 'text']
})
onMounted(() => {
  if (entry.is_collection || documentId.value || resourceAgent.value !== null || !entry.capabilities.includes('read')) return
  const target = resourceTarget(entry, agentId)
  if (target && target.kind !== 'document') return
  if (entry.media_type.startsWith('audio/')) return
  observer = new IntersectionObserver(entries => {
    if (!entries.some(value => value.isIntersecting)) {
      request?.abort(); request = undefined
      if (thumbnail.value) { URL.revokeObjectURL(thumbnail.value); thumbnail.value = '' }
      return
    }
    if (request || thumbnail.value) return
    const controller = new AbortController(); request = controller
    void queuePreview(() => fileBrowserService.thumbnail(agentId, entry.uri, controller.signal), controller.signal)
      .then(blob => { if (!controller.signal.aborted) thumbnail.value = URL.createObjectURL(blob) })
      .catch(() => { /* A missing thumbnail keeps the file icon and never prevents opening. */ })
  }, { rootMargin: '100px' })
  if (tile.value?.$el instanceof HTMLElement) observer.observe(tile.value.$el)
})
onBeforeUnmount(() => { request?.abort(); observer?.disconnect(); if (thumbnail.value) URL.revokeObjectURL(thumbnail.value) })
</script>

<style scoped>
.file-tile-container { position: relative; min-width: 0; }
.file-tile-container--selectable { display: flex; flex-direction: column; gap: 1px; }
.file-tile { --file-icon-size: 88px; --file-preview-height: 96px; width: 100%; min-width: 0; color: inherit; }
.file-tile-content { width: 100%; min-width: 0; padding: 6px 0; text-align: center; }
.file-tile-preview { height: var(--file-preview-height); display: grid; place-items: center; margin-bottom: 2px; }
.file-tile-preview img { width: 100%; height: var(--file-preview-height); object-fit: contain; }
.file-tile-preview .file-tile-document { width: 100%; height: 100%; }
.file-tile-image { filter: drop-shadow(0 3px 5px rgba(0, 0, 0, .14)); }
:global(body.body--dark .file-tile-image) { filter: drop-shadow(0 3px 5px rgba(0, 0, 0, .32)); }
.file-tile-name { font-weight: 400; overflow-wrap: anywhere; line-height: 1.4; }
.file-tile-meta { color: var(--solaire-gray-accent); font-weight: 400; }
.file-tile--compact { --file-icon-size: 48px; }
.file-tile--compact .file-tile-content { padding: 4px 0; }
.file-tile--compact .file-tile-preview { height: 48px; }
.file-tile--compact .file-tile-preview :deep(svg), .file-tile--compact .file-tile-preview :deep(img) { max-height: 48px; }
.file-tile--compact .file-tile-preview :deep(.q-icon) { font-size: 48px !important; }
.file-tile--compact .file-tile-name { font-size: 12px; }
.file-tile--compact .file-tile-meta { display: none; }
.file-tile-actions { order: -1; display: flex; justify-content: flex-end; align-items: center; gap: 4px; min-height: 32px; padding: 0 4px; }
.file-tile-container--selectable .file-tile--compact .file-tile-content { padding: 0; }
.file-tile--selected { background: var(--solaire-blue-light); color: var(--solaire-blue-accent); }
:global(body.body--dark .file-tile--selected) { background: var(--solaire-blue-dark); }
@media (max-width: 1023px) {
  .file-tile:not(.file-tile--compact) { --file-icon-size: 64px; --file-preview-height: 68px; }
}
</style>
