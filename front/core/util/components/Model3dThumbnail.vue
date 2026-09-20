<template>
  <span ref="surface" class="model3d-thumbnail" :aria-busy="loading">
    <img v-if="url" :src="url" :alt="source.name" />
    <q-spinner v-else-if="loading" color="primary" size="28px" />
    <span v-else class="model3d-thumbnail__fallback" :title="error ? t(`model3d.errors.${error}`) : source.name">
      <q-icon name="view_in_ar" size="32px" />
      <span v-if="error">{{ t('model3d.previewUnavailable') }}</span>
    </span>
    <span class="model3d-thumbnail__badge">{{ t('model3d.badge') }}</span>
  </span>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Model3dError } from '../model3d'
import type { Model3dSource } from '../model3d'

const { source } = defineProps<{ source: Model3dSource }>()
const { t } = useI18n()
const surface = useTemplateRef<HTMLSpanElement>('surface')
const loading = ref(false)
const error = ref<string | null>(null)
const url = ref<string | null>(null)
let observer: IntersectionObserver | undefined
let controller: AbortController | undefined
let visible = false

function clear(): void {
  controller?.abort()
  controller = undefined
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = null
  error.value = null
  loading.value = false
}

async function generate(): Promise<void> {
  if (!visible || controller) return
  const current = new AbortController()
  controller = current
  const currentSource = source
  loading.value = true
  try {
    const { createModelThumbnail } = await import('../model3dRuntime')
    current.signal.throwIfAborted()
    const blob = await createModelThumbnail(currentSource, current.signal)
    if (!current.signal.aborted) url.value = URL.createObjectURL(blob)
  } catch (cause) {
    if (!current.signal.aborted) error.value = cause instanceof Model3dError ? cause.code : 'invalid'
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => source.key, () => { clear(); void generate() })
onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return
    visible = true
    observer?.disconnect()
    void generate()
  }, { rootMargin: '160px' })
  if (surface.value) observer.observe(surface.value)
})
onBeforeUnmount(() => { observer?.disconnect(); clear() })
</script>

<style scoped>
.model3d-thumbnail { position: relative; display: flex; width: 100%; height: 100%; min-height: 86px; align-items: center; justify-content: center; overflow: hidden; color: #356493; background: #e9eef5; }
.model3d-thumbnail img { display: block; width: 100%; height: 100%; object-fit: contain; }
.model3d-thumbnail__badge { position: absolute; right: 6px; bottom: 6px; padding: 2px 5px; border-radius: 4px; color: #fff; background: #244564; font-size: 10px; }
.model3d-thumbnail__fallback { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px; font-size: 11px; }
</style>
