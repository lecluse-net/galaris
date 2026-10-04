<template>
  <div ref="surface" class="audio-resource-player" :aria-busy="loading">
    <audio controls preload="metadata" :src="url || undefined" :aria-label="source.name" @error="failed = true" />
    <q-spinner v-if="loading" color="primary" size="24px" />
    <q-btn v-else-if="failed" flat dense no-caps :label="t('richEditor.resources.retryMedia')" @click="loadAudio" />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { queuePreview } from '../previewQueue'

const { source } = defineProps<{
  source: { key: string; name: string; load: (signal: AbortSignal) => Promise<Blob> }
}>()
const { t } = useI18n()
const surface = useTemplateRef<HTMLDivElement>('surface')
const url = ref<string | null>(null)
const loading = ref(false)
const failed = ref(false)
let visible = false
let observer: IntersectionObserver | undefined
let controller: AbortController | undefined

function clear(): void {
  controller?.abort()
  controller = undefined
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = null
  loading.value = false
  failed.value = false
}

async function loadAudio(): Promise<void> {
  if (!visible || loading.value) return
  clear()
  const current = new AbortController()
  const currentSource = source
  controller = current
  loading.value = true
  try {
    const blob = await queuePreview(() => currentSource.load(current.signal), current.signal)
    if (!current.signal.aborted) url.value = URL.createObjectURL(blob)
  } catch {
    if (!current.signal.aborted) failed.value = true
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => source.key, () => { clear(); void loadAudio() })
onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return
    visible = true
    observer?.disconnect()
    void loadAudio()
  }, { rootMargin: '160px' })
  if (surface.value) observer.observe(surface.value)
})
onBeforeUnmount(() => { observer?.disconnect(); clear() })
</script>

<style scoped>
.audio-resource-player { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px; }
.audio-resource-player audio { display: block; width: 100%; min-width: 0; }
</style>
