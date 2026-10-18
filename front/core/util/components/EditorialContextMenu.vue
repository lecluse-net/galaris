<template>
  <q-menu ref="menu" :target="target" :model-value="!clipped" no-parent-event no-focus no-refocus
    anchor="top middle" self="bottom middle" :offset="[0, 8]" :transition-duration="0"
    max-width="calc(100vw - 16px)" class="rich-editor editorial-context" role="presentation"
    @hide="hide" @escape-key="emit('dismiss', contextKey, true)">
    <div ref="panel" class="editorial-context-items" role="toolbar" :aria-label="label" :data-code-toolbar="code ? '' : undefined" @mousedown.prevent>
      <slot />
    </div>
  </q-menu>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
const { target, contextKey, label, code = false, refreshKey } = defineProps<{
  target: HTMLElement; contextKey: string; label: string; code?: boolean; refreshKey: string
}>()
const emit = defineEmits<{ dismiss: [key: string, restoreFocus: boolean] }>()
const menu = useTemplateRef<{ updatePosition: () => void }>('menu'), panel = useTemplateRef('panel')
const clipped = ref(false)
let observer: ResizeObserver | undefined, frame: number | undefined, disposed = false
function hide(): void { if (!clipped.value) emit('dismiss', contextKey, false) }
function refresh(): void {
  if (disposed || frame !== undefined) return
  frame = requestAnimationFrame(async () => {
    frame = undefined
    const box = target.getBoundingClientRect(), surface = target.closest('[data-editor-surface]')?.getBoundingClientRect()
    clipped.value = !target.isConnected || box.bottom <= Math.max(0, surface?.top ?? 0) || box.top >= Math.min(window.innerHeight, surface?.bottom ?? window.innerHeight)
      || box.right <= 0 || box.left >= window.innerWidth
    await nextTick()
    if (!disposed && !clipped.value) menu.value?.updatePosition()
  })
}
function focus(): void { panel.value?.querySelector<HTMLElement>('[role="combobox"], button:not([disabled])')?.focus() }
watch(() => refreshKey, async () => { await nextTick(); refresh() })
watch(panel, (value, old) => { if (old) observer?.unobserve(old); if (value) observer?.observe(value) })
onMounted(async () => {
  observer = new ResizeObserver(refresh)
  observer.observe(target)
  await nextTick()
  if (disposed) return
  if (panel.value) observer.observe(panel.value)
  window.addEventListener('scroll', refresh, { capture: true, passive: true })
  window.addEventListener('resize', refresh)
  refresh()
})
onBeforeUnmount(() => {
  disposed = true
  observer?.disconnect()
  window.removeEventListener('scroll', refresh, true)
  window.removeEventListener('resize', refresh)
  if (frame !== undefined) cancelAnimationFrame(frame)
})
defineExpose({ focus })
</script>
