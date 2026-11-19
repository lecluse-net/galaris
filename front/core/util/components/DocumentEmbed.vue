<template>
  <DocumentReferenceToolbar v-if="toolbar" v-bind="$attrs" mode="embed"><slot /></DocumentReferenceToolbar>
  <div v-else-if="display === 'embed'" ref="viewport" class="document-reference-reader"
    :class="{ 'document-reference-sized': size }" :style="size && {
      width: size.width + 'px', height: size.height + 'px',
      '--document-embed-height': `min(${size.height}px, 90dvh)`,
    }">
    <div class="document-reference-viewport">
      <slot v-if="visible"><ResourceEmbed v-bind="$attrs" display="embed" /></slot>
    </div>
    <q-btn v-if="visible && resize" flat dense icon="south_east" size="sm" class="document-reference-resize" draggable="false"
      :aria-label="t('richEditor.resources.resizeEmbed')" aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
      @pointerdown.stop="startResize" @pointermove="moveResize" @pointerup="finishResize" @lostpointercapture="cancelResize"
      @dragstart.stop.prevent @click.stop @keydown.stop="resizeWithKeyboard">
      <q-tooltip>{{ t('richEditor.resources.resizeEmbed') }}</q-tooltip>
    </q-btn>
  </div>
  <slot v-else><ResourceEmbed v-bind="$attrs" :display="display" /></slot>
</template>
<script setup lang="ts">
import { computed, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { maxDocumentEmbedSize, parseDocumentEmbedSize, type DocumentEmbedSize } from '../documentReference'
import DocumentReferenceToolbar from './DocumentReferenceToolbar.vue'
import { ResourceEmbed } from '../resourceEmbed'

defineOptions({ inheritAttrs: false })
const { display = 'embed', reference, resize } = defineProps<{
  toolbar?: boolean; display?: 'legacy' | 'embed'; reference?: HTMLElement
  resize?: (size: DocumentEmbedSize) => void
}>()
const { t } = useI18n()
const viewport = useTemplateRef('viewport'), visible = ref(false)
const savedSize = shallowRef<DocumentEmbedSize>(), draft = shallowRef<DocumentEmbedSize>()
const size = computed(() => draft.value ?? savedSize.value)
let drag: { id: number; x: number; y: number; width: number; height: number; scaleX: number; scaleY: number } | undefined

watch(() => reference, (element, _, cleanup) => {
  function read(): void {
    savedSize.value = parseDocumentEmbedSize(element?.dataset.resourceSize)
    if (!drag) draft.value = undefined
  }
  read()
  if (!element) return
  const observer = new MutationObserver(read)
  observer.observe(element, { attributeFilter: ['data-resource-size'] })
  cleanup(() => observer.disconnect())
}, { immediate: true })

function dimension(value: number, minimum: number): number {
  return Math.min(maxDocumentEmbedSize, Math.max(minimum, Math.round(value)))
}
function startResize(event: PointerEvent): void {
  const frame = viewport.value, handle = event.currentTarget
  if (event.button !== 0 || drag || !frame || !(handle instanceof HTMLElement)) return
  const bounds = frame.getBoundingClientRect()
  const { offsetWidth: width, offsetHeight: height } = frame
  if (!width || !height || !bounds.width || !bounds.height) return
  // Pointer capture alone does not suppress an ancestor's native block drag.
  event.preventDefault()
  handle.setPointerCapture(event.pointerId)
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY, width, height, scaleX: bounds.width / width, scaleY: bounds.height / height }
}
function moveResize(event: PointerEvent): void {
  if (drag?.id !== event.pointerId) return
  const dx = (event.clientX - drag.x) / drag.scaleX
  const dy = (event.clientY - drag.y) / drag.scaleY
  draft.value = {
    width: dx ? dimension(drag.width + dx, 128) : savedSize.value?.width ?? dimension(drag.width, 1),
    height: dy ? dimension(drag.height + dy, 64) : savedSize.value?.height ?? dimension(drag.height, 1),
  }
}
function finishResize(event: PointerEvent): void {
  if (drag?.id !== event.pointerId) return
  drag = undefined
  if (draft.value) resize?.(draft.value)
  draft.value = undefined
}
function cancelResize(event: PointerEvent): void {
  if (drag?.id !== event.pointerId) return
  drag = undefined
  draft.value = undefined
}
function resizeWithKeyboard(event: KeyboardEvent): void {
  const frame = viewport.value
  if (!frame || drag || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  event.preventDefault()
  const horizontal = event.key === 'ArrowLeft' || event.key === 'ArrowRight'
  resize?.({
    width: horizontal ? dimension(frame.offsetWidth + (event.key === 'ArrowLeft' ? -24 : 24), 128) : savedSize.value?.width ?? dimension(frame.offsetWidth, 1),
    height: horizontal ? savedSize.value?.height ?? dimension(frame.offsetHeight, 1) : dimension(frame.offsetHeight + (event.key === 'ArrowUp' ? -24 : 24), 64),
  })
}

watch(viewport, (element, _, cleanup) => {
  if (!element) return
  if (typeof IntersectionObserver === 'undefined') { visible.value = true; return }
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { visible.value = true; observer.disconnect() }
  }, { rootMargin: '200px' })
  observer.observe(element)
  cleanup(() => observer.disconnect())
}, { flush: 'post' })
</script>
<style scoped>
.document-reference-reader {
  --document-embed-height: initial;
  position: relative;
  width: var(--document-embed-width, 85%);
  max-width: 100%;
  min-height: 1px;
}
.document-reference-reader:has(> .document-reference-viewport > .document-resource-embed > .document-text-embed) {
  width: var(--document-text-embed-width, min(32rem, 85%));
}
.document-reference-reader:has(> .document-reference-viewport > .process-preview) {
  width: var(--document-embed-width, 100%);
}
.document-reference-sized { max-height: 90dvh; }
.document-reference-sized > .document-reference-viewport {
  height: 100%;
  overflow: auto;
  overscroll-behavior: contain;
  pointer-events: auto;
  touch-action: pan-x pan-y;
}
.document-reference-sized :deep(.document-reference-viewport > .document-resource-embed) { overflow: visible; }
.document-reference-resize {
  position: absolute;
  inset: auto 2px 2px auto;
  min-width: 24px;
  min-height: 24px;
  cursor: nwse-resize;
  touch-action: none;
  pointer-events: auto;
  background: var(--rich-editor-toolbar);
}
</style>
