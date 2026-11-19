<template>
  <section class="drawing-editor">
    <q-banner v-if="error" role="alert" rounded class="bg-solaire-red-light text-negative">
      {{ t(`drawingSample.${error}`) }}
      <template #action>
        <q-btn v-if="error === 'loadError'" outline color="primary" :label="tCommon('common.retry')" @click="load(source)" />
        <q-btn v-else-if="dirty" outline color="primary" :label="t('drawingSample.download')" @click="download" />
      </template>
    </q-banner>
    <DocumentToolbar v-if="source && !source.readonly" :label="t('drawingSample.name')"
      :groups="toolbarGroups" @command="toolbarCommand" />
    <div v-if="loading" class="row q-gutter-sm items-center" role="status">
      <q-spinner color="primary" /> <span>{{ t('drawingSample.loading') }}</span>
    </div>
    <div v-show="ready" class="drawing-stage">
      <canvas ref="canvas" :tabindex="editable ? 0 : -1" :aria-label="t('drawingSample.canvas')"
        :aria-description="editable ? t('drawingSample.keyboard') : undefined"
        @pointerdown="beginStroke" @pointermove="moveStroke" @pointerup="endStroke" @pointercancel="endStroke"
        @lostpointercapture="endStroke" @keydown="useKeyboard" @blur="keyboardActive = false" />
      <span v-if="keyboardActive" class="drawing-cursor" aria-hidden="true" :style="cursorStyle" />
    </div>
    <span v-if="saved" class="text-caption" role="status">{{ t('drawingSample.saved') }}</span>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QBanner, QBtn, QSpinner } from 'quasar'
import { DocumentToolbar, type DocumentContentSource, type DocumentFocusAnchor, type DocumentToolbarGroup } from '@/app/document'
import { saveBlobAsResource, solaire } from '@/core/util/facade'
import { drawingMessages } from './messages'

const { source } = defineProps<{ source?: DocumentContentSource | null }>()
const { t } = useI18n({ messages: drawingMessages })
const { t: tCommon } = useI18n({ useScope: 'global' })
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')
const ready = ref(false), loading = ref(false), saving = ref(false), saved = ref(false), dirty = ref(false)
const error = ref<'' | 'loadError' | 'saveError' | 'changed'>('')
const tool = ref<'brush' | 'eraser'>('brush'), color = ref<string>(solaire.blue.accent), size = ref(8)
const editable = computed(() => ready.value && source && !source.readonly && !saving.value && error.value !== 'changed')
type Point = { x: number; y: number }
const cursor = ref<Point>({ x: 0, y: 0 }), keyboardActive = ref(false)
let focusedPoint: Point | null = null
const cursorStyle = computed(() => ({
  left: `${100 * cursor.value.x / (canvas.value?.width || 1)}%`,
  top: `${100 * cursor.value.y / (canvas.value?.height || 1)}%`,
}))

const undoFrames: ImageData[] = []
const undoCount = ref(0)
const toolbarGroups = computed<DocumentToolbarGroup[]>(() => {
  const disabled = !editable.value
  return [
    { id: 'tools', label: t('drawingSample.tools'), commands: [
      { id: 'brush', kind: 'toggle', icon: 'brush', label: t('drawingSample.brush'), pressed: tool.value === 'brush', disabled },
      { id: 'eraser', kind: 'toggle', icon: 'backspace', label: t('drawingSample.eraser'), pressed: tool.value === 'eraser', disabled },
      { id: 'color', kind: 'color', label: t('drawingSample.color'), value: color.value, disabled },
      { id: 'size', kind: 'range', label: t('drawingSample.size'), value: size.value, min: 1, max: 48, disabled },
    ] },
    { id: 'edit', label: tCommon('richEditor.groups.editing'), commands: [
      { id: 'undo', kind: 'button', icon: 'undo', label: t('drawingSample.undo'), disabled: disabled || !undoCount.value },
      { id: 'clear', kind: 'button', icon: 'layers_clear', label: t('drawingSample.clear'), secondary: true, disabled },
      { id: 'save', kind: 'button', icon: 'save', label: t('drawingSample.save'), showLabel: true, primary: true,
        disabled: disabled || !dirty.value, busy: saving.value },
    ] },
  ]
})

function toolbarCommand(id: string, value?: string | number): void {
  if (!editable.value) return
  switch (id) {
    case 'brush':
    case 'eraser':
      tool.value = id
      break
    case 'color':
      if (typeof value === 'string') color.value = value
      break
    case 'size':
      if (typeof value === 'number') size.value = value
      break
    case 'undo':
      undo()
      break
    case 'clear':
      clear()
      break
    case 'save':
      void save()
      break
  }
}

let sourceRequest: AbortController | undefined
let saveRequest: AbortController | undefined
let pendingSave: Promise<boolean> | undefined
let autosaveTimer: ReturnType<typeof setTimeout> | undefined
let baseRevision = 0
let baseKey = ''
let writing: { pointer: number; point: Point } | undefined

function context(): CanvasRenderingContext2D | null {
  return canvas.value?.getContext('2d', { willReadFrequently: true }) ?? null
}

async function load(current?: DocumentContentSource | null): Promise<void> {
  cancelAutosave()
  sourceRequest?.abort()
  const request = new AbortController()
  sourceRequest = request
  loading.value = Boolean(current)
  ready.value = false
  error.value = ''
  if (!current) return
  try {
    const png = await current.load(request.signal)
    request.signal.throwIfAborted()
    const image = await createImageBitmap(png)
    try {
      request.signal.throwIfAborted()
      const painting = context()
      if (!painting) throw new Error('Canvas unavailable')
      painting.canvas.width = image.width
      painting.canvas.height = image.height
      painting.drawImage(image, 0, 0)
      cursor.value = { x: image.width / 2, y: image.height / 2 }
    } finally {
      image.close()
    }
    undoFrames.length = 0
    undoCount.value = 0
    focusedPoint = null
    baseRevision = current.revision
    baseKey = current.key
    dirty.value = false
    ready.value = true
  } catch {
    if (!request.signal.aborted) error.value = 'loadError'
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch(() => source?.key, key => {
  if (key === baseKey || saving.value) return
  cancelAutosave()
  if (dirty.value) error.value = 'changed'
  else void load(source)
}, { immediate: true, flush: 'post' })

function remember(painting: CanvasRenderingContext2D): void {
  const { width, height } = painting.canvas
  const limit = Math.max(1, Math.min(12, Math.floor(32 * 1024 ** 2 / (width * height * 4))))
  while (undoFrames.length >= limit) undoFrames.shift()
  undoFrames.push(painting.getImageData(0, 0, width, height))
  undoCount.value = undoFrames.length
}

function markChanged(): void {
  dirty.value = true
  saved.value = false
  error.value = ''
  if (!writing) scheduleAutosave()
}

function cancelAutosave(): void {
  clearTimeout(autosaveTimer)
  autosaveTimer = undefined
}

function scheduleAutosave(): void {
  cancelAutosave()
  autosaveTimer = setTimeout(() => { void save() }, 700)
}

function paint(painting: CanvasRenderingContext2D, from: Point, to: Point): void {
  painting.save()
  painting.globalCompositeOperation = tool.value === 'eraser' ? 'destination-out' : 'source-over'
  painting.lineWidth = size.value
  painting.lineCap = 'round'
  painting.strokeStyle = color.value
  painting.fillStyle = color.value
  painting.beginPath()
  if (from.x === to.x && from.y === to.y) {
    painting.arc(to.x, to.y, size.value / 2, 0, Math.PI * 2)
    painting.fill()
  } else {
    painting.moveTo(from.x, from.y)
    painting.lineTo(to.x, to.y)
    painting.stroke()
  }
  painting.restore()
  markChanged()
}

function point(event: PointerEvent, element: HTMLCanvasElement): Point {
  const rectangle = element.getBoundingClientRect()
  return {
    x: (event.clientX - rectangle.left) * element.width / rectangle.width,
    y: (event.clientY - rectangle.top) * element.height / rectangle.height,
  }
}

function beginStroke(event: PointerEvent): void {
  const painting = context()
  if (!editable.value || !painting || writing || event.button !== 0) return
  cancelAutosave()
  keyboardActive.value = false
  painting.canvas.setPointerCapture(event.pointerId)
  remember(painting)
  const first = point(event, painting.canvas)
  focusedPoint = first
  writing = { pointer: event.pointerId, point: first }
  paint(painting, first, first)
}

function moveStroke(event: PointerEvent): void {
  const painting = context()
  if (!editable.value || !painting || writing?.pointer !== event.pointerId) return
  const next = point(event, painting.canvas)
  focusedPoint = next
  paint(painting, writing.point, next)
  writing.point = next
}

function endStroke(event: PointerEvent): void {
  if (writing?.pointer !== event.pointerId) return
  writing = undefined
  if (editable.value && dirty.value) scheduleAutosave()
}

function useKeyboard(event: KeyboardEvent): void {
  const painting = context()
  if (!editable.value || !painting) return
  const movement: Record<string, Point> = {
    ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 },
    ArrowUp: { x: 0, y: -1 }, ArrowDown: { x: 0, y: 1 },
  }
  const delta = movement[event.key]
  if (!delta && event.key !== ' ') return
  event.preventDefault()
  keyboardActive.value = true
  if (delta) cursor.value = {
    x: Math.max(0, Math.min(painting.canvas.width - 1, cursor.value.x + delta.x * 8)),
    y: Math.max(0, Math.min(painting.canvas.height - 1, cursor.value.y + delta.y * 8)),
  }
  else { remember(painting); paint(painting, cursor.value, cursor.value) }
  focusedPoint = cursor.value
}

function undo(): void {
  const painting = context()
  if (!editable.value || !painting) return
  const frame = undoFrames.pop()
  undoCount.value = undoFrames.length
  if (!frame) return
  painting.putImageData(frame, 0, 0)
  markChanged()
}

function clear(): void {
  const painting = context()
  if (!editable.value || !painting) return
  remember(painting)
  painting.clearRect(0, 0, painting.canvas.width, painting.canvas.height)
  markChanged()
}

function png(): Promise<Blob> {
  const element = canvas.value
  if (!element) return Promise.reject(new Error('Canvas unavailable'))
  return new Promise((resolve, reject) => element.toBlob(
    blob => blob ? resolve(blob) : reject(new Error('PNG encoding failed')), 'image/png',
  ))
}

async function save(): Promise<boolean> {
  cancelAutosave()
  if (pendingSave) return pendingSave
  if (!dirty.value) return true
  const current = source
  if (!editable.value || !current || current.key !== baseKey) return false
  const request = new AbortController()
  saveRequest = request
  saving.value = true
  error.value = ''
  pendingSave = (async () => {
    try {
      const content = await png()
      request.signal.throwIfAborted()
      baseRevision = await current.save(content, baseRevision, request.signal)
      request.signal.throwIfAborted()
      dirty.value = false
      saved.value = true
      if (source?.revision === baseRevision) baseKey = source.key
      else if (source?.key !== baseKey) await load(source)
      return true
    } catch {
      if (!request.signal.aborted) error.value = source?.key === baseKey ? 'saveError' : 'changed'
      return false
    } finally {
      pendingSave = undefined
      saveRequest = undefined
      saving.value = false
    }
  })()
  return pendingSave
}

async function download(): Promise<void> {
  try {
    saveBlobAsResource(await png(), 'drawing.png')
  } catch {
    error.value = 'saveError'
  }
}

function captureFocus(): DocumentFocusAnchor | null {
  const element = canvas.value
  if (!element || !focusedPoint || !ready.value || loading.value || dirty.value || source?.key !== baseKey) return null
  return { kind: 'point', x: Math.max(0, Math.min(element.width - 1, Math.floor(focusedPoint.x))),
    y: Math.max(0, Math.min(element.height - 1, Math.floor(focusedPoint.y))) }
}

defineExpose({
  flush: save,
  captureFocus,
  discardDraft: async () => { cancelAutosave(); await pendingSave; dirty.value = false; await load(source) },
})

onBeforeUnmount(() => { cancelAutosave(); sourceRequest?.abort(); saveRequest?.abort() })
</script>

<style scoped>
.drawing-editor { display: grid; gap: 12px; }
.drawing-stage { position: relative; width: fit-content; max-width: 100%; border: 1px solid var(--solaire-gray-accent); }
.drawing-stage canvas { display: block; max-width: 100%; height: auto; background: white; touch-action: none; }
.drawing-cursor { position: absolute; width: 14px; height: 14px; border: 2px solid var(--solaire-blue-accent); border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none; }
</style>
