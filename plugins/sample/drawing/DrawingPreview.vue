<template>
  <q-spinner v-if="loading" color="primary" :aria-label="t('drawingSample.loading')" />
  <q-banner v-else-if="failed" role="alert">{{ t('drawingSample.loadError') }}</q-banner>
  <img v-else-if="url" class="drawing-preview" :src="url" :alt="t('drawingSample.preview')" />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QBanner, QSpinner } from 'quasar'
import type { DocumentContentSource } from '@/app/document'
import { drawingMessages } from './messages'

const { source } = defineProps<{ source?: DocumentContentSource | null }>()
const { t } = useI18n({ messages: drawingMessages })
const url = ref(''), loading = ref(false), failed = ref(false)

watch(() => source?.key, async (_, __, onCleanup) => {
  const current = source
  const request = new AbortController()
  onCleanup(() => {
    request.abort()
    if (url.value) URL.revokeObjectURL(url.value)
    url.value = ''
  })
  failed.value = false
  loading.value = Boolean(current)
  if (!current) return
  try {
    const png = await current.load(request.signal)
    if (!request.signal.aborted) url.value = URL.createObjectURL(png)
  } catch {
    if (!request.signal.aborted) failed.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.drawing-preview { display: block; max-width: 100%; max-height: 60vh; object-fit: contain; }
</style>
