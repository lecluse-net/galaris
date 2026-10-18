<template>
  <FullscreenPreview v-model="open" immersive interactive :viewer-label="title">
    <template #default="{ fit }">
      <div v-if="failed" role="alert" class="q-pa-lg bg-white text-dark">
        {{ t('richEditor.unavailable') }}
        <q-btn outline :label="t('common.retry')" @click="prepare" />
      </div>
      <q-spinner v-else-if="!html" color="primary" size="48px" />
      <iframe v-else :srcdoc="html" sandbox="" referrerpolicy="no-referrer" :title="title"
        class="rendered-object-preview" :class="{ 'rendered-object-preview--fit': fit }" />
    </template>
  </FullscreenPreview>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import FullscreenPreview from './FullscreenPreview.vue'
import { preparePortableDocumentSnapshot } from '../documentSnapshot'
import type { RenderedDocumentCapture } from '../renderedDocument'

const { source, language, capture, title } = defineProps<{
  source: string; language: string; capture: RenderedDocumentCapture; title: string
}>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const open = ref(true), html = ref(''), failed = ref(false)
let controller: AbortController | undefined
async function prepare(): Promise<void> {
  controller?.abort()
  const pending = new AbortController(); controller = pending
  failed.value = false; html.value = ''
  const pre = document.createElement('pre'), code = document.createElement('code')
  code.className = 'language-' + language; code.textContent = source; pre.append(code)
  try {
    const snapshot = await preparePortableDocumentSnapshot(pre.outerHTML, title, pending.signal,
      undefined, () => capture(pending.signal))
    if (!pending.signal.aborted) html.value = snapshot
  } catch { if (!pending.signal.aborted) failed.value = true }
}
watch(open, value => { if (!value) { controller?.abort(); emit('close') } })
onMounted(prepare)
onBeforeUnmount(() => controller?.abort())
</script>
<style scoped>
.rendered-object-preview { display: block; box-sizing: border-box; width: 960px; height: 800px; padding-top: 72px; border: 0; background: #fff; }
.rendered-object-preview--fit { width: 100vw; height: var(--galaris-preview-height, 100dvh); }
</style>
