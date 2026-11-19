import { computed, nextTick, ref, watch } from 'vue'
import type { Ref } from 'vue'

interface Point { x: number; y: number }
interface Size { width: number; height: number }
interface Pointer extends Point { id: number; canPan: boolean }

const minZoom = .15
const maxZoom = 3
const step = 1.2

function center(first: Point, second: Point): Point {
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 }
}

function distance(first: Point, second: Point): number {
  return Math.hypot(second.x - first.x, second.y - first.y)
}

export function useMindMapViewport(canvas: Ref<HTMLElement | null>, content: Ref<HTMLElement | null>,
  toolbar: Ref<HTMLElement | null>, scrollbar: Ref<HTMLElement | null>, fullscreen: Ref<boolean>) {
  const scale = ref(1)
  const viewportWidth = ref(0)
  const stage = ref<Size>({ width: 0, height: 0 })
  const pointers = new Map<number, Pointer>()
  const panning = ref(false)
  const horizontalPosition = ref(0)
  const percentage = computed(() => Math.round(scale.value * 100))
  const inset = computed(() => viewportWidth.value / 2)
  const planeWidth = computed(() => Math.ceil(Math.max(stage.value.width * scale.value, viewportWidth.value) + 2 * inset.value))
  const horizontalLimit = computed(() => Math.max(0, planeWidth.value - viewportWidth.value))
  const horizontalThumb = computed(() => planeWidth.value ? 100 * viewportWidth.value / planeWidth.value : 100)
  const planeStyle = computed(() => ({
    width: `${planeWidth.value}px`,
    height: `${stage.value.height * scale.value}px`,
  }))
  const stageStyle = computed(() => ({
    left: `${inset.value}px`, transform: `scale(${scale.value})`,
  }))
  let pendingScroll: Point | undefined
  let vertical: HTMLElement | null = null

  function verticalContainer(surface: HTMLElement): HTMLElement | null {
    return surface.closest<HTMLElement>('.document-editor--fullscreen > .document-editor-fields, .editorial-fullscreen, .document-editor')
      ?? surface.ownerDocument.scrollingElement as HTMLElement | null
  }

  watch(fullscreen, () => { if (canvas.value) vertical = verticalContainer(canvas.value) }, { flush: 'post' })

  function verticalFrameTop(): number {
    return vertical && vertical !== vertical.ownerDocument.scrollingElement ? vertical.getBoundingClientRect().top : 0
  }

  function position(): Point {
    return pendingScroll ?? { x: canvas.value?.scrollLeft ?? 0, y: vertical?.scrollTop ?? 0 }
  }

  function syncHorizontalScroll(): void { horizontalPosition.value = canvas.value?.scrollLeft ?? 0 }

  function setHorizontalScroll(x: number): void {
    if (!canvas.value || !Number.isFinite(x)) return
    canvas.value.scrollLeft = x
    syncHorizontalScroll()
  }

  function scrollTo(target: Point): void {
    setHorizontalScroll(target.x)
    if (vertical) vertical.scrollTop = target.y
  }

  function scrollAfterLayout(target: Point): void {
    if (!pendingScroll) void nextTick(() => {
      const latest = pendingScroll
      pendingScroll = undefined
      if (latest) scrollTo(latest)
    })
    pendingScroll = target
  }

  watch([canvas, content], ([surface, tree], _, cleanup) => {
    if (!surface || !tree) return
    vertical = verticalContainer(surface)
    function measure(surface: HTMLElement, tree: HTMLElement, initialize = false): void {
      const width = surface.clientWidth
      const previous = inset.value
      const origin = position()
      const size = { width: tree.offsetWidth, height: tree.offsetHeight }
      if (size.width !== stage.value.width || size.height !== stage.value.height) stage.value = size
      if (!initialize && width === viewportWidth.value) return
      viewportWidth.value = width
      scrollAfterLayout({ x: initialize ? inset.value : origin.x + inset.value - previous, y: origin.y })
    }
    measure(surface, tree, true)
    // Measuring the tree updates the canvas size. Schedule that write outside
    // ResizeObserver delivery so folding a branch does not start a resize loop.
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (frame) return
      frame = requestAnimationFrame(() => { frame = 0; measure(surface, tree) })
    })
    observer.observe(surface)
    observer.observe(tree)
    cleanup(() => { observer.disconnect(); cancelAnimationFrame(frame); pointers.clear(); panning.value = false; pendingScroll = undefined; vertical = null })
  }, { flush: 'post' })

  function local(x: number, y: number): Point {
    return { x: x - (canvas.value?.getBoundingClientRect().left ?? 0), y: y - verticalFrameTop() }
  }

  function stageTop(): number {
    return (canvas.value?.getBoundingClientRect().top ?? 0) - verticalFrameTop() + (vertical?.scrollTop ?? 0)
  }

  function zoom(value: number, anchor: Point, destination = anchor): void {
    const bounded = Math.max(minZoom, Math.min(maxZoom, value))
    const ratio = bounded / scale.value
    const origin = position(), left = inset.value, top = stageTop()
    scale.value = bounded
    scrollAfterLayout({
      x: left + (origin.x + anchor.x - left) * ratio - destination.x,
      y: top + (origin.y + anchor.y - top) * ratio - destination.y,
    })
  }

  function zoomStep(direction: 1 | -1): void {
    const surface = canvas.value
    if (!surface) return
    const centerY = Math.min((vertical?.clientHeight ?? window.innerHeight) / 2, surface.getBoundingClientRect().bottom - verticalFrameTop())
    zoom(scale.value * step ** direction, { x: surface.clientWidth / 2, y: centerY })
  }

  function reset(): void {
    scale.value = 1
    scrollAfterLayout({ x: inset.value, y: position().y })
  }

  function fit(): void {
    const surface = canvas.value
    const { width, height } = stage.value
    if (!surface || !width || !height) return
    const toolbarHeight = toolbar.value?.offsetHeight ?? 0
    const availableHeight = (vertical?.clientHeight ?? window.innerHeight) - toolbarHeight - (scrollbar.value?.offsetHeight ?? 0)
    scale.value = Math.max(minZoom, Math.min(1, surface.clientWidth / width, availableHeight / height))
    scrollAfterLayout({
      x: inset.value + (width * scale.value - surface.clientWidth) / 2,
      y: Math.min(position().y, stageTop() - toolbarHeight),
    })
  }

  function wheel(event: WheelEvent): void {
    if (!event.ctrlKey && !event.metaKey) return
    event.preventDefault()
    const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY
    zoom(scale.value * Math.exp(-delta * .002), local(event.clientX, event.clientY))
  }

  function pointerDown(event: PointerEvent): void {
    const surface = canvas.value
    if (!surface) return
    if (event.button !== 0 || !(event.target instanceof Element) || pointers.size >= 2) return
    const point = local(event.clientX, event.clientY)
    if (point.x >= surface.clientWidth || event.clientY - surface.getBoundingClientRect().top >= surface.clientHeight) return
    const canPan = !event.target.closest('.mindmap-node')
    if (!canPan && (event.pointerType !== 'touch' || event.target.closest('input, textarea, button, a, [contenteditable]:not([contenteditable="false"])'))) return
    pointers.set(event.pointerId, { ...point, id: event.pointerId, canPan })
    if (pointers.size === 2) {
      for (const id of pointers.keys()) canvas.value?.setPointerCapture(id)
      panning.value = true
    } else if (canPan) {
      canvas.value?.setPointerCapture(event.pointerId)
      panning.value = true
      if (event.pointerType === 'mouse') event.preventDefault()
    }
  }

  function pointerMove(event: PointerEvent): void {
    const previous = pointers.get(event.pointerId)
    if (!previous) return
    const next = { ...previous, ...local(event.clientX, event.clientY) }
    pointers.set(event.pointerId, next)
    const other = [...pointers.values()].find(pointer => pointer.id !== event.pointerId)
    if (other) {
      const oldDistance = distance(previous, other)
      const ratio = oldDistance > 1 ? distance(next, other) / oldDistance : 1
      zoom(scale.value * ratio, center(previous, other), center(next, other))
    } else if (previous.canPan) {
      const origin = position()
      const target = { x: origin.x + previous.x - next.x, y: origin.y + previous.y - next.y }
      if (pendingScroll) scrollAfterLayout(target)
      else scrollTo(target)
    }
  }

  function pointerEnd(event: PointerEvent): void {
    pointers.delete(event.pointerId)
    panning.value = [...pointers.values()].some(pointer => pointer.canPan)
  }

  function reveal(element?: Element | null): void {
    const surface = canvas.value
    const frame = surface?.getBoundingClientRect()
    const box = element?.getBoundingClientRect()
    if (!surface || !frame || !box) return
    const padding = 10
    const frameTop = verticalFrameTop()
    const visibleTop = Math.max(frameTop, toolbar.value?.getBoundingClientRect().bottom ?? frameTop) + padding
    const visibleBottom = Math.min(frameTop + (vertical?.clientHeight ?? window.innerHeight), scrollbar.value?.getBoundingClientRect().top ?? Infinity) - padding
    const x = box.left < frame.left + padding ? box.left - frame.left - padding : Math.max(0, box.right - frame.left - surface.clientWidth + padding)
    const y = box.top < visibleTop || box.height > visibleBottom - visibleTop ? box.top - visibleTop : Math.max(0, box.bottom - visibleBottom)
    if (x || y) scrollTo({ x: surface.scrollLeft + x, y: (vertical?.scrollTop ?? 0) + y })
  }

  return {
    percentage, planeStyle, stageStyle, horizontalLimit, horizontalPosition, horizontalThumb,
    syncHorizontalScroll, setHorizontalScroll, panning, zoomStep, reset, fit, wheel, pointerDown, pointerMove, pointerEnd, reveal,
  }
}
