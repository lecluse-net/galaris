<template>
  <div ref="surface" class="timeline-window" :class="{ 'timeline-window--virtual': virtualized }"
    :style="virtualized ? { height: `${offsets.at(-1)}px` } : undefined" role="region" tabindex="0"
    @focusin="scheduleUpdate" @focusout="scheduleUpdate" @play.capture="scheduleUpdate"
    @pause.capture="scheduleUpdate" @ended.capture="scheduleUpdate" @keydown="onKeydown">
    <div v-for="{ item, index } in renderedItems" :key="`${scope}:${item.key}`"
      :ref="element => setRowElement(item.key, element)" :data-timeline-key="item.key"
      class="timeline-window-row" :style="virtualized ? { position: 'absolute', top: `${offsets[index]}px`, left: 0, right: 0 } : undefined">
      <slot :entry="item" />
    </div>
  </div>
</template>

<script setup lang="ts" generic="T extends { key: string }">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch, type ComponentPublicInstance } from 'vue'

const { items, scope, retain } = defineProps<{ items: readonly T[]; scope: string; retain?: (item: T) => boolean }>()
defineSlots<{ default(props: { entry: T }): unknown }>()
const emit = defineEmits<{ rendered: []; navigate: [] }>()
const surface = useTemplateRef<HTMLElement>('surface')
const virtualized = computed(() => items.length > 150)
const measured = new Map<string, number>()
const rows = new Map<string, HTMLElement>()
const measurementRevision = ref(0)
const bounds = ref({ top: 0, bottom: 1000, height: 1000 })
const pinned = ref(new Set<string>())
const restoringRows = ref(new Set<string>())
const nativeSearch = ref(false)
let target: HTMLElement | Window | null = null
let observer: ResizeObserver | null = null
let updateFrame: number | null = null
let restoreFrame: number | null = null
let width = 0
let generation = 0
type Anchor = { key: string; offset: number } | { bottom: true }
let pendingAnchor: Anchor | null = null
let readingAnchor: Anchor | null = null

const offsets = computed(() => {
  void measurementRevision.value
  const result = [0]
  for (const item of items) result.push(result.at(-1)! + (measured.get(item.key) ?? 150))
  return result
})

function indexAt(position: number): number {
  const positions = offsets.value
  let low = 0, high = items.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (positions[middle + 1]! <= position) low = middle + 1
    else high = middle
  }
  return low
}

const renderedItems = computed(() => {
  const from = indexAt(Math.max(0, bounds.value.top - bounds.value.height))
  const to = Math.min(items.length, indexAt(bounds.value.bottom + bounds.value.height) + 1)
  return items.flatMap((item, index) => !virtualized.value || nativeSearch.value
    || (index >= from && index < to) || pinned.value.has(item.key)
    || restoringRows.value.has(item.key) || retain?.(item)
    ? [{ item, index }] : [])
})

function findTarget(): HTMLElement | Window {
  let element = surface.value?.parentElement
  while (element) {
    // overflow-x: hidden can compute overflow-y: auto without making a scroller.
    if (element.classList.contains('q-scrollarea__container')
      || (/(auto|scroll)/.test(getComputedStyle(element).overflowY) && element.scrollHeight > element.clientHeight + 1)) return element
    element = element.parentElement
  }
  return window
}

function viewport(): { top: number; height: number } {
  if (target instanceof HTMLElement) return { top: target.getBoundingClientRect().top + target.clientTop, height: target.clientHeight }
  return { top: 0, height: window.innerHeight }
}

function scrollPosition(): number { return target instanceof HTMLElement ? target.scrollTop : window.scrollY }
function scrollHeight(): number { return target instanceof HTMLElement ? target.scrollHeight : document.documentElement.scrollHeight }
function setScrollPosition(top: number): void {
  if (target instanceof HTMLElement) target.scrollTop = top
  else window.scrollTo({ top, behavior: 'instant' })
}

function captureAnchor(): Anchor | null {
  if (!surface.value || !target) return null
  const view = viewport()
  if (scrollHeight() - view.height - scrollPosition() <= 48) return { bottom: true }
  let crossing: Anchor | null = null
  for (const item of items) {
    const row = rows.get(item.key)
    if (!row) continue
    const rect = row.getBoundingClientRect()
    if (rect.top >= view.top && rect.top < view.top + view.height) return { key: item.key, offset: rect.top - view.top }
    if (rect.top < view.top && rect.bottom > view.top) crossing = { key: item.key, offset: rect.top - view.top }
  }
  return crossing
}

function cancelRestore(): void {
  pendingAnchor = null
  restoringRows.value = new Set()
  if (restoreFrame !== null) cancelAnimationFrame(restoreFrame)
  restoreFrame = null
}

function preserveAnchor(anchor: Anchor | null): void {
  if (!anchor || pendingAnchor || nativeSearch.value) return
  pendingAnchor = anchor
  // Keep the whole reading window intact while inserted rows change offsets.
  restoringRows.value = new Set([...rows.keys(), ...('key' in anchor ? [anchor.key] : [])])
  const currentGeneration = generation
  void nextTick().then(() => {
    if (currentGeneration !== generation || pendingAnchor !== anchor) return
    restoreFrame = requestAnimationFrame(() => {
      restoreFrame = null
      if (pendingAnchor !== anchor) return
      if ('bottom' in anchor) setScrollPosition(scrollHeight() - viewport().height)
      else {
        const row = rows.get(anchor.key)
        if (row) setScrollPosition(scrollPosition() + row.getBoundingClientRect().top - viewport().top - anchor.offset)
      }
      // Move the rendered range before releasing the retained anchor; otherwise
      // one frame without visible rows can lose subsequent height corrections.
      update()
      readingAnchor = anchor
      pendingAnchor = null
      restoringRows.value = new Set()
      scheduleUpdate()
    })
  })
}

function update(): void {
  if (!surface.value || !target) return
  const view = viewport()
  const top = view.top - surface.value.getBoundingClientRect().top
  const bottom = top + view.height
  const height = Math.max(view.height, 200)
  if (bounds.value.top !== top || bounds.value.bottom !== bottom || bounds.value.height !== height) bounds.value = { top, bottom, height }
  const selection = window.getSelection()
  const range = selection && !selection.isCollapsed && selection.rangeCount ? selection.getRangeAt(0) : null
  const overlay = [...document.querySelectorAll('[role="dialog"], [role="menu"], [role="listbox"]')]
    .some(element => !element.contains(surface.value))
  const keep = new Set<string>()
  for (const [key, row] of rows) {
    if (overlay || row.contains(document.activeElement) || row.querySelector('[aria-expanded="true"]')
      || (range && range.intersectsNode(row))
      || [...row.querySelectorAll<HTMLMediaElement>('audio, video')].some(media => !media.paused && !media.ended)) keep.add(key)
  }
  if (keep.size !== pinned.value.size || [...keep].some(key => !pinned.value.has(key))) pinned.value = keep
  if (!pendingAnchor && Math.abs(surface.value.getBoundingClientRect().width - width) <= 1) readingAnchor = captureAnchor()
}

function scheduleUpdate(): void {
  if (updateFrame !== null) return
  updateFrame = requestAnimationFrame(() => { updateFrame = null; update() })
}

function onScroll(): void {
  if (!pendingAnchor) readingAnchor = captureAnchor()
  scheduleUpdate()
}
function onUserScroll(): void { cancelRestore(); readingAnchor = null; scheduleUpdate() }
function onPointerDown(): void { nativeSearch.value = false; cancelRestore(); scheduleUpdate() }
function onFind(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && surface.value?.getBoundingClientRect().width) {
    // Let the browser's normal Find see every loaded message.
    nativeSearch.value = true
    cancelRestore()
  } else if (event.key === 'Escape') { nativeSearch.value = false; scheduleUpdate() }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
  const element = event.target
  if (element instanceof HTMLElement && (element.isContentEditable || element.closest('input, textarea, select, button, a, [role="button"]'))) return
  const position = scrollPosition()
  const page = Math.max(40, viewport().height - 48)
  const positions: Record<string, number> = { Home: 0, End: scrollHeight(), PageUp: position - page, PageDown: position + page,
    ArrowUp: position - 40, ArrowDown: position + 40, ' ': position + (event.shiftKey ? -page : page) }
  const next = positions[event.key]
  if (next === undefined) return
  event.preventDefault()
  cancelRestore()
  readingAnchor = null
  emit('navigate')
  setScrollPosition(next)
  scheduleUpdate()
}

function setRowElement(key: string, element: Element | ComponentPublicInstance | null): void {
  const previous = rows.get(key)
  if (previous === element) return
  if (previous) observer?.unobserve(previous)
  if (element instanceof HTMLElement) { rows.set(key, element); observer?.observe(element) }
  else rows.delete(key)
}

const keys = computed(() => items.map(item => item.key).join('\0'))
watch(keys, () => {
  preserveAnchor(captureAnchor())
  const currentKeys = new Set(items.map(item => item.key))
  for (const key of measured.keys()) if (!currentKeys.has(key)) measured.delete(key)
  measurementRevision.value++
  scheduleUpdate()
}, { flush: 'pre' })
watch(() => scope, () => {
  generation++
  cancelRestore()
  measured.clear(); measurementRevision.value++
  readingAnchor = null
  pinned.value = new Set(); nativeSearch.value = false
  scheduleUpdate()
}, { flush: 'pre' })
const renderedKeys = computed(() => renderedItems.value.map(entry => entry.item.key).join('\0'))
watch(renderedKeys, async () => { await nextTick(); emit('rendered') }, { flush: 'post' })

onMounted(() => {
  target = findTarget()
  update()
  observer = new ResizeObserver(() => {
    const anchor = pendingAnchor ?? readingAnchor ?? captureAnchor()
    let changed = bounds.value.height !== Math.max(viewport().height, 200)
    const newWidth = surface.value?.getBoundingClientRect().width ?? 0
    if (newWidth > 0 && Math.abs(newWidth - width) > 1) { width = newWidth; measured.clear(); changed = true }
    for (const [key, row] of rows) {
      const height = Math.ceil(row.getBoundingClientRect().height)
      if (key && height > 0 && measured.get(key) !== height) { measured.set(key, height); changed = true }
    }
    if (changed) {
      if (virtualized.value) preserveAnchor(anchor)
      measurementRevision.value++
    }
    scheduleUpdate()
  })
  if (surface.value) observer.observe(surface.value)
  if (target instanceof HTMLElement) observer.observe(target)
  for (const row of rows.values()) observer.observe(row)
  target.addEventListener('scroll', onScroll, { passive: true })
  target.addEventListener('wheel', onUserScroll, { passive: true })
  target.addEventListener('touchstart', onUserScroll, { passive: true })
  document.addEventListener('selectionchange', scheduleUpdate)
  document.addEventListener('pointerdown', onPointerDown, true)
  document.addEventListener('keydown', onFind)
})
onBeforeUnmount(() => {
  generation++
  cancelRestore()
  if (updateFrame !== null) cancelAnimationFrame(updateFrame)
  observer?.disconnect()
  target?.removeEventListener('scroll', onScroll)
  target?.removeEventListener('wheel', onUserScroll)
  target?.removeEventListener('touchstart', onUserScroll)
  document.removeEventListener('selectionchange', scheduleUpdate)
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('keydown', onFind)
})
</script>

<style scoped>
.timeline-window { position: relative; min-width: 0; outline-offset: 2px; }
.timeline-window--virtual { overflow-anchor: none; }
.timeline-window-row { display: flow-root; min-width: 0; }
</style>
