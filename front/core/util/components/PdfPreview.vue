<template>
  <FullscreenPreview v-model="open" immersive interactive :viewer-label="source?.title ?? ''">
    <template #default="{ fit }">
      <iframe v-if="url" :src="url + '#view=FitH'" :title="source?.title" class="pdf-preview-frame" :class="{ 'pdf-preview-frame--fit': fit }" />
    </template>
  </FullscreenPreview>
</template>
<script setup lang="ts">
import { computed, onWatcherCleanup, ref, watch } from 'vue'
import FullscreenPreview from './FullscreenPreview.vue'
import type { PdfPreviewSource } from '../documentMedia'

const source = defineModel<PdfPreviewSource | null>({ default: null })
const open = computed({ get: () => source.value !== null, set: (value: boolean) => { if (!value) source.value = null } })
const url = ref('')
watch(source, value => {
  url.value = value ? URL.createObjectURL(value.blob) : ''
  const current = url.value
  onWatcherCleanup(() => { if (current) URL.revokeObjectURL(current) })
}, { immediate: true })
</script>
<style scoped>
.pdf-preview-frame { display: block; width: 1280px; height: 800px; border: 0; background: #fff; }
.pdf-preview-frame--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); }
</style>
