<template>
  <q-btn ref="tile" flat no-caps :ripple="false" class="file-tile" :aria-label="t('files.openItem', { name: entry.name })" @click="emit('open', entry)">
    <div class="file-tile-content">
      <div class="file-tile-preview">
        <FolderIcon v-if="entry.is_collection" size="88px" tone="orange" />
        <img v-else-if="thumbnail" class="file-tile-image" :src="thumbnail" :alt="entry.name" loading="lazy" />
        <q-icon v-else class="file-tile-image" :name="icon" size="88px" color="primary" />
      </div>
      <div class="file-tile-name">{{ entry.name }}</div>
      <div v-if="!entry.is_collection" class="file-tile-meta text-caption">{{ entry.size === null ? entry.media_type : formatFileSize(entry.size, locale) }}</div>
      <q-tooltip>{{ entry.uri }}</q-tooltip>
    </div>
  </q-btn>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { QBtn } from 'quasar'
import { FolderIcon, browserResourceKind, formatFileSize, queuePreview } from '@/core/util'
import { fileBrowserService, type FileEntry } from '../services/fileBrowserService'
import { resourceTarget } from '../presentation'

const { entry, agentId } = defineProps<{ entry: FileEntry; agentId: number }>()
const emit = defineEmits<{ open: [entry: FileEntry] }>()
const { t, locale } = useI18n()
const tile = useTemplateRef<QBtn>('tile')
const thumbnail = ref('')
let request: AbortController | undefined
let observer: IntersectionObserver | undefined
const icon = computed(() => {
  const target = resourceTarget(entry, agentId)
  if (target) return ({ task: 'task_alt', round: 'forum', voice: 'record_voice_over', document: 'description', memory: 'memory' })[target.kind] || 'description'
  const kind = browserResourceKind(entry.media_type, entry.name)
  return ({ image: 'image', pdf: 'picture_as_pdf', audio: 'audio_file', video: 'movie', html: 'html', model3d: 'view_in_ar', markdown: 'article', text: 'description' })[kind ?? 'text']
})
onMounted(() => {
  if (entry.is_collection || !entry.capabilities.includes('read')) return
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
.file-tile { width: 100%; min-width: 0; color: inherit; }
.file-tile-content { width: 100%; min-width: 0; padding: 10px 0; text-align: center; }
.file-tile-preview { height: 120px; display: grid; place-items: center; margin-bottom: 12px; }
.file-tile-preview img { width: 100%; height: 120px; object-fit: contain; }
.file-tile-image { filter: drop-shadow(0 3px 5px rgba(0, 0, 0, .14)); }
:global(body.body--dark .file-tile-image) { filter: drop-shadow(0 3px 5px rgba(0, 0, 0, .32)); }
.file-tile-name { font-weight: 400; overflow-wrap: anywhere; line-height: 1.4; }
.file-tile-meta { color: var(--solaire-gray-accent); font-weight: 400; }
</style>
